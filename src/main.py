# =============================================================================
# src/main.py
# PUNTO DE ENTRADA DEL PROYECTO — Ejecuta la simulación completa.
# =============================================================================

import os
import traceback
import pandas as pd
import time

import lib_data_prep     as prep
import lib_gdp_core      as gdp
import lib_excel_export  as excel
import lib_sensitivity   as sens
import lib_visualization as vis
import lib_intermodal    as inter 

from config import CFG, FS_CANDIDATE
from lib_gdp_core import calcular_retraso_minimo_newell, calcular_kpis_economicos
from lib_ghp_solver import ejecutar_ghp_completo, calcular_kpis_ghp

# =============================================================================
# FUNCIONES AUXILIARES DE MÉTRICAS (KPAs)
# =============================================================================

def calcular_rsd_por_aerolinea(df: pd.DataFrame) -> float:
    """KPA Equidad: Calcula la RSD de los retrasos medios para top 4 aerolíneas."""
    top_airlines = df['airline'].value_counts().head(4).index
    delays_por_airline = [df[df['airline'] == airline]['total_delay'].mean() for airline in top_airlines]
    
    mean_of_means = sum(delays_por_airline) / len(delays_por_airline)
    if mean_of_means == 0: 
        return 0.0
        
    variance = sum((x - mean_of_means)**2 for x in delays_por_airline) / len(delays_por_airline)
    return ((variance ** 0.5) / mean_of_means) * 100


# =============================================================================
# ORQUESTADOR PRINCIPAL
# =============================================================================

def ejecutar_proyecto_completo() -> None:

    # 1. Arrancamos el cronómetro
    start_time = time.time()
    print("\n" + "═" * 70)
    print("🚀 INICIANDO SIMULADOR ATM — AEROPUERTO DE BARCELONA (LEBL)")
    print("═" * 70)

    # Rutas
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    PATH_VUELOS_RAW = os.path.join(BASE_DIR, 'data/raw/LEBL_10AUG2025.csv')
    PATH_FLOTA_RAW  = os.path.join(BASE_DIR, 'data/raw/fleet_cat_seat.csv')
    PATH_OUTPUT_CSV   = os.path.join(BASE_DIR, 'data/processed/vuelos_finales_gdp.csv')
    PATH_OUTPUT_EXCEL = os.path.join(BASE_DIR, 'data/processed/auditoria_completa.xlsx')

    rutas_graficos = {
        'cum': os.path.join(BASE_DIR, 'output/figures/1_diagrama_newell.png'),
        'bal': os.path.join(BASE_DIR, 'output/figures/2_balance_capacidad.png'),
    }

    # -------------------------------------------------------------------------
    # WP1: PREPARACIÓN DE DATOS
    # -------------------------------------------------------------------------
    print("\n[WP1] Preparando datos y escenario...")
    params = CFG.to_params_dict()
    df_vuelos = prep.preparar_vuelos(PATH_VUELOS_RAW, PATH_FLOTA_RAW)
    print(f"   ✅ Datos cargados y depurados: {len(df_vuelos)} vuelos en la red.")

    # -------------------------------------------------------------------------
    # WP2: SIMULACIÓN GDP BASE
    # -------------------------------------------------------------------------
    print("\n" + "═" * 70)
    print("🛫 [WP2] EJECUTANDO MOTOR DE SIMULACIÓN GDP (Algoritmo RBS)")
    print("═" * 70)
    
    # IMPORTANTE: Desactivamos el print interno del GHP de validación para no manchar
    resultados = gdp.ejecutar_nucleo_gdp(df_vuelos, params, run_ghp=False)

    df_final = resultados['vuelos_asignados']
    df_slots = resultados['slots']
    slots_list = list(df_slots['slot_start_min'])
    candidatos = df_final[df_final['flight_status'] == FS_CANDIDATE]
    
    print(f"   • Vuelos regulados (GDP): {len(candidatos)}")
    print(f"   • Vuelos exentos:         {len(df_final) - len(candidatos)}")
    print(f"   • Retraso medio global:   {df_final['total_delay'].mean():.1f} min/vuelo")

    # -------------------------------------------------------------------------
    # WP2 (EXTRA): ANÁLISIS DE SENSIBILIDAD
    # -------------------------------------------------------------------------
    print("\n" + "═" * 70)
    print("🌡️  [WP2-B] ANÁLISIS DE SENSIBILIDAD (Radio vs H_File)")
    print("═" * 70)
    # Ejecutamos el análisis (asumimos que dentro de su código ya tiene prints)
    sens.ejecutar_analisis_sensibilidad(df_vuelos, params, BASE_DIR)
    print("   ✅ Matrices guardadas y Heatmaps generados.")

    # -------------------------------------------------------------------------
    # WP3: OPTIMIZACIÓN GHP Y ANÁLISIS DE EQUIDAD
    # -------------------------------------------------------------------------
    print("\n" + "═" * 70)
    print("🧠 [WP3] EJECUTANDO OPTIMIZACIÓN GHP Y EQUIDAD (RSD)")
    print("═" * 70)
    
    resultados_ghp = ejecutar_ghp_completo(
        df_vuelos_etiquetados=df_final, 
        slots_disponibles=slots_list, 
        params=params,
        verbose=False 
    )
    
    kpis_ghp = {}
    for nombre_task, rf_key in [
        ('task1_validation', 'rf_unitario'),
        ('task2_emissions', 'rf_emisiones'),
        ('task3_cost', 'rf_coste'),
    ]:
        kpis_ghp[nombre_task] = calcular_kpis_ghp(resultados_ghp[nombre_task], resultados_ghp[rf_key], nombre_task)
    
    # Análisis de Equidad
    rsd_gdp = calcular_rsd_por_aerolinea(df_final)
    rsd_ghp = calcular_rsd_por_aerolinea(resultados_ghp['task3_cost'])

    kpis_gdp = calcular_kpis_economicos(df_final)
    
    # Imprimimos resumen ejecutivo limpio en consola
    print("\n   📊 RESUMEN EJECUTIVO WP3:")
    print(f"      • Retraso Base (RBS):    {df_final['total_delay'].sum():.1f} min")
    print(f"      • Retraso Óptimo (Task1):{kpis_ghp['task1_validation']['total_delay_min']:.1f} min")
    print(f"      • Emisiones Ópt. (Task2):{kpis_ghp['task2_emissions']['co2_total_kg']:,.1f} kg CO2")
    print(f"      • Coste Ópt. (Task3):    {kpis_ghp['task3_cost']['coste_delay_eur']:,.0f} EUR")
    print(f"      • Equidad (RSD GDP):     {rsd_gdp:.1f}%")
    print(f"      • Equidad (RSD GHP T3):  {rsd_ghp:.1f}%")

    comparativa_wp3 = pd.DataFrame({
    'Métrica': ['Retraso Total (min)', 'Retraso Aire (min)', 'Retraso Tierra (min)', 'CO₂ Retraso (kg)', 'Coste Retraso (EUR)', 'RSD Equidad (%)'],
    'GDP (RBS)': [
        df_final['total_delay'].sum(), 
        df_final['air_delay'].sum(), 
        df_final['ground_delay'].sum(), 
        kpis_gdp['co2_aire_delay'] + kpis_gdp['co2_tierra_delay'], 
        kpis_gdp['cost_gdp'], 
        rsd_gdp
    ],
    'GHP Task 1': [
        kpis_ghp['task1_validation']['total_delay_min'], 
        kpis_ghp['task1_validation']['air_delay_min'], 
        kpis_ghp['task1_validation']['ground_delay_min'], 
        kpis_ghp['task1_validation']['co2_total_kg'],
        None, 
        None
    ],
    'GHP Task 3': [
        kpis_ghp['task3_cost']['total_delay_min'], 
        kpis_ghp['task3_cost']['air_delay_min'], 
        kpis_ghp['task3_cost']['ground_delay_min'], 
        kpis_ghp['task3_cost']['co2_total_kg'],
        kpis_ghp['task3_cost']['coste_delay_eur'], 
        rsd_ghp
    ]
})
    
    path_wp3 = os.path.join(BASE_DIR, 'data/processed/wp3_comparativa_final.csv')
    comparativa_wp3.to_csv(path_wp3, index=False)
    print("\n   ✅ Matriz comparativa GHP vs GDP guardada en CSV.")

    # -------------------------------------------------------------------------
    # WP4: ANÁLISIS INTERMODAL
    # -------------------------------------------------------------------------
    # Aquí llamamos a tu módulo. Si `lib_intermodal` tiene un print de cabecera muy escandaloso, 
    # te recomiendo que edites ese archivo y le bajes el tono para que siga este formato.
    try:
        resultados_wp4 = inter.ejecutar_analisis_intermodal(df_vuelos, resultados, params, BASE_DIR)
    except Exception as e:
        print(f"\n❌ ERROR en WP4. Revisa lib_intermodal.py. Detalle: {e}")
        traceback.print_exc()

    # -------------------------------------------------------------------------
    # WP5: ENTREGABLES (EXCEL y GRÁFICOS)
    # -------------------------------------------------------------------------
    print("\n" + "═" * 70)
    print("📁 [WP5] GENERANDO ENTREGABLES MAESTROS (AUDITORÍA Y GRÁFICOS)")
    print("═" * 70)

    os.makedirs(os.path.dirname(PATH_OUTPUT_CSV), exist_ok=True)
    df_final.to_csv(PATH_OUTPUT_CSV, index=False)
    print("   ✅ CSV maestro guardado.")

    r_min_newell = calcular_retraso_minimo_newell(resultados['timeline'])
    excel.exportar_auditoria_excel(
        resultados['vuelos_crudos'], df_final, df_slots, resultados['params'],
        resultados['h_noreg'], resultados['timeline'], r_min_newell,
        PATH_OUTPUT_EXCEL, df_res_comprimido=resultados['vuelos_comprimidos']
    )
    print("   ✅ Excel de auditoría consolidado.")

    vis.generar_graficos_fase2(
        timeline=resultados['timeline'], df_vuelos=df_vuelos, df_res=resultados['vuelos_asignados'],
        params=params, h_noreg=resultados['h_noreg'], paths=rutas_graficos,
    )
    print("   ✅ Gráficos de Newell y Capacidad exportados.")

    # -------------------------------------------------------------------------
    # RESUMEN FINAL
    # -------------------------------------------------------------------------
    print("\n" + "═" * 70)
    print("✨ PROCESO COMPLETO FINALIZADO CON ÉXITO ✨")
    print(f"   📄 CSV maestro:          data/processed/vuelos_finales_gdp.csv")
    print(f"   📊 Excel de auditoría:   data/processed/auditoria_completa.xlsx")
    print(f"   📈 Comparativa WP3:      data/processed/wp3_comparativa_final.csv")
    print(f"   🚆 Comparativa WP4:      data/processed/wp4_comparativa_intermodal.csv")
    print(f"   🌡️  Matriz sensibilidad: data/processed/sensitivity_grid.csv")
    print("═" * 70 + "\n")
    end_time = time.time()
    tiempo_ejecucion = end_time - start_time
    print(f"\n⏱️ TIEMPO DE EJECUCIÓN GHP: {tiempo_ejecucion:.4f} segundos")
    print("="*50)

if __name__ == "__main__":
    ejecutar_proyecto_completo()