from __future__ import annotations

from homeassistant.components.event import EventEntity

from .const import EREIGNISSE
from .entity import JarvisEntitaet


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([Ereignisse(entry)])


class Ereignisse(JarvisEntitaet, EventEntity):
    _attr_event_types = list(EREIGNISSE)

    def __init__(self, entry) -> None:
        super().__init__(entry, "ereignisse")

    @property
    def available(self) -> bool:
        return self.client.verbunden

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.client.bei_ereignis(self._ereignis))

    def _ereignis(self, m: dict) -> None:
        if m.get("art") in EREIGNISSE:
            self._trigger_event(m["art"], {"id": m.get("id"), "name": m.get("name")})
            self.async_write_ha_state()
