# =============================================================================
# src/lib_excel_export.py
# FASE 3: Construcción y formato del Excel maestro de auditoría.
#
# Arquitectura de este módulo:
#   Cada pestaña del Excel es una función privada independiente (_sheet_*).
#   El orquestador público (exportar_auditoria_excel) las llama en orden.
#
#   Para añadir una pestaña nueva en el futuro:
#       1. Escribe una función  _sheet_mi_nueva_hoja(wb, datos...)
#       2. Llámala desde exportar_auditoria_excel()
#   Eso es todo. No hay que tocar nada más.
#
# Pestañas actuales:
#   0_Parametros_GDP    → Parámetros del escenario simulado
#   1_Datos_Crudos      → Vuelos originales sin procesar
#   2_Regulacion_GDP    → Vuelos con slot asignado y retraso
#   3_Matriz_Slots      → Todos los slots y su estado
#   5_KPIs_Comparativa  → Tabla Sin Regulación vs GDP
#   6_Analisis_Retrasos → Estadísticas y bandas CODA
#   7_Equidad_RBS       → Retraso medio por aerolínea
# =============================================================================

import os

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    PatternFill,
    Side,
)
from openpyxl.utils import get_column_letter

from config import CO2_AIR_MIN, CO2_GND_MIN, COST_AIR_MIN, COST_GND_MIN
from lib_gdp_core import calcular_kpis_economicos


# =============================================================================
# PALETA DE ESTILOS — Fuente única de verdad para el diseño visual
#
# Centralizar los colores aquí significa que si quieres cambiar el azul
# de las cabeceras, lo cambias en UN solo sitio y afecta a todas las hojas.
# =============================================================================

# Colores en formato ARGB (Alpha + RGB hex)
COLOR_CABECERA_AZUL    = "FF1F4E79"   # Azul oscuro institucional — fondo de cabeceras
COLOR_CABECERA_GRIS    = "FF404040"   # Gris oscuro — cabeceras secundarias
COLOR_SECCION          = "FF2E75B6"   # Azul medio — filas de título de bloque
COLOR_FILA_ALTERNA     = "FFD9E1F2"   # Azul muy claro — filas pares (legibilidad)
COLOR_FILA_BLANCA      = "FFFFFFFF"   # Blanco puro — filas impares
COLOR_ADVERTENCIA      = "FFFFF2CC"   # Amarillo suave — celda de nota o aviso
COLOR_POSITIVO         = "FFE2EFDA"   # Verde suave — dato favorable (ahorro, mejora)
COLOR_NEGATIVO         = "FFFCE4D6"   # Rojo suave — dato desfavorable

FUENTE_BASE            = "Arial"
TAMAÑO_NORMAL          = 10
TAMAÑO_CABECERA        = 11
TAMAÑO_TITULO_HOJA     = 13


# =============================================================================
# HELPERS DE FORMATO — Funciones reutilizables por todas las hojas
# =============================================================================

def _estilo_cabecera(color_fondo: str = COLOR_CABECERA_AZUL) -> dict:
    """Devuelve los estilos openpyxl para una fila de cabecera."""
    return {
        'font':      Font(name=FUENTE_BASE, size=TAMAÑO_CABECERA, bold=True, color="FFFFFFFF"),
        'fill':      PatternFill("solid", fgColor=color_fondo),
        'alignment': Alignment(horizontal="center", vertical="center", wrap_text=True),
        'border':    _borde_fino(),
    }


def _estilo_seccion() -> dict:
    """Estilo para las filas que actúan como separadores de bloque (─── TÍTULO ───)."""
    return {
        'font':      Font(name=FUENTE_BASE, size=TAMAÑO_NORMAL, bold=True, color="FFFFFFFF"),
        'fill':      PatternFill("solid", fgColor=COLOR_SECCION),
        'alignment': Alignment(horizontal="left", vertical="center"),
    }


def _estilo_dato(fila_par: bool = False) -> dict:
    """Estilo para celdas de datos normales, con color alterno por fila."""
    color = COLOR_FILA_ALTERNA if fila_par else COLOR_FILA_BLANCA
    return {
        'font':      Font(name=FUENTE_BASE, size=TAMAÑO_NORMAL),
        'fill':      PatternFill("solid", fgColor=color),
        'alignment': Alignment(horizontal="left", vertical="center", wrap_text=False),
        'border':    _borde_fino(),
    }


def _borde_fino() -> Border:
    """Borde gris fino para todas las celdas de datos."""
    lado = Side(style="thin", color="FFD0D0D0")
    return Border(left=lado, right=lado, top=lado, bottom=lado)


def _aplicar_estilos_fila(ws, fila_idx: int, n_cols: int, estilos: dict) -> None:
    """Aplica un diccionario de estilos a todas las celdas de una fila."""
    for col_idx in range(1, n_cols + 1):
        celda = ws.cell(row=fila_idx, column=col_idx)
        if 'font'      in estilos: celda.font      = estilos['font']
        if 'fill'      in estilos: celda.fill      = estilos['fill']
        if 'alignment' in estilos: celda.alignment = estilos['alignment']
        if 'border'    in estilos: celda.border    = estilos['border']


def _autoajustar_columnas(ws, ancho_minimo: int = 12, ancho_maximo: int = 55) -> None:
    """
    Ajusta el ancho de cada columna al contenido más largo que contiene.

    openpyxl no tiene autofit nativo, así que iteramos todas las celdas,
    medimos la longitud del texto y asignamos un ancho proporcional.

    Args:
        ancho_minimo: Ancho mínimo en caracteres (evita columnas demasiado estrechas).
        ancho_maximo: Ancho máximo en caracteres (evita columnas kilométricas).
    """
    for col_cells in ws.columns:
        max_len = 0
        col_letra = get_column_letter(col_cells[0].column)
        for celda in col_cells:
            if celda.value is not None:
                # Consideramos saltos de línea: tomamos la línea más larga
                lineas = str(celda.value).split('\n')
                largo = max(len(l) for l in lineas)
                max_len = max(max_len, largo)
        # Factor 1.15 de margen visual + 2 de padding interno de Excel
        ancho_calculado = min(ancho_maximo, max(ancho_minimo, max_len * 1.15 + 2))
        ws.column_dimensions[col_letra].width = ancho_calculado


def _escribir_dataframe_con_formato(ws, df: pd.DataFrame, fila_inicio: int = 1) -> int:
    """
    Escribe un DataFrame en la hoja con cabecera formateada y filas alternas.

    Detecta automáticamente si una fila es un "separador de bloque":
    aquellas cuyo primer valor empieza por '──' se pintan con color de sección.

    Args:
        ws:          Hoja de openpyxl donde escribir.
        df:          DataFrame a escribir.
        fila_inicio: Fila de Excel donde empieza la cabecera (1-indexed).

    Returns:
        Índice de la última fila escrita.
    """
    n_cols = len(df.columns)

    # --- Cabecera ---
    for col_idx, nombre_col in enumerate(df.columns, start=1):
        celda = ws.cell(row=fila_inicio, column=col_idx, value=nombre_col)
        estilos = _estilo_cabecera()
        celda.font      = estilos['font']
        celda.fill      = estilos['fill']
        celda.alignment = estilos['alignment']
        celda.border    = estilos['border']
    ws.row_dimensions[fila_inicio].height = 30

    # --- Datos ---
    contador_filas_dato = 0  # Para el color alterno (no cuenta separadores)
    fila_actual = fila_inicio + 1

    for _, row in df.iterrows():
        valores = list(row)
        primer_valor = str(valores[0]) if valores[0] is not None else ''

        # ¿Es una fila separadora de bloque?
        es_separador = primer_valor.startswith('──')

        if es_separador:
            estilos = _estilo_seccion()
        else:
            contador_filas_dato += 1
            estilos = _estilo_dato(fila_par=(contador_filas_dato % 2 == 0))

        for col_idx, valor in enumerate(valores, start=1):
            # Las filas separadoras solo muestran texto en la primera columna
            contenido = valor if (not es_separador or col_idx == 1) else ''
            celda = ws.cell(row=fila_actual, column=col_idx, value=contenido)
            if 'font'      in estilos: celda.font      = estilos['font']
            if 'fill'      in estilos: celda.fill      = estilos['fill']
            if 'alignment' in estilos: celda.alignment = estilos['alignment']
            if 'border'    in estilos and not es_separador:
                celda.border = estilos['border']

        ws.row_dimensions[fila_actual].height = 18
        fila_actual += 1

    return fila_actual - 1


def _congelar_primera_fila(ws) -> None:
    """Congela la fila de cabecera para que sea siempre visible al hacer scroll."""
    ws.freeze_panes = ws['A2']


# =============================================================================
# FUNCIONES DE PESTAÑA — Una función, una hoja
# =============================================================================

def _sheet_parametros(wb, params: dict, h_noreg: int) -> None:
    """Pestaña 0: Parámetros operacionales del escenario simulado."""

    def min_a_hhmm(m: float) -> str:
        return f"{int(m)//60:02d}:{int(m)%60:02d} UTC"

    dur_reg   = params['H_END'] - params['H_START']
    dur_total = h_noreg - params['H_START']
    reduccion = round((1 - params['PAAR'] / params['AAR']) * 100, 1)

    df = pd.DataFrame({
        'Parámetro': [
            '── AEROPUERTO ──────────────────────────────',
            'Aeropuerto Destino',
            'Tipo de Regulación',
            '── CAPACIDAD ───────────────────────────────',
            'AAR — Tasa de Llegada Nominal',
            'PAAR — Tasa de Llegada Reducida (LVP)',
            'Reducción de Capacidad',
            'Tamaño de Slot Nominal',
            'Tamaño de Slot Reducido (GDP)',
            '── VENTANA TEMPORAL ────────────────────────',
            'Inicio de Regulación (H_START)',
            'Fin de Regulación (H_END)',
            'Duración de la Regulación',
            'Fin del Impacto — Cola Disuelta (H_NOREG)',
            'Duración Total del Impacto',
            'Ventana de Congelación CTOT',
            '── COBERTURA ───────────────────────────────',
            'Radio de Cobertura GDP',
            'Espacio Aéreo Regulado',
            '── PARÁMETROS ECONÓMICOS ───────────────────',
            'Coste por minuto en el AIRE',
            'Coste por minuto en TIERRA',
            'Emisiones CO₂ por minuto en el AIRE',
            'Emisiones CO₂ por minuto en TIERRA',
        ],
        'Valor': [
            '',
            'LEBL — Barcelona El Prat',
            'LVP (Low Visibility Procedures)',
            '',
            f"{params['AAR']} llegadas/hora",
            f"{params['PAAR']} llegadas/hora",
            f"{reduccion} %",
            f"{round(params['SLOT_NOM'], 2)} min/avión  ({round(60/params['SLOT_NOM'])} aviones/hora)",
            f"{round(params['SLOT_RED'], 2)} min/avión  ({round(60/params['SLOT_RED'])} aviones/hora)",
            '',
            min_a_hhmm(params['H_START']),
            min_a_hhmm(params['H_END']),
            f"{dur_reg} min  ({dur_reg//60}h {dur_reg%60}min)",
            min_a_hhmm(h_noreg),
            f"{dur_total} min desde inicio  ({dur_total//60}h {dur_total%60}min)",
            f"{params.get('H_FREEZE_OFFSET', 150)} min antes de H_START",
            '',
            '3.000 km desde LEBL',
            'ECAC (European Civil Aviation Conference)',
            '',
            f"€ {COST_AIR_MIN} / minuto",
            f"€ {COST_GND_MIN} / minuto",
            f"{CO2_AIR_MIN} kg / minuto",
            f"{CO2_GND_MIN} kg / minuto",
        ],
        'Fuente / Nota': [
            '', '', 'Meteorología LEBL 10-AUG-2025', '',
            'Carta AIP LEBL', 'Carta AIP LEBL LVP',
            'Calculado', 'Calculado a partir de AAR', 'Calculado a partir de PAAR',
            '', 'Input de simulación', 'Input de simulación',
            'Calculado', 'Calculado por modelo de Newell', 'Calculado',
            'Estándar Eurocontrol CTOT', '',
            'Eurocontrol GDP Reference Manual', 'Definición ECAC Doc 30',
            '', 'Eurocontrol Standard Inputs 2024',
            'Eurocontrol Standard Inputs 2024',
            'Eurocontrol Standard Inputs 2024',
            'Eurocontrol Standard Inputs 2024',
        ],
    })

    ws = wb.create_sheet('0_Parametros_GDP')
    _escribir_dataframe_con_formato(ws, df)
    _autoajustar_columnas(ws)
    _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_datos_crudos(wb, df_vuelos_crudo: pd.DataFrame) -> None:
    """Pestaña 1: Datos originales sin procesar — para trazabilidad."""
    ws = wb.create_sheet('1_Datos_Crudos')
    _escribir_dataframe_con_formato(ws, df_vuelos_crudo.reset_index(drop=True))
    _autoajustar_columnas(ws)
    _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_regulacion_gdp(wb, df_res: pd.DataFrame) -> None:
    """Pestaña 2: Vuelos con slot asignado y retraso desglosado."""
    cols = [
        'ARCID', 'airline', 'ADEP', 'ATYP', 'recat', 'is_ecac',
        'distancia_km', 'minutes_eta', 'assigned_slot',
        'total_delay', 'air_delay', 'ground_delay', 'flight_status',
    ]
    df_export = (
        df_res[cols].copy()
        .sort_values('minutes_eta')
        .rename(columns={'minutes_eta': 'ETA_Prog', 'assigned_slot': 'ATA_Real'})
        .reset_index(drop=True)
    )
    ws = wb.create_sheet('2_Regulacion_GDP')
    _escribir_dataframe_con_formato(ws, df_export)
    _autoajustar_columnas(ws)
    _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_matriz_slots(wb, df_slots: pd.DataFrame) -> None:
    """Pestaña 3: Matriz de slots generados y su estado de ocupación."""
    ws = wb.create_sheet('3_Matriz_Slots')
    _escribir_dataframe_con_formato(ws, df_slots.reset_index(drop=True))
    _autoajustar_columnas(ws)
    _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_kpis_comparativa(wb, df_res: pd.DataFrame) -> None:
    """
    Pestaña 5: Tabla comparativa Sin Regulación vs GDP.
    Columnas: Métrica | Sin Regulación | Con GDP | Δ Diferencia | Mejora %
    """
    kpis = calcular_kpis_economicos(df_res)

    candidatos = df_res[df_res['flight_status'] == 'GPD CANDIDATE']
    exentos    = df_res[df_res['flight_status'] != 'GPD CANDIDATE']

    r_total  = df_res['total_delay'].sum()
    r_aire   = df_res['air_delay'].sum()
    r_tierra = df_res['ground_delay'].sum()

    def fmt_min(v):  return f"{round(v, 1)} min"
    def fmt_eur(v):  return f"€ {int(v):,}"
    def fmt_kg(v):   return f"{int(v):,} kg"
    def pct(a, b):
        return f"{round((a-b)/a*100, 1)} %" if a != 0 else "—"
    def dif(a, b):   return round(a - b, 2)

    df = pd.DataFrame({
        'Métrica': [
            '── OPERACIONAL ─────────────────────────────────────────',
            'Total vuelos en ventana GDP',
            'Vuelos candidatos GDP (regulados)',
            'Vuelos exentos',
            'Retraso TOTAL acumulado',
            'Retraso absorbido en el AIRE',
            'Retraso absorbido en TIERRA',
            'Retraso medio por vuelo',
            'Retraso máximo',
            'Desviación estándar',
            '── ECONÓMICO ───────────────────────────────────────────',
            'Coste total estimado',
            'Coste retraso en AIRE',
            'Coste retraso en TIERRA',
            'Ahorro generado por GDP',
            '── AMBIENTAL ───────────────────────────────────────────',
            'Emisiones CO₂ totales',
            'CO₂ del retraso en AIRE',
            'CO₂ del retraso en TIERRA',
            'CO₂ ahorrado por GDP',
        ],
        'Sin Regulación': [
            '',
            len(df_res), len(candidatos), len(exentos),
            fmt_min(r_total), fmt_min(r_total), fmt_min(0),
            fmt_min(df_res['total_delay'].mean()),
            fmt_min(df_res['total_delay'].max()),
            fmt_min(df_res['total_delay'].std()),
            '',
            fmt_eur(kpis['cost_baseline']),
            fmt_eur(r_total * COST_AIR_MIN), fmt_eur(0), '—',
            '',
            fmt_kg(kpis['co2_baseline']),
            fmt_kg(r_total * CO2_AIR_MIN), fmt_kg(0), '—',
        ],
        'Con GDP': [
            '',
            len(df_res), len(candidatos), len(exentos),
            fmt_min(r_total), fmt_min(r_aire), fmt_min(r_tierra),
            fmt_min(df_res['total_delay'].mean()),
            fmt_min(df_res['total_delay'].max()),
            fmt_min(df_res['total_delay'].std()),
            '',
            fmt_eur(kpis['cost_gdp']),
            fmt_eur(r_aire * COST_AIR_MIN),
            fmt_eur(r_tierra * COST_GND_MIN),
            fmt_eur(kpis['cost_savings']),
            '',
            fmt_kg(kpis['co2_gdp']),
            fmt_kg(r_aire * CO2_AIR_MIN),
            fmt_kg(r_tierra * CO2_GND_MIN),
            fmt_kg(kpis['co2_savings']),
        ],
        'Δ Diferencia': [
            '', '—', '—', '—', '—',
            fmt_min(dif(r_total, r_aire)),
            fmt_min(dif(0, r_tierra)),
            '—', '—', '—',
            '',
            fmt_eur(dif(kpis['cost_baseline'], kpis['cost_gdp'])),
            fmt_eur(dif(r_total * COST_AIR_MIN, r_aire * COST_AIR_MIN)),
            fmt_eur(dif(0, r_tierra * COST_GND_MIN)), '—',
            '',
            fmt_kg(dif(kpis['co2_baseline'], kpis['co2_gdp'])),
            fmt_kg(dif(r_total * CO2_AIR_MIN, r_aire * CO2_AIR_MIN)),
            fmt_kg(dif(0, r_tierra * CO2_GND_MIN)), '—',
        ],
        'Mejora GDP (%)': [
            '', '—', '—', '—', '—',
            pct(r_total, r_aire), '—', '—', '—', '—',
            '',
            pct(kpis['cost_baseline'], kpis['cost_gdp']),
            pct(r_total * COST_AIR_MIN, r_aire * COST_AIR_MIN),
            '—', '—',
            '',
            pct(kpis['co2_baseline'], kpis['co2_gdp']),
            pct(r_total * CO2_AIR_MIN, r_aire * CO2_AIR_MIN),
            '—', '—',
        ],
    })

    ws = wb.create_sheet('5_KPIs_Comparativa')
    _escribir_dataframe_con_formato(ws, df)
    _autoajustar_columnas(ws)
    _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_analisis_retrasos(wb, df_res: pd.DataFrame, df_slots: pd.DataFrame) -> None:
    """Pestaña 6: Estadísticas descriptivas y bandas CODA de retraso."""
    delay      = df_res['total_delay']
    candidatos = df_res[df_res['flight_status'] == 'GPD CANDIDATE']
    exentos    = df_res[df_res['flight_status'] != 'GPD CANDIDATE']
    retrasados = df_res[df_res['total_delay'] > 0]
    total      = len(df_res)

    def pct(n):      return f"{round(n/total*100, 1)} %"
    def fmt_min(v):  return f"{round(v, 1)} min"
    def mean_safe(s): return fmt_min(s['total_delay'].mean()) if len(s) > 0 else '—'

    n0  = int((delay == 0).sum())
    n1  = int(((delay > 0)  & (delay <= 15)).sum())
    n2  = int(((delay > 15) & (delay <= 30)).sum())
    n3  = int(((delay > 30) & (delay <= 60)).sum())
    n4  = int((delay > 60).sum())

    def grp(status): return df_res[df_res['flight_status'] == status]

    df = pd.DataFrame({
        'Métrica': [
            '── ESTADÍSTICAS DESCRIPTIVAS ───────────────────────────',
            'Total vuelos en ventana GDP',
            'Vuelos SIN retraso',
            'Vuelos CON retraso',
            'Retraso mínimo (entre retrasados)',
            'Retraso medio — todos los vuelos',
            'Retraso medio — solo vuelos retrasados',
            'Mediana del retraso',
            'Percentil 75 del retraso',
            'Percentil 90 del retraso',
            'Retraso máximo',
            'Desviación estándar',
            '── DISTRIBUCIÓN POR BANDAS CODA / EUROCONTROL ──────────',
            'Banda 0 — Sin retraso',
            'Banda 1 — Leve          [  0 – 15 min ]',
            'Banda 2 — Moderado      [ 15 – 30 min ]',
            'Banda 3 — Significativo [ 30 – 60 min ]',
            'Banda 4 — Severo        [    > 60 min ]',
            '── POR TIPO DE VUELO ────────────────────────────────────',
            'Retraso medio — Candidatos GDP (tierra)',
            'Retraso medio — Vuelos Exentos (aire)',
            'Retraso medio — Exentos Internacionales',
            'Retraso medio — Exentos Airborne',
            'Retraso medio — Exentos por Distancia',
            '── EFICIENCIA DE SLOTS ──────────────────────────────────',
            'Slots generados',
            'Slots ocupados',
            'Slots sin asignar',
            'Tasa de ocupación',
            'Vuelos sin slot asignado',
        ],
        'Valor': [
            '',
            total,
            f"{n0}  ({pct(n0)})",
            f"{len(retrasados)}  ({pct(len(retrasados))})",
            fmt_min(retrasados['total_delay'].min()) if len(retrasados) > 0 else '—',
            fmt_min(delay.mean()),
            fmt_min(retrasados['total_delay'].mean()) if len(retrasados) > 0 else '—',
            fmt_min(delay.median()),
            fmt_min(delay.quantile(0.75)),
            fmt_min(delay.quantile(0.90)),
            fmt_min(delay.max()),
            fmt_min(delay.std()),
            '',
            f"{n0} vuelos  ({pct(n0)})",
            f"{n1} vuelos  ({pct(n1)})",
            f"{n2} vuelos  ({pct(n2)})",
            f"{n3} vuelos  ({pct(n3)})",
            f"{n4} vuelos  ({pct(n4)})",
            '',
            mean_safe(candidatos),
            mean_safe(exentos),
            mean_safe(grp('EXEMPT INTERNATIONAL')),
            mean_safe(grp('EXEMPT AIRBORNE')),
            mean_safe(grp('EXEMPT DISTANCE')),
            '',
            len(df_slots),
            int(df_slots['occupied'].sum()),
            int((~df_slots['occupied']).sum()),
            f"{round(df_slots['occupied'].sum()/len(df_slots)*100, 1)} %" if len(df_slots) > 0 else '—',
            int(df_res['assigned_slot'].isna().sum()),
        ],
    })

    ws = wb.create_sheet('6_Analisis_Retrasos')
    _escribir_dataframe_con_formato(ws, df)
    _autoajustar_columnas(ws)
    _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_equidad_rbs(wb, df_res: pd.DataFrame) -> None:
    """Pestaña 7: Retraso medio y distribución por aerolínea."""
    eq_df = (
        df_res.groupby('airline')
        .agg(
            Total_Vuelos=('ARCID', 'count'),
            Retraso_Total_min=('total_delay', 'sum'),
            Retraso_Medio_min=('total_delay', 'mean'),
            Retraso_Maximo_min=('total_delay', 'max'),
            Vuelos_Retrasados=('total_delay', lambda x: (x > 0).sum()),
        )
        .reset_index()
        .sort_values('Total_Vuelos', ascending=False)
        .round(2)
    )
    # Columna extra: % de vuelos retrasados por aerolínea
    eq_df['Pct_Retrasados'] = (
        eq_df['Vuelos_Retrasados'] / eq_df['Total_Vuelos'] * 100
    ).round(1).astype(str) + ' %'

    ws = wb.create_sheet('7_Equidad_RBS')
    _escribir_dataframe_con_formato(ws, eq_df)
    _autoajustar_columnas(ws)
    _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


# =============================================================================
# ORQUESTADOR PÚBLICO — El único punto de entrada desde main.py
# =============================================================================

def exportar_auditoria_excel(
    df_vuelos_crudo: pd.DataFrame,
    df_res: pd.DataFrame,
    df_slots: pd.DataFrame,
    params: dict,
    h_noreg: int,
    path: str,
) -> None:
    """
    Construye el Excel maestro de auditoría llamando a cada función de hoja.

    Para añadir una pestaña nueva:
        1. Escribe _sheet_mi_nueva_hoja(wb, ...) siguiendo el mismo patrón.
        2. Añade la llamada justo antes de wb.save().
        Eso es todo.

    Args:
        df_vuelos_crudo: DataFrame original pre-GDP.
        df_res:          Resultados del GDP con retrasos calculados.
        df_slots:        Matriz de slots generados.
        params:          Parámetros del escenario (AAR, PAAR, H_START...).
        h_noreg:         Minuto del día en que la cola se disuelve.
        path:            Ruta completa del .xlsx de salida.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        # Creamos el workbook usando pandas primero para escribir los datos,
        # y luego abrimos con openpyxl para aplicar el formato visual.
        # Esta estrategia es la más robusta: pandas gestiona los datos,
        # openpyxl gestiona el diseño.

        # Paso 1: Escribir todas las hojas con pandas (datos puros, sin formato)
        with pd.ExcelWriter(path, engine='openpyxl') as writer:
            # Hoja temporal vacía para que el archivo sea válido
            pd.DataFrame().to_excel(writer, sheet_name='_tmp')

        # Paso 2: Abrir con openpyxl y construir cada hoja con formato completo
        from openpyxl import load_workbook
        wb = load_workbook(path)

        # Eliminar la hoja temporal
        if '_tmp' in wb.sheetnames:
            del wb['_tmp']

        # Construir cada pestaña — añade aquí nuevas hojas cuando las necesites
        _sheet_parametros(wb, params, h_noreg)
        _sheet_datos_crudos(wb, df_vuelos_crudo)
        _sheet_regulacion_gdp(wb, df_res)
        _sheet_matriz_slots(wb, df_slots)
        _sheet_kpis_comparativa(wb, df_res)
        _sheet_analisis_retrasos(wb, df_res, df_slots)
        _sheet_equidad_rbs(wb, df_res)

        wb.save(path)
        print(f"✅ Excel de auditoría generado en: {path}")

    except PermissionError:
        print("⚠️  ERROR: Cierra el archivo Excel antes de ejecutar el script.")
    except Exception as e:
        print(f"❌ Error inesperado al generar el Excel: {e}")
        raise