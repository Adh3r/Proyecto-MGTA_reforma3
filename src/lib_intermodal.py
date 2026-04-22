# =============================================================================
# src/lib_intermodal.py
# WP4: Análisis de Intermodalidad — Sustitución de vuelos cortos por tren
# =============================================================================

import os
import pandas as pd

from config import CFG, FS_CANDIDATE
import lib_gdp_core as gdp
from lib_gdp_core import calcular_kpis_economicos
from lib_ghp_solver import ejecutar_ghp_completo, calcular_kpis_ghp

# =============================================================================
# CONSTANTES WP4 (Extraídas para evitar "Magic Numbers")
# =============================================================================

# Parámetros de Intermodalidad
DISTANCIA_MAX_INTERMODAL_KM = 500
VELOCIDAD_HSR_KMH = 200

# Tiempos de Acceso/Egreso (D2D)
TIEMPO_ACCESO_AEROPUERTO_MIN = 90
TIEMPO_EGRESO_AEROPUERTO_MIN = TIEMPO_ACCESO_AEROPUERTO_MIN / 2  # 45 min
TIEMPO_ACCESO_ESTACION_MIN = 30
TIEMPO_EGRESO_ESTACION_MIN = 15

# Parámetros Aeronáuticos
VELOCIDAD_CRUCERO_KT = 440
KT_TO_KMH = 1.852
LOAD_FACTOR_POR_DEFECTO = 0.837
ASIENTOS_POR_DEFECTO = 180

# Destinos con conexión HSR directa desde Barcelona (LEBL)
DESTINOS_HSR_DESDE_LEBL = {
    'LEMD': {'ciudad': 'Madrid',    'tiempo_tren_h': 3.5},
    'LEVC': {'ciudad': 'Valencia',  'tiempo_tren_h': 3.0},
    'LEZG': {'ciudad': 'Zaragoza',  'tiempo_tren_h': 1.5},
    'LFBO': {'ciudad': 'Toulouse',  'tiempo_tren_h': 4.0},
    'LEAL': {'ciudad': 'Alicante',  'tiempo_tren_h': 5.25},
    'LFML': {'ciudad': 'Marsella',  'tiempo_tren_h': 7.0},
    'LFLL': {'ciudad': 'Lyon',      'tiempo_tren_h': 5.0},
}

# MATRIZ DE EMISIONES TREN kg CO2 / PASAJERO / RUTA COMPLETA 
# Datos extraídos directamente de EcoPassenger (2026)
FACTORES_CO2_TREN_KG_PAX = {
    'LEMD': 19.0,  # Madrid 
    'LEVC': 10.7,  # Valencia 
    'LEAL': 15.5,  # Alicante 
    'LEZG': 8.3,   # Zaragoza 
    'LFML': 7.3,   # Marsella 
    'LFBO': 6.4,   # Toulouse 
    'LFLL': 7.9,   # Lyon 
}

# =============================================================================
# PASO 1: IDENTIFICAR RUTAS SUBSTITUIBLES
# =============================================================================

def identificar_vuelos_substituibles(df_vuelos: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
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

def calcular_tiempo_d2d(distancia_km: float, origen_icao: str, es_avion: bool = True) -> float:
    if es_avion:
        tiempo_vuelo_h = distancia_km / (VELOCIDAD_CRUCERO_KT * KT_TO_KMH)
        return TIEMPO_ACCESO_AEROPUERTO_MIN + (tiempo_vuelo_h * 60) + TIEMPO_EGRESO_AEROPUERTO_MIN
    else:
        if origen_icao in DESTINOS_HSR_DESDE_LEBL:
            tiempo_tren_h = DESTINOS_HSR_DESDE_LEBL[origen_icao]['tiempo_tren_h']
        else:
            tiempo_tren_h = distancia_km / VELOCIDAD_HSR_KMH
        return TIEMPO_ACCESO_ESTACION_MIN + (tiempo_tren_h * 60) + TIEMPO_EGRESO_ESTACION_MIN

# =============================================================================
# PASO 3: CALCULAR EMISIONES AVIÓN VS TREN (ACTUALIZADO ECOPASSENGER)
# =============================================================================

def calcular_emision_tren(distancia_km: float, origen_icao: str, n_pasajeros: int) -> float:
    factor_kg_pax = FACTORES_CO2_TREN_KG_PAX.get(origen_icao)
    if factor_kg_pax is not None:
        return factor_kg_pax * n_pasajeros
    else:
        factor_g_pax_km = 15.0 if origen_icao.startswith('LE') else 20.0
        return (distancia_km * n_pasajeros * factor_g_pax_km) / 1000

# =============================================================================
# PASO 4: GENERAR TABLA COMPARATIVA MODAL
# =============================================================================

def generar_comparativa_modal(df_vuelos: pd.DataFrame) -> pd.DataFrame:
    substituibles = df_vuelos[df_vuelos['es_substituible']].copy()
    if substituibles.empty:
        return pd.DataFrame()

    comparativa = []
    for idx, vuelo in substituibles.iterrows():
        distancia = vuelo['distancia_km']
        origen = vuelo['ADEP']
        asientos = vuelo.get('size_seats_avg', ASIENTOS_POR_DEFECTO)
        n_pax = int(asientos * LOAD_FACTOR_POR_DEFECTO)

        t_avion = calcular_tiempo_d2d(distancia, origen, es_avion=True)
        t_tren = calcular_tiempo_d2d(distancia, origen, es_avion=False)

        co2_avion = vuelo.get('co2_kg_vuelo', 0)
        
        # LOG DE ADVERTENCIA PARA CONTROL DE ERRORES
        if co2_avion == 0:
            print(f"⚠️ AVISO: El vuelo {vuelo.get('ARCID', 'Desconocido')} no tiene datos previos de emisiones.")

        co2_tren = calcular_emision_tren(distancia, origen, n_pax)

        comparativa.append({
            'ARCID': vuelo.get('ARCID', 'N/A'),
            'ADEP': origen,
            'distancia_km': round(distancia, 1),
            'n_pasajeros_reales': n_pax,
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

def simular_sin_vuelos_cortos(df_vuelos_original: pd.DataFrame, params: dict, verbose: bool = True) -> dict:
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
# PASO 6: COMPARATIVA FINAL INTERMODAL (CON PASAJEROS)
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
    
    # CÁLCULO DE PASAJEROS TRASLADADOS AL TREN
    pax_trasladados = sum(
        int(row.get('size_seats_avg', ASIENTOS_POR_DEFECTO) * LOAD_FACTOR_POR_DEFECTO) 
        for _, row in df_substituibles.iterrows()
    )

    co2_tren_total = sum(
        calcular_emision_tren(
            row['distancia_km'],
            row['ADEP'],
            int(row.get('size_seats_avg', ASIENTOS_POR_DEFECTO) * LOAD_FACTOR_POR_DEFECTO)
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
            'Pasajeros trasladados a tren (Pax)',
            'Emisiones CO₂ tren alternativo (kg)',
            'Ahorro neto CO₂ intermodal (kg)',
            'Coste total retraso (EUR)',
        ],
        'Escenario Base': [
            len(df_base),
            round(df_base['total_delay'].sum(), 1),
            h_noreg_base,
            h_noreg_base - resultados_base['params']['H_START'],
            round(kpis_base['co2_aire_delay'] + kpis_base['co2_tierra_delay'], 1),
            'N/A',
            'N/A',
            'N/A',
            'N/A',
            int(kpis_base['cost_gdp']),
        ],
        'Escenario Intermodal': [
            len(df_reducido),
            round(df_reducido['total_delay'].sum(), 1),
            h_noreg_reducido,
            h_noreg_reducido - resultados_reducido['resultados_gdp']['params']['H_START'],
            round(kpis_reducido['co2_aire_delay'] + kpis_reducido['co2_tierra_delay'], 1),
            round(co2_vuelos_eliminados, 1),
            pax_trasladados,
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
            pax_trasladados,
            'N/A',
            round(ahorro_co2_intermodal, 1),
            int(kpis_base['cost_gdp'] - kpis_reducido['cost_gdp']),
        ],
    })

    if verbose:
        print("\n   📊 COMPARATIVA INTERMODAL (ACTUALIZADA):")
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


# =============================================================================
# MODO DEBUG / PRUEBA AISLADA
# =============================================================================
if __name__ == '__main__':
    import lib_data_prep as prep

    print("🛠️  MODO DEBUG: lib_intermodal.py")

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota = os.path.join(base, 'data/raw/fleet_cat_seat.csv')

    params = CFG.to_params_dict()
    df_vuelos = prep.preparar_vuelos(p_vuelos, p_flota)

    # Ejecutamos el GDP base para tener algo con lo que comparar
    resultados_base = gdp.ejecutar_nucleo_gdp(df_vuelos, params)

    # Ejecutamos el WP4
    ejecutar_analisis_intermodal(df_vuelos, resultados_base, params, base)