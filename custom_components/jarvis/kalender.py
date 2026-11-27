"""Kalenderdaten aus Jarvis: ein gemeinsamer Abruf fuer die vier Kalender-Entitaeten (nur lesen)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import JarvisClient, JarvisFehler
from .const import KALENDER_ENTPRELLUNG, KALENDER_INTERVALL, KALENDER_MAX_TAGE, KALENDER_QUELLEN

_LOGGER = logging.getLogger(__name__)
FMT = "%Y-%m-%d %H:%M"


def zu_ereignis(e: dict) -> CalendarEvent | None:
    """Ein Eintrag aus Jarvis als CalendarEvent (Ortszeit von HA, ganztaegig als date). Unbrauchbares wird uebergangen."""
    try:
        if e.get("ganztaegig"):
            beginn, ende = date.fromisoformat(str(e["beginn"])[:10]), date.fromisoformat(str(e["ende"])[:10])
        else:
            zone = dt_util.get_default_time_zone()
            beginn = datetime.strptime(e["beginn"], FMT).replace(tzinfo=zone)
            ende = datetime.strptime(e["ende"], FMT).replace(tzinfo=zone)
        if ende <= beginn:
            return None
        return CalendarEvent(start=beginn, end=ende, summary=str(e.get("titel") or ""), description=e.get("beschreibung") or None,
                             location=e.get("ort") or None, uid=str(e["uid"]) if e.get("uid") else None)
    except (KeyError, ValueError, TypeError):
        _LOGGER.debug("Kalendereintrag uebersprungen: %r", e)
        return None


def als_zeit(wert: date | datetime) -> datetime:
    return wert if isinstance(wert, datetime) else dt_util.start_of_local_day(wert)


def ereignisse(eintraege: list[dict], quelle: str) -> list[CalendarEvent]:
    erg = [z for e in eintraege if e.get("quelle") == quelle and (z := zu_ereignis(e))]
    erg.sort(key=lambda z: (als_zeit(z.start), als_zeit(z.end)))
    return erg


class KalenderDaten(DataUpdateCoordinator[dict]):
    """Fenster gestern bis heute + 14 Tage; Abruf alle 5 Minuten, nach dem Verbinden und bei kalender_geaendert."""

    def __init__(self, hass: HomeAssistant, client: JarvisClient) -> None:
        super().__init__(hass, _LOGGER, name=f"Jarvis Kalender ({client.instanz})", update_interval=KALENDER_INTERVALL,
                         request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=KALENDER_ENTPRELLUNG, immediate=True))
        self.client = client
        self.quellen: list[str] = []
        self.unterstuetzt = True
        self._gewarnt: set[str] = set()

    async def _async_update_data(self) -> dict:
        heute = dt_util.now().date()
        try:
            d = await self.client.abrufen_kalender(heute - timedelta(days=1), heute + timedelta(days=14))
        except JarvisFehler as e:
            if e.code == "not_connected":
                return self.data or {}
            if e.code == "unknown_action":
                self.unterstuetzt, self.quellen = False, []
                if "unknown_action" not in self._gewarnt:
                    self._gewarnt.add("unknown_action")
                    _LOGGER.warning("Jarvis (%s) kennt den Befehl kalender_lesen nicht (aelterer Stand): Kalender nicht verfuegbar", self.client.instanz)
                return {}
            raise UpdateFailed(f"Jarvis-Kalender: {e}") from e
        self.unterstuetzt = True
        self._gewarnt.discard("unknown_action")
        quellen = [q for q in (d.get("quellen") or []) if q in KALENDER_QUELLEN]
        for q in KALENDER_QUELLEN:
            if q in quellen:
                self._gewarnt.discard(q)
            elif q not in self._gewarnt:
                self._gewarnt.add(q)
                _LOGGER.warning("Jarvis (%s): Kalenderquelle %s ist nicht aktiv (Modul in Jarvis pruefen)", self.client.instanz, q)
        self.quellen = quellen
        liste = [e for e in (d.get("eintraege") or []) if isinstance(e, dict)]
        return {q: ereignisse(liste, q) for q in quellen}

    def verfuegbar(self, quelle: str) -> bool:
        return self.client.verbunden and self.last_update_success and self.unterstuetzt and quelle in self.quellen


def grenzen(start: datetime, ende: datetime) -> tuple[date, date]:
    """Inklusive Tage (Ortszeit) fuer einen Zeitraum [start, ende), auf KALENDER_MAX_TAGE gekuerzt."""
    von = dt_util.as_local(start).date()
    bis = dt_util.as_local(ende - timedelta(microseconds=1)).date()
    return von, min(max(bis, von), von + timedelta(days=KALENDER_MAX_TAGE - 1))
