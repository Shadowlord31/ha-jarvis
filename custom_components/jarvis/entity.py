from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_INSTANZ, DOMAIN, VERSION


class JarvisEntitaet(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, schluessel: str) -> None:
        self.client = entry.runtime_data.client
        self._attr_unique_id = f"{entry.entry_id}_{schluessel}"
        instanz = entry.data[CONF_INSTANZ]
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=f"Jarvis ({instanz})",
                                            manufacturer="Shadowlord31", model="Jarvis", sw_version=VERSION)
        self._attr_translation_key = schluessel

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.client.bei_status(self.async_write_ha_state))
