# Auffangnetz einrichten

Was du danach hast: Ist die Plattform nicht erreichbar, sieht ein Besucher
statt der englischen Cloudflare-Seite eine eigene Seite. Sie erklärt, was los
ist, sieht im Hintergrund nach, ob die Plattform wieder da ist, nimmt ein
Support-Ticket für den CTO auf – und, das Wichtigste: **sie nimmt weiterhin
Bewerbungen entgegen.**

Neu geladen wird die Seite nur auf Knopfdruck, nie von selbst. Sie trägt das
Bewerbungsformular; ein Reload mitten im Tippen würde alles Getippte
wegwerfen, und wer sich einmal umsonst beworben hat, tut es kein zweites Mal.
Ist die Plattform wieder erreichbar, steht das im Band und daneben liegt ein
Knopf – wer mittendrin ist, schickt erst ab. Das geht auch dann noch: Die
Bewerbung nimmt der Worker entgegen, nicht der Server.

Unter der Fehlermeldung steht die komplette Startseite noch einmal, fest
eingetragen: wer wir sind, wie das Jahr läuft, dein Weg in der AG, und das
vollständige Bewerbungsformular. Was im Dashboard gepflegt wird (Aktivitäten,
Arbeitsproben, Quiz), fehlt dort mit Absicht – es käme aus derselben
Datenbank, die gerade nicht antwortet.

Eine Bewerbung, die während eines Ausfalls eingeht, wird bei Cloudflare
hinterlegt und automatisch eingetragen, sobald die Plattform wieder läuft –
mit dem richtigen Zeitpunkt, samt Bestätigungsmail an die bewerbende Person
und Benachrichtigung an alle, die Bewerbungen sichten. Für sie sieht es
hinterher aus wie eine ganz normale Bewerbung.

Dauer: etwa 20 Minuten. Du brauchst nur einen Browser – auf dem Laptop muss
nichts installiert werden.

---

## Schritt 1: Der Worker anlegen

1. `dash.cloudflare.com` öffnen und anmelden.
2. Links **Compute (Workers)** anklicken, dann **Create application**,
   dann **Create Worker**.
3. Als Namen `wag-auffangnetz` eintragen. **Deploy** klicken.
4. Auf **Edit code** klicken. Im Editor steht ein Beispiel – alles markieren
   und löschen.
5. Den vollständigen Inhalt von `cloudflare/worker.js` hineinkopieren.
6. Oben rechts **Deploy** klicken.

Das ist schon der halbe Weg. Der Worker läuft, hängt aber noch an keiner
Adresse und kann noch keine Meldungen speichern.

---

## Schritt 2: Vor die Domain hängen

Der Worker muss **vor allem** stehen, nicht nur vor der Startseite – wer mitten
in der Arbeit ist, fällt auf einer Unterseite hinein.

1. Im Worker auf den Reiter **Settings**, dann **Domains & Routes**.
2. **Add** → **Route**.
3. Zone: `mvlg-wag.de`. Route: `mvlg-wag.de/*`
4. Noch einmal **Add** → **Route**: Zone `mvlg-wag.de`,
   Route `app.mvlg-wag.de/*`

Beide Adressen, weil ein Ausfall beide trifft.

**Jetzt einmal prüfen, ob die Seite noch normal läuft.** Öffne
`https://mvlg-wag.de` – es muss alles aussehen wie vorher. Wenn nicht: in
**Domains & Routes** die Routen wieder entfernen, dann ist der Zustand von
vorher zurück.

---

## Schritt 3: Der Speicher für die Meldungen

Ohne diesen Schritt funktioniert die Fehlerseite – nur ohne Meldeknopf. Der
Worker merkt das selbst und blendet den Knopf aus, statt einen anzubieten, der
nichts tut.

1. Links **Storage & Databases** → **KV**.
2. **Create a namespace**, Name: `wag-ausfallmeldungen`. **Add**.
3. Zurück zum Worker → **Settings** → **Bindings** → **Add** →
   **KV namespace**.
4. Variable name: `LAGER` (genau so, groß geschrieben).
   KV namespace: `wag-ausfallmeldungen`. **Deploy**.

---

## Schritt 4: Zwei Geheimnisse setzen

### 4a. Der Abholschlüssel

Damit niemand außer der Plattform die Meldungen auslesen kann.

Denk dir eine lange zufällige Zeichenfolge aus, mindestens 40 Zeichen,
Buchstaben und Zahlen. Zum Beispiel per Tastatur wild drauflos – sie muss
niemand behalten, sie wird nur an zwei Stellen eingetragen.

1. Worker → **Settings** → **Variables and Secrets** → **Add**.
2. Type: **Secret**. Name: `ABHOL_SCHLUESSEL`. Value: deine Zeichenfolge.
3. **Deploy**.

### 4b. Das ntfy-Thema (damit dein Telefon klingelt)

**Nimm dafür ein neues, eigenes Thema – nicht dein persönliches aus dem
Dashboard.** Das persönliche steht im Worker als Geheimnis, und wer ein
ntfy-Thema kennt, kann alles mitlesen, was darüber läuft. Ein eigenes Thema nur
für Ausfälle kostet nichts und hält das getrennt.

1. Denk dir ein Thema aus, das niemand erraten kann, z. B.
   `wag-ausfall-` plus 20 zufällige Zeichen.
2. In der **ntfy**-App auf deinem Telefon dieses Thema abonnieren
   (Server `ntfy.sh`).
3. Worker → **Settings** → **Variables and Secrets** → **Add** →
   Type **Secret**, Name `NTFY_THEMA`, Value: dein Thema. **Deploy**.

Ohne diesen Schritt läuft alles andere weiter – die Meldung wird dann nur
gespeichert und wird zum Ticket, sobald die Plattform wieder läuft. Das Klingeln
ist der schnelle Weg, das Ticket der verlässliche.

**Damit ist auch der Ausfall-Alarm scharf.** Sobald der Worker merkt, dass
nichts antwortet, klingelt dein Telefon – ohne dass jemand einen Knopf drücken
muss. Gemeldet wird der Wechsel, nicht der Zustand: einmal beim Ausfall, einmal
bei der Rückkehr, nicht dazwischen. Sonst wären acht Leute in einer AG-Stunde
acht Nachrichten, und beim dritten Mal schaltet man sie ab.

Zwei Dinge, die dazugehören:

- Der Alarm braucht **beides** – den Zwischenspeicher aus Schritt 3 und dieses
  Thema. Der Selbsttest zeigt in der Zeile „Alarm beim Ausfall", ob er scharf
  ist.
- Er hängt daran, dass **jemand die Seite aufruft**. Fällt die Plattform nachts
  aus und niemand schaut hin, merkt es auch der Worker nicht. Wenn du das
  willst, schalte zusätzlich den Zeitplan ein (siehe unten) – dann sieht
  Cloudflare alle fünf Minuten von selbst nach.

---

## Schritt 5: Die Plattform holt die Meldungen ab

Damit aus einer Meldung ein echtes Support-Ticket wird, trägst du auf dem
Laptop in `config.cmd` zwei Zeilen ein:

```
set "AUSFALL_WORKER_URL=https://mvlg-wag.de"
set "AUSFALL_SCHLUESSEL=hier die Zeichenfolge aus Schritt 4a"
```

Danach die Plattform einmal neu starten. Im Startfenster muss stehen:

```
  Auffangnetz  : Meldungen alle 5 min abholen
```

Steht die Zeile nicht da, fehlt einer der beiden Werte.

Ab jetzt schaut die Plattform beim Start und dann alle fünf Minuten nach, ob
Meldungen warten, legt Tickets an und benachrichtigt den Vorstand.

---

## Schritt 6: Der Selbsttest

Ruf auf:

```
https://mvlg-wag.de/__ausfall/selbsttest
```

Die Seite sagt dir in einer Tabelle, was eingerichtet ist und was fehlt –
Zwischenspeicher, Abholschlüssel, ntfy-Thema, wartende Meldungen. Steht oben
„Alles eingerichtet", stimmt die Kette.

Ist ein ntfy-Thema hinterlegt, gibt es dort auch einen Knopf
**Probemeldung aufs Telefon**. Das ist der schnellste Weg herauszufinden, ob es
bis zu deinem Handy durchkommt – ohne dafür die Plattform abschalten zu müssen.
Höchstens einmal pro Minute, damit die Adresse kein Klingelstreich wird.

Die Seite zeigt nur Ja/Nein-Angaben, keine Geheimnisse und keine
Meldungstexte. Deshalb braucht sie keinen Schlüssel.

---

## Schritt 7: Prüfen, dass es wirklich funktioniert

Der ehrliche Test ist der, bei dem du es kaputt machst.

1. Auf dem Laptop das Fenster der Plattform schließen (**nicht** den Tunnel –
   dann bekommst du 502 statt 1033, beide werden abgefangen, aber so ist es
   schneller wieder da).
2. Vom Telefon `https://mvlg-wag.de` öffnen. Du musst deine eigene Seite sehen:
   „Die Plattform ist gerade nicht erreichbar."
3. Warte 15 Sekunden – unten muss der Zähler herunterlaufen.
4. **Dem CTO melden** antippen, etwas hineinschreiben, abschicken.
   Es muss stehen: „Angekommen."
5. Dein Telefon sollte klingeln (wenn Schritt 4b gemacht ist).
6. Die Plattform auf dem Laptop wieder starten.
7. Die Fehlerseite auf dem Telefon lädt sich innerhalb von etwa einer Minute
   **von selbst** neu und zeigt die echte Seite.
8. Im Dashboard unter **Support** steht ein neues Ticket
   „Ausfallmeldung: … konnte die Plattform nicht erreichen".

Wenn Punkt 8 klappt, ist alles richtig verbunden.

**Und einmal dasselbe mit einer Bewerbung** – das ist der Weg, der wirklich
zählt:

1. Plattform wieder abschalten, `https://mvlg-wag.de` öffnen.
2. Nach unten scrollen. Unter der Fehlermeldung steht die ganze Startseite.
3. Das Bewerbungsformular ausfüllen und abschicken. Es muss stehen:
   „Danke, … Deine Bewerbung liegt sicher."
4. Plattform starten, ein paar Minuten warten.
5. Im Dashboard unter **Bewerbungen** steht sie – mit dem Zeitpunkt, zu dem
   sie wirklich abgeschickt wurde, nicht dem des Neustarts.

Anders als bei den Störungsmeldungen nimmt der Worker eine Bewerbung
**immer** an, auch wenn die Plattform währenddessen zurückkommt. Lieber eine
doppelte als eine verlorene: Eine doppelte sieht man und löscht sie, eine
fehlende sieht niemand.

---

## Optional: auch dann nachsehen, wenn niemand die Seite aufruft

Der Alarm aus Schritt 4b greift, sobald jemand die Seite öffnet – im Alltag
also innerhalb von Minuten. Fällt die Plattform aber Freitagabend aus und bis
Montag schaut niemand hin, merkt es auch der Worker nicht.

Cloudflare kann deshalb zusätzlich alle fünf Minuten selbst nachsehen. Gemeldet
wird derselbe Wechsel über dieselbe Stelle im Code – doppelte Nachrichten gibt
es dadurch nicht.

**Überleg es dir aber gut:** Der Rechner in der Schule läuft nicht rund um die
Uhr. Geht er abends planmäßig aus, klingelt es abends planmäßig – und eine
Meldung, die jeden Abend kommt, liest nach einer Woche niemand mehr. Schalte das
nur ein, wenn der Rechner eigentlich immer laufen soll.

Zum Einschalten: Worker → **Settings** → **Trigger Events** → **Add** →
**Cron Trigger** → `*/5 * * * *`.

---

## Wenn etwas schiefgeht

**„Ich habe den neuen Code eingespielt, aber es sieht aus wie vorher"**
Zwei Dinge trennen: Ist der Code drin, und ist überhaupt etwas anders?

1. Ruf `https://mvlg-wag.de/__ausfall/selbsttest` auf. Oben in der Tabelle
   steht die **Fassung**. Stimmt sie mit der Zeile `const FASSUNG = "…"` ganz
   oben in `worker.js` überein, ist der neue Code live. Lädt die Seite gar
   nicht, ist er es nicht – dann im Worker auf **Deploy** drücken.
2. Der Vorstellungstext über die AG steht **nur auf `mvlg-wag.de`**, nicht auf
   `app.mvlg-wag.de`. Auf dem Dashboard sieht die Fehlerseite absichtlich
   unverändert aus – wer sich dort anmelden wollte, ist in der AG.
3. Auf der Fehlerseite selbst steht die Fassung klein in der Fußzeile. Ein
   Bildschirmfoto genügt also, um sie zu bestimmen.

**Die Seite ist ganz weg / zeigt einen Worker-Fehler**
Worker → **Settings** → **Domains & Routes** → beide Routen entfernen. Damit
ist sofort der Zustand von vorher zurück, ohne dass am Worker etwas geändert
werden muss. Danach in Ruhe suchen.

**Die Fehlerseite kommt, obwohl die Plattform läuft**
Dann antwortet der Tunnel nicht so, wie der Worker es erwartet. Sieh im Worker
unter **Logs** nach, welcher Status zurückkommt. Steht dort 502 oder 1033, ist
es kein Fehler des Workers – dann kommt die Anwendung wirklich nicht durch.

**Der Meldeknopf fehlt auf der Fehlerseite**
Die KV-Anbindung fehlt oder heißt nicht `LAGER`. Schritt 3 nachsehen.

**Meldungen werden nicht zu Tickets**
Zuerst den Selbsttest aufrufen. Steht dort eine Zahl bei „Meldungen, die auf
Abholung warten", sind sie angekommen und es hakt nur beim Abholen: Dann ist
`AUSFALL_SCHLUESSEL` in `config.cmd` nicht **genau** derselbe wie das Secret im
Worker (oft ein Leerzeichen am Ende), oder die Plattform wurde nach dem
Eintragen nicht neu gestartet. Bei falschem Schlüssel steht im Startfenster
`[Ausfallmeldungen] Antwort 403 vom Auffangnetz`.

**Das Telefon klingelt nicht**
Selbsttest aufrufen und dort auf **Probemeldung aufs Telefon** drücken. Kommt
nichts an, stimmen `NTFY_THEMA` im Worker und das abonnierte Thema in der App
nicht zeichengenau überein. Steht in der Tabelle eine Zeile
„Letzter Fehler beim Klingeln", hat ntfy die Nachricht abgelehnt – dort steht,
warum.

**Auf der Fehlerseite stand „Gespeichert" statt „aufs Telefon bekommen"**
Das ist keine Panne, sondern die ehrliche Auskunft: Die Meldung liegt sicher,
aber es war kein ntfy-Thema hinterlegt. Schritt 4b nachholen.

---

## Was das Netz nicht kann

- **Keine gepflegten Inhalte zeigen.** Aktivitäten, Arbeitsproben, die
  Vorteilsliste und das Quiz stehen in der Datenbank, die gerade nicht
  antwortet. Auf der Notfassung fehlen sie. Was dort steht, ist fest
  eingetragen und ändert sich nur, wenn jemand `worker.js` anfasst – wenn ihr
  also den Auftritt umschreibt, gehört diese Datei nachgezogen.
- **Kein Login, kein Dashboard.** Die Notfassung ist die öffentliche Seite.
  Auf `app.mvlg-wag.de` bleibt es bei der schlichten Fehlermeldung – wer sich
  dort anmelden wollte, ist in der AG und braucht keine Vorstellung.
- **Eine laufende Eingabe retten.** Wer gerade ein Formular abgeschickt hat und
  dabei in den Ausfall läuft, verliert das Getippte. Das ließe sich nur auf dem
  Gerät selbst abfangen, nicht am Rand des Netzes. Was auf der Notfassung
  selbst getippt wird, bleibt dagegen stehen – sie lädt sich nicht von allein
  neu.
- **Einen Ausfall von Cloudflare oder der Domain überbrücken.** Zeigt die
  Domain nicht mehr auf Cloudflare, ist auch der Worker nicht erreichbar.

## Was es kostet

Nichts. Der kostenlose Worker-Tarif erlaubt 100.000 Anfragen am Tag; der
KV-Speicher 100.000 Lesevorgänge und 1.000 Schreibvorgänge am Tag. Bei acht
Mitgliedern ist das nicht in Reichweite. Geschrieben wird ohnehin nur, wenn
jemand eine Meldung abschickt.

## Was du an Cloudflare gibst

Jede Anfrage lief auch vorher schon über Cloudflare – daran ändert der Worker
nichts. Neu ist, dass Meldungen von der Fehlerseite dort kurz liegen: Text,
Name und E-Mail, freiwillig eingetippt, höchstens vier Wochen lang. Sie werden
gelöscht, sobald die Plattform ein Ticket daraus gemacht hat.
