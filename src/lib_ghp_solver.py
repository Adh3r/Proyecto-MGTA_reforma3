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
#   - Load factor europeo: 83,7% (IATA Annual Review 2025, dato para Europa)
#   - Conexiones perdidas: 20% de pasajeros son de conexión en LEBL
#     (Fuente: AENA estadísticas LEBL 2024 — LEBL tiene ~18-22% transit PAX)
#   - Coste por pasajero perdiendo conexión: 200 EUR
#     (EC 261/2004 compensación media + re-routing; Cook & Tanner 2015 soft costs)
#   - Turn-around mínimo (TAT):
#       narrow 45 min, wide 80 min
#       (Eurocontrol Standard Inputs for Economic Analyses, §18, datos CODA ECAC)
#   - Coste reactionary: COST_AIR_MIN × 1.3 por efecto cascada
#     (Cook et al. 2015, EUROCONTROL Cost of Delay v4.1, Table 19)
#   - MAX_AIR_DELAY: 90 min (hipótesis conservadora; vuelos en holding >90 min
#     se desvían a alternativo en la mayoría de escenarios operativos europeos)
#   - Granularidad de slots: 1 minuto (igual que WP2 para comparabilidad)
#
# NOTA SOBRE EMISIONES EN HOLDING (FIX #1):
#   La tasa de CO₂/min usada en Task 2 se obtiene dividiendo el CO₂ total
#   del vuelo por su duración planificada (tasa media crucero).  Esto
#   sobreestima las emisiones reales del holding, que ocurre a menor potencia.
#   Se acepta como hipótesis conservadora documentada.  El mismo valor se usa
#   en los KPIs (calcular_kpis_ghp) para mantener coherencia con el objetivo LP.
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

# Límite máximo de air delay para vuelos (minutos).
MAX_AIR_DELAY_MIN = 90

# Load factor europeo (fracción de asientos ocupados).
# Fuente: IATA Annual Review 2025, promedio europeo 2025: 83,7%
LOAD_FACTOR_EU = 0.837

# Fracción de pasajeros de conexión en LEBL.
# Fuente: AENA estadísticas LEBL 2024 — tráfico de tránsito ~18-22% en LEBL.
# Se adopta 0.20 como valor central del rango observado.
FRAC_CONNECTING_PAX = 0.20

# Coste por pasajero que pierde su conexión (EUR).
# Incluye: EC261/2004 compensación media (~250-400 EUR ponderado por distancia)
# + re-routing + soft cost reputacional (Cook & Tanner 2015, Table 3).
# 200 EUR es una estimación conservadora de orden de magnitud.
COST_LOST_CONNECTION_EUR = 200

# Turn-around time mínimo por categoría (minutos).
# Fuente: Eurocontrol Standard Inputs for Economic Analyses, §18
#   "Turnaround time" — datos CODA (Central Office for Delay Analysis),
#   percentiles bajos del turnaround real en ECAC por categoría de aeronave.
#   https://ansperformance.eu/economics/cba/standard-inputs/latest/chapters/turnaround_time.html
TAT_MIN = {
    'narrow':  45,   # A320, B737 y similares (RECAT D, E, F) — mínimo proceso Medium
    'wide':    80,   # A330, B777 y similares (RECAT A, B, C) — mínimo proceso Heavy
}

# Multiplicador de coste para reactionary delay.
# Fuente: Cook et al. 2015, EUROCONTROL Cost of Delay v4.1, Table 19
#   "Basic reactionary multipliers by delay magnitude".
#   El valor 1.3 es una aproximación media para retrasos moderados (base scenario).
REACTIONARY_COST_MULTIPLIER = 1.3

# Umbral de delay "largo" que activa el multiplicador de coste no lineal.
# Justificación: definición OTP estándar IATA/CODA — vuelos con delay < 15 min
#   se contabilizan como "on-time".  La no-linealidad del coste a partir de
#   este umbral está documentada en Cook & Tanner 2015 v4.1 (step cost functions).
OTP_THRESHOLD_MIN = 15


# =============================================================================
# UTILIDAD INTERNA: CO₂ por minuto de vuelo
# =============================================================================

def _co2_per_min(distancia_km: float, asientos: int,
                 duracion_min: float) -> float:
    """
    Calcula el CO₂ medio por minuto de vuelo usando compute_co2_total_kg.

    FIX #1 — fuente única: tanto calcular_rf_emisiones (objetivo LP Task 2)
    como calcular_kpis_ghp (métricas de CO₂) llaman a esta función, garantizando
    que el valor optimizado y el reportado son coherentes.

    FIX #1 — hipótesis holding: se usa la tasa crucero media como proxy de la
    tasa de holding.  Esto sobreestima las emisiones reales del holding (menor
    potencia), pero es conservador y mantiene la linealidad del modelo LP.

    Args:
        distancia_km:  Distancia planificada del vuelo (km).
        asientos:      Número de asientos disponibles.
        duracion_min:  Duración planificada del vuelo (min).

    Returns:
        CO₂ en kg por minuto de vuelo (≥ 0.01 como suelo mínimo).
    """
    if distancia_km <= 0 or asientos <= 0 or duracion_min <= 0:
        return 0.01

    # FIX #2 — validación upstream: compute_co2_total_kg llama a _validate_inputs
    # que emite warnings para valores fuera de rango en lugar de fallar en silencio.
    try:
        co2_total = compute_co2_total_kg(distancia_km, int(asientos), force=True)
    except Exception:
        return 0.01

    return max(co2_total / duracion_min, 0.01)


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
    Task 2: r_f = CO₂ por minuto de retraso de cada vuelo (kg/min).

    LÓGICA:
        r_f = compute_co2_total_kg(distancia, asientos) / duracion_vuelo_min

        Delay_CO2_{f,t} = r_f × (t - ETA(f))   [kg]

        Con esto, el LP minimiza el CO₂ total del retraso, priorizando
        vuelos con menor tasa de emisión por minuto (vuelos largos con
        muchos asientos emiten menos por ASK que vuelos cortos).

    FIX #1: usa _co2_per_min, la misma función que calcular_kpis_ghp,
    garantizando coherencia entre objetivo LP y KPIs reportados.

    Returns:
        Series con r_f en kg CO₂/min para cada vuelo.
    """
    def _co2_per_min(fila):
        distancia = fila.get('distancia_km', 0)
        asientos  = fila.get('size_seats_avg', 180)
        duracion  = fila.get('duracion_vuelo_min', 60)

        if distancia <= 0 or pd.isna(asientos) or pd.isna(distancia) or duracion <= 0:
            return 0.1

        co2_ask      = compute_co2_ask(float(distancia), int(asientos), force=True)
        co2_total_kg = co2_ask * float(distancia) * int(asientos) / 1000
        return max(co2_total_kg / float(duracion), 0.01)

    return df_vuelos.apply(_co2_per_min, axis=1)


def calcular_rf_coste(df_vuelos: pd.DataFrame) -> pd.Series:
    """
    Task 3: r_f(t) — coeficiente de coste no lineal por vuelo (EUR/min).

    El coeficiente r_f captura la no-linealidad del coste con el delay:
    vuelos con más pasajeros de conexión y menos TAT disponible son
    más costosos por minuto de retraso, especialmente en delays largos.

    COMPONENTES DE r_f:
    1. Coste base por minuto (COST_AIR_MIN o COST_GND_MIN)
    2. Coste de pasajeros perdiendo conexión:
         pax_connecting × COST_LOST_CONNECTION / ventana_conexion
    3. Factor reactionary si el margen TAT < OTP_THRESHOLD_MIN

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
        asientos = fila.get('size_seats_avg', 180)
        if pd.isna(asientos):
            asientos = 180

        # --- Pasajeros y conexiones ---
        pax_total      = int(asientos * LOAD_FACTOR_EU)
        pax_connecting = int(pax_total * FRAC_CONNECTING_PAX)

        # Coste por minuto base
        es_candidato   = (fila.get('flight_status', '') == FS_CANDIDATE)
        coste_base_min = COST_GND_MIN if es_candidato else COST_AIR_MIN

        # --- Turn-around y reactionary ---
        recat    = str(fila.get('recat', 'D'))
        es_wide  = recat in ('A', 'B', 'C')
        tat_min_avion  = TAT_MIN['wide'] if es_wide else TAT_MIN['narrow']
        tat_disponible = fila.get('tat_disponible', tat_min_avion + 20)
        margen_tat     = max(tat_disponible - tat_min_avion, 0)

        factor_reactionary = (
            REACTIONARY_COST_MULTIPLIER if margen_tat < OTP_THRESHOLD_MIN else 1.0
        )

        # --- Coste de conexiones perdidas ---
        ventana_conexion   = 60   # min — ventana media MCT en LEBL
        coste_conexion_min = (pax_connecting * COST_LOST_CONNECTION_EUR) / ventana_conexion

        # --- r_f compuesto ---
        rf_valor = (coste_base_min + coste_conexion_min) * factor_reactionary
        rf[idx]  = round(rf_valor, 4)

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
    Si no hay rotación conocida, asumimos TAT mínimo + 20 min.

    Args:
        df_vuelos: DataFrame con columnas RM, minutes_eta, minutes_etd, ADES.

    Returns:
        DataFrame con columna 'tat_disponible' añadida (minutos).
    """
    df = df_vuelos.copy()
    df['tat_disponible'] = np.nan

    if 'RM' in df.columns:
        for rm, grupo in df.groupby('RM'):
            if pd.isna(rm) or rm == '':
                continue

            vuelos_rm  = grupo.sort_values('minutes_eta')
            llegadas_rm = vuelos_rm[vuelos_rm['ADES'] == 'LEBL']
            salidas_rm  = vuelos_rm[vuelos_rm['ADEP'] == 'LEBL']

            for idx_ll, vuelo_llegada in llegadas_rm.iterrows():
                eta = vuelo_llegada['minutes_eta']
                salidas_post = salidas_rm[salidas_rm['minutes_etd'] > eta]
                if not salidas_post.empty:
                    etd_siguiente = salidas_post['minutes_etd'].min()
                    df.at[idx_ll, 'tat_disponible'] = max(etd_siguiente - eta, 0)

    recat_col   = df['recat'].fillna('D')
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
          (1) Σ_f x_{f,t} ≤ 1           para todo t  (1 vuelo por slot)
          (2) Σ_{t≥ETA(f)} x_{f,t} = 1  para todo f  (cada vuelo 1 slot)
          (3) Los exentos tienen su slot fijado (no son variables del LP)
          (4) Air delay de exentos ≤ max_air_delay

    Returns:
        DataFrame combinado con columnas assigned_slot, total_delay,
        air_delay, ground_delay.
    """
    slots = sorted(slots_disponibles)

    # -------------------------------------------------------------------------
    # PASO 3a: Asignar slots a exentos primero (prioridad operacional)
    # -------------------------------------------------------------------------
    slots_ocupados      = set()
    asignaciones_exentos = {}

    for idx, vuelo in df_exentos.sort_values('minutes_eta').iterrows():
        eta = vuelo['minutes_eta']
        slots_elegibles = [
            s for s in slots
            if s >= eta and s not in slots_ocupados and (s - eta) <= max_air_delay
        ]
        if slots_elegibles:
            slot_asignado = slots_elegibles[0]
        else:
            # Fuerza mayor: ya está en vuelo, asignamos el primero disponible
            slots_sin_cap = [s for s in slots if s >= eta and s not in slots_ocupados]
            slot_asignado = slots_sin_cap[0] if slots_sin_cap else eta

        asignaciones_exentos[idx] = slot_asignado
        slots_ocupados.add(slot_asignado)

    slots_para_candidatos = [s for s in slots if s not in slots_ocupados]

    # -------------------------------------------------------------------------
    # PASO 3b: Formular el LP para los candidatos GDP
    # -------------------------------------------------------------------------
    if df_candidatos.empty or not slots_para_candidatos:
        return _construir_resultado(df_candidatos, df_exentos,
                                    {}, asignaciones_exentos)

    candidatos_idx = list(df_candidatos.index)
    eta_map        = df_candidatos['minutes_eta'].to_dict()

    if verbose:
        print(f"   [{nombre_problema}] {len(candidatos_idx)} candidatos, "
              f"{len(slots_para_candidatos)} slots disponibles")

    prob = pulp.LpProblem(nombre_problema, pulp.LpMinimize)

    x = {
        (f_idx, t_idx): pulp.LpVariable(f"x_{f_idx}_{t_idx}", cat='Binary')
        for f_idx in candidatos_idx
        for t_idx, t_val in enumerate(slots_para_candidatos)
        if t_val >= eta_map[f_idx]
    }

    prob += pulp.lpSum(
        rf_series.get(f_idx, 1.0) * (slots_para_candidatos[t_idx] - eta_map[f_idx])
        * x[(f_idx, t_idx)]
        for (f_idx, t_idx) in x
    )

    for t_idx in range(len(slots_para_candidatos)):
        vars_en_slot = [x[(f, t)] for (f, t) in x if t == t_idx]
        if vars_en_slot:
            prob += pulp.lpSum(vars_en_slot) <= 1, f"cap_slot_{t_idx}"

    for f_idx in candidatos_idx:
        vars_vuelo = [x[(f, t)] for (f, t) in x if f == f_idx]
        if vars_vuelo:
            prob += pulp.lpSum(vars_vuelo) == 1, f"asig_vuelo_{f_idx}"

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if verbose:
        print(f"   [{nombre_problema}] Status: {pulp.LpStatus[prob.status]}")
        print(f"   [{nombre_problema}] Coste óptimo: {pulp.value(prob.objective):.2f}")

    asignaciones_candidatos = {
        f_idx: slots_para_candidatos[t_idx]
        for (f_idx, t_idx), var in x.items()
        if pulp.value(var) is not None and pulp.value(var) > 0.5
    }

    return _construir_resultado(df_candidatos, df_exentos,
                                asignaciones_candidatos, asignaciones_exentos)


def _construir_resultado(
    df_candidatos: pd.DataFrame,
    df_exentos: pd.DataFrame,
    asig_candidatos: dict,
    asig_exentos: dict,
) -> pd.DataFrame:
    """Combina candidatos y exentos en un único DataFrame con delays calculados."""
    partes = []

    if not df_candidatos.empty:
        df_c = df_candidatos.copy()
        df_c['assigned_slot'] = df_c.index.map(asig_candidatos)
        df_c['total_delay']   = (df_c['assigned_slot'] - df_c['minutes_eta']).clip(lower=0)
        df_c['ground_delay']  = df_c['total_delay']
        df_c['air_delay']     = 0.0
        partes.append(df_c)

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
# PASO 4: ORQUESTADOR WP3
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
        'task2_emissions':  minimizar CO₂ del retraso
        'task3_cost':       minimizar coste real (pasajeros + reactionary)
    """
    df_enriched  = enriquecer_con_tat(df_vuelos_etiquetados)
    h_start      = params['H_START']
    df_en_ventana = df_enriched[df_enriched['minutes_eta'] >= h_start].copy()

    df_candidatos = df_en_ventana[df_en_ventana['flight_status'] == FS_CANDIDATE].copy()
    df_exentos    = df_en_ventana[df_en_ventana['flight_status'] != FS_CANDIDATE].copy()

    if verbose:
        print(f"   GHP: {len(df_candidatos)} candidatos, {len(df_exentos)} exentos")
        print(f"        {len(slots_disponibles)} slots disponibles")

    resultados = {}

    for tarea, rf_fn, nombre in [
        ('task1_validation', calcular_rf_unitario,  'GHP_Task1_Validation'),
        ('task2_emissions',  calcular_rf_emisiones, 'GHP_Task2_Emissions'),
        ('task3_cost',       calcular_rf_coste,     'GHP_Task3_Cost'),
    ]:
        if verbose:
            print(f"\n   [{nombre}] Calculando r_f...")
        rf = rf_fn(df_en_ventana)
        resultados[tarea] = resolver_ghp(
            df_candidatos.copy(), df_exentos.copy(),
            slots_disponibles, rf,
            nombre_problema=nombre, verbose=verbose,
        )
        resultados[f'rf_{tarea.split("_")[1]}'] = rf

    # Alias para compatibilidad con código existente
    resultados['rf_unitario']  = resultados.pop('rf_task1', resultados.get('rf_validation'))
    resultados['rf_emisiones'] = resultados.pop('rf_task2', resultados.get('rf_emissions'))
    resultados['rf_coste']     = resultados.pop('rf_task3', resultados.get('rf_cost'))

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

    FIX #3 — coherencia emisiones: el CO₂ del retraso se calcula con
    _co2_per_min, la misma función que usa calcular_rf_emisiones al
    construir el objetivo LP de Task 2.  Anteriormente se usaba la columna
    'co2_kg_vuelo' del CSV, que podía diferir del modelo de emisiones.

    KPIs calculados:
        - Retraso total, medio, air/ground
        - CO₂ del retraso (aire y tierra) — coherente con Task 2
        - Coste del retraso (EUR) usando los r_f del escenario
        - Nº vuelos retrasados, distribución por aerolínea
        - Air delay check (vuelos con air delay > MAX_AIR_DELAY)
    """
    if df_ghp.empty:
        return {}

    df = df_ghp.copy()
    for col in ('total_delay', 'air_delay', 'ground_delay'):
        if col not in df.columns:
            df[col] = 0.0

    # --- Retrasos ---
    total_delay  = df['total_delay'].sum()
    mean_delay   = df['total_delay'].mean()
    air_delay    = df['air_delay'].sum()
    ground_delay = df['ground_delay'].sum()
    n_delayed    = (df['total_delay'] > 0).sum()
    n_flights    = len(df)

    max_air_obs    = df['air_delay'].max()
    infeasible_air = (df['air_delay'] > MAX_AIR_DELAY_MIN).sum()

    # --- CO₂ del retraso — FIX #3 ---
    # Se usa _co2_per_min (misma función que Task 2) en lugar de 'co2_kg_vuelo'.
    def _co2_rate(row):
        return _co2_per_min(
            distancia_km=row.get('distancia_km', 0),
            asientos=int(row.get('size_seats_avg', 180) or 180),
            duracion_min=max(row.get('duracion_vuelo_min', 60), 1),
        )

    co2_rate = df.apply(_co2_rate, axis=1)   # kg CO₂ / min de vuelo

    co2_aire_delay   = (co2_rate * df['air_delay']).sum()
    co2_tierra_delay = (co2_rate * df['ground_delay']).sum()
    co2_total_delay  = co2_aire_delay + co2_tierra_delay

    # --- Coste del retraso usando r_f ---
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
            .groupby('airline').size()
            .nlargest(4).index.tolist()
        )
        for al in top_aerolineas:
            sub = df[df['airline'] == al]
            kpis_aerolinea[al] = {
                'n_vuelos':    len(sub),
                'delay_medio': round(sub['total_delay'].mean(), 2),
                'delay_total': round(sub['total_delay'].sum(), 2),
                'delay_std':   round(sub['total_delay'].std(), 2),
            }

    return {
        'escenario':           nombre_escenario,
        'n_flights':           n_flights,
        'n_delayed':           int(n_delayed),
        'total_delay_min':     round(total_delay, 2),
        'mean_delay_min':      round(mean_delay, 2),
        'air_delay_min':       round(air_delay, 2),
        'ground_delay_min':    round(ground_delay, 2),
        'max_air_delay_obs':   round(max_air_obs, 2),
        'infeasible_air':      int(infeasible_air),
        'co2_aire_delay_kg':   round(co2_aire_delay, 2),
        'co2_tierra_delay_kg': round(co2_tierra_delay, 2),
        'co2_total_delay_kg':  round(co2_total_delay, 2),
        'coste_delay_eur':     round(coste_total, 2),
        'kpis_aerolinea':      kpis_aerolinea,
    }


# =============================================================================
# MODO DEBUG
# =============================================================================

if __name__ == '__main__':
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import lib_data_prep as prep
    import lib_gdp_core  as gdp

    print("🛠️  MODO DEBUG: lib_ghp_solver.py")
    base     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota  = os.path.join(base, 'data/raw/fleet_cat_seat.csv')

    params    = CFG.to_params_dict()
    df_vuelos = prep.preparar_vuelos(p_vuelos, p_flota)

    resultados_gdp = gdp.ejecutar_nucleo_gdp(df_vuelos, params)
    df_etiquetado  = resultados_gdp['vuelos_asignados']
    slots_list     = list(resultados_gdp['slots']['slot_start_min'])

    resultados_ghp = ejecutar_ghp_completo(
        df_etiquetado, slots_list, params, verbose=True
    )

    # Verificar Task 1
    df_val   = resultados_ghp['task1_validation']
    rf_1     = resultados_ghp['rf_unitario']
    kpis_val = calcular_kpis_ghp(df_val, rf_1, 'Task1_Validation')
    coste_gdp = resultados_gdp['vuelos_asignados']['total_delay'].sum()

    print(f"\n{'='*50}")
    print(f"  VALIDACIÓN Task 1:")
    print(f"  Delay total GHP: {kpis_val['total_delay_min']:.2f} min")
    print(f"  Delay total GDP: {coste_gdp:.2f} min")
    diff_pct = abs(kpis_val['total_delay_min'] - coste_gdp) / max(coste_gdp, 1) * 100
    print(f"  Diferencia: {diff_pct:.1f}%  {'✅ OK' if diff_pct < 5 else '⚠️ Revisar'}")
    print(f"{'='*50}")

    for escenario, rf_key in [
        ('task2_emissions', 'rf_emisiones'),
        ('task3_cost',      'rf_coste'),
    ]:
        df_esc = resultados_ghp[escenario]
        rf_esc = resultados_ghp[rf_key]
        kpis   = calcular_kpis_ghp(df_esc, rf_esc, escenario)
        print(f"\n  {escenario.upper()}:")
        print(f"    Total delay:    {kpis['total_delay_min']:.1f} min")
        print(f"    Air delay:      {kpis['air_delay_min']:.1f} min")
        print(f"    Ground delay:   {kpis['ground_delay_min']:.1f} min")
        print(f"    CO2 delay:      {kpis['co2_total_delay_kg']:.1f} kg")
        print(f"    Coste delay:    {kpis['coste_delay_eur']:.0f} EUR")
        print(f"    Air infeasible: {kpis['infeasible_air']} vuelos")
