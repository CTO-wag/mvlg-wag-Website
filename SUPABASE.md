# Datenbank zu Supabase umziehen

Danach liegt der Datenbestand nicht mehr als Datei auf dem Laptop, sondern
bei Supabase. Die Anwendung läuft weiter dort, wo sie jetzt läuft.

Dauer: etwa 30 Minuten. Du brauchst einen Browser und ein Terminal.

**Wichtig vorweg:** Die SQLite-Datei wird beim Umzug nur *gelesen*. Sie bleibt
unverändert liegen. Wenn etwas schiefgeht, trägst du `DATABASE_URL` wieder aus
und alles läuft wie vorher. Es gibt keinen Punkt, ab dem du nicht mehr zurück
kannst.

---

## Schritt 1: Projekt anlegen

1. Auf `supabase.com` anmelden (GitHub-Konto reicht).
2. **New project**.
3. Name: `wag-plattform`
4. **Database Password**: Supabase schlägt eines vor. **Kopier es sofort in
   deinen Passwortspeicher** – es wird dir nur einmal gezeigt.
5. Region: **Central EU (Frankfurt)**. Nimm wirklich Frankfurt; jede andere
   Region kostet dich bei jeder Abfrage zusätzliche Millisekunden.
6. **Create new project**. Das dauert ein bis zwei Minuten.

---

## Schritt 2: Die Verbindungsadresse holen

1. Im Projekt oben auf **Connect**.
2. Reiter **Connection string**, darunter **Transaction pooler** wählen.

   Nicht die direkte Verbindung. Der Pooler bündelt Verbindungen; die direkte
   ist auf wenige gleichzeitige begrenzt, und die Anwendung öffnet mehr.

3. Du bekommst etwas in dieser Form:

   ```
   postgresql://postgres.abcdefghijkl:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:6543/postgres
   ```

4. Daran musst du **zwei Dinge ändern**:

   - `[YOUR-PASSWORD]` durch dein Passwort aus Schritt 1 ersetzen
   - `postgresql://` zu `postgresql+psycopg2://` machen

   Enthält dein Passwort Sonderzeichen, müssen die kodiert werden:
   `@` wird zu `%40`, `#` zu `%23`, `/` zu `%2F`. In einer `.cmd`-Datei
   musst du außerdem jedes `%` verdoppeln: aus `%40` wird `%%40`.
   Am einfachsten ist ein Passwort nur aus Buchstaben und Ziffern – das
   kannst du in Supabase unter *Settings → Database → Reset password*
   jederzeit neu setzen.

   Fertig sieht es so aus:

   ```
   postgresql+psycopg2://postgres.abcdefghijkl:MeinPasswort123@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require
   ```

---

## Schritt 3: In config.cmd eintragen

Öffne `config.cmd`. Dort steht schon ein auskommentiertes Beispiel. Trag
darunter deine Adresse ein:

```
set "DATABASE_URL=postgresql+psycopg2://postgres.abcdefghijkl:MeinPasswort123@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require"
```

**Speichern, aber die Plattform noch nicht starten.**

---

## Schritt 4: Treiber installieren

```
python -m pip install -r requirements.txt
```

---

## Schritt 5: Verbindung prüfen

Ein Terminal im Projektordner öffnen und die Konfiguration laden:

```
call config.cmd
python werkzeuge/nach_supabase.py --pruefen
```

Das ändert **nichts**. Es verbindet sich und zählt beide Seiten:

```
Vorhanden in der SQLite-Datei: 46 Tabellen, 181 Zeilen
Vorhanden bei Supabase: 0 Tabellen, 0 Zeilen
```

Kommt stattdessen ein Fehler, steht darunter, woran es meistens liegt.

---

## Schritt 6: Umziehen

```
python werkzeuge/nach_supabase.py --umziehen
```

Das Werkzeug legt alle Tabellen an, kopiert jede Zeile und zählt danach
gegen. Stimmen die Zahlen nicht überein, sagt es das deutlich.

Zum Schluss setzt es die Zähler der laufenden Nummern nach. Ohne diesen
Schritt vergäbe Postgres beim nächsten neuen Eintrag die 1 – die es längst
gibt, und der erste Klick nach dem Umzug endete mit einem Fehler an einer
völlig unverdächtigen Stelle.

---

## Schritt 6b: Nachrechnen

```
python werkzeuge/nach_supabase.py --vergleichen
```

Das stellt beide Seiten Zeile für Zeile und Spalte für Spalte
gegenüber. Erwartete Ausgabe:

```
Beide Seiten sind gleich - jede Tabelle, jede Zeile, jede Spalte.
```

Diesen Schritt gibt es, weil gleiche Zeilenzahlen nicht genügen. Beim
ersten echten Umzug stimmten sie überall – und trotzdem hatte im
Dashboard jede Rolle null Rechte. Die 28 Rechtespalten stehen nicht in
`kern/modelle.py`, sondern werden von `kern/rechte.py` beim Import
angehängt. Das Umzugswerkzeug importierte nur `modelle`, sah eine
roles-Tabelle mit 6 Spalten und ließ die Rechte liegen. Im Ziel legte
die Migration sie dann mit Standardwert 0 neu an – vollständige
Zeilenzahlen, leere Rechte.

Behoben ist beides: Das Werkzeug importiert `rechte`, und kopiert wird
inzwischen über das, was wirklich in der Datenbank steht, statt über die
Modelle.

---

## Schritt 7: Starten und nachsehen

`start.bat` wie immer. Im Fenster muss stehen:

```
Datenbank    : Supabase (aws-0-eu-central-1.pooler.supabase.com:6543)
```

Dann anmelden und prüfen: Sind alle Mitglieder da? Die Aufgaben? Die
Bewerbungen? Der Kalender?

Wenn ja, bist du fertig.

---

## Sicherheit: Row Level Security

Neben der Datenbank stellt Supabase eine **offene REST-Schnittstelle**
bereit. Die Rolle `anon` darf dort standardmäßig jede Tabelle im Schema
`public` lesen und schreiben. Zurück hält sie allein Row Level Security.

Ohne RLS kommt jeder, der den anon-Schlüssel hat, an:

| Tabelle | was drinsteht |
|---|---|
| `users` | alle Konten samt Passwort-Hashes |
| `user_sessions` | offene Sitzungen – die Kennung **ist** der Anmeldeschlüssel |
| `password_reset_tokens` | jedes Konto übernehmbar |
| `applications` | Namen, E-Mails, Telefonnummern von Schülern |

Der anon-Schlüssel ist dafür gemacht, veröffentlicht zu werden – er
steckt normalerweise in Webseiten. Diese Plattform benutzt ihn nicht,
sie verbindet sich direkt mit Postgres. Der Schlüssel existiert aber,
und die Projektkennung steht in jeder Verbindungsadresse.

**Eingeschaltet wird RLS ohne jede Richtlinie.** Das sperrt `anon` und
`authenticated` vollständig aus. Die Anwendung merkt nichts davon: Sie
verbindet sich als `postgres`, und diese Rolle besitzt die Tabellen und
darf RLS umgehen. Deshalb **kein** `FORCE ROW LEVEL SECURITY` – damit
wäre auch der Eigentümer gebunden und die Anwendung sähe keine Zeile
mehr.

Das passiert von selbst: beim Umzug (`kopiere`) und bei jedem Start der
Anwendung (`kern/migration.py`). Eine neu angelegte Tabelle steht also
nie offen. Nachsehen kann man jederzeit:

```
python werkzeuge/nach_supabase.py --sicherheit
```

Zusätzlich empfehlenswert im Supabase-Dashboard unter
*Settings → API → Exposed schemas*: `public` entfernen. Dann gibt es die
REST-Schnittstelle gar nicht erst. Nötig ist es nach dem Einschalten von
RLS nicht mehr.

---

## Ab jetzt laufen beide Seiten auseinander

Die SQLite-Datei ist ab dem Umzug ein eingefrorener Stand. Alles, was
danach passiert, steht nur bei Supabase. `--vergleichen` meldet deshalb
mit der Zeit immer mehr Unterschiede – das ist richtig so und kein
Fehler. Aussagekräftig ist der Vergleich nur direkt nach einem Umzug.

---

## Wenn du zurück willst

`DATABASE_URL` in `config.cmd` wieder auskommentieren (`REM` davor) und neu
starten. Die SQLite-Datei ist unangetastet – du bist auf dem Stand von vor
dem Umzug.

Beachte: Was du **nach** dem Umzug eingetragen hast, steht dann nur bei
Supabase. Willst du das mitnehmen, hol es dir vorher als Sicherung
(Dashboard → System → Sicherungen → Herunterladen) und spiel sie nach dem
Zurückstellen ein.

---

## Was sich ändert

**Es wird langsamer, aber weniger als gedacht.** Gemessen nach dem
Umzug, gegen Frankfurt:

| | vorher (Datei) | jetzt (Supabase) |
|---|---|---|
| eine Abfrage | unter 0,1 ms | 10 ms |
| Übersichtsseite (29 Abfragen) | 15 ms | rund 300 ms |
| Startseite, Bewerbung | 2–6 ms | 2–6 ms |

Öffentliche Seiten bleiben schnell, weil sie vorgerendert sind und die
Datenbank gar nicht anfassen. Spürbar langsamer wird das Dashboard.

Wichtig ist die Region: Steht das Projekt nicht in Frankfurt, sondern
etwa in Nordamerika, werden aus 10 ms schnell 120 – und aus der
Übersichtsseite dreieinhalb Sekunden.

**Der Speicherplatz reicht bei weitem.** Supabase gibt kostenlos 500 MB
für die Datenbank. Belegt sind nach dem Umzug 13 MB – und davon ist das
meiste Postgres' eigene Verwaltung; die AG-Daten sind knapp 1 MB. Die
größte Tabelle hat 112 kB.

Nach Supabase geht **nur die Datenbank**. Alles andere im Datenordner
bleibt auf der Festplatte und zählt nicht mit:

| | Größe | wohin |
|---|---|---|
| `ag_plattform.db` | 0,6 MB | Supabase |
| `whatsapp-sitzung/` | 575 MB | bleibt lokal |
| `backups/` | 2,9 MB | bleibt lokal |
| `*_uploads/` | wächst | bleibt lokal |

Die `whatsapp-sitzung` ist kein Datenbestand, sondern ein Chrome-Profil
mit dem angemeldeten WhatsApp-Zustand. Ohne den Ordner müsstest du den
QR-Code neu scannen. Supabase kann damit nichts anfangen.

**Sicherungen sehen anders aus.** Es gibt keine Datei mehr zum Kopieren.
Die Anwendung schreibt stattdessen alle Tabellen in eine SQLite-Datei –
dieselbe Stelle im Dashboard, dieselben Knöpfe, herunterladen und
einspielen funktionieren wie vorher. Zusätzlich sichert Supabase selbst
täglich.

**Das Projekt schläft ein.** Supabase pausiert kostenlose Projekte nach
einer Woche ohne Zugriff. Ist der Laptop in den Ferien aus, musst du das
Projekt im Supabase-Dashboard von Hand wieder aufwecken. Solange die
Plattform läuft, passiert das nicht – sie greift alle paar Minuten zu.

---

## Wenn etwas nicht geht

**„Connection refused" oder „could not translate host name"**
Adresse falsch abgeschrieben. Achte auf `:6543` am Ende und darauf, dass
`postgresql+psycopg2://` davorsteht.

**„password authentication failed"**
Passwort falsch oder Sonderzeichen nicht kodiert. Setz das Passwort in
Supabase neu und nimm eines nur aus Buchstaben und Ziffern.

**„No module named 'psycopg2'"**
Schritt 4 vergessen.

**Beim Start: „relation ... does not exist"**
Der Umzug lief nicht durch. Nochmal `--pruefen`, dann `--umziehen`.

**Alles ist da, aber neue Einträge scheitern mit „duplicate key"**
Die Zähler wurden nicht nachgezogen. `--umziehen` noch einmal laufen lassen,
das macht es am Ende von selbst.

**„value too long for type character varying(...)"**
SQLite behandelt `VARCHAR(200)` nur als Notiz und speichert auch längere
Werte. Postgres weist sie ab. `--pruefen` findet das inzwischen vorher
und nennt Tabelle, Spalte und Länge – dann muss die Spalte in
`kern/modelle.py` auf `Text` umgestellt werden. Abschneiden wäre
Datenverlust.

Steht die Tabelle bei Supabase schon mit der alten Breite da, macht die
Migration das beim nächsten Start selbst (`_spalten_verbreitern`).

**Das Projekt ist pausiert**
Im Supabase-Dashboard auf **Restore project**. Dauert ein paar Minuten.
