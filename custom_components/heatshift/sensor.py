"""Sensors that show what HeatShift plans and does."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatShiftConfigEntry
from .const import STATUSES
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
        PlannedOffsetSensor(controller, "planned_offset"),
    ]
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


class PlannedOffsetSensor(HeatShiftEntity, SensorEntity):
    """Offset for the current quarter, with today's plan as attribute."""

    _attr_icon = "mdi:thermometer-lines"
    _attr_native_unit_of_measurement = "°C"
    # The plan changes daily and is large; keep it out of the history database.
    _unrecorded_attributes = frozenset({"plan"})

    @property
    def native_value(self) -> int:
        """Return the planned offset."""
        return self.controller.target_offset

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the price position and today's plan."""
        position = self.controller.position
        return {
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
        return {"end": block.end.isoformat(), "average_price": round(block.average, 5)}
