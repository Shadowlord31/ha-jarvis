# Sicherheitshinweise

Dies ist ein privates Hobbyprojekt ohne Garantie und ohne kommerziellen Support. Die Nutzung erfolgt auf eigene Verantwortung (siehe Lizenz).

## Was die Integration tut und nicht tut

- Die Integration verbindet sich **ausgehend** zu Jarvis und zum Jarvis-Gateway. Sie öffnet keinen Port in Home Assistant.
- Zugangsdaten (Jarvis-Token, Gateway-Token) liegen nur im Config Entry und werden weder geloggt noch in der Diagnose ausgegeben.
- Jarvis kann über die Leitung nur eine feste Positivliste von Gateway-Pfaden abfragen (`GET /health`, `/areas`, `/entities`, `/entities/{id}`, `/history`, `POST /call`, `/call_many`). Alles andere wird abgelehnt.
- Die Integration führt keine freien Home-Assistant-Dienstaufrufe aus; die Freigabe, was Jarvis steuern darf, liegt allein im Gateway.
- Verwende `wss://`, wenn die Leitung nicht im vertrauenswürdigen Heimnetz bleibt.

## Sicherheitslücke melden

Bitte melde Sicherheitslücken **nicht** als öffentliches Issue, sondern vertraulich über den Reiter **Security → Report a vulnerability** dieses Repositories.

Ich kümmere mich in meiner Freizeit darum, kann aber keine festen Reaktionszeiten zusagen.
