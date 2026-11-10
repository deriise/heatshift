"""Shared entity base for HeatShift."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .controller import HeatShiftController


class HeatShiftEntity(Entity):
    """Base entity linked to the HeatShift service device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: HeatShiftController, key: str) -> None:
        self.controller = controller
        entry_id = controller.entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="HeatShift",
            manufacturer="HeatShift",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Update when the controller has news."""
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.async_add_listener(self.async_write_ha_state))
