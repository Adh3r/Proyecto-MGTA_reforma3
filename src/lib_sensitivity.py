# =============================================================================
# src/lib_sensitivity.py
# FASE 4: Análisis de sensibilidad — ¿Cuáles son los valores óptimos de R y HFile?
#
# CONTEXTO — POR QUÉ EXISTE ESTE MÓDULO:
#   El GDP tiene dos parámetros de diseño que el controlador puede ajustar:
#     - R (radio de cobertura):  ¿A qué distancia máxima regulamos vuelos?
#     - HFile (freeze horizon):  ¿Cuántos minutos antes del GDP consideramos
#                                 que un vuelo ya "no puede esperar en tierra"?
#   Este módulo estudia cómo cambian los KPIs cuando variamos estos parámetros,
#   y genera heatmaps para visualizar el trade-off entre ellos.
#
# METODOLOGÍA — BÚSQUEDA EN CUADRÍCULA (Grid Search):
#   Ejecutamos la simulación GDP completa para cada combinación posible de
#   (R, HFile) dentro de los rangos definidos en RADIOS_KM y HFILE_MINS.
#   Con 6 radios × 7 valores de HFile = 42 simulaciones en total.
#   El resultado es una tabla 6×7 por KPI, que se visualiza como heatmap.
#
# SEPARACIÓN DE RESPONSABILIDADES:
#   - Este módulo SOLO gestiona la cuadrícula y recoge los KPIs.
#   - Los heatmaps los dibuja lib_visualization.generar_heatmap().
#   - La simulación GDP la ejecuta lib_gdp_core.ejecutar_nucleo_gdp().
# =============================================================================

import os
import warnings

import numpy as np
import pandas as pd

import lib_visualization as vis
from config import CFG


# =============================================================================
# CUADRÍCULA DE PARÁMETROS A EXPLORAR
# =============================================================================
# Estos son los valores que vamos a probar para cada parámetro.
# Modificar estas listas cambia la resolución y el rango del análisis.

RADIOS_KM  = [500, 1000, 1500, 2000, 2500, 3000]    # Radio de cobertura GDP (km)
HFILE_MINS = [30, 60, 90, 120, 150, 180, 210]        # Freeze horizon HFile (min antes de H_START)


# =============================================================================
# DEFINICIÓN DE LOS HEATMAPS A GENERAR
# =============================================================================
# Cada entrada es una tupla con:
#   (nombre_columna_en_df, título_del_gráfico, unidad, 'min'/'max')
#
# 'min' significa que el valor MENOR es el mejor (ej: menos retraso = mejor).
# 'max' significa que el valor MAYOR es el mejor (ej: más ahorro = mejor).
# La función de heatmap usa esto para colorear y marcar la celda óptima.

HEATMAPS = [
    # --- KPIs exigidos explícitamente en el enunciado ---
    ('air_delay_total',     'Trade-off: Total AIR Delay',               'min', 'min'),
    ('co2_tierra_delay',    'CO2 Emissions Due to GROUND Delay',        'kg',  'min'),
    ('co2_aire_delay',      'CO2 Emissions Due to AIR Delay',           'kg',  'min'),
    ('unrecoverable_delay', 'Irrecoverable Delay (GDP cancelled)',      'min', 'min'),
    # --- KPIs de valor añadido (aportación del equipo) ---
    ('co2_savings',         'Net CO2 Savings vs. Do-Nothing',           'kg',  'max'),
    ('cost_savings',        'Total Economic Savings vs. Do-Nothing',    'EUR', 'max'),
]


# =============================================================================
# MOTOR DE SIMULACIÓN LIGERO — UNA EJECUCIÓN POR CELDA DE LA CUADRÍCULA
# =============================================================================

def _simular_gdp_ligero(
    df_vuelos: pd.DataFrame,
    params: dict,
    radius_km: int,
    h_freeze_offset: int,
) -> dict:
    """
    Ejecuta la simulación GDP completa para una combinación (R, HFile) concreta
    y devuelve solo los KPIs necesarios para los heatmaps.

    POR QUÉ NO DUPLICAMOS LA LÓGICA DE SIMULACIÓN AQUÍ:
        La simulación GDP ya está implementada en ejecutar_nucleo_gdp().
        En lugar de copiar ese código, simplemente la llamamos con los parámetros
        que queremos probar. Así, si corregimos un bug en ejecutar_nucleo_gdp(),
        el análisis de sensibilidad se beneficia automáticamente.

    POR QUÉ EL IMPORT ESTÁ DENTRO DE LA FUNCIÓN (no al principio del archivo):
        lib_sensitivity importa lib_gdp_core, y lib_gdp_core podría importar
        lib_sensitivity en el futuro. Si ambos se importan al principio,
        Python entra en un bucle infinito (import circular).
        Poner el import dentro de la función evita ese problema.

    Args:
        df_vuelos:       Tabla de vuelos preparada por la Fase 1.
        params:          Parámetros base del GDP (H_START, H_END, AAR, PAAR...).
        radius_km:       Radio de cobertura a probar en esta ejecución.
        h_freeze_offset: Freeze horizon a probar en esta ejecución.

    Returns:
        Diccionario con los KPIs de esta ejecución, listo para añadir a la tabla.
    """
    # Import local para evitar circularidad (ver explicación arriba)
    from lib_gdp_core import ejecutar_nucleo_gdp, calcular_kpis_economicos
    from config import FS_AIRBORNE

    # Ejecutamos la simulación GDP completa con los parámetros de esta celda
    resultados = ejecutar_nucleo_gdp(
        df_vuelos,
        params,
        radius_km=radius_km,
        h_freeze_offset=h_freeze_offset,
    )

    df_resultado = resultados['vuelos_asignados']
    kpis         = calcular_kpis_economicos(df_resultado)

    # Retraso irrecuperable: retraso total de los vuelos que ya estaban en el aire
    # cuando se activó el GDP. Si el GDP se cancela, este retraso no se puede evitar.
    retraso_irrecuperable = float(
    df_resultado[
        (df_resultado['flight_status'] == FS_AIRBORNE) &
        (df_resultado['distancia_km'] <= radius_km)
    ]['total_delay'].sum()
)

    # Devolvemos solo los KPIs que necesitamos para los heatmaps
    # (no toda la tabla de vuelos, para ahorrar memoria en las 42 ejecuciones)
    return {
        'radius_km':           radius_km,
        'h_freeze_offset':     h_freeze_offset,
        'air_delay_total':     float(df_resultado['air_delay'].sum()),
        'unrecoverable_delay': retraso_irrecuperable,
        'cost_savings':        kpis['cost_savings'],
        'co2_savings':         kpis['co2_savings'],
        'co2_aire_delay':      kpis['co2_aire_delay'],
        'co2_tierra_delay':    kpis['co2_tierra_delay'],
    }


# =============================================================================
# ORQUESTADOR PRINCIPAL
# =============================================================================

def ejecutar_analisis_sensibilidad(
    df_vuelos: pd.DataFrame,
    params: dict,
    base_dir: str,
) -> pd.DataFrame:
    """
    Ejecuta el análisis de sensibilidad completo:

        1. Itera sobre todas las combinaciones (R, HFile) de la cuadrícula.
        2. Para cada combinación, simula el GDP y recoge los KPIs.
        3. Construye una tabla con todos los resultados (42 filas).
        4. Para cada KPI, pivota la tabla en una matriz 6×7 y genera un heatmap.
        5. Guarda la tabla completa en un CSV para análisis posterior.

    QUÉ ES "PIVOTAR" UNA TABLA:
        La tabla de resultados tiene una fila por simulación (42 filas) con columnas
        radius_km, h_freeze_offset, air_delay_total, etc.
        Para dibujar un heatmap necesitamos una MATRIZ donde:
            - Las filas son los valores de HFile  (eje Y del heatmap)
            - Las columnas son los valores de R   (eje X del heatmap)
            - Cada celda contiene el valor del KPI para esa combinación
        df.pivot() hace exactamente esa transformación de tabla a matriz.

    Args:
        df_vuelos: Tabla de vuelos preparada por la Fase 1.
        params:    Parámetros base del GDP.
        base_dir:  Ruta raíz del proyecto (para construir rutas de salida).

    Returns:
        DataFrame con los resultados de las 42 simulaciones.
    """
    carpeta_heatmaps = os.path.join(base_dir, 'output', 'figures', 'heatmaps')
    total_simulaciones = len(RADIOS_KM) * len(HFILE_MINS)

    print(f"\n[SENSIBILIDAD] Ejecutando cuadrícula "
          f"{len(RADIOS_KM)} radios × {len(HFILE_MINS)} HFile = {total_simulaciones} simulaciones...")

    # -------------------------------------------------------------------------
    # BUCLE PRINCIPAL: EJECUTAR UNA SIMULACIÓN POR CELDA DE LA CUADRÍCULA
    # -------------------------------------------------------------------------
    # Iteramos sobre todos los radios y, para cada radio, sobre todos los HFile.
    # enumerate() nos da tanto el índice (i, j) como el valor (radio, hfile)
    # del elemento actual, lo cual usamos para mostrar el progreso.
    #
    # warnings.catch_warnings() + simplefilter("ignore") suprime los warnings
    # de pandas durante la simulación (ej: SettingWithCopyWarning). Los
    # suprimimos aquí porque son advertencias que ya conocemos y hemos decidido
    # ignorar, y mostrarlas 42 veces ensuciaría la consola innecesariamente.

    lista_resultados = []

    for i, radio in enumerate(RADIOS_KM):
        for j, hfile in enumerate(HFILE_MINS):

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                resultado_celda = _simular_gdp_ligero(df_vuelos, params, radio, hfile)

            lista_resultados.append(resultado_celda)

            # Mostramos el progreso en consola con \r (retorno de carro):
            # \r mueve el cursor al inicio de la línea SIN hacer salto de línea,
            # de modo que el siguiente print sobreescribe la misma línea.
            # Esto crea el efecto de "barra de progreso" en la terminal.
            numero_actual = i * len(HFILE_MINS) + j + 1
            print(
                f"   [{numero_actual:02d}/{total_simulaciones}] "
                f"R={radio:4d} km  HFile={hfile:3d} min  "
                f"→ air_delay={resultado_celda['air_delay_total']:.0f} min",
                end='\r'
            )

    print()  # Salto de línea después del último \r para no sobreescribir el resumen

    # Convertimos la lista de diccionarios en un DataFrame (una fila por simulación)
    df_cuadricula = pd.DataFrame(lista_resultados)

    # -------------------------------------------------------------------------
    # GENERAR UN HEATMAP POR CADA KPI
    # -------------------------------------------------------------------------
    print(f"   Generando {len(HEATMAPS)} heatmaps...")

    for nombre_kpi, titulo, unidad, mejor in HEATMAPS:

        # PIVOTAR: transformar la tabla lineal en una matriz 2D para el heatmap.
        # index='h_freeze_offset' → las filas del heatmap serán los valores de HFile
        # columns='radius_km'     → las columnas del heatmap serán los valores de R
        # values=nombre_kpi       → el valor en cada celda es el KPI que estamos analizando
        df_matriz = df_cuadricula.pivot(
            index='h_freeze_offset',
            columns='radius_km',
            values=nombre_kpi,
        )

        # Encontrar la celda con el valor óptimo (mínimo o máximo según el KPI)
        valores = df_matriz.values.astype(float)

        if mejor == 'min':
            # np.argmin() devuelve la posición del mínimo en el array aplanado (1D)
            # np.unravel_index() convierte esa posición 1D en coordenadas (fila, columna)
            indice_optimo = np.unravel_index(np.argmin(valores), valores.shape)
        else:
            indice_optimo = np.unravel_index(np.argmax(valores), valores.shape)

        # Construimos la ruta de salida del PNG
        nombre_archivo = nombre_kpi.replace('_', '-')
        ruta_png = os.path.join(carpeta_heatmaps, f"heatmap_{nombre_archivo}.png")

        # Llamamos a la función de visualización con todos los datos preparados
        vis.generar_heatmap(
            df_matriz,
            titulo,
            unidad,
            mejor,
            ruta_png,
            int(indice_optimo[0]),  # Fila del óptimo (índice de HFile)
            int(indice_optimo[1]),  # Columna del óptimo (índice de R)
            # _r invierte la paleta: rojo=alto (malo), verde=bajo (bueno)
        )

    # -------------------------------------------------------------------------
    # GUARDAR LA TABLA COMPLETA EN CSV
    # -------------------------------------------------------------------------
    # Guardamos todos los resultados de las 42 simulaciones en un CSV.
    # Esto permite análisis posteriores sin necesidad de re-ejecutar todo.
    ruta_csv = os.path.join(base_dir, 'data', 'processed', 'sensitivity_grid.csv')
    os.makedirs(os.path.dirname(ruta_csv), exist_ok=True)
    df_cuadricula.to_csv(ruta_csv, index=False)

    print(f"   → CSV con los 42 resultados: data/processed/sensitivity_grid.csv")
    print(f"   → Heatmaps: output/figures/heatmaps/ ({len(HEATMAPS)} imágenes PNG)")

    return df_cuadricula


# =============================================================================
# MODO DEBUG — Ejecutar directamente para probar este módulo de forma aislada.
#   cd src/
#   python lib_sensitivity.py
# =============================================================================
if __name__ == "__main__":
    import lib_data_prep as prep

    print("🛠️  MODO DEBUG: lib_sensitivity.py")

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    params = CFG.to_params_dict()

    df_vuelos = prep.preparar_vuelos(
        os.path.join(base, 'data/raw/LEBL_10AUG2025.csv'),
        os.path.join(base, 'data/raw/fleet_cat_seat.csv'),
    )

    ejecutar_analisis_sensibilidad(df_vuelos, params, base)