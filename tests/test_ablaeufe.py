"""Die üblichen Handgriffe einmal durchspielen: anlegen, ändern, löschen.

Warum so ausführlich: Ein kaputter Knopf fällt sonst erst auf, wenn jemand
ihn im Betrieb drückt - so wie beim Löschen von Aufgaben, das monatelang
still das Bearbeiten-Formular abgeschickt hätte. Jeder Bereich, in dem etwas
entsteht und wieder verschwindet, wird hier einmal komplett bedient.

Geprüft wird nach jedem Schritt zweierlei: dass die Antwort keine
Fehlermeldung enthält (die Oberfläche also nicht meckert) und dass in der
Datenbank tatsächlich steht, was stehen soll.
"""

import re
import unittest
from datetime import date, timedelta

from tests import hilfe                                      # noqa: F401

from kern.datenbank import SessionLocal
from kern.modelle import (
    Budget, Buchung, CalendarEvent, Competition, ContentItem, Inhalt,
    Meeting, Project, SupportTicket, Task, TrashItem, User,
)
from kern.rechte import cache_verwerfen
from tests.hilfe import angemeldeter_client, csrf_aus

MORGEN = (date.today() + timedelta(days=1)).isoformat()


class TestAblaeufe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()
        cls.csrf = csrf_aus(cls.dash.get("/dashboard/aufgaben").text)

    # --- Hilfen ------------------------------------------------------------
    def senden(self, pfad, **daten):
        """POST mit Token - und die Antwort darf nicht meckern."""
        daten.setdefault("csrf", self.csrf)
        antwort = self.dash.post(pfad, data=daten)
        self.assertEqual(antwort.status_code, 200, f"{pfad}: {antwort.status_code}")
        fehler = re.search(r'meldung-fehler[^>]*>\s*<div>(.*?)</div>',
                           antwort.text, re.S)
        self.assertIsNone(fehler, f"{pfad} meldet: "
                                  f"{fehler.group(1).strip()[:120] if fehler else ''}")
        return antwort

    def zaehlen(self, modell, **filter_):
        db = SessionLocal()
        try:
            abfrage = db.query(modell)
            for feld, wert in filter_.items():
                abfrage = abfrage.filter(getattr(modell, feld) == wert)
            return abfrage.count()
        finally:
            db.close()

    def erstes(self, modell, **filter_):
        db = SessionLocal()
        try:
            abfrage = db.query(modell)
            for feld, wert in filter_.items():
                abfrage = abfrage.filter(getattr(modell, feld) == wert)
            eintrag = abfrage.first()
            return eintrag.id if eintrag else None
        finally:
            db.close()

    # --- Kalender ----------------------------------------------------------
    def test_termin(self):
        self.senden("/dashboard/kalender", titel="Probetermin", ort="Raum 1",
                    von=MORGEN, start="15:00", ende="16:30", ziel="alle")
        termin_id = self.erstes(CalendarEvent, title="Probetermin")
        self.assertIsNotNone(termin_id, "Termin wurde nicht angelegt")
        self.senden(f"/dashboard/kalender/{termin_id}/aendern", titel="Probetermin",
                    ort="Raum 2", von=MORGEN, start="15:00", ziel="alle")
        self.senden(f"/dashboard/kalender/{termin_id}/loeschen")
        self.assertIsNone(self.erstes(CalendarEvent, title="Probetermin"))

    # --- Projekte ----------------------------------------------------------
    def test_projekt_mit_team(self):
        self.senden("/dashboard/projekte", titel="Probeprojekt",
                    beschreibung="Nur zum Prüfen", frist=MORGEN)
        projekt_id = self.erstes(Project, title="Probeprojekt")
        self.assertIsNotNone(projekt_id)

        db = SessionLocal()
        person_id = db.query(User).filter(User.status == "aktiv").first().id
        db.close()
        self.senden(f"/dashboard/projekte/{projekt_id}/mitglied",
                    person=str(person_id), rolle="Mitarbeit")
        self.senden(f"/dashboard/projekte/{projekt_id}/aendern",
                    titel="Probeprojekt", status="laufend", fortschritt="50",
                    frist=MORGEN)
        self.senden(f"/dashboard/projekte/{projekt_id}/loeschen")
        self.assertIsNone(self.erstes(Project, title="Probeprojekt"))

    # --- Wettbewerbe -------------------------------------------------------
    def test_wettbewerb(self):
        self.senden("/dashboard/wettbewerbe", titel="Probewettbewerb",
                    wann=MORGEN, ort="Aula")
        comp_id = self.erstes(Competition, title="Probewettbewerb")
        self.assertIsNotNone(comp_id)
        db = SessionLocal()
        person_id = db.query(User).filter(User.status == "aktiv").first().id
        db.close()
        self.senden(f"/dashboard/wettbewerbe/{comp_id}/teilnahme",
                    person=str(person_id), team="Team A", platz="2", punkte="88")
        self.senden(f"/dashboard/wettbewerbe/{comp_id}/loeschen")
        self.assertIsNone(self.erstes(Competition, title="Probewettbewerb"))

    # --- Treffen -----------------------------------------------------------
    def test_treffen(self):
        self.senden("/dashboard/treffen", titel="Probetreffen", wann=MORGEN,
                    protokoll_text="Kurz besprochen.")
        treffen_id = self.erstes(Meeting, title="Probetreffen")
        self.assertIsNotNone(treffen_id)
        self.senden(f"/dashboard/treffen/{treffen_id}/loeschen")
        self.assertIsNone(self.erstes(Meeting, title="Probetreffen"))

    # --- Redaktionsplan ----------------------------------------------------
    def test_redaktion(self):
        self.senden("/dashboard/redaktion", titel="Probebeitrag",
                    abteilung="marketing", kanal="instagram", wann=MORGEN)
        eintrag_id = self.erstes(ContentItem, titel="Probebeitrag")
        self.assertIsNotNone(eintrag_id)
        self.senden(f"/dashboard/redaktion/{eintrag_id}/aendern",
                    titel="Probebeitrag", kanal="instagram", wann=MORGEN,
                    status="geplant")
        self.senden(f"/dashboard/redaktion/{eintrag_id}/loeschen")
        self.assertIsNone(self.erstes(ContentItem, titel="Probebeitrag"))

    # --- Startseite --------------------------------------------------------
    def test_startseiten_block(self):
        self.senden("/dashboard/startseite", bereich="portfolio",
                    titel="Probeeintrag", text="Was wir gemacht haben",
                    zeitraum="Herbst 2026", ergebnis="2. Platz")
        block_id = self.erstes(Inhalt, titel="Probeeintrag")
        self.assertIsNotNone(block_id)
        self.senden(f"/dashboard/startseite/{block_id}/verschieben", richtung="-1")
        self.senden(f"/dashboard/startseite/{block_id}/aendern",
                    titel="Probeeintrag", text="Geändert", zeitraum="Herbst 2026",
                    ergebnis="1. Platz", aktiv="1")
        db = SessionLocal()
        block = db.get(Inhalt, block_id)
        self.assertEqual(block.ergebnis, "1. Platz")
        db.close()
        self.senden(f"/dashboard/startseite/{block_id}/loeschen")
        self.assertIsNone(self.erstes(Inhalt, titel="Probeeintrag"))

    # --- Kassenbuch --------------------------------------------------------
    def test_kassenbuch(self):
        self.senden("/dashboard/kassenbuch", zweck="Probebuchung", betrag="12,50",
                    richtung="ein", kategorie="sonstiges", wann=date.today().isoformat())
        buchung_id = self.erstes(Buchung, zweck="Probebuchung")
        self.assertIsNotNone(buchung_id)
        db = SessionLocal()
        self.assertEqual(db.get(Buchung, buchung_id).betrag_cent, 1250,
                         "Komma-Betrag falsch umgerechnet")
        db.close()

        self.senden("/dashboard/kassenbuch/budget", abteilung="tech",
                    bezeichnung="Probebudget", betrag="100",
                    von=date.today().isoformat(), bis=MORGEN)
        budget_id = self.erstes(Budget, bezeichnung="Probebudget")
        self.assertIsNotNone(budget_id)
        self.senden(f"/dashboard/kassenbuch/budget/{budget_id}/loeschen")

        self.senden(f"/dashboard/kassenbuch/{buchung_id}/stornieren")
        self.assertIsNone(self.erstes(Buchung, zweck="Probebuchung"))

    # --- Support -----------------------------------------------------------
    def test_support(self):
        self.senden("/dashboard/support", betreff="Probeanliegen",
                    text="Etwas klemmt.")
        ticket_id = self.erstes(SupportTicket, subject="Probeanliegen")
        self.assertIsNotNone(ticket_id)
        self.senden(f"/dashboard/support/{ticket_id}/antwort", text="Schon erledigt.")
        self.senden(f"/dashboard/support/{ticket_id}/schliessen")
        self.senden(f"/dashboard/support/{ticket_id}/loeschen")
        self.assertIsNone(self.erstes(SupportTicket, subject="Probeanliegen"))

    # --- Konten ------------------------------------------------------------
    def test_konto_anlegen_aendern_loeschen(self):
        self.senden("/dashboard/konten", vorname="Probe", nachname="Person",
                    email="probe.person@ag.local", rolle="member",
                    abteilung="marketing", passwort="Zufall-Kennwort-2026")
        konto_id = self.erstes(User, email="probe.person@ag.local")
        self.assertIsNotNone(konto_id)
        self.senden(f"/dashboard/konten/{konto_id}/aendern", vorname="Probe",
                    nachname="Person", email="probe.person@ag.local",
                    rolle="member", abteilung="tech", status="aktiv")
        db = SessionLocal()
        self.assertEqual(db.get(User, konto_id).department, "tech")
        db.close()
        # Ein Recht ausdrücklich setzen und wieder freigeben
        self.senden(f"/dashboard/konten/{konto_id}/recht", perm="aufgaben_all",
                    wert="an")
        self.senden(f"/dashboard/konten/{konto_id}/recht", perm="aufgaben_all",
                    wert="")
        self.senden(f"/dashboard/konten/{konto_id}/loeschen")
        self.assertIsNone(self.erstes(User, email="probe.person@ag.local"))

    # --- Rollen und Abteilungen -------------------------------------------
    def test_rolle_und_abteilung(self):
        self.senden("/dashboard/rollen", schluessel="probe_rolle",
                    name="Proberolle", rang="10", beschreibung="Nur zum Prüfen")
        cache_verwerfen()
        self.senden("/dashboard/rollen/probe_rolle/aendern", name="Proberolle",
                    rang="12", beschreibung="Geändert", rechte=["aufgaben_all"])
        self.senden("/dashboard/rollen/probe_rolle/loeschen")

        self.senden("/dashboard/abteilungen", schluessel="probe_abt",
                    name="Probeabteilung", farbe="#123456")
        cache_verwerfen()
        self.senden("/dashboard/abteilungen/probe_abt/loeschen")
        cache_verwerfen()

    # --- Papierkorb --------------------------------------------------------
    def test_papierkorb_wiederherstellen(self):
        self.senden("/dashboard/aufgaben", titel="Zum Wiederholen",
                    zustaendig="a:tech")
        aufgabe_id = self.erstes(Task, titel="Zum Wiederholen")
        self.senden(f"/dashboard/aufgaben/{aufgabe_id}/loeschen")
        eintrag_id = self.erstes(TrashItem, entity_type="task")
        self.assertIsNotNone(eintrag_id, "nichts im Papierkorb")
        self.senden(f"/dashboard/papierkorb/{eintrag_id}/wiederherstellen")
        self.assertIsNotNone(self.erstes(Task, titel="Zum Wiederholen"),
                             "Wiederherstellen hat nichts zurückgebracht")
        # und jetzt endgültig
        neue_id = self.erstes(Task, titel="Zum Wiederholen")
        self.senden(f"/dashboard/aufgaben/{neue_id}/loeschen")
        rest = self.erstes(TrashItem, entity_type="task")
        self.senden(f"/dashboard/papierkorb/{rest}/endgueltig")
        self.assertEqual(self.zaehlen(TrashItem, entity_type="task"), 0)

    # --- Leistung ----------------------------------------------------------
    def test_leistung_neu_rechnen(self):
        self.senden("/dashboard/leistung/neu-rechnen")

    # --- Anwesenheit -------------------------------------------------------
    def test_anwesenheit(self):
        db = SessionLocal()
        person_id = db.query(User).filter(User.status == "aktiv").first().id
        db.close()
        self.senden("/dashboard/anwesenheit", personen=[str(person_id)],
                    art="anwesend", wann=date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
