from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_GATEWAY_TOKEN, CONF_GATEWAY_URL, CONF_JARVIS_TOKEN, CONF_JARVIS_URL

SCHWAERZEN = {CONF_GATEWAY_TOKEN, CONF_JARVIS_TOKEN, CONF_GATEWAY_URL, CONF_JARVIS_URL}


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    c = entry.runtime_data.client
    return {
        "eintrag": async_redact_data(dict(entry.data), SCHWAERZEN),
        "optionen": async_redact_data(dict(entry.options), SCHWAERZEN),
        "status": {"verbunden": c.verbunden, "timer": len(c.timer), "gateway_ok": c.gateway_ok,
                   "gateway_version": c.gateway_version, "abonnierte_entitaeten": len(entry.runtime_data.push.abo),
                   "freigegebene_entitaeten": len(entry.runtime_data.push.freigegeben)},
    }
