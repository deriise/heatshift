"""HeatShift: run your heat pump on the cheapest hours of a dynamic contract."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .controller import HeatShiftController

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR]

type HeatShiftConfigEntry = ConfigEntry[HeatShiftController]


async def async_setup_entry(hass: HomeAssistant, entry: HeatShiftConfigEntry) -> bool:
    """Set up HeatShift from a config entry."""
    controller = HeatShiftController(hass, entry)
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeatShiftConfigEntry) -> bool:
    """Unload a config entry and hand control back to the heat pump."""
    await entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: HeatShiftConfigEntry) -> None:
    """Reload after the settings change."""
    await hass.config_entries.async_reload(entry.entry_id)
