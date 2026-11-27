from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jarvis import kalender as kalender_modul
from custom_components.jarvis.const import DOMAIN, VERSION

NAMEN = {"termine": "appointments", "geburtstage": "birthdays", "aufgaben": "tasks", "dienst": "duty"}
FMT = "%Y-%m-%d %H:%M"


@pytest.fixture(autouse=True)
def _schnelle_entprellung(monkeypatch):
    monkeypatch.setattr(kalender_modul, "KALENDER_ENTPRELLUNG", 0.05)


def _zeit(quelle, uid, titel, beginn: datetime, ende: datetime, **mehr):
    return {"quelle": quelle, "uid": uid, "titel": titel, "ganztaegig": False, "beginn": beginn.strftime(FMT),
            "ende": ende.strftime(FMT), "beschreibung": "", "ort": "", **mehr}


def _ganz(quelle, uid, titel, von: date, bis_exklusiv: date, **mehr):
    return {"quelle": quelle, "uid": uid, "titel": titel, "ganztaegig": True, "beginn": von.isoformat(),
            "ende": bis_exklusiv.isoformat(), "beschreibung": "", "ort": "", **mehr}


def _jetzt():
    return dt_util.now().replace(second=0, microsecond=0)


async def _einrichten(hass, daten, fake):
    e = MockConfigEntry(domain=DOMAIN, data=daten, unique_id="haupt", title="Jarvis (haupt)")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await asyncio.wait_for(fake.verbunden.wait(), 5)
    await fake.naechste("hallo")
    await hass.async_block_till_done()
    return e


async def _warte(hass, bedingung, zeit=5.0):
    ende = asyncio.get_running_loop().time() + zeit
    while not bedingung():
        assert asyncio.get_running_loop().time() < ende, "Bedingung nicht eingetreten"
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()


def _eid(hass, quelle):
    eid = er.async_get(hass).async_get_entity_id("calendar", DOMAIN, f"{hass.config_entries.async_entries(DOMAIN)[0].entry_id}_{quelle}")
    assert eid, quelle
    return eid


async def _abbauen(hass, e):
    if e.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(e.entry_id)


def test_versionen_gleich():
    manifest = json.loads((Path(kalender_modul.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == VERSION == "0.3.0"


async def test_vier_entitaeten(hass, daten, fake_jarvis):
    e = await _einrichten(hass, daten, fake_jarvis)
    await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_appointments").state != STATE_UNAVAILABLE)
    for quelle, name in NAMEN.items():
        assert _eid(hass, quelle) == f"calendar.jarvis_haupt_{name}"
        st = hass.states.get(f"calendar.jarvis_haupt_{name}")
        assert st.state == STATE_OFF
        assert not st.attributes.get("supported_features")
    assert fake_jarvis.kalender_anfragen
    a = fake_jarvis.kalender_anfragen[0]
    heute = dt_util.now().date()
    assert (a["von"], a["bis"]) == ((heute - timedelta(days=1)).isoformat(), (heute + timedelta(days=14)).isoformat())
    await _abbauen(hass, e)


async def test_event_laufend_und_naechster(hass, daten, fake_jarvis):
    j = _jetzt()
    fake_jarvis.kalender_eintraege = [
        _zeit("termine", "t1-x", "Vorbei", j - timedelta(hours=5), j - timedelta(hours=4)),
        _zeit("termine", "t2-x", "Laufend", j - timedelta(minutes=30), j + timedelta(minutes=30), beschreibung="Notiz", ort="Hier"),
        _zeit("termine", "t3-x", "Spaeter", j + timedelta(hours=3), j + timedelta(hours=4)),
        _zeit("dienst", "d1", "Thomas: Spaet", j + timedelta(hours=2), j + timedelta(hours=10)),
        _ganz("geburtstage", "g1-x", "Anna wird 5", j.date() + timedelta(days=3), j.date() + timedelta(days=4)),
    ]
    e = await _einrichten(hass, daten, fake_jarvis)
    await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_appointments").state == STATE_ON)
    st = hass.states.get("calendar.jarvis_haupt_appointments")
    assert st.attributes["message"] == "Laufend" and st.attributes["location"] == "Hier" and st.attributes["description"] == "Notiz"
    st = hass.states.get("calendar.jarvis_haupt_duty")
    assert st.state == STATE_OFF and st.attributes["message"] == "Thomas: Spaet"
    st = hass.states.get("calendar.jarvis_haupt_birthdays")
    assert st.state == STATE_OFF and st.attributes["all_day"] is True and st.attributes["message"] == "Anna wird 5"
    assert hass.states.get("calendar.jarvis_haupt_tasks").attributes.get("message") is None
    await _abbauen(hass, e)


async def test_event_abgelaufen_springt_zum_naechsten(hass, daten, fake_jarvis):
    j = _jetzt()
    fake_jarvis.kalender_eintraege = [
        _zeit("termine", "t1-x", "Gestern", j - timedelta(days=1, hours=2), j - timedelta(days=1, hours=1)),
        _zeit("termine", "t2-x", "Morgen", j + timedelta(days=1), j + timedelta(days=1, hours=1)),
    ]
    e = await _einrichten(hass, daten, fake_jarvis)
    await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_appointments").state == STATE_OFF)
    assert hass.states.get("calendar.jarvis_haupt_appointments").attributes["message"] == "Morgen"
    await _abbauen(hass, e)


async def test_get_events_zeitzone_und_ganztaegig(hass, daten, fake_jarvis):
    j = _jetzt()
    heute = j.date()
    fake_jarvis.kalender_eintraege = [
        _zeit("termine", "t1-x", "Mit Zeit", j + timedelta(hours=1), j + timedelta(hours=2), ort="Ort", beschreibung="Text"),
        _ganz("termine", "t2-x", "Ganztag", heute + timedelta(days=1), heute + timedelta(days=3)),
        _zeit("termine", "t3-x", "Ausserhalb", j + timedelta(days=30), j + timedelta(days=30, hours=1)),
        _zeit("termine", "t4-x", "Davor", j - timedelta(days=5), j - timedelta(days=5) + timedelta(hours=1)),
    ]
    e = await _einrichten(hass, daten, fake_jarvis)
    await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_appointments").state != STATE_UNAVAILABLE)
    fake_jarvis.kalender_anfragen.clear()
    antwort = await hass.services.async_call(
        "calendar", "get_events", {"entity_id": "calendar.jarvis_haupt_appointments", "start_date_time": (j - timedelta(hours=1)).isoformat(),
                                   "end_date_time": (j + timedelta(days=5)).isoformat()}, blocking=True, return_response=True)
    ereignisse = antwort["calendar.jarvis_haupt_appointments"]["events"]
    ereignisse.sort(key=lambda x: x["summary"] != "Mit Zeit")
    assert [x["summary"] for x in ereignisse] == ["Mit Zeit", "Ganztag"]
    mit = ereignisse[0]
    assert datetime.fromisoformat(mit["start"]).utcoffset() == j.utcoffset()
    assert mit["location"] == "Ort" and mit["description"] == "Text"
    assert ereignisse[1]["start"] == (heute + timedelta(days=1)).isoformat() and ereignisse[1]["end"] == (heute + timedelta(days=3)).isoformat()
    a = fake_jarvis.kalender_anfragen[-1]
    assert a["quellen"] == ["termine"]
    assert (a["von"], a["bis"]) == ((j - timedelta(hours=1)).date().isoformat(), (j + timedelta(days=5)).date().isoformat())
    await _abbauen(hass, e)


async def test_get_events_kuerzt_auf_100_tage(hass, daten, fake_jarvis):
    e = await _einrichten(hass, daten, fake_jarvis)
    await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_duty").state != STATE_UNAVAILABLE)
    fake_jarvis.kalender_anfragen.clear()
    j = _jetzt()
    await hass.services.async_call(
        "calendar", "get_events", {"entity_id": "calendar.jarvis_haupt_duty", "start_date_time": j.isoformat(),
                                   "end_date_time": (j + timedelta(days=400)).isoformat()}, blocking=True, return_response=True)
    a = fake_jarvis.kalender_anfragen[-1]
    assert (date.fromisoformat(a["bis"]) - date.fromisoformat(a["von"])).days + 1 == 100
    await _abbauen(hass, e)


async def test_aktualisierung_bei_kalender_geaendert(hass, daten, fake_jarvis):
    j = _jetzt()
    e = await _einrichten(hass, daten, fake_jarvis)
    await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_tasks").state == STATE_OFF)
    assert hass.states.get("calendar.jarvis_haupt_tasks").attributes.get("message") is None
    fake_jarvis.kalender_eintraege = [_zeit("aufgaben", "a1", "Muell raus", j - timedelta(minutes=5), j + timedelta(minutes=25))]
    await fake_jarvis.senden({"typ": "kalender_geaendert"})
    await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_tasks").state == STATE_ON)
    assert hass.states.get("calendar.jarvis_haupt_tasks").attributes["message"] == "Muell raus"
    await _abbauen(hass, e)


async def test_unbekannter_befehl(hass, daten, fake_jarvis, caplog):
    fake_jarvis.kalender_unbekannt = True
    with caplog.at_level(logging.WARNING):
        e = await _einrichten(hass, daten, fake_jarvis)
        await _warte(hass, lambda: any(a for a in fake_jarvis.kalender_anfragen))
        await fake_jarvis.senden({"typ": "kalender_geaendert"})
        await asyncio.sleep(0.3)
        await hass.async_block_till_done()
    for name in NAMEN.values():
        assert hass.states.get(f"calendar.jarvis_haupt_{name}").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.jarvis_haupt_connected").state == STATE_ON
    assert len([r for r in caplog.records if "kalender_lesen" in r.getMessage() and r.levelno == logging.WARNING]) == 1
    await _abbauen(hass, e)


async def test_fehlende_quelle(hass, daten, fake_jarvis, caplog):
    fake_jarvis.kalender_quellen = ["termine", "geburtstage", "aufgaben"]
    with caplog.at_level(logging.WARNING):
        e = await _einrichten(hass, daten, fake_jarvis)
        await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_appointments").state != STATE_UNAVAILABLE)
        await fake_jarvis.senden({"typ": "kalender_geaendert"})
        await asyncio.sleep(0.3)
        await hass.async_block_till_done()
    assert hass.states.get("calendar.jarvis_haupt_duty").state == STATE_UNAVAILABLE
    assert hass.states.get("calendar.jarvis_haupt_tasks").state == STATE_OFF
    assert len([r for r in caplog.records if "dienst" in r.getMessage() and r.levelno == logging.WARNING]) == 1
    await _abbauen(hass, e)


async def test_verbindung_weg_und_wieder_da(hass, daten, fake_jarvis):
    j = _jetzt()
    e = await _einrichten(hass, daten, fake_jarvis)
    await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_duty").state == STATE_OFF)
    fake_jarvis.kalender_eintraege = [_zeit("dienst", "d1", "Thomas: Frueh", j - timedelta(minutes=5), j + timedelta(hours=8))]
    await fake_jarvis.trennen()
    await _warte(hass, lambda: all(hass.states.get(f"calendar.jarvis_haupt_{n}").state == STATE_UNAVAILABLE for n in NAMEN.values()))
    assert hass.states.get("binary_sensor.jarvis_haupt_connected").state != STATE_ON
    await _warte(hass, lambda: hass.states.get("calendar.jarvis_haupt_duty").state == STATE_ON, zeit=8)
    assert hass.states.get("calendar.jarvis_haupt_duty").attributes["message"] == "Thomas: Frueh"
    await _abbauen(hass, e)
