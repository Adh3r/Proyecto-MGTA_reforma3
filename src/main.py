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
# =============================================================================

import os

import lib_data_prep as prep
import lib_gdp_core as gdp
import lib_excel_export as excel
from config import CFG


def ejecutar_proyecto_completo() -> None:
    """
    Orquestador principal: ejecuta las 3 fases del simulador ATM de LEBL.

    ¿Por qué separar la lógica en lib_data_prep y lib_gdp_core en lugar de
    ponerlo todo aquí?
        - Separación de responsabilidades: cada módulo hace una sola cosa.
        - Testeabilidad: puedes probar cada fase de forma independiente
          ejecutando su script directamente (modo debug en cada librería).
        - Reutilización: si mañana quieres simular otro aeropuerto, solo
          cambias config.py y los paths, sin tocar la lógica del algoritmo.
    """
    print("🚀 INICIANDO SIMULADOR ATM — AEROPUERTO DE BARCELONA (LEBL)")
    print("=" * 60)

    # -------------------------------------------------------------------------
    # RUTAS DE ARCHIVO
    # Calculamos todas las rutas desde la raíz del proyecto (BASE_DIR)
    # para que el script funcione independientemente de desde dónde se ejecute.
    # os.path.abspath(__file__) → ruta absoluta de este script (src/main.py)
    # os.path.dirname(...)×2    → subimos dos niveles → raíz del proyecto
    # -------------------------------------------------------------------------
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # ENTRADAS (datos crudos — nunca se modifican)
    PATH_VUELOS_RAW = os.path.join(BASE_DIR, 'data/raw/LEBL_10AUG2025.csv')
    PATH_FLOTA_RAW  = os.path.join(BASE_DIR, 'data/raw/fleet_cat_seat.csv')

    # SALIDAS (entregables finales)
    PATH_OUTPUT_CSV   = os.path.join(BASE_DIR, 'data/processed/vuelos_finales_gdp.csv')
    PATH_OUTPUT_EXCEL = os.path.join(BASE_DIR, 'data/processed/auditoria_completa.xlsx')

    # Rutas de los gráficos — se pasan como diccionario al módulo GDP
    rutas_graficos = {
        'cum': os.path.join(BASE_DIR, 'output/figures/1_diagrama_newell.png'),
        'bal': os.path.join(BASE_DIR, 'output/figures/2_balance_capacidad.png'),
    }

    # -------------------------------------------------------------------------
    # FASE 1: Preparación de datos
    # Convierte los CSVs crudos en un DataFrame limpio con cinemática calculada.
    # -------------------------------------------------------------------------
    print("\n[FASE 1] Preparando datos y escenario...")

    # Construimos el diccionario de parámetros a partir del dataclass centralizado.
    # Así, si alguien cambia AAR en config.py, el cambio se propaga automáticamente.
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
    # FASE 2: Motor de simulación GDP
    # Ejecuta Newell, etiqueta exenciones, asigna slots RBS y genera gráficos.
    # -------------------------------------------------------------------------
    print("\n[FASE 2] Ejecutando motor de simulación y algoritmo RBS...")

    resultados = gdp.ejecutar_nucleo_gdp(df_vuelos, params, rutas_graficos)

    df_final  = resultados['vuelos_asignados']
    df_slots  = resultados['slots']

    # Mostramos un resumen rápido en consola para verificación inmediata
    candidatos = df_final[df_final['flight_status'] == 'GPD CANDIDATE']
    print(f"   Vuelos regulados (GDP): {len(candidatos)}")
    print(f"   Vuelos exentos:         {len(df_final) - len(candidatos)}")
    print(f"   Retraso medio:          {df_final['total_delay'].mean():.1f} min/vuelo")

    # -------------------------------------------------------------------------
    # FASE 3: Generación de entregables finales
    # CSV ligero para análisis posterior + Excel completo para el cliente.
    # -------------------------------------------------------------------------
    print("\n[FASE 3] Generando entregables finales...")

    # Creamos el directorio si no existe (exist_ok=True evita error si ya existe)
    os.makedirs(os.path.dirname(PATH_OUTPUT_CSV), exist_ok=True)
    df_final.to_csv(PATH_OUTPUT_CSV, index=False)
    print(f"   → CSV maestro guardado en data/processed/")

    # El Excel necesita 4 argumentos: datos crudos (para trazabilidad),
    # resultados GDP, matriz de slots y ruta de salida.
    excel.exportar_auditoria_excel(
        resultados['vuelos_crudos'],   # Pestaña 1: datos originales sin tocar
        df_final,                      # Pestañas 2, 4, 5: resultados del GDP
        df_slots,                      # Pestaña 3: matriz de slots
        resultados['params'],
        resultados['h_noreg'],
        resultados['timeline'],
        PATH_OUTPUT_EXCEL,
    )

    # -------------------------------------------------------------------------
    # RESUMEN FINAL
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("✨ PROCESO FINALIZADO CON ÉXITO")
    print(f"   📄 CSV:     data/processed/vuelos_finales_gdp.csv")
    print(f"   📊 Excel:   data/processed/auditoria_completa.xlsx")
    print(f"   🖼️  Gráficos: output/figures/ (4 imágenes PNG)")
    print("=" * 60)


# =============================================================================
# Punto de entrada estándar de Python.
# Este bloque SOLO se ejecuta cuando lanzas el script directamente:
#   python main.py
# pito cum cum 
# NO se ejecuta si otro módulo importa main (ej: import main).
# =============================================================================
if __name__ == "__main__":
    ejecutar_proyecto_completo()
