# =============================================================================
# src/lib_ghp_solver.py
# WP3: Ground Holding Problem (GHP) — Solver de Programación Lineal Entera
#
# CONTEXTO:
#   El GHP asigna vuelos a slots de llegada minimizando una función de coste.
#   A diferencia del RBS (FIFO), el LP puede priorizar vuelos más costosos
#   asignándoles slots más tempranos aunque lleguen más tarde.
#
# FORMULACIÓN (Ball, 2007):
#   Variables:  x_{f,t} ∈ {0,1}  →  1 si el vuelo f se asigna al slot t
#   Objetivo:   min Σ_f Σ_t  c_{f,t} · x_{f,t}
#   Restricciones:
#     (1) Capacidad:  Σ_f x_{f,t} ≤ b_t   para todo t  (un slot = un avión)
#     (2) Asignación: Σ_{t≥ETA(f)} x_{f,t} = 1  para todo f  (cada vuelo llega una vez)
#     (3) No antes de ETA: la restricción (2) empieza desde t=ETA(f)
#     (4) Exentos: tienen fijado su slot, no pueden mejorar su posición
#     (5) Cap air delay: exentos no pueden tener más de MAX_AIR_DELAY minutos
#
# FUNCIONES DE COSTE IMPLEMENTADAS:
#   - Task 1 (validación): c_{f,t} = 1 · (t - ETA(f))  →  r_f = 1 para todos
#   - Task 2 (emisiones):  c_{f,t} = emissions_per_min_f · (t - ETA(f))
#   - Task 3 (coste real): c_{f,t} = r_f(t) · (t - ETA(f))
#       donde r_f(t) depende de:
#         a) Pasajeros × load factor (conexiones perdidas si delay > umbral)
#         b) Turn-around time (reactionary delay si delay > TAT disponible)
#
# HIPÓTESIS (justificadas en el informe):
#   - Load factor europeo: 83,5% (IATA Annual Review 2024, dato para Europa)
#   - Conexiones perdidas: 20% de pasajeros son de conexión en LEBL
#     (Fuente: AENA estadísticas LEBL 2024 — LEBL tiene ~18-22% transit PAX)
#   - Coste por pasajero perdiendo conexión: 200 EUR
#     (Eurocontrol PRR 2023: EC261 + re-routing + reputación media europea)
#   - Turn-around mínimo (TAT): 45 min para narrow-body, 60 min para wide-body
#     (IATA Airport Handling Manual, AHM 810; confirmado en literatura)
#   - Coste reactionary: 65 EUR/min (COST_AIR_MIN × 1.3 por efecto cascada)
#     (Cook et al. 2015, EUROCONTROL Cost of Delay v4.1, factor reactionary)
#   - MAX_AIR_DELAY: 90 min (límite operativo — más de 90 min en holding
#     implica desvío a alternativo; hipótesis conservadora basada en
#     Eurocontrol Network Manager Operations Centre guidelines)
#   - Granularidad de slots: 1 minuto (igual que WP2 para comparabilidad)
# =============================================================================

import numpy as np
import pandas as pd
import pulp

from config import (
    CFG, FS_CANDIDATE, FS_AIRBORNE, FS_INTERNATIONAL, FS_DISTANCE,
    COST_AIR_MIN, COST_GND_MIN,
)
from emissions_fuel_model import compute_co2_ask

# =============================================================================
# CONSTANTES WP3
# =============================================================================

# Límite máximo de air delay para vuelos exentos (minutos).
# Justificación: más de 90 min en holding implica desvío a alternativo.
# Fuente: Eurocontrol NMOC operational guidelines.
MAX_AIR_DELAY_MIN = 90

# Load factor europeo (fracción de asientos ocupados).
# Fuente: IATA Annual Review 2024, p.18 — promedio europeo 2024: 84.1%
LOAD_FACTOR_EU = 0.835

# Fracción de pasajeros de conexión en LEBL.
# Fuente: AENA Informe Anual LEBL 2024 — tráfico de tránsito ~20%.
FRAC_CONNECTING_PAX = 0.20

# Coste por pasajero que pierde su conexión (EUR).
# Incluye: EC261/2004 compensación media + re-routing + coste reputacional.
# Fuente: Eurocontrol PRR 2023, Cook et al. 2015.
COST_LOST_CONNECTION_EUR = 200

# Turn-around time mínimo por categoría (minutos).
# Fuente: IATA AHM 810; valores conservadores para narrow/wide body.
# Si el delay supera el TAT disponible, genera reactionary delay.
TAT_MIN = {
    'narrow':  45,   # A320, B737 y similares (RECAT D, E, F)
    'wide':    60,   # A330, B777 y similares (RECAT A, B, C)
}

# Multiplicador de coste para reactionary delay.
# Fuente: Cook et al. 2015, EUROCONTROL Cost of Delay v4.1.
# El reactionary delay cuesta más porque afecta a múltiples vuelos.
REACTIONARY_COST_MULTIPLIER = 1.3

# Umbral de delay "largo" que activa el multiplicador de coste no lineal.
# Justificación: vuelos dentro de OTP (<15 min) tienen coste bajo.
# Los que superan el umbral entran en zona de coste acelerado.
# Fuente: Pilon et al. 2019 — "margin of manoeuvre" concept.
OTP_THRESHOLD_MIN = 15


# =============================================================================
# PASO 1: CALCULAR COEFICIENTES r_f PARA CADA VUELO
# =============================================================================

def calcular_rf_unitario(df_vuelos: pd.DataFrame) -> pd.Series:
    """
    Task 1 (validación): r_f = 1 para todos los vuelos.

    Con esta configuración, el coste total = retraso total en minutos.
    El GHP con r=1 debe dar el mismo coste total que el GDP (RBS),
    ya que ambos minimizan el delay total con costes iguales.
    Esto sirve para verificar que el solver LP está correctamente codificado.

    Returns:
        Series indexada por el índice del DataFrame, con r_f = 1.0.
    """
    return pd.Series(1.0, index=df_vuelos.index)


def calcular_rf_emisiones(df_vuelos: pd.DataFrame) -> pd.Series:
    """
    Task 2: r_f = emisiones de CO2 por minuto de retraso de cada vuelo.

    LÓGICA:
        El modelo de Delgado et al. (2025) calcula el CO2 proporcional
        a la distancia y asientos. Las emisiones por minuto se obtienen
        dividiendo el CO2 total del vuelo por su duración.

        Delay_emissions_{f,t} = emissions_per_min_f × (t - ETA(f))

        Con esto, el LP minimizará las emisiones del retraso priorizando
        vuelos con menores emisiones por minuto (vuelos largos con muchos
        asientos emiten menos por ASK que vuelos cortos).

    Returns:
        Series con las emisiones de CO2 en kg/min para cada vuelo.
    """
    def _co2_per_min(fila):
        distancia  = fila.get('distancia_km', 0)
        asientos   = fila.get('size_seats_avg', 180)
        duracion   = fila.get('duracion_vuelo_min', 60)

        if distancia <= 0 or pd.isna(asientos) or duracion <= 0:
            return 0.1  # valor mínimo por defecto

        co2_ask = compute_co2_ask(distancia, int(asientos), force=True)
        co2_total_kg = co2_ask * distancia * asientos / 1000
        return max(co2_total_kg / duracion, 0.01)

    return df_vuelos.apply(_co2_per_min, axis=1)


def calcular_rf_coste(df_vuelos: pd.DataFrame) -> pd.Series:
    """
    Task 3: r_f(t) — coeficiente de coste no lineal por vuelo.

    El coeficiente r_f captura la no-linealidad del coste con el delay:
    vuelos con más pasajeros de conexión y menos TAT disponible son
    más costosos por minuto de retraso, especialmente en delays largos.

    COMPONENTES DE r_f:
    1. Coste base por minuto (COST_AIR_MIN o COST_GND_MIN)
    2. Coste de pasajeros perdiendo conexión:
         pax_connecting × COST_LOST_CONNECTION / (delay donde se pierden)
    3. Coste de reactionary delay si el delay supera el TAT disponible

    NOTA: En el LP usamos r_f como escalar (no función de t) porque
    PuLP necesita coeficientes lineales. Para capturar la no-linealidad
    usamos r_f evaluado en el punto de quiebre (OTP_THRESHOLD_MIN),
    de modo que vuelos con más impacto post-umbral tienen mayor r_f.
    Esto es consistente con la formulación c_{f,t} = r_f(t)·(t-ETA(f))
    donde r_f(t) se aproxima por tramos (Ball, 2007).

    Returns:
        Series con r_f para cada vuelo (EUR/min de delay).
    """
    rf = pd.Series(index=df_vuelos.index, dtype=float)

    for idx, fila in df_vuelos.iterrows():
        asientos   = fila.get('size_seats_avg', 180)
        if pd.isna(asientos):
            asientos = 180

        # --- Pasajeros y conexiones ---
        pax_total      = int(asientos * LOAD_FACTOR_EU)
        pax_connecting = int(pax_total * FRAC_CONNECTING_PAX)

        # Coste por minuto base (ya sea aire o tierra según status)
        # Para candidatos GDP: el delay es en tierra
        # Para exentos: el delay es en aire
        es_candidato = (fila.get('flight_status', '') == FS_CANDIDATE)
        coste_base_min = COST_GND_MIN if es_candidato else COST_AIR_MIN

        # --- Turn-around y reactionary ---
        # Determinamos si el avión es narrow o wide body según RECAT
        recat = str(fila.get('recat', 'D'))
        es_wide = recat in ('A', 'B', 'C')
        tat_min_avion = TAT_MIN['wide'] if es_wide else TAT_MIN['narrow']

        # Turn-around disponible: tiempo entre llegada y siguiente salida.
        # Usamos el campo 'tat_disponible' si existe, sino asumimos TAT mínimo + 30 min
        # (hipótesis conservadora: la rotación media tiene 15-30 min de margen).
        tat_disponible = fila.get('tat_disponible', tat_min_avion + 20)
        margen_tat = max(tat_disponible - tat_min_avion, 0)

        # Un delay > margen_tat genera reactionary delay.
        # El coste de reactionary se añade al r_f como penalización.
        if margen_tat < OTP_THRESHOLD_MIN:
            # Poco margen: alta probabilidad de reactionary → coste más alto
            factor_reactionary = REACTIONARY_COST_MULTIPLIER
        else:
            factor_reactionary = 1.0

        # --- Coste de conexiones perdidas ---
        # Se activa si el delay supera ~45 min (tiempo mínimo de transferencia MCT)
        # Aquí lo incluimos como coste por minuto a partir del OTP threshold.
        # Por encima del OTP, cada minuto adicional pone en riesgo una fracción
        # de los pasajeros de conexión.
        # Coste adicional por minuto = pax_connecting × EUR / window
        ventana_conexion = 60  # minutos de ventana media de conexión en LEBL
        coste_conexion_min = (pax_connecting * COST_LOST_CONNECTION_EUR) / ventana_conexion

        # --- r_f compuesto ---
        # Suma de: coste operativo base + conexiones perdidas (amortizado)
        # Multiplicado por el factor de reactionary si hay poco TAT
        rf_valor = (coste_base_min + coste_conexion_min) * factor_reactionary

        rf[idx] = round(rf_valor, 4)

    return rf


# =============================================================================
# PASO 2: CALCULAR TAT DISPONIBLE DESDE EL CSV (usando Registration Mark)
# =============================================================================

def enriquecer_con_tat(df_vuelos: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula el turn-around time disponible para cada vuelo usando el RM.

    Para cada vuelo de llegada con un Registration Mark (RM), buscamos
    si ese mismo avión tiene una salida posterior en el dataset.
    Si la hay, el TAT disponible = ETD_salida - ETA_llegada.
    Si no hay rotación conocida, asumimos TAT mínimo + 30 min.

    Referencia: LEBL data CSV contiene columna 'RM' (registration mark).
    Eurocontrol Data Snapshot 20: ~57% de los retrasos reactionary provienen
    de rotaciones con TAT ajustado.

    Args:
        df_vuelos: DataFrame con columnas RM, minutes_eta, minutes_etd, ADES.

    Returns:
        DataFrame con columna 'tat_disponible' añadida.
    """
    df = df_vuelos.copy()
    df['tat_disponible'] = np.nan

    # Solo calculamos TAT para vuelos que llegan a LEBL (los regulados)
    llegadas = df[df['ADES'] == 'LEBL'].copy()

    # Agrupamos por RM para encontrar pares llegada-salida del mismo avión
    if 'RM' in df.columns:
        for rm, grupo in df.groupby('RM'):
            if pd.isna(rm) or rm == '':
                continue

            vuelos_rm = grupo.sort_values('minutes_eta')
            # Buscamos llegadas a LEBL seguidas de salidas desde LEBL
            llegadas_rm = vuelos_rm[vuelos_rm['ADES'] == 'LEBL']
            salidas_rm  = vuelos_rm[vuelos_rm['ADEP'] == 'LEBL']

            for idx_ll, vuelo_llegada in llegadas_rm.iterrows():
                eta = vuelo_llegada['minutes_eta']
                # La siguiente salida del mismo avión desde LEBL
                salidas_post = salidas_rm[salidas_rm['minutes_etd'] > eta]
                if not salidas_post.empty:
                    etd_siguiente = salidas_post['minutes_etd'].min()
                    tat = etd_siguiente - eta
                    df.at[idx_ll, 'tat_disponible'] = max(tat, 0)

    # Para vuelos sin rotación conocida, asumimos TAT mínimo + 20 min
    recat_col = df['recat'].fillna('D')
    tat_default = recat_col.apply(
        lambda r: TAT_MIN['wide'] + 20 if r in ('A', 'B', 'C')
                  else TAT_MIN['narrow'] + 20
    )
    df['tat_disponible'] = df['tat_disponible'].fillna(tat_default)

    return df


# =============================================================================
# PASO 3: SOLVER GHP — PROGRAMACIÓN LINEAL ENTERA BINARIA
# =============================================================================

def resolver_ghp(
    df_candidatos: pd.DataFrame,
    df_exentos: pd.DataFrame,
    slots_disponibles: list,
    rf_series: pd.Series,
    nombre_problema: str = 'GHP',
    max_air_delay: int = MAX_AIR_DELAY_MIN,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Resuelve el GHP como un problema de programación lineal entera binaria.

    FORMULACIÓN (Ball, 2007):
        Variables: x_{f,t} ∈ {0,1}
        Objetivo:  min Σ_f Σ_t  c_{f,t} · x_{f,t}
        donde      c_{f,t} = r_f · (t - ETA(f))  para t ≥ ETA(f)

        Restricciones:
          (1) Σ_f x_{f,t} ≤ 1          para todo t   (1 vuelo por slot)
          (2) Σ_{t≥ETA(f)} x_{f,t} = 1  para todo f   (cada vuelo 1 slot)
          (3) Los exentos tienen su slot fijado (no son variables del LP)
          (4) Air delay de exentos ≤ max_air_delay

    NOTA SOBRE EXENTOS:
        Los vuelos exentos (airborne, internacionales, lejanos) no pueden
        recibir ground delay. Se les asigna el primer slot disponible ≥ ETA
        con la restricción de que su air delay ≤ max_air_delay.
        Si no hay slot disponible dentro del límite, se les asigna el más
        cercano (el sistema no puede hacer más — ya están en vuelo).

    Args:
        df_candidatos:    Vuelos regulables (GDP CANDIDATE).
        df_exentos:       Vuelos exentos (airborne, international, distance).
        slots_disponibles: Lista de tiempos de slot en minutos.
        rf_series:        Coeficiente r_f por vuelo (índice = índice del df).
        nombre_problema:  Nombre del problema para el solver (debug).
        max_air_delay:    Límite de air delay para exentos (min).
        verbose:          Si True, imprime info del solver.

    Returns:
        DataFrame combinado con columnas assigned_slot, total_delay,
        air_delay, ground_delay.
    """
    slots = sorted(slots_disponibles)
    n_slots = len(slots)

    # -------------------------------------------------------------------------
    # PASO 3a: Asignar slots a exentos primero (tienen prioridad operacional)
    # -------------------------------------------------------------------------
    slots_ocupados = set()
    asignaciones_exentos = {}

    df_exentos_sorted = df_exentos.sort_values('minutes_eta')
    for idx, vuelo in df_exentos_sorted.iterrows():
        eta = vuelo['minutes_eta']
        # Slots disponibles para este exento: >= ETA y no ocupados
        slots_elegibles = [
            s for s in slots
            if s >= eta and s not in slots_ocupados
            and (s - eta) <= max_air_delay
        ]
        if slots_elegibles:
            slot_asignado = slots_elegibles[0]
        else:
            # Si no hay slot dentro del límite de air delay,
            # asignamos el primero disponible (fuerza mayor — ya está en vuelo)
            slots_sin_cap = [s for s in slots if s >= eta and s not in slots_ocupados]
            slot_asignado = slots_sin_cap[0] if slots_sin_cap else eta

        asignaciones_exentos[idx] = slot_asignado
        slots_ocupados.add(slot_asignado)

    # Slots restantes para los candidatos GDP
    slots_para_candidatos = [s for s in slots if s not in slots_ocupados]

    # -------------------------------------------------------------------------
    # PASO 3b: Formular el LP para los candidatos GDP
    # -------------------------------------------------------------------------
    if df_candidatos.empty or not slots_para_candidatos:
        # No hay candidatos o no quedan slots — devolvemos lo que tenemos
        df_res = _construir_resultado(
            df_candidatos, df_exentos,
            {}, asignaciones_exentos
        )
        return df_res

    candidatos_idx = list(df_candidatos.index)
    n_candidatos = len(candidatos_idx)
    n_slots_c = len(slots_para_candidatos)

    if verbose:
        print(f"   [{nombre_problema}] {n_candidatos} candidatos, "
              f"{n_slots_c} slots disponibles")

    # Precalcular matriz de costes c[f][t] = r_f * max(0, slot_t - ETA_f)
    # Solo para t >= ETA(f) (restricción: no llegar antes de ETA)
    eta_map = df_candidatos['minutes_eta'].to_dict()

    # Crear problema LP
    prob = pulp.LpProblem(nombre_problema, pulp.LpMinimize)

    # Variables binarias x[f][t]
    x = {}
    for f_idx in candidatos_idx:
        eta_f = eta_map[f_idx]
        rf_f  = rf_series.get(f_idx, 1.0)
        for t_idx, t_val in enumerate(slots_para_candidatos):
            if t_val >= eta_f:
                coste = rf_f * (t_val - eta_f)
                x[(f_idx, t_idx)] = pulp.LpVariable(
                    f"x_{f_idx}_{t_idx}",
                    cat='Binary'
                )

    # Función objetivo: min Σ c_{f,t} · x_{f,t}
    prob += pulp.lpSum(
        rf_series.get(f_idx, 1.0) * (slots_para_candidatos[t_idx] - eta_map[f_idx])
        * x[(f_idx, t_idx)]
        for (f_idx, t_idx) in x
    )

    # Restricción (1): capacidad — máximo 1 vuelo por slot
    for t_idx in range(n_slots_c):
        vars_en_slot = [x[(f, t)] for (f, t) in x if t == t_idx]
        if vars_en_slot:
            prob += pulp.lpSum(vars_en_slot) <= 1, f"cap_slot_{t_idx}"

    # Restricción (2): cada candidato debe recibir exactamente 1 slot
    for f_idx in candidatos_idx:
        vars_vuelo = [x[(f, t)] for (f, t) in x if f == f_idx]
        if vars_vuelo:
            prob += pulp.lpSum(vars_vuelo) == 1, f"asig_vuelo_{f_idx}"
        # Si no hay ninguna variable (ningún slot >= ETA), el vuelo queda sin slot
        # Esto no debería ocurrir si la ventana de slots es suficientemente grande

    # Resolver
    solver = pulp.PULP_CBC_CMD(msg=0)  # msg=0 suprime output del solver
    prob.solve(solver)

    if verbose:
        print(f"   [{nombre_problema}] Status: {pulp.LpStatus[prob.status]}")
        print(f"   [{nombre_problema}] Coste óptimo: {pulp.value(prob.objective):.2f}")

    # Extraer solución
    asignaciones_candidatos = {}
    for (f_idx, t_idx), var in x.items():
        if pulp.value(var) is not None and pulp.value(var) > 0.5:
            asignaciones_candidatos[f_idx] = slots_para_candidatos[t_idx]

    # -------------------------------------------------------------------------
    # PASO 3c: Construir DataFrame de resultados
    # -------------------------------------------------------------------------
    df_res = _construir_resultado(
        df_candidatos, df_exentos,
        asignaciones_candidatos, asignaciones_exentos
    )

    return df_res


def _construir_resultado(
    df_candidatos: pd.DataFrame,
    df_exentos: pd.DataFrame,
    asig_candidatos: dict,
    asig_exentos: dict,
) -> pd.DataFrame:
    """
    Combina candidatos y exentos en un único DataFrame con delays calculados.
    """
    partes = []

    # Candidatos
    if not df_candidatos.empty:
        df_c = df_candidatos.copy()
        df_c['assigned_slot'] = df_c.index.map(asig_candidatos)
        df_c['total_delay']   = (df_c['assigned_slot'] - df_c['minutes_eta']).clip(lower=0)
        df_c['ground_delay']  = df_c['total_delay']
        df_c['air_delay']     = 0.0
        partes.append(df_c)

    # Exentos
    if not df_exentos.empty:
        df_e = df_exentos.copy()
        df_e['assigned_slot'] = df_e.index.map(asig_exentos)
        df_e['total_delay']   = (df_e['assigned_slot'] - df_e['minutes_eta']).clip(lower=0)
        df_e['air_delay']     = df_e['total_delay']
        df_e['ground_delay']  = 0.0
        partes.append(df_e)

    if not partes:
        return pd.DataFrame()

    return pd.concat(partes).sort_values('minutes_eta').reset_index(drop=False)


# =============================================================================
# PASO 4: ORQUESTADOR WP3 — EJECUTAR LOS 3 ESCENARIOS GHP
# =============================================================================

def ejecutar_ghp_completo(
    df_vuelos_etiquetados: pd.DataFrame,
    slots_disponibles: list,
    params: dict,
    verbose: bool = True,
) -> dict:
    """
    Ejecuta los 3 escenarios GHP del WP3 y devuelve los resultados.

    ESCENARIOS:
        'task1_validation': r_f = 1 (validación — debe coincidir con GDP)
        'task2_emissions':  minimizar emisiones CO2 del retraso
        'task3_cost':       minimizar coste real (pasajeros + reactionary)

    Args:
        df_vuelos_etiquetados: DataFrame con flight_status ya asignado.
        slots_disponibles:     Lista de slots en minutos (igual que WP2).
        params:                Parámetros del GDP (H_START, etc.).
        verbose:               Si True, imprime progreso.

    Returns:
        Diccionario con los resultados de cada escenario.
    """
    # Enriquecer con TAT disponible (necesario para Task 3)
    df_enriched = enriquecer_con_tat(df_vuelos_etiquetados)

    # Separar candidatos y exentos
    # Solo procesamos vuelos dentro de la ventana GDP
    h_start = params['H_START']
    df_en_ventana = df_enriched[df_enriched['minutes_eta'] >= h_start].copy()

    df_candidatos = df_en_ventana[df_en_ventana['flight_status'] == FS_CANDIDATE].copy()
    df_exentos    = df_en_ventana[df_en_ventana['flight_status'] != FS_CANDIDATE].copy()

    if verbose:
        print(f"   GHP: {len(df_candidatos)} candidatos, {len(df_exentos)} exentos")
        print(f"        {len(slots_disponibles)} slots disponibles")

    resultados = {}

    # -------------------------------------------------------------------------
    # Task 1: Validación — r_f = 1
    # -------------------------------------------------------------------------
    if verbose:
        print("\n   [Task 1] Validación: r_f = 1 (debe igualar coste GDP)...")

    rf_unitario = calcular_rf_unitario(df_en_ventana)
    resultados['task1_validation'] = resolver_ghp(
        df_candidatos.copy(),
        df_exentos.copy(),
        slots_disponibles,
        rf_unitario,
        nombre_problema='GHP_Task1_Validation',
        verbose=verbose,
    )

    # -------------------------------------------------------------------------
    # Task 2: Minimizar emisiones
    # -------------------------------------------------------------------------
    if verbose:
        print("\n   [Task 2] Minimizar emisiones CO2 del retraso...")

    rf_emisiones = calcular_rf_emisiones(df_en_ventana)
    resultados['task2_emissions'] = resolver_ghp(
        df_candidatos.copy(),
        df_exentos.copy(),
        slots_disponibles,
        rf_emisiones,
        nombre_problema='GHP_Task2_Emissions',
        verbose=verbose,
    )

    # -------------------------------------------------------------------------
    # Task 3: Minimizar coste real (r_f con pasajeros + reactionary)
    # -------------------------------------------------------------------------
    if verbose:
        print("\n   [Task 3] Minimizar coste real (pasajeros + reactionary)...")

    rf_coste = calcular_rf_coste(df_en_ventana)
    resultados['task3_cost'] = resolver_ghp(
        df_candidatos.copy(),
        df_exentos.copy(),
        slots_disponibles,
        rf_coste,
        nombre_problema='GHP_Task3_Cost',
        verbose=verbose,
    )

    # Guardamos también los rf para poder calcular KPIs después
    resultados['rf_unitario']  = rf_unitario
    resultados['rf_emisiones'] = rf_emisiones
    resultados['rf_coste']     = rf_coste

    return resultados


# =============================================================================
# PASO 5: KPIs WP3
# =============================================================================

def calcular_kpis_ghp(
    df_ghp: pd.DataFrame,
    rf_series: pd.Series,
    nombre_escenario: str = 'GHP',
) -> dict:
    """
    Calcula los KPIs del WP3 para un escenario GHP.

    KPIs calculados (Task 4):
        - Retraso total, medio, air/ground
        - CO2 del retraso (aire y tierra)
        - Coste del retraso (EUR) usando los r_f
        - Nº vuelos retrasados, distribución por aerolínea
        - Air delay check (¿hay air delays infeasibles > MAX_AIR_DELAY?)

    Args:
        df_ghp:          Resultado del GHP (output de resolver_ghp).
        rf_series:       Coeficientes r_f usados en este escenario.
        nombre_escenario: Nombre para el log.

    Returns:
        Diccionario con todos los KPIs.
    """
    if df_ghp.empty:
        return {}

    df = df_ghp.copy()

    # Completar columnas necesarias si faltan
    if 'total_delay' not in df.columns:
        df['total_delay'] = 0.0
    if 'air_delay' not in df.columns:
        df['air_delay'] = 0.0
    if 'ground_delay' not in df.columns:
        df['ground_delay'] = 0.0

    # --- Retrasos ---
    total_delay    = df['total_delay'].sum()
    mean_delay     = df['total_delay'].mean()
    air_delay      = df['air_delay'].sum()
    ground_delay   = df['ground_delay'].sum()
    n_delayed      = (df['total_delay'] > 0).sum()
    n_flights      = len(df)

    # --- Check feasibilidad air delay ---
    max_air_obs    = df['air_delay'].max()
    infeasible_air = (df['air_delay'] > MAX_AIR_DELAY_MIN).sum()

    # --- CO2 del retraso ---
    dur = df.get('duracion_vuelo_min', pd.Series(60, index=df.index)).clip(lower=1)
    co2_base = df.get('co2_kg_vuelo', pd.Series(0, index=df.index))

    co2_aire_delay   = (co2_base * (df['air_delay']   / dur)).sum()
    co2_tierra_delay = (co2_base * (df['ground_delay'] / dur)).sum()
    co2_total_delay  = co2_aire_delay + co2_tierra_delay

    # --- Coste del retraso usando r_f ---
    # c_{f,t} = r_f * delay_f
    idx_col = df.index if 'index' not in df.columns else df['index']
    coste_total = 0.0
    for i, row in df.iterrows():
        orig_idx = row.get('index', i)
        rf = rf_series.get(orig_idx, 1.0)
        coste_total += rf * row['total_delay']

    # --- KPIs por aerolínea (top 4) ---
    kpis_aerolinea = {}
    if 'airline' in df.columns:
        top_aerolineas = (
            df[df['total_delay'] > 0]
            .groupby('airline')
            .size()
            .nlargest(4)
            .index.tolist()
        )
        for al in top_aerolineas:
            sub = df[df['airline'] == al]
            kpis_aerolinea[al] = {
                'n_vuelos':      len(sub),
                'delay_medio':   round(sub['total_delay'].mean(), 2),
                'delay_total':   round(sub['total_delay'].sum(), 2),
                'delay_std':     round(sub['total_delay'].std(), 2),
            }

    return {
        'escenario':          nombre_escenario,
        'n_flights':          n_flights,
        'n_delayed':          int(n_delayed),
        'total_delay_min':    round(total_delay, 2),
        'mean_delay_min':     round(mean_delay, 2),
        'air_delay_min':      round(air_delay, 2),
        'ground_delay_min':   round(ground_delay, 2),
        'max_air_delay_obs':  round(max_air_obs, 2),
        'infeasible_air':     int(infeasible_air),
        'co2_aire_delay_kg':  round(co2_aire_delay, 2),
        'co2_tierra_delay_kg':round(co2_tierra_delay, 2),
        'co2_total_delay_kg': round(co2_total_delay, 2),
        'coste_delay_eur':    round(coste_total, 2),
        'kpis_aerolinea':     kpis_aerolinea,
    }


# =============================================================================
# MODO DEBUG
# =============================================================================

if __name__ == '__main__':
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import lib_data_prep as prep
    import lib_gdp_core  as gdp

    print("🛠️  MODO DEBUG: lib_ghp_solver.py")
    base     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota  = os.path.join(base, 'data/raw/fleet_cat_seat.csv')

    params    = CFG.to_params_dict()
    df_vuelos = prep.preparar_vuelos(p_vuelos, p_flota)

    # Usar mismos slots y etiquetado que WP2
    resultados_gdp = gdp.ejecutar_nucleo_gdp(df_vuelos, params)
    df_etiquetado  = resultados_gdp['vuelos_asignados']
    slots_list     = list(resultados_gdp['slots']['slot_start_min'])

    # Ejecutar GHP
    resultados_ghp = ejecutar_ghp_completo(
        df_etiquetado, slots_list, params, verbose=True
    )
    

    # Verificar Task 1
    df_val = resultados_ghp['task1_validation']
    rf_1   = resultados_ghp['rf_unitario']
    kpis_val = calcular_kpis_ghp(df_val, rf_1, 'Task1_Validation')

    # Coste GDP con r=1
    coste_gdp = resultados_gdp['vuelos_asignados']['total_delay'].sum()

    print(f"\n{'='*50}")
    print(f"  VALIDACIÓN Task 1:")
    print(f"  Coste GHP (r=1): {kpis_val['coste_delay_eur']:.2f} min")
    print(f"  Delay total GHP: {kpis_val['total_delay_min']:.2f} min")
    print(f"  Delay total GDP: {coste_gdp:.2f} min")
    diff_pct = abs(kpis_val['total_delay_min'] - coste_gdp) / max(coste_gdp, 1) * 100
    print(f"  Diferencia: {diff_pct:.1f}%  {'✅ OK' if diff_pct < 5 else '⚠️ Revisar'}")
    print(f"{'='*50}")

    # KPIs Task 2 y Task 3
    for escenario, rf_key in [
        ('task2_emissions', 'rf_emisiones'),
        ('task3_cost',      'rf_coste'),
    ]:
        df_esc  = resultados_ghp[escenario]
        rf_esc  = resultados_ghp[rf_key]
        kpis    = calcular_kpis_ghp(df_esc, rf_esc, escenario)
        print(f"\n  {escenario.upper()}:")
        print(f"    Total delay:    {kpis['total_delay_min']:.1f} min")
        print(f"    Air delay:      {kpis['air_delay_min']:.1f} min")
        print(f"    Ground delay:   {kpis['ground_delay_min']:.1f} min")
        print(f"    CO2 delay:      {kpis['co2_total_delay_kg']:.1f} kg")
        print(f"    Coste delay:    {kpis['coste_delay_eur']:.0f} EUR")
        print(f"    Air infeasible: {kpis['infeasible_air']} vuelos")
