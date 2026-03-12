# =============================================================================
# test/test_data_prep.py
# Tests automatizados para lib_data_prep.py
#
# ¿Qué es un test automatizado?
#   Es código que verifica que tu código funciona correctamente.
#   En lugar de ejecutar el script y mirar a mano si el resultado parece bien,
#   el test lo comprueba por ti en milisegundos y te avisa si algo falla.
#
# ¿Por qué son útiles?
#   Imagina que dentro de 3 meses modificas parse_time_to_minutes() para
#   añadir un nuevo formato. Sin tests, no sabes si rompiste los casos que
#   ya funcionaban. Con tests, ejecutas un comando y lo sabes al instante.
#
# Cómo ejecutar estos tests desde la terminal:
#   cd Proyecto MGTA_reforma3/
#   python -m pytest test/ -v
#       -v = verbose, muestra el nombre de cada test y si pasó o falló
#
# Si no tienes pytest instalado:
#   pip install pytest
#   O simplemente ejecuta: python test/test_data_prep.py
# =============================================================================

import sys
import os
import unittest

import pandas as pd
import numpy as np

# Añadimos la carpeta src/ al path de Python para poder importar los módulos
# del proyecto sin necesidad de instalarlos como paquete.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import lib_data_prep as prep


# =============================================================================
# CLASE DE TESTS: parse_time_to_minutes
#
# Una "clase de tests" agrupa todos los tests relacionados con una función.
# Hereda de unittest.TestCase, que es la librería estándar de Python para tests.
# Cada método que empieza por "test_" se ejecuta automáticamente.
# =============================================================================

class TestParseTimeToMinutes(unittest.TestCase):
    """
    Tests para la función parse_time_to_minutes().

    Cubrimos todos los "casos límite" (edge cases):
    los valores raros o extremos que pueden romper el código.
    """

    def test_formato_hhmm_normal(self):
        """
        Caso más común: formato "HH:MM" estándar.
        06:30 = 6*60 + 30 = 390 minutos.
        """
        resultado = prep.parse_time_to_minutes("06:30")
        self.assertAlmostEqual(resultado, 390.0)
        # assertAlmostEqual compara floats con tolerancia,
        # porque 0.1 + 0.2 == 0.30000000000000004 en Python.

    def test_formato_hhmmss_con_segundos(self):
        """
        Formato con segundos: "HH:MM:SS".
        06:30:45 = 390 + 45/60 = 390.75 minutos.
        """
        resultado = prep.parse_time_to_minutes("06:30:45")
        self.assertAlmostEqual(resultado, 390.75)

    def test_formato_solo_minutos(self):
        """
        Formato sin separador: "15" (solo un número).
        Este es el bug que encontramos — la columna TT del CSV
        contiene valores así. Debe devolver 15.0 (ya en minutos).
        """
        resultado = prep.parse_time_to_minutes("15")
        self.assertAlmostEqual(resultado, 15.0)

    def test_medianoche(self):
        """
        Las 00:00 deben devolver 0.0, no NaN ni error.
        """
        resultado = prep.parse_time_to_minutes("00:00")
        self.assertAlmostEqual(resultado, 0.0)

    def test_valor_nan(self):
        """
        Una celda vacía en pandas es float('nan').
        La función debe devolver 0.0 silenciosamente, sin lanzar error.
        """
        resultado = prep.parse_time_to_minutes(float('nan'))
        self.assertAlmostEqual(resultado, 0.0)

    def test_valor_none(self):
        """
        None es distinto de NaN en Python.
        pd.isna(None) devuelve True, así que también debe devolver 0.0.
        """
        resultado = prep.parse_time_to_minutes(None)
        self.assertAlmostEqual(resultado, 0.0)

    def test_string_invalido(self):
        """
        Un valor corrupto como "N/A" o "??" no debe crashear el programa.
        El except (ValueError) lo captura y devuelve 0.0.
        """
        resultado = prep.parse_time_to_minutes("N/A")
        self.assertAlmostEqual(resultado, 0.0)

    def test_string_vacio(self):
        """
        Un string vacío "" tampoco debe causar un error.
        """
        resultado = prep.parse_time_to_minutes("")
        self.assertAlmostEqual(resultado, 0.0)

    def test_fin_de_dia(self):
        """
        23:59 = 23*60 + 59 = 1439 minutos. Valor máximo esperado del día.
        """
        resultado = prep.parse_time_to_minutes("23:59")
        self.assertAlmostEqual(resultado, 1439.0)


# =============================================================================
# CLASE DE TESTS: preparar_vuelos
#
# Estos tests comprueban el pipeline completo de carga y limpieza.
# Usamos datos SINTÉTICOS (inventados) en lugar de los CSVs reales,
# así los tests son rápidos y no dependen de que el archivo exista.
# =============================================================================

class TestPrepararVuelos(unittest.TestCase):
    """
    Tests para la función preparar_vuelos().

    Estrategia: creamos mini-DataFrames "de juguete" con exactamente
    los datos que necesitamos para verificar cada comportamiento.
    """

    def setUp(self):

        import tempfile
        """
        setUp() se ejecuta ANTES de cada test de esta clase.
        Es el lugar para preparar los datos comunes que usarán los tests.

        Aquí creamos dos CSVs temporales en memoria (sin tocar el disco)
        que simulan el formato real de los archivos del proyecto.
        """
        # Mini-CSV de vuelos: 3 vuelos de prueba
        # - IBE001: Madrid (LEMD) → Barcelona (LEBL), ECAC, B738
        # - BAW002: Londres (EGLL) → Barcelona (LEBL), ECAC, A320
        # - UAE003: Dubai (OMDB) → Barcelona (LEBL), NO ECAC, B77W

        self.directorio_temp = tempfile.mkdtemp()

        self.df_vuelos_raw = pd.DataFrame({
            'ARCID':  ['IBE001', 'BAW002', 'UAE003'],
            'ADEP':   ['LEMD',   'EGLL',   'OMDB'],
            'ADES':   ['LEBL',   'LEBL',   'LEBL'],
            'ETA':    ['08:30',  '09:15',  '10:00'],
            'ETD':    ['07:00',  '07:30',  '05:00'],
            'TT':     ['15',     '12',     '20'],     # Formato de un solo número
            'ATYP':   ['B738',   'A320',   'B77W'],
        })

        # Mini-CSV de flota: categoría de estela y asientos por tipo de avión
        self.df_flota_raw = pd.DataFrame({
            'f':              ['B738', 'A320', 'B77W'],
            'recat':          ['D',    'D',    'C'],
            'size_seats_avg': [189,    180,    396],
        })

        # Guardamos los mini-CSVs en archivos temporales para pasárselos
        # a preparar_vuelos() exactamente igual que en producción.
        self.path_vuelos = os.path.join(self.directorio_temp, 'test_vuelos.csv')
        self.path_flota  = os.path.join(self.directorio_temp, 'test_flota.csv')
        self.df_vuelos_raw.to_csv(self.path_vuelos, sep=';', index=False)
        self.df_flota_raw.to_csv(self.path_flota,   sep=';', index=False)

        self.df = prep.preparar_vuelos(self.path_vuelos, self.path_flota)

    def tearDown(self):
        import shutil
        # Eliminamos la carpeta temporal al terminar cada test
        shutil.rmtree(self.directorio_temp, ignore_errors=True)

    def test_numero_de_vuelos(self):
        """
        Los 3 vuelos del CSV deben aparecer en el resultado.
        Si preparar_vuelos filtra de más, este test lo detecta.
        """
        self.assertEqual(len(self.df), 3)

    def test_columnas_nuevas_existen(self):
        """
        La función debe haber creado estas columnas nuevas.
        Si alguien las renombra o borra, el test falla inmediatamente.
        """
        columnas_esperadas = [
            'minutes_eta', 'minutes_etd', 'minutes_tt',
            'is_ecac', 'airline', 'distancia_km',
        ]
        for col in columnas_esperadas:
            self.assertIn(col, self.df.columns, msg=f"Falta la columna: {col}")

    def test_is_ecac_correcto(self):
        """
        IBE (LEMD) y BAW (EGLL) son ECAC → True.
        UAE (OMDB, Dubai) NO es ECAC → False.
        """
        df = self.df.set_index('ARCID')  # Indexamos por indicativo para acceder fácil
        self.assertTrue(df.loc['IBE001', 'is_ecac'])
        self.assertTrue(df.loc['BAW002', 'is_ecac'])
        self.assertFalse(df.loc['UAE003', 'is_ecac'])

    def test_airline_extraida_correctamente(self):
        """
        Los primeros 3 caracteres de ARCID = código ICAO de la aerolínea.
        IBE001 → IBE, BAW002 → BAW, UAE003 → UAE.
        """
        df = self.df.set_index('ARCID')
        self.assertEqual(df.loc['IBE001', 'airline'], 'IBE')
        self.assertEqual(df.loc['BAW002', 'airline'], 'BAW')
        self.assertEqual(df.loc['UAE003', 'airline'], 'UAE')

    def test_distancia_km_no_negativa(self):
        """
        La distancia nunca puede ser negativa (usamos .clip(lower=0)).
        Este test protege contra regresiones si alguien toca la fórmula.
        """
        self.assertTrue((self.df['distancia_km'] >= 0).all())

    def test_ordenado_por_eta(self):
        """
        El DataFrame debe llegar ordenado por ETA (el más temprano primero).
        IBE001 llega a las 08:30, BAW002 a las 09:15, UAE003 a las 10:00.
        """
        etas = self.df['minutes_eta'].tolist()
        self.assertEqual(etas, sorted(etas))

    def test_recat_desconocido_es_nan(self):
        """
        Si un tipo de avión no está en el catálogo de flota,
        su recat debe quedar como NaN — sin fallback silencioso.
        Así los datos sucios son visibles en lugar de enmascarados.
        """
        df_extra = self.df_vuelos_raw.copy()
        df_extra = pd.concat([df_extra, pd.DataFrame({
            'ARCID': ['TST999'], 'ADEP': ['LFPG'], 'ADES': ['LEBL'],
            'ETA': ['11:00'], 'ETD': ['09:00'], 'TT': ['10'], 'ATYP': ['XYZ'],
        })], ignore_index=True)

        path_extra = os.path.join(self.directorio_temp, 'test_vuelos_extra.csv')
        df_extra.to_csv(path_extra, sep=';', index=False)
        df_resultado = prep.preparar_vuelos(path_extra, self.path_flota)

        vuelo_desconocido = df_resultado[df_resultado['ARCID'] == 'TST999']
        self.assertTrue(pd.isna(vuelo_desconocido['recat'].values[0]))


# =============================================================================
# PUNTO DE ENTRADA
# Permite ejecutar los tests directamente: python test/test_data_prep.py
# =============================================================================
if __name__ == '__main__':
    # verbosity=2 muestra el nombre de cada test y su resultado (OK / FAIL)
    unittest.main(verbosity=2)
