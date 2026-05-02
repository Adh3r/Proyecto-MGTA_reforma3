# =============================================================================
# src/lib_intermodal.py
# WP4: Análisis de Intermodalidad — Sustitución de vuelos cortos por tren
# Integración final con costes no lineales de Cook & Tanner (GHP)
# =============================================================================

import os
import pandas as pd

from config import CFG
import lib_gdp_core as gdp
from lib_ghp_solver import ejecutar_ghp_completo
from lib_metrics import evaluar_escenario  # <-- Traemos el motor unificado

# --- CONSTANTES ---
DISTANCIA_MAX_INTERMODAL_KM = 500
VELOCIDAD_HSR_KMH = 200
TIEMPO_ACCESO_AEROPUERTO_MIN = 90
TIEMPO_EGRESO_AEROPUERTO_MIN = 60
TIEMPO_ACCESO_ESTACION_MIN = 40
TIEMPO_EGRESO_ESTACION_MIN = 20
VELOCIDAD_CRUCERO_KT = 440
KT_TO_KMH = 1.852
LOAD_FACTOR_POR_DEFECTO = 0.837
ASIENTOS_POR_DEFECTO = 180

DESTINOS_HSR_DESDE_LEBL = {
    'LEMD': {'ciudad': 'Madrid',    'tiempo_tren_h': 3.1}, # Ajustado a tiempos reales
    'LEVC': {'ciudad': 'Valencia',  'tiempo_tren_h': 3.0},
    'LEZG': {'ciudad': 'Zaragoza',  'tiempo_tren_h': 1.5},
    'LFBO': {'ciudad': 'Toulouse',  'tiempo_tren_h': 4.0},
    'LEAL': {'ciudad': 'Alicante',  'tiempo_tren_h': 5.2},
    'LFML': {'ciudad': 'Marsella',  'tiempo_tren_h': 4.8},
    'LFLL': {'ciudad': 'Lyon',      'tiempo_tren_h': 5.0},
}

FACTORES_CO2_TREN_KG_PAX = {
    'LEMD': 19.0, 'LEVC': 10.7, 'LEAL': 15.5, 'LEZG': 8.3,
    'LFML': 7.3,  'LFBO': 6.4,  'LFLL': 7.9,
}

def identificar_vuelos_substituibles(df_vuelos: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    df = df_vuelos.copy()
    df['es_substituible'] = (
        (df['distancia_km'] <= DISTANCIA_MAX_INTERMODAL_KM) &
        (df['ADEP'].isin(DESTINOS_HSR_DESDE_LEBL.keys())) &
        (df['ADES'] == 'LEBL')
    )
    if verbose:
        n_sub = df['es_substituible'].sum()
        pct = (n_sub / len(df)) * 100 if len(df) > 0 else 0
        print(f"\n 🚄 ANÁLISIS INTERMODAL: {n_sub} vuelos detectados ({pct:.1f}%)")
    return df

def calcular_tiempo_d2d(distancia_km: float, origen_icao: str, es_avion: bool = True) -> float:
    if es_avion:
        tiempo_vuelo_h = distancia_km / (VELOCIDAD_CRUCERO_KT * KT_TO_KMH)
        return TIEMPO_ACCESO_AEROPUERTO_MIN + (tiempo_vuelo_h * 60) + TIEMPO_EGRESO_AEROPUERTO_MIN
    else:
        tiempo_tren_h = DESTINOS_HSR_DESDE_LEBL.get(origen_icao, {}).get('tiempo_tren_h', distancia_km / VELOCIDAD_HSR_KMH)
        return TIEMPO_ACCESO_ESTACION_MIN + (tiempo_tren_h * 60) + TIEMPO_EGRESO_ESTACION_MIN

def calcular_emision_tren(distancia_km: float, origen_icao: str, n_pasajeros: int) -> float:
    factor_kg_pax = FACTORES_CO2_TREN_KG_PAX.get(origen_icao)
    if factor_kg_pax is not None:
        return factor_kg_pax * n_pasajeros
    else:
        factor_g_pax_km = 15.0 if origen_icao.startswith('LE') else 20.0
        return (distancia_km * n_pasajeros * factor_g_pax_km) / 1000

def generar_comparativa_modal(df_vuelos_regulados: pd.DataFrame) -> pd.DataFrame:
    substituibles = df_vuelos_regulados[df_vuelos_regulados['es_substituible']].copy()
    if substituibles.empty: return pd.DataFrame()

    comparativa = []
    for _, vuelo in substituibles.iterrows():
        distancia = vuelo['distancia_km']
        origen = vuelo['ADEP']
        n_pax = int(vuelo.get('size_seats_avg', ASIENTOS_POR_DEFECTO) * LOAD_FACTOR_POR_DEFECTO)
        retraso_min = vuelo.get('total_delay', 0)

        t_avion_nom = calcular_tiempo_d2d(distancia, origen, es_avion=True)
        t_tren = calcular_tiempo_d2d(distancia, origen, es_avion=False)
        co2_avion = vuelo.get('co2_kg_vuelo', 0)
        co2_tren = calcular_emision_tren(distancia, origen, n_pax)

        comparativa.append({
            'ARCID': vuelo.get('ARCID', 'N/A'),
            'ADEP': origen,
            'distancia_km': round(distancia, 1),
            'retraso_ATFM_min': round(retraso_min, 1),
            'tiempo_d2d_avion_NOMINAL_min': round(t_avion_nom, 1), 
            'tiempo_d2d_avion_CON_RETRASO_min': round(t_avion_nom + retraso_min, 1),
            'tiempo_d2d_tren_min': round(t_tren, 1),
            'ahorro_tiempo_TREN_min': round((t_avion_nom + retraso_min) - t_tren, 1),
            'co2_avion_kg': round(co2_avion, 1), 
            'co2_tren_kg': round(co2_tren, 1),   
            'ahorro_co2_neto_kg': round(co2_avion - co2_tren, 1),
        })
    return pd.DataFrame(comparativa)

def simular_sin_vuelos_cortos(df_vuelos_original: pd.DataFrame, params: dict, verbose: bool = True) -> dict:
    df_con_marca = identificar_vuelos_substituibles(df_vuelos_original, verbose=verbose)
    df_reducido = df_con_marca[~df_con_marca['es_substituible']].copy()

    # 1. Re-ejecutar GDP (RBS) para obtener nuevos slots
    resultados_gdp_red = gdp.ejecutar_nucleo_gdp(df_reducido, params, run_ghp=False)
    
    # 2. Re-ejecutar GHP completo (Cook & Tanner) sobre la red descongestionada
    if verbose: print(" 🔄 Re-optimizando GHP (Cook & Tanner) para escenario intermodal...")
    
    resultados_ghp_red = ejecutar_ghp_completo(
        df_vuelos_etiquetados=resultados_gdp_red['vuelos_asignados'],
        slots_disponibles=list(resultados_gdp_red['slots']['slot_start_min']),
        params=params,
        verbose=False
    )

    return {
        'resultados_gdp': resultados_gdp_red,
        'resultados_ghp': resultados_ghp_red,
        'df_reducido': df_reducido,
        'n_vuelos_eliminados': df_con_marca['es_substituible'].sum()
    }

def generar_comparativa_intermodal(
    resultados_base_gdp: dict,
    resultados_base_ghp: dict,
    resultados_reducido: dict,
    df_vuelos_original: pd.DataFrame,
    verbose: bool = True,
) -> pd.DataFrame:
    
    # 1. Recuperamos el H_START para el motor de métricas
    h_start_min = resultados_reducido['resultados_gdp']['params'].get('H_START', 0)
    h_noreg_red = resultados_reducido['resultados_gdp']['h_noreg']

    # 2. Extraemos los DataFrames re-simulados (Intermodales)
    df_red_GDP  = resultados_reducido['resultados_ghp']['task1_validation']
    df_red_co2  = resultados_reducido['resultados_ghp']['task2_emissions']
    df_red_cost = resultados_reducido['resultados_ghp']['task3_cost'] 
    
    # 3. Calculamos KPIs con el MISMO MOTOR que el WP3 (lib_metrics)
    kpis_red_GDP  = evaluar_escenario(df_red_GDP, 'Intermodal_GDP', h_start_min)
    kpis_red_co2  = evaluar_escenario(df_red_co2, 'Intermodal_CO2', h_start_min)
    kpis_red_cost = evaluar_escenario(df_red_cost, 'Intermodal_Cost', h_start_min)

    # 4. CÁLCULO AHORRO DIRECTO TREN (CO2)
    df_sub = identificar_vuelos_substituibles(df_vuelos_original, verbose=False)
    df_sub = df_sub[df_sub['es_substituible']]
    co2_vuelos_del = df_sub['co2_kg_vuelo'].sum()
    co2_tren_total = sum(calcular_emision_tren(r['distancia_km'], r['ADEP'], int(r.get('size_seats_avg', ASIENTOS_POR_DEFECTO) * LOAD_FACTOR_POR_DEFECTO)) for _, r in df_sub.iterrows())
    ahorro_co2_tren_directo = co2_vuelos_del - co2_tren_total

    # 5. CÁLCULO CO2 TOTAL DEL SISTEMA (Igualando la base del WP3)
    # Cogemos las emisiones base nominales desde los vuelos asignados para que cuadre exacto con WP3
    co2_nominal_base = resultados_base_gdp['vuelos_asignados']['co2_kg_vuelo'].sum()
    co2_nominal_reducido = co2_nominal_base - co2_vuelos_del

    # Crear DataFrame Comparativo usando las claves del nuevo diccionario de KPIs
    comparativa = pd.DataFrame({
        'Métrica': [
            'Demanda total (vuelos)',
            'Retraso total GDP (min)',
            'HNoReg — Cola disuelta (min UTC)',
            'Duración impacto (min)',
            'Emisiones CO₂ retraso (kg)',
            'Emisiones CO₂ TOTAL Sistema (kg)', 
            'Coste total retraso (EUR)',
            'Ahorro neto CO₂ directo por Tren (kg)',
        ],
        'Intermodal (GDP)': [
            len(df_red_GDP),
            round(kpis_red_GDP['Retraso_Total_min'], 1),
            h_noreg_red,
            h_noreg_red - h_start_min,
            round(kpis_red_GDP['CO2_Total_Retraso_kg'], 1),  
            round(co2_nominal_reducido + kpis_red_GDP['CO2_Total_Retraso_kg'] + co2_tren_total, 1),
            int(kpis_red_GDP['Coste_Cook_EUR']),         
            round(ahorro_co2_tren_directo, 1),
        ],
        'Intermodal (Opt. Costes)': [
            len(df_red_cost),
            round(kpis_red_cost['Retraso_Total_min'], 1),
            h_noreg_red,
            h_noreg_red - h_start_min,
            round(kpis_red_cost['CO2_Total_Retraso_kg'], 1),  
            round(co2_nominal_reducido + kpis_red_cost['CO2_Total_Retraso_kg'] + co2_tren_total, 1),
            int(kpis_red_cost['Coste_Cook_EUR']),         
            round(ahorro_co2_tren_directo, 1),
        ],
        'Intermodal (Opt. Emisiones)': [
            len(df_red_co2),
            round(kpis_red_co2['Retraso_Total_min'], 1),
            h_noreg_red,
            h_noreg_red - h_start_min,
            round(kpis_red_co2['CO2_Total_Retraso_kg'], 1),  
            round(co2_nominal_reducido + kpis_red_co2['CO2_Total_Retraso_kg'] + co2_tren_total, 1),
            int(kpis_red_co2['Coste_Cook_EUR']),         
            round(ahorro_co2_tren_directo, 1),
        ],
    })

    if verbose:
        print("\n 📊 COMPARATIVA INTERMODAL Y GHP (TRES ESCENARIOS):")
        print(f"{'Métrica':>38} | {'Intermodal (GDP)':>18} | {'Intermodal (Opt. Costes)':>25} | {'Intermodal (Opt. Emis.)':>25}")
        print("-" * 115)
        for _, row in comparativa.iterrows():
            print(f"{row['Métrica']:>38} | {str(row['Intermodal (GDP)']):>18} | {str(row['Intermodal (Opt. Costes)']):>25} | {str(row['Intermodal (Opt. Emisiones)']):>25}")

    return comparativa

def ejecutar_analisis_intermodal(df_vuelos: pd.DataFrame, resultados_base: dict, resultados_base_ghp: dict, params: dict, base_dir: str) -> dict:
    print("\n" + "=" * 80)
    print("🚄 WP4: ANÁLISIS DE INTERMODALIDAD — IMPACTO EN RED (COOK & TANNER)")
    print("=" * 80)

    # 1. Comparativa modal individual (Avión vs Tren con retrasos)
    df_regulado_base = resultados_base['vuelos_asignados'].copy()
    df_con_marca = identificar_vuelos_substituibles(df_regulado_base, verbose=True)
    df_modal = generar_comparativa_modal(df_con_marca)

    # 2. Re-simulación de la red sin vuelos cortos
    resultados_red = simular_sin_vuelos_cortos(df_vuelos, params, verbose=True)

    # 3. Comparativa de KPIs globales usando GHP
    df_comp = generar_comparativa_intermodal(
        resultados_base,
        resultados_base_ghp,
        resultados_red,
        df_vuelos,
        verbose=True
    )

    # Guardar resultados
    os.makedirs(os.path.join(base_dir, 'data/processed'), exist_ok=True)
    df_modal.to_csv(os.path.join(base_dir, 'data/processed/wp4_comparativa_modal.csv'), index=False)
    df_comp.to_csv(os.path.join(base_dir, 'data/processed/wp4_comparativa_intermodal.csv'), index=False)

    return {
        'df_modal': df_modal,
        'df_comparativa': df_comp,
        'resultados_reducido': resultados_red
    }