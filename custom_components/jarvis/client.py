"""Verbindung zu Jarvis: eine ausgehende WebSocket-Leitung (`/ws/ha`) mit Reconnect (Backoff 1 s bis 60 s)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable

import aiohttp
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (BACKOFF_MAX, BACKOFF_START, BEFEHL_ZEIT, NICHT_ERREICHBAR, VERBINDEN_ZEIT, VERSION)
from .gateway_zugang import GatewayFehler, GatewayZugang, NichtErlaubt

_LOGGER = logging.getLogger(__name__)


class JarvisFehler(HomeAssistantError):
    """Jarvis hat einen Befehl abgelehnt (code und text kommen von Jarvis)."""

    def __init__(self, code: str, text: str):
        super().__init__(text)
        self.code = code


def ws_adresse(url: str) -> str:
    """Normalisiert die Eingabe: ws:// oder wss:// (http/https werden umgesetzt), Pfad /ws/ha, keine Query."""
    url = str(url or "").strip()
    if url.startswith("http://"):
        url = "ws://" + url[7:]
    elif url.startswith("https://"):
        url = "wss://" + url[8:]
    if not url.startswith(("ws://", "wss://")):
        raise ValueError("Adresse muss mit ws:// oder wss:// beginnen")
    url = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return url if url.endswith("/ws/ha") else url + "/ws/ha"


class JarvisClient:
    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession, instanz: str, url: str, token: str,
                 gateway: GatewayZugang) -> None:
        self.hass, self.session, self.instanz = hass, session, instanz
        self._url, self._token = ws_adresse(url), token
        self.gateway = gateway
        self.verbunden = False
        self.timer: list[dict] = []
        self.gateway_ok: bool | None = None
        self.gateway_version = ""
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._offen: dict[str, asyncio.Future] = {}
        self._hintergrund: set[asyncio.Task] = set()
        self._bei_status: list[Callable[[], None]] = []
        self._bei_ereignis: list[Callable[[dict], None]] = []
        self._bei_abo: list[Callable[[list[str]], None]] = []
        self._bei_verbunden: list[Callable[[], None]] = []
        self._bei_kalender: list[Callable[[], None]] = []
        self._sende_sperre = asyncio.Lock()

    # ---- Abos der Entitaeten
    @callback
    def bei_status(self, fn: Callable[[], None]) -> Callable[[], None]:
        self._bei_status.append(fn)
        return lambda: self._bei_status.remove(fn)

    @callback
    def bei_ereignis(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        self._bei_ereignis.append(fn)
        return lambda: self._bei_ereignis.remove(fn)

    @callback
    def bei_abo(self, fn: Callable[[list[str]], None]) -> Callable[[], None]:
        self._bei_abo.append(fn)
        return lambda: self._bei_abo.remove(fn)

    @callback
    def bei_verbunden(self, fn: Callable[[], None]) -> Callable[[], None]:
        """Wird nach jedem (Wieder-)Verbinden aufgerufen, sobald das Hallo gesendet ist."""
        self._bei_verbunden.append(fn)
        return lambda: self._bei_verbunden.remove(fn)

    @callback
    def bei_kalender(self, fn: Callable[[], None]) -> Callable[[], None]:
        self._bei_kalender.append(fn)
        return lambda: self._bei_kalender.remove(fn)

    def _status_melden(self) -> None:
        for fn in list(self._bei_status):
            fn()

    # ---- Lebenslauf
    def start(self) -> None:
        self._task = self.hass.async_create_background_task(self._lauf(), f"jarvis_{self.instanz}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for t in list(self._hintergrund):
            t.cancel()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._abbauen()

    def _abbauen(self) -> None:
        self.verbunden = False
        self.timer = []
        for z in self._offen.values():
            if not z.done():
                z.set_exception(JarvisFehler("not_connected", NICHT_ERREICHBAR))
        self._offen.clear()
        self._ws = None

    async def _lauf(self) -> None:
        wartezeit = BACKOFF_START
        while True:
            try:
                async with self.session.ws_connect(
                    self._url, headers={"Authorization": f"Bearer {self._token}"},
                    params={"instanz": self.instanz, "version": VERSION}, timeout=aiohttp.ClientWSTimeout(ws_close=VERBINDEN_ZEIT),
                    heartbeat=None, max_msg_size=4 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self.verbunden = True
                    wartezeit = BACKOFF_START
                    _LOGGER.info("Jarvis (%s): verbunden", self.instanz)
                    self._status_melden()
                    await self._hallo()
                    for fn in list(self._bei_verbunden):
                        fn()
                    await self._empfangen(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _LOGGER.debug("Jarvis (%s): Verbindung beendet (%s)", self.instanz, type(e).__name__, exc_info=True)
            if self.verbunden:
                _LOGGER.warning("Jarvis (%s): Verbindung getrennt, neuer Versuch in %s s", self.instanz, wartezeit)
            self._abbauen()
            self._status_melden()
            await asyncio.sleep(wartezeit)
            wartezeit = min(BACKOFF_MAX, wartezeit * 2)

    async def _empfangen(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                m = json.loads(msg.data)
            except ValueError:
                continue
            if isinstance(m, dict):
                self._verteilen(m)

    def _verteilen(self, m: dict) -> None:
        typ = m.get("typ")
        if typ == "ping":
            self._spaeter(self._senden({"typ": "pong"}))
        elif typ == "timer":
            self.timer = [t for t in (m.get("liste") or []) if isinstance(t, dict)]
            self._status_melden()
        elif typ == "ereignis":
            for fn in list(self._bei_ereignis):
                fn(m)
        elif typ == "kalender_geaendert":
            for fn in list(self._bei_kalender):
                fn()
        elif typ == "gateway":
            self._spaeter(self._gateway(m))
        elif typ == "abo":
            self._spaeter(self._abo(m))
        elif isinstance(m.get("id"), str) and (z := self._offen.get(m["id"])) is not None and not z.done():
            z.set_result(m)

    def _spaeter(self, coro) -> None:
        t = self.hass.async_create_background_task(coro, "jarvis_nachricht")
        self._hintergrund.add(t)
        t.add_done_callback(self._hintergrund.discard)

    async def _senden(self, daten: dict) -> None:
        ws = self._ws
        if ws is None or ws.closed:
            raise JarvisFehler("not_connected", NICHT_ERREICHBAR)
        async with self._sende_sperre:
            await ws.send_str(json.dumps(daten, ensure_ascii=False))

    async def _hallo(self) -> None:
        ok, version = await self.gateway_gesundheit()
        await self._senden({"typ": "hallo", "instanz": self.instanz, "ha_version": HA_VERSION,
                            "gateway": {"ok": ok, "version": version}})

    async def gateway_gesundheit(self) -> tuple[bool, str]:
        try:
            st, d = await self.gateway.anfrage("GET", "/health")
        except (GatewayFehler, NichtErlaubt):
            ok, version = False, ""
        else:
            ok, version = st < 400, str(d.get("version") or "")
        self.gateway_ok, self.gateway_version = ok, version
        return ok, version

    # ---- Anfragen von Jarvis
    async def _gateway(self, m: dict) -> None:
        rid = m.get("id")
        try:
            status, daten = await self.gateway.anfrage(m.get("methode"), m.get("pfad"), m.get("params"), m.get("body"))
            antwort = {"id": rid, "ok": status < 400, "status": status, "daten": daten}
        except NichtErlaubt as e:
            antwort = {"id": rid, "ok": False, "fehler": {"code": "not_allowed", "text": str(e)}}
        except GatewayFehler as e:
            antwort = {"id": rid, "ok": False, "fehler": {"code": e.code, "text": e.text}}
        try:
            await self._senden(antwort)
        except JarvisFehler:
            pass

    async def _abo(self, m: dict) -> None:
        eids = [str(e) for e in (m.get("entities") or []) if isinstance(e, str)][:2000]
        try:
            await self._senden({"id": m.get("id"), "ok": True, "daten": {"anzahl": len(eids)}})
        except JarvisFehler:
            return
        for fn in list(self._bei_abo):
            fn(eids)

    async def zustand_senden(self, entity_id: str, zustand, attribute: dict) -> None:
        await self._senden({"typ": "zustand", "entity_id": entity_id, "zustand": zustand, "attribute": attribute})

    # ---- Befehle an Jarvis
    async def befehl(self, aktion: str, **felder) -> dict:
        if not self.verbunden:
            raise JarvisFehler("not_connected", NICHT_ERREICHBAR)
        rid = uuid.uuid4().hex[:12]
        zukunft = self.hass.loop.create_future()
        self._offen[rid] = zukunft
        try:
            await self._senden({**felder, "typ": "befehl", "id": rid, "aktion": aktion})
            antwort = await asyncio.wait_for(zukunft, BEFEHL_ZEIT)
        except TimeoutError:
            raise JarvisFehler("timeout", "Jarvis antwortet nicht rechtzeitig")
        finally:
            self._offen.pop(rid, None)
        if not antwort.get("ok"):
            f = antwort.get("fehler") or {}
            raise JarvisFehler(str(f.get("code") or "error"), str(f.get("text") or "Jarvis hat den Befehl abgelehnt"))
        d = antwort.get("daten")
        return d if isinstance(d, dict) else {}

    async def abrufen_kalender(self, von, bis, quellen: list[str] | None = None) -> dict:
        felder = {"von": von.isoformat(), "bis": bis.isoformat()}
        if quellen:
            felder["quellen"] = quellen
        return await self.befehl("kalender_lesen", **felder)
