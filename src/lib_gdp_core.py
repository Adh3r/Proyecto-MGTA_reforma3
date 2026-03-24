# =============================================================================
# src/lib_gdp_core.py
# FASE 2: Motor de simulación del Ground Delay Program (GDP).
#
# Este módulo es el núcleo matemático del proyecto. Recibe los vuelos limpios
# de la Fase 1 y ejecuta toda la lógica del GDP paso a paso.
#
# FLUJO COMPLETO (en orden de ejecución):
#   1. simular_curvas_newell()          → ¿Cuándo y cuánto colapsa el aeropuerto?
#   2. etiquetar_vuelos_gdp()           → ¿A qué vuelos podemos regular?
#   3. asignar_slots_rbs()              → ¿A qué hora aterriza cada vuelo regulado?
#   4. calcular_delays()                → ¿Cuánto retrasa cada vuelo y dónde espera?
#   5. calcular_retraso_minimo_newell() → ¿Cuál es el mínimo retraso inevitable?
#   6. calcular_kpis_economicos()       → ¿Cuánto cuesta y cuánto CO2 se emite?
#   7. ejecutar_nucleo_gdp()            → Orquestador: llama a todo lo anterior.
#
# SEPARACIÓN DE RESPONSABILIDADES:
#   - Los gráficos viven en lib_visualization.py
#   - El Excel  vive en lib_excel_export.py
#   - Las constantes (AAR, PAAR, costes...) viven en config.py
# =============================================================================

import os
import numpy as np
import pandas as pd

from config import (
    CFG,
    COST_AIR_MIN,
    COST_GND_MIN,
    FS_CANDIDATE,
    FS_INTERNATIONAL,
    FS_AIRBORNE,
    FS_DISTANCE,
)


# =============================================================================
# 1. MODELO DE NEWELL — ¿CUÁNDO Y CUÁNTO COLAPSA EL AEROPUERTO?
# =============================================================================

def simular_curvas_newell(
    df_vuelos: pd.DataFrame,
    params: dict,
) -> tuple[pd.DataFrame, int]:
    """
    Construye las curvas acumuladas de demanda y capacidad del aeropuerto
    para todo el día (1440 minutos), siguiendo el Modelo de Newell.

    QUÉ CALCULA ESTA FUNCIÓN:
        - Minuto a minuto, cuántos vuelos hay en cola.
        - H_NOREG: el minuto en que la cola desaparece (aeropuerto recuperado).

    RESULTADO (timeline):
        Un DataFrame de 1440 filas (una por minuto del día) con:
        - demand_accum:   cuántos vuelos han pedido aterrizar hasta ese minuto.
        - capacity_accum: cuántos vuelos ha podido aceptar el aeropuerto.
        - queue_size:     demand_accum - capacity_accum = aviones en espera.

    Args:
        df_vuelos: Tabla de vuelos con la columna 'minutes_eta' (ETA en minutos).
        params:    Parámetros del GDP: H_START, H_END, SLOT_NOM, SLOT_RED.

    Returns:
        (timeline, h_noreg): La tabla minuto a minuto y el minuto de recuperación.
    """
    h_start = params['H_START']
    h_end   = params['H_END']

    # Tasa de llegadas que puede aceptar el aeropuerto (aviones por minuto).
    # Es el inverso del intervalo entre slots: si un slot cada 3 min → 1/3 aviones/min.
    tasa_nominal  = 1 / params['SLOT_NOM']  # Capacidad normal (sin LVP)
    tasa_reducida = 1 / params['SLOT_RED']  # Capacidad reducida (con LVP activo)

    # Creamos la columna de tiempo: un número por cada minuto del día (0 a 1439)
    timeline = pd.DataFrame({'minuto': range(1440)})

    # -------------------------------------------------------------------------
    # CURVA DE DEMANDA ACUMULADA
    # Contamos cuántos vuelos tienen su ETA en cada minuto exacto y hacemos
    # la suma acumulada. reindex() garantiza que todos los minutos aparecen
    # aunque no haya ningún vuelo programado en ese instante (rellena con 0).
    # -------------------------------------------------------------------------
    vuelos_por_minuto = (
        df_vuelos
        .groupby('minutes_eta')   # Agrupar vuelos por su ETA (minuto exacto)
        .size()                   # Contar cuántos vuelos hay en cada minuto
        .reindex(timeline['minuto'], fill_value=0)  # Rellenar minutos sin vuelos con 0
    )
    timeline['demand_accum'] = vuelos_por_minuto.cumsum()  # Suma acumulada

    # -------------------------------------------------------------------------
    # CURVA DE CAPACIDAD ACUMULADA (minuto a minuto)
    #
    # Hay tres fases distintas durante el día:
    #   FASE A (antes del GDP):   el aeropuerto funciona con normalidad.
    #                             La capacidad iguala la demanda → no hay cola.
    #   FASE B (durante el GDP):  LVP activo, capacidad reducida.
    #                             La capacidad sube más despacio → se acumula cola.
    #   FASE C (después del GDP): LVP levantado, capacidad nominal de nuevo.
    #                             La cola se va absorbiendo hasta desaparecer.
    # -------------------------------------------------------------------------
    capacidad_acumulada = []  # Lista que iremos rellenando minuto a minuto
    capacidad_actual    = 0.0 # Contador que sube a lo largo del día

    for minuto in timeline['minuto']:
        demanda_hasta_ahora = timeline.loc[minuto, 'demand_accum']

        if minuto < h_start:
            # FASE A: sin restricciones - la capacidad absorbe todo lo que llega
            capacidad_actual = demanda_hasta_ahora

        elif h_start <= minuto <= h_end:
            # FASE B: LVP activo - solo podemos aceptar 'tasa_reducida' aviones/min
            capacidad_actual += tasa_reducida

        else:
            # FASE C: recuperación - aceptamos a tasa nominal, pero sin superar
            # la demanda real (no podemos "inventar" aterrizajes)
            if capacidad_actual < demanda_hasta_ahora:
                capacidad_actual += tasa_nominal

        # La capacidad nunca puede superar la demanda: no puedes aterrizar
        # más aviones de los que han pedido aterrizar.
        capacidad_acumulada.append(min(capacidad_actual, demanda_hasta_ahora))

    timeline['capacity_accum'] = capacidad_acumulada

    # Cola = diferencia entre lo que quiere llegar y lo que puede aterrizar.
    # .clip(lower=0) elimina valores negativos por errores de redondeo.
    timeline['queue_size'] = (
        timeline['demand_accum'] - timeline['capacity_accum']
    ).clip(lower=0)

    # -------------------------------------------------------------------------
    # H_NOREG:Cuándo se disuelve la cola?
    # Buscamos el primer minuto despues del GDP en que la cola baja de 0.5 aviones.
    # Usamos 0.5 (no 0) para absorber pequeños errores de redondeo en la suma.
    # Si la cola no desaparece antes de las 00, devolvemos 1440 (fin del día).
    # -------------------------------------------------------------------------
    try:
        h_noreg = int(
            timeline[
                (timeline['minuto'] > h_end) & (timeline['queue_size'] < 0.5)
            ]['minuto'].iloc[0]  # .iloc[0] toma el primer resultado de la búsqueda
        )
    except IndexError:
        # IndexError ocurre cuando el filtro no encuentra ningún minuto
        # la cola no se disuelve en todo el día
        h_noreg = 1440

    return timeline, h_noreg


# =============================================================================
# 2. ETIQUETADO DE VUELOS — VUELOS QUE PODEMOS REGULAR
# =============================================================================

def etiquetar_vuelos_gdp(
    df_vuelos: pd.DataFrame,
    h_start: int,
    radius_km: int  = CFG.GDP_RADIUS_KM,
    h_freeze_offset: int = CFG.H_FILE_OFFSET,
) -> pd.DataFrame:
    """
    Clasifica cada vuelo en una de estas cuatro categorías de regulación:

        GPD CANDIDATE        → Podemos retrasarlo en tierra (es el que el GDP controla).
        EXEMPT INTERNATIONAL → Viene de fuera del espacio aéreo europeo (ECAC).
                               No podemos obligarle a seguir un CTOT.
        EXEMPT AIRBORNE      → Ya despegó antes de que activaramos el GDP.
                               No podemos retrasarlo: ya está en el aire.
        EXEMPT DISTANCE      → Sale de tan lejos que cuando llega el GDP ya habrá terminado.
                               El radio de cobertura del GDP no llega a su origen.

    el orden importa:
        Un vuelo intercontinental que ya despegó NO se etiqueta como AIRBORNE,
        sino como INTERNATIONAL. La categoría ECAC tiene prioridad.

    FREEZE HORIZON (H_FREEZE_OFFSET):
        El GDP no puede notificar a un avión que ya está en el aire.
        Si un vuelo despegó más de H_FREEZE_OFFSET minutos antes de H_START,
        se considera "airborne" a efectos del GDP.
        Valor estándar Eurocontrol: 150 minutos (2.5 horas).

    Args:
        df_vuelos:       Tabla de vuelos con is_ecac, minutes_etd, distancia_km.
        h_start:         Minuto de inicio del GDP (360 = 06:00).
        radius_km:       Radio máximo de cobertura del GDP en km (3000 km).
        h_freeze_offset: Minutos antes de H_START.

    Returns:
        Copia de df_vuelos con 4 columnas nuevas:
        is_departed, is_inside_radius, is_gpd_candidate, flight_status.
    """
    df = df_vuelos.copy()

    # vuelos que despegaron antes de este minuto
    # ya no pueden recibir un nuevo CTOT (hora de salida asignada).
    t_file = h_start - h_freeze_offset

    # --- Tres checks (True/False) por vuelo ---

    # Despegó antes del hfile?
    df['is_departed'] = df['minutes_etd'] < t_file

    # Su aeropuerto de origen está dentro del radio de cobertura del GDP?
    df['is_inside_radius'] = df['distancia_km'] <= radius_km

    # Es candidato GDP? Solo si cumple las 3 condiciones a la vez:
    df['is_gpd_candidate'] = (
        df['is_ecac']            # 1. Origen en espacio aéreo europeo (ECAC)
        & ~df['is_departed']     # 2. Aún no ha despegado (el ~ invierte True/False)
        & df['is_inside_radius'] # 3. Dentro del radio de cobertura
    )

    # -------------------------------------------------------------------------
    # Asignación de etiqueta final usando np.select()
    #
    # np.select() es el equivalente vectorizado de un if-elif-else aplicado
    # a toda la columna de una vez.
    # Evalúa las condiciones en orden: la PRIMERA que sea True gana.
    # Si ninguna condición es True, asigna el valor predeterminado.
    #
    # Equivalente en lenguaje natural:
    #   SI es candidato GDP        → FS_CANDIDATE
    #   SINO SI no es ECAC         → FS_INTERNATIONAL
    #   SINO SI ya despegó         → FS_AIRBORNE
    #   SINO SI fuera del radio    → FS_DISTANCE
    #   EN CUALQUIER OTRO CASO     → 'UNKNOWN' --> solo saldra si hubiese algun error
    # -------------------------------------------------------------------------
    condiciones = [
        df['is_gpd_candidate'],   # Condición 1: es regulable
        ~df['is_ecac'],           # Condición 2: es intercontinental
        df['is_departed'],        # Condición 3: ya está en el aire
        ~df['is_inside_radius'],  # Condición 4: demasiado lejos
    ]
    etiquetas = [
        FS_CANDIDATE,
        FS_INTERNATIONAL,
        FS_AIRBORNE,
        FS_DISTANCE,
    ]
    df['flight_status'] = np.select(condiciones, etiquetas, default='UNKNOWN')

    return df


# =============================================================================
# 3. ASIGNACIÓN DE SLOTS — ALGORITMO RBS (Ration-By-Schedule)
# =============================================================================

def asignar_slots_rbs(
    df_regulados: pd.DataFrame,
    df_slots: pd.DataFrame,
) -> pd.DataFrame:
    """
    Asigna un slot de aterrizaje a cada vuelo usando el algoritmo RBS
    (Ration-By-Schedule) de Eurocontrol.

    QUÉ ES RBS:
        RBS es el algoritmo oficial de Eurocontrol para asignar slots en un GDP.
        La idea central es: "el que primero tenía previsto llegar, primero aterriza".
        Es un sistema FIFO (First In, First Out) aplicado a los slots disponibles.

    LÓGICA EN DOS PASADAS:
        PASADA 1 — Vuelos EXENTOS (airborne, internacionales, lejanos):
            Estos aviones ya no pueden cambiar su hora de llegada.
            Se les asigna el primer slot disponible >= su ETA original.
            Tienen PRIORIDAD porque no podemos pedirles que esperen.

        PASADA 2 — Vuelos CANDIDATOS GDP:
            Estos aviones pueden ser retrasados en tierra.
            Se les asigna el primer slot disponible tras los exentos.
            Si el slot disponible es posterior a su ETA → hay retraso en tierra.

    HAREMOS DOS PASADAS:
        Si mezcláramos ambos grupos, un candidato GDP podría "robar" el slot
        de un exento que llega en ese mismo minuto. Los exentos tienen prioridad
        operacional porque ya no tienen margen de maniobra.

    Args:
        df_regulados: Tabla de vuelos con 'flight_status' y 'minutes_eta'.
        df_slots:     Tabla de slots disponibles con 'slot_start_min' y 'occupied'.

    Returns:
        df_regulados con la columna 'assigned_slot' rellena (NaN si sin slot).
    """
    df = df_regulados.copy()
    df['assigned_slot'] = np.nan  # Empezamos sin asignar nada

    # Dos pasadas: primero exentos, luego candidatos
    for procesar_candidatos_gdp in [False, True]:

        if procesar_candidatos_gdp:
            seleccion = df['flight_status'] == FS_CANDIDATE
        else:
            seleccion = df['flight_status'] != FS_CANDIDATE

        # Procesamos los vuelos de este grupo en orden de ETA (más temprano primero)
        for indice_vuelo, datos_vuelo in df[seleccion].sort_values('minutes_eta').iterrows():

            # Buscamos slots que: (1) empiecen >= ETA del vuelo y (2) estén libres
            slots_disponibles = df_slots[
                (df_slots['slot_start_min'] >= datos_vuelo['minutes_eta'])
                & (~df_slots['occupied'])  # ~ invierte: occupied=False → disponible
            ]

            if not slots_disponibles.empty:
                # Tomamos el primer slot disponible (el más cercano a la ETA)
                indice_slot = slots_disponibles.index[0]

                # Marcamos el slot como ocupado para que nadie más lo tome
                df_slots.at[indice_slot, 'occupied']  = True
                df_slots.at[indice_slot, 'flight_id'] = indice_vuelo

                # Asignamos la hora del slot al vuelo
                df.at[indice_vuelo, 'assigned_slot'] = df_slots.at[indice_slot, 'slot_start_min']

    return df


# =============================================================================
# 4. CÁLCULO DE RETRASOS — ¿CUÁNTO RETRASA CADA VUELO Y DÓNDE ESPERA?
# =============================================================================

def calcular_delays(df_res: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula el retraso de cada vuelo y lo desglosa en dos componentes:

        total_delay  = assigned_slot - ETA_original  (retraso total del vuelo)
        air_delay    = retraso absorbido EN EL AIRE   (solo vuelos EXENTOS)
        ground_delay = retraso absorbido EN TIERRA    (solo vuelos CANDIDATOS GDP)

    POR QUÉ ESTA SEPARACIÓN:
        Los vuelos EXENTOS no podemos regularlos: si llegan tarde, es retraso
        en el aire (holding, etc.) que no controlamos.
        Los vuelos CANDIDATOS GDP esperan en origen antes de despegar: su
        retraso es en tierra, que es mucho más barato y ecológico.

        La suma siempre se cumple: air_delay + ground_delay = total_delay

    NOTA SOBRE np.where():
        np.where(condición, valor_si_True, valor_si_False) es el equivalente
        vectorizado de: "para cada fila, si condición → ponle este valor, si no → este otro".
        Es mucho más rápido que un bucle for sobre las filas del DataFrame.

    Args:
        df_res: Tabla con 'assigned_slot', 'minutes_eta' y 'flight_status'.

    Returns:
        La misma tabla con 3 columnas nuevas: total_delay, air_delay, ground_delay.
    """
    df = df_res.copy()

    # Retraso total = hora de aterrizaje asignada - hora de aterrizaje prevista.
    # .clip(lower=0) elimina valores negativos: si un avión llega antes de su ETA,
    # su retraso es 0, no negativo.
    df['total_delay'] = (df['assigned_slot'] - df['minutes_eta']).clip(lower=0)

    # Identificamos qué vuelos son candidatos GDP (True) y cuáles son exentos (False)
    es_candidato_gdp = df['flight_status'] == FS_CANDIDATE

    # Vuelos EXENTOS (no candidatos): su retraso es en el aire
    # Vuelos CANDIDATOS: su retraso es en tierra
    df['air_delay']    = np.where(~es_candidato_gdp, df['total_delay'], 0)
    df['ground_delay'] = np.where( es_candidato_gdp, df['total_delay'], 0)

    return df


# =============================================================================
# 5. RETRASO MÍNIMO TEÓRICO — ¿CUÁL ES EL MÍNIMO INEVITABLE?
# =============================================================================

def calcular_retraso_minimo_newell(timeline: pd.DataFrame) -> float:
    """
    Calcula el retraso mínimo teórico que impone la restricción de capacidad,
    independientemente del algoritmo de asignación que se use.

    QUÉ SIGNIFICA "MÍNIMO TEÓRICO":
        Cuando hay LVP, el aeropuerto no puede aceptar todos los vuelos.
        Aunque usáramos el algoritmo perfecto (ILP, RBS u otro), siempre habrá
        un retraso mínimo que no se puede evitar — es consecuencia directa
        de la diferencia entre oferta (capacidad) y demanda (vuelos).

        Este valor es el ÁREA entre las dos curvas del diagrama de Newell.
        Si el área es X minutos, significa que como mínimo X minutos de retraso
        se van a acumular en el sistema, sin importar cómo se distribuyan.

    CÓMO SE CALCULA:
        En cada minuto, la cola = demanda_acumulada - capacidad_acumulada.
        Sumamos la cola de todos los minutos → retraso mínimo total acumulado.

    Args:
        timeline: DataFrame con columnas 'demand_accum' y 'capacity_accum'.

    Returns:
        Suma total de la cola acumulada (en minutos).
    """
    cola_por_minuto = (timeline['demand_accum'] - timeline['capacity_accum']).clip(lower=0)
    return cola_por_minuto.sum()


# =============================================================================
# 6. KPIs ECONÓMICOS Y AMBIENTALES — FUENTE ÚNICA DE VERDAD
# =============================================================================

def calcular_kpis_economicos(df_res: pd.DataFrame) -> dict:
    """
    Calcula todos los KPIs de coste y CO2 en un único lugar.

    POR QUÉ "FUENTE ÚNICA DE VERDAD":
        Los KPIs se usan en tres sitios: los gráficos, el Excel y el análisis
        de sensibilidad. Si los calculáramos en cada sitio por separado, un
        cambio en la fórmula habría que aplicarlo en tres sitios.
        Al centralizar aquí, todos usan siempre los mismos cálculos.

    LÓGICA DE COSTES:
        Escenario Sin GDP (FIFO):  todo el retraso ocurre en el aire (caro).
            coste_base = total_delay × COST_AIR_MIN

        Escenario Con GDP (RBS):   el retraso se separa en aire y tierra.
            coste_gdp = air_delay × COST_AIR_MIN + ground_delay × COST_GND_MIN
            Como COST_GND_MIN << COST_AIR_MIN, el GDP ahorra dinero.

    LÓGICA DE CO2 — Modelo Delgado et al. (2025):
        Cada vuelo tiene un CO2 base (co2_kg_vuelo) calculado en la Fase 1
        a partir de su distancia y número de asientos.

        El retraso en el aire AÑADE CO2 (el avión sigue quemando combustible).
        El retraso en tierra NO añade CO2 (el avión está parado, motor apagado).

        La proporción de CO2 extra es lineal con el retraso:
            CO2_extra = co2_kg_vuelo × (retraso_en_aire / duración_del_vuelo)

    RETRASO IRRECUPERABLE:
        Si el GDP se cancela justo en H_START, los vuelos EXEMPT AIRBORNE
        ya no pueden ser retrasados en tierra — están en el aire.
        Su retraso ya está "comprometido" y no puede evitarse.

    Args:
        df_res: Tabla con total_delay, air_delay, ground_delay,
                co2_kg_vuelo (del modelo Delgado) y duracion_vuelo_min.

    Returns:
        Diccionario con todas las métricas económicas, ambientales y operacionales.
    """
    # --- Retrasos totales del escenario ---
    retraso_total  = df_res['total_delay'].sum()
    retraso_aire   = df_res['air_delay'].sum()
    retraso_tierra = df_res['ground_delay'].sum()

    # --- Costes ---
    coste_sin_gdp = retraso_total * COST_AIR_MIN
    coste_con_gdp = retraso_aire  * COST_AIR_MIN + retraso_tierra * COST_GND_MIN

    # --- CO2 usando el modelo proporcional de Delgado et al. (2025) ---
    # .clip(lower=1) evita división por cero si duracion_vuelo_min = 0
    duracion_vuelo = df_res['duracion_vuelo_min'].clip(lower=1)
    co2_base_vuelo = df_res['co2_kg_vuelo']

    # CO2 sin GDP: el CO2 base más el extra por todo el retraso en el aire
    co2_sin_gdp = (co2_base_vuelo * (1 + df_res['total_delay'] / duracion_vuelo)).sum()

    # CO2 con GDP: el CO2 base más el extra solo por el retraso que queda en el aire
    co2_con_gdp = (co2_base_vuelo * (1 + df_res['air_delay'] / duracion_vuelo)).sum()

    # Desglose del CO2 extra atribuible a cada tipo de retraso
    co2_extra_aire   = (co2_base_vuelo * (df_res['air_delay']   / duracion_vuelo)).sum()
    co2_extra_tierra = (co2_base_vuelo * (df_res['ground_delay'] / duracion_vuelo)).sum()

    # --- Retraso Irrecuperable (Unrecoverable Delay) ---
    # Asumimos que la previsión meteorológica falla y el GDP se cancela 
    # exactamente en H_START. ¿Cuánto tiempo han perdido ya los aviones en tierra?
    
    # CTD (Calculated Take-Off Time) = Hora real a la que van a despegar con el retraso
    # Como ground_delay es el retraso asignado en tierra, CTD = ETD + ground_delay
    ctd = df_res['minutes_etd'] + df_res['ground_delay']
    h_start = CFG.H_START # El momento de la cancelación
    
    # Inicializamos una serie de ceros
    unrecoverable = pd.Series(0.0, index=df_res.index)
    
    # CASO 1: ETD >= H_start
    # El avión no iba a despegar hasta después de la cancelación de todas formas.
    # Pierde 0 minutos (el retraso es 100% recuperable).
    # No hacemos nada porque ya está inicializado a 0.
    
    # CASO 2: CTD <= H_start
    # El avión ya se tragó todo su retraso en tierra y despegó ANTES de que
    # se cancelara el GDP. Todo su ground_delay es irrecuperable.
    caso2 = ctd <= h_start
    unrecoverable[caso2] = df_res.loc[caso2, 'ground_delay']
    
    # CASO 3: ETD < H_start < CTD
    # El avión debía haber despegado, pero el GDP lo retuvo. En el momento
    # H_start se cancela el GDP y le decimos "¡despega ya!".
    # El tiempo que ha perdido tontamente es (H_start - ETD).
    caso3 = (df_res['minutes_etd'] < h_start) & (ctd > h_start)
    unrecoverable[caso3] = h_start - df_res.loc[caso3, 'minutes_etd']
    
    # A esto le sumamos el air_delay de los vuelos AIRBORNE, que por definición 
    # no se puede recuperar porque ya están en el aire.
    retraso_irrecuperable = unrecoverable.sum()

    return {
        # Costes
        'cost_baseline':       round(coste_sin_gdp, 2),
        'cost_gdp':            round(coste_con_gdp, 2),
        'cost_savings':        round(coste_sin_gdp - coste_con_gdp, 2),
        # Emisiones CO2
        'co2_baseline':        round(co2_sin_gdp, 2),
        'co2_gdp':             round(co2_con_gdp, 2),
        'co2_savings':         round(co2_sin_gdp - co2_con_gdp, 2),
        'co2_aire_delay':      round(co2_extra_aire, 2),
        'co2_tierra_delay':    round(co2_extra_tierra, 2),
        # Operacional
        'unrecoverable_delay': round(retraso_irrecuperable, 2),
    }


# =============================================================================
# 7. ORQUESTADOR — CONECTA TODOS LOS PASOS EN EL ORDEN CORRECTO
# =============================================================================

def ejecutar_nucleo_gdp(
    df_vuelos: pd.DataFrame,
    params: dict,
    radius_km: int       = CFG.GDP_RADIUS_KM,
    h_file_offset: int = CFG.H_FILE_OFFSET,
) -> dict:
    """
    Orquestador de la Fase 2: ejecuta los 5 pasos del GDP en orden.

    Esta función NO tiene lógica propia — solo llama a las funciones
    anteriores en el orden correcto y empaqueta los resultados.

    También acepta parámetros opcionales de radio y freeze horizon para
    que lib_sensitivity.py pueda llamarla con distintos valores sin
    duplicar código.

    FLUJO:
        Paso 1 → simular_curvas_newell()  → ¿Cuándo colapsa el aeropuerto?
        Paso 2 → etiquetar_vuelos_gdp()   → ¿A qué vuelos podemos regular?
        Paso 3 → [aquí mismo]             → Generar la rejilla de slots disponibles
        Paso 4 → asignar_slots_rbs()      → ¿A qué slot va cada vuelo?
        Paso 5 → calcular_delays()        → ¿Cuánto retrasa y dónde espera?

    Args:
        df_vuelos:       Tabla de vuelos limpia de la Fase 1.
        params:          Parámetros del GDP (H_START, H_END, AAR, PAAR...).
        radius_km:       Radio de cobertura del GDP. Por defecto: config.py.
        h_freeze_offset: Ventana de congelación CTOT. Por defecto: config.py.

    Returns:
        Diccionario con todos los resultados que main.py necesita para
        generar el CSV, el Excel, los gráficos y el análisis de sensibilidad.
    """
    # PASO 1: Construir las curvas de Newell y encontrar H_NOREG
    timeline, h_noreg = simular_curvas_newell(df_vuelos, params)

    # PASO 2: Clasificar cada vuelo (candidato GDP o exento, y por qué)
    df_vuelos_etiquetados = etiquetar_vuelos_gdp(
        df_vuelos,
        h_start=params['H_START'],
        radius_km=radius_km,
        h_freeze_offset=h_file_offset,
    )

    # PASO 3: Generar la rejilla de slots disponibles
    # Empezamos en H_START y añadimos un slot cada SLOT_RED minutos mientras dura el GDP,
    # luego cada SLOT_NOM minutos hasta que la cola se disuelve (h_noreg).
    # El +1000 es un margen de seguridad: generamos slots hasta bien pasado h_noreg
    # para garantizar que todos los vuelos en cola tengan un slot disponible.
    lista_slots = []
    tiempo = params['H_START']
    while tiempo < min(h_noreg + 1000, 1440):
        lista_slots.append(round(tiempo, 4))
        if tiempo < params['H_END']:
            tiempo += params['SLOT_RED']  # Durante el GDP: intervalo reducido
        else:
            tiempo += params['SLOT_NOM']  # Después del GDP: intervalo normal

    df_slots = pd.DataFrame({
        'slot_start_min': lista_slots,
        'occupied':       False,   # Al inicio todos los slots están libres
        'flight_id':      None,    # Se rellenará en el Paso 4
    })

    # PASO 4: Asignar slots usando el algoritmo RBS
    # Solo procesamos vuelos cuya ETA está dentro de la ventana GDP
    df_en_ventana = df_vuelos_etiquetados[
        df_vuelos_etiquetados['minutes_eta'] >= params['H_START']
    ].copy()
    #df_resultado = asignar_slots_rbs(df_en_ventana, df_slots)

    df_slots_original = df_slots.copy()
    df_resultado_original = asignar_slots_rbs(df_en_ventana, df_slots_original)
    df_resultado_original = calcular_delays(df_resultado_original)

   # PASO 5: Calcular retrasos (total, en aire y en tierra)
    from lib_compression import penalty_and_compression
    
    # Llamamos a la función SOLO con los argumentos que acepta y recogemos un solo resultado
    df_resultado_comprimido = penalty_and_compression(
        df_vuelos_asignados=df_resultado_original, 
        num_penalizados=12
    )
    
    # Recalculamos los retrasos para la versión comprimida
    df_resultado_comprimido = calcular_delays(df_resultado_comprimido)
    df_slots_comprimido = df_slots_original.copy()

    return {
        # Resultados SIN comprimir
        'vuelos_asignados': df_resultado_original, 
        'slots':            df_slots_original,
        
        # Resultados CON compresión
        'vuelos_comprimidos': df_resultado_comprimido,
        'slots_comprimidos':  df_slots_comprimido,
        
        # Datos comunes
        'vuelos_crudos':    df_vuelos,      
        'timeline':         timeline,       
        'h_noreg':          h_noreg,        
        'params':           params,         
    }

# =============================================================================
# MODO DEBUG — Ejecutar directamente para probar este módulo de forma aislada.
#   cd src/
#   python lib_gdp_core.py
# =============================================================================
if __name__ == "__main__":
    print("🛠️  MODO DEBUG: lib_gdp_core.py")
    import lib_data_prep as prep

    base     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota  = os.path.join(base, 'data/raw/fleet_cat_seat.csv')
    p_debug  = os.path.join(base, 'debug/DEBUG_02_etiquetado_gdp.xlsx')

    params = CFG.to_params_dict()

    df_vuelos = prep.preparar_vuelos(p_vuelos, p_flota)
    df_etiq   = etiquetar_vuelos_gdp(df_vuelos, CFG.H_START)

    os.makedirs(os.path.dirname(p_debug), exist_ok=True)
    cols_debug = ['ARCID', 'airline', 'ADEP', 'is_ecac', 'distancia_km', 'is_departed', 'flight_status']
    df_etiq[cols_debug].to_excel(p_debug, index=False)

    print(f"✅ Excel de etiquetado generado en: {p_debug}")
    print("   → Abre el archivo y verifica que los filtros ECAC, distancia y Airborne son correctos.")