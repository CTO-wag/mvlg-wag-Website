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

## Schritt 7: Starten und nachsehen

`start.bat` wie immer. Im Fenster muss stehen:

```
Datenbank    : postgresql (Supabase)
```

Dann anmelden und prüfen: Sind alle Mitglieder da? Die Aufgaben? Die
Bewerbungen? Der Kalender?

Wenn ja, bist du fertig.

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

**Es wird langsamer.** Die Übersichtsseite macht 29 Abfragen. Als Datei
kostete jede Mikrosekunden, jetzt kostet jede einen Weg durchs Netz. Rechne
mit einer halben bis einer Sekunde pro Seite statt der bisherigen 15
Millisekunden. Du hast gesagt, das ist dir egal – nur damit du weißt, woran
es liegt, wenn es sich zäh anfühlt.

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

**Das Projekt ist pausiert**
Im Supabase-Dashboard auf **Restore project**. Dauert ein paar Minuten.
