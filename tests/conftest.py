from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jarvis import client as client_modul
from custom_components.jarvis.const import (CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, CONF_INSTANZ, CONF_JARVIS_TOKEN,
                                            CONF_JARVIS_URL, DOMAIN)

JARVIS_TOKEN = "jarvis-test-token-1234567890"
GATEWAY_TOKEN = "gateway-test-token-abcdefghij"


@pytest.fixture(autouse=True)
def _alles(enable_custom_integrations, socket_enabled):
    yield


@pytest.fixture(autouse=True)
def _schneller_backoff(monkeypatch):
    monkeypatch.setattr(client_modul, "BACKOFF_START", 0.05)
    monkeypatch.setattr(client_modul, "BACKOFF_MAX", 0.2)


class FakeJarvis:
    def __init__(self) -> None:
        self.ws: web.WebSocketResponse | None = None
        self.empfangen: asyncio.Queue = asyncio.Queue()
        self.verbindungen = 0
        self.kopfzeilen: list[dict] = []
        self.abfragen: list[dict] = []
        self.befehl_antwort = self._standard
        self.kalender_quellen = ["termine", "geburtstage", "aufgaben", "dienst"]
        self.kalender_eintraege: list[dict] = []
        self.kalender_unbekannt = False
        self.kalender_anfragen: list[dict] = []
        self.verbunden = asyncio.Event()
        self.ende = False

    def _standard(self, m: dict) -> dict:
        if m.get("aktion") == "kalender_lesen":
            self.kalender_anfragen.append(m)
            if self.kalender_unbekannt:
                return {"id": m["id"], "ok": False, "fehler": {"code": "unknown_action", "text": "Unbekannter Befehl"}}
            wunsch = m.get("quellen") or self.kalender_quellen
            eintraege = [e for e in self.kalender_eintraege if e["quelle"] in wunsch and e["quelle"] in self.kalender_quellen]
            return {"id": m["id"], "ok": True, "daten": {"quellen": self.kalender_quellen, "eintraege": eintraege, "gekuerzt": False}}
        return {"id": m["id"], "ok": True, "daten": {}}

    async def handler(self, request: web.Request):
        self.kopfzeilen.append(dict(request.headers))
        self.abfragen.append(dict(request.query))
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        if self.ende:
            await ws.close()
            return ws
        if request.headers.get("Authorization") != f"Bearer {JARVIS_TOKEN}":
            await ws.close(code=4401)
            return ws
        self.ws = ws
        self.verbindungen += 1
        self.verbunden.set()
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                m = json.loads(msg.data)
                if m.get("typ") == "befehl":
                    await ws.send_str(json.dumps(self.befehl_antwort(m)))
                if m.get("aktion") != "kalender_lesen":
                    await self.empfangen.put(m)
        self.verbunden.clear()
        return ws

    async def senden(self, m: dict) -> None:
        await self.ws.send_str(json.dumps(m))

    async def naechste(self, typ: str | None = None, zeit: float = 5) -> dict:
        while True:
            m = await asyncio.wait_for(self.empfangen.get(), zeit)
            if typ is None or m.get("typ") == typ or (typ == "antwort" and "typ" not in m):
                return m

    async def frage(self, m: dict, zeit: float = 5) -> dict:
        await self.senden(m)
        while True:
            a = await self.naechste("antwort", zeit)
            if a.get("id") == m["id"]:
                return a

    async def trennen(self) -> None:
        self.verbunden.clear()
        await self.ws.close()


class FakeGateway:
    def __init__(self) -> None:
        self.aufrufe: list[tuple[str, str, dict, bytes]] = []
        self.entitaeten = {"sensor.test": {"state": "1", "attributes": {"friendly_name": "Test"}}}
        self.version = "1.2.3"

    def _pruefen(self, request: web.Request):
        self.aufrufe.append((request.method, request.path, dict(request.headers), b""))
        if request.headers.get("X-API-Token") != GATEWAY_TOKEN:
            return web.json_response({"error": "unauthorized"}, status=401)

    async def health(self, request):
        return self._pruefen(request) or web.json_response({"ok": True, "version": self.version})

    async def liste(self, request):
        return self._pruefen(request) or web.json_response(
            {"entities": [{"entity_id": k, "name": k, "state": v["state"], "attributes": v["attributes"]} for k, v in self.entitaeten.items()]})

    async def eine(self, request):
        e = self._pruefen(request)
        if e:
            return e
        k = request.match_info["eid"]
        if k not in self.entitaeten:
            return web.json_response({"code": "not_found"}, status=404)
        return web.json_response({"entity_id": k, **self.entitaeten[k]})

    async def call(self, request):
        return self._pruefen(request) or web.json_response({"ok": True, "echo": await request.json()})


@pytest.fixture
async def fake_jarvis():
    f = FakeJarvis()
    app = web.Application()
    app.router.add_get("/ws/ha", f.handler)
    server = TestServer(app)
    await server.start_server()
    f.url = f"ws://127.0.0.1:{server.port}/ws/ha"
    yield f
    f.ende = True
    if f.ws is not None and not f.ws.closed:
        await f.ws.close()
    await server.close()


@pytest.fixture
async def fake_gateway():
    g = FakeGateway()
    app = web.Application()
    app.router.add_get("/api/v1/health", g.health)
    app.router.add_get("/api/v1/entities", g.liste)
    app.router.add_get("/api/v1/entities/{eid}", g.eine)
    app.router.add_post("/api/v1/call", g.call)
    server = TestServer(app)
    await server.start_server()
    g.url = f"http://127.0.0.1:{server.port}"
    yield g
    await server.close()


@pytest.fixture
def daten(fake_jarvis, fake_gateway):
    return {CONF_INSTANZ: "haupt", CONF_JARVIS_URL: fake_jarvis.url, CONF_JARVIS_TOKEN: JARVIS_TOKEN,
            CONF_GATEWAY_URL: fake_gateway.url, CONF_GATEWAY_TOKEN: GATEWAY_TOKEN}


@pytest.fixture
async def eintrag(hass, daten, fake_jarvis):
    e = MockConfigEntry(domain=DOMAIN, data=daten, unique_id="haupt", title="Jarvis (haupt)")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await asyncio.wait_for(fake_jarvis.verbunden.wait(), 5)
    await fake_jarvis.naechste("hallo")
    await hass.async_block_till_done()
    yield e
    if e.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(e.entry_id)
