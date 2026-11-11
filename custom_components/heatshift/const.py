"""Constants for HeatShift."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "heatshift"

# Setup (entry data)
CONF_PRICE_SENSOR: Final = "price_sensor"
CONF_OFFSET_ENTITY: Final = "offset_entity"
CONF_WATER_HEATER: Final = "water_heater"
CONF_TANK_SENSOR: Final = "tank_sensor"
CONF_ACCEPT: Final = "accept_disclaimer"
CONF_CONTROL_MODE: Final = "control_mode"

MODE_OFFSET: Final = "offset"
MODE_THERMOSTAT: Final = "thermostat"
CONTROL_MODES: Final = [MODE_OFFSET, MODE_THERMOSTAT]

# Settings (entry options)
CONF_EXPENSIVE_THRESHOLD: Final = "expensive_threshold"
CONF_EXPENSIVE_OFFSET: Final = "expensive_offset"
CONF_CHEAP_THRESHOLD: Final = "cheap_threshold"
CONF_CHEAP_OFFSET: Final = "cheap_offset"
CONF_DHW_ENABLED: Final = "dhw_enabled"
CONF_DHW_WINDOW_START: Final = "dhw_window_start"
CONF_DHW_WINDOW_END: Final = "dhw_window_end"
CONF_DHW_BLOCK_MINUTES: Final = "dhw_block_minutes"
CONF_DHW_REHEAT_BELOW: Final = "dhw_reheat_below"
CONF_MORNING_ENABLED: Final = "morning_enabled"
CONF_MORNING_TIME: Final = "morning_time"
CONF_MORNING_BELOW: Final = "morning_below"
CONF_MORNING_TARGET: Final = "morning_target"
CONF_MORNING_TIMEOUT: Final = "morning_timeout"
CONF_TANK_MINIMUM: Final = "tank_minimum"
CONF_BASE_TEMP: Final = "base_temperature"
CONF_THERMO_EXPENSIVE_DELTA: Final = "thermostat_expensive_delta"
CONF_THERMO_CHEAP_DELTA: Final = "thermostat_cheap_delta"
CONF_THERMO_MIN: Final = "thermostat_min"
CONF_THERMO_MAX: Final = "thermostat_max"

# COP
CONF_WEATHER_ENTITY: Final = "weather_entity"
CONF_OUTDOOR_SENSOR: Final = "outdoor_sensor"
CONF_HEATING_LWT: Final = "heating_lwt"
CONF_DHW_LWT: Final = "dhw_lwt"
CONF_COP_A7: Final = "cop_a7w35"
CONF_COP_A2: Final = "cop_a2w35"
CONF_COP_SOURCE: Final = "cop_source"
CONF_FLOW_SENSOR: Final = "flow_sensor"
CONF_SUPPLY_SENSOR: Final = "supply_sensor"
CONF_RETURN_SENSOR: Final = "return_sensor"
CONF_POWER_SENSOR: Final = "power_sensor"

CONF_MARGIN: Final = "reference_margin"
CONF_MIN_SPREAD: Final = "min_spread"
CONF_REF_DAYS: Final = "reference_days"
CONF_START_PRICE: Final = "start_price"

COP_ESTIMATE: Final = "estimate"
COP_MEASURED: Final = "measured"
COP_SOURCES: Final = [COP_ESTIMATE, COP_MEASURED]

DEFAULT_OPTIONS: Final[dict] = {
    CONF_EXPENSIVE_THRESHOLD: 65,
    CONF_EXPENSIVE_OFFSET: -2,
    CONF_CHEAP_THRESHOLD: 15,
    CONF_CHEAP_OFFSET: 0,
    CONF_DHW_ENABLED: True,
    CONF_DHW_WINDOW_START: "10:00:00",
    CONF_DHW_WINDOW_END: "16:00:00",
    CONF_DHW_BLOCK_MINUTES: 60,
    CONF_DHW_REHEAT_BELOW: 45,
    CONF_MORNING_ENABLED: True,
    CONF_MORNING_TIME: "05:00:00",
    CONF_MORNING_BELOW: 40,
    CONF_MORNING_TARGET: 45,
    CONF_MORNING_TIMEOUT: 120,
    CONF_TANK_MINIMUM: 35,
    CONF_BASE_TEMP: 20.5,
    CONF_THERMO_EXPENSIVE_DELTA: -1.0,
    CONF_THERMO_CHEAP_DELTA: 0.5,
    CONF_THERMO_MIN: 17.0,
    CONF_THERMO_MAX: 23.0,
    CONF_HEATING_LWT: 35,
    CONF_DHW_LWT: 55,
    CONF_COP_A7: 0,
    CONF_COP_A2: 0,
    CONF_COP_SOURCE: COP_ESTIMATE,
    CONF_MARGIN: 20,
    CONF_MIN_SPREAD: 20,
    CONF_REF_DAYS: 7,
    # CBS average all-in price for dynamic contracts, September 2026.
    CONF_START_PRICE: 0.32,
}

# Hard safety limits, also used as selector bounds.
OFFSET_MIN: Final = -5
OFFSET_MAX: Final = 3
TANK_TEMP_MIN: Final = 30
TANK_TEMP_MAX: Final = 60
ROOM_TEMP_MIN: Final = 15
ROOM_TEMP_MAX: Final = 25
DELTA_MIN: Final = -3.0
DELTA_MAX: Final = 2.0

# Water heater modes as used by Daikin Onecta.
MODE_NORMAL: Final = "heat_pump"
MODE_BOOST: Final = "performance"

# Status values
STATUS_OFF: Final = "off"
STATUS_ACTIVE: Final = "active"
STATUS_NO_PRICES: Final = "no_prices"
STATUS_HEATING_OFF: Final = "heating_off"
STATUSES: Final = [STATUS_OFF, STATUS_ACTIVE, STATUS_NO_PRICES, STATUS_HEATING_OFF]
