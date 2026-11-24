from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.util import dt as dt_util

from .entity import JarvisEntitaet


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AktiveTimer(entry), NaechsterTimer(entry)])


def _ende(t: dict) -> datetime | None:
    try:
        return dt_util.parse_datetime(str(t.get("ende")))
    except (TypeError, ValueError):
        return None


class AktiveTimer(JarvisEntitaet, SensorEntity):
    _attr_icon = "mdi:timer-sand"

    def __init__(self, entry) -> None:
        super().__init__(entry, "aktive_timer")

    @property
    def available(self) -> bool:
        return self.client.verbunden

    @property
    def native_value(self) -> int:
        return len(self.client.timer)

    @property
    def extra_state_attributes(self) -> dict:
        return {"timer": [{k: t.get(k) for k in ("id", "name", "ende", "geraet")} for t in self.client.timer]}


class NaechsterTimer(JarvisEntitaet, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry) -> None:
        super().__init__(entry, "naechster_timer")

    @property
    def available(self) -> bool:
        return self.client.verbunden

    @property
    def native_value(self) -> datetime | None:
        enden = [e for e in map(_ende, self.client.timer) if e]
        return min(enden) if enden else None
