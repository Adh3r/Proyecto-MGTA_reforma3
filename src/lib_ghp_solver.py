# =============================================================================
# src/lib_ghp_solver.py
# WP3: Ground Holding Problem (GHP) — Solver de Programación Lineal Entera
#
# CONTEXTO:
#   El GHP asigna vuelos a slots de llegada minimizando una función de coste.
#   A diferencia del RBS (FIFO), el LP puede priorizar vuelos más costosos
#   asignándoles slots más tempranos aunque lleguen más tarde.
#
# VERSIÓN COMBINADA:
#   - CO2: APU en tierra vs. crucero en aire
#   - COSTE: Cook & Tanner (2015), Tables 11 y 12, ajustado por pasajeros reales
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

MAX_AIR_DELAY_MIN = 90

# Load factor europeo. Fuente: IATA Annual Review 2025, promedio europeo: 83,7%
LOAD_FACTOR_EU = 0.837

# Turn-around time mínimo por categoría (minutos).
# Fuente: Eurocontrol Standard Inputs for Economic Analyses, §18
TAT_MIN = {
    'narrow':  45,   # A320, B737 y similares (RECAT D, E, F)
    'wide':    80,   # A330, B777 y similares (RECAT A, B, C)
}

# Umbral OTP: delay < 15 min = "on-time" (IATA/CODA estándar).
OTP_THRESHOLD_MIN = 15

# Consumo APU por categoría RECAT (kg fuel/min).
# Fuente: ICAO Airport Air Quality Manual, Doc 9889.
APU_FUEL_KG_PER_MIN = {
    'A': 2.25,
    'B': 1.83,
    'C': 1.50,
    'D': 1.16,
    'E': 0.66,
    'F': 0.25,
}

# Factor conversión fuel → CO2. Fuente: ICAO Carbon Emissions Calculator, v11.
CO2_PER_KG_FUEL = 3.16


# =============================================================================
# TABLAS DE COSTE — Cook & Tanner 2015 (passengerdelaycost.pdf)
#
# Tabla 12: Coste TOTAL (hard + soft, base scenario, EUR 2014)
#   → Sin reactionary delay (primary delay).
# Tabla 11: Coste HARD únicamente (base scenario, EUR 2014)
#   → Con reactionary delay (total delay).
#
# Columnas = franjas de delay: 5, 15, 30, 60, 90, 120, 180, 240, 300 min
# =============================================================================

_DELAY_BREAKPOINTS = [5, 15, 30, 60, 90, 120, 180, 240, 300]

# Tabla 12: hard + soft (EUR 2014)
_COST_TOTAL_TABLE = {
    #           5     15     30      60      90     120     180      240      300
    'A319': [  40,   270,   960,  3510,  7180, 11730, 23420,  38410,  56520],
    'A320': [  40,   310,  1110,  4030,  8260, 13500, 26940,  44190,  65020],
    'A321': [  50,   380,  1350,  4900, 10040, 16400, 32750,  53710,  79020],
    'B733': [  40,   250,   910,  3320,  6800, 11110, 22180,  36370,  53520],
    'B734': [  40,   290,  1040,  3780,  7750, 12670, 25280,  41470,  61020],
    'B738': [  40,   330,  1170,  4250,  8700, 14220, 28390,  46570,  68520],
    'B752': [  50,   400,  1420,  5180, 10610, 17340, 34610,  56770,  83520],
    'B763': [  70,   490,  1760,  6420, 13150, 21490, 42900,  70360, 103530],
    'B744': [ 110,   790,  2850, 10360, 21220, 34670, 69220, 113530, 167050],
    'A332': [  80,   550,  1980,  7200, 14740, 24080, 48080,  78860, 116030],
    'E190': [  30,   180,   660,  2390,  4890,  7990, 15960,  26170,  38510],
    'DH8D': [  20,   140,   490,  1770,  3620,  5920, 11810,  19380,  28510],
    'AT72': [  20,   120,   440,  1610,  3300,  5400, 10780,  17680,  26010],
    'AT43': [  10,    90,   310,  1120,  2290,  3740,  7460,  12240,  18010],
}

# Tabla 11: solo hard (EUR 2014)
_COST_HARD_TABLE = {
    #           5     15     30      60      90     120     180      240      300
    'A319': [  36,   252,   870,  3000,  6180, 10320, 21280,  35550,  52940],
    'A320': [  41,   290,  1000,  3450,  7100, 11870, 24480,  40900,  60910],
    'A321': [  50,   353,  1220,  4190,  8630, 14430, 29750,  49710,  74030],
    'B733': [  34,   239,   820,  2840,  5850,  9770, 20150,  33660,  50130],
    'B734': [  38,   272,   940,  3230,  6670, 11140, 22970,  38380,  57160],
    'B738': [  43,   306,  1050,  3630,  7490, 12510, 25800,  43100,  64190],
    'B752': [  53,   373,  1280,  4430,  9130, 15250, 31440,  52540,  78240],
    'B763': [  65,   462,  1590,  5490, 11310, 18900, 38980,  65130,  96980],
    'B744': [ 105,   746,  2570,  8850, 18250, 30500, 62890, 105080, 156490],
    'A332': [  73,   518,  1780,  6150, 12680, 21190, 43680,  72990, 108700],
    'E190': [  24,   172,   590,  2040,  4210,  7030, 14500,  24230,  36080],
    'DH8D': [  18,   127,   440,  1510,  3120,  5210, 10730,  17930,  26710],
    'AT72': [  16,   116,   400,  1380,  2840,  4750,  9790,  16360,  24360],
    'AT43': [  11,    80,   280,   950,  1970,  3290,  6780,  11330,  16870],
}

# Pasajeros base Annex 3 (Cook & Tanner 2015, base scenario).
_PAX_BASE_TABLE = {
    'A319': 113, 'A320': 130, 'A321': 158,
    'B733': 107, 'B734': 122, 'B738': 137,
    'B752': 167, 'B763': 207, 'B744': 334,
    'A332': 232, 'E190':  77, 'DH8D':  57,
    'AT72':  52, 'AT43':  36,
}

# =============================================================================
# MAPEO ICAO → TIPO COOK & TANNER (v4.1, 2014)
#
# Principio: identificar el tipo Cook cuya estructura de costes (fuel, crew,
# maintenance, pax) sea lo mas similar posible a la aeronave real. El ajuste
# por densidad de pasajeros (factor_pax) en _calcular_kpis_ghp corrige despues
# la diferencia de capacidad, por lo que el mapeo debe capturar la CATEGORIA
# de operacion (turbofan narrowbody, widebody, turboprop, bizjet), no solo el
# numero de asientos.
#
# Aeronaves del CSV de LEBL con sus mappings:
#   A320/A20N (173 seats) → A320 (Cook base: 153 seats, pax 130)
#   A321/A21N (207/220)   → A321 (Cook base: 187 seats, pax 158)
#   A319      (144)       → A319 (Cook base: 133 seats, pax 113)
#   B738/B38M (184/189)   → B738 (Cook base: 161 seats, pax 137)
#   B739      (183)       → B738 (mas cercano operacionalmente)
#   BCS3      (145)       → A319 (mismo rango de asientos; la A220-300 tiene
#                           estructura de costes de narrowbody similar a A319)
#   B733      (142, RECAT E en CSV → probable error de datos; tratamos como
#                           narrowbody pequeno → B733 de Cook)
#   B789/B788 (284/266)   → A332 (widebody de capacidad similar)
#   A332/A333/A338/A339   → A332 (Cook base: 279 seats, pax 232)
#   A359      (297)       → A332 (mas cercano disponible en Cook)
#   B764      (245)       → B763 (Cook base: 279 seats, ajuste pax cubre dif.)
#   B772/B77L/B77W (296-331) → B744 (widebody pesado, estructura similar)
#   A388      (492)       → B744 (unico jumbo disponible en Cook)
#   CRJX/CRJ2 (49-100)   → E190 (regional jet, mas cercano en Cook)
#   E190      (104)       → E190 (match directo)
#   AT43      (49)        → AT43 (match directo)
#   Bizjets (GLEX,GLF6,GA5C,C525,C560,C650,C68A,E35L,E50P,
#            E55P,F2TH,PC24,PC12,CL35) → AT43 como proxy de coste de bizjet
#            (estructura de coste minima en Cook; el factor_pax = seats_reales/36
#            escala el coste a la baja automaticamente para aviones con 5-15 pax)
# =============================================================================

_FLEET_TO_COOK = {
    # --- Familia Airbus A320 ---
    'A318': 'A319', 'A319': 'A319',
    'A320': 'A320', 'A20N': 'A320',   # A320neo -> misma tabla Cook, seats reales del CSV
    'A321': 'A321', 'A21N': 'A321',   # A321neo -> misma tabla Cook
    # --- A220 (Bombardier CRJ -> Airbus) ---
    'BCS1': 'A319',                    # A220-100 (~115 seats) -> A319 (133 seats Cook)
    'BCS3': 'A319',                    # A220-300 (~145 seats) -> A319 (mas cercano)
    # --- Boeing 737 classics y NG ---
    'B733': 'B733', 'B734': 'B734', 'B735': 'B733', 'B736': 'B733',
    'B737': 'B734',
    'B738': 'B738', 'B38M': 'B738',   # B737 MAX 8 -> B738 como proxy
    'B739': 'B738',                    # B737-900 -> B738 (misma familia)
    'B752': 'B752', 'B753': 'B752',
    # --- Embraer comercial ---
    'E170': 'E190', 'E175': 'E190', 'E190': 'E190', 'E195': 'E190',
    'E75L': 'E190', 'E75S': 'E190',
    # --- CRJ comercial ---
    'CRJ1': 'AT43', 'CRJ2': 'AT43',   # CRJ-100/200 (~50 seats) -> AT43
    'CRJ7': 'AT72',                    # CRJ-700 (~70 seats) -> AT72
    'CRJ9': 'E190', 'CRJX': 'E190',   # CRJ-900/1000 (~90-100 seats) -> E190
    # --- DHC-8 / Turboprop ---
    'AT43': 'AT43', 'AT46': 'AT43',
    'AT72': 'AT72', 'ATP':  'AT72',
    'DH8A': 'AT43', 'DH8B': 'AT43', 'DH8C': 'AT43', 'DH8D': 'DH8D',
    'F50':  'AT43', 'F70':  'AT72', 'SB20': 'AT43',
    # --- Otros narrowbody comerciales ---
    'F100': 'E190', 'RJ1H': 'E190', 'RJ85': 'E190',
    'B712': 'B733', 'B462': 'B733', 'B463': 'B733',
    'MD80': 'B738', 'MD82': 'B738', 'MD83': 'B738',
    'T154': 'B733', 'YK42': 'B733', 'SU95': 'E190',
    'E120': 'AT43', 'E135': 'AT43', 'E145': 'AT43',
    'B190': 'AT43', 'CARJ': 'AT43', 'SF34': 'AT43',
    'A140': 'AT43', 'A148': 'AT43',
    # --- Widebody medio (A330 / B787) ---
    'A306': 'B763', 'A310': 'B763',
    'A332': 'A332', 'A333': 'A332', 'A338': 'A332', 'A339': 'A332',
    'A340': 'A332', 'A343': 'A332',
    'A359': 'A332', 'A35K': 'A332',   # A350-900/1000 -> A332 (mas cercano Cook)
    'B788': 'A332', 'B789': 'A332',   # B787-8/9 (~260-280 seats) -> A332
    'B78X': 'B744',                    # B787-10 (~330 seats) -> B744
    # --- Widebody pesado / jumbo ---
    'A345': 'B744', 'A346': 'B744',
    'A388': 'B744',                    # A380 (492 seats) -> B744 (unico jumbo Cook)
    'B744': 'B744', 'B748': 'B744',
    'B762': 'B763', 'B763': 'B763', 'B764': 'B763',
    'B772': 'B744',                    # B777-200 (~300 seats) -> B744
    'B773': 'B744', 'B77W': 'B744', 'B77L': 'B744',
    'IL96': 'B763', 'T204': 'B763',
    # --- Business jets / VIP (RECAT E/F en LEBL) ---
    # Proxy: AT43 como tipo Cook de menor coste disponible.
    # El factor_pax = (seats_reales x LF) / 36 escala el coste a la baja
    # automaticamente (p.ej. PC24 con 8 seats → factor ~0.19).
    'GLEX': 'AT43', 'GLF6': 'AT43', 'GLF5': 'AT43', 'GLF4': 'AT43',
    'GA5C': 'AT43', 'GA6C': 'AT43',
    'C525': 'AT43', 'C56X': 'AT43', 'C560': 'AT43', 'C650': 'AT43',
    'C68A': 'AT43', 'C750': 'AT43',
    'E35L': 'AT43', 'E50P': 'AT43', 'E55P': 'AT43',
    'F2TH': 'AT43', 'FA50': 'AT43', 'FA7X': 'AT43',
    'PC24': 'AT43', 'PC12': 'AT43',
    'CL35': 'AT43', 'CL60': 'AT43', 'CL30': 'AT43',
    'H25B': 'AT43', 'H25C': 'AT43',
    'LJ45': 'AT43', 'LJ60': 'AT43',
    'C25A': 'AT43', 'C25B': 'AT43', 'C25C': 'AT43',
    'BE40': 'AT43', 'BE20': 'AT43', 'BE9L': 'AT43',
    'PRM1': 'AT43', 'TBM9': 'AT43', 'TBM8': 'AT43',
}


def _mapear_tipo_cook(tipo_icao: str, recat: str, seats: int = 0) -> str:
    """
    Mapea tipo ICAO al tipo Cook & Tanner v4.1 mas cercano.

    Orden de prioridad:
      1. Lookup directo en _FLEET_TO_COOK (identificacion exacta por tipo ICAO).
      2. Fallback por RECAT + seats cuando el tipo no esta en la tabla:
         - RECAT A/B/C (widebody): B744 si seats > 350, A332 si seats > 240, B763
         - RECAT D     (narrowbody): A321 si seats > 195, A320 si seats > 160,
                                     A319 si seats > 130, B733
         - RECAT E     (regional):   E190 si seats > 80, AT72 si seats > 55, AT43
         - RECAT F     (ligero):     AT43 (con factor_pax muy bajo)
    """
    tipo_upper = str(tipo_icao).upper().strip()
    if tipo_upper in _FLEET_TO_COOK:
        return _FLEET_TO_COOK[tipo_upper]

    recat_upper = str(recat).upper()
    if recat_upper in ('A', 'B', 'C'):
        if seats > 350:
            return 'B744'
        if seats > 240:
            return 'A332'
        return 'B763'
    if recat_upper == 'D':
        if seats > 195:
            return 'A321'
        if seats > 160:
            return 'A320'
        if seats > 130:
            return 'A319'
        return 'B733'
    if recat_upper == 'E':
        if seats > 80:
            return 'E190'
        if seats > 55:
            return 'AT72'
        return 'AT43'
    # RECAT F o desconocido
    return 'AT43'


def _interpolar_coste(tipo_cook: str, delay_min: float, usar_hard: bool) -> float:
    """Interpolación lineal del coste entre franjas de la tabla."""
    tabla  = _COST_HARD_TABLE if usar_hard else _COST_TOTAL_TABLE
    costes = tabla.get(tipo_cook, tabla['A320'])
    puntos = _DELAY_BREAKPOINTS

    if delay_min <= 0:
        return 0.0
    if delay_min <= puntos[0]:
        return costes[0] * (delay_min / puntos[0])
    if delay_min >= puntos[-1]:
        return float(costes[-1])

    for i in range(len(puntos) - 1):
        if puntos[i] <= delay_min <= puntos[i + 1]:
            t = (delay_min - puntos[i]) / (puntos[i + 1] - puntos[i])
            return costes[i] + t * (costes[i + 1] - costes[i])

    return float(costes[-1])


# =============================================================================
# UTILIDAD INTERNA: CO₂ por minuto de vuelo (Aire)
# =============================================================================

def _co2_per_min(distancia_km: float, asientos: int, duracion_min: float) -> float:
    """CO₂ medio por minuto de vuelo en el aire (tasa crucero)."""
    if distancia_km <= 0 or asientos <= 0 or duracion_min <= 0:
        return 0.01
    try:
        co2_ask   = compute_co2_ask(distancia_km, int(asientos), force=True)
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
    Task 2: r_f = CO₂ por minuto de retraso (kg/min).
    Candidatos GDP → APU en tierra.
    Exentos        → tasa crucero en aire.
    """
    def _apply_co2(fila):
        if fila.get('flight_status') == FS_CANDIDATE:
            recat_str = str(fila.get('recat', 'D')).upper()
            fuel_min  = APU_FUEL_KG_PER_MIN.get(recat_str, 1.16)
            return fuel_min * CO2_PER_KG_FUEL

        distancia = float(fila.get('distancia_km', 0) or 0)
        asientos  = int(fila.get('size_seats_avg', 180) or 180)
        duracion  = float(fila.get('duracion_vuelo_min', 60) or 60)
        return _co2_per_min(distancia_km=distancia, asientos=asientos, duracion_min=duracion)

    return df_vuelos.apply(_apply_co2, axis=1)


def calcular_rf_coste(df_vuelos: pd.DataFrame) -> pd.Series:
    """
    Task 3: r_f — coeficiente de coste marginal por vuelo (EUR/min de delay).

    METODOLOGÍA (Cook & Tanner 2015, University of Westminster):

    1. MAPEO DE AERONAVE:
       Tipo ICAO ('ATYP' del CSV o 'f' del fleet CSV) → tipo Cook & Tanner
       via _FLEET_TO_COOK. Fallback por RECAT.

    2. SELECCIÓN DE TABLA:
       - Sin reactionary (margen_tat >= OTP_THRESHOLD_MIN) → Tabla 12 (hard+soft)
       - Con reactionary (margen_tat < OTP_THRESHOLD_MIN)  → Tabla 11 (solo hard)
       margen_tat = tat_disponible - tat_min_avion

    3. AJUSTE POR PASAJEROS REALES:
       pax_reales = size_seats_avg × LOAD_FACTOR_EU
       factor_pax = pax_reales / pax_base_cook  (Annex 3)
       coste_ajustado = coste_tabla × factor_pax

    4. r_f = coste_ajustado(delay=15 min) / 15
       Evaluado en el punto OTP (15 min) como coste marginal EUR/min.

    Fuentes: Cook & Tanner (2015) Tables 11, 12, Annex 3. Ball (2007).
    """
    rf = pd.Series(index=df_vuelos.index, dtype=float)

    for idx, fila in df_vuelos.iterrows():
        tipo_icao = str(fila.get('ATYP', fila.get('f', ''))).upper().strip()
        asientos  = fila.get('size_seats_avg', 180)
        if pd.isna(asientos) or asientos <= 0:
            asientos = 180
        asientos = int(asientos)

        recat   = str(fila.get('recat', 'D')).upper()
        es_wide = recat in ('A', 'B', 'C')

        tipo_cook = _mapear_tipo_cook(tipo_icao, recat, asientos)

        tat_min_avion  = TAT_MIN['wide'] if es_wide else TAT_MIN['narrow']
        tat_disponible = fila.get('tat_disponible', tat_min_avion + 20)
        if pd.isna(tat_disponible):
            tat_disponible = tat_min_avion + 20
        margen_tat      = max(float(tat_disponible) - tat_min_avion, 0)
        hay_reactionary = margen_tat < OTP_THRESHOLD_MIN

        coste_tabla = _interpolar_coste(tipo_cook, OTP_THRESHOLD_MIN, hay_reactionary)

        pax_base   = _PAX_BASE_TABLE.get(tipo_cook, 130)
        pax_reales = max(int(asientos * LOAD_FACTOR_EU), 1)
        factor_pax = pax_reales / pax_base

        coste_ajustado = coste_tabla * factor_pax
        rf[idx] = round(coste_ajustado / OTP_THRESHOLD_MIN, 4)

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

    slots_ocupados       = set()
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
            slots_sin_cap = [s for s in slots if s >= eta and s not in slots_ocupados]
            slot_asignado = slots_sin_cap[0] if slots_sin_cap else eta

        asignaciones_exentos[idx] = slot_asignado
        slots_ocupados.add(slot_asignado)

    slots_para_candidatos = [s for s in slots if s not in slots_ocupados]

    if df_candidatos.empty or not slots_para_candidatos:
        return _construir_resultado(df_candidatos, df_exentos, {}, asignaciones_exentos)

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
    df_enriched   = enriquecer_con_tat(df_vuelos_etiquetados)
    h_start       = params['H_START']
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

    # Alias de compatibilidad
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

    COSTE DE RETRASO — Cook & Tanner (2015), University of Westminster:
      - Por cada vuelo con delay real > 0, se interpola el coste NO LINEAL
        directamente de las tablas Cook (Tables 22-29, base scenario, EUR 2014).
      - Se selecciona tabla PRIMARY (sin reactionary) o FULL (con reactionary)
        segun el margen TAT disponible vs. TAT minimo de la categoria.
      - El coste se escala: factor_pax = pax_reales / pax_base_cook (Annex B2),
        donde pax_reales = size_seats_avg x LOAD_FACTOR_EU.
      - rf_series se mantiene en la firma por compatibilidad con llamadas externas
        pero ya no interviene en el calculo de coste_delay_eur.

    Fuente: Cook, A., Tanner, G. (2015). European airline delay cost reference
            values. Version 4.1. University of Westminster / EUROCONTROL PRU.
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

    # --- CO₂ del retraso (APU en tierra, crucero en aire) ---
    def _co2_rate_aire(row):
        return _co2_per_min(
            distancia_km=float(row.get('distancia_km', 0) or 0),
            asientos=int(row.get('size_seats_avg', 180) or 180),
            duracion_min=max(float(row.get('duracion_vuelo_min', 60) or 60), 1),
        )

    def _get_apu_co2(recat):
        recat_str = str(recat).upper() if pd.notna(recat) else 'D'
        return APU_FUEL_KG_PER_MIN.get(recat_str, 1.16) * CO2_PER_KG_FUEL

    co2_rate_aire   = df.apply(_co2_rate_aire, axis=1)
    co2_rate_tierra = df.get('recat', pd.Series('D', index=df.index)).apply(_get_apu_co2)

    co2_aire_delay   = (co2_rate_aire   * df['air_delay']).sum()
    co2_tierra_delay = (co2_rate_tierra * df['ground_delay']).sum()
    co2_total_delay  = co2_aire_delay + co2_tierra_delay

    # --- Coste del retraso — Cook & Tanner (2015), Tables 22-25 / 26-29 ---
    #
    # Metodología:
    #   1. Mapear ATYP → tipo Cook via _mapear_tipo_cook().
    #   2. Seleccionar tabla:
    #      · PRIMARY  (sin reactionary): margen_tat >= OTP_THRESHOLD_MIN → _COST_TOTAL_TABLE
    #      · FULL     (con reactionary): margen_tat <  OTP_THRESHOLD_MIN → _COST_HARD_TABLE
    #   3. Interpolar el coste TOTAL para el delay real de cada vuelo (no lineal).
    #   4. Ajustar por pasajeros reales vs. pax base Cook (Annex B2):
    #        factor_pax = (size_seats_avg × LOAD_FACTOR_EU) / pax_base_cook
    #   5. coste_vuelo = coste_tabla × factor_pax
    #
    # Fuente: Cook & Tanner (2015), University of Westminster para EUROCONTROL.
    #         Tables 22-29, Annex B2. Versión 4.1 (referencia año 2014).
    # -------------------------------------------------------------------------
    coste_total         = 0.0
    coste_primary_total = 0.0   # vuelos sin riesgo reactionary (margen_tat >= 15 min)
    coste_react_total   = 0.0   # vuelos con riesgo reactionary (margen_tat <  15 min)

    for i, row in df.iterrows():
        delay_real = float(row.get('total_delay', 0) or 0)
        if delay_real <= 0:
            continue

        tipo_icao = str(row.get('ATYP', row.get('f', ''))).upper().strip()
        recat     = str(row.get('recat', 'D')).upper()
        asientos  = int(row.get('size_seats_avg', 180) or 180)
        if asientos <= 0:
            asientos = 180

        tipo_cook = _mapear_tipo_cook(tipo_icao, recat, asientos)

        # Primary (Tables 22-25) vs Full/reactionary (Tables 26-29) segun margen TAT
        es_wide        = recat in ('A', 'B', 'C')
        tat_min_avion  = TAT_MIN['wide'] if es_wide else TAT_MIN['narrow']
        tat_disponible = float(row.get('tat_disponible', tat_min_avion + 20) or tat_min_avion + 20)
        margen_tat     = max(tat_disponible - tat_min_avion, 0)
        # usar_hard=True  -> tabla FULL con costes reactionary (Tables 26-29, hard only)
        # usar_hard=False -> tabla PRIMARY sin reactionary (Tables 22-25, hard+soft)
        usar_hard = margen_tat < OTP_THRESHOLD_MIN

        # Coste Cook interpolado para el delay REAL del vuelo (no lineal por franja)
        coste_tabla = _interpolar_coste(tipo_cook, delay_real, usar_hard)

        # Escalar por densidad de pasajeros reales vs. pax base Cook (Annex B2)
        # Cook tabula para su LF implicito; ajustamos con el LF real del vuelo.
        pax_base   = _PAX_BASE_TABLE.get(tipo_cook, 130)
        pax_reales = max(int(asientos * LOAD_FACTOR_EU), 1)
        factor_pax = pax_reales / pax_base

        coste_vuelo  = coste_tabla * factor_pax
        coste_total += coste_vuelo
        if usar_hard:
            coste_react_total   += coste_vuelo
        else:
            coste_primary_total += coste_vuelo

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
        'co2_tierra_delay_kg':    round(co2_tierra_delay, 2),
        'co2_total_delay_kg':     round(co2_total_delay, 2),
        # Cook & Tanner (2015) cost — non-linear table lookup per flight
        'coste_delay_eur':        round(coste_total, 2),
        'coste_primary_eur':      round(coste_primary_total, 2),
        'coste_reactionary_eur':  round(coste_react_total, 2),
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

    df_val    = resultados_ghp['task1_validation']
    rf_1      = resultados_ghp['rf_unitario']
    kpis_val  = calcular_kpis_ghp(df_val, rf_1, 'Task1_Validation')
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
        print(f"    CO2 tierra delay:   {kpis['co2_tierra_delay_kg']:.1f} kg")
        print(f"    CO2 total delay:    {kpis['co2_total_delay_kg']:.1f} kg")
        print(f"    Coste delay (Cook): {kpis['coste_delay_eur']:.0f} EUR")
        print(f"      (primary flights):  {kpis['coste_primary_eur']:.0f} EUR")
        print(f"      (reactionary flts): {kpis['coste_reactionary_eur']:.0f} EUR")
        print(f"    Air infeasible:     {kpis['infeasible_air']} vuelos")