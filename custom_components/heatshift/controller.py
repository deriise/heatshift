"""The HeatShift controller: plans and steers the heat pump."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_interval,
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

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
    DOMAIN,
    CONF_BASE_TEMP,
    CONF_CONTROL_MODE,
    CONF_THERMO_CHEAP_DELTA,
    CONF_THERMO_EXPENSIVE_DELTA,
    CONF_THERMO_MAX,
    CONF_THERMO_MIN,
    MODE_OFFSET,
    MODE_THERMOSTAT,
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
    MODE_BOOST,
    MODE_NORMAL,
    OFFSET_MAX,
    OFFSET_MIN,
    STATUS_ACTIVE,
    STATUS_HEATING_OFF,
    STATUS_NO_PRICES,
    STATUS_OFF,
)
from .copmodel import CopModel, LearnedCorrection, heat_kw
from .planner import (
    Block,
    PriceSlot,
    cheapest_block,
    offset_for_position,
    offset_plan,
    parse_prices,
    price_position,
    thermostat_setpoint,
)

_LOGGER = logging.getLogger(__name__)

HEATING_MODE = "heat"
STORE_VERSION = 1
SAMPLE_INTERVAL = timedelta(minutes=1)
# HVAC modes in which a room thermostat may be shifted.
THERMOSTAT_MODES = ("heat", "heat_cool", "auto")


def _parse_time(value: str, fallback: str) -> time:
    return dt_util.parse_time(value) or dt_util.parse_time(fallback) or time(0, 0)


class HeatShiftController:
    """Plans per quarter and sends commands within fixed limits."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.price_sensor: str = entry.data[CONF_PRICE_SENSOR]
        self.offset_entity: str = entry.data[CONF_OFFSET_ENTITY]
        self.water_heater: str | None = entry.data.get(CONF_WATER_HEATER)
        self.tank_sensor: str | None = entry.data.get(CONF_TANK_SENSOR)
        self.options: dict[str, Any] = {**DEFAULT_OPTIONS, **entry.options}
        self.mode: str = entry.data.get(CONF_CONTROL_MODE, MODE_OFFSET)

        self.enabled = False
        self.slots: list[PriceSlot] = []
        self.target_offset = 0
        # The value that is sent: an offset, or a room setpoint in thermostat mode.
        self.target_value: float = self._neutral_value()
        self.position: float | None = None
        self.current_price: float | None = None
        self.dhw_block: Block | None = None
        self.status = STATUS_OFF

        self._listeners: list[CALLBACK_TYPE] = []
        self._update_callbacks: set[Callable[[], None]] = set()
        self._dhw_unsub: CALLBACK_TYPE | None = None
        self._morning_unsubs: list[CALLBACK_TYPE] = []
        self._morning_restore_setpoint: float | None = None
        self._boost_by_us = False

        # COP
        self.cop_model = CopModel(
            cop_a7=float(self.options[CONF_COP_A7]) or None,
            cop_a2=float(self.options[CONF_COP_A2]) or None,
        )
        self.learned = LearnedCorrection()
        self.measuring: bool = self.options[CONF_COP_SOURCE] == COP_MEASURED
        self.forecast: list[tuple[datetime, float, float | None]] = []
        self.cop_now: float | None = None
        self.heat_cost_now: float | None = None
        self.live_cop: float | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.cop"
        )

    # ----- entity updates -------------------------------------------------

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        """Register an entity update callback."""
        self._update_callbacks.add(update)
        return lambda: self._update_callbacks.discard(update)

    @callback
    def _notify(self) -> None:
        for update in list(self._update_callbacks):
            update()

    # ----- lifecycle -------------------------------------------------------

    async def async_start(self) -> None:
        """Subscribe to time and state events."""
        self.learned = LearnedCorrection.from_dict(await self._store.async_load())
        await self._async_update_forecast()
        self._listeners.append(
            async_track_time_change(self.hass, self._handle_hourly, minute=2, second=0)
        )
        if self.measuring:
            self._listeners.append(
                async_track_time_interval(self.hass, self._handle_sample, SAMPLE_INTERVAL)
            )
        self._listeners.append(
            async_track_time_change(
                self.hass, self._handle_quarter, minute=[0, 15, 30, 45], second=30
            )
        )
        self._listeners.append(
            async_track_time_change(self.hass, self._handle_midnight, hour=0, minute=5, second=0)
        )
        self._listeners.append(
            async_track_state_change_event(
                self.hass, [self.price_sensor], self._handle_price_change
            )
        )
        morning = _parse_time(
            self.options[CONF_MORNING_TIME], DEFAULT_OPTIONS[CONF_MORNING_TIME]
        )
        self._listeners.append(
            async_track_time_change(
                self.hass,
                self._handle_morning,
                hour=morning.hour,
                minute=morning.minute,
                second=0,
            )
        )
        self._read_prices()
        self._plan_dhw()
        self._refresh_target()
        self._notify()

    async def async_stop(self) -> None:
        """Remove listeners and hand control back to the heat pump."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()
        if self._dhw_unsub:
            self._dhw_unsub()
            self._dhw_unsub = None
        if self.measuring:
            await self._store.async_save(self.learned.to_dict())
        if self.enabled:
            await self._async_release()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Turn steering on or off."""
        self.enabled = enabled
        if enabled:
            await self._async_tick()
        else:
            await self._async_release()
            self.status = STATUS_OFF
            self._notify()

    @callback
    def restore_enabled(self, enabled: bool) -> None:
        """Restore the switch state after a restart, without sending commands."""
        self.enabled = enabled

    # ----- event handlers --------------------------------------------------

    async def _handle_quarter(self, now: datetime) -> None:
        await self._async_tick()

    async def _handle_midnight(self, now: datetime) -> None:
        self._read_prices()
        self._plan_dhw()
        self._notify()

    async def _handle_price_change(self, event: Event[EventStateChangedData]) -> None:
        self._read_prices()
        self._plan_dhw()
        await self._async_tick()

    async def _handle_morning(self, now: datetime) -> None:
        await self._async_morning_check()

    async def _handle_hourly(self, now: datetime) -> None:
        await self._async_update_forecast()
        self._plan_dhw()
        self._refresh_target()
        self._notify()

    async def _handle_sample(self, now: datetime) -> None:
        self._sample_cop()

    # ----- weather and COP -------------------------------------------------

    async def _async_update_forecast(self) -> None:
        """Fetch the hourly weather forecast for the COP per quarter."""
        weather = self.options.get(CONF_WEATHER_ENTITY)
        if not weather:
            self.forecast = []
            return
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {ATTR_ENTITY_ID: weather, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("HeatShift could not read the weather forecast: %s", err)
            return
        items = ((response or {}).get(weather) or {}).get("forecast") or []
        forecast: list[tuple[datetime, float, float | None]] = []
        for item in items:
            when = dt_util.parse_datetime(str(item.get("datetime", "")))
            temperature = item.get("temperature")
            if when is None or temperature is None:
                continue
            humidity = item.get("humidity")
            forecast.append(
                (
                    dt_util.as_local(when),
                    float(temperature),
                    float(humidity) if humidity is not None else None,
                )
            )
        self.forecast = sorted(forecast)

    def _float_state(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        try:
            return float(state.state) if state else None
        except (TypeError, ValueError):
            return None

    def _current_weather(self) -> tuple[float | None, float | None]:
        """Outdoor temperature and humidity right now."""
        temperature = self._float_state(self.options.get(CONF_OUTDOOR_SENSOR))
        humidity = None
        weather = self.options.get(CONF_WEATHER_ENTITY)
        state = self.hass.states.get(weather) if weather else None
        if state:
            if temperature is None:
                try:
                    temperature = float(state.attributes.get("temperature"))
                except (TypeError, ValueError):
                    temperature = None
            try:
                humidity = float(state.attributes.get("humidity"))
            except (TypeError, ValueError):
                humidity = None
        return temperature, humidity

    def _weather_at(self, when: datetime) -> tuple[float | None, float | None]:
        """Forecast temperature and humidity for a moment."""
        best: tuple[datetime, float, float | None] | None = None
        for item in self.forecast:
            if item[0] <= when < item[0] + timedelta(hours=1):
                best = item
                break
        if best is not None:
            return best[1], best[2]
        if abs((when - dt_util.now()).total_seconds()) <= 3600:
            return self._current_weather()
        return None, None

    def _cop_at(self, when: datetime, lwt: float) -> float | None:
        outdoor, humidity = self._weather_at(when)
        if outdoor is None:
            return None
        if self.measuring:
            return self.learned.cop(self.cop_model, outdoor, lwt, humidity)
        return self.cop_model.estimate(outdoor, lwt, humidity)

    def _cost_slots(self, lwt: float) -> list[tuple[PriceSlot, float | None, PriceSlot]]:
        """Per slot: the price slot, its COP, and a slot with the heat cost as price.

        Without a COP for a slot the average COP of the other slots is used.
        Without any COP the heat cost equals the price, so planning falls back
        to planning on price.
        """
        cops = [self._cop_at(slot.start, lwt) for slot in self.slots]
        known = [cop for cop in cops if cop]
        fill = sum(known) / len(known) if known else 1.0
        result = []
        for slot, cop in zip(self.slots, cops):
            used = cop or fill
            result.append(
                (slot, cop, PriceSlot(start=slot.start, end=slot.end, price=slot.price / used))
            )
        return result

    def _sample_cop(self) -> None:
        """Add one minute of measurements to the learned COP curve."""
        outdoor, humidity = self._current_weather()
        flow = self._flow_l_per_min()
        supply = self._float_state(self.options.get(CONF_SUPPLY_SENSOR))
        return_ = self._float_state(self.options.get(CONF_RETURN_SENSOR))
        power = self._power_kw()
        if None in (outdoor, flow, supply, return_, power):
            self.live_cop = None
            return
        heat = heat_kw(flow, supply, return_)
        self.live_cop = round(heat / power, 2) if power > 0.2 and heat > 0 else None
        if self.learned.add_sample(
            self.cop_model, outdoor, humidity, supply, return_, flow, power, 1 / 60
        ):
            self._store.async_delay_save(self.learned.to_dict, 600)

    def _flow_l_per_min(self) -> float | None:
        entity_id = self.options.get(CONF_FLOW_SENSOR)
        value = self._float_state(entity_id)
        if value is None:
            return None
        unit = (self.hass.states.get(entity_id).attributes.get("unit_of_measurement") or "").lower()
        if unit in ("l/h", "lph"):
            return value / 60
        if unit in ("m³/h", "m3/h"):
            return value * 1000 / 60
        return value

    def _power_kw(self) -> float | None:
        entity_id = self.options.get(CONF_POWER_SENSOR)
        value = self._float_state(entity_id)
        if value is None:
            return None
        unit = (self.hass.states.get(entity_id).attributes.get("unit_of_measurement") or "").lower()
        return value if unit == "kw" else value / 1000

    # ----- planning --------------------------------------------------------

    def _read_prices(self) -> None:
        state = self.hass.states.get(self.price_sensor)
        self.slots = parse_prices(state.attributes) if state else []

    def _changes(self) -> tuple[float, float]:
        """Change for expensive and for cheap prices, for the active mode."""
        if self.mode == MODE_THERMOSTAT:
            return (
                float(self.options[CONF_THERMO_EXPENSIVE_DELTA]),
                float(self.options[CONF_THERMO_CHEAP_DELTA]),
            )
        return (
            int(self.options[CONF_EXPENSIVE_OFFSET]),
            int(self.options[CONF_CHEAP_OFFSET]),
        )

    def _neutral_value(self) -> float:
        """Value without any shift: offset 0 or the base temperature."""
        if self.mode == MODE_THERMOSTAT:
            return self._value_for(0)
        return 0

    def _value_for(self, change: float) -> float:
        """Turn a change into the value to send, within the hard limits."""
        if self.mode == MODE_THERMOSTAT:
            return thermostat_setpoint(
                float(self.options[CONF_BASE_TEMP]),
                change,
                float(self.options[CONF_THERMO_MIN]),
                float(self.options[CONF_THERMO_MAX]),
            )
        return max(OFFSET_MIN, min(OFFSET_MAX, int(change)))

    def _compute_target(self) -> float:
        now = dt_util.now()
        lwt = float(self.options[CONF_HEATING_LWT])
        self.cop_now = self._cop_at(now, lwt)
        costs = [item for item in self._cost_slots(lwt) if item[0].start.date() == now.date()]
        day_costs = [item[2] for item in costs]
        index = next(
            (i for i, item in enumerate(costs) if item[0].start <= now < item[0].end), None
        )
        if index is None:
            self.current_price = None
            self.heat_cost_now = None
            self.position = None
            return 0
        self.current_price = costs[index][0].price
        self.heat_cost_now = costs[index][2].price if self.cop_now else None
        self.position = price_position(day_costs, costs[index][2].price)
        expensive, cheap = self._changes()
        return offset_for_position(
            self.position,
            self.options[CONF_EXPENSIVE_THRESHOLD],
            expensive,
            self.options[CONF_CHEAP_THRESHOLD],
            cheap,
        )

    def _refresh_target(self) -> None:
        """Compute the value for this quarter and the status, without sending it."""
        self.target_offset = self._compute_target()
        self.target_value = self._value_for(self.target_offset)
        if not self.enabled:
            self.status = STATUS_OFF
        elif self.current_price is None:
            self.status = STATUS_NO_PRICES
        else:
            self.status = STATUS_ACTIVE

    def plan(self) -> list[dict[str, Any]]:
        """Today's plan, for the sensor attributes and dashboard card."""
        expensive, cheap = self._changes()
        today = dt_util.now().date()
        costs = [
            item
            for item in self._cost_slots(float(self.options[CONF_HEATING_LWT]))
            if item[0].start.date() == today
        ]
        changes = offset_plan(
            [item[2] for item in costs],
            today,
            self.options[CONF_EXPENSIVE_THRESHOLD],
            expensive,
            self.options[CONF_CHEAP_THRESHOLD],
            cheap,
        )
        return [
            {
                "start": slot.start.isoformat(),
                "price": slot.price,
                "cop": round(cop, 2) if cop else None,
                "heat_cost": round(cost.price, 4),
                "change": change,
                "value": self._value_for(change),
            }
            for (slot, cop, cost), (_, change) in zip(costs, changes)
        ]

    def _plan_dhw(self) -> None:
        if self._dhw_unsub:
            self._dhw_unsub()
            self._dhw_unsub = None
        self.dhw_block = None
        if not self.water_heater or not self.options[CONF_DHW_ENABLED]:
            return
        dhw_costs = [item[2] for item in self._cost_slots(float(self.options[CONF_DHW_LWT]))]
        self.dhw_block = cheapest_block(
            dhw_costs,
            dt_util.now().date(),
            _parse_time(self.options[CONF_DHW_WINDOW_START], DEFAULT_OPTIONS[CONF_DHW_WINDOW_START]),
            _parse_time(self.options[CONF_DHW_WINDOW_END], DEFAULT_OPTIONS[CONF_DHW_WINDOW_END]),
            int(self.options[CONF_DHW_BLOCK_MINUTES]),
        )
        if self.dhw_block and self.dhw_block.start > dt_util.now():
            self._dhw_unsub = async_track_point_in_time(
                self.hass, self._handle_dhw_start, self.dhw_block.start
            )

    # ----- steering --------------------------------------------------------

    async def _async_tick(self) -> None:
        self._read_prices()
        self._refresh_target()

        if self.enabled:
            await self._async_apply(self.target_value)
            await self._async_tank_guard()
        self._notify()

    def _may_steer(self, hvac_state: str) -> bool:
        if self.mode == MODE_THERMOSTAT:
            return hvac_state in THERMOSTAT_MODES
        return hvac_state == HEATING_MODE

    async def _async_apply(self, target: float, *, release: bool = False) -> None:
        """Send the value to the climate entity if it differs."""
        state = self.hass.states.get(self.offset_entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if not self._may_steer(state.state):
            # Heating is off or cooling: leave the heat pump alone.
            if not release:
                self.status = STATUS_HEATING_OFF
            return
        try:
            current: float | None = float(state.attributes.get(ATTR_TEMPERATURE))
        except (TypeError, ValueError):
            current = None
        if current is not None and abs(current - target) < 0.05:
            return
        await self._async_call(
            "climate",
            "set_temperature",
            {ATTR_ENTITY_ID: self.offset_entity, ATTR_TEMPERATURE: target},
        )

    def _tank_temperature(self) -> float | None:
        if self.tank_sensor:
            state = self.hass.states.get(self.tank_sensor)
            value = state.state if state else None
        elif self.water_heater:
            state = self.hass.states.get(self.water_heater)
            value = state.attributes.get("current_temperature") if state else None
        else:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _water_heater_mode(self) -> str | None:
        if not self.water_heater:
            return None
        state = self.hass.states.get(self.water_heater)
        return state.state if state else None

    async def _async_set_mode(self, mode: str) -> None:
        await self._async_call(
            "water_heater",
            "set_operation_mode",
            {ATTR_ENTITY_ID: self.water_heater, "operation_mode": mode},
        )

    async def _async_tank_guard(self) -> None:
        """Always heat when the tank drops below the safety minimum."""
        if not self.water_heater:
            return
        tank = self._tank_temperature()
        if tank is None or tank >= float(self.options[CONF_TANK_MINIMUM]):
            return
        if self._water_heater_mode() == MODE_BOOST:
            return
        _LOGGER.info("Tank at %.1f °C is below the minimum, heating now", tank)
        await self._async_set_mode(MODE_BOOST)
        self._boost_by_us = True

    async def _handle_dhw_start(self, now: datetime) -> None:
        self._dhw_unsub = None
        if not self.enabled or not self.water_heater:
            return
        tank = self._tank_temperature()
        if tank is None or tank >= float(self.options[CONF_DHW_REHEAT_BELOW]):
            return
        await self._async_set_mode(MODE_BOOST)
        self._boost_by_us = True
        self._notify()

    async def _async_morning_check(self) -> None:
        if not (self.enabled and self.water_heater and self.options[CONF_MORNING_ENABLED]):
            return
        if self._morning_unsubs:
            return
        tank = self._tank_temperature()
        if tank is None or tank >= float(self.options[CONF_MORNING_BELOW]):
            return

        target = float(self.options[CONF_MORNING_TARGET])
        state = self.hass.states.get(self.water_heater)
        self._morning_restore_setpoint = (
            state.attributes.get(ATTR_TEMPERATURE) if state else None
        )
        await self._async_call(
            "water_heater",
            "set_temperature",
            {ATTR_ENTITY_ID: self.water_heater, ATTR_TEMPERATURE: target},
        )
        await self._async_set_mode(MODE_BOOST)
        self._boost_by_us = True

        @callback
        def _progress(event: Event[EventStateChangedData]) -> None:
            reached = self._tank_temperature()
            if reached is not None and reached >= target:
                self.hass.async_create_task(self._async_morning_finish())

        watch = self.tank_sensor or self.water_heater
        self._morning_unsubs.append(
            async_track_state_change_event(self.hass, [watch], _progress)
        )
        self._morning_unsubs.append(
            async_call_later(
                self.hass,
                int(self.options[CONF_MORNING_TIMEOUT]) * 60,
                self._handle_morning_timeout,
            )
        )

    async def _handle_morning_timeout(self, now: datetime) -> None:
        await self._async_morning_finish()

    async def _async_morning_finish(self) -> None:
        if not self._morning_unsubs:
            return
        for unsub in self._morning_unsubs:
            unsub()
        self._morning_unsubs.clear()
        await self._async_set_mode(MODE_NORMAL)
        self._boost_by_us = False
        if self._morning_restore_setpoint is not None:
            await self._async_call(
                "water_heater",
                "set_temperature",
                {
                    ATTR_ENTITY_ID: self.water_heater,
                    ATTR_TEMPERATURE: self._morning_restore_setpoint,
                },
            )
            self._morning_restore_setpoint = None

    async def _async_release(self) -> None:
        """Hand control back: offset 0 or base temperature, water heater normal."""
        if self._morning_unsubs:
            await self._async_morning_finish()
        await self._async_apply(self._neutral_value(), release=True)
        if self._boost_by_us and self._water_heater_mode() == MODE_BOOST:
            await self._async_set_mode(MODE_NORMAL)
        self._boost_by_us = False

    async def _async_call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("HeatShift could not call %s.%s: %s", domain, service, err)
