# =============================================================================
# test/test_gdp_core.py
# Tests automatizados para lib_gdp_core.py
#
# QUÉ SE VERIFICA AQUÍ:
#   Las funciones más importantes del proyecto — el corazón del simulador.
#   Si alguna de estas funciones tiene un bug, los resultados del GDP serían
#   incorrectos sin que el programa lanzara ningún error visible.
#
# FUNCIONES CUBIERTAS:
#   1. etiquetar_vuelos_gdp()    → ¿Se clasifica bien cada tipo de vuelo?
#   2. asignar_slots_rbs()       → ¿El algoritmo RBS asigna los slots en orden FIFO?
#                                   ¿Los exentos tienen prioridad sobre los candidatos?
#   3. calcular_delays()         → ¿Se calcula bien el retraso y se asigna a la fase correcta?
#   4. calcular_kpis_economicos() → ¿Los KPIs económicos y de CO2 son matemáticamente correctos?
#
# CÓMO EJECUTAR:
#   python -m pytest test/ -v
# =============================================================================

import sys
import os
import unittest

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from lib_gdp_core import (
    etiquetar_vuelos_gdp,
    asignar_slots_rbs,
    calcular_delays,
    calcular_kpis_economicos,
)
from config import FS_CANDIDATE, FS_AIRBORNE, FS_DISTANCE, FS_INTERNATIONAL


# =============================================================================
# DATOS SINTÉTICOS COMPARTIDOS
#
# En lugar de usar los CSVs reales (que requieren tener los archivos en disco),
# construimos DataFrames mínimos con exactamente los datos que necesita cada test.
# Esto hace los tests rápidos, predecibles y sin dependencias externas.
# =============================================================================

def _hacer_vuelos_base() -> pd.DataFrame:
    """
    Crea un DataFrame mínimo con 5 vuelos que representan los 4 tipos de exención.
    Los valores están diseñados para que los filtros de etiquetar_vuelos_gdp()
    produzcan resultados predecibles y verificables.

    Contexto: H_START = 360 min (06:00 UTC), H_FREEZE_OFFSET = 150 min
    → h_freeze = 360 - 150 = 210 min (03:30 UTC)
    """
    return pd.DataFrame({
        'ARCID':       ['IBE001', 'BAW002', 'UAE003', 'VLG004', 'AFR005'],
        'ADEP':        ['LEMD',   'EGLL',   'OMDB',   'LEMD',   'LFPG'],
        # is_ecac: LEMD(LE), EGLL(EG) → ECAC. OMDB(OM) → NO ECAC.
        'is_ecac':     [True,     True,     False,    True,     True],
        # minutes_etd:
        #   IBE001 → 300 > 210 (no ha despegado antes del freeze) → candidato
        #   BAW002 → 200 < 210 (despegó antes del freeze) → airborne
        #   UAE003 → irrelevante, es internacional
        #   VLG004 → 300 > 210 → candidato
        #   AFR005 → 300 > 210 → candidato (pero lo excluirá el radio)
        'minutes_etd': [300,      200,      100,      300,      300],
        'minutes_eta': [390,      410,      430,      450,      470],
        # distancia_km:
        #   IBE001, BAW002, VLG004 → dentro del radio 3000 km
        #   UAE003 → internacional (se excluye antes de llegar al radio)
        #   AFR005 → 3500 > 3000 → fuera del radio → EXEMPT DISTANCE
        'distancia_km':[500,      1800,     4200,     500,      3500],
    })


def _hacer_slots_base() -> pd.DataFrame:
    """Crea una rejilla de 6 slots libres empezando en el minuto 390."""
    return pd.DataFrame({
        'slot_start_min': [390.0, 393.0, 396.0, 399.0, 402.0, 405.0],
        'occupied':       [False] * 6,
        'flight_id':      [None]  * 6,
    })

# =============================================================================
# TEST CLASE 1 — etiquetar_vuelos_gdp()
#
# Verifica que cada vuelo recibe la etiqueta correcta según su origen,
# su hora de despegue y su distancia al aeropuerto destino.
# =============================================================================

class TestEtiquetarVuelosGDP(unittest.TestCase):
    """Tests para etiquetar_vuelos_gdp()."""

    def setUp(self):
        """Prepara los datos antes de cada test."""
        self.df = _hacer_vuelos_base()
        self.H_START = 360
        self.RADIUS  = 3000
        self.H_FREEZE_OFFSET = 150

    def _etiquetar(self):
        return etiquetar_vuelos_gdp(
            self.df, self.H_START,
            radius_km=self.RADIUS,
            h_freeze_offset=self.H_FREEZE_OFFSET,
        )

    def test_vuelo_ecac_no_despegado_dentro_radio_es_candidato(self):
        """IBE001: ECAC + no despegado antes del freeze + dentro del radio → GDP CANDIDATE."""
        df_etiq = self._etiquetar()
        self.assertEqual(
            df_etiq.loc[df_etiq['ARCID'] == 'IBE001', 'flight_status'].values[0],
            FS_CANDIDATE,
            msg="IBE001 debería ser GDP CANDIDATE: cumple las 3 condiciones.",
        )

    def test_vuelo_despegado_antes_freeze_es_airborne(self):
        """BAW002: despegó en minuto 200, antes del freeze (210) → EXEMPT AIRBORNE."""
        df_etiq = self._etiquetar()
        self.assertEqual(
            df_etiq.loc[df_etiq['ARCID'] == 'BAW002', 'flight_status'].values[0],
            FS_AIRBORNE,
            msg="BAW002 despegó antes del freeze horizon → EXEMPT AIRBORNE.",
        )

    def test_vuelo_no_ecac_es_internacional(self):
        """UAE003: origen fuera del ECAC → EXEMPT INTERNATIONAL (prioridad sobre airborne)."""
        df_etiq = self._etiquetar()
        self.assertEqual(
            df_etiq.loc[df_etiq['ARCID'] == 'UAE003', 'flight_status'].values[0],
            FS_INTERNATIONAL,
            msg="UAE003 no es ECAC → EXEMPT INTERNATIONAL, independientemente de su hora.",
        )

    def test_vuelo_fuera_del_radio_es_exempt_distance(self):
        """AFR005: distancia 3500 km > radio 3000 km → EXEMPT DISTANCE."""
        df_etiq = self._etiquetar()
        self.assertEqual(
            df_etiq.loc[df_etiq['ARCID'] == 'AFR005', 'flight_status'].values[0],
            FS_DISTANCE,
            msg="AFR005 está fuera del radio de cobertura → EXEMPT DISTANCE.",
        )

    def test_columnas_nuevas_creadas(self):
        """La función debe crear las 4 columnas auxiliares en el DataFrame."""
        df_etiq = self._etiquetar()
        for col in ['is_departed', 'is_inside_radius', 'is_gpd_candidate', 'flight_status']:
            self.assertIn(col, df_etiq.columns, msg=f"Falta la columna '{col}'.")

    def test_no_modifica_df_original(self):
        """La función trabaja sobre una copia — el DataFrame original no cambia."""
        df_original = self.df.copy()
        self._etiquetar()
        self.assertNotIn(
            'flight_status', self.df.columns,
            msg="etiquetar_vuelos_gdp() no debe modificar el DataFrame original.",
        )


# =============================================================================
# TEST CLASE 2 — asignar_slots_rbs()
#
# Verifica que el algoritmo RBS asigna slots en orden FIFO y que los vuelos
# exentos tienen prioridad sobre los candidatos GDP.
# =============================================================================

class TestAsignarSlotsRBS(unittest.TestCase):
    """Tests para asignar_slots_rbs()."""

    def test_fifo_candidatos_orden_eta(self):
        """
        Con dos candidatos GDP, el que tiene ETA menor debe recibir el slot
        más temprano. FIFO: First In (ETA menor) → First Out (slot más temprano).
        """
        df_vuelos = pd.DataFrame({
            'ARCID':         ['VLG001', 'IBE002'],
            'minutes_eta':   [400.0,    395.0],   # IBE002 llega antes
            'flight_status': [FS_CANDIDATE, FS_CANDIDATE],
        })
        df_slots = pd.DataFrame({
            'slot_start_min': [395.0, 400.0],
            'occupied':       [False, False],
            'flight_id':      [None,  None],
        })

        df_res = asignar_slots_rbs(df_vuelos, df_slots)

        slot_ibe = df_res.loc[df_res['ARCID'] == 'IBE002', 'assigned_slot'].values[0]
        slot_vlg = df_res.loc[df_res['ARCID'] == 'VLG001', 'assigned_slot'].values[0]

        self.assertLess(
            slot_ibe, slot_vlg,
            msg="IBE002 tiene ETA menor y debe recibir el slot más temprano (FIFO).",
        )

    def test_exentos_tienen_prioridad_sobre_candidatos(self):
        """
        Un vuelo exento y un candidato GDP con la misma ETA deben resolverse
        dando el slot disponible al exento. El candidato absorbe su retraso en tierra.
        """
        df_vuelos = pd.DataFrame({
            'ARCID':         ['EXENTO', 'CANDIDATO'],
            'minutes_eta':   [390.0,    390.0],   # misma ETA
            'flight_status': [FS_AIRBORNE, FS_CANDIDATE],
        })
        df_slots = pd.DataFrame({
            'slot_start_min': [390.0, 393.0],
            'occupied':       [False, False],
            'flight_id':      [None,  None],
        })

        df_res = asignar_slots_rbs(df_vuelos, df_slots)

        slot_exento    = df_res.loc[df_res['ARCID'] == 'EXENTO',    'assigned_slot'].values[0]
        slot_candidato = df_res.loc[df_res['ARCID'] == 'CANDIDATO', 'assigned_slot'].values[0]

        self.assertEqual(
            slot_exento, 390.0,
            msg="El vuelo exento debe recibir el slot de las 390 (prioridad RBS).",
        )
        self.assertEqual(
            slot_candidato, 393.0,
            msg="El candidato GDP debe recibir el slot siguiente.",
        )

    def test_columna_assigned_slot_creada(self):
        """La función debe crear la columna 'assigned_slot' en el DataFrame."""
        df_vuelos = pd.DataFrame({
            'ARCID':         ['IBE001'],
            'minutes_eta':   [390.0],
            'flight_status': [FS_CANDIDATE],
        })
        df_slots = _hacer_slots_base()
        df_res = asignar_slots_rbs(df_vuelos, df_slots)
        self.assertIn('assigned_slot', df_res.columns)

    def test_sin_slots_disponibles_assigned_slot_es_nan(self):
        """Si no hay slots disponibles, assigned_slot debe quedar como NaN."""
        df_vuelos = pd.DataFrame({
            'ARCID':         ['IBE001'],
            'minutes_eta':   [390.0],
            'flight_status': [FS_CANDIDATE],
        })
        # Todos los slots están en el pasado respecto a la ETA del vuelo
        df_slots = pd.DataFrame({
            'slot_start_min': [200.0, 300.0],
            'occupied':       [False, False],
            'flight_id':      [None,  None],
        })
        df_res = asignar_slots_rbs(df_vuelos, df_slots)
        self.assertTrue(
            pd.isna(df_res.loc[df_res['ARCID'] == 'IBE001', 'assigned_slot'].values[0]),
            msg="Si no hay slots >= ETA, assigned_slot debe ser NaN.",
        )


# =============================================================================
# TEST CLASE 3 — calcular_delays()
#
# Verifica que el retraso se calcula correctamente y que se asigna a la
# fase correcta (aire para exentos, tierra para candidatos GDP).
# =============================================================================

class TestCalcularDelays(unittest.TestCase):
    """Tests para calcular_delays()."""

    def setUp(self):
        self.df = pd.DataFrame({
            'ARCID':         ['CAND', 'EXENTO', 'SIN_RETRASO'],
            'minutes_eta':   [390.0,  400.0,    430.0],
            'assigned_slot': [400.0,  410.0,    430.0],  # 10, 10 y 0 min de retraso
            'flight_status': [FS_CANDIDATE, FS_AIRBORNE, FS_CANDIDATE],
        })

    def test_total_delay_calculado_correctamente(self):
        """total_delay = assigned_slot - minutes_eta."""
        df_res = calcular_delays(self.df)
        self.assertEqual(df_res.loc[df_res['ARCID'] == 'CAND',    'total_delay'].values[0], 10.0)
        self.assertEqual(df_res.loc[df_res['ARCID'] == 'EXENTO',  'total_delay'].values[0], 10.0)
        self.assertEqual(df_res.loc[df_res['ARCID'] == 'SIN_RETRASO', 'total_delay'].values[0], 0.0)

    def test_candidato_gdp_absorbe_retraso_en_tierra(self):
        """Los candidatos GDP esperan en tierra: ground_delay = total_delay, air_delay = 0."""
        df_res = calcular_delays(self.df)
        self.assertEqual(df_res.loc[df_res['ARCID'] == 'CAND', 'ground_delay'].values[0], 10.0)
        self.assertEqual(df_res.loc[df_res['ARCID'] == 'CAND', 'air_delay'].values[0],    0.0)

    def test_exento_absorbe_retraso_en_aire(self):
        """Los vuelos exentos no pueden esperar en tierra: air_delay = total_delay, ground_delay = 0."""
        df_res = calcular_delays(self.df)
        self.assertEqual(df_res.loc[df_res['ARCID'] == 'EXENTO', 'air_delay'].values[0],    10.0)
        self.assertEqual(df_res.loc[df_res['ARCID'] == 'EXENTO', 'ground_delay'].values[0], 0.0)

    def test_suma_aire_tierra_igual_total(self):
        """air_delay + ground_delay debe ser siempre igual a total_delay."""
        df_res = calcular_delays(self.df)
        for _, fila in df_res.iterrows():
            self.assertAlmostEqual(
                fila['air_delay'] + fila['ground_delay'],
                fila['total_delay'],
                places=6,
                msg=f"Para {fila['ARCID']}: air + ground ≠ total.",
            )

    def test_no_hay_retrasos_negativos(self):
        """Si un avión llega antes de su ETA, su retraso debe ser 0, no negativo."""
        df_adelantado = pd.DataFrame({
            'ARCID':         ['PUNTUAL'],
            'minutes_eta':   [400.0],
            'assigned_slot': [395.0],   # Llega 5 min antes de lo previsto
            'flight_status': [FS_CANDIDATE],
        })
        df_res = calcular_delays(df_adelantado)
        self.assertEqual(df_res['total_delay'].values[0], 0.0,
                         msg="Un slot anterior a la ETA debe producir retraso 0, no negativo.")


# =============================================================================
# TEST CLASE 4 — calcular_kpis_economicos()
#
# Verifica que los KPIs económicos y de CO2 son matemáticamente correctos.
# =============================================================================

class TestCalcularKpisEconomicos(unittest.TestCase):
    """Tests para calcular_kpis_economicos()."""

    def setUp(self):
        """
        Construimos un caso controlado donde podemos calcular el resultado
        esperado a mano para verificar que la función lo calcula igual.

        Caso:
          - Vuelo candidato GDP: 10 min de retraso en tierra.
            co2_kg_vuelo=1000, duracion=100 min → co2_extra_tierra = 1000 × 10/100 = 100 kg
          - Vuelo exento airborne: 10 min de retraso en el aire.
            co2_kg_vuelo=2000, duracion=200 min → co2_extra_aire = 2000 × 10/200 = 100 kg
        """
        self.df = pd.DataFrame({
            'total_delay':       [10.0,  10.0],
            'air_delay':         [0.0,   10.0],
            'ground_delay':      [10.0,  0.0],
            'flight_status':     [FS_CANDIDATE, FS_AIRBORNE],
            'co2_kg_vuelo':      [1000.0, 2000.0],
            'duracion_vuelo_min': [100.0,  200.0],
        })

    def test_coste_gdp_menor_que_baseline(self):
        """
        El GDP siempre debe ser más barato que el Do-Nothing porque
        transfiere retraso del aire (caro) a tierra (barato).
        """
        kpis = calcular_kpis_economicos(self.df)
        self.assertLess(
            kpis['cost_gdp'], kpis['cost_baseline'],
            msg="Con GDP, el coste debe ser menor que sin GDP.",
        )

    def test_cost_savings_positivo(self):
        """El ahorro económico debe ser positivo cuando hay retraso en tierra."""
        kpis = calcular_kpis_economicos(self.df)
        self.assertGreater(kpis['cost_savings'], 0,
                           msg="cost_savings debe ser positivo.")

    def test_co2_gdp_menor_que_baseline(self):
        """El GDP debe reducir las emisiones CO2 respecto al Do-Nothing."""
        kpis = calcular_kpis_economicos(self.df)
        self.assertLess(
            kpis['co2_gdp'], kpis['co2_baseline'],
            msg="Con GDP, las emisiones CO2 deben ser menores.",
        )

    def test_co2_savings_igual_a_diferencia(self):
        """co2_savings debe ser exactamente co2_baseline - co2_gdp."""
        kpis = calcular_kpis_economicos(self.df)
        self.assertAlmostEqual(
            kpis['co2_savings'],
            kpis['co2_baseline'] - kpis['co2_gdp'],
            places=2,
            msg="co2_savings debe ser igual a co2_baseline - co2_gdp.",
        )

    def test_unrecoverable_delay_es_solo_airborne(self):
        """
        El retraso irrecuperable debe ser exactamente el retraso total
        de los vuelos EXEMPT AIRBORNE — en este caso, 10 minutos.
        """
        kpis = calcular_kpis_economicos(self.df)
        self.assertEqual(
            kpis['unrecoverable_delay'], 10.0,
            msg="El retraso irrecuperable debe ser solo el de los vuelos AIRBORNE.",
        )

    def test_resultado_tiene_todas_las_claves(self):
        """El diccionario devuelto debe tener exactamente las claves esperadas."""
        kpis = calcular_kpis_economicos(self.df)
        claves_esperadas = {
            'cost_baseline', 'cost_gdp', 'cost_savings',
            'co2_baseline', 'co2_gdp', 'co2_savings',
            'co2_aire_delay', 'co2_tierra_delay',
            'unrecoverable_delay',
        }
        self.assertEqual(
            set(kpis.keys()), claves_esperadas,
            msg="El diccionario de KPIs no tiene las claves esperadas.",
        )


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)