import pandas as pd

# Asegúrate de importar aquí tus constantes (FEGP_KW_PER_RECAT, LOAD_FACTOR_EU, etc.)
# y tus funciones auxiliares (_mapear_tipo_cook, _interpolar_coste)

# Consumo eléctrico demandado por categoría RECAT en kW
FEGP_KW_PER_RECAT = {
    'A': 288.0,  # A388: 4 x 90 kVA (360 kVA * 0.8 = 288 kW)
    'B': 144.0,  # B789: 2 x 90 kVA (180 kVA * 0.8 = 144 kW)
    'C': 144.0,  # B764: 2 x 90 kVA (180 kVA * 0.8 = 144 kW)
    'D': 72.0,   # A320: 1 x 90 kVA (90 kVA * 0.8 = 72 kW)
    'E': 32.0,   # E190: Límite del bus interno (40 kVA * 0.8 = 32 kW)
    'F': 12.8,   # PC24: 28.5 VDC * 450 Amperios continuos = 12.8 kW
}

# Factor de emisión de la red eléctrica en España (kg CO2 / kWh) 
# Fuente: Red Eléctrica de España (REE) / MITERD 2023
GRID_EMISSION_FACTOR_KG_KWH = 0.283 

# Umbral OTP: delay < 15 min = "on-time" (IATA/CODA estándar).
OTP_THRESHOLD_MIN = 15

# Pasajeros base Annex 3 (Cook & Tanner 2015, base scenario).
_PAX_BASE_TABLE = {
    'A319': 113, 'A320': 130, 'A321': 158,
    'B733': 107, 'B734': 122, 'B738': 137,
    'B752': 167, 'B763': 207, 'B744': 334,
    'A332': 232, 'E190':  77, 'DH8D':  57,
    'AT72':  52, 'AT43':  36,
}

# Load factor europeo. Fuente: IATA Annual Review 2025, promedio europeo: 83,7%
LOAD_FACTOR_EU = 0.837

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

_DELAY_BREAKPOINTS = [5, 15, 30, 60, 90, 120, 180, 240, 300]

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

def evaluar_escenario(df_res: pd.DataFrame, nombre_escenario: str, h_start_min: int) -> dict:
    """
    Motor Unificado de Métricas (Unified Metrics Engine).
    Calcula KPIs Operacionales, Ambientales (Delgado + FEGP), Económicos (Cook 2015) 
    y de Equidad (RSD) de forma estandarizada para cualquier escenario.
    """
    if df_res.empty:
        return {}

    df = df_res.copy()
    # Asegurar columnas
    for col in ('total_delay', 'air_delay', 'ground_delay'):
        if col not in df.columns:
            df[col] = 0.0

    # ---------------------------------------------------------
    # 1. KPIs OPERACIONALES BÁSICOS
    # ---------------------------------------------------------
    n_flights = len(df)
    n_delayed = (df['total_delay'] > 0).sum()
    
    total_delay  = df['total_delay'].sum()
    air_delay    = df['air_delay'].sum()
    ground_delay = df['ground_delay'].sum()

    # Promedios y Máximos
    avg_total_delay  = df['total_delay'].mean() if n_flights > 0 else 0
    max_total_delay  = df['total_delay'].max() if n_flights > 0 else 0
    max_air_delay    = df['air_delay'].max() if n_flights > 0 else 0
    max_ground_delay = df['ground_delay'].max() if n_flights > 0 else 0

    # OTP (On-Time Performance): % Vuelos con retraso < 15 min
    vuelos_otp = (df['total_delay'] < OTP_THRESHOLD_MIN).sum()
    otp_pct = (vuelos_otp / n_flights) * 100 if n_flights > 0 else 0

    # Retraso Irrecuperable (Cancelación en H_START)
    ctd = df['minutes_etd'] + df['ground_delay']
    unrecoverable = pd.Series(0.0, index=df.index)
    
    caso2 = ctd <= h_start_min
    unrecoverable[caso2] = df.loc[caso2, 'ground_delay']
    
    caso3 = (df['minutes_etd'] < h_start_min) & (ctd > h_start_min)
    unrecoverable[caso3] = h_start_min - df.loc[caso3, 'minutes_etd']
    retraso_irrecuperable = unrecoverable.sum()

    # ---------------------------------------------------------
    # 2. KPIs AMBIENTALES (CO2)
    # ---------------------------------------------------------
    duracion_vuelo = df['duracion_vuelo_min'].clip(lower=1)
    if 'co2_kg_vuelo' in df.columns:
        co2_aire_delay = (df['co2_kg_vuelo'] * (df['air_delay'] / duracion_vuelo)).sum()
    else:
        co2_aire_delay = 0.0

    def _get_fegp_co2(recat):
        recat_str = str(recat).upper() if pd.notna(recat) else 'D'
        potencia_kw = FEGP_KW_PER_RECAT.get(recat_str, 72.0)
        return potencia_kw * (1 / 60.0) * GRID_EMISSION_FACTOR_KG_KWH

    co2_rate_tierra = df.get('recat', pd.Series('D', index=df.index)).apply(_get_fegp_co2)
    co2_tierra_delay = (co2_rate_tierra * df['ground_delay']).sum()

    # ---------------------------------------------------------
    # 3. KPIs ECONÓMICOS (Cook & Tanner 2015)
    # ---------------------------------------------------------
    costes_individuales = []
    for i, row in df.iterrows():
        delay_real = float(row.get('total_delay', 0) or 0)
        if delay_real <= 0:
            costes_individuales.append(0.0)
            continue

        tipo_icao = str(row.get('ATYP', row.get('f', ''))).upper().strip()
        recat     = str(row.get('recat', 'D')).upper()
        asientos  = max(int(row.get('size_seats_avg', 180) or 180), 1)

        tipo_cook = _mapear_tipo_cook(tipo_icao, recat, asientos)
        usar_hard = delay_real >= OTP_THRESHOLD_MIN
        coste_tabla = _interpolar_coste(tipo_cook, delay_real, usar_hard)

        pax_base   = _PAX_BASE_TABLE.get(tipo_cook, 130)
        pax_reales = max(int(asientos * LOAD_FACTOR_EU), 1)
        factor_pax = pax_reales / pax_base

        costes_individuales.append(coste_tabla * factor_pax)
    
    df['coste_retraso_eur'] = costes_individuales
    coste_total = sum(costes_individuales)
    coste_maximo = max(costes_individuales) if costes_individuales else 0.0
    coste_medio = coste_total / n_delayed if n_delayed > 0 else 0.0

    # ---------------------------------------------------------
    # 4. KPA EQUIDAD Y DISTRIBUCIÓN (RSD Global y Top Aerolíneas)
    # ---------------------------------------------------------
    # RSD Global (Air, Ground, Total)
    rsd_air = (df['air_delay'].std() / df['air_delay'].mean() * 100) if df['air_delay'].mean() > 0 else 0
    rsd_ground = (df['ground_delay'].std() / df['ground_delay'].mean() * 100) if df['ground_delay'].mean() > 0 else 0
    rsd_total = (df['total_delay'].std() / df['total_delay'].mean() * 100) if df['total_delay'].mean() > 0 else 0

    # Extracción Top 4 Aerolíneas
    top_airlines_data = {}
    if 'airline' in df.columns:  # Asegura que usas la columna correcta del indicativo (Opr o ARCID[:3])
        top_4 = df['airline'].value_counts().head(4).index
        for idx, al in enumerate(top_4, start=1):
            df_al = df[df['airline'] == al]
            avg_al = df_al['total_delay'].mean()
            std_al = df_al['total_delay'].std()
            rsd_al = (std_al / avg_al * 100) if (avg_al > 0 and pd.notna(std_al)) else 0
            
            top_airlines_data[f'Top{idx}_Aerolinea'] = al
            top_airlines_data[f'Top{idx}_Retraso_Medio_min'] = round(avg_al, 1)
            top_airlines_data[f'Top{idx}_RSD_%'] = round(rsd_al, 1)

    # ---------------------------------------------------------
    # DICCIONARIO UNIFICADO DE SALIDA
    # ---------------------------------------------------------
    kpis = {
        'Escenario':             nombre_escenario,
        'Vuelos_Totales':        n_flights,
        'Vuelos_Retrasados':     int(n_delayed),
        'OTP_%_Menor_15min':     round(otp_pct, 2),
        'Retraso_Total_min':     round(total_delay, 2),
        'Retraso_Max_min':       round(max_total_delay, 2),
        'Retraso_Medio_min':     round(avg_total_delay, 2),
        'Retraso_Aire_min':      round(air_delay, 2),
        'Retraso_Aire_Max_min':  round(max_air_delay, 2),
        'Retraso_Tierra_min':    round(ground_delay, 2),
        'Retraso_Tierra_Max_min':round(max_ground_delay, 2),
        'Retraso_Irrecup_min':   round(retraso_irrecuperable, 2),
        'CO2_Extra_Aire_kg':     round(co2_aire_delay, 2),
        'CO2_Extra_Tierra_kg':   round(co2_tierra_delay, 2),
        'CO2_Total_Retraso_kg':  round(co2_aire_delay + co2_tierra_delay, 2),
        'Coste_Cook_Total_EUR':  round(coste_total, 2),
        'Coste_Cook_Medio_EUR':  round(coste_medio, 2),
        'Coste_Cook_Max_EUR':    round(coste_maximo, 2),
        'RSD_Aire_%':            round(rsd_air, 2),
        'RSD_Tierra_%':          round(rsd_ground, 2),
        'RSD_Total_%':           round(rsd_total, 2),
    }
    
    # Añadimos los datos de las aerolíneas dinámicamente si existen
    kpis.update(top_airlines_data)

    return kpis