# =============================================================================
# src/lib_data_prep.py
# FASE 1: Carga, limpieza y enriquecimiento de los datos de vuelo.
#
# Transforma los CSVs en una tabla limpia
# lista para que el motor GDP la procese.
#
# FLUJO (en orden de ejecución dentro de preparar_vuelos):
#   Paso 1 → Leer los dos CSVs (vuelos del día + catálogo de flota)
#   Paso 2 → Filtrar solo vuelos que aterrizan en LEBL
#   Paso 3 → Unir con el catálogo de flota (categoría + nº asientos)
#   Paso 4 → Convertir tiempos "HH:MM" a minutos desde medianoche
#   Paso 5 → Marcar si el vuelo viene de Europa (ECAC) y extraer código aerolínea
#   Paso 6 → Calcular la distancia recorrida en vuelo 
#   Paso 7 → Calcular las emisiones CO2 de cada vuelo 
#
# SEPARACIÓN:
#   SOLO prepara datos, entrega una tabla limpia.
# =============================================================================

import os
import numpy as np
import pandas as pd

# Importamos las constantes desde config.py, si cambia una velocidad o un
# ECAC, solo hay que tocar config.py.
from config import ECAC_PREFIXES, VELOCIDAD_KNOTS

# =============================================================================
# AUXILIAR: CONVERTIR TIEMPO A MINUTOS
# =============================================================================

def parse_time_to_minutes(time_str: str) -> float:
    """
    Convierte un string de tiempo en minutos decimales desde medianoche.

    inputs:
        time_str: El string de tiempo a convertir (puede venir del CSV como NaN).

    Returns:
        Los minutos totales como número decimal. Devuelve 0.0 si el valor es inválido.
    """
    # Si la celda del CSV está vacía, pandas la lee como NaN.
    # pd.isna() detecta este caso y devolvemos 0 para no romper los cálculos.
    if pd.isna(time_str):
        return 0.0

    try:
        # Separamos el string por ":" y convertimos cada parte a entero.
        # "06:30:45".split(':') → ['06', '30', '45']
        # map(int, ...) convierte cada string a entero: [6, 30, 45]
        partes = list(map(int, str(time_str).split(':')))

        if len(partes) == 3:
            # Formato HH:MM:SS → horas×60 + minutos + segundos/60
            return partes[0] * 60 + partes[1] + partes[2] / 60
        elif len(partes) == 2:
            # Formato HH:MM → horas×60 + minutos
            return partes[0] * 60 + partes[1]
        elif len(partes) == 1:
            # Formato numérico solo (ej: taxi time "12" → 12 minutos)
            return float(partes[0])
        else:
            return 0.0  # Formato desconocido

    except (ValueError, AttributeError):
        # ValueError:    el string contiene texto no numérico (ej: "N/A", "??")
        # AttributeError: time_str es un tipo que no tiene .split()
        # En ambos casos devolvemos 0.0 para no interrumpir el procesamiento.
        return 0.0

# =============================================================================
# FUNCIÓN PRINCIPAL: CARGA Y ENRIQUECIMIENTO DE VUELOS
# =============================================================================

def preparar_vuelos(path_vuelos: str, path_flota: str) -> pd.DataFrame:
    """
    returns:
        Una tabla con una fila por vuelo, ordenada por ETA,
        columnas: distancia_km, is_ecac, co2_kg_vuelo...
        DataFrame limpio y enriquecido, ordenado por ETA, listo para el GDP.

    inputs:
        path_vuelos: Ruta al CSV con el plan de vuelos del día (LEBL_10AUG2025.csv).
        path_flota:  Ruta al CSV con la clasificación de la flota (fleet_cat_seat.csv).
    """
    print("   -> Leyendo datos y calculando distancias cinemáticas...")

    # =========================================================================
    # PASO 1: LEER LOS DOS CSVs
    # =========================================================================
    # separador=';' 
    df_vuelos = pd.read_csv(path_vuelos, sep=';')
    df_flota  = pd.read_csv(path_flota,  sep=';')

    # =========================================================================
    # PASO 2: FILTRAR SOLO LLEGADAS A LEBL
    # =========================================================================
    # Nos quedamos únicamente con vuelos que ATERRIZAN en LEBL (Barcelona).
    # Excluimos vuelos LEBL→LEBL (circuitos de prueba, no nos interesan).
    #
    df_vuelos = df_vuelos[
        (df_vuelos['ADES'] == 'LEBL') &   # Destino = Barcelona
        (df_vuelos['ADEP'] != 'LEBL')      # Origen != Barcelona (excluir locales)
    ].copy()

    # =========================================================================
    # PASO 3: UNIR CON LA LISTA
    # =========================================================================
    # Nos da dos datos por tipo de avión (ATYP):
    #   - recat:          categoría (A, B, C, D, E, F)
    #                     usada para calcular la velocidad de crucero
    #   - size_seats_avg: número medio de asientos
    #                     usado para calcular las emisiones CO2
    #
    # CÓMO FUNCIONA pd.merge() (equivalente a un JOIN de base de datos):
    #   Buscamos en df_flota la fila cuyo ATYP coincide con el ATYP de cada vuelo.
    #   how='left' significa que nos quedamos con TODOS los vuelos aunque su tipo
    #   de avión no aparezca en el catálogo (en ese caso, las columnas quedan NaN).

    # Limpieza previa: eliminar espacios en los nombres de columna
    # y renombrar la columna 'f' a 'ATYP' para que coincida con df_vuelos.
    df_flota.columns = df_flota.columns.str.strip()
    df_flota = df_flota.rename(columns={'f': 'ATYP'})

    df_vuelos = pd.merge(
        df_vuelos,
        df_flota[['ATYP', 'recat', 'size_seats_avg']],
        on='ATYP',    # Columna común que usamos para unir las dos tablas
        how='left',   # Mantenemos todos los vuelos aunque no estén en el catálogo
    )

    # =========================================================================
    # PASO 4: CONVERTIR TIEMPOS A MINUTOS DESDE MEDIANOCHE
    # =========================================================================
    # Convertimos las columnas de tiempo de strings "HH:MM" a números.
    # .apply(función) aplica la función a cada fila de la columna.
    df_vuelos['minutes_eta'] = df_vuelos['ETA'].apply(parse_time_to_minutes)  # Llegada prevista
    df_vuelos['minutes_etd'] = df_vuelos['ETD'].apply(parse_time_to_minutes)  # Despegue previsto
    df_vuelos['minutes_tt']  = df_vuelos['TT'].apply(parse_time_to_minutes)   # Taxi time (rodaje)

    # =========================================================================
    # PASO 5: MARCAR ORIGEN ECAC Y EXTRAER CÓDIGO DE AEROLÍNEA
    # =========================================================================
    # is_ecac: El aeropuerto de origen está en el espacio aéreo europeo (ECAC)
    #   - True  → el vuelo puede recibir una restricción GDP (está bajo el rango ECAC)
    #   - False → vuelo intercontinental, exento de regulación GDP
    #
    # Los prefijos ECAC son los primeros 2 caracteres del código OACI del aeropuerto.
    #
    # .str.startswith(vec) comprueba si el string empieza por alguno de los prefijos
    # del vector
    df_vuelos['is_ecac'] = df_vuelos['ADEP'].astype(str).str.startswith(ECAC_PREFIXES)

    # airline: Los 3 primeros caracteres del indicativo de vuelo = código ICAO aerolínea.
    df_vuelos['airline'] = df_vuelos['ARCID'].str[:3]

    # =========================================================================
    # PASO 6: CALCULAR LA DISTANCIA RECORRIDA EN VUELO 
    # =========================================================================
    # Necesitamos la distancia de cada vuelo para:
    #   a) Saber si está dentro del radio de cobertura del GDP.
    #   b) Calcular las emisiones CO2.
    #
    # FÓRMULA:
    #   distancia_km = tiempo_en_aire (horas) × velocidad_crucero (kt) × 1.852 (km/kt)
    #
    # CÁLCULO DEL TIEMPO EN AIRE:
    #   tiempo_en_aire = (ETA - ETD) - taxi_time - 5.5 min de margen
    #
    # CORRECCIÓN PARA VUELOS QUE CRUZAN MEDIANOCHE:
    #   Si un vuelo despega a las 23:30 (=1410 min) y llega a las 01:00 (=60 min),
    #   la resta daría 60 - 1410 = -1350 min (quedaria negativo).
    #   La solución es sumar 1440 min (= 24 horas) cuando el resultado es negativo.

    duracion_total_min = df_vuelos['minutes_eta'] - df_vuelos['minutes_etd']

    # np.where() es el equivalente
    # usando vectores de: para cada fila, si la duración es negativa, sumar 1440
    duracion_total_min = np.where(
        duracion_total_min < 0,
        duracion_total_min + 1440,  # Corrección para vuelos que cruzan medianoche
        duracion_total_min          # Sin corrección para el resto
    )

    # Tiempo real en el aire en horas (sin taxi ni margen de maniobra)
    tiempo_en_aire_horas = (duracion_total_min - df_vuelos['minutes_tt'] - 5.5) / 60.0

    # Velocidad según categoría (kt).
    # .map() sustituye cada valor de la columna por su valor en el diccionario.
    # .fillna(440) asigna 440 kt (la que hemos elegido de media) si la categoría no está en el diccionario.
    velocidad_crucero_kt = df_vuelos['recat'].map(VELOCIDAD_KNOTS).fillna(440)

    # Distancia en km. 1 kt × 1 hora = 1 NM = 1.852 km.
    # .clip(lower=0) elimina distancias negativas que pueden aparecer por datos mal procesados.
    df_vuelos['distancia_km'] = (tiempo_en_aire_horas * velocidad_crucero_kt * 1.852).clip(lower=0)

    # =========================================================================
    # PASO 7: CALCULAR EMISIONES CO2 POR VUELO — MODELO DELGADO ET AL. (2025)
    # =========================================================================
    # Usamos el modelo analítico publicado en:
    #   Montlaur, A., Trapote-Barreira, C., & Delgado, L. (2025).
    #   Applied Sciences, 15(17), 9688.
    #   https://doi.org/10.3390/app15179688
    #
    # QUÉ ES ASK (Available Seat Kilometer):
    #   Es la unidad estándar de la industria aérea para medir la capacidad
    #   ofertada. 1 ASK = 1 asiento disponible transportado 1 km.
    #   Un avión de 180 asientos que vuela 1000 km genera 180.000 ASK.
    #
    # QUÉ CALCULA EL MODELO:
    #   compute_co2_ask(distancia, asientos) → gramos de CO2 por ASK (gCO2/ASK)
    #
    # CÓMO OBTENEMOS KG TOTALES DEL VUELO:
    #   co2_total_kg = co2_por_ask [gCO2/ASK]
    #                × distancia [km]
    #                × asientos [ASK/km]
    #                / 1000 [g → kg]
    #
    # force=True: algunos vuelos muy cortos o con aviones inusuales quedan fuera
    # del rango validado del modelo. Con force=True el modelo extrapola en lugar
    # de lanzar un error, lo cual es aceptable para nuestro análisis.

    from emissions_fuel_model import compute_co2_ask

    def _calcular_co2_vuelo(fila) -> float:
        """Calcula el CO2 total (kg) de un vuelo usando el modelo de Delgado."""
        distancia = fila['distancia_km']
        asientos  = fila['size_seats_avg']
        duracion  = fila['minutes_eta'] - fila['minutes_etd']

        # Corrección para vuelos que cruzan medianoche
        if duracion < 0:
            duracion += 1440

        # Si algún dato esencial es inválido, devolvemos 0 para no romper el cálculo
        if distancia <= 0 or pd.isna(asientos) or asientos <= 0 or duracion <= 0:
            return 0.0

        # compute_co2_ask devuelve gramos de CO2 por ASK
        co2_por_ask = compute_co2_ask(distancia, int(asientos), force=True)

        # Convertimos a kg totales del vuelo completo
        co2_total_kg = co2_por_ask * distancia * asientos / 1000
        return round(co2_total_kg, 2)

    # .apply(f, axis=1) aplica la función a cada FILA (axis=1) del DataFrame.
    # Es equivalente a un bucle for sobre las filas
    df_vuelos['co2_kg_vuelo'] = df_vuelos.apply(_calcular_co2_vuelo, axis=1)

    # Guardamos la duración del vuelo como columna porque la necesita
    # calcular_kpis_economicos() para el cálculo proporcional de CO2.
    # .clip(min=1) garantiza mínimo 1 minuto para evitar divisiones por cero.
    df_vuelos['duracion_vuelo_min'] = np.where(
        duracion_total_min <= 0,
        duracion_total_min + 1440,  # Corrección medianoche
        duracion_total_min
    ).clip(min=1)

    # =========================================================================
    # PASO FINAL: ORDENAR POR ETA Y DEVOLVER
    # =========================================================================
    # El motor GDP procesa vuelos en orden de llegada. Entregamos la tabla ya ordenada.
    # reset_index(drop=True) renumera las filas desde 0 después del filtrado.
    return df_vuelos.sort_values('minutes_eta').reset_index(drop=True)

# =============================================================================
# MODO DEBUG — Ejecutar directamente para probar este módulo de forma aislada.
#   cd src/
#   python lib_data_prep.py
# =============================================================================
if __name__ == "__main__":
    print("🛠️  MODO DEBUG: lib_data_prep.py")

    # Construimos la ruta base del proyecto subiendo dos niveles desde /src/
    base        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos    = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota     = os.path.join(base, 'data/raw/fleet_cat_seat.csv')
    p_debug_out = os.path.join(base, 'debug/DEBUG_01_preprocesado.xlsx')

    df_debug = preparar_vuelos(p_vuelos, p_flota)

    os.makedirs(os.path.dirname(p_debug_out), exist_ok=True)
    df_debug.to_excel(p_debug_out, index=False)

    print(f"✅ Excel intermedio generado en: {p_debug_out}")
    print(f"   Vuelos procesados: {len(df_debug)}")
    print(f"   Columnas: {list(df_debug.columns)}")
    print("   → Abre el archivo y verifica 'distancia_km', 'co2_kg_vuelo' y 'minutes_eta'.")
