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
# FLUJO DE LAS 4 FASES:
#   [FASE 1] lib_data_prep    → Leer CSVs, limpiar datos, calcular distancias y CO2.
#   [FASE 2] lib_gdp_core     → Newell, etiquetado de vuelos, RBS, cálculo de retrasos.
#   [FASE 3] main             → Guardar CSV + Excel de auditoría + gráficos base.
#   [FASE 4] lib_sensitivity  → Análisis de sensibilidad: cuadrícula R × HFile → heatmaps.
#
# SEPARACIÓN DE RESPONSABILIDADES:
#   main.py solo sabe DÓNDE están los archivos y en QUÉ ORDEN llamar a cada módulo.
#   Toda la lógica vive en los módulos lib_*.
# =============================================================================

import os

import lib_data_prep    as prep
import lib_gdp_core     as gdp
import lib_excel_export as excel
import lib_sensitivity  as sens
import lib_visualization as vis
from config import CFG
from lib_gdp_core import calcular_retraso_minimo_newell
from config import FS_CANDIDATE
from lib_ghp_solver import ejecutar_ghp_completo


def ejecutar_proyecto_completo() -> None:
    """
    Orquestador principal: ejecuta las 4 fases del simulador ATM de LEBL.

    Esta función no hace cálculos — solo organiza el flujo de trabajo
    y conecta los módulos entre sí pasando los datos de una fase a la siguiente.
    """
    print("🚀 INICIANDO SIMULADOR ATM — AEROPUERTO DE BARCELONA (LEBL)")
    print("=" * 60)

    # =========================================================================
    # RUTAS DE ARCHIVO
    # =========================================================================
    # os.path.abspath(__file__)  → ruta absoluta de este script (src/main.py)
    # os.path.dirname(...) × 2  → subimos dos niveles → raíz del proyecto
    # Así el script funciona correctamente desde cualquier directorio.
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Datos de entrada (nunca se modifican)
    PATH_VUELOS_RAW = os.path.join(BASE_DIR, 'data/raw/LEBL_10AUG2025.csv')
    PATH_FLOTA_RAW  = os.path.join(BASE_DIR, 'data/raw/fleet_cat_seat.csv')

    # Entregables finales
    PATH_OUTPUT_CSV   = os.path.join(BASE_DIR, 'data/processed/vuelos_finales_gdp.csv')
    PATH_OUTPUT_EXCEL = os.path.join(BASE_DIR, 'data/processed/auditoria_completa.xlsx')

    # Rutas de los gráficos base (Fase 3)
    # Los gráficos 3 y 4 los construye generar_graficos_fase2() internamente
    rutas_graficos = {
        'cum': os.path.join(BASE_DIR, 'output/figures/1_diagrama_newell.png'),
        'bal': os.path.join(BASE_DIR, 'output/figures/2_balance_capacidad.png'),
    }

    # =========================================================================
    # FASE 1: PREPARACIÓN DE DATOS
    # =========================================================================
    # Construimos el diccionario de parámetros a partir de config.py.
    # Si alguien cambia el AAR en config.py, el cambio se propaga automáticamente.
    print("\n[FASE 1] Preparando datos y escenario...")

    params = CFG.to_params_dict()
    
    df_vuelos = prep.preparar_vuelos(PATH_VUELOS_RAW, PATH_FLOTA_RAW)
    print(f"✅ Datos cargados: {len(df_vuelos)} vuelos listos.")

    # =========================================================================
    # FASE 2: SIMULACIÓN GDP — ESCENARIO BASE
    # =========================================================================
    # Ejecutamos el GDP con los parámetros de config.py (el "escenario base").
    # La Fase 4 repetirá esta simulación 42 veces con distintos R y HFile.
    print("\n[FASE 2] Ejecutando motor de simulación y algoritmo RBS...")

    resultados = gdp.ejecutar_nucleo_gdp(df_vuelos, params, run_ghp=True)

    df_final = resultados['vuelos_asignados']
    df_slots = resultados['slots']
    slots_list = list(df_slots['slot_start_min'])

    # Resumen rápido en consola para verificar que la simulación tiene sentido
    candidatos = df_final[df_final['flight_status'] == FS_CANDIDATE]
    print(f"   Vuelos regulados (GDP): {len(candidatos)}")
    print(f"   Vuelos exentos:         {len(df_final) - len(candidatos)}")
    print(f"   Retraso medio global:   {df_final['total_delay'].mean():.1f} min/vuelo")
    # GHP
    from lib_ghp_solver import ejecutar_ghp_completo, calcular_kpis_ghp
    resultados_ghp = ejecutar_ghp_completo(df_final, slots_list, params)

    # =========================================================================
    # FASE 3: GENERACIÓN DE ENTREGABLES DEL ESCENARIO BASE
    # =========================================================================
    print("\n[FASE 3] Generando entregables del escenario base...")

    # --- CSV ligero (para análisis rápido o importar en Excel manualmente) ---
    os.makedirs(os.path.dirname(PATH_OUTPUT_CSV), exist_ok=True)
    df_final.to_csv(PATH_OUTPUT_CSV, index=False)
    print("   → CSV maestro guardado en data/processed/")

    # --- Excel de auditoría completo (7 pestañas con formato) ---
    # r_min_newell es el retraso mínimo teórico calculado aquí (no dentro del Excel)
    # para mantener lib_excel_export libre de lógica de cálculo.
    r_min_newell = calcular_retraso_minimo_newell(resultados['timeline'])

    excel.exportar_auditoria_excel(
        resultados['vuelos_crudos'],  # Pestaña 1: datos originales sin tocar
        df_final,                     # Pestañas 2, 5, 6, 7: resultados del GDP
        df_slots,                     # Pestaña 3: matriz de slots generados
        resultados['params'],         # Pestaña 0: parámetros del escenario
        resultados['h_noreg'],        # Pestaña 0: hora de recuperación del aeropuerto
        resultados['timeline'],       # Pestaña 0: curvas de Newell (para el gráfico)
        r_min_newell,                 # Pestaña 0: retraso mínimo teórico
        PATH_OUTPUT_EXCEL,
        df_res_comprimido=resultados['vuelos_comprimidos'] # <-- ¡NUEVA LÍNEA!
    )
    print("   → Excel de auditoría guardado en data/processed/")

    # --- 4 gráficos PNG del escenario base ---
    vis.generar_graficos_fase2(
        timeline  = resultados['timeline'],
        df_vuelos = df_vuelos,
        df_res    = resultados['vuelos_asignados'],
        params    = params,
        h_noreg   = resultados['h_noreg'],
        paths     = rutas_graficos,
    )
    print("   → Gráficos guardados en output/figures/")

    # =========================================================================
    # FASE 4: ANÁLISIS DE SENSIBILIDAD — CUADRÍCULA R × HFILE
    # =========================================================================
    # Ejecutamos el GDP 42 veces (6 radios × 7 HFile) y generamos un heatmap
    # por KPI para identificar los valores óptimos de R y HFile.
    print("\n[FASE 4] Análisis de sensibilidad (42 simulaciones)...")

    sens.ejecutar_analisis_sensibilidad(df_vuelos, params, BASE_DIR)

    # =========================================================================
    # RESUMEN FINAL
    # =========================================================================
    print("\n" + "=" * 60)
    print("✨ PROCESO COMPLETO FINALIZADO CON ÉXITO")
    print(f"   📄 CSV escenario base:   data/processed/vuelos_finales_gdp.csv")
    print(f"   📊 Excel de auditoría:   data/processed/auditoria_completa.xlsx")
    print(f"   🌡️  Matriz sensibilidad:  data/processed/sensitivity_grid.csv")
    print(f"   🖼️  Gráficos y heatmaps:  output/figures/")
    print("=" * 60)


if __name__ == "__main__":
    ejecutar_proyecto_completo()