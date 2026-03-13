# =============================================================================
# src/lib_sensitivity.py
# ANÁLISIS DE SENSIBILIDAD — Efecto de R (radio) y HFile (ventana de congelación)
# sobre los KPIs del GDP.
# =============================================================================

import os
import warnings
import numpy as np
import pandas as pd
import lib_visualization as vis


from config import CFG
from lib_gdp_core import (
    asignar_slots_rbs,
    calcular_delays,
    calcular_kpis_economicos,
    etiquetar_vuelos_gdp,
    simular_curvas_newell,
)

# =============================================================================
# CUADRÍCULA DE PARÁMETROS
# =============================================================================
RADIOS_KM  = [500, 1000, 1500, 2000, 2500, 3000]
HFILE_MINS = [30, 60, 90, 120, 150, 180, 210]

# =============================================================================
# MOTOR LIGERO 
# =============================================================================
def _simular_gdp_ligero(df_vuelos: pd.DataFrame, params: dict, radius_km: int, h_freeze_offset: int) -> dict:
    params_local = {**params, 'H_FREEZE_OFFSET': h_freeze_offset}
    timeline, h_noreg = simular_curvas_newell(df_vuelos, params_local)

    df_v = etiquetar_vuelos_gdp(
        df_vuelos,
        h_start=params_local['H_START'],
        radius_km=radius_km,
        h_freeze_offset=h_freeze_offset,
    )

    slots_list = []
    t = params_local['H_START']
    while t < min(h_noreg + 1000, 1440):
        slots_list.append(round(t, 4))
        t += params_local['SLOT_RED'] if t < params_local['H_END'] else params_local['SLOT_NOM']
    
    df_slots = pd.DataFrame({
        'slot_start_min': slots_list,
        'occupied':       False,
        'flight_id':      None,
    })

    df_en_ventana = df_v[df_v['minutes_eta'] >= params_local['H_START']].copy()
    df_res = asignar_slots_rbs(df_en_ventana, df_slots)
    df_res = calcular_delays(df_res)
    kpis = calcular_kpis_economicos(df_res)

    # Retraso irrecuperable: retraso de vuelos que ya estaban airborne en el momento de avisar (HFile)
    unrecoverable = float(df_res[df_res['flight_status'] == 'EXEMPT AIRBORNE']['total_delay'].sum())

    # Solo devolvemos los KPIs necesarios para la rúbrica del WP3, optimizando memoria
    return {
        'radius_km':           radius_km,
        'h_freeze_offset':     h_freeze_offset,
        'air_delay_total':     float(df_res['air_delay'].sum()),
        'unrecoverable_delay': unrecoverable,
        'cost_savings':        kpis['cost_savings'],
        'co2_savings':         kpis['co2_savings'],
        'co2_aire_delay':      kpis['co2_aire_delay'],
        'co2_tierra_delay':    kpis['co2_tierra_delay'],
    }

# =============================================================================
# GENERACIÓN DE HEATMAPS (ADAPTADO A LA RÚBRICA DEL PROYECTO)
# =============================================================================
HEATMAPS = [
    # 1. Los exigidos explícitamente en la diapositiva:
    ('air_delay_total',     'Trade-off: Total AIR Delay',                   'min', 'min'),
    ('co2_tierra_delay',    'Emisiones CO₂ Emisions Due to GROUND Delay',   'kg',  'min'),
    ('co2_aire_delay',      'CO₂ Emisions Due to AIR Delay',                'kg',  'min'),
    ('unrecoverable_delay', 'Irrecoverable Delay (Cancelled GDP)',          'min', 'min'),
    
    # 2. Los "otros KPIs de interés" (Aportación de valor del alumno):
    ('co2_savings',         'Net CO₂ Savingso',                             'kg',  'max'),
    ('cost_savings',        'Total Economic Savings',                       'EUR', 'max'),
]

# =============================================================================
# FUNCIÓN PRINCIPAL — ORQUESTADOR
# =============================================================================
def ejecutar_analisis_sensibilidad(df_vuelos: pd.DataFrame, params: dict, base_dir: str) -> pd.DataFrame:
    dir_figuras = os.path.join(base_dir, 'output', 'figures', 'heatmaps')
    total = len(RADIOS_KM) * len(HFILE_MINS)

    print(f"\n[SENSIBILIDAD] Ejecutando cuadrícula {len(RADIOS_KM)}×{len(HFILE_MINS)} = {total} simulaciones...")

    resultados = []
    for i, r in enumerate(RADIOS_KM):
        for j, hf in enumerate(HFILE_MINS):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = _simular_gdp_ligero(df_vuelos, params, r, hf)
            resultados.append(res)
            n = i * len(HFILE_MINS) + j + 1
            print(f"   [{n:02d}/{total}] R={r:4d} km  HFile={hf:3d} min  → air_delay={res['air_delay_total']:.0f} min", end='\r')

    print()
    df_grid = pd.DataFrame(resultados)

    print(f"   Generando {len(HEATMAPS)} heatmaps...")
    optimos = {}

    for kpi_col, titulo, unidad, mejor in HEATMAPS:
        # IMPORTANTE: Seaborn necesita que los datos estén pivoteados (Matriz 2D real)
        df_pivot = df_grid.pivot(index='h_freeze_offset', columns='radius_km', values=kpi_col)

        flat_vals = df_pivot.values.astype(float)
        if mejor == 'min':
            opt_idx = np.unravel_index(np.argmin(flat_vals), flat_vals.shape)
        else:
            opt_idx = np.unravel_index(np.argmax(flat_vals), flat_vals.shape)

        opt_r    = df_pivot.columns[opt_idx[1]]
        opt_hf   = df_pivot.index[opt_idx[0]]
        opt_val  = flat_vals[opt_idx]
        optimos[kpi_col] = (opt_r, opt_hf, opt_val, unidad)

        nombre_archivo = kpi_col.replace('_', '-')
        path_png = os.path.join(dir_figuras, f"heatmap_{nombre_archivo}.png")

        vis.generar_heatmap(df_pivot, titulo, unidad, mejor, path_png, int(opt_idx[0]), int(opt_idx[1]))

    path_csv = os.path.join(base_dir, 'data', 'processed', 'sensitivity_grid.csv')
    os.makedirs(os.path.dirname(path_csv), exist_ok=True)
    df_grid.to_csv(path_csv, index=False)
    
    return df_grid

if __name__ == "__main__":
    import lib_data_prep as prep
    print("🛠️  MODO DEBUG: lib_sensitivity.py")
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params = {'H_START': CFG.H_START, 'H_END': CFG.H_END, 'AAR': CFG.AAR, 'PAAR': CFG.PAAR, 'SLOT_NOM': CFG.SLOT_NOM, 'SLOT_RED': CFG.SLOT_RED}
    df_vuelos = prep.preparar_vuelos(os.path.join(base, 'data/raw/LEBL_10AUG2025.csv'), os.path.join(base, 'data/raw/fleet_cat_seat.csv'))
    ejecutar_analisis_sensibilidad(df_vuelos, params, base)