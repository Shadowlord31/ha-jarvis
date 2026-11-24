from __future__ import annotations

import asyncio
import logging

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (SelectSelector, SelectSelectorConfig, TextSelector, TextSelectorConfig,
                                            TextSelectorType)

from .client import ws_adresse
from .const import (CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, CONF_INSTANZ, CONF_JARVIS_TOKEN, CONF_JARVIS_URL, DOMAIN,
                    INSTANZEN, STANDARD_GATEWAY_URL, STANDARD_INSTANZ, VERBINDEN_ZEIT, VERSION)
from .gateway_zugang import GatewayFehler, GatewayZugang

_LOGGER = logging.getLogger(__name__)
_PW = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def pruefen(hass, d: dict) -> dict[str, str]:
    """Prueft beide Verbindungen; gibt Fehler als {Feld: Schluessel} zurueck (leer = alles gut)."""
    fehler: dict[str, str] = {}
    session = async_get_clientsession(hass)
    try:
        url = ws_adresse(d[CONF_JARVIS_URL])
    except ValueError:
        fehler[CONF_JARVIS_URL] = "ungueltige_adresse"
        url = None
    if not str(d[CONF_GATEWAY_URL]).startswith(("http://", "https://")):
        fehler[CONF_GATEWAY_URL] = "ungueltige_adresse"
    if fehler:
        return fehler
    try:
        st, _ = await GatewayZugang(session, d[CONF_GATEWAY_URL], d[CONF_GATEWAY_TOKEN]).anfrage("GET", "/health")
        if st in (401, 403):
            fehler[CONF_GATEWAY_TOKEN] = "gateway_token"
        elif st >= 400:
            fehler[CONF_GATEWAY_URL] = "gateway_nicht_erreichbar"
    except GatewayFehler:
        fehler[CONF_GATEWAY_URL] = "gateway_nicht_erreichbar"
    try:
        async with session.ws_connect(url, headers={"Authorization": f"Bearer {d[CONF_JARVIS_TOKEN]}"},
                                      params={"instanz": d[CONF_INSTANZ], "version": VERSION}, timeout=aiohttp.ClientWSTimeout(ws_close=VERBINDEN_ZEIT)) as ws:
            # Jarvis schliesst bei falschem Token sofort (4401); auf eine erste Nachricht oder ein offenes Ende kurz warten.
            try:
                msg = await asyncio.wait_for(ws.receive(), 1.5)
            except TimeoutError:
                msg = None
            if msg is not None and msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                fehler[CONF_JARVIS_TOKEN] = "jarvis_token"
    except aiohttp.WSServerHandshakeError as e:
        fehler[CONF_JARVIS_TOKEN if e.status in (401, 403) else CONF_JARVIS_URL] = "jarvis_token" if e.status in (401, 403) else "jarvis_nicht_erreichbar"
    except (aiohttp.ClientError, TimeoutError, OSError):
        fehler[CONF_JARVIS_URL] = "jarvis_nicht_erreichbar"
    return fehler


def _schema(v: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_INSTANZ, default=v.get(CONF_INSTANZ, STANDARD_INSTANZ)): SelectSelector(
            SelectSelectorConfig(options=list(INSTANZEN), translation_key="instanz")),
        vol.Required(CONF_JARVIS_URL, default=v.get(CONF_JARVIS_URL, "ws://")): str,
        vol.Required(CONF_JARVIS_TOKEN, default=v.get(CONF_JARVIS_TOKEN, "")): _PW,
        vol.Required(CONF_GATEWAY_URL, default=v.get(CONF_GATEWAY_URL, STANDARD_GATEWAY_URL)): str,
        vol.Required(CONF_GATEWAY_TOKEN, default=v.get(CONF_GATEWAY_TOKEN, "")): _PW,
    })


class JarvisConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        fehler: dict[str, str] = {}
        if user_input is not None:
            user_input = {k: (v.strip() if isinstance(v, str) else v) for k, v in user_input.items()}
            await self.async_set_unique_id(user_input[CONF_INSTANZ])
            self._abort_if_unique_id_configured()
            fehler = await pruefen(self.hass, user_input)
            if not fehler:
                return self.async_create_entry(title=f"Jarvis ({user_input[CONF_INSTANZ]})", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}), errors=fehler)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return JarvisOptionsFlow()


class JarvisOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        fehler: dict[str, str] = {}
        aktuell = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            neu = {**aktuell, **{k: v.strip() if isinstance(v, str) else v for k, v in user_input.items()}}
            fehler = await pruefen(self.hass, neu)
            if not fehler:
                return self.async_create_entry(data={k: neu[k] for k in (CONF_JARVIS_URL, CONF_JARVIS_TOKEN, CONF_GATEWAY_URL, CONF_GATEWAY_TOKEN)})
            aktuell = neu
        schema = _schema(aktuell).schema
        schema = vol.Schema({k: v for k, v in schema.items() if k.schema != CONF_INSTANZ})
        return self.async_show_form(step_id="init", data_schema=schema, errors=fehler)
