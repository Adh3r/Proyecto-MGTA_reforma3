# =============================================================================
# src/main.py
# PUNTO DE ENTRADA DEL PROYECTO — Ejecuta la simulación completa de extremo a extremo.
#
# Este script es el "director de orquesta": no tiene lógica propia, solo llama
# a las funciones correctas en el orden correcto y gestiona las rutas de archivo.
#
# Para ejecutar el proyecto completo, lanza desde la terminal:
#   cd src/
#   python main.py
#
# Estructura del flujo:
#   [FASE 1] lib_data_prep → Leer CSVs, limpiar, calcular distancias.
#   [FASE 2] lib_gdp_core  → Newell, etiquetado, RBS, gráficos.
#   [FASE 3] main          → Guardar CSV final + Excel de auditoría.
#   [FASE 4] lib_sensitivity → Cuadrícula de R vs HFile (Heatmaps)
# =============================================================================

import os

import lib_data_prep as prep
import lib_gdp_core as gdp
import lib_excel_export as excel
import lib_sensitivity as sens
import lib_visualization as vis
from config import CFG


def ejecutar_proyecto_completo() -> None:
    """
    Orquestador principal: ejecuta las 4 fases del simulador ATM de LEBL.
    """
    print("🚀 INICIANDO SIMULADOR ATM — AEROPUERTO DE BARCELONA (LEBL)")
    print("=" * 60)

    # -------------------------------------------------------------------------
    # RUTAS DE ARCHIVO
    # -------------------------------------------------------------------------
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # ENTRADAS
    PATH_VUELOS_RAW = os.path.join(BASE_DIR, 'data/raw/LEBL_10AUG2025.csv')
    PATH_FLOTA_RAW  = os.path.join(BASE_DIR, 'data/raw/fleet_cat_seat.csv')

    # SALIDAS 
    PATH_OUTPUT_CSV   = os.path.join(BASE_DIR, 'data/processed/vuelos_finales_gdp.csv')
    PATH_OUTPUT_EXCEL = os.path.join(BASE_DIR, 'data/processed/auditoria_completa.xlsx')

    rutas_graficos = {
        'cum': os.path.join(BASE_DIR, 'output/figures/1_diagrama_newell.png'),
        'bal': os.path.join(BASE_DIR, 'output/figures/2_balance_capacidad.png'),
    }

    # -------------------------------------------------------------------------
    # FASE 1: Preparación de datos
    # -------------------------------------------------------------------------
    print("\n[FASE 1] Preparando datos y escenario...")

    params = {
        'H_START':  CFG.H_START,
        'H_END':    CFG.H_END,
        'AAR':      CFG.AAR,
        'PAAR':     CFG.PAAR,
        'SLOT_NOM': CFG.SLOT_NOM,
        'SLOT_RED': CFG.SLOT_RED,
    }

    df_vuelos = prep.preparar_vuelos(PATH_VUELOS_RAW, PATH_FLOTA_RAW)
    print(f"✅ Datos cargados: {len(df_vuelos)} vuelos listos.")

    # -------------------------------------------------------------------------
    # FASE 2: Motor de simulación GDP (Escenario Base Configurado en config.py)
    # -------------------------------------------------------------------------
    print("\n[FASE 2] Ejecutando motor de simulación y algoritmo RBS (Escenario Base)...")

    resultados = gdp.ejecutar_nucleo_gdp(df_vuelos, params)

    df_final  = resultados['vuelos_asignados']
    df_slots  = resultados['slots']

    candidatos = df_final[df_final['flight_status'] == 'GPD CANDIDATE']
    print(f"   Vuelos regulados (GDP): {len(candidatos)}")
    print(f"   Vuelos exentos:         {len(df_final) - len(candidatos)}")
    print(f"   Retraso medio global:   {df_final['total_delay'].mean():.1f} min/vuelo")

    # -------------------------------------------------------------------------
    # FASE 3: Generación de entregables finales (Escenario Base)
    # -------------------------------------------------------------------------
    print("\n[FASE 3] Generando entregables finales del Escenario Base...")

    os.makedirs(os.path.dirname(PATH_OUTPUT_CSV), exist_ok=True)
    df_final.to_csv(PATH_OUTPUT_CSV, index=False)
    print(f"   → CSV maestro guardado en data/processed/")

    excel.exportar_auditoria_excel(
        resultados['vuelos_crudos'],
        df_final,
        df_slots,
        resultados['params'],
        resultados['h_noreg'],
        resultados['timeline'],
        PATH_OUTPUT_EXCEL,
    )
    print(f"   → Excel de auditoría guardado en data/processed/")

    vis.generar_graficos_fase2(
    timeline=resultados['timeline'],
    df_vuelos=df_vuelos,
    df_res=resultados['vuelos_asignados'],
    params=params,
    h_noreg=resultados['h_noreg'],
    paths=rutas_graficos
    )
    print(f"   → Gráficos guardados en output/figures/")

    # -------------------------------------------------------------------------
    # FASE 4: Análisis de Sensibilidad (Heatmaps)
    # -------------------------------------------------------------------------
    print("\n[FASE 4] Arrancando Análisis de Sensibilidad (Múltiples Escenarios)...")
    
    # Llamamos a la función principal de lib_sensitivity pasándole los datos base
    # La función se encarga de iterar, generar el CSV de la cuadrícula y los PNGs
    df_grid_sensibilidad = sens.ejecutar_analisis_sensibilidad(df_vuelos, params, BASE_DIR)


    # -------------------------------------------------------------------------
    # RESUMEN FINAL
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("✨ PROCESO COMPLETO FINALIZADO CON ÉXITO")
    print(f"   📄 Escenario Base (CSV):    data/processed/vuelos_finales_gdp.csv")
    print(f"   📊 Excel Auditoría:         data/processed/auditoria_completa.xlsx")
    print(f"   🌡️ Matriz Sensibilidad:     data/processed/sensitivity_grid.csv")
    print(f"   🖼️ Gráficos y Heatmaps:     output/figures/")
    print("=" * 60)


if __name__ == "__main__":
    ejecutar_proyecto_completo()