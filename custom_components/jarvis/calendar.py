"""Kalender: Termine, Geburtstage, Aufgaben und Dienst aus Jarvis (nur Anzeige)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import JarvisConfigEntry
from .const import KALENDER_QUELLEN
from .entity import JarvisEntitaet
from .kalender import als_zeit, ereignisse, grenzen


async def async_setup_entry(hass: HomeAssistant, entry: JarvisConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(JarvisKalender(entry, q) for q in KALENDER_QUELLEN)


class JarvisKalender(JarvisEntitaet, CalendarEntity):
    def __init__(self, entry: JarvisConfigEntry, quelle: str) -> None:
        super().__init__(entry, quelle)
        self.quelle = quelle
        self.daten = entry.runtime_data.kalender

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.daten.async_add_listener(self._daten_geaendert))

    @callback
    def _daten_geaendert(self) -> None:
        self.async_write_ha_state()
        aktualisieren = getattr(self, "async_update_event_listeners", None)
        if aktualisieren is not None:
            aktualisieren()

    @property
    def available(self) -> bool:
        return self.daten.verfuegbar(self.quelle)

    @property
    def event(self) -> CalendarEvent | None:
        """Laufender oder naechster Eintrag; wird bei jedem Zugriff gegen die aktuelle Zeit geprueft (auch nach Mitternacht)."""
        jetzt = dt_util.now()
        kommende = [e for e in (self.daten.data or {}).get(self.quelle, []) if als_zeit(e.end) > jetzt]
        return kommende[0] if kommende else None

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        if not self.available:
            return []
        von, bis = grenzen(start_date, end_date)
        d = await self.daten.client.abrufen_kalender(von, bis, [self.quelle])
        start, ende = dt_util.as_local(start_date), dt_util.as_local(end_date)
        return [e for e in ereignisse([x for x in d.get("eintraege") or [] if isinstance(x, dict)], self.quelle)
                if als_zeit(e.start) < ende and als_zeit(e.end) > start]
