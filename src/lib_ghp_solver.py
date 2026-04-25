# =============================================================================
# src/lib_ghp_solver.py
# WP3: Ground Holding Problem (GHP) — Solver de Programación Lineal Entera
#
# CONTEXTO:
#   El GHP asigna vuelos a slots de llegada minimizando una función de coste.
#   A diferencia del RBS (FIFO), el LP puede priorizar vuelos más costosos
#   asignándoles slots más tempranos aunque lleguen más tarde.
#
# VERSIÓN COMBINADA CON EMISIONES ALCANCE 1 Y 2:
#   Integra la lógica avanzada de emisiones documentada académicamente:
#   - Aire: Airborne holding (consumo de queroseno por minuto).
#   - Tierra: Ground delay usando conexión a red FEGP (Scope 2, REE) +
#             10 minutos reglamentarios fijos de APU (Scope 1, ICAO Doc 9889).
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
LOAD_FACTOR_EU = 0.837

# Fracción de pasajeros de conexión en LEBL.
FRAC_CONNECTING_PAX = 0.20

# Coste por pasajero que pierde su conexión (EUR).
COST_LOST_CONNECTION_EUR = 200

# Turn-around time mínimo por categoría (minutos).
TAT_MIN = {
    'narrow':  45,   # A320, B737 y similares (RECAT D, E, F)
    'wide':    80,   # A330, B777 y similares (RECAT A, B, C)
}

# Multiplicador de coste para reactionary delay.
REACTIONARY_COST_MULTIPLIER = 1.3

# Umbral de delay "largo" que activa el multiplicador de coste no lineal.
OTP_THRESHOLD_MIN = 15

# Factor de conversión estándar (Jet-A1): 3.16 kg CO2 por 1 kg de queroseno
CO2_PER_KG_FUEL = 3.16

# --- CONSTANTES DE EMISIONES EN TIERRA (SCOPE 1 Y SCOPE 2) ---

# Fuel consumption at gate (APU) per RECAT category in kg/min
# Fuente: ICAO Doc 9889, Tabla 3-A1-6 (Normal running - Maximum ECS)
APU_FUEL_KG_PER_MIN = {
    'A': 3.97,  # Larger (300 <= seats), newer types (238 kg/h / 60)
    'B': 3.37,  # Larger (300 <= seats), older types (202 kg/h / 60)
    'C': 2.73,  # Mid-range (200 <= seats < 300) (164 kg/h / 60)
    'D': 1.83,  # Smaller (100 <= seats < 200), newer types (110 kg/h / 60)
    'E': 1.68,  # Business jets/regional jets (101 kg/h / 60)
    'F': 0.50,  # Light aircraft (Estimación conservadora, no explícito en OACI)
}

# Minutos reglamentarios de uso de APU antes del pushback
APU_MANDATORY_MINUTES = 10.0

# Factor de emisión de la red eléctrica en España (kg CO2 / kWh) 
# Fuente: Red Eléctrica de España (REE) / MITERD 2023
GRID_EMISSION_FACTOR_KG_KWH = 0.283 

# =============================================================================
# REQUISITOS DE POTENCIA ELÉCTRICA EN TIERRA (FEGP / GPU)
# Fuentes: Manuales ACAP (Airbus/Boeing), APM (Embraer) y POH (Pilatus)
# =============================================================================

# Consumo eléctrico instalado/demandado por categoría RECAT en kW (Consumo Continuo en Espera)
FEGP_KW_PER_RECAT = {
    'A': 288.0,  # A388: 4 x 90 kVA (360 kVA * 0.8 = 288 kW)
    'B': 144.0,  # B789: 2 x 90 kVA (180 kVA * 0.8 = 144 kW)
    'C': 144.0,  # B764: 2 x 90 kVA (180 kVA * 0.8 = 144 kW)
    'D': 72.0,   # A320: 1 x 90 kVA (90 kVA * 0.8 = 72 kW)
    'E': 32.0,   # E190: Límite del bus interno (40 kVA * 0.8 = 32 kW)
    'F': 12.8,   # PC24: 28.5 VDC * 450 Amperios continuos = 12.8 kW
}

# =============================================================================
# UTILIDAD INTERNA: CO₂ por minuto de vuelo (Aire)
# =============================================================================

def _co2_per_min(distancia_km: float, asientos: int, duracion_min: float) -> float:
    """
    Calcula el CO₂ medio por minuto de vuelo en el aire.
    Maneja excepciones y previene divisiones por cero.
    """
    if distancia_km <= 0 or asientos <= 0 or duracion_min <= 0:
        return 0.01

    try:
        co2_ask = compute_co2_ask(distancia_km, int(asientos), force=True)
        co2_total = co2_ask * distancia_km * asientos / 1000.0
    except Exception:
        return 0.01

    return max(co2_total / duracion_min, 0.01)


# =============================================================================
# PASO 1: CALCULAR COEFICIENTES r_f PARA CADA VUELO
# =============================================================================

def calcular_rf_unitario(df_vuelos: pd.DataFrame) -> pd.Series:
    """Task 1 (validación): r_f = 1 para todos los vuelos."""
    return pd.Series(1.0, index=df_vuelos.index)


def calcular_rf_emisiones(df_vuelos: pd.DataFrame) -> pd.Series:
    """
    Task 2: r_f = CO₂ por minuto de retraso de cada vuelo (kg/min).
    Diferencia FEGP Scope 2 (Candidatos en Tierra) vs Crucero (Exentos en el Aire).
    """
    def _apply_co2(fila):
        # Si es candidato (Ground Hold), la penalización marginal es Scope 2 (FEGP)
        if fila.get('flight_status') == FS_CANDIDATE:
            recat_str = str(fila.get('recat', 'D')).upper()
            potencia_kw = FEGP_KW_PER_RECAT.get(recat_str, 50.0)
            
            # Emisiones Scope 2 por cada minuto extra conectado al aeropuerto
            co2_fegp_min = potencia_kw * (1 / 60.0) * GRID_EMISSION_FACTOR_KG_KWH
            return co2_fegp_min

        # Si ya está volando, asume emisiones de aire (Scope 1)
        distancia = float(fila.get('distancia_km', 0) or 0)
        asientos  = int(fila.get('size_seats_avg', 180) or 180)
        duracion  = float(fila.get('duracion_vuelo_min', 60) or 60)
        
        return _co2_per_min(distancia_km=distancia, asientos=asientos, duracion_min=duracion)

    return df_vuelos.apply(_apply_co2, axis=1)


def calcular_rf_coste(df_vuelos: pd.DataFrame) -> pd.Series:
    """Task 3: r_f(t) — coeficiente de coste no lineal por vuelo (EUR/min)."""
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
# PASO 2: CALCULAR TAT DISPONIBLE DESDE EL CSV
# =============================================================================

def enriquecer_con_tat(df_vuelos: pd.DataFrame) -> pd.DataFrame:
    """Calcula el turn-around time disponible para cada vuelo usando el RM."""
    df = df_vuelos.copy()
    df['tat_disponible'] = np.nan

    if 'RM' in df.columns:
        for rm, grupo in df.groupby('RM'):
            if pd.isna(rm) or rm == '':
                continue

            vuelos_rm   = grupo.sort_values('minutes_eta')
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
    """Resuelve el GHP como un problema de programación lineal entera binaria."""
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
    """Ejecuta los 3 escenarios GHP del WP3 y devuelve los resultados."""
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
    """Calcula los KPIs del WP3 para un escenario GHP (con APU en tierra)."""
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

    # --- CO₂ del retraso (Separando Aire, FEGP y APU fijo) ---
    def _co2_rate_aire(row):
        return _co2_per_min(
            distancia_km=float(row.get('distancia_km', 0) or 0),
            asientos=int(row.get('size_seats_avg', 180) or 180),
            duracion_min=max(float(row.get('duracion_vuelo_min', 60) or 60), 1),
        )

    def _get_fegp_co2_min(recat):
        recat_str = str(recat).upper() if pd.notna(recat) else 'D'
        potencia_kw = FEGP_KW_PER_RECAT.get(recat_str, 50.0)
        return potencia_kw * (1 / 60.0) * GRID_EMISSION_FACTOR_KG_KWH

    def _get_apu_co2_fijo(recat):
        recat_str = str(recat).upper() if pd.notna(recat) else 'D'
        fuel_apu_min = APU_FUEL_KG_PER_MIN.get(recat_str, 1.16)
        return APU_MANDATORY_MINUTES * fuel_apu_min * CO2_PER_KG_FUEL

    # Scope 1 Aire
    co2_rate_aire = df.apply(_co2_rate_aire, axis=1)
    co2_aire_delay = (co2_rate_aire * df['air_delay']).sum()

    # Scope 2 FEGP Tierra
    col_recat = df.get('recat', pd.Series('D', index=df.index))
    co2_rate_fegp = col_recat.apply(_get_fegp_co2_min)
    co2_tierra_fegp_delay = (co2_rate_fegp * df['ground_delay']).sum()

    # Scope 1 APU Fijo (Solo aplicable a candidatos gestionados en tierra)
    mask_candidato = (df.get('flight_status', '') == FS_CANDIDATE)
    co2_apu_fijo = col_recat.apply(_get_apu_co2_fijo) * mask_candidato
    co2_tierra_apu_fijo = co2_apu_fijo.sum()

    co2_tierra_total = co2_tierra_fegp_delay + co2_tierra_apu_fijo
    co2_total_emisiones = co2_aire_delay + co2_tierra_total

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
        'escenario':              nombre_escenario,
        'n_flights':              n_flights,
        'n_delayed':              int(n_delayed),
        'total_delay_min':        round(total_delay, 2),
        'mean_delay_min':         round(mean_delay, 2),
        'air_delay_min':          round(air_delay, 2),
        'ground_delay_min':       round(ground_delay, 2),
        'max_air_delay_obs':      round(max_air_obs, 2),
        'infeasible_air':         int(infeasible_air),
        'co2_aire_delay_kg':      round(co2_aire_delay, 2),
        'co2_tierra_fegp_delay_kg': round(co2_tierra_fegp_delay, 2),
        'co2_tierra_apu_fijo_kg': round(co2_tierra_apu_fijo, 2),
        'co2_tierra_total_kg':    round(co2_tierra_total, 2),
        'co2_total_kg':           round(co2_total_emisiones, 2),
        'coste_delay_eur':        round(coste_total, 2),
        'kpis_aerolinea':         kpis_aerolinea,
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
        print(f"    Total delay:        {kpis['total_delay_min']:.1f} min")
        print(f"    Air delay:          {kpis['air_delay_min']:.1f} min")
        print(f"    Ground delay:       {kpis['ground_delay_min']:.1f} min")
        print(f"    CO2 aire delay:     {kpis['co2_aire_delay_kg']:.1f} kg")
        print(f"    CO2 tierra (FEGP):  {kpis['co2_tierra_fegp_delay_kg']:.1f} kg")
        print(f"    CO2 tierra (APU):   {kpis['co2_tierra_apu_fijo_kg']:.1f} kg")
        print(f"    CO2 tierra total:   {kpis['co2_tierra_total_kg']:.1f} kg")
        print(f"    CO2 total generad:  {kpis['co2_total_kg']:.1f} kg")
        print(f"    Coste delay:        {kpis['coste_delay_eur']:.0f} EUR")
        print(f"    Air infeasible:     {kpis['infeasible_air']} vuelos")

        # Añade esto en la zona de DEBUG de lib_ghp_solver.py
    
    # Extraemos el DataFrame de resultados que equivale a la hoja 2_Regulacion_GDP
    df_resultado = resultados_ghp['task1_validation']
    """
    print("\n" + "="*50)
    print(" ✈️  MODELOS REPRESENTATIVOS POR CATEGORÍA:")
    for cat, grupo in df_resultado.groupby('recat'):
        top_modelo = grupo['ATYP'].value_counts().index[0]
        cantidad = grupo['ATYP'].value_counts().iloc[0]
        porcentaje = (cantidad / len(grupo)) * 100
        print(f"   - Cat {cat}: {top_modelo} domina con {cantidad} vuelos ({porcentaje:.1f}%)")
    print("="*50)
    """