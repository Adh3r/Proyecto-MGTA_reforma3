# =============================================================================
# src/lib_data_prep.py
# FASE 1: Carga, limpieza y enriquecimiento cinemático de los datos de vuelo.
#
# Este módulo se encarga de transformar los CSVs crudos en un DataFrame limpio
# y enriquecido, listo para que el motor GDP lo procese.
#
# Responsabilidades:
#   1. Leer y limpiar los CSV de vuelos y flota.
#   2. Filtrar solo los vuelos que aterrizan en LEBL.
#   3. Convertir tiempos (HH:MM:SS) a minutos desde medianoche.
#   4. Calcular la distancia recorrida en vuelo (cinemática básica).
#   5. Añadir metadatos: si el vuelo es ECAC, código de aerolínea, etc.
# =============================================================================

import os

import numpy as np
import pandas as pd

# Importamos todas las constantes desde el archivo central.
# Así, si cambia una velocidad o un prefijo ECAC, solo tocamos config.py.
from config import ECAC_PREFIXES, VELOCIDAD_KNOTS


# =============================================================================
# FUNCIONES DE UTILIDAD (helpers pequeños y reutilizables)
# =============================================================================

def parse_time_to_minutes(time_str: str) -> float:
    """
    Convierte un string de tiempo "HH:MM" o "HH:MM:SS" a minutos decimales.

    Ejemplo:
        "06:30"     → 390.0
        "06:30:45"  → 390.75

    Args:
        time_str: El string de tiempo a convertir. Puede ser NaN.

    Returns:
        Los minutos totales como float. Devuelve 0.0 si el valor es inválido.

    ¿Por qué capturar ValueError y no Exception?
        Si hubiera un error de tipo inesperado (ej: un bug en el código),
        queremos que Python lo muestre en lugar de silenciarlo silenciosamente.
        Solo ignoramos errores que esperamos: valores mal formateados (ValueError)
        o atributos ausentes en tipos raros (AttributeError).
    """
    # Si la celda está vacía (NaN en pandas), devolvemos 0 directamente.
    if pd.isna(time_str):
        return 0.0

    try:
        # Dividimos "HH:MM:SS" por ":" y convertimos cada parte a entero.
        parts = list(map(int, str(time_str).split(':')))

        if len(parts) == 3:
            # Formato con segundos: horas*60 + minutos + segundos/60
            return parts[0] * 60 + parts[1] + (parts[2] / 60.0)
        elif len(parts) == 2:
            # Formato sin segundos: horas*60 + minutos
            return parts[0] * 60 + parts[1]
        elif len(parts) == 1:
            # Valor sin formato HH:MM — asumimos que ya está en minutos
            # Ej: "15" → 15.0 minutos de taxi time
            return float(parts[0])
        else:
            return 0.0

    except (ValueError, AttributeError):
        # ValueError:    el string no contiene números válidos (ej: "N/A", "??")
        # AttributeError: time_str es un tipo sin método .split() (raro pero posible)
        return 0.0


# =============================================================================
# FUNCIÓN PRINCIPAL: CARGA Y ENRIQUECIMIENTO DE VUELOS
# =============================================================================

def preparar_vuelos(path_vuelos: str, path_flota: str) -> pd.DataFrame:
    """
    Pipeline completo de preparación de datos: carga → limpia → enriquece.

    Pasos internos:
        1. Lee los dos CSVs (vuelos del día y catálogo de flota).
        2. Filtra solo vuelos con destino LEBL y origen distinto de LEBL.
        3. Une el DataFrame de vuelos con la categoría de estela y nº de asientos.
        4. Convierte ETA, ETD y TT de "HH:MM" a minutos.
        5. Añade flags: is_ecac (¿viene de Europa?) y columna airline (código ICAO).
        6. Calcula la distancia en km recorrida en vuelo (física cinemática).

    Args:
        path_vuelos: Ruta al CSV con el plan de vuelos del día (LEBL_10AUG2025.csv).
        path_flota:  Ruta al CSV con la clasificación de la flota (fleet_cat_seat.csv).

    Returns:
        DataFrame con una fila por vuelo, ordenado por ETA (hora estimada de llegada),
        listo para el motor GDP.
    """
    print("   -> Leyendo datos y calculando distancias cinemáticas...")

    # -------------------------------------------------------------------------
    # PASO 1: Carga de los CSVs
    # sep=';' porque el formato europeo usa punto y coma en lugar de coma.
    # -------------------------------------------------------------------------
    df = pd.read_csv(path_vuelos, sep=';')
    flota = pd.read_csv(path_flota, sep=';')

    # -------------------------------------------------------------------------
    # PASO 2: Filtro base — solo llegadas a LEBL, excluyendo vuelos locales
    # Un vuelo LEBL→LEBL sería un circuito de pruebas, no nos interesa.
    # .copy() es importante: evita el warning "SettingWithCopyWarning" de pandas
    # al modificar un subconjunto de un DataFrame original.
    # -------------------------------------------------------------------------
    df = df[(df['ADES'] == 'LEBL') & (df['ADEP'] != 'LEBL')].copy()

    # -------------------------------------------------------------------------
    # PASO 3: Unión con el catálogo de flota
    # Queremos saber la categoría de estela (recat) y el nº medio de asientos
    # para cada tipo de avión (ATYP). Usamos LEFT JOIN para no perder vuelos
    # aunque no tengamos datos de ese tipo de avión en el catálogo.
    # -------------------------------------------------------------------------
    flota.columns = flota.columns.str.strip()           # Elimina espacios en nombres de columna
    flota = flota.rename(columns={'f': 'ATYP'})         # Renombramos para que coincida con df

    df = pd.merge(
        df,
        flota[['ATYP', 'recat', 'size_seats_avg']],
        on='ATYP',
        how='left',
    )

    # -------------------------------------------------------------------------
    # PASO 4: Conversión de tiempos a minutos
    # Pasamos de strings "HH:MM" a un número flotante (ej: 390.5 min).
    # Esto facilita enormemente las operaciones aritméticas posteriores.
    # -------------------------------------------------------------------------
    df['minutes_eta'] = df['ETA'].apply(parse_time_to_minutes)   # Hora estimada de llegada
    df['minutes_etd'] = df['ETD'].apply(parse_time_to_minutes)   # Hora estimada de despegue
    df['minutes_tt']  = df['TT'].apply(parse_time_to_minutes)    # Taxi time (rodaje en tierra)

    # -------------------------------------------------------------------------
    # PASO 5: Metadatos de regulación
    # is_ecac: ¿El aeropuerto de origen tiene prefijo OACI europeo?
    #          True  → el vuelo puede recibir una restricción GDP.
    #          False → vuelo intercontinental, exento de regulación.
    # airline: Los 3 primeros caracteres del indicativo de vuelo = código ICAO
    #          de la aerolínea (ej: "IBE123" → aerolínea "IBE" = Iberia).
    # -------------------------------------------------------------------------
    df['is_ecac'] = df['ADEP'].astype(str).str.startswith(ECAC_PREFIXES)
    df['airline'] = df['ARCID'].str[:3]

    # -------------------------------------------------------------------------
    # PASO 6: Cálculo de la distancia recorrida en vuelo (cinemática)
    #
    # Fórmula:
    #   distancia_km = tiempo_vuelo_puro (horas) × velocidad (kt) × 1.852 (km/kt)
    #
    # tiempo_vuelo_puro = duración_total - taxi_time - 5.5 min de margen
    #   La duración total puede ser negativa si un vuelo despega antes de
    #   medianoche y llega después (ej: ETD=23:30, ETA=01:00 → diferencia=-22h).
    #   En ese caso sumamos 1440 min (= 24h) para corregirlo.
    # -------------------------------------------------------------------------
    duration_min = df['minutes_eta'] - df['minutes_etd']
    duration_min = np.where(duration_min < 0, duration_min + 1440, duration_min)

    # Tiempo real en el aire, en horas (descontamos taxi y un pequeño margen)
    air_time_hours = (duration_min - df['minutes_tt'] - 5.5) / 60.0

    # Velocidad típica según categoría de estela (kt), con fallback a 440 kt
    speed_kts = df['recat'].map(VELOCIDAD_KNOTS).fillna(440)

    # Distancia en km; .clip(lower=0) evita distancias negativas por datos sucios
    df['distancia_km'] = (air_time_hours * speed_kts * 1.852).clip(lower=0)

    # -------------------------------------------------------------------------
    # PASO FINAL: Ordenar por ETA
    # El motor GDP procesará los vuelos en orden de llegada, así que
    # entregamos el DataFrame ya ordenado para facilitar ese trabajo.
    # -------------------------------------------------------------------------
    return df.sort_values('minutes_eta').reset_index(drop=True)


# =============================================================================
# MODO DEBUG — Solo se ejecuta si llamas a este script directamente:
#   python lib_data_prep.py
# No se ejecuta cuando otro módulo hace "import lib_data_prep".
# =============================================================================
if __name__ == "__main__":
    print("🛠️  MODO DEBUG: Probando lib_data_prep.py de forma independiente...")

    # Calculamos la ruta base del proyecto (dos niveles arriba de /src/)
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    p_vuelos    = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota     = os.path.join(base, 'data/raw/fleet_cat_seat.csv')
    p_debug_out = os.path.join(base, 'debug/DEBUG_01_preprocesado.xlsx')

    # Ejecutamos el pipeline completo
    df_debug = preparar_vuelos(p_vuelos, p_flota)

    # Guardamos en la carpeta debug/ para inspección manual
    os.makedirs(os.path.dirname(p_debug_out), exist_ok=True)
    df_debug.to_excel(p_debug_out, index=False)

    print(f"✅ Excel intermedio generado en: {p_debug_out}")
    print(f"   Vuelos procesados: {len(df_debug)}")
    print("   → Ábrelo para verificar 'distancia_km' y 'minutes_eta'.")
