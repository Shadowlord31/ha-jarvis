"""Durchleitung zum Gateway-Add-on: feste Positivliste, kein freier Zugriff.

Jarvis darf nur lesen (`/health`, `/areas`, `/entities`, `/entities/{id}`, `/history`) und ueber das Gateway schalten
(`POST /call`, `/call_many`). Alles andere liefert `not_allowed`. Die Integration setzt den `X-API-Token`-Header selbst;
Statuscode und Antwort des Gateways gehen unveraendert zurueck. Es gibt hier keinen Aufruf von `hass.services`.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

import aiohttp

from .const import GATEWAY_API, GATEWAY_ZEIT

FEST = {("GET", "/health"), ("GET", "/areas"), ("GET", "/entities"), ("GET", "/history"),
        ("POST", "/call"), ("POST", "/call_many")}
ZEICHEN = re.compile(r"^[A-Za-z0-9_.%-]+$")
PROZENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
PARAM_NAME = re.compile(r"^[A-Za-z0-9_]{1,40}$")


class NichtErlaubt(Exception):
    """Methode oder Pfad stehen nicht auf der Positivliste."""


class GatewayFehler(Exception):
    """Das Gateway ist nicht erreichbar oder antwortet nicht (code: gateway_unreachable | timeout)."""

    def __init__(self, code: str, text: str):
        super().__init__(text)
        self.code, self.text = code, text


def pruefe(methode: str, pfad: str) -> str:
    """Gibt den geprueften Pfad zurueck oder wirft NichtErlaubt."""
    methode = str(methode or "").upper()
    pfad = str(pfad or "")
    if not pfad.startswith("/") or len(pfad) > 300 or "//" in pfad:
        raise NichtErlaubt("Pfad nicht erlaubt")
    teile = pfad[1:].split("/")
    if any(not t or not ZEICHEN.match(t) or PROZENT.search(t) for t in teile):
        raise NichtErlaubt("Pfad nicht erlaubt")
    for t in teile:
        echt = unquote(t)
        if echt in (".", "..") or any(c in echt for c in "/\\?#") or any(ord(c) < 32 for c in echt) or ".." in echt:
            raise NichtErlaubt("Pfad nicht erlaubt")
    if (methode, pfad) in FEST:
        return pfad
    if methode == "GET" and len(teile) == 2 and teile[0] == "entities":
        return pfad
    raise NichtErlaubt("Anfrage nicht erlaubt")


def _params(params) -> dict[str, str]:
    if not params:
        return {}
    if not isinstance(params, dict):
        raise NichtErlaubt("Parameter nicht erlaubt")
    aus = {}
    for k, v in params.items():
        if not PARAM_NAME.match(str(k)) or isinstance(v, (dict, list)) or v is None:
            raise NichtErlaubt("Parameter nicht erlaubt")
        aus[str(k)] = str(v).lower() if isinstance(v, bool) else str(v)
    return aus


class GatewayZugang:
    def __init__(self, session: aiohttp.ClientSession, url: str, token: str):
        self._session, self._basis, self._token = session, url.rstrip("/"), token

    async def anfrage(self, methode: str, pfad: str, params=None, body=None) -> tuple[int, dict]:
        """(Status, Antwort). Wirft NichtErlaubt oder GatewayFehler."""
        pfad = pruefe(methode, pfad)
        abfrage = _params(params)
        methode = methode.upper()
        try:
            async with self._session.request(
                methode, self._basis + GATEWAY_API + pfad, params=abfrage or None,
                json=body if methode == "POST" and isinstance(body, dict) else None,
                headers={"X-API-Token": self._token},
                timeout=aiohttp.ClientTimeout(total=GATEWAY_ZEIT), allow_redirects=False,
            ) as r:
                try:
                    daten = await r.json(content_type=None)
                except ValueError:
                    daten = {}
                return r.status, daten if isinstance(daten, dict) else {"daten": daten}
        except TimeoutError:
            raise GatewayFehler("timeout", "Das Gateway antwortet nicht.")
        except aiohttp.ClientError:
            raise GatewayFehler("gateway_unreachable", "Das Gateway ist nicht erreichbar.")
