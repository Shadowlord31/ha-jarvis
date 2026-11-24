from __future__ import annotations

import asyncio
import logging

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry

from custom_components.jarvis import zustand
from custom_components.jarvis.const import (CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, CONF_INSTANZ, CONF_JARVIS_TOKEN,
                                            CONF_JARVIS_URL, DOMAIN)

from .conftest import GATEWAY_TOKEN, JARVIS_TOKEN


def _id(hass, plattform, schluessel):
    return er.async_get(hass).async_get_entity_id(plattform, DOMAIN, f"{{}}_{schluessel}".format(
        hass.config_entries.async_entries(DOMAIN)[0].entry_id))


# ---------- Config Flow
async def _flow(hass, daten):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert r["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(r["flow_id"], daten)


async def test_flow_erfolg(hass, daten):
    r = await _flow(hass, daten)
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["title"] == "Jarvis (haupt)"
    assert r["data"][CONF_JARVIS_TOKEN] == JARVIS_TOKEN
    await hass.async_block_till_done()
    for e in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(e.entry_id)


async def test_flow_falsches_jarvis_token(hass, daten):
    r = await _flow(hass, {**daten, CONF_JARVIS_TOKEN: "falsch-falsch-falsch"})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {CONF_JARVIS_TOKEN: "jarvis_token"}


async def test_flow_falsches_gateway_token(hass, daten):
    r = await _flow(hass, {**daten, CONF_GATEWAY_TOKEN: "falsch"})
    assert r["errors"] == {CONF_GATEWAY_TOKEN: "gateway_token"}


async def test_flow_jarvis_nicht_erreichbar(hass, daten):
    r = await _flow(hass, {**daten, CONF_JARVIS_URL: "ws://127.0.0.1:9/ws/ha"})
    assert r["errors"] == {CONF_JARVIS_URL: "jarvis_nicht_erreichbar"}


async def test_flow_gateway_nicht_erreichbar(hass, daten):
    r = await _flow(hass, {**daten, CONF_GATEWAY_URL: "http://127.0.0.1:9"})
    assert r["errors"] == {CONF_GATEWAY_URL: "gateway_nicht_erreichbar"}


async def test_flow_ungueltige_adresse(hass, daten):
    r = await _flow(hass, {**daten, CONF_JARVIS_URL: "ftp://x"})
    assert r["errors"] == {CONF_JARVIS_URL: "ungueltige_adresse"}


async def test_flow_doppelt(hass, daten, eintrag):
    r = await _flow(hass, daten)
    assert r["type"] is FlowResultType.ABORT


async def test_options_flow(hass, eintrag, fake_gateway):
    r = await hass.config_entries.options.async_init(eintrag.entry_id)
    assert r["type"] is FlowResultType.FORM
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        CONF_JARVIS_URL: eintrag.data[CONF_JARVIS_URL], CONF_JARVIS_TOKEN: JARVIS_TOKEN,
        CONF_GATEWAY_URL: fake_gateway.url, CONF_GATEWAY_TOKEN: "falsch"})
    assert r["errors"] == {CONF_GATEWAY_TOKEN: "gateway_token"}
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        CONF_JARVIS_URL: eintrag.data[CONF_JARVIS_URL], CONF_JARVIS_TOKEN: JARVIS_TOKEN,
        CONF_GATEWAY_URL: fake_gateway.url, CONF_GATEWAY_TOKEN: GATEWAY_TOKEN})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert eintrag.state is ConfigEntryState.LOADED


# ---------- Anmeldung, hallo, Entitaeten
async def test_anmeldung_und_hallo(hass, daten, fake_jarvis):
    e = MockConfigEntry(domain=DOMAIN, data=daten, unique_id="haupt")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    h = await fake_jarvis.naechste("hallo")
    assert fake_jarvis.kopfzeilen[0]["Authorization"] == f"Bearer {JARVIS_TOKEN}"
    assert fake_jarvis.abfragen[0]["instanz"] == "haupt" and fake_jarvis.abfragen[0]["version"]
    assert h["instanz"] == "haupt" and h["ha_version"] and h["gateway"] == {"ok": True, "version": "1.2.3"}


async def test_ping_pong(hass, eintrag, fake_jarvis):
    await fake_jarvis.senden({"typ": "ping"})
    assert (await fake_jarvis.naechste("pong"))["typ"] == "pong"


async def test_entitaeten_und_timer(hass, eintrag, fake_jarvis):
    assert hass.states.get("binary_sensor.jarvis_haupt_connected").state == "on"
    assert hass.states.get("sensor.jarvis_haupt_active_timers").state == "0"
    assert hass.states.get("sensor.jarvis_haupt_next_timer").state == "unknown"
    await fake_jarvis.senden({"typ": "timer", "liste": [
        {"id": "a", "name": "Nudeln", "ende": "2030-01-01T12:10:00+00:00", "geraet": ""},
        {"id": "b", "name": "Ei", "ende": "2030-01-01T12:05:00+00:00", "geraet": ""}]})
    await asyncio.sleep(0.1)
    assert hass.states.get("sensor.jarvis_haupt_active_timers").state == "2"
    assert hass.states.get("sensor.jarvis_haupt_active_timers").attributes["timer"][0]["name"] == "Nudeln"
    assert hass.states.get("sensor.jarvis_haupt_next_timer").state == "2030-01-01T12:05:00+00:00"


async def test_ereignis(hass, eintrag, fake_jarvis):
    await fake_jarvis.senden({"typ": "ereignis", "art": "timer_fertig", "id": "a", "name": "Nudeln"})
    await asyncio.sleep(0.1)
    s = hass.states.get("event.jarvis_haupt_events")
    assert s.attributes["event_type"] == "timer_fertig" and s.attributes["id"] == "a" and s.attributes["name"] == "Nudeln"
    await fake_jarvis.senden({"typ": "ereignis", "art": "erinnerung_faellig", "id": "b", "name": "Arzt"})
    await asyncio.sleep(0.1)
    assert hass.states.get("event.jarvis_haupt_events").attributes["event_type"] == "erinnerung_faellig"
    await fake_jarvis.senden({"typ": "ereignis", "art": "unbekannt", "id": "c", "name": ""})
    await asyncio.sleep(0.1)
    assert hass.states.get("event.jarvis_haupt_events").attributes["event_type"] == "erinnerung_faellig"


# ---------- Services
async def test_timer_starten(hass, eintrag, fake_jarvis):
    fake_jarvis.befehl_antwort = lambda m: {"id": m["id"], "ok": True, "daten": {"id": "x1", "ende": "2030-01-01T00:10:00+00:00"}}
    r = await hass.services.async_call(DOMAIN, "timer_starten", {"dauer": {"minutes": 10}, "name": "Nudeln"}, blocking=True, return_response=True)
    assert r == {"id": "x1", "ende": "2030-01-01T00:10:00+00:00"}
    b = await fake_jarvis.naechste("befehl")
    assert (b["aktion"], b["dauer"], b["name"], b["ueberall"]) == ("timer_starten", 600, "Nudeln", True)


async def test_timer_stoppen(hass, eintrag, fake_jarvis):
    await hass.services.async_call(DOMAIN, "timer_stoppen", {"id": "abc"}, blocking=True)
    b = await fake_jarvis.naechste("befehl")
    assert b["aktion"] == "timer_stoppen" and b["timer_id"] == "abc" and b["id"] != "abc"
    await hass.services.async_call(DOMAIN, "timer_stoppen", {"alle": True}, blocking=True)
    assert (await fake_jarvis.naechste("befehl"))["alle"] is True
    for d in ({}, {"id": "a", "name": "b"}, {"alle": True, "name": "x"}):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(DOMAIN, "timer_stoppen", d, blocking=True)


async def test_meldung(hass, eintrag, fake_jarvis):
    await hass.services.async_call(DOMAIN, "meldung", {"nachricht": "Wasch fertig", "titel": "Haus", "dringend": True, "ziel": "hub"}, blocking=True)
    b = await fake_jarvis.naechste("befehl")
    assert (b["aktion"], b["nachricht"], b["titel"], b["dringend"], b["sprechen"], b["ziel"]) == ("meldung", "Wasch fertig", "Haus", True, False, "hub")


async def test_aufgaben(hass, eintrag, fake_jarvis):
    await hass.services.async_call(DOMAIN, "aufgabe_anlegen", {"titel": "Müll", "liste": "Haus", "faellig_datum": "2030-02-03", "faellig_zeit": "18:30"}, blocking=True)
    b = await fake_jarvis.naechste("befehl")
    assert b["aktion"] == "aufgabe_anlegen" and b["faellig_datum"] == "2030-02-03" and b["faellig_zeit"] == "18:30" and "notiz" not in b
    await hass.services.async_call(DOMAIN, "aufgabe_erledigt", {"titel": "Müll"}, blocking=True)
    assert (await fake_jarvis.naechste("befehl"))["aktion"] == "aufgabe_erledigt"
    with pytest.raises(Exception):
        await hass.services.async_call(DOMAIN, "aufgabe_anlegen", {"titel": "x", "faellig_datum": "morgen"}, blocking=True)


async def test_service_fehler_von_jarvis(hass, eintrag, fake_jarvis):
    fake_jarvis.befehl_antwort = lambda m: {"id": m["id"], "ok": False, "fehler": {"code": "invalid", "text": "Dauer ungueltig"}}
    with pytest.raises(HomeAssistantError, match="Dauer ungueltig"):
        await hass.services.async_call(DOMAIN, "timer_starten", {"dauer": {"seconds": 5}}, blocking=True)


async def test_service_zeitgrenze(hass, eintrag, fake_jarvis, monkeypatch):
    from custom_components.jarvis import client
    monkeypatch.setattr(client, "BEFEHL_ZEIT", 0.2)
    fake_jarvis.befehl_antwort = lambda m: {"id": "andere", "ok": True, "daten": {}}
    with pytest.raises(HomeAssistantError, match="nicht rechtzeitig"):
        await hass.services.async_call(DOMAIN, "meldung", {"nachricht": "x"}, blocking=True)


# ---------- getrennt, Reconnect
async def test_getrennt_und_reconnect(hass, eintrag, fake_jarvis):
    n = fake_jarvis.verbindungen
    await fake_jarvis.senden({"typ": "timer", "liste": [{"id": "a", "name": "x", "ende": "2030-01-01T00:00:00+00:00"}]})
    await asyncio.sleep(0.1)
    await fake_jarvis.trennen()
    await asyncio.sleep(0.02)
    assert hass.states.get("binary_sensor.jarvis_haupt_connected").state == "off"
    assert hass.states.get("sensor.jarvis_haupt_active_timers").state == "unavailable"
    assert hass.states.get("sensor.jarvis_haupt_next_timer").state == "unavailable"
    assert hass.states.get("event.jarvis_haupt_events").state == "unavailable"
    with pytest.raises(HomeAssistantError, match="Jarvis ist nicht erreichbar"):
        await hass.services.async_call(DOMAIN, "meldung", {"nachricht": "x"}, blocking=True)
    await asyncio.wait_for(fake_jarvis.verbunden.wait(), 5)
    await fake_jarvis.naechste("hallo")
    await asyncio.sleep(0.05)
    assert fake_jarvis.verbindungen == n + 1
    assert hass.states.get("binary_sensor.jarvis_haupt_connected").state == "on"
    assert hass.states.get("sensor.jarvis_haupt_active_timers").state == "0"


async def test_jarvis_nicht_da_service(hass, daten):
    e = MockConfigEntry(domain=DOMAIN, data={**daten, CONF_JARVIS_URL: "ws://127.0.0.1:9/ws/ha"}, unique_id="haupt")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await asyncio.sleep(0.1)
    assert hass.states.get("binary_sensor.jarvis_haupt_connected").state == "off"
    with pytest.raises(HomeAssistantError, match="Jarvis ist nicht erreichbar"):
        await hass.services.async_call(DOMAIN, "timer_starten", {"dauer": {"seconds": 5}}, blocking=True)
    assert await hass.config_entries.async_unload(e.entry_id)


# ---------- Durchleitung Gateway
async def test_gateway_durchleitung(hass, eintrag, fake_jarvis, fake_gateway):
    a = await fake_jarvis.frage({"id": "1", "typ": "gateway", "methode": "GET", "pfad": "/entities/sensor.test"})
    assert a["ok"] is True and a["status"] == 200 and a["daten"]["state"] == "1"
    h = fake_gateway.aufrufe[-1]
    assert h[2]["X-API-Token"] == GATEWAY_TOKEN
    a = await fake_jarvis.frage({"id": "2", "typ": "gateway", "methode": "POST", "pfad": "/call", "body": {"entity_id": "x"}})
    assert a["ok"] and a["daten"]["echo"] == {"entity_id": "x"}
    a = await fake_jarvis.frage({"id": "3", "typ": "gateway", "methode": "GET", "pfad": "/entities/nope"})
    assert a["ok"] is False and a["status"] == 404 and a["daten"]["code"] == "not_found"


@pytest.mark.parametrize("pfad", ["/../x", "/entities/../health", "/config", "/entities/%2e%2e", "/entities/a b"])
async def test_gateway_positivliste(hass, eintrag, fake_jarvis, fake_gateway, pfad):
    n = len(fake_gateway.aufrufe)
    a = await fake_jarvis.frage({"id": "9", "typ": "gateway", "methode": "GET", "pfad": pfad})
    assert a["ok"] is False and a["fehler"]["code"] == "not_allowed"
    a = await fake_jarvis.frage({"id": "10", "typ": "gateway", "methode": "DELETE", "pfad": "/entities"})
    assert a["fehler"]["code"] == "not_allowed"
    assert len(fake_gateway.aufrufe) == n


async def test_gateway_nicht_erreichbar(hass, eintrag, fake_jarvis):
    hass.config_entries.async_entries(DOMAIN)[0].runtime_data.client.gateway._basis = "http://127.0.0.1:9"
    a = await fake_jarvis.frage({"id": "1", "typ": "gateway", "methode": "GET", "pfad": "/health"})
    assert a["ok"] is False and a["fehler"]["code"] == "gateway_unreachable"


# ---------- Zustands-Push
async def test_zustand_push(hass, eintrag, fake_jarvis, fake_gateway, monkeypatch):
    monkeypatch.setattr(zustand, "ENTPRELLUNG_S", 0.1)
    fake_gateway.entitaeten["sensor.geheim"] = {"state": "9", "attributes": {}}
    a = await fake_jarvis.frage({"id": "abo1", "typ": "abo", "entities": ["sensor.test", "sensor.nichtfrei"]})
    assert a["ok"] is True
    await asyncio.sleep(0.2)
    push = eintrag.runtime_data.push
    assert push.abo == {"sensor.test", "sensor.nichtfrei"}
    assert {"sensor.test", "sensor.geheim"} <= push.freigegeben
    fake_gateway.entitaeten["sensor.test"] = {"state": "5", "attributes": {"einheit": "W"}}
    for w in ("2", "3", "5"):
        hass.states.async_set("sensor.test", w)
    hass.states.async_set("sensor.nichtfrei", "1")
    hass.states.async_set("sensor.geheim", "1")
    z = await fake_jarvis.naechste("zustand")
    assert z == {"typ": "zustand", "entity_id": "sensor.test", "zustand": "5", "attribute": {"einheit": "W"}}
    await asyncio.sleep(0.4)
    assert fake_jarvis.empfangen.empty()


# ---------- Diagnose, Unload, Reload
async def test_diagnose_ohne_geheimnisse(hass, hass_client, eintrag, fake_jarvis, fake_gateway):
    d = await get_diagnostics_for_config_entry(hass, hass_client, eintrag)
    text = str(d)
    for geheim in (JARVIS_TOKEN, GATEWAY_TOKEN, fake_jarvis.url, fake_gateway.url):
        assert geheim not in text
    assert d["status"]["verbunden"] is True


async def test_token_nicht_im_log(hass, caplog, daten, fake_jarvis):
    caplog.set_level(logging.DEBUG)
    e = MockConfigEntry(domain=DOMAIN, data={**daten, CONF_JARVIS_TOKEN: "falsch-falsch-falsch"}, unique_id="haupt")
    e.add_to_hass(hass)
    await hass.config_entries.async_setup(e.entry_id)
    await asyncio.sleep(0.2)
    await hass.config_entries.async_unload(e.entry_id)
    assert "falsch-falsch-falsch" not in caplog.text and GATEWAY_TOKEN not in caplog.text


async def test_unload_reload(hass, eintrag, fake_jarvis):
    assert hass.services.has_service(DOMAIN, "meldung")
    assert await hass.config_entries.async_unload(eintrag.entry_id)
    assert eintrag.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, "meldung")
    await asyncio.sleep(0.1)
    assert hass.states.get("binary_sensor.jarvis_haupt_connected").state == "unavailable"
    fake_jarvis.verbunden.clear()
    assert await hass.config_entries.async_setup(eintrag.entry_id)
    await asyncio.wait_for(fake_jarvis.verbunden.wait(), 5)
    await fake_jarvis.naechste("hallo")
    await asyncio.sleep(0.05)
    assert hass.services.has_service(DOMAIN, "meldung")
    assert hass.states.get("binary_sensor.jarvis_haupt_connected").state == "on"
    assert await hass.config_entries.async_reload(eintrag.entry_id)
    assert await hass.config_entries.async_unload(eintrag.entry_id)


def test_kein_freier_service_aufruf():
    import pathlib
    for f in pathlib.Path("custom_components/jarvis").glob("*.py"):
        assert "async_call(" not in f.read_text(), f.name


def _texte(knoten):
    if isinstance(knoten, dict):
        for v in knoten.values():
            yield from _texte(v)
    elif isinstance(knoten, list):
        for v in knoten:
            yield from _texte(v)
    elif isinstance(knoten, str):
        yield knoten


@pytest.mark.parametrize("datei", ["strings.json", "translations/de.json", "translations/en.json"])
def test_uebersetzungen_ohne_spitze_klammern(datei):
    import json
    import pathlib
    pfad = pathlib.Path(__file__).parent.parent / "custom_components" / "jarvis" / datei
    for text in _texte(json.loads(pfad.read_text(encoding="utf-8"))):
        assert "<" not in text and ">" not in text, f"{datei}: {text}"


async def test_timer_attribute_mit_id(hass, eintrag, fake_jarvis):
    await fake_jarvis.senden({"typ": "timer", "liste": [
        {"id": "a", "name": "Nudeln", "ende": "2030-01-01T12:10:00+00:00", "geraet": "pixel"},
        {"id": "b", "name": "Ei", "ende": "2030-01-01T12:05:00+00:00", "geraet": ""}]})
    await asyncio.sleep(0.1)
    erwartet = [{"id": "b", "name": "Ei", "endet": "2030-01-01T12:05:00+00:00", "geraet": ""},
                {"id": "a", "name": "Nudeln", "endet": "2030-01-01T12:10:00+00:00", "geraet": "pixel"}]
    assert hass.states.get("sensor.jarvis_haupt_next_timer").attributes["timer"] == erwartet
    assert sorted(hass.states.get("sensor.jarvis_haupt_active_timers").attributes["timer"], key=lambda t: t["id"]) == sorted(erwartet, key=lambda t: t["id"])
