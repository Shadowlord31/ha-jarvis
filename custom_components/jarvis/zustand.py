"""Zustands-Push: leitet Aenderungen abonnierter Entitaeten an Jarvis weiter, aber nur solche, die das Gateway freigegeben hat.

Zustand und Attribute kommen aus `GET /entities/{id}` des Gateways (keine eigene Attributlogik hier).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .client import JarvisClient
from .const import ENTPRELLUNG_S, FREIGABE_INTERVALL_S
from .gateway_zugang import GatewayFehler, NichtErlaubt

_LOGGER = logging.getLogger(__name__)


class ZustandsPush:
    def __init__(self, hass: HomeAssistant, client: JarvisClient) -> None:
        self.hass, self.client = hass, client
        self.abo: set[str] = set()
        self.freigegeben: set[str] = set()
        self._wartend: dict[str, callable] = {}
        self._aus: list = []
        self._letzte_gesundheit: tuple | None = None

    def start(self) -> None:
        self._aus = [
            self.hass.bus.async_listen("state_changed", self._geaendert),
            self.client.bei_abo(self._neues_abo),
            async_track_time_interval(self.hass, self._regelmaessig, timedelta(seconds=FREIGABE_INTERVALL_S)),
        ]

    def stop(self) -> None:
        for aus in self._aus:
            aus()
        self._aus = []
        for abbrechen in self._wartend.values():
            abbrechen()
        self._wartend.clear()

    @callback
    def _neues_abo(self, eids: list[str]) -> None:
        self.abo = set(eids)
        self.hass.async_create_background_task(self.freigabe_laden(), "jarvis_freigabe")

    async def freigabe_laden(self) -> None:
        try:
            st, d = await self.client.gateway.anfrage("GET", "/entities")
        except (GatewayFehler, NichtErlaubt):
            return
        if st < 400:
            self.freigegeben = {e["entity_id"] for e in d.get("entities", []) if isinstance(e, dict) and e.get("entity_id")}

    async def _regelmaessig(self, _now=None) -> None:
        if not self.client.verbunden:
            return
        await self.freigabe_laden()
        ok, version = await self.client.gateway_gesundheit()
        if self._letzte_gesundheit is not None and self._letzte_gesundheit != (ok, version):
            await self.freigabe_laden()
        self._letzte_gesundheit = (ok, version)

    @callback
    def _geaendert(self, event: Event) -> None:
        eid = event.data.get("entity_id")
        if eid not in self.abo or eid not in self.freigegeben or eid in self._wartend or not self.client.verbunden:
            return

        @callback
        def los(_jetzt) -> None:
            self._los(eid)

        self._wartend[eid] = async_call_later(self.hass, ENTPRELLUNG_S, los)

    @callback
    def _los(self, eid: str) -> None:
        self._wartend.pop(eid, None)
        self.hass.async_create_background_task(self._senden(eid), "jarvis_zustand")

    async def _senden(self, eid: str) -> None:
        try:
            st, d = await self.client.gateway.anfrage("GET", f"/entities/{eid}")
            if st >= 400 or eid not in self.freigegeben:
                return
            await self.client.zustand_senden(eid, d.get("state"), d.get("attributes") or {})
        except Exception as e:  # noqa: BLE001 - ein Fehler bei einer Entitaet darf nichts anderes stoppen
            _LOGGER.debug("Zustand von %s nicht gesendet (%s)", eid, type(e).__name__)
