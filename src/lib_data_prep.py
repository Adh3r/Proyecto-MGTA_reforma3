# =============================================================================
# Data Prep - Phase 1
# Maps raw CSV data to the clean format needed for GDP processing.
#
# Steps:
#   - Load flight schedule & fleet specs
#   - Filter arrivals (LEBL)
#   - Join aircraft metadata (seats/type)
#   - Time conversion (HH:MM -> minutes)
#   - Region tagging (ECAC) & airline ID
#   - Distance + CO2 calculations
#
# Decoupled logic: no processing here, just data cleaning.
# =============================================================================

import os
import numpy as np
import pandas as pd

# Import constants from config.py
from config import ECAC_PREFIXES, VELOCIDAD_KNOTS

# =============================================================================
# CONVERT TIME TO MINUTES
# =============================================================================

def parse_time_to_minutes(time_str: str) -> float:
    """
    Parses a time string into decimal minutes from midnight.

    Args:
        time_str: Time string to convert (handles NaN from CSV).

    Returns:
        float: Total minutes. Returns 0.0 if input is invalid or missing.
    """
    # Handle empty CSV cells (Pandas NaNs). 
    # Returning 0 to avoid crashing the math down the line.
    if pd.isna(time_str):
        return 0.0

    try:
        # Parse time string into components
        partes = list(map(int, str(time_str).split(':')))

        if len(partes) == 3:
            # HH:MM:SS format
            return partes[0] * 60 + partes[1] + partes[2] / 60
        elif len(partes) == 2:
            # HH:MM format
            return partes[0] * 60 + partes[1]
        elif len(partes) == 1:
            # Plain numeric (e.g., taxi time "12" -> 12 mins)
            return float(partes[0])
        else:
            return 0.0  # Unknown format

    except (ValueError, AttributeError):
        # Catch non-numeric strings (e.g. "N/A") or types without .split()
        # Default to 0.0 to keep the data pipeline running.
        return 0.0

# =============================================================================
# PRINCIPAL FUNCTION: LOADING FLIGHTS
# =============================================================================

def preparar_vuelos(path_vuelos: str, path_flota: str) -> pd.DataFrame:
    """
    Args:
        path_vuelos: Path to the daily flight schedule CSV (e.g., LEBL_10AUG2025.csv).
        path_flota: Path to the fleet classification CSV (fleet_cat_seat.csv).

    Returns:
        pd.DataFrame: Clean, enriched table sorted by ETA. 
                      Includes distance_km, is_ecac, co2_kg_vuelo, etc.
    """
    print("   -> Leyendo datos y calculando distancias cinemáticas...")

    # =========================================================================
    # STEP 1: READ THE 2 CSVs
    # =========================================================================
    # separator=';' 
    df_vuelos = pd.read_csv(path_vuelos, sep=';')
    df_flota  = pd.read_csv(path_flota,  sep=';')

    # =========================================================================
    # STEP 2: ONLY ARRIVALS TO LEBL
    # =========================================================================
   # Filter for LEBL arrivals only. 
    # Drop LEBL->LEBL flights (test circuits or local loops).
    df_vuelos = df_vuelos[
        (df_vuelos['ADES'] == 'LEBL') & 
        (df_vuelos['ADEP'] != 'LEBL')
    ].copy()

    # =========================================================================
    # STEP 3: FLEET DATA MERGE
    # =========================================================================
    # Adds 'recat' (for cruise speed) and 'size_seats_avg' (for CO2 calc) 
    # based on aircraft type (ATYP).

    # Cleanup: strip whitespace and match column names for the join
    df_flota.columns = df_flota.columns.str.strip()
    df_flota = df_flota.rename(columns={'f': 'ATYP'})

    # Left join to keep all flights even if ATYP is missing in the catalog
    df_vuelos = pd.merge(
        df_vuelos,
        df_flota[['ATYP', 'recat', 'size_seats_avg']],
        on='ATYP',
        how='left'
    )

    # =========================================================================
    # STEP 4: TIME CONVERSION (MINUTES FROM MIDNIGHT)
    # =========================================================================
    df_vuelos['minutes_eta'] = df_vuelos['ETA'].apply(parse_time_to_minutes)
    df_vuelos['minutes_etd'] = df_vuelos['ETD'].apply(parse_time_to_minutes)
    df_vuelos['minutes_tt']  = df_vuelos['TT'].apply(parse_time_to_minutes)

    # =========================================================================
    # STEP 5: ECAC TAGGING & AIRLINE extraction
    # =========================================================================
    # Tagging ECAC flights
    df_vuelos['is_ecac'] = df_vuelos['ADEP'].astype(str).str.startswith(ECAC_PREFIXES)

    # Standard 3-letter ICAO airline code from flight ID
    df_vuelos['airline'] = df_vuelos['ARCID'].str[:3]

    # =========================================================================
    # STEP 6: FLIGHT DISTANCE CALCULATION
    # =========================================================================
    # Used for GDP coverage radius and CO2 estimations.
    # Logic: air_time = (ETA - ETD) - taxi_time - 5.5min buffer.
    
    duracion_total_min = df_vuelos['minutes_eta'] - df_vuelos['minutes_etd']

    # Midnight crossover fix: if arrival < departure, add 24h
    duracion_total_min = np.where(duracion_total_min < 0, duracion_total_min + 1440, duracion_total_min)

    # Actual airborne hours ( - taxi and maneuvering buffer)
    tiempo_en_aire_horas = (duracion_total_min - df_vuelos['minutes_tt'] - 5.5) / 60.0

    # Cruise speed based on RECAT; fallback to 440kt (CAT D) if unknown
    velocidad_crucero_kt = df_vuelos['recat'].map(VELOCIDAD_KNOTS).fillna(440)

    # Final distance in km (1.852 factor for NM to KM)
    df_vuelos['distancia_km'] = (tiempo_en_aire_horas * velocidad_crucero_kt * 1.852).clip(lower=0)

    # =========================================================================
    # STEP 7: CO2 EMISSIONS (Montlaur, Trapote-Barreira & Delgado, 2025)
    # =========================================================================
    # Using ASK (Available Seat Kilometer) model:
    # CO2 [kg] = (gCO2/ASK * distance * seats) / 1000
    from emissions_fuel_model import compute_co2_ask

    def _calcular_co2_vuelo(fila) -> float:
        distancia = fila['distancia_km']
        asientos  = fila['size_seats_avg']
        duracion  = fila['minutes_eta'] - fila['minutes_etd']

        if duracion < 0: duracion += 1440

        # Data check
        if distancia <= 0 or pd.isna(asientos) or asientos <= 0 or duracion <= 0:
            return 0.0

        # Force=True extrapolates for edge cases (very short flights/odd aircraft)
        co2_por_ask = compute_co2_ask(distancia, int(asientos), force=True)
        return round(co2_por_ask * distancia * asientos / 1000, 2)

    df_vuelos['co2_kg_vuelo'] = df_vuelos.apply(_calcular_co2_vuelo, axis=1)

    # Store clean duration for downstream economic KPIs
    df_vuelos['duracion_vuelo_min'] = np.where(
        duracion_total_min <= 0, duracion_total_min + 1440, duracion_total_min
    ).clip(min=1)

    # =========================================================================
    # FINAL EXPORT: SORT BY ETA
    # =========================================================================
    # GDP engine expects chronological arrival order.
    return df_vuelos.sort_values('minutes_eta').reset_index(drop=True)

# --- DEBUG MODE ---
if __name__ == "__main__":
    print("🛠️  DEBUG: Testing lib_data_prep.py...")

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota  = os.path.join(base, 'data/raw/fleet_cat_seat.csv')
    p_debug_out = os.path.join(base, 'debug/DEBUG_01_preprocesado.xlsx')

    df_debug = preparar_vuelos(p_vuelos, p_flota)

    os.makedirs(os.path.dirname(p_debug_out), exist_ok=True)
    df_debug.to_excel(p_debug_out, index=False)

    print(f"✅ Success! Enriched {len(df_debug)} flights.")
    print(f"📍 Output: {p_debug_out}")