# Übergabe

Was passiert, wenn der bisherige CTO nicht mehr da ist? Solange die Antwort
"dann steht die Plattform" lautet, ist sie ein privates Projekt und keine
Einrichtung der AG.

Hier stehen keine Passwörter, nur wo etwas liegt und wer drankommt.

## Woran die Plattform hängt

| Baustein | Wo | Wer kommt dran |
|---|---|---|
| Domain mvlg-wag.de | Registrar: | |
| DNS, Auffangnetz | Cloudflare | |
| Der Rechner | | |
| Tunnel | cloudflared auf demselben Rechner | |
| E-Mail-Versand | Brevo | |
| WhatsApp-Bot | gekoppelte Sitzung auf dem Rechner | |
| Datenbestand | `daten/ag_plattform.db` | |

Bitte ausfüllen und aktuell halten.

## Zugänge

Diese Konten sollten mindestens zwei Personen haben, üblicherweise CTO und
CEO:

- [ ] Cloudflare
- [ ] Registrar der Domain
- [ ] Brevo
- [ ] Benutzerkonto auf dem Rechner
- [ ] `config.cmd` (enthält SECRET_KEY, SMTP-Passwort, Abholschlüssel)
- [ ] Ablageort der Sicherungen
- [ ] Ein Konto mit der Rolle CTO in der Plattform

Ein gemeinsamer Passwortspeicher reicht, Bitwarden ist kostenlos. Kein
Zettel, kein Chatverlauf.

Beim Wechsel des CTO alle Passwörter neu setzen, nicht nur weitergeben.

## Alltag

Starten: `start.bat`. Einzelheiten in der README, Kapitel "Starten".

Läuft es? `https://mvlg-wag.de` aufrufen. Kommt die Notfassung, läuft die
Anwendung nicht – das Auffangnetz antwortet dann an ihrer Stelle und nimmt
weiter Bewerbungen entgegen.

Zustand des Auffangnetzes: `https://mvlg-wag.de/__ausfall/selbsttest`

Wenn etwas kaputt ist: README, Kapitel "Wenn etwas schiefgeht".

## Wenn der Rechner weg ist

1. Die öffentliche Seite antwortet weiter. Es geht nichts verloren, solange
   der Rechner innerhalb von vier Wochen wiederkommt.
2. Jüngste Sicherung holen: `daten/backups/`, oder die Kopie außer Haus.
3. Repository klonen, `config.example.cmd` nach `config.cmd` kopieren und
   ausfüllen, Sicherung nach `daten/ag_plattform.db` legen, `start.bat`.
4. Tunnel neu verbinden oder DNS umstellen.
5. Im Dashboard prüfen, ob die Bewerbungen aus der Ausfallzeit eingetragen
   wurden.

Ohne Schritt 2 ist alles weg.

## Regelmäßig

| Wie oft | Was | Wer |
|---|---|---|
| wöchentlich | schauen, ob die Seite läuft | |
| monatlich | Sicherung an einen zweiten Ort | |
| halbjährlich | dieses Dokument durchgehen | |
| bei Vorstandswechsel | Zugänge neu setzen | |
| jährlich | Rechnungen: Domain, Dienste | |

## Was jemand können muss

Für den Betrieb: eine Datei bearbeiten, einen Ordner kopieren, ein Programm
starten, in der README nachschlagen. Für Änderungen am Programm braucht es
Python-Kenntnisse – für den Betrieb nicht.

## Datenschutz

Die Plattform verwaltet personenbezogene Daten von Minderjährigen.

1. Der Ordner `daten/` verlässt den Rechner nur als Sicherung an einen Ort,
   den der Vorstand kennt. Nicht in eine private Cloud, nicht in einen Chat,
   nicht auf einen USB-Stick.
2. Bewerbungen werden nach Ablauf der Frist automatisch gelöscht (abgelehnte
   nach 180 Tagen, angenommene nach 365). Diese Frist wird nicht verlängert.
3. Wer die Plattform übernimmt, bekommt Zugriff auf diese Daten. Das gehört
   dem Vorstand mitgeteilt.

Zuletzt geprüft am:            von:
