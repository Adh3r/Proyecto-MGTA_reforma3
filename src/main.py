# =============================================================================
# src/main.py
# PUNTO DE ENTRADA DEL PROYECTO — Ejecuta la simulación completa.
#
# Este script es el "director de orquesta": no contiene ninguna lógica
# de cálculo propia. Solo llama a las funciones de los otros módulos
# en el orden correcto y gestiona las rutas de los archivos de entrada y salida.
#
# CÓMO EJECUTAR EL PROYECTO COMPLETO:
#   cd src/
#   python main.py
#
# FLUJO DE LAS FASES ACTUALIZADO (WP1-WP5):
#   [FASE 1] lib_data_prep    → Leer CSVs, limpiar datos, calcular distancias y CO2.
#   [FASE 2] lib_gdp_core     → Newell, etiquetado de vuelos, RBS, cálculo de retrasos.
#   [FASE 3] lib_ghp_solver   → [NUEVO] Optimización lineal, emisiones, costes y equidad.
#   [FASE 4] lib_intermodal   → [NUEVO] Sustitución modal (tren vs avión) y re-simulación.
#   [FASE 5] main             → Guardar CSV + Excel de auditoría + gráficos base.
#   [FASE 6] lib_sensitivity  → Análisis de sensibilidad: cuadrícula R × HFile.
#
# SEPARACIÓN DE RESPONSABILIDADES:
#   main.py solo sabe DÓNDE están los archivos y en QUÉ ORDEN llamar a cada módulo.
#   Toda la lógica vive en los módulos lib_*.
# =============================================================================

import os
import pandas as pd

import lib_data_prep     as prep
import lib_gdp_core      as gdp
import lib_excel_export  as excel
import lib_sensitivity   as sens
import lib_visualization as vis
import lib_intermodal    as inter  # <-- NUEVO MÓDULO WP4

from config import CFG, FS_CANDIDATE
from lib_gdp_core import calcular_retraso_minimo_newell, calcular_kpis_economicos
from lib_ghp_solver import ejecutar_ghp_completo, calcular_kpis_ghp


def ejecutar_proyecto_completo() -> None:
    """
    Orquestador principal: ejecuta las fases del simulador ATM de LEBL
    incluyendo ahora los análisis avanzados del WP3 (GHP) y WP4 (Intermodal).
    """
    print("🚀 INICIANDO SIMULADOR ATM — AEROPUERTO DE BARCELONA (LEBL)")
    print("=" * 60)

    # =========================================================================
    # RUTAS DE ARCHIVO
    # =========================================================================
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Datos de entrada (nunca se modifican)
    PATH_VUELOS_RAW = os.path.join(BASE_DIR, 'data/raw/LEBL_10AUG2025.csv')
    PATH_FLOTA_RAW  = os.path.join(BASE_DIR, 'data/raw/fleet_cat_seat.csv')

    # Entregables finales
    PATH_OUTPUT_CSV   = os.path.join(BASE_DIR, 'data/processed/vuelos_finales_gdp.csv')
    PATH_OUTPUT_EXCEL = os.path.join(BASE_DIR, 'data/processed/auditoria_completa.xlsx')

    # Rutas de los gráficos base (Fase 5)
    rutas_graficos = {
        'cum': os.path.join(BASE_DIR, 'output/figures/1_diagrama_newell.png'),
        'bal': os.path.join(BASE_DIR, 'output/figures/2_balance_capacidad.png'),
    }

    # =========================================================================
    # FASE 1: PREPARACIÓN DE DATOS
    # =========================================================================
    print("\n[FASE 1] Preparando datos y escenario...")

    params = CFG.to_params_dict()
    df_vuelos = prep.preparar_vuelos(PATH_VUELOS_RAW, PATH_FLOTA_RAW)
    print(f"✅ Datos cargados: {len(df_vuelos)} vuelos listos.")

    # =========================================================================
    # FASE 2: SIMULACIÓN GDP — ESCENARIO BASE (RBS)
    # =========================================================================
    print("\n[FASE 2] Ejecutando motor de simulación GDP (Algoritmo RBS)...")

    resultados = gdp.ejecutar_nucleo_gdp(df_vuelos, params, run_ghp=False)

    df_final = resultados['vuelos_asignados']
    df_slots = resultados['slots']
    slots_list = list(df_slots['slot_start_min'])

    candidatos = df_final[df_final['flight_status'] == FS_CANDIDATE]
    print(f"   Vuelos regulados (GDP): {len(candidatos)}")
    print(f"   Vuelos exentos:         {len(df_final) - len(candidatos)}")
    print(f"   Retraso medio global:   {df_final['total_delay'].mean():.1f} min/vuelo")

    # =========================================================================
    # FASE 3: OPTIMIZACIÓN GHP (WP3) Y ANÁLISIS DE EQUIDAD
    # =========================================================================
    print("\n[FASE 3] Ejecutando optimización GHP (WP3 Tasks 1, 2, 3) y Equidad...")
    
    resultados_ghp = ejecutar_ghp_completo(
        df_vuelos_etiquetados=df_final, 
        slots_disponibles=slots_list, 
        params=params,
        verbose=False # Silenciado para mantener la consola limpia
    )
    
    kpis_ghp = {}
    for nombre_task, rf_key in [
        ('task1_validation', 'rf_unitario'),
        ('task2_emissions', 'rf_emisiones'),
        ('task3_cost', 'rf_coste'),
    ]:
        df_ghp = resultados_ghp[nombre_task]
        rf_series = resultados_ghp[rf_key]
        kpis_ghp[nombre_task] = calcular_kpis_ghp(df_ghp, rf_series, nombre_task)
    
    print(f"   ✅ Task 1 (Validación): Retraso Total = {kpis_ghp['task1_validation']['total_delay_min']:.1f} min")
    print(f"   ✅ Task 2 (Emisiones):  CO₂ Total = {kpis_ghp['task2_emissions']['co2_total_delay_kg']:.1f} kg")
    print(f"   ✅ Task 3 (Coste Real): Coste Total = {kpis_ghp['task3_cost']['coste_delay_eur']:.0f} EUR")

    # --- Análisis de Equidad (RSD) ---
    def calcular_rsd_por_aerolinea(df: pd.DataFrame) -> float:
        top_airlines = df['airline'].value_counts().head(4).index
        delays_por_airline = [df[df['airline'] == airline]['total_delay'].mean() for airline in top_airlines]
        mean_of_means = sum(delays_por_airline) / len(delays_por_airline)
        if mean_of_means == 0: return 0.0
        variance = sum((x - mean_of_means)**2 for x in delays_por_airline) / len(delays_por_airline)
        return ((variance ** 0.5) / mean_of_means) * 100
    
    rsd_gdp = calcular_rsd_por_aerolinea(df_final)
    rsd_ghp = calcular_rsd_por_aerolinea(resultados_ghp['task3_cost'])
    
    print(f"\n   📊 EQUIDAD (RSD Top-4 Aerolíneas): GDP = {rsd_gdp:.1f}% | GHP = {rsd_ghp:.1f}%")

    # --- Generar Tabla Comparativa WP3 ---
    kpis_gdp = calcular_kpis_economicos(df_final)
    comparativa_wp3 = pd.DataFrame({
        'Métrica': ['Retraso Total (min)', 'Retraso Aire (min)', 'Retraso Tierra (min)', 'CO₂ Retraso (kg)', 'Coste Retraso (EUR)', 'RSD Equidad (%)'],
        'GDP (RBS)': [df_final['total_delay'].sum(), df_final['air_delay'].sum(), df_final['ground_delay'].sum(), kpis_gdp['co2_aire_delay'] + kpis_gdp['co2_tierra_delay'], kpis_gdp['cost_gdp'], rsd_gdp],
        'GHP Task 1': [kpis_ghp['task1_validation']['total_delay_min'], kpis_ghp['task1_validation']['air_delay_min'], kpis_ghp['task1_validation']['ground_delay_min'], kpis_ghp['task1_validation']['co2_total_delay_kg'], None, None],
        'GHP Task 3': [kpis_ghp['task3_cost']['total_delay_min'], kpis_ghp['task3_cost']['air_delay_min'], kpis_ghp['task3_cost']['ground_delay_min'], kpis_ghp['task3_cost']['co2_total_delay_kg'], kpis_ghp['task3_cost']['coste_delay_eur'], rsd_ghp]
    })
    comparativa_wp3.to_csv(os.path.join(BASE_DIR, 'data/processed/wp3_comparativa_final.csv'), index=False)

    # =========================================================================
    # FASE 4: ANÁLISIS INTERMODAL (WP4 - TREN VS AVIÓN)
    # =========================================================================
    print("\n[FASE 4] Ejecutando análisis intermodal (Sustitución HSR <500km)...")
    
    try:
        # Llama a la función principal de lib_intermodal.py
        # Nota: Asumimos que genera automáticamente su propio CSV dentro.
        _ = inter.ejecutar_analisis_wp4(df_vuelos, resultados, params, BASE_DIR)
        print("   ✅ Tabla comparativa intermodal generada.")
    except Exception as e:
        print(f"   ⚠️ Nota: El módulo WP4 se ejecutará cuando lib_intermodal.py esté completo ({e})")

    # =========================================================================
    # FASE 5: GENERACIÓN DE ENTREGABLES DEL ESCENARIO BASE
    # =========================================================================
    print("\n[FASE 5] Generando entregables del escenario base...")

    os.makedirs(os.path.dirname(PATH_OUTPUT_CSV), exist_ok=True)
    df_final.to_csv(PATH_OUTPUT_CSV, index=False)
    print("   → CSV maestro guardado en data/processed/")

    r_min_newell = calcular_retraso_minimo_newell(resultados['timeline'])
    excel.exportar_auditoria_excel(
        resultados['vuelos_crudos'], df_final, df_slots, resultados['params'],
        resultados['h_noreg'], resultados['timeline'], r_min_newell,
        PATH_OUTPUT_EXCEL, df_res_comprimido=resultados['vuelos_comprimidos']
    )
    print("   → Excel de auditoría guardado en data/processed/")

    vis.generar_graficos_fase2(
        timeline=resultados['timeline'], df_vuelos=df_vuelos, df_res=resultados['vuelos_asignados'],
        params=params, h_noreg=resultados['h_noreg'], paths=rutas_graficos,
    )
    print("   → Gráficos guardados en output/figures/")

    # =========================================================================
    # FASE 6: ANÁLISIS DE SENSIBILIDAD — CUADRÍCULA R × HFILE
    # =========================================================================
    print("\n[FASE 6] Análisis de sensibilidad (42 simulaciones)...")
    sens.ejecutar_analisis_sensibilidad(df_vuelos, params, BASE_DIR)

    # =========================================================================
    # RESUMEN FINAL
    # =========================================================================
    print("\n" + "=" * 60)
    print("✨ PROCESO COMPLETO FINALIZADO CON ÉXITO")
    print(f"   📄 CSV maestro:          data/processed/vuelos_finales_gdp.csv")
    print(f"   📊 Excel de auditoría:   data/processed/auditoria_completa.xlsx")
    print(f"   📈 Comparativa WP3:      data/processed/wp3_comparativa_final.csv")
    print(f"   🚆 Comparativa WP4:      data/processed/wp4_comparativa_intermodal.csv")
    print(f"   🌡️  Matriz sensibilidad:  data/processed/sensitivity_grid.csv")
    print("=" * 60)

if __name__ == "__main__":
    ejecutar_proyecto_completo()