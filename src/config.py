# =============================================================================
# src/config.py
#all constant used in project
#
# import constants from another file:
#   from config import CFG, COST_AIR_MIN, ECAC_PREFIXES
# =============================================================================

from dataclasses import dataclass

# =============================================================================
# GPD parameters in LEBL (BCN EL PRAT)
# =============================================================================

@dataclass(frozen=True)
class AirportConfig:
    """
    Parameters of Ground Delay Program in LEBL.

    DATACLASS FROZEN:
        frozen=True values can't be changed once created. Avoids modifying it by 
        accident the AAR during the program execution.

    TIME UNITS:
        H_START y H_END expressed in minutes from midnight on UTC.

    PARAMETERS:
        AAR:             Aircraft Arrival Rate.
                         how many planes can LEBL accept in nominal conditions.
        PAAR:            Arrival rate while Low Visibility Procedures.
        H_START:         initial minute of the GDP.
        H_END:           end minute GDP.
        H_NOREG:         minutes window before CTOT.
                         If a flight took of more H_NOREG minutes before H_START, it is considered AIRBORNE
                         and remains EXEMPT. Cannot recieve a new CTOT
        GDP_RADIUS_KM:   Max radius in km that covers the GDP. Flights that 
                         take off from outside Are EXEMPT. 
                         

    """
    AAR:             int = 44    # aircraft/hour nominal
    PAAR:            int = 20    # aircraft/hout reducede
    H_START:         int = 360   # 06:00 UTC 
    H_END:           int = 780   # 13:00 UTC 
    H_FILE_OFFSET: int = 150     # 2.5 h before H_START
    GDP_RADIUS_KM:   int = 3000  # radius

    @property
    def SLOT_NOM(self) -> float:
        """
        airport covers 44aircraft/h → 1 aircraft each 60/44 = 1.36 min.
        """
        return 60 / self.AAR

    @property
    def SLOT_RED(self) -> float:
        """
        Airport covers 20 aircraft/h → 1 aircraft each 60/20 = 3 min.
        """
        return 60 / self.PAAR

    def to_params_dict(self) -> dict:
        """
        Returns parameters that ejecutar_nucleo_gdp() will need.

        THIS METHOD:
            with this method, we gather all info in a unique place (this dictionary) 
            and if anything changes in the parameters, the function will read from here.

        USE:
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
# CRUISE SPEED - CATEGORIES (RECAT-EU)
# =============================================================================
# Used to estimate the distance flewn.
# RECAT-EU classifies planes by size:
#   A → largest (A380), F → smallest (light aircrafts).
# we will take as default the speed of category D for the ones that are not defined into these categories

VELOCIDAD_KNOTS: dict[str, int] = {
    'A': 480,   # Super-Heavy: A380
    'B': 470,   # Upper-Heavy: B747, A340
    'C': 460,   # Lower-Heavy: B767, A330
    'D': 440,   # Upper-Medium: B737, A320 — most common in LEBL since it is full of A320 from vueling
    'E': 320,   # Lower-Medium
    'F': 150,   # Light
}


# =============================================================================
# OACI PREFIXES OF ECAC AIRPORTS
# =============================================================================
# ECAC: European Civil Aviation Conference
#
# First two characters of OACI idetify the region of procedence. The ones down are the EUROPE ones.
#
# Only flights that are taking off from ECAC can recieve CTOT.
# INTERNATIONAL are outside the European law.

ECAC_PREFIXES: tuple = tuple([
    'EB', 'ED', 'EE', 'EF', 'EG', 'EH', 'EI', 'EK', 'EL', 'EN', 'EP',
    'ES', 'ET', 'EV', 'EY',
    'LA', 'LB', 'LC', 'LD', 'LE', 'LF', 'LG', 'LH', 'LI', 'LJ', 'LK',
    'LM', 'LN', 'LO', 'LP', 'LQ', 'LR', 'LS', 'LT', 'LU', 'LW', 'LY', 'LZ',
    'BI', 'GC', 'GE', 'UD', 'UG', 'UK', 'UB',
])


# =============================================================================
# ECONOMIC CONSTANTS
# =============================================================================
# Source: University of Westminster / Eurocontrol,
#   "European airline delay cost reference values", v4.1, 2015.
#
# Cost of delay per minute in EUR
# In flight: The expensive. Fuel + crew + handling compensations.
COST_AIR_MIN: int = 100  

# On ground: Much cheaper. The whole point of GDP is to keep them
# parked instead of burning fuel in a holding pattern.
COST_GND_MIN: int = 35

# =============================================================================
# CO2 EMISSION MODEL
# =============================================================================
#
# Emissions aren't handcoded. We use the Montlaur (2025) model https://doi.org/10.3390/app15179688
# based on flight distance + seat count. 
# Logic is in src/emissions_fuel_model.py and runs during Phase 1.

# =============================================================================
# FLIGHT_STATUS TAGS 
# =============================================================================
# Use these constants instead of raw strings to filter df['flight_status'].
# Because typos in strings (like 'GPD' instead of 'GDP') fail usually.
# Using constants triggers a NameError, which is way easier to debug.

FS_CANDIDATE     = 'GDP CANDIDATE'        # Regulated by GDP
FS_INTERNATIONAL = 'EXEMPT INTERNATIONAL' # Out of ECAC scope
FS_AIRBORNE      = 'EXEMPT AIRBORNE'      # Already flying when GDP started
FS_DISTANCE      = 'EXEMPT DISTANCE'      # Too far out to regulate


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================
# Single AirportConfig instance to be shared across all modules.
# Import this directly: from config import CFG
CFG = AirportConfig()