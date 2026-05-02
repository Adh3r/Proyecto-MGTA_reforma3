# =============================================================================
# src/generar_graficos_wp4.py
# Generador de gráficos vectoriales (SVG) para el reporte del WP4
# Dinamizado con pandas para leer directamente de los CSV
# =============================================================================

import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Configuración global de estilo para un acabado profesional
plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Arial', 'Helvetica', 'DejaVu Sans'],
    'font.size': 11,
    'axes.titlesize': 14,
    'axes.labelsize': 12,
    'axes.grid': True,
    'grid.alpha': 0.3,
    'grid.linestyle': '--',
    'legend.fontsize': 11,
    'legend.frameon': True,
    'legend.edgecolor': 'gray',
    'figure.autolayout': True
})

def generar_grafica_1_d2d(output_dir, csv_modal_path):
    """
    Gráfica 1: Comparativa D2D dinámica.
    Selecciona automáticamente 3 vuelos representativos (Min, Med, Max retraso).
    """
    df = pd.read_csv(csv_modal_path)
    
    # Ordenar por retraso para coger representativos
    df_sorted = df.sort_values(by='retraso_ATFM_min').reset_index(drop=True)
    
    # Coger índice mínimo, medio y máximo
    idx_min = 0
    idx_med = len(df_sorted) // 2
    idx_max = len(df_sorted) - 1
    
    vuelos_sel = [df_sorted.iloc[idx_min], df_sorted.iloc[idx_med], df_sorted.iloc[idx_max]]
    
    etiquetas = [
        f"{vuelos_sel[0]['ARCID']}\n(Low Delay)", 
        f"{vuelos_sel[1]['ARCID']}\n(Medium Delay)", 
        f"{vuelos_sel[2]['ARCID']}\n(Severe Delay)"
    ]
    
    nominal_air = np.array([v['tiempo_d2d_avion_NOMINAL_min'] for v in vuelos_sel])
    retraso_atfm = np.array([v['retraso_ATFM_min'] for v in vuelos_sel])
    tiempo_tren = np.array([v['tiempo_d2d_tren_min'] for v in vuelos_sel])
    
    fig, ax = plt.subplots(figsize=(8, 5.5))
    x = np.arange(len(etiquetas))
    width = 0.35
    
    # Barras de Avión (Apiladas)
    ax.bar(x - width/2, nominal_air, width, label='Air D2D (Nominal)', color='#4A90E2', edgecolor='black', linewidth=0.7)
    ax.bar(x - width/2, retraso_atfm, width, bottom=nominal_air, label='ATFM Delay (GDP)', color='#E74C3C', edgecolor='black', linewidth=0.7, hatch='//')
    
    # Barras de Tren
    ax.bar(x + width/2, tiempo_tren, width, label='HSR D2D', color='#2ECC71', edgecolor='black', linewidth=0.7)
    
    ax.set_ylabel('Door-to-Door Time (minutes)')
    ax.set_title('Air vs. HSR Competitiveness under ATFM Regulation')
    ax.set_xticks(x)
    ax.set_xticklabels(etiquetas)
    ax.legend(loc='upper left')

    plt.savefig(os.path.join(output_dir, 'fig1_d2d_dynamic.svg'), format='svg', transparent=True)
    plt.close()

import os
import matplotlib.pyplot as plt

import os
import pandas as pd
import matplotlib.pyplot as plt

def generar_grafica_2_co2_dinamica(output_dir, csv_wp3_path, csv_wp4_path): 
    """ 
    Gráfica 2: El Efecto Multiplicador del CO2 (Donut)
    Lee dinámicamente de los CSVs de WP3 (Base) y WP4 (Intermodal).
    """ 
    # Comprobar que los archivos existen
    if not os.path.exists(csv_wp3_path) or not os.path.exists(csv_wp4_path):
        print("⚠️ Faltan los archivos CSV para generar la gráfica de CO2.")
        return

    try:
        # Cargar los CSVs y usar 'Métrica' como índice
        df_wp3 = pd.read_csv(csv_wp3_path)
        df_wp3.set_index('Métrica', inplace=True)
        
        df_wp4 = pd.read_csv(csv_wp4_path)
        df_wp4.set_index('Métrica', inplace=True)
        
        # 1. Extraer Ahorro Directo (El CO2 que dejan de emitir los aviones sustituidos por tren)
        ahorro_directo = float(df_wp4.loc['Ahorro neto CO₂ directo por Tren (kg)', 'Intermodal (Opt. Costes)'])
        
        # 2. Calcular Ahorro Indirecto (CO2 ahorrado por la reducción de la congestión/retraso)
        # Comparamos el escenario GHP (Opt. Costes) del WP3 vs Intermodal (Opt. Costes) del WP4
        co2_retraso_base = float(df_wp3.loc['Emisiones CO₂ retraso (kg)', 'GHP (Opt. Costes)'])
        co2_retraso_opt = float(df_wp4.loc['Emisiones CO₂ retraso (kg)', 'Intermodal (Opt. Costes)'])
        
        # Usamos max(0, ...) para evitar números negativos si por alguna rareza el optimizador consume más
        ahorro_indirecto = max(0, co2_retraso_base - co2_retraso_opt) 
        
        # Cálculos para el gráfico
        total_ahorro_kg = ahorro_directo + ahorro_indirecto
        total_toneladas = total_ahorro_kg / 1000
        
        # Configuración del gráfico
        fig, ax = plt.subplots(figsize=(8, 6)) 
        
        # Hemos añadido el valor en kg a las etiquetas para que sea más informativo
        labels = [f'Direct Savings\n(Modal Shift)\n{ahorro_directo:,.0f} kg', 
                  f'Systemic Savings\n(Network Relief)\n{ahorro_indirecto:,.0f} kg'] 
        sizes = [ahorro_directo, ahorro_indirecto] 
        colors = ['#27AE60', '#F39C12'] # Verde para tren, Naranja para eficiencia de red
        explode = (0, 0.05) if ahorro_indirecto > 0 else (0, 0)
        
        wedges, texts, autotexts = ax.pie( 
            sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%', 
            shadow=False, startangle=140, pctdistance=0.75, 
            wedgeprops=dict(width=0.45, edgecolor='w') 
        ) 
        
        plt.setp(autotexts, size=11, weight="bold", color="white") 
        plt.setp(texts, size=10, fontweight='bold') 
        
        # Texto central dinámico
        ax.text(0, 0, f'Total CO2 Savings:\n~{total_toneladas:.1f} Tons', 
                ha='center', va='center', fontsize=13, fontweight='bold', color='#333333') 
        
        ax.set_title('Environmental Multiplier Effect (CO2)', y=0.95, fontweight='bold', fontsize=15) 
        
        # Guardar
        output_path = os.path.join(output_dir, 'fig2_co2_leverage.svg')
        plt.savefig(output_path, format='svg', transparent=True, bbox_inches='tight') 
        plt.close()
        print(f"✅ Gráfica de CO2 generada dinámicamente en: {output_path}")
        
    except KeyError as e:
         print(f"❌ Error al generar la gráfica: No se encontró la columna o fila {e} en los CSV.")

def generar_grafica_3_queue(output_dir, csv_wp3_path, csv_wp4_path):
    """
    Gráfica 3: Queue Length Evolution dinamizada.
    Lee el escenario base del WP3 y el escenario intermodal del WP4.
    """
    # Cargar CSVs
    df_wp3 = pd.read_csv(csv_wp3_path)
    df_wp3.set_index('Métrica', inplace=True)
    
    df_wp4 = pd.read_csv(csv_wp4_path)
    df_wp4.set_index('Métrica', inplace=True)
    
    # Extraer duraciones y vuelos dinámicamente usando las columnas correctas
    # Usamos 'GDP (RBS Base)' del WP3 como escenario base
    duracion_base = float(df_wp3.loc['Duración impacto (min)', 'GDP (RBS Base)'])
    duracion_red = float(df_wp4.loc['Duración impacto (min)', 'Intermodal (Opt. Costes)'])
    ahorro_tiempo = duracion_base - duracion_red
    
    # Extraer demanda
    vuelos_base = int(float(df_wp3.loc['Demanda total (vuelos)', 'GDP (RBS Base)']))
    vuelos_red = int(float(df_wp4.loc['Demanda total (vuelos)', 'Intermodal (Opt. Costes)']))
    vuelos_diff = vuelos_base - vuelos_red
    
    fig, ax = plt.subplots(figsize=(7, 4.5))
    
    t = np.linspace(0, duracion_base + 100, 500)
    capacidad = 0.5 * t  
    
    # Curvas dinámicas
    ajuste_orig = (0.5 * duracion_base) / (0.65 * duracion_base - 0.00018 * duracion_base**2)
    demanda_original = np.where(t < duracion_base, (0.65 * t - 0.00018 * t**2) * ajuste_orig, capacidad)

    ajuste_red = (0.5 * duracion_red) / (0.63 * duracion_red - 0.00018 * duracion_red**2)
    demanda_reducida = np.where(t < duracion_red, (0.63 * t - 0.00018 * t**2) * ajuste_red, capacidad)

    cola_original = np.maximum(0, demanda_original - capacidad)
    cola_reducida = np.maximum(0, demanda_reducida - capacidad)

    ax.plot(t, cola_original, label=f'Baseline Backlog ({vuelos_base} flt)', color='#E74C3C', linewidth=2.5)
    ax.plot(t, cola_reducida, label=f'Reduced Backlog (-{vuelos_diff} flt)', color='#3498DB', linewidth=2.5)
    
    ax.fill_between(t, cola_original, alpha=0.1, color='#E74C3C')
    ax.fill_between(t, cola_reducida, alpha=0.2, color='#3498DB')
    
    ax.plot(duracion_base, 0, 'ro', markersize=6)
    ax.plot(duracion_red, 0, 'bo', markersize=6)
    
    ax.annotate(rf'$\Delta$ = {ahorro_tiempo:.0f} min earlier', 
                xy=(duracion_red, 2), xytext=(duracion_red - 120, max(cola_original)*0.15),
                arrowprops=dict(facecolor='black', arrowstyle='->', lw=1.5), 
                fontsize=10, fontweight='bold')

    ax.set_xlim(0, duracion_base + 50)
    ax.set_ylim(0, max(cola_original) * 1.2) 
    
    ax.set_xlabel('Time elapsed from regulation start (minutes)')
    ax.set_ylabel('Number of Aircraft in Queue')
    ax.set_title('Queue Dynamics: Baseline vs. HSR Substitution')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='upper right')

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'fig3_queue_evolution.svg'), format='svg', transparent=True)
    plt.close()
    print(f"✅ Gráfica de Colas (Queue) generada dinámicamente en: {os.path.join(output_dir, 'fig3_queue_evolution.svg')}")

if __name__ == "__main__":
    # Rutas de directorios y archivos
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(base_dir, 'output', 'figures', 'wp4')
    os.makedirs(out_dir, exist_ok=True)
    
    # Ajusta estas rutas si tus CSV están en otra carpeta (ej: 'data/processed')
    path_wp3_csv = os.path.join(base_dir, 'data/processed/wp3_resumen_ejecutivo.csv')
    csv_intermodal = os.path.join(base_dir, 'data', 'processed', 'wp4_comparativa_intermodal.csv')
    csv_modal = os.path.join(base_dir, 'data', 'processed', 'wp4_comparativa_modal.csv')
    
    print(f"Generando gráficos vectoriales leyendo de CSV en: {out_dir}")
    
    try:
        generar_grafica_1_d2d(out_dir, csv_modal)
        generar_grafica_2_co2_dinamica(out_dir, path_wp3_csv, csv_intermodal)
        generar_grafica_3_queue(out_dir, path_wp3_csv, csv_intermodal)
        print("✅ Gráficos SVG dinámicos generados con éxito.")
    except FileNotFoundError as e:
        print(f"❌ Error: No se encontraron los archivos CSV. Asegúrate de haber ejecutado main.py primero. Detalles: {e}")