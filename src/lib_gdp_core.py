# =============================================================================
# src/lib_gdp_core.py
# FASE 2: Motor de simulación del Ground Delay Program (GDP).
#
# Este módulo recibe el DataFrame limpio de lib_data_prep y ejecuta toda la
# lógica del GDP: curvas de Newell, clasificación de exenciones, asignación
# de slots RBS y generación de gráficos y KPIs.
#
# Responsabilidades (cada una en su propia función):
#   1. simular_curvas_newell()  → Modelo de cola de Newell.
#   2. etiquetar_vuelos_gdp()   → Clasificar vuelos: regulados vs. exentos.
#   3. asignar_slots_rbs()      → Algoritmo Ration-By-Schedule.
#   4. calcular_delays()        → Separar retraso en aire vs. tierra.
#   5. calcular_retraso_minimo_newell()        → Calcular area curva de Newell.
#   6. calcular_kpis_economicos() → Fuente única de verdad para costes/CO2.
#   67. plot_*()                 → Un gráfico, una función.
#   8. generar_graficos()       → Orquestador de todos los plots.
#   9. exportar_auditoria_excel() → Genera el Excel final de entregable.
#   10. ejecutar_nucleo_gdp()    → Orquestador principal de todo el módulo.
# =============================================================================

import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Importamos constantes centralizadas — sin "números mágicos" en el código.
from config import (
    CFG,
    COST_AIR_MIN,
    COST_GND_MIN,
    CO2_AIR_MIN,
    CO2_GND_MIN,
)


# =============================================================================
# 1. MODELO DE NEWELL — CURVAS ACUMULADAS DE DEMANDA Y CAPACIDAD
# =============================================================================

def simular_curvas_newell(
    df_vuelos: pd.DataFrame,
    params: dict,
) -> tuple[pd.DataFrame, int]:
    """
    Genera las curvas acumuladas del modelo de Newell para el día completo.

    El modelo de Newell es una representación gráfica de colas en sistemas
    de transporte. Compara la demanda acumulada (vuelos que quieren llegar)
    con la capacidad acumulada (vuelos que el aeropuerto puede absorber).
    La diferencia entre ambas curvas en cualquier momento = tamaño de la cola.

    Args:
        df_vuelos: DataFrame con los vuelos, debe tener columna 'minutes_eta'.
        params:    Diccionario con H_START, H_END, SLOT_NOM, SLOT_RED.

    Returns:
        timeline:  DataFrame de 1440 filas (una por minuto del día) con
                   columnas demand_accum, capacity_accum y queue_size.
        h_noreg:   Minuto del día en que la cola se disuelve (fin de impacto).
    """
    h_start = params['H_START']
    h_end   = params['H_END']

    # Tasa de servicio: cuántos aviones por minuto puede aceptar el aeropuerto.
    # Es el inverso del intervalo entre slots: 1/SLOT_RED = aviones/minuto.
    r_nom = 1 / params['SLOT_NOM']  # Tasa nominal (sin LVP)
    r_red = 1 / params['SLOT_RED']  # Tasa reducida (con LVP activo)

    # Creamos un DataFrame de "timeline": una fila por cada minuto del día (0-1439)
    timeline = pd.DataFrame({'minuto': range(1440)})

    # Contamos cuántos vuelos tienen ETA en cada minuto y acumulamos el total.
    # reindex rellena con 0 los minutos sin vuelos (para no perder la serie completa).
    counts = (
        df_vuelos
        .groupby('minutes_eta')
        .size()
        .reindex(timeline['minuto'], fill_value=0)
    )
    timeline['demand_accum'] = counts.cumsum()

    # -------------------------------------------------------------------------
    # Construcción de la curva de capacidad acumulada, minuto a minuto:
    #   - Antes del GDP (t < h_start): el aeropuerto absorbe todo lo que llega.
    #   - Durante el GDP (h_start ≤ t ≤ h_end): capacidad reducida (LVP).
    #   - Después del GDP (t > h_end): capacidad nominal, hasta que la cola
    #     se disuelve (current_cap alcanza demand_accum).
    # -------------------------------------------------------------------------
    cap_accum = []
    current_cap = 0.0

    for t in timeline['minuto']:
        dem_t = timeline.loc[t, 'demand_accum']

        if t < h_start:
            # Pre-GDP: sin restricciones, la capacidad iguala la demanda.
            current_cap = dem_t
        elif h_start <= t <= h_end:
            # Durante GDP: incremento constante a tasa reducida.
            current_cap += r_red
        else:
            # Post-GDP: recuperamos a tasa nominal, pero no superamos la demanda.
            current_cap += r_nom if current_cap < dem_t else 0

        # La capacidad acumulada nunca puede superar la demanda acumulada real.
        cap_accum.append(min(current_cap, dem_t))

    timeline['capacity_accum'] = cap_accum

    # Cola en cada minuto = diferencia entre lo que quiere llegar y lo que puede.
    # .clip(lower=0) evita valores negativos por redondeo.
    timeline['queue_size'] = (
        timeline['demand_accum'] - timeline['capacity_accum']
    ).clip(lower=0)

    # -------------------------------------------------------------------------
    # H_NOREG: el minuto en que la cola se disuelve.
    # Buscamos el primer minuto DESPUÉS del GDP donde queue_size < 0.5 aviones.
    # Si la cola no se disuelve nunca, usamos el final del día (1440).
    # -------------------------------------------------------------------------
    try:
        h_noreg = int(
            timeline[
                (timeline['minuto'] > h_end) & (timeline['queue_size'] < 0.5)
            ]['minuto'].iloc[0]
        )
    except IndexError:
        # IndexError ocurre si la lista filtrada está vacía (cola no se disuelve).
        h_noreg = 1440

    return timeline, h_noreg


# =============================================================================
# 2. ETIQUETADO DE VUELOS — ¿REGULADO O EXENTO?
# =============================================================================

def etiquetar_vuelos_gdp(
    df_vuelos: pd.DataFrame,
    h_start: int,
    radius_km: int = CFG.GDP_RADIUS_KM,
) -> pd.DataFrame:
    """
    Clasifica cada vuelo en una de estas categorías:
        - GPD CANDIDATE:       Vuelo regulable (ECAC, no airborne, dentro del radio).
        - EXEMPT INTERNATIONAL: Vuelo de fuera del espacio ECAC.
        - EXEMPT AIRBORNE:     Vuelo ya en el aire cuando se activa el GDP.
        - EXEMPT DISTANCE:     Vuelo demasiado lejos para ser regulado.

    La lógica de prioridad importa: un vuelo intercontinental NO se marca
    como "airborne" aunque ya haya despegado; se marca como "international".

    Args:
        df_vuelos: DataFrame con flags is_ecac, minutes_etd, distancia_km.
        h_start:   Minuto de inicio del GDP (desde config.py: CFG.H_START).
        radius_km: Radio máximo de cobertura del GDP en kilómetros.

    Returns:
        Copia del DataFrame con columnas nuevas:
        is_departed, is_inside_radius, is_gpd_candidate, flight_status.
    """
    df = df_vuelos.copy()

    # Minuto de "congelación": si un vuelo despegó antes de este momento,
    # ya está volando y no puede recibir un CTOT (clearance to take-off time).
    # H_FREEZE_OFFSET viene de config.py (valor estándar: 150 min).
    h_freeze = h_start - CFG.H_FREEZE_OFFSET

    # Flag 1: ¿El vuelo ya ha despegado antes de la ventana de congelación?
    df['is_departed'] = df['minutes_etd'] < h_freeze

    # Flag 2: ¿Está el aeropuerto de origen dentro del radio de cobertura?
    df['is_inside_radius'] = df['distancia_km'] <= radius_km

    # Un vuelo es candidato SOLO si cumple las 3 condiciones:
    df['is_gpd_candidate'] = (
        df['is_ecac']           # 1. Origen en espacio ECAC
        & ~df['is_departed']    # 2. Aún en tierra cuando se activa el GDP
        & df['is_inside_radius']# 3. Dentro del radio de cobertura
    )

    # np.select evalúa las condiciones en orden; la primera que sea True gana.
    # 'default' captura cualquier caso no previsto (debería ser imposible aquí).
    conds = [
        df['is_gpd_candidate'],
        ~df['is_ecac'],
        df['is_departed'],
        ~df['is_inside_radius'],
    ]
    labels = [
        'GPD CANDIDATE',
        'EXEMPT INTERNATIONAL',
        'EXEMPT AIRBORNE',
        'EXEMPT DISTANCE',
    ]
    df['flight_status'] = np.select(conds, labels, default='UNKNOWN')

    return df


# =============================================================================
# 3. ASIGNACIÓN DE SLOTS — ALGORITMO RBS (Ration-By-Schedule)
# =============================================================================

def asignar_slots_rbs(
    df_regulados: pd.DataFrame,
    df_slots: pd.DataFrame,
) -> pd.DataFrame:
    """
    Implementa el algoritmo RBS (Ration-By-Schedule) de Eurocontrol.

    Lógica:
        - Primero se asignan slots a los vuelos EXENTOS (tienen preferencia
          porque ya no pueden cambiar su hora de llegada).
        - Luego se asignan los slots restantes a los vuelos CANDIDATOS GDP,
          que pueden ser retrasados en tierra para ajustarse.
        - Dentro de cada grupo, el orden es por ETA (primero en llegar,
          primero en ser servido → FIFO, que es la base del RBS).

    Args:
        df_regulados: DataFrame con los vuelos en ventana GDP y su flight_status.
        df_slots:     DataFrame con todos los slots disponibles y si están ocupados.

    Returns:
        Copia del df_regulados con la columna 'assigned_slot' rellena.
    """
    df = df_regulados.copy()
    df['assigned_slot'] = np.nan  # Inicializamos como sin asignar

    # Procesamos primero los exentos (group_gdp=False) y luego los candidatos.
    # Esto garantiza que los vuelos que no pueden cambiar de hora tengan
    # prioridad sobre los que sí pueden ser retrasados.
    for group_gdp in [False, True]:
        if group_gdp:
            mask = df['flight_status'] == 'GPD CANDIDATE'
        else:
            mask = df['flight_status'] != 'GPD CANDIDATE'

        # Iteramos en orden de ETA (el más temprano primero = FIFO)
        for idx, flight in df[mask].sort_values('minutes_eta').iterrows():
            # Buscamos el primer slot disponible a partir de la ETA del vuelo
            available_slots = df_slots[
                (df_slots['slot_start_min'] >= flight['minutes_eta'])
                & (~df_slots['occupied'])
            ]

            if not available_slots.empty:
                slot_idx = available_slots.index[0]

                # Marcamos el slot como ocupado y lo vinculamos al vuelo
                df_slots.at[slot_idx, 'occupied'] = True
                df_slots.at[slot_idx, 'flight_id'] = idx

                # Asignamos la hora del slot al vuelo
                df.at[idx, 'assigned_slot'] = df_slots.at[slot_idx, 'slot_start_min']

    return df


# =============================================================================
# 4. CÁLCULO DE RETRASOS — AIRE VS. TIERRA Y RETRASO MÍNIMO NEWELL
# =============================================================================

def calcular_delays(df_res: pd.DataFrame) -> pd.DataFrame:
    """
    Descompone el retraso total de cada vuelo en dos componentes:
        - air_delay:    Retraso absorbido en el AIRE (vuelos exentos del GDP).
                        Estos aviones llegan tarde porque no pudieron ser regulados.
        - ground_delay: Retraso absorbido en TIERRA (vuelos candidatos GDP).
                        Estos aviones esperan en origen antes de despegar.

    La suma air_delay + ground_delay = total_delay siempre.

    Args:
        df_res: DataFrame con 'assigned_slot', 'minutes_eta' y 'flight_status'.

    Returns:
        El mismo DataFrame con 3 columnas nuevas: total_delay, air_delay, ground_delay.
    """
    df = df_res.copy()

    # Retraso total = diferencia entre el slot asignado y la ETA original.
    # .clip(lower=0) evita retrasos negativos (si un vuelo llega antes de su ETA).
    df['total_delay'] = (df['assigned_slot'] - df['minutes_eta']).clip(lower=0)

    # Los vuelos EXENTOS absorben su retraso en el aire (no tenemos control).
    # Los vuelos CANDIDATOS absorben su retraso en tierra (con GDP aplicado).
    es_candidato = df['flight_status'] == 'GPD CANDIDATE'
    df['air_delay']    = np.where(~es_candidato, df['total_delay'], 0)
    df['ground_delay'] = np.where( es_candidato, df['total_delay'], 0)

    return df

def calcular_retraso_minimo_newell(timeline: pd.DataFrame) -> float:
    """
    Retraso mínimo teórico impuesto por la restricción de capacidad.
    Es el área entre la curva de demanda y la curva de capacidad
    en el diagrama de Newell. Representa el mínimo inevitable
    independientemente del algoritmo de asignación usado.
    """
    return (timeline['demand_accum'] - timeline['capacity_accum']).clip(lower=0).sum()

# =============================================================================
# 5. KPIs ECONÓMICOS Y AMBIENTALES — FUENTE ÚNICA DE VERDAD
# =============================================================================

def calcular_kpis_economicos(df_res: pd.DataFrame) -> dict:
    """
    Calcula todos los KPIs de coste y CO2 en un único lugar.

    ¿Por qué una función separada?
        Antes, estos cálculos estaban duplicados en generar_graficos() y en
        exportar_auditoria_excel(). Si cambiabas COST_AIR_MIN en config.py,
        el gráfico y el Excel podían mostrar valores distintos. Ahora ambos
        llaman a esta misma función y siempre son coherentes.

    Lógica:
        Escenario "Do-Nothing": Si no hubiera GDP, TODO el retraso ocurriría
        en el aire (el más caro). Usamos el retraso total × COST_AIR_MIN.

        Escenario "GDP": El retraso se separa. Los candidatos esperan en tierra
        (más barato). Solo los exentos acumulan retraso en el aire.

    Args:
        df_res: DataFrame con columnas total_delay, air_delay, ground_delay.

    Returns:
        Diccionario con 6 métricas: cost_baseline, cost_gdp, cost_savings,
        co2_baseline, co2_gdp, co2_savings.
    """
    r_total  = df_res['total_delay'].sum()
    r_aire   = df_res['air_delay'].sum()
    r_tierra = df_res['ground_delay'].sum()

    cost_baseline = r_total  * COST_AIR_MIN
    cost_gdp      = r_aire   * COST_AIR_MIN + r_tierra * COST_GND_MIN

    co2_baseline  = r_total  * CO2_AIR_MIN
    co2_gdp       = r_aire   * CO2_AIR_MIN  + r_tierra * CO2_GND_MIN

    return {
        'cost_baseline': round(cost_baseline, 2),
        'cost_gdp':      round(cost_gdp, 2),
        'cost_savings':  round(cost_baseline - cost_gdp, 2),
        'co2_baseline':  round(co2_baseline, 2),
        'co2_gdp':       round(co2_gdp, 2),
        'co2_savings':   round(co2_baseline - co2_gdp, 2),
    }


# =============================================================================
# 6. GRÁFICOS — UN PLOT, UNA FUNCIÓN
# =============================================================================

def plot_newell(
    timeline: pd.DataFrame,
    params: dict,
    h_noreg: int,
    path: str,
) -> None:
    """
    Gráfico 1: Diagrama de flujo acumulado (Modelo de Newell).

    Muestra la demanda acumulada vs. la capacidad acumulada a lo largo del día.
    El área entre ambas curvas representa la cola de vuelos retrasados.
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

    Compara la demanda original (barras azules) con el tráfico realmente
    servido (barras oscuras) y la capacidad declarada (línea rosa).
    Permite ver visualmente las horas en las que el aeropuerto está saturado.
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

    Visualiza el ahorro económico que genera el GDP al transferir retraso
    del aire (caro) a tierra (barato). Usa calcular_kpis_economicos()
    para garantizar coherencia con el Excel.
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

    El RBS debería distribuir el retraso equitativamente entre aerolíneas.
    Si una aerolínea tiene un retraso medio muy superior a la media global
    (línea roja), podría indicar un problema de equidad en la asignación.
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


def generar_graficos(
    timeline: pd.DataFrame,
    df_vuelos: pd.DataFrame,
    df_res: pd.DataFrame,
    params: dict,
    h_noreg: int,
    paths: dict,
) -> None:
    """
    Orquestador de gráficos: llama a cada función de plot de forma independiente.

    Al tener cada gráfico en su propia función, si uno falla (ej: datos
    insuficientes para el gráfico de equidad), los demás se siguen generando.

    Args:
        paths: Diccionario con las rutas de salida. Debe tener la clave 'cum'
               (directorio base donde se construyen las demás rutas).
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
# 8. ORQUESTADOR PRINCIPAL DEL MÓDULO
# =============================================================================

def ejecutar_nucleo_gdp(
    df_vuelos: pd.DataFrame,
    params: dict,
    output_paths: dict,
) -> dict:
    """
    Orquestador de la Fase 2: llama a todas las funciones en el orden correcto.

    Flujo:
        1. Simula las curvas de Newell para obtener el timeline y h_noreg.
        2. Etiqueta cada vuelo: candidato GDP o exento (y de qué tipo).
        3. Genera la matriz de slots según la capacidad del GDP.
        4. Asigna slots a los vuelos usando el algoritmo RBS.
        5. Calcula los retrasos desglosados (aire vs. tierra).
        6. Genera los 4 gráficos de salida.

    Args:
        df_vuelos:    DataFrame limpio de la Fase 1.
        params:       Diccionario de parámetros del escenario GDP.
        output_paths: Rutas de los archivos de imagen de salida.

    Returns:
        Diccionario con todos los resultados para que mine_lib.py
        pueda acceder a ellos y generar los entregables finales.
    """
    # PASO 1: Curvas de Newell
    timeline, h_noreg = simular_curvas_newell(df_vuelos, params)

    # PASO 2: Etiquetado de vuelos
    df_v = etiquetar_vuelos_gdp(df_vuelos, params['H_START'])

    # PASO 3: Generación de la matriz de slots
    # Empezamos en H_START y añadimos slots según el tipo de capacidad activa.
    # Paramos cuando la cola se disuelve (h_noreg) o llegamos al final del día.
    slots_list = []
    t = params['H_START']
    while t < min(h_noreg + 1000, 1440):
        slots_list.append(round(t, 4))
        t += params['SLOT_RED'] if t < params['H_END'] else params['SLOT_NOM']

    df_slots = pd.DataFrame({
        'slot_start_min': slots_list,
        'occupied':       False,
        'flight_id':      None,
    })

    # PASO 4: Asignación RBS
    # Solo procesamos vuelos dentro de la ventana GDP (ETA ≥ H_START)
    df_en_ventana = df_v[df_v['minutes_eta'] >= params['H_START']].copy()
    df_res = asignar_slots_rbs(df_en_ventana, df_slots)

    # PASO 5: Cálculo de retrasos
    df_res = calcular_delays(df_res)

    # PASO 6: Gráficos
    generar_graficos(timeline, df_vuelos, df_res, params, h_noreg, output_paths)

    return {
        'vuelos_asignados': df_res,
        'vuelos_crudos':    df_vuelos,
        'slots':            df_slots,
        'timeline':         timeline,
        'h_noreg':          h_noreg,
        'params':           params,
    }


# =============================================================================
# MODO DEBUG — Ejecutar directamente para probar este módulo de forma aislada.
#   python lib_gdp_core.py
# =============================================================================
if __name__ == "__main__":
    print("🛠️  MODO DEBUG: Probando lib_gdp_core.py de forma independiente...")
    import lib_data_prep as prep

    base       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p_vuelos   = os.path.join(base, 'data/raw/LEBL_10AUG2025.csv')
    p_flota    = os.path.join(base, 'data/raw/fleet_cat_seat.csv')
    p_debug    = os.path.join(base, 'debug/DEBUG_02_etiquetado_gdp.xlsx')

    params    = {'H_START': CFG.H_START, 'H_END': CFG.H_END,
                 'SLOT_NOM': CFG.SLOT_NOM, 'SLOT_RED': CFG.SLOT_RED,
                 'AAR': CFG.AAR, 'PAAR': CFG.PAAR}
    df_vuelos = prep.preparar_vuelos(p_vuelos, p_flota)
    df_etiq   = etiquetar_vuelos_gdp(df_vuelos, CFG.H_START)

    os.makedirs(os.path.dirname(p_debug), exist_ok=True)
    cols_debug = ['ARCID', 'airline', 'ADEP', 'is_ecac', 'distancia_km', 'is_departed', 'flight_status']
    df_etiq[cols_debug].to_excel(p_debug, index=False)

    print(f"✅ Excel de etiquetado generado en: {p_debug}")
    print("   → Ábrelo para verificar que los filtros ECAC, distancia y Airborne son correctos.")
