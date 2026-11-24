"""Konstanten der Jarvis-Integration."""

DOMAIN = "jarvis"
VERSION = "0.1.1"

CONF_INSTANZ = "instanz"
CONF_JARVIS_URL = "jarvis_url"
CONF_JARVIS_TOKEN = "jarvis_token"
CONF_GATEWAY_URL = "gateway_url"
CONF_GATEWAY_TOKEN = "gateway_token"

STANDARD_INSTANZ = "haupt"
STANDARD_GATEWAY_URL = "http://3744e95d-jarvis-gateway:3003"
INSTANZEN = ("haupt", "garten")

GATEWAY_API = "/api/v1"
GATEWAY_ZEIT = 12
BEFEHL_ZEIT = 10
VERBINDEN_ZEIT = 10
BACKOFF_START = 1
BACKOFF_MAX = 60
ENTPRELLUNG_S = 1.0
FREIGABE_INTERVALL_S = 60

EREIGNISSE = ("timer_fertig", "erinnerung_faellig")
ZIELE = ("alle", "haupt", "hub", "flur", "handy")

SERVICE_TIMER_STARTEN = "timer_starten"
SERVICE_TIMER_STOPPEN = "timer_stoppen"
SERVICE_MELDUNG = "meldung"
SERVICE_AUFGABE_ANLEGEN = "aufgabe_anlegen"
SERVICE_AUFGABE_ERLEDIGT = "aufgabe_erledigt"

NICHT_ERREICHBAR = "Jarvis ist nicht erreichbar"
