"""Main switch: turns HeatShift steering on or off."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import HeatShiftConfigEntry
from .entity import HeatShiftEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatShiftConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the main switch."""
    async_add_entities([HeatShiftSwitch(entry.runtime_data, "steering")])


class HeatShiftSwitch(HeatShiftEntity, RestoreEntity, SwitchEntity):
    """Off by default. Off means the heat pump runs on its own settings."""

    _attr_icon = "mdi:heat-pump-outline"

    async def async_added_to_hass(self) -> None:
        """Restore the last state without sending commands."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.controller.restore_enabled(last.state == STATE_ON)

    @property
    def is_on(self) -> bool:
        """Return whether steering is on."""
        return self.controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start steering."""
        await self.controller.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop steering and hand control back."""
        await self.controller.async_set_enabled(False)
        self.async_write_ha_state()
