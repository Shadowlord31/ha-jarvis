# Jarvis for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/Shadowlord31/ha-jarvis.svg)](https://github.com/Shadowlord31/ha-jarvis/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

One connection between the self-hosted family assistant **Jarvis** and Home Assistant:

```
Jarvis (NAS, Docker)  <-- WebSocket (outbound from HA) -->  Integration "jarvis"  -->  Gateway add-on  -->  Home Assistant
```

---

## 🇩🇪 Deutsch

### Was macht die Integration?

- Verbindet sich **ausgehend** per WebSocket mit Jarvis (`ws://<NAS-IP>:8340/ws/ha`) – kein offener Port in Home Assistant nötig.
- Reicht Anfragen von Jarvis an das **Jarvis-Gateway-Add-on** durch (nur eine feste Positivliste von Pfaden).
- Meldet Zustandsänderungen der im Gateway freigegebenen Entitäten an Jarvis.
- Stellt Dienste, Sensoren und ein Ereignis für Timer, Meldungen und Aufgaben bereit.

### Installation (HACS)

1. HACS → Integrationen → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/Shadowlord31/ha-jarvis` (Kategorie *Integration*).
2. **Jarvis** installieren und Home Assistant **neu starten** (nicht nur den Browser neu laden).
3. In Jarvis (`config.json`) `"ha_integration": {"aktiv": true, "token": "<mind. 16 Zeichen>"}` setzen und den Container neu starten.
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → **Jarvis**: Instanz, Jarvis-Adresse und -Token, Gateway-Adresse (Standard `http://3744e95d-jarvis-gateway:3003`) und Gateway-Token eintragen. Beide Verbindungen werden geprüft.

### Dienste

| Dienst | Zweck |
|---|---|
| `jarvis.timer_starten` | Timer starten (`dauer`, `name`, `ueberall`); Antwort `{id, ende}` |
| `jarvis.timer_stoppen` | Timer stoppen (genau eins von `id`, `name`, `alle`) |
| `jarvis.meldung` | Meldung anzeigen (`nachricht`, `titel`, `symbol`, `dringend`, `sprechen`, `ziel`, `person`); Antwort `{erreicht, personen, nicht_erreicht}` |
| `jarvis.aufgabe_anlegen` | To-Do-Aufgabe anlegen |
| `jarvis.aufgabe_erledigt` | To-Do-Aufgabe abhaken |

#### Meldung an bestimmte Personen

`ziel` ist `alle`, `handy`, `browser`, `display` oder der Name eines Geräts (Jarvis ab dem Stand „eine Ansicht“; ältere Werte `hub` und `flur` gelten weiter). `person` schickt die Meldung nur auf die Geräte dieser Personen (Geräte, bei denen in Jarvis der Standardsprecher gesetzt ist): ein Name (`Thomas`), mehrere Namen (`Thomas, Jenny` oder als YAML-Liste) oder eine Gruppe (`erwachsene`, `kinder`, `admins`, `familie`). Ohne `person` geht die Meldung wie bisher an das `ziel`. Ein unbekannter Name bricht die Aktion mit einer lesbaren Fehlermeldung ab, es wird nichts gesendet. Mit `response_variable` lässt sich prüfen, ob jemand erreicht wurde (setzt Jarvis ab dem Stand mit Meldung an Personen voraus):

```yaml
- action: jarvis.meldung
  data:
    nachricht: Die Waschmaschine ist fertig.
    person: Thomas
  response_variable: antwort
- if:
    - condition: template
      value_template: "{{ antwort.erreicht == 0 }}"
  then:
    - action: script.telegram_notify   # Rückfall
```

Antwort: `erreicht` (Zahl der Verbindungen), `personen` (erreichte Personen), `nicht_erreicht` (Personen ohne verbundenes Gerät).

### Entitäten (Gerät „Jarvis (<Instanz>)“)

`binary_sensor.jarvis_verbunden`, `sensor.jarvis_aktive_timer`, `sensor.jarvis_naechster_timer`, `event.jarvis_ereignisse` (`timer_fertig`, `erinnerung_faellig`). Ist Jarvis nicht erreichbar, sind die Sensoren *nicht verfügbar* und die Dienste melden „Jarvis ist nicht erreichbar“. Es wird nichts zwischengespeichert.

### Sicherheit

Siehe [SECURITY.md](SECURITY.md). Zugangsdaten stehen nur im Config Entry; die Diagnose schwärzt sie.

---

## 🇬🇧 English

### What does it do?

- Connects **outbound** via WebSocket to Jarvis (`ws://<NAS-IP>:8340/ws/ha`) – no open port needed in Home Assistant.
- Forwards Jarvis requests to the **Jarvis gateway add-on** (fixed allow-list of paths only).
- Reports state changes of entities released by the gateway to Jarvis.
- Provides services, sensors and an event entity for timers, notices and tasks.

### Installation (HACS)

1. HACS → Integrations → ⋮ → *Custom repositories* → `https://github.com/Shadowlord31/ha-jarvis` (type *Integration*).
2. Install **Jarvis** and **restart** Home Assistant (a browser reload is not enough).
3. In Jarvis' `config.json` set `"ha_integration": {"aktiv": true, "token": "<at least 16 characters>"}` and restart the container.
4. Settings → Devices & services → Add integration → **Jarvis**: instance, Jarvis address and token, gateway address (default `http://3744e95d-jarvis-gateway:3003`) and gateway token. Both connections are checked.

### Services

`jarvis.timer_starten`, `jarvis.timer_stoppen`, `jarvis.meldung`, `jarvis.aufgabe_anlegen`, `jarvis.aufgabe_erledigt` (see Deutsch above for fields).

### Entities (device "Jarvis (<instance>)")

`binary_sensor.jarvis_verbunden`, `sensor.jarvis_aktive_timer`, `sensor.jarvis_naechster_timer`, `event.jarvis_ereignisse`. While Jarvis is unreachable the sensors are *unavailable* and services raise "Jarvis ist nicht erreichbar". Nothing is cached.

### Security

See [SECURITY.md](SECURITY.md). Credentials live only in the config entry; diagnostics redact them.
