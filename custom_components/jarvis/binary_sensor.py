from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import JarvisEntitaet


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([Verbunden(entry)])


class Verbunden(JarvisEntitaet, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, entry) -> None:
        super().__init__(entry, "verbunden")

    @property
    def is_on(self) -> bool:
        return self.client.verbunden
