# =============================================================================
# src/lib_visualization.py
# MÓDULO DE VISUALIZACIÓN — Gráficos, diagramas y heatmaps del simulador.
#
# Este módulo contiene TODAS las funciones que generan imágenes PNG.
# Ninguna otra función de cálculo vive aquí — solo visualización.
#
# GRÁFICOS DEL ESCENARIO BASE (Fase 2):
#   1. plot_newell()              → Diagrama de flujo acumulado (curvas de Newell)
#   2. plot_balance_capacidad()   → Demanda horaria vs. tráfico real servido
#   3. plot_impacto_economico()   → Coste Do-Nothing vs. GDP (barras)
#   4. plot_equidad_aerolineas()  → Retraso medio por aerolínea (Top 10)
#   5. generar_graficos_fase2()   → Orquestador: llama a los 4 anteriores
#
# HEATMAPS DEL ANÁLISIS DE SENSIBILIDAD (Fase 4):
#   6. generar_heatmap()          → Un heatmap por KPI (R vs HFile)
#
# LIBRERÍAS USADAS:
#   - matplotlib: la librería estándar de Python para gráficos.
#                 plt.figure(), plt.plot(), plt.bar()... son sus funciones base.
#   - seaborn:    librería de alto nivel construida sobre matplotlib.
#                 Simplifica ciertos gráficos complejos como los heatmaps.
# =============================================================================

import os
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd

# Importamos calcular_kpis_economicos para el gráfico de impacto económico.
# Usamos la misma función que el Excel para garantizar que los números coinciden.
from lib_gdp_core import calcular_kpis_economicos


# =============================================================================
# HEATMAP DEL ANÁLISIS DE SENSIBILIDAD (FASE 4)
# =============================================================================

def generar_heatmap(
    df_matriz: pd.DataFrame,
    titulo: str,
    unidad: str,
    mejor: str,
    ruta_salida: str,
    fila_optima: int,
    columna_optima: int,
    
) -> None:
    """
    Genera y guarda un heatmap de una matriz KPI en función de R y HFile.

    QUÉ ES UN HEATMAP:
        Un heatmap es una tabla donde cada celda tiene un color que representa
        su valor. Las celdas "buenas" son verdes y las "malas" son rojas
        (o al revés, según si queremos maximizar o minimizar el KPI).
        Permite ver de un vistazo qué combinación de (R, HFile) es la mejor.

    CÓMO FUNCIONA EL CONTRASTE DISCRETO (5 BINS):
        En lugar de una escala de color continua (infinitos tonos), usamos
        solo 5 colores distintos. Esto hace que diferencias pequeñas entre
        celdas sean inmediatamente visibles incluso en impresión en blanco y negro.
        plt.get_cmap('RdYlGn', 5) obtiene la paleta Rojo-Amarillo-Verde
        dividida en exactamente 5 tonos.

    CÓMO FUNCIONAN LOS PERCENTILES COMO LÍMITES:
        Si usáramos el mínimo y máximo absolutos como límites de color,
        un único valor extremo (outlier) haría que todas las demás celdas
        tuvieran prácticamente el mismo color.
        Usar los percentiles 10 y 90 como límites ignora los extremos y
        concentra el contraste en el rango donde están la mayoría de los valores.

    Args:
        df_matriz:      Matriz 2D pivotada (filas=HFile, columnas=R, valores=KPI).
        titulo:         Título del gráfico (nombre del KPI).
        unidad:         Unidad de medida para la barra de color ('min', 'kg', 'EUR').
        mejor:          'min' si el valor menor es mejor, 'max' si el mayor es mejor.
        ruta_salida:    Ruta completa del archivo PNG de salida.
        fila_optima:    Índice de fila de la celda óptima (para marcarla).
        columna_optima: Índice de columna de la celda óptima (para marcarla).
    """
    # 1. Damos la vuelta a los valores del eje Y (HFile)
    df_matriz = df_matriz.sort_index(ascending=False)

    # 2. Corregimos la posición del recuadro azul ("★ BEST"). 
    # Al dar la vuelta a la tabla, la fila óptima cambia de coordenada visual.
    fila_optima = (len(df_matriz) - 1) - fila_optima
    # =========================================================

    plt.figure(figsize=(12, 7))

    # Aplanamos la matriz a una lista 1D para calcular los percentiles
    todos_los_valores = df_matriz.values.flatten()
    plt.figure(figsize=(12, 7))

    # Aplanamos la matriz a una lista 1D para calcular los percentiles
    todos_los_valores = df_matriz.values.flatten()

    # Límites de color: percentiles 10 y 90 para ignorar outliers extremos
    limite_inferior = np.nanpercentile(todos_los_valores, 10)
    limite_superior = np.nanpercentile(todos_los_valores, 90)

    # Si todos los valores son iguales, usamos el mínimo y máximo absolutos
    # (de lo contrario vmin == vmax y matplotlib lanzaría un error)
    if limite_inferior == limite_superior:
        limite_inferior = todos_los_valores.min()
        limite_superior = todos_los_valores.max()

    # Paleta de 5 colores discretos:
    #   'RdYlGn'   → Rojo (malo) a Verde (bueno): usada cuando más = mejor
    #   'RdYlGn_r' → Verde (bueno) a Rojo (malo): usada cuando menos = mejor
    #   El segundo argumento (5) divide la paleta en exactamente 5 tonos.
    nombre_paleta = "RdYlGn" if mejor == 'max' else "RdYlGn_r"
    paleta_5_colores = plt.get_cmap(nombre_paleta, 5)

    # Formato numérico de las anotaciones dentro de las celdas:
    #   ",.0f" → número entero con separador de miles (ej: 35,000)
    #   ".1f"  → un decimal (ej: 68.8)
    formato_numero = ",.0f" if any(x in unidad for x in ["EUR", "kg"]) else ".1f"

    # -------------------------------------------------------------------------
    # DIBUJAR EL HEATMAP CON SEABORN
    #
    # sns.heatmap() es la función principal de seaborn para heatmaps.
    # Parámetros clave:
    #   annot=True     → Muestra el valor numérico dentro de cada celda
    #   fmt=           → Formato de ese número
    #   cmap=          → Paleta de colores a usar
    #   vmin/vmax=     → Límites de la escala de color
    #   linewidths=    → Grosor de las líneas entre celdas
    #   cbar_kws=      → Opciones de la barra de color lateral
    # -------------------------------------------------------------------------
    ax = sns.heatmap(
        df_matriz,
        annot=True,
        fmt=formato_numero,
        cmap=paleta_5_colores,
        vmin=limite_inferior,
        vmax=limite_superior,
        cbar_kws={
            'label': unidad,
            'ticks': np.linspace(limite_inferior, limite_superior, 6),
        },
        linewidths=1.5,
        linecolor='white',
        annot_kws={"size": 8, "weight": "bold"},
    )

    # Etiquetas de los ejes con las unidades correctas
    ax.set_xticklabels([f"{int(c)} km"  for c in df_matriz.columns])
    ax.set_yticklabels([f"{int(i)} min" for i in df_matriz.index], rotation=0)
    ax.set_xlabel('GDP Radius of Exemption R (km)',      fontsize=11, fontweight='bold')
    ax.set_ylabel('Freeze Horizon HFile (min)',          fontsize=11, fontweight='bold')
    ax.set_title(titulo.upper(), fontsize=13, fontweight='bold', pad=20)

    # -------------------------------------------------------------------------
    # MARCAR LA CELDA ÓPTIMA CON UN RECUADRO AZUL
    #
    # ax.add_patch() añade una figura geométrica encima del heatmap.
    # plt.Rectangle((x, y), ancho, alto) define un rectángulo.
    # Las coordenadas (x, y) en un heatmap de seaborn corresponden a
    # (columna, fila) contando desde la esquina superior izquierda.
    # fill=False hace que el rectángulo sea solo el borde, sin relleno.
    # zorder=15 asegura que el recuadro se dibuje por encima de todo lo demás.
    # -------------------------------------------------------------------------
    ax.add_patch(plt.Rectangle(
        (columna_optima, fila_optima), 1, 1,
        fill=False, edgecolor='blue', linewidth=4, zorder=15,
    ))

    # Texto "★ BEST" dentro de la celda óptima
    ax.text(
        columna_optima + 0.5,   # Centro horizontal de la celda
        fila_optima + 0.9,      # Cerca del borde inferior de la celda
        '★ BEST',
        ha='center', va='bottom',
        fontsize=10, color='blue', fontweight='bold',
        bbox=dict(facecolor='white', alpha=0.9, edgecolor='blue', boxstyle='round,pad=0.2'),
    )

    plt.tight_layout()
    os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)
    plt.savefig(ruta_salida, dpi=200, bbox_inches='tight')
    plt.close()


# =============================================================================
# GRÁFICO 1: DIAGRAMA DE NEWELL — CURVAS ACUMULADAS
# =============================================================================

def plot_newell(
    timeline: pd.DataFrame,
    params: dict,
    h_noreg: int,
    ruta_salida: str,
) -> None:
    """
    Genera el Diagrama de Flujo Acumulado (Cumulative Flow Diagram) de Newell.

    QUÉ MUESTRA ESTE GRÁFICO:
        Dos curvas que suben con el tiempo:
        - Línea azul (demanda): cuántos vuelos han querido aterrizar hasta ahora.
        - Línea rosa (capacidad): cuántos vuelos ha podido aceptar el aeropuerto.
        El área sombreada entre ambas curvas = aviones en espera (cola).
        Cuanto mayor es el área, mayor es el retraso acumulado en el sistema.

        Las líneas verticales marcan los tres hitos del GDP:
        - Regulation Start: cuando comienza la restricción de capacidad (LVP).
        - Regulation End:   cuando se levanta la restricción.
        - H_NOREG:          cuando la cola desaparece y el aeropuerto se recupera.

    NOTA SOBRE LA ESCALA DEL EJE X:
        Los datos internos usan minutos desde medianoche (ej: 360 = 06:00).
        Dividimos por 60 para mostrar horas decimales en el gráfico (ej: 6.0 = 06:00).

    Args:
        timeline:     DataFrame con columnas 'minuto', 'demand_accum', 'capacity_accum'.
        params:       Parámetros del GDP con H_START y H_END.
        h_noreg:      Minuto en que la cola desaparece.
        ruta_salida:  Ruta completa del PNG de salida.
    """
    plt.figure(figsize=(12, 6))

    # Convertimos minutos a horas para el eje X (dividimos por 60)
    tiempo_en_horas = timeline['minuto'] / 60

    plt.plot(tiempo_en_horas, timeline['demand_accum'],
             label='Cumulative Demand (ETA)', color='cornflowerblue', linewidth=2)

    plt.plot(tiempo_en_horas, timeline['capacity_accum'],
             '--', label='Cumulative Service (RTA)', color='hotpink', linewidth=2)

    # fill_between() colorea el área entre las dos curvas
    plt.fill_between(
        tiempo_en_horas,
        timeline['demand_accum'],
        timeline['capacity_accum'],
        color='plum', alpha=0.5, label='Delay / Queue',
    )

    # Líneas verticales para los tres hitos del GDP
    plt.axvline(x=params['H_START'] / 60, color='palevioletred',    linestyle=':',  label='Regulation Start')
    plt.axvline(x=params['H_END']   / 60, color='mediumaquamarine', linestyle=':',  label='Regulation End')
    plt.axvline(x=h_noreg           / 60, color='midnightblue',     linestyle='-.', label='H_NOREG (queue cleared)')

    plt.title("Cumulative Flow Diagram (Newell Model)", fontsize=14, fontweight='bold')
    plt.xlabel("UTC Time (hours)", fontsize=12)
    plt.ylabel("Cumulative Number of Aircraft", fontsize=12)
    plt.legend()
    plt.grid(True, alpha=0.4)
    plt.tight_layout()
    plt.savefig(ruta_salida, dpi=300, bbox_inches='tight')
    plt.close()


# =============================================================================
# GRÁFICO 2: BALANCE DE CAPACIDAD HORARIO
# =============================================================================

def plot_balance_capacidad(
    timeline: pd.DataFrame,
    df_vuelos: pd.DataFrame,
    params: dict,
    ruta_salida: str,
) -> None:
    """
    Genera el gráfico de balance de capacidad hora a hora.

    QUÉ MUESTRA ESTE GRÁFICO:
        Para cada hora del día, tres valores:
        - Barras azules (demanda original): cuántos vuelos tenían ETA en esa hora.
        - Barras oscuras (tráfico servido): cuántos vuelos aterrizaron realmente.
        - Línea rosa (límite de capacidad): cuántos podría aceptar el aeropuerto.

        Durante el GDP (LVP activo), la línea de capacidad baja a PAAR.
        El gap entre la demanda y la capacidad = vuelos que acumulan retraso.

    CÓMO SE CALCULA EL TRÁFICO SERVIDO POR HORA:
        Tomamos la curva de capacidad acumulada del timeline y calculamos
        cuánto sube en cada hora: capacidad(h+1) - capacidad(h) = vuelos servidos esa hora.

    Args:
        timeline:    DataFrame con la curva de capacidad acumulada por minuto.
        df_vuelos:   Tabla de vuelos con la ETA de cada uno.
        params:      Parámetros del GDP (H_START, H_END, AAR, PAAR).
        ruta_salida: Ruta completa del PNG de salida.
    """
    plt.figure(figsize=(12, 6))

    # -------------------------------------------------------------------------
    # DEMANDA HORARIA: agrupar vuelos por hora de su ETA
    # // 60 es la división entera: convierte minutos a hora del día (0-23)
    # .reindex(range(24), fill_value=0) garantiza que las 24 horas aparecen
    # aunque alguna hora no tenga ningún vuelo programado.
    # -------------------------------------------------------------------------
    df_copia = df_vuelos.copy()
    df_copia['hora'] = (df_copia['minutes_eta'] // 60).astype(int)
    demanda_horaria = df_copia.groupby('hora').size().reindex(range(24), fill_value=0)

    # -------------------------------------------------------------------------
    # TRÁFICO SERVIDO: cuánto sube la capacidad acumulada en cada hora
    # -------------------------------------------------------------------------
    trafico_servido_por_hora = []
    for hora in range(24):
        minuto_inicio = hora * 60
        minuto_fin    = min((hora + 1) * 60, 1440)

        capacidad_inicio = timeline.loc[minuto_inicio, 'capacity_accum']
        # Para la última hora usamos el minuto 1439 (no existe el 1440)
        indice_fin       = minuto_fin - 1 if minuto_fin == 1440 else minuto_fin
        capacidad_fin    = timeline.loc[indice_fin, 'capacity_accum']

        trafico_servido_por_hora.append(capacidad_fin - capacidad_inicio)

    # -------------------------------------------------------------------------
    # PERFIL DE CAPACIDAD: PAAR durante el GDP, AAR fuera
    # -------------------------------------------------------------------------
    hora_inicio_gdp = int(params['H_START'] / 60)
    hora_fin_gdp    = int(params['H_END']   / 60)

    capacidad_por_hora = [
        params['PAAR'] if hora_inicio_gdp <= h < hora_fin_gdp else params['AAR']
        for h in range(24)
    ]

    horas = range(24)
    plt.bar(horas, demanda_horaria,        color='cornflowerblue', alpha=0.5, width=0.8, edgecolor='black', label='Original Demand (ETA)')
    plt.bar(horas, trafico_servido_por_hora, color='midnightblue', alpha=0.8, width=0.4, edgecolor='black', label='Actual Traffic Served')

    # plt.step() dibuja una línea escalonada (plana dentro de cada hora)
    plt.step(horas, capacidad_por_hora, where='mid', color='hotpink', linewidth=3, label='Capacity Limit')

    plt.title('Impact of LVP Regulation: Demand vs. Actual Flow', fontsize=15, fontweight='bold')
    plt.xlabel('Time of Day (UTC hour)', fontsize=12)
    plt.ylabel('Movements per Hour', fontsize=12)
    plt.xticks(horas)
    plt.legend(loc='upper left')
    plt.grid(True, axis='y', linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.savefig(ruta_salida, dpi=300, bbox_inches='tight')
    plt.close()


# =============================================================================
# GRÁFICO 3: IMPACTO ECONÓMICO — DO-NOTHING VS. GDP
# =============================================================================

def plot_impacto_economico(df_res: pd.DataFrame, ruta_salida: str) -> None:
    """
    Genera el gráfico de barras comparando el coste del escenario Do-Nothing
    (sin GDP, todo el retraso en el aire) contra el escenario con GDP.

    QUÉ MUESTRA ESTE GRÁFICO:
        Dos barras de colores:
        - Roja:  coste total si NO hubiera GDP (todo el retraso en el aire, caro).
        - Verde: coste total CON GDP (parte del retraso transferido a tierra, barato).
        La diferencia entre ambas barras = ahorro económico del GDP.

    Args:
        df_res:      Tabla de resultados del GDP con retrasos calculados.
        ruta_salida: Ruta completa del PNG de salida.
    """
    # Usamos la función centralizada de KPIs — mismos números que el Excel
    kpis = calcular_kpis_economicos(df_res)

    etiquetas = [
        'Scenario 1: Do-Nothing\n(All delay airborne)',
        'Scenario 2: GDP\n(Delay transferred to ground)',
    ]
    valores = [kpis['cost_baseline'], kpis['cost_gdp']]

    plt.figure(figsize=(10, 6))
    barras = plt.bar(
        etiquetas, valores,
        color=['crimson', 'mediumseagreen'],
        edgecolor='black', width=0.6,
    )

    plt.title("GDP Cost Savings vs. Do-Nothing Scenario", fontsize=14, fontweight='bold')
    plt.ylabel("Estimated Total Cost (EUR)", fontsize=12)

    # Añadimos un 30% de margen arriba para que las etiquetas de valor no queden cortadas
    valor_maximo = max(valores)
    plt.ylim(0, valor_maximo * 1.30)

    # Etiqueta numérica encima de cada barra
    for barra in barras:
        altura = barra.get_height()
        plt.text(
            barra.get_x() + barra.get_width() / 2,  # Centro horizontal de la barra
            altura + (valor_maximo * 0.03),           # Ligeramente por encima de la barra
            f"EUR {int(altura):,}",
            ha='center', va='bottom', fontweight='bold', fontsize=11,
        )

    plt.grid(axis='y', linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(ruta_salida, dpi=300, bbox_inches='tight')
    plt.close()


# =============================================================================
# GRÁFICO 4: EQUIDAD DEL ALGORITMO RBS POR AEROLÍNEA
# =============================================================================

def plot_equidad_aerolineas(df_res: pd.DataFrame, ruta_salida: str) -> None:
    """
    Genera el gráfico de equidad del algoritmo RBS por aerolínea (Top 10).

    QUÉ MUESTRA ESTE GRÁFICO:
        El retraso medio de cada una de las 10 aerolíneas con más vuelos.
        La línea roja horizontal es el retraso medio global.

        Si el algoritmo RBS es equitativo, las barras deberían ser similares
        entre sí y aproximarse a la línea media. Si una aerolínea tiene
        muchas más barras altas que otras, hay un sesgo de equidad.

        NOTA: Pequeñas diferencias son normales porque el RBS asigna por ETA,
        y las aerolíneas tienen distribuciones de ETA distintas.

    Args:
        df_res:      Tabla de resultados del GDP con retrasos por vuelo.
        ruta_salida: Ruta completa del PNG de salida.
    """
    # Seleccionamos solo las 10 aerolíneas con más vuelos en la ventana GDP
    top_10_aerolineas = df_res['airline'].value_counts().head(10).index
    df_top10 = df_res[df_res['airline'].isin(top_10_aerolineas)]

    # Calculamos el retraso medio por aerolínea y ordenamos de mayor a menor
    retraso_medio_por_aerolinea = (
        df_top10.groupby('airline')['total_delay']
        .mean()
        .sort_values(ascending=False)
    )

    plt.figure(figsize=(12, 6))
    plt.bar(
        retraso_medio_por_aerolinea.index,
        retraso_medio_por_aerolinea.values,
        color='mediumpurple', edgecolor='black', alpha=0.8,
    )

    # Línea de referencia: retraso medio global (sobre TODOS los vuelos, no solo Top 10)
    retraso_medio_global = df_res['total_delay'].mean()
    plt.axhline(
        y=retraso_medio_global,
        color='red', linestyle='--', linewidth=2,
        label=f"Global Average Delay ({retraso_medio_global:.1f} min)",
    )

    plt.title("RBS Equity: Mean Delay per Airline (Top 10 by Volume)", fontsize=14, fontweight='bold')
    plt.xlabel("Airline ICAO Code", fontsize=12)
    plt.ylabel("Average Delay (minutes)", fontsize=12)
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.savefig(ruta_salida, dpi=300, bbox_inches='tight')
    plt.close()


# =============================================================================
# ORQUESTADOR: GENERA LOS 4 GRÁFICOS DEL ESCENARIO BASE
# =============================================================================

def generar_graficos_fase2(
    timeline: pd.DataFrame,
    df_vuelos: pd.DataFrame,
    df_res: pd.DataFrame,
    params: dict,
    h_noreg: int,
    paths: dict,
) -> None:
    """
    Llama a los 4 gráficos del escenario base en orden.

    Esta función no tiene lógica propia — solo organiza las llamadas.
    Si necesitas añadir un gráfico nuevo, añade su función plot_X() arriba
    y llámala aquí.

    Args:
        timeline:  DataFrame con las curvas de Newell minuto a minuto.
        df_vuelos: Tabla de vuelos original (para el gráfico de demanda horaria).
        df_res:    Tabla de resultados del GDP con retrasos calculados.
        params:    Parámetros del GDP (H_START, H_END, AAR, PAAR...).
        h_noreg:   Minuto en que la cola desaparece.
        paths:     Diccionario con las rutas de salida {'cum': ..., 'bal': ...}.
    """
    # Creamos la carpeta de salida si no existe
    carpeta_figuras = os.path.dirname(paths['cum'])
    os.makedirs(carpeta_figuras, exist_ok=True)

    # Gráfico 1: Curvas acumuladas de Newell
    plot_newell(timeline, params, h_noreg, paths['cum'])

    # Gráfico 2: Balance de capacidad horario
    plot_balance_capacidad(timeline, df_vuelos, params, paths['bal'])

    # Gráficos 3 y 4: construimos sus rutas a partir de la carpeta del gráfico 1
    plot_impacto_economico(
        df_res,
        os.path.join(carpeta_figuras, '3_impacto_economico.png'),
    )
    plot_equidad_aerolineas(
        df_res,
        os.path.join(carpeta_figuras, '4_equidad_aerolineas.png'),
    )

    print("   -> 4 gráficos generados en output/figures/")


# =============================================================================
# MODO DEBUG — Ejecutar directamente para probar este módulo de forma aislada.
#   cd src/
#   python lib_visualization.py
# =============================================================================
if __name__ == "__main__":
    print("🛠️  MODO DEBUG: lib_visualization.py")

    import lib_data_prep as prep
    import lib_gdp_core  as gdp
    from config import CFG

    base       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos   = os.path.join(base, 'data', 'raw', 'LEBL_10AUG2025.csv')
    p_flota    = os.path.join(base, 'data', 'raw', 'fleet_cat_seat.csv')
    carpeta_test = os.path.join(base, 'output', 'figures', 'TEST_VISUALS')

    params = CFG.to_params_dict()

    print("   -> Cargando datos (Fase 1)...")
    df_vuelos = prep.preparar_vuelos(p_vuelos, p_flota)

    print("   -> Ejecutando simulación GDP (Fase 2)...")
    resultados = gdp.ejecutar_nucleo_gdp(df_vuelos, params)

    print("   -> Generando gráficos de prueba...")
    rutas_test = {
        'cum': os.path.join(carpeta_test, '1_newell_test.png'),
        'bal': os.path.join(carpeta_test, '2_balance_test.png'),
    }

    generar_graficos_fase2(
        timeline  = resultados['timeline'],
        df_vuelos = df_vuelos,
        df_res    = resultados['vuelos_asignados'],
        params    = params,
        h_noreg   = resultados['h_noreg'],
        paths     = rutas_test,
    )

    print(f"\n✅ Prueba superada. Gráficos guardados en: {carpeta_test}")