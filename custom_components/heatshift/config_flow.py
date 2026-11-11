"""Setup screen and settings for HeatShift."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from .const import (
    CONF_COP_A2,
    CONF_COP_A7,
    CONF_COP_SOURCE,
    CONF_DHW_LWT,
    CONF_FLOW_SENSOR,
    CONF_HEATING_LWT,
    CONF_OUTDOOR_SENSOR,
    CONF_POWER_SENSOR,
    CONF_RETURN_SENSOR,
    CONF_SUPPLY_SENSOR,
    CONF_WEATHER_ENTITY,
    COP_MEASURED,
    COP_SOURCES,
    CONF_ACCEPT,
    CONF_BASE_TEMP,
    CONF_CONTROL_MODE,
    CONF_THERMO_CHEAP_DELTA,
    CONF_THERMO_EXPENSIVE_DELTA,
    CONF_THERMO_MAX,
    CONF_THERMO_MIN,
    CONTROL_MODES,
    DELTA_MAX,
    DELTA_MIN,
    MODE_OFFSET,
    MODE_THERMOSTAT,
    ROOM_TEMP_MAX,
    ROOM_TEMP_MIN,
    CONF_CHEAP_OFFSET,
    CONF_CHEAP_THRESHOLD,
    CONF_DHW_BLOCK_MINUTES,
    CONF_DHW_ENABLED,
    CONF_DHW_REHEAT_BELOW,
    CONF_DHW_WINDOW_END,
    CONF_DHW_WINDOW_START,
    CONF_EXPENSIVE_OFFSET,
    CONF_EXPENSIVE_THRESHOLD,
    CONF_MORNING_BELOW,
    CONF_MORNING_ENABLED,
    CONF_MORNING_TARGET,
    CONF_MORNING_TIME,
    CONF_MORNING_TIMEOUT,
    CONF_OFFSET_ENTITY,
    CONF_PRICE_SENSOR,
    CONF_TANK_MINIMUM,
    CONF_TANK_SENSOR,
    CONF_WATER_HEATER,
    DEFAULT_OPTIONS,
    DOMAIN,
    OFFSET_MAX,
    OFFSET_MIN,
    TANK_TEMP_MAX,
    TANK_TEMP_MIN,
)
from .planner import entity_fits_mode, parse_prices


def _number(minimum: float, maximum: float, step: float = 1, unit: str | None = None) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=NumberSelectorMode.BOX,
        )
    )


class HeatShiftConfigFlow(ConfigFlow, domain=DOMAIN):
    """Setup screen: pick the devices and accept the disclaimer."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the setup screen."""
        errors: dict[str, str] = {}
        if user_input is not None:
            state = self.hass.states.get(user_input[CONF_PRICE_SENSOR])
            climate = self.hass.states.get(user_input[CONF_OFFSET_ENTITY])
            mode = user_input[CONF_CONTROL_MODE]
            if state is None or not parse_prices(state.attributes):
                errors[CONF_PRICE_SENSOR] = "no_prices"
            elif climate is None or not entity_fits_mode(
                mode, climate.attributes.get("min_temp"), climate.attributes.get("max_temp")
            ):
                errors[CONF_OFFSET_ENTITY] = f"not_{mode}_entity"
            elif not user_input.get(CONF_ACCEPT):
                errors["base"] = "must_accept"
            else:
                await self.async_set_unique_id(user_input[CONF_OFFSET_ENTITY])
                self._abort_if_unique_id_configured()
                data = {key: value for key, value in user_input.items() if key != CONF_ACCEPT}
                options = dict(DEFAULT_OPTIONS)
                if mode == MODE_THERMOSTAT:
                    # Start from the setpoint the thermostat has now.
                    current = climate.attributes.get("temperature")
                    if isinstance(current, (int, float)) and ROOM_TEMP_MIN <= current <= ROOM_TEMP_MAX:
                        options[CONF_BASE_TEMP] = float(current)
                return self.async_create_entry(title="HeatShift", data=data, options=options)

        schema = vol.Schema(
            {
                vol.Required(CONF_PRICE_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_CONTROL_MODE, default=MODE_OFFSET): SelectSelector(
                    SelectSelectorConfig(
                        options=CONTROL_MODES,
                        mode=SelectSelectorMode.LIST,
                        translation_key=CONF_CONTROL_MODE,
                    )
                ),
                vol.Required(CONF_OFFSET_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_WATER_HEATER): EntitySelector(
                    EntitySelectorConfig(domain="water_heater")
                ),
                vol.Optional(CONF_TANK_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_ACCEPT, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HeatShiftOptionsFlow:
        """Return the settings flow."""
        return HeatShiftOptionsFlow()


class HeatShiftOptionsFlow(OptionsFlow):
    """Settings: price thresholds, hot water, safety limits, then COP."""

    _data: dict[str, Any]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the settings screen."""
        errors: dict[str, str] = {}
        if user_input is not None:
            low = user_input.get(CONF_THERMO_MIN)
            high = user_input.get(CONF_THERMO_MAX)
            base = user_input.get(CONF_BASE_TEMP)
            if low is not None and high is not None and not low <= base <= high:
                errors["base"] = "base_outside_limits"
            else:
                # Keep settings of the other mode, so switching back loses nothing.
                self._data = {**self.config_entry.options, **user_input}
                return await self.async_step_cop()

        fields: dict[Any, Any] = {
            vol.Required(CONF_EXPENSIVE_THRESHOLD): _number(50, 100, 5, "%"),
            vol.Required(CONF_CHEAP_THRESHOLD): _number(0, 50, 5, "%"),
        }
        if self.config_entry.data.get(CONF_CONTROL_MODE, MODE_OFFSET) == MODE_THERMOSTAT:
            fields.update(
                {
                    vol.Required(CONF_BASE_TEMP): _number(ROOM_TEMP_MIN, ROOM_TEMP_MAX, 0.5, "°C"),
                    vol.Required(CONF_THERMO_EXPENSIVE_DELTA): _number(DELTA_MIN, 0, 0.5, "°C"),
                    vol.Required(CONF_THERMO_CHEAP_DELTA): _number(0, DELTA_MAX, 0.5, "°C"),
                    vol.Required(CONF_THERMO_MIN): _number(ROOM_TEMP_MIN, ROOM_TEMP_MAX, 0.5, "°C"),
                    vol.Required(CONF_THERMO_MAX): _number(ROOM_TEMP_MIN, ROOM_TEMP_MAX, 0.5, "°C"),
                }
            )
        else:
            fields.update(
                {
                    vol.Required(CONF_EXPENSIVE_OFFSET): _number(OFFSET_MIN, 0, 1, "°C"),
                    vol.Required(CONF_CHEAP_OFFSET): _number(0, OFFSET_MAX, 1, "°C"),
                }
            )
        schema = vol.Schema(
            {
                **fields,
                vol.Required(CONF_DHW_ENABLED): BooleanSelector(),
                vol.Required(CONF_DHW_WINDOW_START): TimeSelector(),
                vol.Required(CONF_DHW_WINDOW_END): TimeSelector(),
                vol.Required(CONF_DHW_BLOCK_MINUTES): _number(15, 240, 15, "min"),
                vol.Required(CONF_DHW_REHEAT_BELOW): _number(TANK_TEMP_MIN, TANK_TEMP_MAX, 1, "°C"),
                vol.Required(CONF_MORNING_ENABLED): BooleanSelector(),
                vol.Required(CONF_MORNING_TIME): TimeSelector(),
                vol.Required(CONF_MORNING_BELOW): _number(TANK_TEMP_MIN, TANK_TEMP_MAX, 1, "°C"),
                vol.Required(CONF_MORNING_TARGET): _number(TANK_TEMP_MIN, TANK_TEMP_MAX, 1, "°C"),
                vol.Required(CONF_MORNING_TIMEOUT): _number(30, 240, 15, "min"),
                vol.Required(CONF_TANK_MINIMUM): _number(TANK_TEMP_MIN, 45, 1, "°C"),
            }
        )
        current = {**DEFAULT_OPTIONS, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or current),
            errors=errors,
        )

    async def async_step_cop(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Second settings screen: weather and COP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            measured = user_input.get(CONF_COP_SOURCE) == COP_MEASURED
            a7 = user_input.get(CONF_COP_A7) or 0
            a2 = user_input.get(CONF_COP_A2) or 0
            if bool(a7) != bool(a2):
                errors["base"] = "datasheet_both"
            elif measured and not all(user_input.get(key) for key in MEASURE_SENSORS):
                errors["base"] = "measured_sensors_missing"
            elif measured and not (
                user_input.get(CONF_OUTDOOR_SENSOR) or user_input.get(CONF_WEATHER_ENTITY)
            ):
                errors["base"] = "outdoor_missing"
            else:
                # Optional entities left empty must be removed, not kept from before.
                data = {
                    key: value for key, value in self._data.items() if key not in OPTIONAL_COP_ENTITIES
                }
                return self.async_create_entry(data={**data, **user_input})

        schema = vol.Schema(
            {
                vol.Optional(CONF_WEATHER_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="weather")
                ),
                vol.Optional(CONF_OUTDOOR_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_HEATING_LWT): _number(25, 55, 1, "°C"),
                vol.Required(CONF_DHW_LWT): _number(40, 65, 1, "°C"),
                vol.Required(CONF_COP_A7): _number(0, 8, 0.05),
                vol.Required(CONF_COP_A2): _number(0, 8, 0.05),
                vol.Required(CONF_COP_SOURCE): SelectSelector(
                    SelectSelectorConfig(
                        options=COP_SOURCES,
                        mode=SelectSelectorMode.LIST,
                        translation_key=CONF_COP_SOURCE,
                    )
                ),
                vol.Optional(CONF_FLOW_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_SUPPLY_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_RETURN_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_POWER_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="power")
                ),
            }
        )
        return self.async_show_form(
            step_id="cop",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or self._data),
            errors=errors,
        )


MEASURE_SENSORS = (CONF_FLOW_SENSOR, CONF_SUPPLY_SENSOR, CONF_RETURN_SENSOR, CONF_POWER_SENSOR)
OPTIONAL_COP_ENTITIES = (CONF_WEATHER_ENTITY, CONF_OUTDOOR_SENSOR, *MEASURE_SENSORS)

