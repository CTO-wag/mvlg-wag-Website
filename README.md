# Management-System V2

Die Plattform der Wirtschafts- & Investment-AG am Max-von-Laue-Gymnasium
Koblenz: öffentliche Seite, Bewerbungen und die interne Verwaltung.
Neubau von V1 — gleiche Daten, gleiches Erscheinungsbild, neue Struktur.

Was drin ist: Aufgaben, AG-Treffen mit Zu- und Absagen, Kalender mit
Abo-Adresse je Person, Kassenbuch, Bewerbungsverwaltung, Wettbewerbe,
Projekte, Leadership-Werte, Redaktionsplan, Support-Tickets, Rollen und
Rechte, zweiter Faktor, Push-Benachrichtigungen und ein Auffangnetz bei
Cloudflare, das während eines Ausfalls weiter Bewerbungen entgegennimmt.

Python 3.13 oder neuer, FastAPI, SQLAlchemy, SQLite, Jinja2, htmx. Keine
Build-Kette, kein Framework im Browser.

**Für den Betrieb:** [UEBERGABE.md](UEBERGABE.md) — was wo liegt, wer
drankommt, was zu tun ist, wenn der Rechner ausfällt.
**Sicherheitslücke gefunden?** [SECURITY.md](SECURITY.md)

## Schnellstart

```
git clone <repository>
cd Management-System-V2
copy config.example.cmd config.cmd     # ausfüllen: SECRET_KEY, SMTP, Adressen
start.bat
```

Beim ersten Start entsteht `ERSTE-ANMELDUNG.txt` mit dem Startpasswort.

## Starten

```
start.bat
```

Beim ersten Start richtet sich alles selbst ein: Pakete installieren,
Konfiguration von V1 übernehmen, Datenbank auf V2 bringen. Danach laufen zwei
Server:

| Server    | Port | Was                                        |
|-----------|------|--------------------------------------------|
| Website   | 8000 | Öffentliche Seite, Bewerbung, Anmeldung    |
| Dashboard | 8001 | Die Verwaltung                             |

Angemeldet wird über die Website; das Sitzungs-Cookie gilt für beide, weil
Cookies nicht nach Port getrennt werden.

Weitere Aufrufe:

```
start.bat lokal     nur zum Ausprobieren, ohne Wiederanlauf
start.bat pruefen   Testsuite laufen lassen
start.bat neu       Einrichtung erzwingen
```

Ohne `start.bat` geht es auch direkt — `server.py` liest `config.cmd` selbst
ein:

```
python server.py website
python server.py dashboard
python server.py beide
```

## Der Umstieg von V1

**Es geht nichts verloren, und niemand muss etwas neu einrichten.**

* Dieselbe Datenbank, dieselben Tabellen. `kern/migration.py` fügt nur hinzu:
  fehlende Tabellen, fehlende Spalten, Vorbelegungen. Gelöscht oder umbenannt
  wird nichts.
* Vor der ersten Änderung legt die Migration eine Sicherung an
  (`vor-v2-JJJJ-MM-TT_HH-MM.db` im Sicherungsordner). Die bleibt dauerhaft
  erhalten und fällt nicht der Aufbewahrungsgrenze zum Opfer — sie ist der Weg
  zurück.
* Derselbe `SECRET_KEY` aus V1 → **niemand wird abgemeldet**.
* Dieselben `notification_preferences` samt ntfy-Thema, dieselben
  `push_subscriptions`, dieselben VAPID-Schlüssel → **Benachrichtigungen
  laufen weiter**, ohne dass jemand sein Handy neu einrichtet.
* Bearbeitete E-Mail-Vordrucke bleiben, wie sie sind.
* Abgeschaltete Rechte bleiben abgeschaltet — auch wenn die Vorgabe etwas
  anderes sagen würde.
* Tabellen aus einer früheren Fassung (`chats`, `news` …) werden nicht
  angefasst, nur beim Start einmal genannt.

## Was neu ist

**Struktur.** Statt einer Datei mit 17 700 Zeilen: ein gemeinsamer Kern und
zwei Anwendungen. Vorlagen sind echte Dateien, CSS und JavaScript liegen
getrennt.

**Zwei Server.** Die öffentliche Seite und die Verwaltung lassen sich getrennt
härten, neu starten und im Ernstfall getrennt abschalten.

**Rechte auf drei Achsen.** Rolle und Abteilung geben frei; neu ist die dritte
Achse: einer einzelnen Person lässt sich ein Recht zusätzlich geben oder
ausdrücklich entziehen — ein Entzug schlägt alles andere. Dazu kommt ein Rang
je Rolle: wer keinen höheren Rang hat, kann ein Konto nicht bearbeiten. Damit
kann jemand mit dem Recht „Konten“ nicht mehr den CTO umkonfigurieren.

**Sicherheit.** Kein `unsafe-inline` mehr für Skripte (CSP mit Nonce),
optionaler zweiter Faktor ohne zusätzliches Paket, Sitzungen an den Browser
gebunden und mit Leerlauf-Ablauf, Anmeldeprotokoll samt Fehlversuchen,
Passwortprüfung gegen naheliegende Muster, eigener Sicherheitsbereich im
Dashboard.

**Leistungswerte rechnen sich selbst.** Bei jedem Ereignis sofort, einmal
nachts für alle. Jede Erledigung wird dauerhaft festgehalten und überlebt das
Löschen der Aufgabe — in V1 sank der Wert rückwirkend, wenn jemand aufräumte.

**WhatsApp-Bot.** Begrüßt neue Mitglieder automatisch, Text im Dashboard
anpassbar. Vier Betriebsarten – empfohlen ist `web`: ein eigener Node-Dienst
auf Basis von [whatsapp-web.js](https://wwebjs.dev/), einmal per QR-Code
gekoppelt, danach vollautomatisch an jede Nummer. Kein Business-Konto, keine
genehmigten Vorlagen.

**Startseite anpassbar.** „Womit wir uns beschäftigen“, die Vorteilsliste und
die Stufen stehen in der Datenbank statt im Quelltext. Dazu neu: ein
**Portfolio** unter „Unsere Arbeit“ – was die AG schon gemacht hat, mit
Zeitraum und Ergebnis. Der Abschnitt erscheint erst, wenn ein Eintrag da ist;
eine leere Erfolgsliste wirbt gegen die AG.

**Suchleisten.** Über den langen Listen (Aufgaben, Konten, Mitglieder,
Termine, Bewerbungen, Papierkorb) steht wieder ein Suchfeld. Es filtert im
Browser, ohne Anfrage an den Server: die Liste ist beim Tippen sofort dabei,
und die Eingabe überlebt einen Klick auf „Erledigt“.

**Nichts von fremden Servern.** Die drei Schriften liegen im eigenen Ordner
statt bei Google. Das spart vor dem ersten Buchstaben eine fremde
DNS-Auflösung samt TLS-Aufbau – im Schul-WLAN gut eine halbe Sekunde – und
schickt nicht mehr die IP-Adresse jedes Mitglieds nach Kalifornien. Die
Sicherheitsrichtlinie verbietet fremde Quellen jetzt ausdrücklich.

**Rundgang auf dem Handy.** Auf schmalen Bildschirmen ein Blatt am unteren
Rand mit begrenzter Höhe, eigenem Scrollbereich und festsitzender Fußzeile —
der „Weiter“-Knopf kann nicht mehr unterhalb der Bildschirmkante landen.

## WhatsApp-Bot einrichten

In `config.cmd`:

```
set "WHATSAPP_MODUS=web"
set "WHATSAPP_WEB_TOKEN=<wird von start.bat erzeugt>"
```

`start.bat` startet dann einen dritten Prozess (Fenster „AG-WhatsApp“) und
installiert beim allerersten Mal die Node-Pakete. Einen eigenen Browser lädt
er **nicht** herunter – der Dienst steuert den fern, der ohnehin auf dem
Rechner liegt (Chrome, sonst Edge). Der 200-MB-Download von Puppeteer bricht
in Schulnetzen gerne mittendrin ab und lässt danach jedes `npm install`
scheitern; wer ihn trotzdem will, holt ihn mit
`npx puppeteer browsers install chrome` und er wird dann bevorzugt. Danach im Dashboard unter
**WhatsApp-Bot** den QR-Code mit dem Handy scannen: WhatsApp → Einstellungen →
Verknüpfte Geräte → Gerät verknüpfen. Die Verknüpfung bleibt über Neustarts
bestehen; die Sitzung liegt im Datenordner unter `whatsapp-sitzung`.

**Ehrlich dazu:** Das ist nicht die offizielle Schnittstelle von Meta, sondern
eine Fernsteuerung von WhatsApp Web. Automatisierung verstößt gegen die
Nutzungsbedingungen von WhatsApp, und die verwendete Nummer kann gesperrt
werden. Bei ein paar Willkommensnachrichten im Monat ist das Risiko klein –
trotzdem besser eine Zweitnummer der AG nehmen als eine private. Wer das nicht
will, nimmt `WHATSAPP_MODUS=manuell` (ein Klick je Nachricht, kein Risiko) oder
`cloud` (offiziell, braucht Business-Konto und genehmigte Vorlage).

## Benachrichtigungen und die App auf dem Startbildschirm

Push-Anmeldungen hängen am **Ursprung** (Schema + Host). Daraus folgt, welche
Seite man auf den Startbildschirm legen muss:

* **Zwei Hosts** (`mvlg-wag.de` für die Website, `app.mvlg-wag.de` fürs
  Dashboard – so läuft es hier). Dafür müssen beide Adressen in `config.cmd`
  stehen:

  ```
  set "WEBSITE_URL=https://mvlg-wag.de"
  set "DASHBOARD_URL=https://app.mvlg-wag.de"
  ```

  Daran erkennt die Anwendung die Aufstellung und setzt das Sitzungs-Cookie
  für `.mvlg-wag.de` – ohne das gilt die Anmeldung nur für den Namen, unter
  dem man sich angemeldet hat, und das Dashboard schickt einen sofort wieder
  zur Anmeldeseite.

  Push sind dann zwei getrennte Anmeldungen – deshalb kann sich
  **jede der beiden Seiten selbst anmelden**. Im Dashboard unter
  *Nachrichten* steht ein Hinweis mit dem Weg zur zweiten Anmeldung
  (`/benachrichtigungen` auf der Website). Danach ist es egal, welche der
  beiden Seiten auf dem Startbildschirm liegt.
  Doppelt kommt nichts an: beide Anmeldungen tragen dieselbe Gerätekennung
  (ein Cookie auf der gemeinsamen Domain), und verschickt wird je Gerät nur
  eine Meldung.
  Damit die Anmeldung überhaupt für beide Namen gilt, setzt die Anwendung das
  Sitzungs-Cookie in dieser Aufstellung automatisch auf `.mvlg-wag.de` – ohne
  das landet man im Dashboard sofort wieder auf der Anmeldeseite.
  Auf diesem Rechner testen geht trotzdem: Ruft man `http://localhost:8001`
  auf, bleiben Weiterleitungen und Verweise auf `localhost` – die eingetragenen
  Live-Adressen gelten nur für Aufrufe von außen. Das Sitzungs-Cookie
  verliert dabei die Domain-Angabe, sonst würde der Browser es auf localhost
  wegwerfen und man käme nie über die Anmeldung hinaus.
* **Ein Host** (einfacher, wenn die Startseite *die* App sein soll): Im Tunnel
  `/dashboard` auf Port 8001 leiten, alles andere auf 8000. Dann genügt eine
  einzige Anmeldung für beides.

```yaml
ingress:
  - hostname: mvlg-wag.de
    path: ^/dashboard
    service: http://127.0.0.1:8001
  - hostname: mvlg-wag.de
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Dazu in `config.cmd`:

```
set "WEBSITE_URL=https://mvlg-wag.de"
set "DASHBOARD_URL=https://mvlg-wag.de/dashboard"
```

Auf dem iPhone gilt zusätzlich: Web Push funktioniert **nur**, wenn die Seite
über „Zum Home-Bildschirm“ abgelegt und von dort geöffnet wird. In Safari
selbst gibt es keine Push-Meldungen. Wer das nicht will, nutzt ntfy – das
läuft über eine eigene App und ist von alldem unabhängig.

## Rundgänge

Zwei geführte Rundgänge, beide über dieselbe Mechanik
(`statisch/js/rundgang.js`, Schritte kommen als JSON vom Server):

* **Erst-Rundgang** (`dashboard/routen/konto.py`) – die Einführung für Neue.
* **„Was ist neu“** (`dashboard/routen/neuerungen.py`) – nach dem Umzug auf
  zwei Adressen. Persönlich: eigene Kalenderadresse, eigenes ntfy-Thema,
  eigener Anmeldestand. Wird nie zusammen mit dem Erst-Rundgang angeboten.

Zwei Dinge hängen am Namen der Seite und lassen sich für niemanden von außen
umstellen: das **Kalender-Abo** (feste Adresse in der Kalender-App) und
**Web-Push** (gilt je Ursprung). Was davon bei wem noch offen ist, rechnet
`kern/umzug.py` aus; die Übersicht zeigt es, bis es erledigt ist:

* Kalender: erledigt, sobald die Kalender-App die neue Adresse abgeholt hat
  (`users.calendar_last_fetch`, gesetzt beim `.ics`-Abruf).
* Push: erledigt, sobald es je Ursprung eine Anmeldung von nach dem Umzug
  gibt (`umzug.UMZUG_AB`).

Bewusst kein Haken zum Selbstsetzen – der wäre in dem Moment falsch, in dem
ihn jemand zu früh anklickt. Wer kein Termin-Abo will, wählt den Punkt
ausdrücklich ab; wer Push in seinen Einstellungen aus hat, wird gar nicht
gefragt.

Zu jedem kommenden Treffen kann jeder zusagen oder absagen (mit Grund) und
vorher Punkte für die Tagesordnung eintragen; im Treffen werden sie abgehakt.
Das ist bewusst getrennt von der Anwesenheit: Die wird hinterher erfasst und
zählt für den Leadership-Wert, die Zusage vorher ist nur Planung.

Beide Rundgänge lassen sich unter *Support* neu starten. Sie melden sich
wieder bei allen, wenn `RUNDGANG_FASSUNG` bzw. `umzug.FASSUNG` hochgezählt
wird - genau das ist beim Überarbeiten der Pflichtschritt: Wer den alten
Rundgang abgehakt hat, sieht den neuen sonst nie.

## Hinter einem Tunnel

Alles, was am Namen der Seite hängt, richtet sich nach dem Aufruf
(`cfg.adressen_fuer`). Damit bleibt ein Aufruf über `localhost` örtlich - und
ein Aufruf von außen nicht. Entscheidend ist dabei **nicht** der Host allein:
Reicht der Tunnel den ursprünglichen Namen nicht durch, sondern seinen
eigenen (`127.0.0.1`), sähe die Anwendung sonst einen örtlichen Aufruf und
würde jeden Verweis der öffentlichen Seite dorthin umbiegen. Deshalb gilt:
Sobald eine Proxy-Kopfzeile dabei ist (`X-Forwarded-*`, `CF-*`, `Forwarded`),
zählen die eingestellten Adressen - siehe `cfg.ueber_proxy()` und
`webbasis.OertlicheCookies`.

## Wenn etwas schiefgeht

Zwei Wege zurück, beide neu:

* **Zweiter Faktor verloren.** Beim Einschalten gibt es acht Ersatzcodes,
  jeder gilt einmal statt des Zahlencodes (`kern/sicherheit.py`,
  `ersatzcodes_erzeugen`). Sind auch die weg, setzt der Vorstand den zweiten
  Faktor unter *Konten* zurück – die Person bekommt darüber eine E-Mail, und
  es steht im Protokoll.
* **Datenbank zurücksetzen.** Unter *Papierkorb & Sicherungen* lässt sich
  eine Sicherung einspielen. Vorher wird der jetzige Stand automatisch als
  `vor-einspielen_*.db` abgelegt; bestätigt wird durch Eintippen des Wortes
  EINSPIELEN. Eingespielt wird über die SQLite-Sicherungsfunktion, nicht
  durch Austauschen der Datei – das überlebt offene Verbindungen.

**Störungen melden sich von selbst.** Scheitert eine Sicherung oder verliert
der WhatsApp-Bot die Kopplung, geht das an den Vorstand statt nur ins
Konsolenfenster (`kern/stoerung.py`). Höchstens einmal je 12 Stunden, und
wenn es wieder läuft, kommt eine Entwarnung.

## Tägliche Hinweise

Einmal täglich zur `REMINDER_HOUR` laufen vier Dinge:

* Aufgaben, die heute oder morgen fällig sind (`kern/aufgaben.py`)
* AG-Treffen von heute und morgen – an alle
* Kalendertermine von heute und morgen – nur an die Betroffenen
* Bewerbungen, die länger als drei Tage unbeantwortet sind – an alle mit dem
  Recht *bewerbungen*, höchstens alle drei Tage

Die letzten drei stehen in `kern/hinweise.py`. Jeder Datensatz merkt sich in
`erinnert_am`, wann zuletzt erinnert wurde – ein Neustart am selben Tag
schickt deshalb nichts doppelt.

## Farben im Dunkelmodus

Eine Regel, die man kennen muss, bevor man dort etwas anfasst: **Ein Akzent
mit zehn Prozent Deckkraft über dem Seitengrund funktioniert im Hellmodus und
im Dunkelmodus nicht.** Über hellem Papier ist das ein zarter Farbhauch; über
dunklem Marineblau hebt es die Fläche kaum an, trägt aber auch keine Farbe
hinein - heraus kommt Schmutzgrau. Nachgemessen an den Meldungskästen:
Warnung `#24252B`, Fehler `#201D2C`, Erfolg `#152630` - drei Grautöne, die
sich weder voneinander noch von einem Fehler unterscheiden ließen.

Deshalb im Dunkelmodus:

* **Flächen** kommen aus der Stufenleiter (`--flaeche`, `--flaeche-2`), nicht
  aus einem Akzent über dem Grund.
* **Die Bedeutung** tragen Rand, Zeichen und fette Zeile - die halten Farbe
  auch bei voller Sättigung.
* Wo eine getönte Fläche doch passt (Abzeichen, Zustandsknöpfe), wird der
  Akzent **in die Fläche** gemischt (`color-mix(… 18%, var(--flaeche))`),
  nicht über den Grund gelegt.

Warme Töne auf blaugrauem Grund heben sich rechnerisch selbst auf: Bernstein
ergab bei 15 % ein reines Grau und erst bei 30 % Farbe - dann aber Oliv.

## Rückmeldungen und das Scrollen

Nach einem abgeschickten Formular bleibt die Seite **stehen**, wo sie war
(der Stand wird in `htmx:beforeSwap` gemerkt und danach zurückgesetzt), und
die Antwort des Servers wird aus dem Bereich herausgenommen und unten ins
Bild gehängt (`#meldungsplatz`). Vorher stand sie immer ganz oben – wer unten
in einem Formular arbeitete, sah sie nicht und wurde zusätzlich an den Anfang
geworfen.

Nur die Antwort auf die letzte Aktion wandert dorthin; sie trägt dafür
`data-rueckmeldung` (gesetzt im Makro `rueckmeldung`). Dauerhafte Hinweise im
Bereich – etwa der zum Startpasswort – bleiben stehen, wo sie hingehören.
Beim **Bereichswechsel** (GET) wird weiterhin nach oben gescrollt.

## Push auf dem Handy

`statisch/js/push.js` muss **im Rahmen** geladen werden, nicht im Bereich
*Nachrichten*: Ein `<script>` in einem per htmx nachgeladenen Stück läuft
unter der Nonce-Richtlinie nicht. Im Dashboard fehlte die Einbindung ganz –
der Knopf hatte niemanden, der zuhört, und ein Druck darauf tat nichts.

Auf dem iPhone kommt dazu: Web Push gibt es nur, wenn die Seite über „Zum
Home-Bildschirm“ abgelegt und von dort geöffnet wurde. In Safari selbst fehlt
`window.PushManager`; das Skript erkennt das und sagt es. Und
`Notification.requestPermission()` muss direkt aus der Berührung heraus
aufgerufen werden – siehe den Kommentar dort.

## Das Kalender-Abo

Die persönliche `.ics`-Adresse wird von **beiden** Anwendungen unter demselben
Pfad ausgeliefert (`kern/kalender_abo.py`, eingehängt in `website/app.py` und
`dashboard/app.py`). Grund: Diese Adresse trägt jemand einmal in seine
Kalender-App ein und sieht sie danach nie wieder – sie darf nicht daran
scheitern, dass gerade ein Hostname klemmt. Ausgegeben wird die Adresse auf
dem **Dashboard-Namen**. Das war einmal andersherum gedacht, bis eine Messung
das Gegenteil zeigte: Solange unter `mvlg-wag.de` noch die alte Fassung läuft,
antwortet dieselbe Kennung dort mit 404 und unter `app.mvlg-wag.de` mit der
Datei. Ausgegeben wird deshalb die Adresse, die nachweislich antwortet.

Ist die Kennung unbekannt, kommt kein nacktes „Nicht gefunden“, sondern ein
Text, der die drei üblichen Gründe nennt. Und im Bereich *Kalender* gibt es
**„Adresse prüfen“**: Das holt die eigene Adresse über das offene Netz ab –
denselben Weg, den auch das Telefon geht – und sagt, was eine Kalender-App
dort vorfindet (erreichbar? richtiger Typ? wie viele Termine?). Schlägt es
fehl, wird derselbe Pfad unter dem anderen Namen probiert: Antwortet der,
liegt es nicht an der Kennung, und die Meldung sagt das auch.

## Wie lange eine Anmeldung hält

Beim Anmelden steht ein Haken **„Angemeldet bleiben“**, vorausgewählt. Daran
hängen zwei Sätze von Fristen:

| | Leerlauf | Höchstdauer |
|---|---|---|
| mit Haken (Standard) | `SITZUNG_DAUERHAFT_LEERLAUF_TAGE` (90 Tage) | `SITZUNG_DAUERHAFT_TAGE` (180 Tage) |
| ohne Haken | `SITZUNG_LEERLAUF_MINUTEN` (8 Stunden) | `SITZUNG_HOECHSTDAUER_STUNDEN` (24 Stunden) |

Vorher galten die kurzen Fristen für alle. Wer nachmittags arbeitete und am
nächsten Tag wiederkam, musste sich neu anmelden – bei einer AG, die sich alle
zwei Wochen trifft, praktisch jedes Mal.

Die Wahl steht in `user_sessions.dauerhaft` und überlebt auch den zweiten
Faktor (sie wandert in der halben Anmeldung mit). Bestehende Sitzungen
bekommen bei der Migration eine 1 – die Umstellung wirft niemanden hinaus.
Der Sitzungs-Cookie lebt so lange wie die längstmögliche Sitzung; wie lange
sie wirklich gilt, entscheidet der Server.

## Sicherungen

`kern/sicherung.py`, alle `BACKUP_INTERVAL_HOURS` Stunden, aufbewahrt werden
`BACKUP_KEEP` Stück (Standard 2). Eine Kopie vor einer Strukturänderung legt
die Migration selbst an – aber nur, wenn wirklich etwas ansteht
(`AKTUELLER_STAND` gegen die Marke in `app_settings`), nicht bei jedem Start.

Von der Aufbewahrungsgrenze ausgenommen ist genau eine Datei: die älteste
`vor-v2-*.db`. Das ist der Stand von V1, bevor die Migration das erste Mal
etwas angefasst hat – der einzige Weg zurück.

## Aufbau

```
kern/            gemeinsam genutzt von beiden Servern
  einstellungen  alle Konfigurationswerte an einer Stelle
  modelle        die Tabellen (schema-gleich mit V1)
  migration      V1 → V2, nicht zerstörend
  rechte         Rollen, Abteilungen, persönliche Ausnahmen
  sicherheit     Passwörter, Token, TOTP, Anmeldebremse
  sitzung        wer ist angemeldet, wer darf was
  leistung       automatisches Scoring
  whatsapp       der Willkommens-Bot
  …
website/         Port 8000
dashboard/       Port 8001
whatsapp-dienst/ Node-Beiwagen (whatsapp-web.js), Port 8099
vorlagen/        Jinja-Vorlagen als Dateien
statisch/        CSS, JavaScript, Bilder, Schriften
tests/           Testsuite (python -m unittest discover -s tests -t .)
werkzeuge/       Skripte zum Nachbauen von Bildern und Ähnlichem
```

## Telefonnummern

Sehr viele schreiben ihre Nummer ohne alles: `1516 1234567`. So ruft man sie
jemandem zu – und so stand sie bisher auch in der Datenbank. Für WhatsApp ist
das eine Auslandsnummer ins Nichts: Die Begrüßung ging nicht raus, und niemand
merkte es.

Jetzt wird die Nummer gerichtet statt abgelehnt. Alles hiervon führt zum
selben Ergebnis `+49 163 6177263`:

```
1636177263      0163 6177263     0163/6177263     +49 163 6177263
491636177263    +4916 36 177263  004916 36177263  0163-617 7263
```

Die Landesvorwahl wird dabei nicht verdoppelt, und ausländische Nummern
(`+43 …`) bleiben unangetastet. Nur was auch danach unmöglich ist – zu kurz,
keine Ziffern – führt zu einer Rückfrage mit Beispiel; die übrigen Eingaben
des Formulars bleiben dabei stehen.

Gespeichert wird einheitlich `+49 163 6177263`: in der Bewerbung, beim Anlegen
und Ändern von Konten, unter „Mein Konto“ und im CSV-Export. Ältere Einträge
werden beim Anzeigen gerichtet – ohne die Datenbank anzufassen –, und der
`tel:`-Link funktioniert damit auch vom Handy aus.

## Weniger Handarbeit

**Anwesenheit in zwei Klicks.** „Alle“ kreuzt an, wer da ist – die zwei
Fehlenden wählt man wieder ab. Vorher waren das zwanzig Einzelklicks jede
Woche. Mit Namensfilter, und „Alle“ trifft nach dem Filtern nur die
Sichtbaren.

**Erledigtes verschwindet aus dem Weg.** Aufgaben, die länger als 30 Tage
abgehakt sind, werden nicht mehr mitgeladen – sonst wächst die Liste über ein
Schuljahr auf hunderte Zeilen. Ein Hinweis nennt die Zahl, ein Klick zeigt sie
trotzdem. Gelöscht wird nichts.

**Das Anlegen-Formular bleibt nach dem Speichern offen** (Aufgaben,
Kassenbuch). Nach einer Sitzung trägt man selten nur eine Aufgabe ein.

**Leere Bereiche zeigen den Weg.** Statt „Noch keine Buchungen“ steht dort
jetzt ein Knopf, der das richtige Formular aufklappt und den Schreibzeiger
hineinsetzt.

## Das Logo in den E-Mails

Es hatte einen weißen Hintergrund fest eingebrannt – kein einziger
durchsichtiger Punkt. In der Mail sitzt es auf der navyblauen Kopfleiste,
also klebte dort ein weißer Kasten, im hellen wie im dunklen Modus.

Jetzt trägt das Bild denselben Navy-Ton wie die Leiste (`#0E2647`), die Naht
ist unsichtbar. Bewusst kein transparentes PNG: Mailprogramme tauschen im
Dunkelmodus gern Hintergründe aus, dann stünde ein dunkles Wappen auf dunklem
Grund. Ein Bild mit eigenem Grund sieht überall gleich aus.

Daneben steht der Name jetzt als **Text**, nicht im Bild – lesbar auch für
alle, die Bilder abgeschaltet haben. Neu gebaut wird das Logo mit

```
python werkzeuge/vorschaubild_bauen.py
```

## Wie die Seite nach aussen wirkt

**Vorschaubild beim Verschicken.** Wer die Adresse in WhatsApp, Discord oder
Signal einfügt, sieht ein 1200x630-Bild mit Wappen, Namen und Motto – nicht
nur einen blauen Link. `/bewerbung` hat ein eigenes Bild mit „Bewirb dich“,
weil genau dieser Link herumgeschickt wird, um Leute zu werben.

Beide Bilder baut ein Skript, damit sie sich mit dem Motto ändern lassen:

```
python werkzeuge/vorschaubild_bauen.py
```

Die Adresse des Bildes trägt eine Prüfsumme (`?v=…`). Das ist kein Zierrat:
Chat-Apps merken sich ein Vorschaubild je Adresse und zeigen sonst nach einer
Änderung wochenlang das alte.

**robots.txt** liegt unter `/robots.txt` und wird erzeugt, nicht gepflegt –
gesperrt ist alles, dessen Adresse ein Geheimnis enthält (Kalender-Abo,
Passwort-Link) oder das nichts im Index verloren hat.

**sitemap.xml** nennt die fünf öffentlichen Seiten mit einem ehrlichen
`lastmod`: dem Änderungsdatum der Vorlage, bei der Startseite zusätzlich dem
letzten gepflegten Portfolio-Eintrag. Vorher stand dort stur das heutige
Datum – wer einer Suchmaschine jeden Tag „alles neu“ meldet, dem glaubt sie
das Datum irgendwann nicht mehr.

**security.txt** unter `/.well-known/security.txt` (RFC 9116) sagt, wohin man
sich wendet, wenn man eine Lücke findet. Ohne die Datei landet so etwas im
Zweifel öffentlich in einer WhatsApp-Gruppe.

## Damit Fehler nicht wehtun

Leute vertippen sich, lassen Felder leer und klicken auf den falschen Knopf.
Das System ist darauf eingestellt:

* **Eingaben überleben einen Fehler.** Meldet der Server „Titel fehlt“, steht
  alles andere noch im Formular – auch die Auswahlfelder und das Datum. Erst
  wenn es geklappt hat, ist das Formular wieder leer.
* **Kein versehentliches Wegklicken.** Wer etwas eingetippt hat und in einen
  anderen Bereich wechselt, wird einmal gefragt. Ohne Eingabe fragt niemand.
* **Ein Weg zurück nach jedem Löschen.** Die Erfolgsmeldung bringt einen
  Knopf in den Papierkorb mit; 30 Tage lang ist alles wiederherstellbar,
  samt Teilschritten und Kommentaren.
* **Zahlen werden nicht geraten.** `12 50` wird nicht stillschweigend zu
  1.250 € – das System fragt nach. `12,50`, `12.50`, `1.234,56`, `12,-` und
  `12,50 €` versteht es dagegen alle.
* **Die Anmeldung läuft nicht unter den Händen weg.** Ist die Sitzung
  abgelaufen, springt die Seite nicht mehr sofort zur Anmeldung, sondern
  erklärt es – der getippte Text bleibt stehen und lässt sich kopieren.
* **Das Startpasswort wird angesprochen.** Wer sein Passwort noch nie selbst
  geändert hat, sieht auf der Übersicht einen Hinweis mit Knopf dorthin.
* **Gefährliches sagt, was es anrichtet.** „Papierkorb leeren (17)“ statt
  „Papierkorb leeren“, und die Rückfrage nennt die Zahl noch einmal.
* **Nichts kaputtzumachen, was hängt.** Eine Rolle oder Abteilung, an der
  noch Konten hängen, lässt sich nicht löschen – mit Angabe, wie viele es
  sind.

## Was noch dazugekommen ist

**Alles läuft ohne fremde Server.** Keine Schriften von Google, keine
Bibliotheken von einem CDN – die Sicherheitsrichtlinie verbietet es jetzt
ausdrücklich. Ein Test prüft das bei jedem Lauf mit.

**Auf dem Handy geprüft.** Jeder der 23 Bereiche wurde bei 375 und bei 320
Pixel Breite durchgesehen: nichts ragt über den Rand, die Seite lässt sich
nirgends seitlich schieben, und Knöpfe, die man mit dem Finger trifft, sind
mindestens 34 Pixel hoch.

**Suchleisten** über Aufgaben, Konten, Mitgliedern, Terminen, Bewerbungen,
Papierkorb, Buchungen, Postfach, Support und der Leadership-Rangliste.

## Tests

```
start.bat pruefen
```

oder direkt:

```
python -m unittest discover -s tests -t .
```

183 Tests. Sie laufen immer gegen eine frische Datenbank in einem temporären
Ordner; der echte Datenbestand wird nie angefasst — das prüft die Suite sogar
ausdrücklich. Vier Dateien sind dabei besonders:

* `test_ablaeufe.py` spielt in jedem Bereich anlegen → ändern → löschen durch.
  Dabei fiel auf, dass ein Projekt mit Team sich gar nicht löschen liess.
* `test_alle_routen.py` ruft jede Adresse beider Server auf – angemeldet,
  nicht angemeldet und als einfaches Mitglied. Nirgends ein Serverfehler.
* `test_bedienung.py` hält jeden gemeldeten Fehler fest, damit er nicht
  wiederkommt.
* `test_zwei_adressen.py` fährt die echte Aufstellung mit zwei Namen hoch und
  prüft Anmeldung, Push und Abmelden über beide.
* `test_telefon.py` hält jede Schreibweise fest, die im Formular ankommt.
* `test_seo.py` prüft, was Suchmaschinen und Chat-Apps sehen: robots.txt,
  Sitemap, Vorschaubild samt Maßen und Gewicht.
* `test_fehleingaben.py` tippt Unsinn in jedes Formular: leer abschicken,
  `12 50` als Betrag, `<script>` im Titel, 5000 Zeichen Titel, das eigene
  Konto löschen. Nichts davon darf abstürzen oder falsche Daten anlegen.

---

© 2026 **Janis Hahn**. Entwickelt und der Wirtschafts- & Investment-AG des
Max-von-Laue-Gymnasiums Koblenz zur Verfügung gestellt. Alle Rechte am System
verbleiben beim Urheber.
