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

DEFAULT_OPTIONS: Final = {
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
