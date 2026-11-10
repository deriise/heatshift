"""The HeatShift controller: plans and steers the heat pump."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from .const import (
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
from .planner import (
    Block,
    PriceSlot,
    cheapest_block,
    current_slot,
    offset_for_position,
    offset_plan,
    parse_prices,
    price_position,
    slots_for_day,
)

_LOGGER = logging.getLogger(__name__)

HEATING_MODE = "heat"


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

        self.enabled = False
        self.slots: list[PriceSlot] = []
        self.target_offset = 0
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
        self._notify()

    async def async_stop(self) -> None:
        """Remove listeners and hand control back to the heat pump."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()
        if self._dhw_unsub:
            self._dhw_unsub()
            self._dhw_unsub = None
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

    # ----- planning --------------------------------------------------------

    def _read_prices(self) -> None:
        state = self.hass.states.get(self.price_sensor)
        self.slots = parse_prices(state.attributes) if state else []

    def _compute_target(self) -> int:
        now = dt_util.now()
        day_slots = slots_for_day(self.slots, now.date())
        slot = current_slot(day_slots, now)
        if slot is None:
            self.current_price = None
            self.position = None
            return 0
        self.current_price = slot.price
        self.position = price_position(day_slots, slot.price)
        target = offset_for_position(
            self.position,
            self.options[CONF_EXPENSIVE_THRESHOLD],
            int(self.options[CONF_EXPENSIVE_OFFSET]),
            self.options[CONF_CHEAP_THRESHOLD],
            int(self.options[CONF_CHEAP_OFFSET]),
        )
        return max(OFFSET_MIN, min(OFFSET_MAX, target))

    def plan(self) -> list[dict[str, Any]]:
        """Today's offset plan, for the sensor attributes and dashboard card."""
        return [
            {"start": slot.start.isoformat(), "price": slot.price, "offset": offset}
            for slot, offset in offset_plan(
                self.slots,
                dt_util.now().date(),
                self.options[CONF_EXPENSIVE_THRESHOLD],
                int(self.options[CONF_EXPENSIVE_OFFSET]),
                self.options[CONF_CHEAP_THRESHOLD],
                int(self.options[CONF_CHEAP_OFFSET]),
            )
        ]

    def _plan_dhw(self) -> None:
        if self._dhw_unsub:
            self._dhw_unsub()
            self._dhw_unsub = None
        self.dhw_block = None
        if not self.water_heater or not self.options[CONF_DHW_ENABLED]:
            return
        self.dhw_block = cheapest_block(
            self.slots,
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
        self.target_offset = self._compute_target()

        if not self.enabled:
            self.status = STATUS_OFF
        elif self.current_price is None:
            self.status = STATUS_NO_PRICES
        else:
            self.status = STATUS_ACTIVE

        if self.enabled:
            await self._async_apply_offset(self.target_offset)
            await self._async_tank_guard()
        self._notify()

    async def _async_apply_offset(self, target: int) -> None:
        state = self.hass.states.get(self.offset_entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if state.state != HEATING_MODE:
            # Heating is off or cooling: leave the heat pump alone.
            self.status = STATUS_HEATING_OFF
            return
        try:
            current = int(float(state.attributes.get(ATTR_TEMPERATURE, 0)))
        except (TypeError, ValueError):
            current = None
        if current == target:
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
        """Hand control back: offset 0 and the water heater on normal."""
        if self._morning_unsubs:
            await self._async_morning_finish()
        state = self.hass.states.get(self.offset_entity)
        if state and state.state == HEATING_MODE:
            try:
                current = int(float(state.attributes.get(ATTR_TEMPERATURE, 0)))
            except (TypeError, ValueError):
                current = None
            if current != 0:
                await self._async_call(
                    "climate",
                    "set_temperature",
                    {ATTR_ENTITY_ID: self.offset_entity, ATTR_TEMPERATURE: 0},
                )
        if self._boost_by_us and self._water_heater_mode() == MODE_BOOST:
            await self._async_set_mode(MODE_NORMAL)
        self._boost_by_us = False

    async def _async_call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("HeatShift could not call %s.%s: %s", domain, service, err)
