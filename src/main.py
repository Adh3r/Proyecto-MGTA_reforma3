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
from lib_metrics         import evaluar_escenario # <-- NUEVO MOTOR DE MÉTRICAS

from config import CFG, FS_CANDIDATE
from lib_gdp_core import calcular_retraso_minimo_newell
from lib_ghp_solver import ejecutar_ghp_completo

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
    PATH_VUELOS_RAW   = os.path.join(BASE_DIR, 'data/raw/LEBL_10AUG2025.csv')
    PATH_FLOTA_RAW    = os.path.join(BASE_DIR, 'data/raw/fleet_cat_seat.csv')
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
    h_start_min = params.get('H_START', 0) # Necesario para evaluar retraso irrecuperable
    df_vuelos = prep.preparar_vuelos(PATH_VUELOS_RAW, PATH_FLOTA_RAW)
    print(f"   ✅ Datos cargados y depurados: {len(df_vuelos)} vuelos en la red.")

    # -------------------------------------------------------------------------
    # WP2: SIMULACIÓN GDP BASE
    # -------------------------------------------------------------------------
    print("\n" + "═" * 70)
    print("🛫 [WP2] EJECUTANDO MOTOR DE SIMULACIÓN GDP (Algoritmo RBS)")
    print("═" * 70)
    
    resultados = gdp.ejecutar_nucleo_gdp(df_vuelos, params, run_ghp=False)

    df_final = resultados['vuelos_asignados']
    df_slots = resultados['slots']
    slots_list = list(df_slots['slot_start_min'])
    candidatos = df_final[df_final['flight_status'] == FS_CANDIDATE]
    
    print(f"   • Vuelos regulados (GDP): {len(candidatos)}")
    print(f"   • Vuelos exentos:         {len(df_final) - len(candidatos)}")
    print(f"   • Retraso medio global:   {df_final['total_delay'].mean():.1f} min/vuelo")

    # Inicializamos el diccionario maestro de escenarios y la lista de KPIs
    escenarios_dict = {'GDP_Basic_Scenario': df_final}
    lista_kpis = [evaluar_escenario(df_final, 'GDP_Basic_Scenario', h_start_min)]

    # -------------------------------------------------------------------------
    # WP2 (EXTRA): ANÁLISIS DE SENSIBILIDAD
    # -------------------------------------------------------------------------
    print("\n" + "═" * 70)
    print("🌡️  [WP2-B] ANÁLISIS DE SENSIBILIDAD (Radio vs H_File)")
    print("═" * 70)
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
    
    # Evaluamos y almacenamos los escenarios GHP usando el motor unificado
    for nombre_task in ['GDP_Aditional_Constraints', 'GHP_Opt_Emissions', 'GHP_Opt_Cost']:
        df_task = resultados_ghp[nombre_task]
        escenarios_dict[f'WP3_{nombre_task}'] = df_task
        lista_kpis.append(evaluar_escenario(df_task, f'WP3_{nombre_task}', h_start_min))
    
    # Construimos el Dashboard Comparativo (DataFrame) maestro
    df_dashboard = pd.DataFrame(lista_kpis)

    # -------------------------------------------------------------------------
    # --- REFORMATAR TABLA WP3 PARA IGUALAR A WP4 ---
    # -------------------------------------------------------------------------
    
    # Cálculos previos necesarios para igualar las métricas
    demanda_total = len(df_final)
    # Por si la columna de CO2 se genera en otro lado, pillamos de df_final o df_vuelos
    co2_nominal_base = df_final['co2_kg_vuelo'].sum() if 'co2_kg_vuelo' in df_final.columns else df_vuelos['co2_kg_vuelo'].sum()
    
    h_noreg_base = resultados['h_noreg'] 
    duracion_impacto = h_noreg_base - params.get('H_START', 0)

    # Función auxiliar para extraer datos de df_dashboard
    def get_kpi(escenario, columna):
        return df_dashboard.loc[df_dashboard['Escenario'] == escenario, columna].iloc[0]

    # Creamos la tabla con la misma estructura exacta que WP4
    comparativa_wp3 = pd.DataFrame({
        'Métrica': [
            'Demanda total (vuelos)',
            'Retraso total GDP (min)',
            'HNoReg — Cola disuelta (min UTC)',
            'Duración impacto (min)',
            'Emisiones CO₂ retraso (kg)',
            'Emisiones CO₂ TOTAL Sistema (kg)', 
            'Coste total retraso (EUR)',
            'Ahorro neto CO₂ directo por Tren (kg)',
            'Equidad RSD (%)'
        ],
        'GDP Basic Scenario': [
            demanda_total,
            round(get_kpi('GDP_Basic_Scenario', 'Retraso_Total_min'), 1),
            h_noreg_base,
            duracion_impacto,
            round(get_kpi('GDP_Basic_Scenario', 'CO2_Total_Retraso_kg'), 1),
            round(co2_nominal_base + get_kpi('GDP_Basic_Scenario', 'CO2_Total_Retraso_kg'), 1),
            int(get_kpi('GDP_Basic_Scenario', 'Coste_Cook_Total_EUR')),
            'N/A', 
            round(get_kpi('GDP_Basic_Scenario', 'RSD_Total_%'), 2)
        ],
        'GDP Aditional Constraints': [
            demanda_total,
            round(get_kpi('WP3_GDP_Aditional_Constraints', 'Retraso_Total_min'), 1),
            h_noreg_base,
            duracion_impacto,
            round(get_kpi('WP3_GDP_Aditional_Constraints', 'CO2_Total_Retraso_kg'), 1),
            round(co2_nominal_base + get_kpi('WP3_GDP_Aditional_Constraints', 'CO2_Total_Retraso_kg'), 1),
            int(get_kpi('WP3_GDP_Aditional_Constraints', 'Coste_Cook_Total_EUR')),
            'N/A', 
            round(get_kpi('WP3_GDP_Aditional_Constraints', 'RSD_Total_%'), 2)
        ],
        'GHP Opt Cost': [
            demanda_total,
            round(get_kpi('WP3_GHP_Opt_Cost', 'Retraso_Total_min'), 1),
            h_noreg_base,
            duracion_impacto,
            round(get_kpi('WP3_GHP_Opt_Cost', 'CO2_Total_Retraso_kg'), 1),
            round(co2_nominal_base + get_kpi('WP3_GHP_Opt_Cost', 'CO2_Total_Retraso_kg'), 1),
            int(get_kpi('WP3_GHP_Opt_Cost', 'Coste_Cook_Total_EUR')),
            'N/A', 
            round(get_kpi('WP3_GHP_Opt_Cost', 'RSD_Total_%'), 2)
        ],
        'GHP Opt Emissions': [
            demanda_total,
            round(get_kpi('WP3_GHP_Opt_Emissions', 'Retraso_Total_min'), 1),
            h_noreg_base,
            duracion_impacto,
            round(get_kpi('WP3_GHP_Opt_Emissions', 'CO2_Total_Retraso_kg'), 1),
            round(co2_nominal_base + get_kpi('WP3_GHP_Opt_Emissions', 'CO2_Total_Retraso_kg'), 1),
            int(get_kpi('WP3_GHP_Opt_Emissions', 'Coste_Cook_Total_EUR')),
            'N/A', 
            round(get_kpi('WP3_GHP_Opt_Emissions', 'RSD_Total_%'), 2)
        ]
    })

    print("\n 📊 RESUMEN EJECUTIVO WP3 (Sin Intermodalidad):")
    print(f"{'Métrica':>38} | {'GDP Basic Scenario':>18} | {'GDP Aditional Constraints':>18} | {'GHP Opt Cost':>20} | {'GHP Opt Emissions':>20}")
    print("-" * 125)
    for _, row in comparativa_wp3.iterrows():
        print(f"{row['Métrica']:>38} | {str(row['GDP Basic Scenario']):>18} | {str(row['GDP Aditional Constraints']):>18} | {str(row['GHP Opt Cost']):>20} | {str(row['GHP Opt Emissions']):>20}")

    # Guardamos ambos (el original crudo para auditoría y el visual para los gráficos)
    path_wp3_original = os.path.join(BASE_DIR, 'data/processed/wp3_dashboard_crudo.csv')
    
    # 🌟 AQUÍ ESTÁ LA MAGIA: Guardamos la comparativa que acabas de construir 
    # directamente como wp3_resumen_ejecutivo.csv para que la lea el gráfico luego.
    path_wp3_resumen = os.path.join(BASE_DIR, 'data/processed/wp3_resumen_ejecutivo.csv')
    
    df_dashboard.to_csv(path_wp3_original, index=False)
    comparativa_wp3.to_csv(path_wp3_resumen, index=False)
    print(f"\n   ✅ Matrices comparativas guardadas en CSV.")
    print(f"   ✅ Resumen Ejecutivo WP3 exportado a: {path_wp3_resumen}")

    

    # -------------------------------------------------------------------------
    # WP4: ANÁLISIS INTERMODAL
    # -------------------------------------------------------------------------
    df_tabla_intermodal = None
    try:
        # Pasamos resultados_ghp como tercer argumento
        resultados_wp4 = inter.ejecutar_analisis_intermodal(df_vuelos, resultados, resultados_ghp, params, BASE_DIR)
        
        if isinstance(resultados_wp4, dict):
            # 1. Capturamos la tabla comparativa para la Pestaña 8
            df_tabla_intermodal = resultados_wp4['df_comparativa']
            
            # 2. Capturamos los resultados del GHP para las DOS funciones de coste
            df_intermodal_gdp = resultados_wp4['resultados_reducido']['resultados_ghp']['GDP_Aditional_Constraints']
            df_intermodal_coste = resultados_wp4['resultados_reducido']['resultados_ghp']['GHP_Opt_Cost']
            df_intermodal_co2 = resultados_wp4['resultados_reducido']['resultados_ghp']['GHP_Opt_Emissions']
            
            # 3. Los inyectamos en el diccionario general de escenarios
            escenarios_dict['Intermodal_GDP'] = df_intermodal_gdp
            escenarios_dict['Intermodal_GHP_Coste'] = df_intermodal_coste
            escenarios_dict['Intermodal_GHP_CO2'] = df_intermodal_co2
            
            # 4. Actualizamos el Dashboard general (WP5)
            lista_kpis.append(evaluar_escenario(df_intermodal_gdp, 'Intermodal_GDP', h_start_min))
            lista_kpis.append(evaluar_escenario(df_intermodal_coste, 'Intermodal_GHP_Coste', h_start_min))
            lista_kpis.append(evaluar_escenario(df_intermodal_co2, 'Intermodal_GHP_CO2', h_start_min))
            df_dashboard = pd.DataFrame(lista_kpis)
            
            print("✅ Datos intermodales procesados y listos para exportar.")
            
    except Exception as e:
        print(f"\n❌ ERROR en WP4. Detalle: {e}")
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
    
    # Llamada refactorizada al exportador Multi-Escenario
    excel.exportar_auditoria_excel(
        df_vuelos_crudo=resultados['vuelos_crudos'],
        escenarios_dict=escenarios_dict,
        df_dashboard=df_dashboard,
        df_slots=df_slots,
        params=resultados['params'],
        h_noreg=resultados['h_noreg'],
        timeline=resultados['timeline'],
        r_min_newell=r_min_newell,
        path=PATH_OUTPUT_EXCEL,
        df_res_comprimido=resultados.get('vuelos_comprimidos'),
        df_intermodal=df_tabla_intermodal
    )

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
    print(f"   📈 Dashboard KPIs:       data/processed/wp3_comparativa_final.csv")
    print(f"   🚆 Comparativa WP4:      data/processed/wp4_comparativa_intermodal.csv")
    print(f"   🌡️  Matriz sensibilidad: data/processed/sensitivity_grid.csv")
    print("═" * 70 + "\n")
    
    end_time = time.time()
    tiempo_ejecucion = end_time - start_time
    print(f"\n⏱️ TIEMPO DE EJECUCIÓN TOTAL: {tiempo_ejecucion:.4f} segundos")
    print("="*50)

if __name__ == "__main__":
    ejecutar_proyecto_completo()