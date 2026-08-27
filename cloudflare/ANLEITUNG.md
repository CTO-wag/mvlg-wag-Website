# Auffangnetz einrichten

Was du danach hast: Ist die Plattform nicht erreichbar, bekommt ein Besucher
trotzdem die Startseite. Nicht die englische Cloudflare-Seite, und auch keine
Fehlermeldung – **dieselbe Seite wie immer**: dasselbe Stylesheet, dieselben
Schriften, derselbe Aufbau. Bewerbung und Kontaktformular funktionieren
weiter; der Worker nimmt beides selbst entgegen.

Der Ausfall steht an genau einer Stelle: **Wer auf „Login" tippt, erfährt es.**
Dann geht ein Hinweis auf – das System ist gerade nicht erreichbar, wir sehen
nach, und hier kannst du es dem CTO melden.

Das ist Absicht. Wer zum ersten Mal auf mvlg-wag.de kommt, weil ihm jemand von
der AG erzählt hat, soll lesen, worum es geht, und sich bewerben können. Für
ihn ist ein Ausfall unserer Verwaltung belanglos – eine Störungsmeldung als
erste Zeile dagegen kostet ihn. Wer sich anmelden will, gehört dagegen zur AG,
und für ihn ist „das System ist gerade aus" die richtige, vollständige
Antwort.

Was fehlt, fehlt mit Absicht: das Quiz und alles, was sonst live aus der
Datenbank käme. Die Datenbank ist ja gerade der Teil, der nicht antwortet. Die
vier im Dashboard pflegbaren Blöcke (Vorteile, Stufen, Aktivitäten,
Portfolio) sind eingebacken – sie stammen von dem Tag, an dem die Notfassung
zuletzt gebaut wurde.

Was während eines Ausfalls hereinkommt – Bewerbung, Kontaktanfrage,
Störungsmeldung – wird bei Cloudflare hinterlegt und automatisch eingetragen,
sobald die Plattform wieder läuft. Mit dem richtigen Zeitpunkt, samt
Bestätigungsmail und Benachrichtigung an die Zuständigen. Hinterher sieht es
aus wie ganz normal hereingekommen.

Dauer: etwa 20 Minuten.

---

## Schritt 0: Die Notfassung bauen

Der Worker steht am Rand des Netzes und kann sich **nichts** nachladen – der
Server, von dem Stylesheet, Schriften und Wappen kämen, ist genau der
ausgefallene. Alles muss mit in die Worker-Datei. Das erledigt ein Skript:

```
python werkzeuge/auffangnetz_bauen.py
```

Es liest `statisch/stil/basis.css`, `statisch/stil/website.css`, die
Schriftschnitte und die Bilder ein und schreibt sie nach
`cloudflare/eingebettet.js`. Steht eine Datenbank zur Verfügung, holt es
zusätzlich die vier pflegbaren Startseiten-Blöcke; sonst bleibt der bisherige
Stand stehen.

**Wann ausführen:** immer, wenn sich das Aussehen der Website ändert oder wenn
im Dashboard Startseiten-Blöcke gepflegt wurden. Sonst sieht die Notfassung
aus wie die Seite von vorletztem Jahr – und zwar ausgerechnet dann, wenn man
es am wenigsten gebrauchen kann.

`cloudflare/eingebettet.js` gehört mit ins Repository und mit ins Deployment.
Von Hand ändern lohnt nicht: Der nächste Lauf überschreibt es.

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

**Achtung:** `worker.js` allein reicht seit dem Umbau nicht mehr – die Datei
holt sich Stylesheet, Schriften und Bilder aus `cloudflare/eingebettet.js`.
Über den Editor im Browser lassen sich zwei Dateien nicht gut einspielen.
Nimm dafür wrangler, das packt beides zusammen:

```
cd cloudflare
npx wrangler deploy
```

Vorher einmal `python werkzeuge/auffangnetz_bauen.py` laufen lassen (Schritt
0). Wer doch über den Browser-Editor geht, muss dort beide Dateien anlegen –
`worker.js` und `eingebettet.js` – und `eingebettet.js` ist etwa ein halbes
Megabyte lang.

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
2. Vom Telefon `https://mvlg-wag.de` öffnen. Du musst die **ganz normale
   Startseite** sehen. Genau das ist der Test: Sieht sie anders aus als sonst
   – andere Schrift, kein Wappen, verrutschte Kästen –, dann fehlt
   `eingebettet.js` oder ist veraltet (Schritt 0).
3. Oben rechts auf **Login** tippen. Erst jetzt darf stehen: „Das System ist
   gerade nicht erreichbar."
4. Warte 15 Sekunden – der Zähler im Hinweis muss herunterlaufen.
5. **Dem CTO melden** aufklappen, etwas hineinschreiben, abschicken.
   Es muss stehen: „Angekommen."
6. Dein Telefon sollte klingeln (wenn Schritt 4b gemacht ist).
7. Die Plattform auf dem Laptop wieder starten. Im offenen Hinweis erscheint
   innerhalb einer Minute **Jetzt anmelden**.
8. Im Dashboard unter **Support** steht ein neues Ticket
   „Ausfallmeldung: … konnte die Plattform nicht erreichen".

Wenn Punkt 2, 3 und 8 klappen, ist alles richtig verbunden.

**Und einmal dasselbe mit einer Bewerbung** – das ist der Weg, der wirklich
zählt:

1. Plattform wieder abschalten, `https://mvlg-wag.de/bewerbung` öffnen.
2. Das Bewerbungsformular ausfüllen und abschicken. Es muss stehen:
   „Danke, … Deine Bewerbung liegt bei uns."
3. Plattform starten, ein paar Minuten warten.
4. Im Dashboard unter **Bewerbungen** steht sie – mit dem Zeitpunkt, zu dem
   sie wirklich abgeschickt wurde, nicht dem des Neustarts.

**Und mit einer Frage über das Kontaktformular:**

1. Plattform abschalten, `https://mvlg-wag.de` öffnen, ganz nach unten zu
   „Fragen? Schreib einfach." scrollen und etwas abschicken.
2. Plattform starten, ein paar Minuten warten.
3. Im Dashboard unter **Nachrichten** steht sie bei „Anfragen über die
   Website" – und lässt sich von dort per E-Mail beantworten.

Anders als bei den Störungsmeldungen nimmt der Worker Bewerbungen und
Anfragen **immer** an, auch wenn die Plattform währenddessen zurückkommt.
Lieber eine doppelte als eine verlorene: Eine doppelte sieht man und löscht
sie, eine fehlende sieht niemand.

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

- **Aktuelle Inhalte zeigen.** Aktivitäten, Portfolio, Vorteilsliste und
  Stufen sind der Stand vom letzten `python werkzeuge/auffangnetz_bauen.py`.
  Wer im Dashboard etwas ändert, sieht es auf der Notfassung erst nach dem
  nächsten Bauen. Das Quiz fehlt ganz – es braucht den Server.
- **Anmelden.** Dafür braucht es die Datenbank. Genau das steht im Hinweis,
  der beim Klick auf „Login" aufgeht; auf `app.mvlg-wag.de` und auf
  `/dashboard/…` steht er gleich offen, denn wer dorthin wollte, wollte sich
  anmelden.
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
