# =============================================================================
# src/lib_intermodal.py
# WP4: Análisis de Intermodalidad — Sustitución de vuelos cortos por tren
#
# CONTEXTO:
#   Los vuelos de corta distancia (<500-600 km) son altamente ineficientes
#   en términos de emisiones de CO2 y tiempo door-to-door (D2D).
#   El tren de alta velocidad (HSR) puede ser competitivo en rutas cortas
#   y tiene una huella de carbono significativamente menor.
#
# METODOLOGÍA WP4:
#   1. Identificar rutas substituibles (distancia ≤ umbral, con conexión HSR)
#   2. Calcular tiempo D2D para avión vs tren
#   3. Calcular emisiones CO2 para avión vs tren
#   4. Eliminar vuelos substituibles de la demanda
#   5. Re-simular GDP y GHP con demanda reducida
#   6. Comparar KPIs: retraso total, HNoReg, emisiones, coste
#
# HIPÓTESIS Y FUENTES:
#   - Umbral de distancia: 500 km (UIC/CER 2021)
#   - Velocidad media HSR: 200 km/h (Renfe AVE, SNCF TGV)
#   - Tiempo acceso aeropuerto: 90 min / Tiempo acceso estación tren: 30 min
#   - Emisiones tren: Lookup Table dinámica basada en EcoPassenger 2025 (UIC)
# =============================================================================

import os
import pandas as pd
import numpy as np
from typing import Tuple

from config import CFG, FS_CANDIDATE
import lib_gdp_core as gdp
from lib_gdp_core import calcular_kpis_economicos
from lib_ghp_solver import ejecutar_ghp_completo, calcular_kpis_ghp

# =============================================================================
# CONSTANTES WP4
# =============================================================================

DISTANCIA_MAX_INTERMODAL_KM = 500
VELOCIDAD_HSR_KMH = 200
TIEMPO_ACCESO_AEROPUERTO_MIN = 90
TIEMPO_ACCESO_ESTACION_MIN = 30

# Destinos con conexión HSR directa desde Barcelona (LEBL)
DESTINOS_HSR_DESDE_LEBL = {
    'LEMD': {'ciudad': 'Madrid',    'tiempo_tren_h': 2.5},   # AVE Barcelona-Madrid
    'LEVC': {'ciudad': 'Valencia',  'tiempo_tren_h': 3.0},   # AVE Barcelona-Valencia
    'LEZG': {'ciudad': 'Zaragoza',  'tiempo_tren_h': 1.5},   # AVE Barcelona-Zaragoza
    'LFBO': {'ciudad': 'Toulouse',  'tiempo_tren_h': 3.5},   # Conexión internacional
    'LEAL': {'ciudad': 'Alicante',  'tiempo_tren_h': 4.0},   # AVE / Euromed
    'LFML': {'ciudad': 'Marsella',  'tiempo_tren_h': 4.5},   # AVE / TGV
    'LFLL': {'ciudad': 'Lyon',      'tiempo_tren_h': 5.0},   # AVE / TGV
}

# MATRIZ DE EMISIONES TREN (gCO2/pax-km) - Extraído de EcoPassenger / MITECO / SNCF
# Usamos códigos OACI para que coincidan con la columna 'ADEP' del CSV
FACTORES_CO2_TREN = {
    'LEMD': 14.3,  # Madrid 
    'LEVC': 14.5,  # Valencia
    'LEAL': 14.5,  # Alicante
    'LEZG': 14.5,  # Zaragoza
    'LEBB': 15.1,  # Bilbao 
    'LFML': 3.4,   # Marsella (Mix nuclear francés)
    'LFBO': 3.4,   # Toulouse
    'LFLL': 3.4,   # Lyon
    'LFPO': 3.5,   # París Orly
    'LFPG': 3.5,   # París CDG
    'DEFAULT_ES': 14.8, # Otros aeropuertos en España (LExx)
    'DEFAULT_FR': 3.5,  # Otros aeropuertos en Francia (LFxx)
    'DEFAULT_INT': 25.0 # Resto del mundo / trenes convencionales
}


# =============================================================================
# PASO 1: IDENTIFICAR RUTAS SUBSTITUIBLES
# =============================================================================

def identificar_vuelos_substituibles(
    df_vuelos: pd.DataFrame,
    verbose: bool = True,
) -> pd.DataFrame:
    df = df_vuelos.copy()

    df['es_substituible'] = (
        (df['distancia_km'] <= DISTANCIA_MAX_INTERMODAL_KM) &
        (df['ADEP'].isin(DESTINOS_HSR_DESDE_LEBL.keys())) &
        (df['ADES'] == 'LEBL')
    )

    n_substituibles = df['es_substituible'].sum()
    pct = (n_substituibles / len(df)) * 100 if len(df) > 0 else 0

    if verbose:
        print(f"\n   🚄 ANÁLISIS INTERMODAL:")
        print(f"      Total vuelos a LEBL:     {len(df)}")
        print(f"      Vuelos substituibles:    {n_substituibles} ({pct:.1f}%)")
        print(f"      Distancia máx:           {DISTANCIA_MAX_INTERMODAL_KM} km")
    return df


# =============================================================================
# PASO 2: CALCULAR TIEMPO DOOR-TO-DOOR (D2D)
# =============================================================================

def calcular_tiempo_d2d(
    distancia_km: float,
    origen_icao: str,
    es_avion: bool = True,
) -> float:
    if es_avion:
        tiempo_vuelo_h = distancia_km / (440 * 1.852)  # kt → km/h
        tiempo_vuelo_min = tiempo_vuelo_h * 60
        tiempo_acceso = TIEMPO_ACCESO_AEROPUERTO_MIN
        tiempo_egreso = TIEMPO_ACCESO_AEROPUERTO_MIN / 2  # Sin check-in salida
        return tiempo_acceso + tiempo_vuelo_min + tiempo_egreso
    else:
        if origen_icao in DESTINOS_HSR_DESDE_LEBL:
            tiempo_tren_h = DESTINOS_HSR_DESDE_LEBL[origen_icao]['tiempo_tren_h']
        else:
            tiempo_tren_h = distancia_km / VELOCIDAD_HSR_KMH
        tiempo_tren_min = tiempo_tren_h * 60
        tiempo_acceso = TIEMPO_ACCESO_ESTACION_MIN
        tiempo_egreso = 15  # Salida rápida de estación
        return tiempo_acceso + tiempo_tren_min + tiempo_egreso


# =============================================================================
# PASO 3: CALCULAR EMISIONES AVIÓN VS TREN (ACTUALIZADO CON RUTAS)
# =============================================================================

def calcular_emision_tren(
    distancia_km: float,
    origen_icao: str,
    n_pasajeros: int,
) -> float:
    """
    Calcula las emisiones de CO2 del tren para una ruta usando la Lookup Table.
    """
    # 1. Obtener el factor específico de la ruta
    factor = FACTORES_CO2_TREN.get(origen_icao)
    
    # 2. Si no está en la lista exacta, inferir por país (Prefijo OACI)
    if factor is None:
        if origen_icao.startswith('LE'):
            factor = FACTORES_CO2_TREN['DEFAULT_ES']
        elif origen_icao.startswith('LF'):
            factor = FACTORES_CO2_TREN['DEFAULT_FR']
        else:
            factor = FACTORES_CO2_TREN['DEFAULT_INT']
            
    # 3. Calcular emisiones totales: Distancia * Pax * factor (en gramos)
    emision_g = distancia_km * n_pasajeros * factor
    return emision_g / 1000  # g → kg


# =============================================================================
# PASO 4: GENERAR TABLA COMPARATIVA AVIÓN VS TREN
# =============================================================================

def generar_comparativa_modal(
    df_vuelos: pd.DataFrame,
    load_factor: float = 0.84,
) -> pd.DataFrame:
    substituibles = df_vuelos[df_vuelos['es_substituible']].copy()
    if substituibles.empty:
        return pd.DataFrame()

    comparativa = []
    for idx, vuelo in substituibles.iterrows():
        distancia = vuelo['distancia_km']
        origen = vuelo['ADEP']
        asientos = vuelo.get('size_seats_avg', 180)
        n_pax = int(asientos * load_factor)

        t_avion = calcular_tiempo_d2d(distancia, origen, es_avion=True)
        t_tren = calcular_tiempo_d2d(distancia, origen, es_avion=False)

        co2_avion = vuelo.get('co2_kg_vuelo', 0)
        # LLAMADA ACTUALIZADA PASANDO EL ORIGEN (ADEP)
        co2_tren = calcular_emision_tren(distancia, origen, n_pax)

        comparativa.append({
            'ARCID': vuelo['ARCID'],
            'ADEP': origen,
            'distancia_km': round(distancia, 1),
            'n_pasajeros': n_pax,
            'tiempo_d2d_avion_min': round(t_avion, 1),
            'tiempo_d2d_tren_min': round(t_tren, 1),
            'ahorro_tiempo_min': round(t_avion - t_tren, 1),
            'co2_avion_kg': round(co2_avion, 1),
            'co2_tren_kg': round(co2_tren, 1),
            'ahorro_co2_kg': round(co2_avion - co2_tren, 1),
        })

    return pd.DataFrame(comparativa)


# =============================================================================
# PASO 5: RE-SIMULAR GDP SIN VUELOS SUBSTITUIBLES
# =============================================================================

def simular_sin_vuelos_cortos(
    df_vuelos_original: pd.DataFrame,
    params: dict,
    verbose: bool = True,
) -> dict:
    df_con_marca = identificar_vuelos_substituibles(df_vuelos_original, verbose=verbose)
    df_reducido = df_con_marca[~df_con_marca['es_substituible']].copy()

    n_eliminados = df_con_marca['es_substituible'].sum()
    pct_reduccion = (n_eliminados / len(df_con_marca)) * 100

    if verbose:
        print(f"      Demanda reducida:        {len(df_reducido)} vuelos")
        print(f"      Reducción:               {n_eliminados} vuelos ({pct_reduccion:.1f}%)")
        print(f"\n   🔄 Re-simulando GDP con demanda reducida...")

    resultados_reducido = gdp.ejecutar_nucleo_gdp(df_reducido, params, run_ghp=False)

    return {
        'resultados_gdp': resultados_reducido,
        'df_reducido': df_reducido,
        'n_vuelos_eliminados': n_eliminados,
        'pct_reduccion_demanda': pct_reduccion,
    }


# =============================================================================
# PASO 6: COMPARATIVA FINAL INTERMODAL
# =============================================================================

def generar_comparativa_intermodal(
    resultados_base: dict,
    resultados_reducido: dict,
    df_vuelos_original: pd.DataFrame,
    verbose: bool = True,
) -> pd.DataFrame:
    df_base = resultados_base['vuelos_asignados']
    kpis_base = calcular_kpis_economicos(df_base)
    h_noreg_base = resultados_base['h_noreg']

    df_reducido = resultados_reducido['resultados_gdp']['vuelos_asignados']
    kpis_reducido = calcular_kpis_economicos(df_reducido)
    h_noreg_reducido = resultados_reducido['resultados_gdp']['h_noreg']

    df_substituibles = df_vuelos_original[
        identificar_vuelos_substituibles(df_vuelos_original, verbose=False)['es_substituible']
    ]
    co2_vuelos_eliminados = df_substituibles['co2_kg_vuelo'].sum()

    # LLAMADA ACTUALIZADA PASANDO row['ADEP'] AL CALCULADOR
    co2_tren_total = sum(
        calcular_emision_tren(
            row['distancia_km'],
            row['ADEP'],
            int(row.get('size_seats_avg', 180) * 0.84)
        )
        for _, row in df_substituibles.iterrows()
    )

    ahorro_co2_intermodal = co2_vuelos_eliminados - co2_tren_total

    comparativa = pd.DataFrame({
        'Métrica': [
            'Demanda total (vuelos)',
            'Retraso total GDP (min)',
            'HNoReg — Cola disuelta (min UTC)',
            'Duración impacto (min)',
            'Emisiones CO₂ retraso (kg)',
            'Emisiones CO₂ vuelos eliminados (kg)',
            'Emisiones CO₂ tren alternativo (kg)',
            'Ahorro CO₂ intermodal (kg)',
            'Coste total retraso (EUR)',
        ],
        'Escenario Base (Todos vuelos)': [
            len(df_base),
            round(df_base['total_delay'].sum(), 1),
            h_noreg_base,
            h_noreg_base - resultados_base['params']['H_START'],
            round(kpis_base['co2_aire_delay'] + kpis_base['co2_tierra_delay'], 1),
            'N/A',
            'N/A',
            'N/A',
            int(kpis_base['cost_gdp']),
        ],
        'Escenario Intermodal (Sin cortos)': [
            len(df_reducido),
            round(df_reducido['total_delay'].sum(), 1),
            h_noreg_reducido,
            h_noreg_reducido - resultados_reducido['resultados_gdp']['params']['H_START'],
            round(kpis_reducido['co2_aire_delay'] + kpis_reducido['co2_tierra_delay'], 1),
            round(co2_vuelos_eliminados, 1),
            round(co2_tren_total, 1),
            round(ahorro_co2_intermodal, 1),
            int(kpis_reducido['cost_gdp']),
        ],
        'Delta (Mejora)': [
            -(len(df_base) - len(df_reducido)),
            round(df_base['total_delay'].sum() - df_reducido['total_delay'].sum(), 1),
            -(h_noreg_base - h_noreg_reducido),
            -((h_noreg_base - resultados_base['params']['H_START']) - 
              (h_noreg_reducido - resultados_reducido['resultados_gdp']['params']['H_START'])),
            round((kpis_base['co2_aire_delay'] + kpis_base['co2_tierra_delay']) - 
                  (kpis_reducido['co2_aire_delay'] + kpis_reducido['co2_tierra_delay']), 1),
            'N/A',
            'N/A',
            round(ahorro_co2_intermodal, 1),
            int(kpis_base['cost_gdp'] - kpis_reducido['cost_gdp']),
        ],
    })

    if verbose:
        print("\n   📊 COMPARATIVA INTERMODAL:")
        print(comparativa.to_string(index=False))

    return comparativa


# =============================================================================
# ORQUESTADOR WP4
# =============================================================================

def ejecutar_analisis_intermodal(
    df_vuelos: pd.DataFrame,
    resultados_base: dict,
    params: dict,
    base_dir: str,
) -> dict:
    print("\n" + "=" * 60)
    print("🚄 WP4: ANÁLISIS DE INTERMODALIDAD (TREN vs AVIÓN)")
    print("=" * 60)

    df_con_marca = identificar_vuelos_substituibles(df_vuelos, verbose=True)

    print("\n   📋 Generando comparativa modal (avión vs tren)...")
    df_modal = generar_comparativa_modal(df_con_marca)

    path_modal = os.path.join(base_dir, 'data/processed/wp4_comparativa_modal.csv')
    os.makedirs(os.path.dirname(path_modal), exist_ok=True)
    df_modal.to_csv(path_modal, index=False)
    print(f"      ✅ Guardado: data/processed/wp4_comparativa_modal.csv")

    resultados_reducido = simular_sin_vuelos_cortos(df_vuelos, params, verbose=True)

    df_comparativa = generar_comparativa_intermodal(
        resultados_base,
        resultados_reducido,
        df_vuelos,
        verbose=True
    )

    path_comparativa = os.path.join(base_dir, 'data/processed/wp4_comparativa_intermodal.csv')
    df_comparativa.to_csv(path_comparativa, index=False)
    print(f"\n   ✅ Guardado: data/processed/wp4_comparativa_intermodal.csv")

    return {
        'df_modal': df_modal,
        'df_comparativa': df_comparativa,
        'resultados_reducido': resultados_reducido,
        'n_vuelos_eliminados': resultados_reducido['n_vuelos_eliminados'],
    }


if __name__ == '__main__':
    import lib_data_prep as prep

    print("🛠️  MODO DEBUG: lib_intermodal.py")

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota = os.path.join(base, 'data/raw/fleet_cat_seat.csv')

    params = CFG.to_params_dict()
    df_vuelos = prep.preparar_vuelos(p_vuelos, p_flota)

    resultados_base = gdp.ejecutar_nucleo_gdp(df_vuelos, params)

    ejecutar_analisis_intermodal(df_vuelos, resultados_base, params, base)