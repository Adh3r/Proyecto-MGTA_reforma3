# =============================================================================
# src/lib_gdp_core.py
# FASE 2: Motor de simulación del Ground Delay Program (GDP).
#
# Este módulo recibe el DataFrame limpio de lib_data_prep y ejecuta toda la
# lógica del GDP: curvas de Newell, clasificación de exenciones, asignación
# de slots RBS y generación de gráficos y KPIs.
#
# Responsabilidades (cada una en su propia función):
#   1. simular_curvas_newell()  → Modelo de cola de Newell.
#   2. etiquetar_vuelos_gdp()   → Clasificar vuelos: regulados vs. exentos.
#   3. asignar_slots_rbs()      → Algoritmo Ration-By-Schedule.
#   4. calcular_delays()        → Separar retraso en aire vs. tierra.
#   5. calcular_kpis_economicos() → Fuente única de verdad para costes/CO2.
#   6. plot_*()                 → Un gráfico, una función.
#   7. generar_graficos()       → Orquestador de todos los plots.
#   8. exportar_auditoria_excel() → Genera el Excel final de entregable.
#   9. ejecutar_nucleo_gdp()    → Orquestador principal de todo el módulo.
# =============================================================================

import os
import numpy as np
import pandas as pd

# Importamos constantes centralizadas — sin "números mágicos" en el código.
from config import (
    CFG,
    COST_AIR_MIN,
    COST_GND_MIN,
)


# =============================================================================
# 1. MODELO DE NEWELL — CURVAS ACUMULADAS DE DEMANDA Y CAPACIDAD
# =============================================================================

def simular_curvas_newell(
    df_vuelos: pd.DataFrame,
    params: dict,
) -> tuple[pd.DataFrame, int]:
    """
    Genera las curvas acumuladas del modelo de Newell para el día completo.

    El modelo de Newell es una representación gráfica de colas en sistemas
    de transporte. Compara la demanda acumulada (vuelos que quieren llegar)
    con la capacidad acumulada (vuelos que el aeropuerto puede absorber).
    La diferencia entre ambas curvas en cualquier momento = tamaño de la cola.

    Args:
        df_vuelos: DataFrame con los vuelos, debe tener columna 'minutes_eta'.
        params:    Diccionario con H_START, H_END, SLOT_NOM, SLOT_RED.

    Returns:
        timeline:  DataFrame de 1440 filas (una por minuto del día) con
                   columnas demand_accum, capacity_accum y queue_size.
        h_noreg:   Minuto del día en que la cola se disuelve (fin de impacto).
    """
    h_start = params['H_START']
    h_end   = params['H_END']

    # Tasa de servicio: cuántos aviones por minuto puede aceptar el aeropuerto.
    # Es el inverso del intervalo entre slots: 1/SLOT_RED = aviones/minuto.
    r_nom = 1 / params['SLOT_NOM']  # Tasa nominal (sin LVP)
    r_red = 1 / params['SLOT_RED']  # Tasa reducida (con LVP activo)

    # Creamos un DataFrame de "timeline": una fila por cada minuto del día (0-1439)
    timeline = pd.DataFrame({'minuto': range(1440)})

    # Contamos cuántos vuelos tienen ETA en cada minuto y acumulamos el total.
    # reindex rellena con 0 los minutos sin vuelos (para no perder la serie completa).
    counts = (
        df_vuelos
        .groupby('minutes_eta')
        .size()
        .reindex(timeline['minuto'], fill_value=0)
    )
    timeline['demand_accum'] = counts.cumsum()

    # -------------------------------------------------------------------------
    # Construcción de la curva de capacidad acumulada, minuto a minuto:
    #   - Antes del GDP (t < h_start): el aeropuerto absorbe todo lo que llega.
    #   - Durante el GDP (h_start ≤ t ≤ h_end): capacidad reducida (LVP).
    #   - Después del GDP (t > h_end): capacidad nominal, hasta que la cola
    #     se disuelve (current_cap alcanza demand_accum).
    # -------------------------------------------------------------------------
    cap_accum = []
    current_cap = 0.0

    for t in timeline['minuto']:
        dem_t = timeline.loc[t, 'demand_accum']

        if t < h_start:
            # Pre-GDP: sin restricciones, la capacidad iguala la demanda.
            current_cap = dem_t
        elif h_start <= t <= h_end:
            # Durante GDP: incremento constante a tasa reducida.
            current_cap += r_red
        else:
            # Post-GDP: recuperamos a tasa nominal, pero no superamos la demanda.
            current_cap += r_nom if current_cap < dem_t else 0

        # La capacidad acumulada nunca puede superar la demanda acumulada real.
        cap_accum.append(min(current_cap, dem_t))

    timeline['capacity_accum'] = cap_accum

    # Cola en cada minuto = diferencia entre lo que quiere llegar y lo que puede.
    # .clip(lower=0) evita valores negativos por redondeo.
    timeline['queue_size'] = (
        timeline['demand_accum'] - timeline['capacity_accum']
    ).clip(lower=0)

    # -------------------------------------------------------------------------
    # H_NOREG: el minuto en que la cola se disuelve.
    # Buscamos el primer minuto DESPUÉS del GDP donde queue_size < 0.5 aviones.
    # Si la cola no se disuelve nunca, usamos el final del día (1440).
    # -------------------------------------------------------------------------
    try:
        h_noreg = int(
            timeline[
                (timeline['minuto'] > h_end) & (timeline['queue_size'] < 0.5)
            ]['minuto'].iloc[0]
        )
    except IndexError:
        # IndexError ocurre si la lista filtrada está vacía (cola no se disuelve).
        h_noreg = 1440

    return timeline, h_noreg


# =============================================================================
# 2. ETIQUETADO DE VUELOS — ¿REGULADO O EXENTO?
# =============================================================================

def etiquetar_vuelos_gdp(
    df_vuelos: pd.DataFrame,
    h_start: int,
    radius_km: int = CFG.GDP_RADIUS_KM,
    h_freeze_offset: int = CFG.H_FREEZE_OFFSET,
) -> pd.DataFrame:
    """
    Clasifica cada vuelo en una de estas categorías:
        - GPD CANDIDATE:       Vuelo regulable (ECAC, no airborne, dentro del radio).
        - EXEMPT INTERNATIONAL: Vuelo de fuera del espacio ECAC.
        - EXEMPT AIRBORNE:     Vuelo ya en el aire cuando se activa el GDP.
        - EXEMPT DISTANCE:     Vuelo demasiado lejos para ser regulado.
 
    La lógica de prioridad importa: un vuelo intercontinental NO se marca
    como "airborne" aunque ya haya despegado; se marca como "international".
 
    Args:
        df_vuelos: DataFrame con flags is_ecac, minutes_etd, distancia_km.
        h_start:   Minuto de inicio del GDP (desde config.py: CFG.H_START).
        radius_km: Radio máximo de cobertura del GDP en kilómetros.
 
    Returns:
        Copia del DataFrame con columnas nuevas:
        is_departed, is_inside_radius, is_gpd_candidate, flight_status.
    """
    df = df_vuelos.copy()
 
    # Minuto de "congelación": si un vuelo despegó antes de este momento,
    # ya está volando y no puede recibir un CTOT (clearance to take-off time).
    # H_FREEZE_OFFSET viene de config.py (valor estándar: 150 min).
    h_freeze = h_start - h_freeze_offset
 
    # Flag 1: ¿El vuelo ya ha despegado antes de la ventana de congelación?
    df['is_departed'] = df['minutes_etd'] < h_freeze
 
    # Flag 2: ¿Está el aeropuerto de origen dentro del radio de cobertura?
    df['is_inside_radius'] = df['distancia_km'] <= radius_km
 
    # Un vuelo es candidato SOLO si cumple las 3 condiciones:
    df['is_gpd_candidate'] = (
        df['is_ecac']           # 1. Origen en espacio ECAC
        & ~df['is_departed']    # 2. Aún en tierra cuando se activa el GDP
        & df['is_inside_radius']# 3. Dentro del radio de cobertura
    )
 
    # np.select evalúa las condiciones en orden; la primera que sea True gana.
    # 'default' captura cualquier caso no previsto (debería ser imposible aquí).
    conds = [
        df['is_gpd_candidate'],
        ~df['is_ecac'],
        df['is_departed'],
        ~df['is_inside_radius'],
    ]
    labels = [
        'GPD CANDIDATE',
        'EXEMPT INTERNATIONAL',
        'EXEMPT AIRBORNE',
        'EXEMPT DISTANCE',
    ]
    df['flight_status'] = np.select(conds, labels, default='UNKNOWN')
 
    return df


# =============================================================================
# 3. ASIGNACIÓN DE SLOTS — ALGORITMO RBS (Ration-By-Schedule)
# =============================================================================

def asignar_slots_rbs(
    df_regulados: pd.DataFrame,
    df_slots: pd.DataFrame,
) -> pd.DataFrame:
    """
    Implementa el algoritmo RBS (Ration-By-Schedule) de Eurocontrol.

    Lógica:
        - Primero se asignan slots a los vuelos EXENTOS (tienen preferencia
          porque ya no pueden cambiar su hora de llegada).
        - Luego se asignan los slots restantes a los vuelos CANDIDATOS GDP,
          que pueden ser retrasados en tierra para ajustarse.
        - Dentro de cada grupo, el orden es por ETA (primero en llegar,
          primero en ser servido → FIFO, que es la base del RBS).

    Args:
        df_regulados: DataFrame con los vuelos en ventana GDP y su flight_status.
        df_slots:     DataFrame con todos los slots disponibles y si están ocupados.

    Returns:
        Copia del df_regulados con la columna 'assigned_slot' rellena.
    """
    df = df_regulados.copy()
    df['assigned_slot'] = np.nan  # Inicializamos como sin asignar

    # Procesamos primero los exentos (group_gdp=False) y luego los candidatos.
    # Esto garantiza que los vuelos que no pueden cambiar de hora tengan
    # prioridad sobre los que sí pueden ser retrasados.
    for group_gdp in [False, True]:
        if group_gdp:
            mask = df['flight_status'] == 'GPD CANDIDATE'
        else:
            mask = df['flight_status'] != 'GPD CANDIDATE'

        # Iteramos en orden de ETA (el más temprano primero = FIFO)
        for idx, flight in df[mask].sort_values('minutes_eta').iterrows():
            # Buscamos el primer slot disponible a partir de la ETA del vuelo
            available_slots = df_slots[
                (df_slots['slot_start_min'] >= flight['minutes_eta'])
                & (~df_slots['occupied'])
            ]

            if not available_slots.empty:
                slot_idx = available_slots.index[0]

                # Marcamos el slot como ocupado y lo vinculamos al vuelo
                df_slots.at[slot_idx, 'occupied'] = True
                df_slots.at[slot_idx, 'flight_id'] = idx

                # Asignamos la hora del slot al vuelo
                df.at[idx, 'assigned_slot'] = df_slots.at[slot_idx, 'slot_start_min']

    return df


# =============================================================================
# 4. CÁLCULO DE RETRASOS — AIRE VS. TIERRA
# =============================================================================

def calcular_delays(df_res: pd.DataFrame) -> pd.DataFrame:
    """
    Descompone el retraso total de cada vuelo en dos componentes:
        - air_delay:    Retraso absorbido en el AIRE (vuelos exentos del GDP).
                        Estos aviones llegan tarde porque no pudieron ser regulados.
        - ground_delay: Retraso absorbido en TIERRA (vuelos candidatos GDP).
                        Estos aviones esperan en origen antes de despegar.

    La suma air_delay + ground_delay = total_delay siempre.

    Args:
        df_res: DataFrame con 'assigned_slot', 'minutes_eta' y 'flight_status'.

    Returns:
        El mismo DataFrame con 3 columnas nuevas: total_delay, air_delay, ground_delay.
    """
    df = df_res.copy()

    # Retraso total = diferencia entre el slot asignado y la ETA original.
    # .clip(lower=0) evita retrasos negativos (si un vuelo llega antes de su ETA).
    df['total_delay'] = (df['assigned_slot'] - df['minutes_eta']).clip(lower=0)

    # Los vuelos EXENTOS absorben su retraso en el aire (no tenemos control).
    # Los vuelos CANDIDATOS absorben su retraso en tierra (con GDP aplicado).
    es_candidato = df['flight_status'] == 'GPD CANDIDATE'
    df['air_delay']    = np.where(~es_candidato, df['total_delay'], 0)
    df['ground_delay'] = np.where( es_candidato, df['total_delay'], 0)

    return df

def calcular_retraso_minimo_newell(timeline: pd.DataFrame) -> float:
    """
    Retraso mínimo teórico impuesto por la restricción de capacidad.
    Es el área entre la curva de demanda y la curva de capacidad
    en el diagrama de Newell. Representa el mínimo inevitable
    independientemente del algoritmo de asignación usado.
    """
    return (timeline['demand_accum'] - timeline['capacity_accum']).clip(lower=0).sum()


# =============================================================================
# 5. KPIs ECONÓMICOS Y AMBIENTALES — FUENTE ÚNICA DE VERDAD
# =============================================================================

def calcular_kpis_economicos(df_res: pd.DataFrame) -> dict:
    """
    Calcula todos los KPIs de coste y CO2 en un único lugar.

    COSTES:
        Do-Nothing: todo el retraso ocurre en el aire → total_delay × COST_AIR_MIN.
        GDP:        retraso separado en aire (caro) y tierra (barato).

    EMISIONES CO2 — modelo proporcional (Delgado et al., 2025):
        co2_kg_vuelo es el CO2 del vuelo completo en condiciones normales,
        calculado en lib_data_prep.py usando la distancia y los asientos.

        Do-Nothing: todos los vuelos emiten su co2_kg_vuelo completo, más
        el CO2 extra del retraso en el aire (proporcional a la duración).

            co2_baseline = Σ co2_kg_vuelo × (1 + total_delay / duracion_vuelo)

        GDP: el retraso en tierra sustituye al retraso en el aire, ahorrando
        las emisiones proporcionales a ese tiempo:

            co2_gdp = Σ co2_kg_vuelo × (1 + air_delay / duracion_vuelo)

        El ahorro es exactamente:
            co2_savings = Σ co2_kg_vuelo × (ground_delay / duracion_vuelo)

    Args:
        df_res: DataFrame con columnas total_delay, air_delay, ground_delay,
                co2_kg_vuelo y duracion_vuelo_min.

    Returns:
        Diccionario con 6 métricas: cost_baseline, cost_gdp, cost_savings,
        co2_baseline, co2_gdp, co2_savings. Todos en € o kg respectivamente.
    """
    r_total  = df_res['total_delay'].sum()
    r_aire   = df_res['air_delay'].sum()
    r_tierra = df_res['ground_delay'].sum()

    cost_baseline = r_total * COST_AIR_MIN
    cost_gdp      = r_aire  * COST_AIR_MIN + r_tierra * COST_GND_MIN

    # CO2 proporcional por vuelo — requiere columnas del modelo Delgado
    dur = df_res['duracion_vuelo_min'].clip(lower=1)   # evitar división por 0
    co2 = df_res['co2_kg_vuelo']

    co2_baseline = (co2 * (1 + df_res['total_delay'] / dur)).sum()
    co2_gdp      = (co2 * (1 + df_res['air_delay']   / dur)).sum()
    
    co2_aire_delay   = (co2 * (df_res['air_delay']   / dur)).sum()
    co2_tierra_delay = (co2 * (df_res['ground_delay'] / dur)).sum()

    unrecoverable = df_res[df_res['flight_status'] == 'EXEMPT AIRBORNE']['total_delay'].sum()

    return {
        'cost_baseline':      round(cost_baseline, 2),
        'cost_gdp':           round(cost_gdp, 2),
        'cost_savings':       round(cost_baseline - cost_gdp, 2),
        'co2_baseline':       round(co2_baseline, 2),
        'co2_gdp':            round(co2_gdp, 2),
        'co2_savings':        round(co2_baseline - co2_gdp, 2),
        'co2_aire_delay':     round(co2_aire_delay, 2),
        'co2_tierra_delay':   round(co2_tierra_delay, 2),
        'unrecoverable_delay': round(unrecoverable, 2),   # ← NUEVO
    }

# =============================================================================
# 7. EXPORTACIÓN DEL EXCEL DE AUDITORÍA
# =============================================================================

def exportar_auditoria_excel(
    df_vuelos_crudo: pd.DataFrame,
    df_res: pd.DataFrame,
    df_slots: pd.DataFrame,
    path: str,
) -> None:
    """
    Genera el Excel de auditoría con 5 pestañas:
        1_Datos_Crudos:   Todos los vuelos sin procesar (para trazabilidad).
        2_Regulacion_GDP: Vuelos con su slot asignado y retraso desglosado.
        3_Matriz_Slots:   Todos los slots generados y si están ocupados.
        4_KPIs_Avanzados: Métricas operacionales, económicas y ambientales.
        5_Equidad_RBS:    Retraso agregado por aerolínea.

    Args:
        df_vuelos_crudo: DataFrame original pre-GDP (para la pestaña de trazabilidad).
        df_res:          DataFrame con resultados del GDP y retrasos calculados.
        df_slots:        DataFrame con la matriz de slots generados.
        path:            Ruta completa del archivo .xlsx a generar.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        with pd.ExcelWriter(path, engine='openpyxl') as writer:

            # --- PESTAÑA 1: Datos sin tocar ---
            # Permite comparar la entrada con la salida para auditar el proceso.
            df_vuelos_crudo.to_excel(writer, sheet_name='1_Datos_Crudos', index=False)

            # --- PESTAÑA 2: Regulación GDP ---
            # Solo las columnas relevantes, renombradas para claridad del receptor.
            cols_reg = [
                'ARCID', 'airline', 'ADEP', 'ATYP', 'recat', 'is_ecac',
                'distancia_km', 'minutes_eta', 'assigned_slot',
                'total_delay', 'air_delay', 'ground_delay', 'flight_status',
            ]
            df_export = (
                df_res[cols_reg]
                .copy()
                .sort_values('minutes_eta')
                .rename(columns={
                    'minutes_eta':   'ETA_Prog',
                    'assigned_slot': 'ATA_Real',
                })
            )
            df_export.to_excel(writer, sheet_name='2_Regulacion_GDP', index=False)

            # --- PESTAÑA 3: Matriz de slots ---
            df_slots.to_excel(writer, sheet_name='3_Matriz_Slots', index=False)

            # --- PESTAÑA 4: KPIs ---
            # Usamos calcular_kpis_economicos() — misma fuente que los gráficos.
            kpis = calcular_kpis_economicos(df_res)
            candidatos = df_res[df_res['flight_status'] == 'GPD CANDIDATE']
            exentos    = df_res[df_res['flight_status'] != 'GPD CANDIDATE']

            kpis_df = pd.DataFrame({
                'Métrica Operacional / Ambiental': [
                    'Vuelos Regulados (Candidatos GDP)',
                    'Vuelos Exentos',
                    'Retraso Medio (min/vuelo)',
                    'Desviación Estándar Retraso (min)',
                    'Retraso Máximo (min)',
                    '--- ECONOMÍA Y MEDIO AMBIENTE ---',
                    'Coste Total: Escenario Do-Nothing (€)',
                    'Coste Total: Escenario GDP (€)',
                    'Ahorro Económico Estimado (€)',
                    'Emisiones CO2: Escenario Do-Nothing (kg)',
                    'Emisiones CO2: Escenario GDP (kg)',
                    'CO2 Ahorrado (kg)',
                ],
                'Valor': [
                    len(candidatos),
                    len(exentos),
                    round(df_res['total_delay'].mean(), 2),
                    round(df_res['total_delay'].std(), 2),
                    round(df_res['total_delay'].max(), 2),
                    '',
                    kpis['cost_baseline'],
                    kpis['cost_gdp'],
                    kpis['cost_savings'],
                    kpis['co2_baseline'],
                    kpis['co2_gdp'],
                    kpis['co2_savings'],
                ],
            })
            kpis_df.to_excel(writer, sheet_name='4_KPIs_Avanzados', index=False)

            # --- PESTAÑA 5: Equidad RBS por aerolínea ---
            eq_df = (
                df_res.groupby('airline')
                .agg(
                    Total_Vuelos=('ARCID', 'count'),
                    Retraso_Total_min=('total_delay', 'sum'),
                    Retraso_Medio_min=('total_delay', 'mean'),
                    Retraso_Maximo_min=('total_delay', 'max'),
                )
                .reset_index()
                .sort_values('Total_Vuelos', ascending=False)
            )
            eq_df.to_excel(writer, sheet_name='5_Equidad_RBS', index=False)

        print(f"✅ Excel de auditoría generado en: {path}")

    except PermissionError:
        # Ocurre cuando el archivo está abierto en Excel — Windows lo bloquea.
        print("⚠️  ERROR: Cierra el archivo Excel antes de ejecutar el script.")


# =============================================================================
# 8. ORQUESTADOR PRINCIPAL DEL MÓDULO
# =============================================================================

def ejecutar_nucleo_gdp(
    df_vuelos: pd.DataFrame,
    params: dict,
    ) -> dict:
    """
    Orquestador de la Fase 2: llama a todas las funciones en el orden correcto.

    Flujo:
        1. Simula las curvas de Newell para obtener el timeline y h_noreg.
        2. Etiqueta cada vuelo: candidato GDP o exento (y de qué tipo).
        3. Genera la matriz de slots según la capacidad del GDP.
        4. Asigna slots a los vuelos usando el algoritmo RBS.
        5. Calcula los retrasos desglosados (aire vs. tierra).
        6. Genera los 4 gráficos de salida.

    Args:
        df_vuelos:    DataFrame limpio de la Fase 1.
        params:       Diccionario de parámetros del escenario GDP.
        output_paths: Rutas de los archivos de imagen de salida.

    Returns:
        Diccionario con todos los resultados para que mine_lib.py
        pueda acceder a ellos y generar los entregables finales.
    """
    # PASO 1: Curvas de Newell
    timeline, h_noreg = simular_curvas_newell(df_vuelos, params)

    # PASO 2: Etiquetado de vuelos
    df_v = etiquetar_vuelos_gdp(df_vuelos, params['H_START'])

    # PASO 3: Generación de la matriz de slots
    # Empezamos en H_START y añadimos slots según el tipo de capacidad activa.
    # Paramos cuando la cola se disuelve (h_noreg) o llegamos al final del día.
    slots_list = []
    t = params['H_START']
    while t < min(h_noreg + 1000, 1440):
        slots_list.append(round(t, 4))
        t += params['SLOT_RED'] if t < params['H_END'] else params['SLOT_NOM']

    df_slots = pd.DataFrame({
        'slot_start_min': slots_list,
        'occupied':       False,
        'flight_id':      None,
    })

    # PASO 4: Asignación RBS
    # Solo procesamos vuelos dentro de la ventana GDP (ETA ≥ H_START)
    df_en_ventana = df_v[df_v['minutes_eta'] >= params['H_START']].copy()
    df_res = asignar_slots_rbs(df_en_ventana, df_slots)

    # PASO 5: Cálculo de retrasos
    df_res = calcular_delays(df_res)


    return {
        'vuelos_asignados': df_res,
        'vuelos_crudos':    df_vuelos,
        'slots':            df_slots,
        'timeline':         timeline,
        'h_noreg':          h_noreg,
        'params':           params,
    }


# =============================================================================
# MODO DEBUG — Ejecutar directamente para probar este módulo de forma aislada.
#   python lib_gdp_core.py
# =============================================================================
if __name__ == "__main__":
    print("🛠️  MODO DEBUG: Probando lib_gdp_core.py de forma independiente...")
    import lib_data_prep as prep

    base       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos   = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota    = os.path.join(base, 'data/raw/fleet_cat_seat.csv')
    p_debug    = os.path.join(base, 'debug/DEBUG_02_etiquetado_gdp.xlsx')

    params    = {'H_START': CFG.H_START, 'H_END': CFG.H_END,
                 'SLOT_NOM': CFG.SLOT_NOM, 'SLOT_RED': CFG.SLOT_RED,
                 'AAR': CFG.AAR, 'PAAR': CFG.PAAR}
    df_vuelos = prep.preparar_vuelos(p_vuelos, p_flota)
    df_etiq   = etiquetar_vuelos_gdp(df_vuelos, CFG.H_START)

    os.makedirs(os.path.dirname(p_debug), exist_ok=True)
    cols_debug = ['ARCID', 'airline', 'ADEP', 'is_ecac', 'distancia_km', 'is_departed', 'flight_status']
    df_etiq[cols_debug].to_excel(p_debug, index=False)

    print(f"✅ Excel de etiquetado generado en: {p_debug}")
    print("   → Ábrelo para verificar que los filtros ECAC, distancia y Airborne son correctos.")