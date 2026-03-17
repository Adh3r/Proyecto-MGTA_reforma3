# =============================================================================
# src/config.py
#Todas las constantes del proyecto
#
# IMPORTAR LAS CONSTANTES EN OTRO ARCHIVO:
#   from config import CFG, COST_AIR_MIN, ECAC_PREFIXES
# =============================================================================

from dataclasses import dataclass

# =============================================================================
# PARÁMETROS  DEL GDP EN LEBL (BARCELONA EL PRAT)
# =============================================================================

@dataclass(frozen=True)
class AirportConfig:
    """
    Parámetros del Ground Delay Program simulado en LEBL.

    DATACLASS FROZEN:
        Un dataclass es una clase para almacenar datos.
        frozen=True significa que sus valores NO se pueden cambiar una vez
        creada. Esto evita modificar por accidente
        el AAR durante la ejecución del programa.

    UNIDADES DE TIEMPO:
        H_START y H_END se expresan en MINUTOS desde medianoche UTC.
        Conversión rápida: horas × 60 = minutos
            06:00 UTC = 6 × 60 = 360 minutos
            13:00 UTC = 13 × 60 = 780 minutos

    PARÁMETROS:
        AAR:             Tasa de llegadas nominal (Aircraft Arrival Rate).
                         Cuántos aviones por hora puede aceptar LEBL en condiciones normales.
        PAAR:            Tasa de llegadas reducida durante LVP (Low Visibility Procedures).
                         Cuántos aviones por hora puede aceptar con visibilidad reducida.
        H_START:         Minuto de inicio del GDP (cuando se activa la restricción LVP).
        H_END:           Minuto de fin del GDP (cuando se levanta la restricción LVP).
        H_FREEZE_OFFSET: Ventana de congelación CTOT (minutos antes de H_START).
                         Si un vuelo despegó más de H_FREEZE_OFFSET minutos antes de H_START,
                         se considera "airborne" y queda exento — no puede recibir un nuevo CTOT.
                         Valor estándar Eurocontrol: 150 minutos (2.5 horas).
        GDP_RADIUS_KM:   Radio máximo de cobertura del GDP en kilómetros.
                         Vuelos que salen de aeropuertos más lejanos quedan exentos
                         porque el GDP no llegaría a tiempo para retrasarlos.
    """
    AAR:             int = 44    # Aviones/hora en operación normal
    PAAR:            int = 20    # Aviones/hora durante LVP (baja visibilidad)
    H_START:         int = 360   # 06:00 UTC → inicio de la regulación LVP
    H_END:           int = 780   # 13:00 UTC → fin de la regulación LVP
    H_FREEZE_OFFSET: int = 150   # 2.5 horas antes de H_START = punto de no retorno
    GDP_RADIUS_KM:   int = 3000  # Radio de cobertura del GDP (km desde LEBL)

    @property
    def SLOT_NOM(self) -> float:
        """
        Intervalo entre slots consecutivos en operación normal (minutos/avión).
        Si el aeropuerto acepta 44 aviones/hora → 1 avión cada 60/44 = 1.36 min.
        """
        return 60 / self.AAR

    @property
    def SLOT_RED(self) -> float:
        """
        Intervalo entre slots durante LVP / capacidad reducida (minutos/avión).
        Si el aeropuerto acepta 20 aviones/hora → 1 avión cada 60/20 = 3 min.
        """
        return 60 / self.PAAR

    def to_params_dict(self) -> dict:
        """
        Devuelve parámetros que necesita ejecutar_nucleo_gdp().

        POR QUÉ EXISTE ESTE MÉTODO:
            Sin él, cada módulo que necesita parámetros tendría que construirlo
            manualmente repitiendo las mismas 6 líneas. Si se añade un parámetro
            nuevo al GDP, habría que recordar actualizarlo en todos esos sitios.
            Con este método, hay un único sitio donde se define qué va en el dict.

        USO:
            from config import CFG
            params = CFG.to_params_dict()
        """
        return {
            'H_START':  self.H_START,
            'H_END':    self.H_END,
            'AAR':      self.AAR,
            'PAAR':     self.PAAR,
            'SLOT_NOM': self.SLOT_NOM,
            'SLOT_RED': self.SLOT_RED,
        }


# =============================================================================
# VELOCIDADES DE CRUCERO POR CATEGORÍA (RECAT-EU)
# =============================================================================
# Se usan para estimar la distancia recorrida por cada vuelo.
# La categoría RECAT-EU clasifica los aviones por su masa y envergadura:
#   A → los más grandes (A380), F → los más pequeños (avionetas).
# La velocidad de la categoría D es el predeterminado cuando no hay datos del avión.

VELOCIDAD_KNOTS: dict[str, int] = {
    'A': 480,   # Super-Heavy: A380
    'B': 470,   # Upper-Heavy: B747, A340
    'C': 460,   # Lower-Heavy: B767, A330
    'D': 440,   # Upper-Medium: B737, A320 — la categoría más común en LEBL
    'E': 320,   # Lower-Medium: turbohélices grandes
    'F': 150,   # Light: aviones pequeños y regionales
}


# =============================================================================
# PREFIJOS OACI DE AEROPUERTOS EN EL ESPACIO AÉREO ECAC
# =============================================================================
# ECAC: European Civil Aviation Conference — el espacio aéreo "europeo" del GDP.
#
# Los primeros 2 caracteres del código OACI de un aeropuerto identifican
# la región del mundo donde está. Los prefijos de abajo son los de Europa.
#
# Solo los vuelos que SALEN de aeropuertos ECAC pueden recibir un CTOT.
# Los vuelos intercontinentales están fuera de la jurisdicción del GDP europeo.

ECAC_PREFIXES: tuple = tuple([
    'EB', 'ED', 'EE', 'EF', 'EG', 'EH', 'EI', 'EK', 'EL', 'EN', 'EP',
    'ES', 'ET', 'EV', 'EY',
    'LA', 'LB', 'LC', 'LD', 'LE', 'LF', 'LG', 'LH', 'LI', 'LJ', 'LK',
    'LM', 'LN', 'LO', 'LP', 'LQ', 'LR', 'LS', 'LT', 'LU', 'LW', 'LY', 'LZ',
    'BI', 'GC', 'GE', 'UD', 'UG', 'UK', 'UB',
])


# =============================================================================
# CONSTANTES ECONÓMICAS
# =============================================================================
# Fuente: University of Westminster / Eurocontrol,
#   "European airline delay cost reference values", v4.1, 2015.
#
# Estos valores representan el coste MEDIO por minuto de retraso para
# una aerolínea europea típica. Incluyen: combustible, tripulación,
# desgaste de equipos, compensaciones a pasajeros y costes de handling.

# Retraso en el AIRE: el avión está volando (motores encendidos, combustible
# quemando, tripulación trabajando). Es el retraso más caro.
COST_AIR_MIN: int = 100   # EUR por minuto de retraso en vuelo

# Retraso en TIERRA: el avión espera en el aeropuerto de origen antes de
# despegar (motores apagados, solo APU auxiliar). Mucho más barato.
# La diferencia entre estos dos valores es la justificación económica del GDP:
# transferir retraso del aire a tierra ahorra dinero.
COST_GND_MIN: int = 35    # EUR por minuto de retraso en tierra


# =============================================================================
# MODELO DE EMISIONES CO2
# =============================================================================
# Las emisiones NO se calculan con constantes — se calculan por vuelo usando:
#   Montlaur, A., Trapote-Barreira, C., & Delgado, L. (2025).
#   Applied Sciences, 15(17), 9688.
#   https://doi.org/10.3390/app15179688
#
# El modelo necesita la distancia del vuelo y el número de asientos.
# Está implementado en src/emissions_fuel_model.py
# Se llama en lib_data_prep.py durante la preparación de datos (Fase 1).


# =============================================================================
# ETIQUETAS DE FLIGHT_STATUS — FUENTE ÚNICA DE VERDAD PARA LOS FILTROS
# =============================================================================
# Estas constantes son los únicos cuatro valores posibles de la columna
# 'flight_status' que asigna etiquetar_vuelos_gdp().
#
# POR QUÉ DEFINIRLAS AQUÍ EN LUGAR DE ESCRIBIR LOS STRINGS DIRECTAMENTE:
#   En el código hay más de 15 sitios donde se filtra por flight_status.
#   Si se escribe el string directamente (ej: 'GPD CANDIDATE') en cada sitio,
#   un typo en cualquiera de ellos (ej: 'GDP CANDIDATE') haría que ese filtro
#   no encontrara nada y fallara en silencio — sin error, con resultados incorrectos.
#   Con estas constantes, un typo en el nombre de la constante sí genera
#   un error inmediato de Python (NameError), que es mucho más fácil de detectar.
#
# USO:
#   from config import FS_CANDIDATE, FS_AIRBORNE, FS_DISTANCE, FS_INTERNATIONAL
#   candidatos = df[df['flight_status'] == FS_CANDIDATE]

FS_CANDIDATE     = 'GDP CANDIDATE'        # Vuelo regulable por el GDP
FS_INTERNATIONAL = 'EXEMPT INTERNATIONAL' # Vuelo intercontinental (fuera del ECAC)
FS_AIRBORNE      = 'EXEMPT AIRBORNE'      # Vuelo ya en el aire cuando arranca el GDP
FS_DISTANCE      = 'EXEMPT DISTANCE'      # Vuelo demasiado lejos para ser regulado


# =============================================================================
# INSTANCIA GLOBAL — LA QUE IMPORTAN TODOS LOS MÓDULOS
# =============================================================================
# Creamos UNA sola instancia de AirportConfig aquí.
# Todos los módulos importan esta instancia: from config import CFG
# Esto garantiza que todos usan exactamente los mismos valores.
CFG = AirportConfig()