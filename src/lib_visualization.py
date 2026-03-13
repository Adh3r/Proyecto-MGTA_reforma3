# =============================================================================
# src/lib_visualization.py
# MÓDULO DE VISUALIZACIÓN — Gráficos, diagramas y heatmaps del simulador.
# =============================================================================

import os
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np

# Necesitamos importar la función de KPIs económicos para el gráfico 3
from lib_gdp_core import calcular_kpis_economicos

# =============================================================================
# HEATMAPS (FASE 4 - SENSIBILIDAD)
# =============================================================================

import matplotlib.colors as mcolors

import matplotlib.colors as mcolors

def generar_heatmap(df_pivot: pd.DataFrame, titulo: str, unidad: str, mejor: str, path_out: str, opt_row: int, opt_col: int) -> None:
    """
    Genera un heatmap con CONTRASTE ULTRA-EXTREMO mediante BoundaryNorm y 
    alinea el recuadro 'BEST' en la parte inferior para visibilidad.
    """
    plt.figure(figsize=(12, 7))
    
    vals = df_pivot.values.flatten()
    
    # 1. CÁLCULO DE LÍMITES ROBUSTOS (Percentiles 10 y 90)
    vmin = np.nanpercentile(vals, 10)
    vmax = np.nanpercentile(vals, 90)
    
    if vmin == vmax: # Evitar error si todos los valores son iguales
        vmin, vmax = vals.min(), vals.max()

    # Definimos solo 5 "escalones" de color para máxima starkness.
    n_bins = 5
    base_cmap_name = "RdYlGn" if mejor == 'max' else "RdYlGn_r"
    cmap = plt.get_cmap(base_cmap_name)

    # PowerNorm(gamma=1.0) es lineal, pero lo forzamos a 5 colores discretos.
    # Esto asegura que diferencias pequeñas en valores normales causen cambios de color Drásticos.
    # Al usar 'bins', Seaborn aplica la paleta discreta.
    cmap = plt.get_cmap(base_cmap_name, n_bins)


    # 3. FORMATO NUMÉRICO
    fmt_str = ",.0f" if any(x in unidad for x in ["EUR", "kg", "€"]) else ".1f"

    # 4. DIBUJAR HEATMAP
    # Usamos PowerNorm(gamma=1.0) para que sea lineal pero con límites vmin/vmax
    ax = sns.heatmap(
        df_pivot, 
        annot=True, 
        fmt=fmt_str, 
        cmap=cmap, # <--- Usamos el mapa de 5 bins discretos
        vmin=vmin, 
        vmax=vmax,
        cbar_kws={'label': unidad, 'ticks': np.linspace(vmin, vmax, n_bins+1)},
        linewidths=1.5,
        linecolor='white',
        annot_kws={"size": 8, "weight": "bold"}
    )

    # Títulos y etiquetas
    ax.set_xticklabels([f"{int(c)} km" for c in df_pivot.columns])
    ax.set_yticklabels([f"{int(i)} min" for i in df_pivot.index], rotation=0)
    ax.set_xlabel('GDP Radius Exemption (R)', fontsize=11, fontweight='bold')
    ax.set_ylabel('Freeze Horizon (HFile)', fontsize=11, fontweight='bold')
    ax.set_title(f"{titulo.upper()}\n(Ultra-Contrast: 5-bins & PowerNorm)", fontsize=13, fontweight='bold', pad=20)

    # 5. SOLUCIÓN AL RECÓUADRO 'BEST'
    # Recuadro azul alrededor de la celda óptima.
    # 'opt_row + 0.1' mueve el inicio del recuadro hacia arriba.
    # 'va="bottom"' alinea el texto desde la parte inferior de la casilla.
    ax.add_patch(plt.Rectangle((opt_col, opt_row), 1, 1, fill=False, edgecolor='blue', linewidth=4, zorder=15))
    ax.text(opt_col + 0.5, opt_row + 0.9, '★ BEST', ha='center', va='bottom', 
            fontsize=10, color='blue', fontweight='bold',
            bbox=dict(facecolor='white', alpha=0.9, edgecolor='blue', boxstyle='round,pad=0.2'))

    plt.tight_layout()
    os.makedirs(os.path.dirname(path_out), exist_ok=True)
    plt.savefig(path_out, dpi=200, bbox_inches='tight')
    plt.close()

# =============================================================================
# GRÁFICOS DEL ESCENARIO BASE (FASE 2)
# =============================================================================

def plot_newell(
    timeline: pd.DataFrame,
    params: dict,
    h_noreg: int,
    path: str,
) -> None:
    """
    Gráfico 1: Diagrama de flujo acumulado (Modelo de Newell).
    """
    plt.figure(figsize=(12, 6))

    plt.plot(
        timeline['minuto'] / 60, timeline['demand_accum'],
        label='Cumulative Demand (ETA)', color='cornflowerblue', linewidth=2,
    )
    plt.plot(
        timeline['minuto'] / 60, timeline['capacity_accum'],
        '--', label='Cumulative Service (RTA)', color='hotpink', linewidth=2,
    )
    plt.fill_between(
        timeline['minuto'] / 60,
        timeline['demand_accum'], timeline['capacity_accum'],
        color='plum', alpha=0.5, label='Delay / Queue',
    )

    # Líneas verticales para marcar los hitos del GDP
    plt.axvline(x=params['H_START'] / 60, color='palevioletred',  linestyle=':', label='Regulation Start')
    plt.axvline(x=params['H_END']   / 60, color='mediumaquamarine', linestyle=':', label='Regulation End')
    plt.axvline(x=h_noreg           / 60, color='midnightblue',   linestyle='-.', label='H_NOREG (queue cleared)')

    plt.title("Cumulative Flow Diagram (Newell Model)", fontsize=14, fontweight='bold')
    plt.xlabel("UTC Time (Local BCN)", fontsize=12)
    plt.ylabel("Cumulative Number of Aircraft", fontsize=12)
    plt.legend()
    plt.grid(True, alpha=0.4)
    plt.savefig(path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_balance_capacidad(
    timeline: pd.DataFrame,
    df_vuelos: pd.DataFrame,
    params: dict,
    path: str,
) -> None:
    """
    Gráfico 2: Balance de capacidad horario (demanda vs. tráfico servido).
    """
    plt.figure(figsize=(12, 6))

    # Agrupamos vuelos por hora del día para mostrar barras horarias
    df_vuelos = df_vuelos.copy()
    df_vuelos['hour_bin'] = (df_vuelos['minutes_eta'] // 60).astype(int)
    hourly_demand = df_vuelos.groupby('hour_bin').size().reindex(range(24), fill_value=0)

    # Calculamos el throughput real hora a hora desde la curva de capacidad
    hourly_throughput = []
    for h in range(24):
        t_s = h * 60
        t_e = min((h + 1) * 60, 1440)
        v_s = timeline.loc[t_s, 'capacity_accum']
        v_e = timeline.loc[t_e - 1 if t_e == 1440 else t_e, 'capacity_accum']
        hourly_throughput.append(v_e - v_s)

    # Perfil de capacidad: PAAR durante el GDP, AAR fuera del GDP
    cap_profile = [
        params['PAAR'] if int(params['H_START'] / 60) <= h < int(params['H_END'] / 60)
        else params['AAR']
        for h in range(24)
    ]

    hours = range(24)
    # Ajustar para alinear correctamente `cap_profile` (demanda vs capacidad)
    plt.bar(hours, hourly_demand,     color='cornflowerblue', alpha=0.5, width=0.8, edgecolor='black', label='Original Demand (ETA)')
    plt.bar(hours, hourly_throughput, color='midnightblue',   alpha=0.8, width=0.4, edgecolor='black', label='Actual Traffic Served')
    plt.step(hours, cap_profile, where='mid', color='hotpink', linewidth=3, label='Capacity Limit')

    plt.title('Impact of LVP Regulation: Demand vs. Actual Flow', fontsize=15, fontweight='bold')
    plt.xlabel('Time of Day (UTC)', fontsize=12)
    plt.ylabel('Movements per Hour', fontsize=12)
    plt.xticks(hours)
    plt.legend(loc='upper left')
    plt.grid(True, axis='y', linestyle='--', alpha=0.6)
    plt.savefig(path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_impacto_economico(df_res: pd.DataFrame, path: str) -> None:
    """
    Gráfico 3: Coste total Do-Nothing vs. GDP.
    """
    kpis = calcular_kpis_economicos(df_res)  # Fuente única de verdad

    labels = [
        'Scenario 1: Do-Nothing\n(All delay airborne)',
        'Scenario 2: GDP\n(Delay transferred to ground)',
    ]
    values = [kpis['cost_baseline'], kpis['cost_gdp']]

    plt.figure(figsize=(10, 6))
    bars = plt.bar(labels, values, color=['crimson', 'mediumseagreen'], edgecolor='black', width=0.6)

    plt.title("GDP Cost Savings vs. Do-Nothing Scenario", fontsize=14, fontweight='bold')
    plt.ylabel("Estimated Total Cost (€)", fontsize=12)

    # Margen del 30% para que las etiquetas de valor no queden cortadas
    max_val = max(values)
    plt.ylim(0, max_val * 1.30)

    for bar in bars:
        yval = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            yval + (max_val * 0.03),
            f"€ {int(yval):,}",
            ha='center', va='bottom', fontweight='bold', fontsize=11,
        )

    plt.grid(axis='y', linestyle='--', alpha=0.5)
    plt.savefig(path, dpi=300, bbox_inches='tight')
    plt.close()


def plot_equidad_aerolineas(df_res: pd.DataFrame, path: str) -> None:
    """
    Gráfico 4: Equidad del algoritmo RBS por aerolínea (Top 10).
    """
    # Seleccionamos las 10 aerolíneas con más vuelos en el período
    top_airlines = df_res['airline'].value_counts().head(10).index
    df_top = df_res[df_res['airline'].isin(top_airlines)]

    equity_stats = (
        df_top.groupby('airline')['total_delay']
        .mean()
        .sort_values(ascending=False)
    )

    plt.figure(figsize=(12, 6))
    plt.bar(equity_stats.index, equity_stats.values, color='mediumpurple', edgecolor='black', alpha=0.8)

    # Línea de referencia: retraso medio global sobre todos los vuelos
    plt.axhline(
        y=df_res['total_delay'].mean(),
        color='red', linestyle='--', linewidth=2,
        label=f"Global Average Delay ({df_res['total_delay'].mean():.1f} min)",
    )

    plt.title("RBS Equity: Mean delay among top 10 airlines in LEBL", fontsize=14, fontweight='bold')
    plt.xlabel("Airline Code", fontsize=12)
    plt.ylabel("Average Delay (minutes)", fontsize=12)
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.6)
    plt.savefig(path, dpi=300, bbox_inches='tight')
    plt.close()


def generar_graficos_fase2(
    timeline: pd.DataFrame,
    df_vuelos: pd.DataFrame,
    df_res: pd.DataFrame,
    params: dict,
    h_noreg: int,
    paths: dict,
) -> None:
    """
    Orquestador de gráficos: llama a cada función de plot de forma independiente.
    """
    dir_figures = os.path.dirname(paths['cum'])
    os.makedirs(dir_figures, exist_ok=True)

    # Cada gráfico se genera de forma independiente
    plot_newell(timeline, params, h_noreg, paths['cum'])
    plot_balance_capacidad(timeline, df_vuelos, params, paths['bal'])
    plot_impacto_economico(df_res, os.path.join(dir_figures, '3_impacto_economico.png'))
    plot_equidad_aerolineas(df_res, os.path.join(dir_figures, '4_equidad_aerolineas.png'))

    print("   -> 4 gráficos generados en output/figures/")


    # =============================================================================
# BLOQUE DE PRUEBA (TESTING AISLADO)
# =============================================================================
if __name__ == "__main__":
    print("🛠️ MODO TEST: Probando lib_visualization.py de forma aislada...")
    import lib_data_prep as prep
    import lib_gdp_core as gdp
    import sys
    
    # Simular la configuración temporal para la prueba
    # (Asegúrate de que config.py está accesible)
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from config import CFG

    # 1. Configurar rutas base
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path_vuelos = os.path.join(base_dir, 'data', 'raw', 'LEBL_10AUG2025.csv')
    path_flota = os.path.join(base_dir, 'data', 'raw', 'fleet_cat_seat.csv')
    
    params = {
        'H_START': CFG.H_START, 'H_END': CFG.H_END, 
        'AAR': CFG.AAR, 'PAAR': CFG.PAAR, 
        'SLOT_NOM': CFG.SLOT_NOM, 'SLOT_RED': CFG.SLOT_RED
    }

    # 2. Fabricar los datos reales llamando a los otros módulos intactos
    print("   -> Cargando datos base (Fase 1)...")
    df_vuelos = prep.preparar_vuelos(path_vuelos, path_flota)

    print("   -> Ejecutando el núcleo GDP para obtener resultados (Fase 2)...")
    # Pasamos rutas 'dummy' con directorios válidos para que el os.makedirs no falle
    dummy_dir = os.path.join(base_dir, 'output', 'figures', 'TEST_VISUALS')
    dummy_paths = {'cum': os.path.join(dummy_dir, 'dummy_1.png'), 'bal': os.path.join(dummy_dir, 'dummy_2.png')}
    resultados = gdp.ejecutar_nucleo_gdp(df_vuelos, params, dummy_paths)

    # 3. PROBAR NUESTRO NUEVO MOTOR GRÁFICO
    print("   -> 🎨 Pasando los datos a las nuevas funciones de visualización...")
    
    # Creamos una carpeta de test para no mezclar los gráficos buenos con estos
    test_paths = {
        'cum': os.path.join(base_dir, 'output', 'figures', 'TEST_VISUALS', '1_newell_test.png'),
        'bal': os.path.join(base_dir, 'output', 'figures', 'TEST_VISUALS', '2_balance_test.png')
    }
    
    # Llamamos a nuestra nueva función orquestadora
    generar_graficos_fase2(
        timeline=resultados['timeline'],
        df_vuelos=df_vuelos,
        df_res=resultados['vuelos_asignados'],
        params=params,
        h_noreg=resultados['h_noreg'],
        paths=test_paths
    )
    
    print(f"\n✅ ¡Prueba superada! Los gráficos se han generado correctamente.")
    print(f"📁 Revisa la nueva carpeta: {os.path.dirname(test_paths['cum'])}")