"""Sensors that show what HeatShift plans and does."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatShiftConfigEntry
from .const import MODE_THERMOSTAT, STATUSES
from .planner import REASONS
from .entity import HeatShiftEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatShiftConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors."""
    controller = entry.runtime_data
    entities: list[SensorEntity] = [
        StatusSensor(controller, "status"),
        PlannedValueSensor(
            controller,
            "planned_setpoint" if controller.mode == MODE_THERMOSTAT else "planned_offset",
        ),
    ]
    entities.append(ReasonSensor(controller, "reason"))
    entities.append(CopSensor(controller, "cop_now"))
    entities.append(HeatCostSensor(controller, "heat_cost_now"))
    if controller.water_heater:
        entities.append(HotWaterStartSensor(controller, "hot_water_start"))
    async_add_entities(entities)


class StatusSensor(HeatShiftEntity, SensorEntity):
    """What HeatShift is doing right now."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES

    @property
    def native_value(self) -> str:
        """Return the status."""
        return self.controller.status


class PlannedValueSensor(HeatShiftEntity, SensorEntity):
    """Offset or room setpoint for the current quarter, with today's plan."""

    _attr_icon = "mdi:thermometer-lines"
    _attr_native_unit_of_measurement = "°C"
    # The plan changes daily and is large; keep it out of the history database.
    _unrecorded_attributes = frozenset({"plan"})

    @property
    def native_value(self) -> float:
        """Return the planned offset or setpoint."""
        return self.controller.target_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the price position and today's plan."""
        position = self.controller.position
        return {
            "mode": self.controller.mode,
            "change": self.controller.target_offset,
            "current_price": self.controller.current_price,
            "price_position": round(position, 3) if position is not None else None,
            "plan": self.controller.plan(),
        }


class HotWaterStartSensor(HeatShiftEntity, SensorEntity):
    """Start of today's cheapest hot-water block."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the planned start."""
        block = self.controller.dhw_block
        return block.start if block else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the end and the average price of the block."""
        block = self.controller.dhw_block
        if block is None:
            return {}
        return {"end": block.end.isoformat(), "average_heat_cost": round(block.average, 5)}


class CopSensor(HeatShiftEntity, SensorEntity):
    """COP used for planning right now (heating)."""

    _attr_icon = "mdi:heat-pump-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        """Return the COP for this moment."""
        cop = self.controller.cop_now
        return round(cop, 2) if cop else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the source and, when measuring, the live and learned values."""
        controller = self.controller
        attributes: dict[str, Any] = {
            "source": "measured" if controller.measuring else "estimate",
            "datasheet": controller.cop_model.has_datasheet,
        }
        if controller.measuring:
            outdoor, _ = controller._current_weather()
            attributes["live_cop"] = controller.live_cop
            attributes["measured_cop_this_temperature"] = (
                round(value, 2)
                if outdoor is not None
                and (value := controller.learned.measured_cop(outdoor)) is not None
                else None
            )
            attributes["learned_bins"] = len(controller.learned.bins)
        return attributes


class HeatCostSensor(HeatShiftEntity, SensorEntity):
    """What one kWh of heat costs right now: price divided by COP."""

    _attr_icon = "mdi:cash-clock"
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_suggested_display_precision = 3

    @property
    def native_value(self) -> float | None:
        """Return the heat cost."""
        cost = self.controller.heat_cost_now
        return round(cost, 4) if cost is not None else None


class ReasonSensor(HeatShiftEntity, SensorEntity):
    """Why HeatShift picks the current change, in plain words."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = REASONS
    _attr_icon = "mdi:comment-question-outline"

    @property
    def native_value(self) -> str:
        """Return the reason code (translated in the UI)."""
        return self.controller.reason

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the numbers behind the reason."""
        c = self.controller
        pct = lambda value: round(value * 100) if value is not None else None
        return {
            "change": c.target_offset,
            "heat_cost": round(c.heat_cost_now, 4) if c.heat_cost_now is not None else None,
            "reference_heat_cost": round(c.reference, 4) if c.reference else None,
            "reference_source": c.reference_source,
            "vs_reference_percent": pct(c.vs_reference),
            "day_spread_percent": pct(c.spread),
            "position_percent": pct(c.position),
            "history_days": len(c.daily),
        }
