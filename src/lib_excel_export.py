# =============================================================================
# src/lib_excel_export.py
# FASE 3: Construccion y formato del Excel maestro de auditoria.
# =============================================================================

import os
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from config import COST_AIR_MIN, COST_GND_MIN, FS_CANDIDATE, FS_AIRBORNE, FS_INTERNATIONAL, FS_DISTANCE
from lib_gdp_core import calcular_kpis_economicos

COLOR_CABECERA_AZUL = "FF1F4E79"
COLOR_CABECERA_GRIS = "FF404040"
COLOR_SECCION       = "FF2E75B6"
COLOR_FILA_ALTERNA  = "FFD9E1F2"
COLOR_FILA_BLANCA   = "FFFFFFFF"
FUENTE_BASE         = "Arial"
TAMANNO_NORMAL      = 10
TAMANNO_CABECERA    = 11

def _borde_fino():
    lado = Side(style="thin", color="FFD0D0D0")
    return Border(left=lado, right=lado, top=lado, bottom=lado)

def _estilo_cabecera(color_fondo=COLOR_CABECERA_AZUL):
    return {
        'font':      Font(name=FUENTE_BASE, size=TAMANNO_CABECERA, bold=True, color="FFFFFFFF"),
        'fill':      PatternFill("solid", fgColor=color_fondo),
        'alignment': Alignment(horizontal="center", vertical="center", wrap_text=True),
        'border':    _borde_fino(),
    }

def _estilo_seccion():
    return {
        'font':      Font(name=FUENTE_BASE, size=TAMANNO_NORMAL, bold=True, color="FFFFFFFF"),
        'fill':      PatternFill("solid", fgColor=COLOR_SECCION),
        'alignment': Alignment(horizontal="left", vertical="center"),
    }

def _estilo_dato(fila_par=False):
    color = COLOR_FILA_ALTERNA if fila_par else COLOR_FILA_BLANCA
    return {
        'font':      Font(name=FUENTE_BASE, size=TAMANNO_NORMAL),
        'fill':      PatternFill("solid", fgColor=color),
        'alignment': Alignment(horizontal="left", vertical="center", wrap_text=False),
        'border':    _borde_fino(),
    }

def _autoajustar_columnas(ws, ancho_minimo=12, ancho_maximo=55):
    for col_cells in ws.columns:
        max_len = 0
        col_letra = get_column_letter(col_cells[0].column)
        for celda in col_cells:
            if celda.value is not None:
                lineas = str(celda.value).split('\n')
                largo = max(len(l) for l in lineas)
                max_len = max(max_len, largo)
        ws.column_dimensions[col_letra].width = min(ancho_maximo, max(ancho_minimo, max_len * 1.15 + 2))

def _escribir_dataframe_con_formato(ws, df, fila_inicio=1):
    n_cols = len(df.columns)
    for col_idx, nombre_col in enumerate(df.columns, start=1):
        celda = ws.cell(row=fila_inicio, column=col_idx, value=nombre_col)
        estilos = _estilo_cabecera()
        celda.font = estilos['font']; celda.fill = estilos['fill']
        celda.alignment = estilos['alignment']; celda.border = estilos['border']
    ws.row_dimensions[fila_inicio].height = 30

    contador_filas_dato = 0
    fila_actual = fila_inicio + 1
    for _, row in df.iterrows():
        valores = list(row)
        primer_valor = str(valores[0]) if valores[0] is not None else ''
        es_separador = primer_valor.startswith('--')
        if es_separador:
            estilos = _estilo_seccion()
        else:
            contador_filas_dato += 1
            estilos = _estilo_dato(fila_par=(contador_filas_dato % 2 == 0))
        for col_idx, valor in enumerate(valores, start=1):
            contenido = valor if (not es_separador or col_idx == 1) else ''
            celda = ws.cell(row=fila_actual, column=col_idx, value=contenido)
            if 'font'   in estilos: celda.font      = estilos['font']
            if 'fill'   in estilos: celda.fill      = estilos['fill']
            if 'alignment' in estilos: celda.alignment = estilos['alignment']
            if 'border' in estilos and not es_separador: celda.border = estilos['border']
        ws.row_dimensions[fila_actual].height = 18
        fila_actual += 1
    return fila_actual - 1

def _congelar_primera_fila(ws):
    ws.freeze_panes = ws['A2']

# =============================================================================
# FUNCIONES DE PESTANA
# =============================================================================

def _sheet_parametros(wb, params, h_noreg, r_min_newell: float):
    """Pestana 0: Parametros del escenario. Incluye retraso minimo de Newell y modelo CO2."""
    def min_a_hhmm(m):
        return f"{int(m)//60:02d}:{int(m)%60:02d} UTC"
    
    dur_reg   = params['H_END'] - params['H_START']
    dur_total = h_noreg - params['H_START']
    reduccion = round((1 - params['PAAR'] / params['AAR']) * 100, 1)

    parametros = [
        '-- AEROPUERTO --', 'Aeropuerto Destino', 'Tipo de Regulacion',
        '-- CAPACIDAD --',
        'AAR - Tasa de Llegada Nominal', 'PAAR - Tasa de Llegada Reducida (LVP)',
        'Reduccion de Capacidad', 'Tamano de Slot Nominal', 'Tamano de Slot Reducido (GDP)',
        '-- VENTANA TEMPORAL --',
        'Inicio de Regulacion (H_START)', 'Fin de Regulacion (H_END)',
        'Duracion de la Regulacion', 'Fin del Impacto - Cola Disuelta (H_NOREG)',
        'Retraso minimo teorico (Newell)', 'Duracion Total del Impacto',
        'Ventana de Congelacion CTOT',
        '-- COBERTURA --', 'Radio de Cobertura GDP', 'Espacio Aereo Regulado',
        '-- PARAMETROS ECONOMICOS --',
        'Coste por minuto en el AIRE', 'Coste por minuto en TIERRA',
        '-- MODELO DE EMISIONES CO2 --',
        'Metodo de calculo', 'Fuente del modelo',
    ]
    valores = [
        '', 'LEBL - Barcelona El Prat', 'LVP (Low Visibility Procedures)',
        '',
        f"{params['AAR']} llegadas/hora", f"{params['PAAR']} llegadas/hora",
        f"{reduccion} %",
        f"{round(params['SLOT_NOM'], 2)} min/avion ({round(60/params['SLOT_NOM'])} aviones/hora)",
        f"{round(params['SLOT_RED'], 2)} min/avion ({round(60/params['SLOT_RED'])} aviones/hora)",
        '',
        min_a_hhmm(params['H_START']), min_a_hhmm(params['H_END']),
        f"{dur_reg} min ({dur_reg//60}h {dur_reg%60}min)",
        min_a_hhmm(h_noreg),
        f"{int(round(r_min_newell))} min",
        f"{dur_total} min desde inicio ({dur_total//60}h {dur_total%60}min)",
        f"{params.get('H_FREEZE_OFFSET', 150)} min antes de H_START",
        '', '3.000 km desde LEBL', 'ECAC (European Civil Aviation Conference)',
        '',
        f"EUR {COST_AIR_MIN} / minuto", f"EUR {COST_GND_MIN} / minuto",
        '',
        'Proporcional por vuelo: co2_vuelo x (retraso_aire / duracion_vuelo)',
        'Montlaur, Trapote-Barreira & Delgado (2025). Applied Sciences, 15(17), 9688.',
    ]
    fuentes = [
        '', '', 'Meteorologia LEBL 10-AUG-2025', '',
        'Carta AIP LEBL', 'Carta AIP LEBL LVP',
        'Calculado', 'Calculado a partir de AAR', 'Calculado a partir de PAAR',
        '', 'Input de simulacion', 'Input de simulacion',
        'Calculado', 'Calculado por modelo de Newell',
        'Area entre curvas acumuladas de demanda y capacidad',
        'Calculado', 'Estandar Eurocontrol CTOT',
        '', 'Eurocontrol GDP Reference Manual', 'Definicion ECAC Doc 30',
        '', 'Univ. Westminster / Eurocontrol, delay cost ref. values v4.1, 2015',
        'Univ. Westminster / Eurocontrol, delay cost ref. values v4.1, 2015',
        '', 'emissions_fuel_model.py - Delgado et al. (2025)',
        'https://doi.org/10.3390/app15179688',
    ]
    assert len(parametros) == len(valores) == len(fuentes), \
        f"Listas desiguales: Parametro={len(parametros)}, Valor={len(valores)}, Fuente={len(fuentes)}"

    df = pd.DataFrame({'Parametro': parametros, 'Valor': valores, 'Fuente / Nota': fuentes})

    ws = wb.create_sheet('0_Parametros_GDP')
    _escribir_dataframe_con_formato(ws, df)
    _autoajustar_columnas(ws)
    _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_datos_crudos(wb, df_vuelos_crudo):
    ws = wb.create_sheet('1_Datos_Crudos')
    _escribir_dataframe_con_formato(ws, df_vuelos_crudo.reset_index(drop=True))
    _autoajustar_columnas(ws); _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_regulacion_gdp(wb, df_res):
    cols = ['ARCID','airline','ADEP','ATYP','recat','is_ecac',
            'distancia_km','minutes_eta','assigned_slot',
            'total_delay','air_delay','ground_delay','flight_status']
    df_export = (df_res[cols].copy().sort_values('minutes_eta')
                 .rename(columns={'minutes_eta':'ETA_Prog','assigned_slot':'CTA'})
                 .reset_index(drop=True))
    ws = wb.create_sheet('2_Regulacion_GDP')
    _escribir_dataframe_con_formato(ws, df_export)
    _autoajustar_columnas(ws); _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_matriz_slots(wb, df_slots):
    ws = wb.create_sheet('3_Matriz_Slots')
    _escribir_dataframe_con_formato(ws, df_slots.reset_index(drop=True))
    _autoajustar_columnas(ws); _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_kpis_comparativa(wb, df_res):
    kpis = calcular_kpis_economicos(df_res)
    candidatos = df_res[df_res['flight_status'] == FS_CANDIDATE]
    exentos    = df_res[df_res['flight_status'] != FS_CANDIDATE]
    r_total = df_res['total_delay'].sum()
    r_aire  = df_res['air_delay'].sum()
    r_tierra= df_res['ground_delay'].sum()

    def fmt_min(v): return f"{int(round(v))} min"
    def fmt_eur(v): return f"EUR {int(v):,}"
    def fmt_kg(v):  return f"{int(v):,} kg"
    def pct(a,b):   return f"{round((a-b)/a*100,1)} %" if a != 0 else "-"
    def dif(a,b):   return round(a-b, 2)

    metricas = [
        '-- OPERACIONAL --',
        'Total vuelos en ventana GDP','Vuelos candidatos GDP (regulados)','Vuelos exentos',
        'Retraso TOTAL acumulado','Retraso absorbido en el AIRE','Retraso absorbido en TIERRA',
        'Retraso medio por vuelo','Retraso maximo','Desviacion estandar',
        '-- ECONOMICO --',
        'Coste total estimado','Coste retraso en AIRE','Coste retraso en TIERRA','Ahorro generado por GDP',
        '-- AMBIENTAL --',
        'Emisiones CO2 totales','CO2 ahorrado por GDP',
    ]
    sin_reg = [
        '',
        len(df_res),len(candidatos),len(exentos),
        fmt_min(r_total),fmt_min(r_total),fmt_min(0),
        fmt_min(df_res['total_delay'].mean()),fmt_min(df_res['total_delay'].max()),fmt_min(df_res['total_delay'].std()),
        '',
        fmt_eur(kpis['cost_baseline']),fmt_eur(r_total*COST_AIR_MIN),fmt_eur(0),'-',
        '',
        fmt_kg(kpis['co2_baseline']),'-',
    ]
    con_gdp = [
        '',
        len(df_res),len(candidatos),len(exentos),
        fmt_min(r_total),fmt_min(r_aire),fmt_min(r_tierra),
        fmt_min(df_res['total_delay'].mean()),fmt_min(df_res['total_delay'].max()),fmt_min(df_res['total_delay'].std()),
        '',
        fmt_eur(kpis['cost_gdp']),fmt_eur(r_aire*COST_AIR_MIN),fmt_eur(r_tierra*COST_GND_MIN),fmt_eur(kpis['cost_savings']),
        '',
        fmt_kg(kpis['co2_gdp']),fmt_kg(kpis['co2_savings']),
    ]
    delta = [
        '','','-','-','-',
        fmt_min(dif(r_total,r_aire)),fmt_min(dif(0,r_tierra)),
        '-','-','-',
        '',
        fmt_eur(dif(kpis['cost_baseline'],kpis['cost_gdp'])),
        fmt_eur(dif(r_total*COST_AIR_MIN,r_aire*COST_AIR_MIN)),
        fmt_eur(dif(0,r_tierra*COST_GND_MIN)),'-',
        '',
        fmt_kg(dif(kpis['co2_baseline'],kpis['co2_gdp'])),'-',
    ]
    mejora = [
        '','','-','-','-',
        pct(r_total,r_aire),'-','-','-','-',
        '',
        pct(kpis['cost_baseline'],kpis['cost_gdp']),
        pct(r_total*COST_AIR_MIN,r_aire*COST_AIR_MIN),
        '-','-',
        '',
        pct(kpis['co2_baseline'],kpis['co2_gdp']),'-',
    ]
    df = pd.DataFrame({'Metrica':metricas,'Sin Regulacion':sin_reg,'Con GDP':con_gdp,'Delta Diferencia':delta,'Mejora GDP (%)':mejora})
    ws = wb.create_sheet('5_KPIs_Comparativa')
    _escribir_dataframe_con_formato(ws, df)
    _autoajustar_columnas(ws); _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_analisis_retrasos(wb, df_res, df_slots):
    delay      = df_res['total_delay']
    candidatos = df_res[df_res['flight_status'] == FS_CANDIDATE]
    exentos    = df_res[df_res['flight_status'] != FS_CANDIDATE]
    retrasados = df_res[df_res['total_delay'] > 0]
    total      = len(df_res)

    def pct(n):       return f"{round(n/total*100,1)} %"
    def fmt_min(v):   return f"{int(round(v))} min"
    def mean_safe(s): return fmt_min(s['total_delay'].mean()) if len(s) > 0 else '-'
    def grp(status):  return df_res[df_res['flight_status'] == status]

    n0 = int((delay==0).sum())
    n1 = int(((delay>0)&(delay<=15)).sum())
    n2 = int(((delay>15)&(delay<=30)).sum())
    n3 = int(((delay>30)&(delay<=60)).sum())
    n4 = int((delay>60).sum())

    metricas = [
        '-- ESTADISTICAS DESCRIPTIVAS --',
        'Total vuelos en ventana GDP','Vuelos SIN retraso','Vuelos CON retraso',
        'Retraso minimo (entre retrasados)','Retraso medio - todos los vuelos',
        'Retraso medio - solo vuelos retrasados','Mediana del retraso',
        'Percentil 75 del retraso','Percentil 90 del retraso','Retraso maximo','Desviacion estandar',
        '-- DISTRIBUCION POR BANDAS CODA / EUROCONTROL --',
        'Banda 0 - Sin retraso','Banda 1 - Leve [0-15 min]','Banda 2 - Moderado [15-30 min]',
        'Banda 3 - Significativo [30-60 min]','Banda 4 - Severo [>60 min]',
        '-- POR TIPO DE VUELO --',
        'Retraso medio - Candidatos GDP (tierra)','Retraso medio - Vuelos Exentos (aire)',
        'Retraso medio - Exentos Internacionales','Retraso medio - Exentos Airborne',
        'Retraso medio - Exentos por Distancia',
        '-- EFICIENCIA DE SLOTS --',
        'Slots generados','Slots ocupados','Slots sin asignar','Tasa de ocupacion',
        'Vuelos sin slot asignado',
    ]
    valores = [
        '',
        total, f"{n0}  ({pct(n0)})", f"{len(retrasados)}  ({pct(len(retrasados))})",
        fmt_min(retrasados['total_delay'].min()) if len(retrasados)>0 else '-',
        fmt_min(delay.mean()),
        fmt_min(retrasados['total_delay'].mean()) if len(retrasados)>0 else '-',
        fmt_min(delay.median()), fmt_min(delay.quantile(0.75)), fmt_min(delay.quantile(0.90)),
        fmt_min(delay.max()), fmt_min(delay.std()),
        '',
        f"{n0} vuelos ({pct(n0)})", f"{n1} vuelos ({pct(n1)})", f"{n2} vuelos ({pct(n2)})",
        f"{n3} vuelos ({pct(n3)})", f"{n4} vuelos ({pct(n4)})",
        '',
        mean_safe(candidatos), mean_safe(exentos),
        mean_safe(grp(FS_INTERNATIONAL)), mean_safe(grp(FS_AIRBORNE)),
        mean_safe(grp(FS_DISTANCE)),
        '',
        len(df_slots), int(df_slots['occupied'].sum()), int((~df_slots['occupied']).sum()),
        f"{round(df_slots['occupied'].sum()/len(df_slots)*100,1)} %" if len(df_slots)>0 else '-',
        int(df_res['assigned_slot'].isna().sum()),
    ]
    df = pd.DataFrame({'Metrica': metricas, 'Valor': valores})
    ws = wb.create_sheet('6_Analisis_Retrasos')
    _escribir_dataframe_con_formato(ws, df)
    _autoajustar_columnas(ws); _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


def _sheet_equidad_rbs(wb, df_res):
    eq_df = (
        df_res.groupby('airline')
        .agg(
            Total_Vuelos=('ARCID','count'),
            Retraso_Total_min=('total_delay','sum'),
            Retraso_Medio_min=('total_delay','mean'),
            Retraso_Maximo_min=('total_delay','max'),
            Vuelos_Retrasados=('total_delay', lambda x: (x>0).sum()),
        )
        .reset_index().sort_values('Total_Vuelos', ascending=False).round(2)
    )
    eq_df['Pct_Retrasados'] = (eq_df['Vuelos_Retrasados']/eq_df['Total_Vuelos']*100).round(1).astype(str) + ' %'
    ws = wb.create_sheet('7_Equidad_RBS')
    _escribir_dataframe_con_formato(ws, eq_df)
    _autoajustar_columnas(ws); _congelar_primera_fila(ws)
    ws.sheet_view.showGridLines = False


# =============================================================================
# ORQUESTADOR PUBLICO
# =============================================================================

def exportar_auditoria_excel(
    df_vuelos_crudo: pd.DataFrame,
    df_res: pd.DataFrame,
    df_slots: pd.DataFrame,
    params: dict,
    h_noreg: int,
    timeline: pd.DataFrame,
    r_min_newell: float,
    path: str,
) -> None:
    """
    Construye el Excel maestro de auditoria.

    Args:
        df_vuelos_crudo: DataFrame original pre-GDP.
        df_res:          Resultados del GDP con retrasos calculados.
        df_slots:        Matriz de slots generados.
        params:          Parametros del escenario (AAR, PAAR, H_START...).
        h_noreg:         Minuto del dia en que la cola se disuelve.
        timeline:        Curvas de Newell minuto a minuto (para graficos).
        r_min_newell:    Retraso minimo teorico calculado.
        path:            Ruta completa del .xlsx de salida.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with pd.ExcelWriter(path, engine='openpyxl') as writer:
            pd.DataFrame().to_excel(writer, sheet_name='_tmp')

        wb = load_workbook(path)
        if '_tmp' in wb.sheetnames:
            del wb['_tmp']

        _sheet_parametros(wb, params, h_noreg, r_min_newell)
        _sheet_datos_crudos(wb, df_vuelos_crudo)
        _sheet_regulacion_gdp(wb, df_res)
        _sheet_matriz_slots(wb, df_slots)
        _sheet_kpis_comparativa(wb, df_res)
        _sheet_analisis_retrasos(wb, df_res, df_slots)
        _sheet_equidad_rbs(wb, df_res)

        wb.save(path)
        print(f"✅ Excel de auditoria generado en: {path}")

    except PermissionError:
        print("⚠️  ERROR: Cierra el archivo Excel antes de ejecutar el script.")
    except Exception as e:
        print(f"❌ Error inesperado al generar el Excel: {e}")
        raise