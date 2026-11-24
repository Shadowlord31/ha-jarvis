"""Jarvis: eine Verbindung zwischen Jarvis und Home Assistant (Integration + Gateway)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import JarvisClient
from .const import (CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, CONF_INSTANZ, CONF_JARVIS_TOKEN, CONF_JARVIS_URL, DOMAIN,
                    SERVICE_AUFGABE_ANLEGEN, SERVICE_AUFGABE_ERLEDIGT, SERVICE_MELDUNG, SERVICE_TIMER_STARTEN,
                    SERVICE_TIMER_STOPPEN, NICHT_ERREICHBAR)
from .gateway_zugang import GatewayZugang
from .zustand import ZustandsPush

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.EVENT]


@dataclass
class Laufzeit:
    client: JarvisClient
    push: ZustandsPush


type JarvisConfigEntry = ConfigEntry[Laufzeit]

_INSTANZ = {vol.Optional("instanz"): cv.string}
_DATUM = vol.Match(r"^\d{4}-\d{2}-\d{2}$")
_ZEIT = vol.Match(r"^\d{2}:\d{2}$")

SCHEMA_TIMER_STARTEN = vol.Schema({**_INSTANZ, vol.Required("dauer"): cv.time_period, vol.Optional("name", default=""): cv.string,
                                   vol.Optional("ueberall", default=True): cv.boolean})
SCHEMA_TIMER_STOPPEN = vol.Schema({**_INSTANZ, vol.Optional("id"): cv.string, vol.Optional("name"): cv.string,
                                   vol.Optional("alle"): cv.boolean})
SCHEMA_MELDUNG = vol.Schema({**_INSTANZ, vol.Required("nachricht"): cv.string, vol.Optional("titel"): cv.string,
                             vol.Optional("symbol"): cv.string, vol.Optional("dringend", default=False): cv.boolean,
                             vol.Optional("sprechen", default=False): cv.boolean, vol.Optional("ziel", default="alle"): cv.string})
SCHEMA_AUFGABE_ANLEGEN = vol.Schema({**_INSTANZ, vol.Required("titel"): cv.string, vol.Optional("liste"): cv.string,
                                     vol.Optional("faellig_datum"): _DATUM, vol.Optional("faellig_zeit"): _ZEIT,
                                     vol.Optional("notiz"): cv.string})
SCHEMA_AUFGABE_ERLEDIGT = vol.Schema({**_INSTANZ, vol.Required("titel"): cv.string, vol.Optional("liste"): cv.string})


def _client(hass: HomeAssistant, instanz: str | None) -> JarvisClient:
    eintraege = [e for e in hass.config_entries.async_entries(DOMAIN) if getattr(e, "runtime_data", None)]
    if instanz:
        eintraege = [e for e in eintraege if e.entry_id == instanz or e.data.get(CONF_INSTANZ) == instanz]
    if not eintraege:
        raise HomeAssistantError(NICHT_ERREICHBAR)
    if len(eintraege) > 1:
        raise HomeAssistantError("Mehrere Jarvis-Instanzen eingerichtet: bitte 'instanz' angeben")
    return eintraege[0].runtime_data.client


def _felder(call: ServiceCall, *namen: str) -> dict:
    return {n: call.data[n] for n in namen if call.data.get(n) not in (None, "")}


async def _timer_starten(call: ServiceCall) -> dict:
    d = await _client(call.hass, call.data.get("instanz")).befehl(
        "timer_starten", dauer=int(call.data["dauer"].total_seconds()), name=call.data["name"], ueberall=call.data["ueberall"])
    return {"id": d.get("id"), "ende": d.get("ende")}


async def _timer_stoppen(call: ServiceCall) -> dict:
    angaben = [bool(call.data.get("id")), bool(call.data.get("name")), bool(call.data.get("alle"))]
    if sum(angaben) != 1:
        raise HomeAssistantError("Genau eins von id, name oder alle angeben")
    felder = _felder(call, "name")
    if call.data.get("id"):
        felder["timer_id"] = call.data["id"]
    if call.data.get("alle"):
        felder["alle"] = True
    return await _client(call.hass, call.data.get("instanz")).befehl("timer_stoppen", **felder)


async def _meldung(call: ServiceCall) -> dict:
    felder = _felder(call, "nachricht", "titel", "symbol", "ziel")
    return await _client(call.hass, call.data.get("instanz")).befehl(
        "meldung", **felder, dringend=call.data["dringend"], sprechen=call.data["sprechen"])


async def _aufgabe_anlegen(call: ServiceCall) -> dict:
    return await _client(call.hass, call.data.get("instanz")).befehl(
        "aufgabe_anlegen", **_felder(call, "titel", "liste", "faellig_datum", "faellig_zeit", "notiz"))


async def _aufgabe_erledigt(call: ServiceCall) -> dict:
    return await _client(call.hass, call.data.get("instanz")).befehl("aufgabe_erledigt", **_felder(call, "titel", "liste"))


def _services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_TIMER_STARTEN):
        return
    for name, fn, schema, antwort in (
        (SERVICE_TIMER_STARTEN, _timer_starten, SCHEMA_TIMER_STARTEN, SupportsResponse.OPTIONAL),
        (SERVICE_TIMER_STOPPEN, _timer_stoppen, SCHEMA_TIMER_STOPPEN, SupportsResponse.OPTIONAL),
        (SERVICE_MELDUNG, _meldung, SCHEMA_MELDUNG, SupportsResponse.OPTIONAL),
        (SERVICE_AUFGABE_ANLEGEN, _aufgabe_anlegen, SCHEMA_AUFGABE_ANLEGEN, SupportsResponse.OPTIONAL),
        (SERVICE_AUFGABE_ERLEDIGT, _aufgabe_erledigt, SCHEMA_AUFGABE_ERLEDIGT, SupportsResponse.OPTIONAL),
    ):
        hass.services.async_register(DOMAIN, name, fn, schema=schema, supports_response=antwort)


async def async_setup_entry(hass: HomeAssistant, entry: JarvisConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    daten = {**entry.data, **entry.options}
    gateway = GatewayZugang(session, daten[CONF_GATEWAY_URL], daten[CONF_GATEWAY_TOKEN])
    client = JarvisClient(hass, session, daten[CONF_INSTANZ], daten[CONF_JARVIS_URL], daten[CONF_JARVIS_TOKEN], gateway)
    push = ZustandsPush(hass, client)
    entry.runtime_data = Laufzeit(client, push)
    _services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    push.start()
    client.start()
    entry.async_on_unload(entry.add_update_listener(_neu_laden))
    return True


async def _neu_laden(hass: HomeAssistant, entry: JarvisConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: JarvisConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        entry.runtime_data.push.stop()
        await entry.runtime_data.client.stop()
        if not any(e.entry_id != entry.entry_id and getattr(e, "runtime_data", None) for e in hass.config_entries.async_entries(DOMAIN)):
            for name in (SERVICE_TIMER_STARTEN, SERVICE_TIMER_STOPPEN, SERVICE_MELDUNG, SERVICE_AUFGABE_ANLEGEN, SERVICE_AUFGABE_ERLEDIGT):
                hass.services.async_remove(DOMAIN, name)
    return ok
