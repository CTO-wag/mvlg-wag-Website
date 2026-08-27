# Testbestand

Diese Datenbank ist zum Ausprobieren da. Sie enthält **keine echten Daten** –
alles ist erfunden, Namen wie Zahlen. Dafür steckt einiges drin, damit kein
Bereich im Dashboard leer aussieht:

* 14 Konten in allen vier Abteilungen und mehreren Rollen (eins inaktiv)
* 7 Bewerbungen in jedem Bearbeitungsstand
* 10 Aufgaben, offen/in Arbeit/erledigt, an Personen wie an Abteilungen
* 4 Treffen (zwei vergangene mit Protokoll und Anwesenheit, zwei kommende
  mit Zu-/Absagen und Tagesordnung)
* 3 Kalendertermine, 2 Wettbewerbe mit Platzierungen, 2 Projekte mit Team
* 5 Einträge im Redaktionsplan, 10 Kassenbuchungen samt Budget und
  Dauerauftrag
* 3 Kontaktanfragen (beantwortet, offen, fehlgeschlagen zugestellt),
  2 Rundnachrichten, 2 Support-Tickets

Erzeugt von `werkzeuge/testdaten.py` – dort steht auch, was wo herkommt.

## Anmelden

| Adresse                | Passwort          | Was es kann              |
|------------------------|-------------------|--------------------------|
| `test@beispiel.de`     | `TestZugang2026!` | **alle Rechte**          |
| `mitglied@beispiel.de` | `TestZugang2026!` | ein einfaches Mitglied   |

Das zweite Konto ist wichtiger, als es aussieht: Aufgaben zuteilen,
Anwesenheit und Leistungswerte lassen sich nur ausprobieren, wenn es jemanden
gibt, der nicht man selbst ist. Und wer wissen will, was ein normales Mitglied
tatsächlich sieht, meldet sich damit an – von oben sieht das Dashboard ganz
anders aus.

## Starten

```
start-entwicklung.bat
```

Website auf <http://localhost:8010>, Dashboard auf <http://localhost:8011>.
Der Starter läuft mit und ohne `config.cmd`; ohne sie nimmt er die Werte, die
zu diesem Bestand gehören.

## Neu aufsetzen

Kaputt geklickt? Kein Problem, das ist der Sinn der Sache:

```
python werkzeuge/testdaten.py --neu
```

Das wirft die Datei weg und baut sie neu. Ohne `--neu` wird nur ergänzt, was
fehlt – bestehende Einträge bleiben stehen. Vorher die Fenster von
`start-entwicklung.bat` schließen: Solange ein Server läuft, hält er die Datei
offen.

## Sie ändert sich beim Benutzen

Jede Anmeldung schreibt eine Sitzung und einen Protokolleintrag – nach einer
Runde Ausprobieren steht die Datei also in `git status`. Das ist normal.
Änderungen, die niemanden interessieren, wirft man so weg:

```bash
git checkout -- daten-entwicklung/ag_plattform.db
```

## Warum das hier im Repository liegt

Der Rest von `daten-entwicklung/` ist in `.gitignore` gesperrt, und der ganze
`daten/`-Ordner sowieso: Dort stehen personenbezogene Daten von
Minderjährigen. Freigegeben ist nur diese eine Datei und diese Anleitung.

**Bevor du eine echte Sicherung hier einspielst**, um etwas nachzustellen:
Danach steht der Livebestand in `ag_plattform.db` – und die ist freigegeben.
Dann entweder in einem anderen Ordner arbeiten oder hinterher
`python werkzeuge/testdaten.py --neu` laufen lassen, bevor du committest.
