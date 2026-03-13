# =============================================================================
# src/config.py
# FUENTE ÚNICA DE VERDAD: Todas las constantes del proyecto viven aquí.
#
# ¿Por qué centralizar las constantes?
# Si mañana cambia la capacidad del aeropuerto (AAR) o el coste por minuto,
# solo tienes que tocar ESTE archivo. Sin esto, tendrías que buscar el valor
# en 3 scripts distintos y arriesgarte a dejar uno sin actualizar.
# =============================================================================

from dataclasses import dataclass


# -----------------------------------------------------------------------------
# CONFIGURACIÓN DEL AEROPUERTO Y EL GDP
# Usamos un dataclass "frozen" (congelado) para que nadie pueda cambiar estos
# valores por accidente durante la ejecución del programa.
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class AirportConfig:
    """
    Parámetros operacionales del Ground Delay Program (GDP) en LEBL (Barcelona).

    H_START / H_END: Ventana de regulación en minutos desde medianoche UTC.
      - 360 minutos = 06:00 UTC
      - 780 minutos = 13:00 UTC
    AAR:  Airport Arrival Rate nominal (sin LVP). Ej: 44 llegadas/hora.
    PAAR: Pre-Departure AAR reducido (con LVP activo). Ej: 20 llegadas/hora.
    H_FREEZE_OFFSET: Minutos antes del GDP start en los que un vuelo ya
      despegado se considera "airborne" y queda exento de regulación.
      150 min = 2.5 horas, margen estándar CTOT de Eurocontrol.
    GDP_RADIUS_KM: Radio máximo desde el aeropuerto destino para incluir
      un vuelo en la regulación. Vuelos más lejanos están exentos.
    """
    AAR: int = 44
    PAAR: int = 20
    H_START: int = 360          # 06:00 UTC en minutos desde medianoche
    H_END: int = 780            # 13:00 UTC en minutos desde medianoche
    H_FREEZE_OFFSET: int = 150  # Ventana de congelación CTOT (minutos)
    GDP_RADIUS_KM: int = 3000   # Radio de cobertura de la regulación (km)

    # Propiedad calculada: tiempo entre slots (minutos/avión) para cada modo
    @property
    def SLOT_NOM(self) -> float:
        """Intervalo entre slots en operación normal (minutos)."""
        return 60 / self.AAR

    @property
    def SLOT_RED(self) -> float:
        """Intervalo entre slots durante LVP / capacidad reducida (minutos)."""
        return 60 / self.PAAR


# -----------------------------------------------------------------------------
# VELOCIDADES POR CATEGORÍA DE ESTELA TURBULENTA (RECAT-EU)
# Se usan para estimar la distancia recorrida en vuelo (cinemática).
# La categoría D (Heavy) es el valor por defecto cuando no hay datos.
# -----------------------------------------------------------------------------
VELOCIDAD_KNOTS: dict[str, int] = {
    'A': 480,   # Super-Heavy (A380)
    'B': 470,   # Upper-Heavy (B747, A340)
    'C': 460,   # Lower-Heavy (B767, A330)
    'D': 440,   # Upper-Medium (B737, A320) — la más común
    'E': 320,   # Lower-Medium (turbohélices grandes)
    'F': 150,   # Light (aviones pequeños)
}

# -----------------------------------------------------------------------------
# PREFIJOS OACI DE AEROPUERTOS DENTRO DEL ESPACIO ECAC
# (European Civil Aviation Conference)
# Solo los vuelos procedentes de aeropuertos ECAC son candidatos al GDP.
# Los vuelos intercontinentales quedan exentos porque el GDP no puede
# ordenarles retrasar el despegue (están fuera de la jurisdicción europea).
# -----------------------------------------------------------------------------
ECAC_PREFIXES: tuple = tuple([
    'EB', 'ED', 'EE', 'EF', 'EG', 'EH', 'EI', 'EK', 'EL', 'EN', 'EP',
    'ES', 'ET', 'EV', 'EY',
    'LA', 'LB', 'LC', 'LD', 'LE', 'LF', 'LG', 'LH', 'LI', 'LJ', 'LK',
    'LM', 'LN', 'LO', 'LP', 'LQ', 'LR', 'LS', 'LT', 'LU', 'LW', 'LY', 'LZ',
    'BI', 'GC', 'GE', 'UD', 'UG', 'UK', 'UB',
])

# -----------------------------------------------------------------------------
# CONSTANTES ECONÓMICAS
# Fuente: University of Westminster / Eurocontrol,
#   "European airline delay cost reference values", v4.1, 2015.
# -----------------------------------------------------------------------------

# Coste por minuto de retraso en el AIRE: motores encendidos, combustible
# quemando, tripulación pagada, desgaste de motores.
COST_AIR_MIN: int = 100   # € por minuto en vuelo (holding o ruta)

# Coste por minuto de retraso en TIERRA: motores apagados, solo APU activo.
COST_GND_MIN: int = 35    # € por minuto en tierra (con GDP aplicado)

# -----------------------------------------------------------------------------
# EMISIONES CO2
# Calculadas por vuelo mediante el modelo analítico de:
#   Montlaur, A., Trapote-Barreira, C., & Delgado, L. (2025).
#   Analytical Models of Flight Fuel Consumption and Non-CO2 Emissions
#   as a Function of Aircraft Capacity.
#   Applied Sciences, 15(17), 9688.
#   https://doi.org/10.3390/app15179688
#
# Implementado en src/emissions_fuel_model.py
# Los valores se calculan dinámicamente — NO hay constantes de CO2.
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# INSTANCIA GLOBAL LISTA PARA IMPORTAR
# En lugar de instanciar AirportConfig() en cada script, la creamos aquí
# una sola vez. Cualquier módulo puede hacer: from config import CFG
# -----------------------------------------------------------------------------
CFG = AirportConfig()