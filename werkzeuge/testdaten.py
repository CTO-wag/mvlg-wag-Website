"""Legt die Entwicklungsdatenbank in daten-entwicklung/ an.

    python werkzeuge/testdaten.py          # anlegen oder ergaenzen
    python werkzeuge/testdaten.py --neu    # vorher wegwerfen und frisch bauen

Wofuer das da ist
-----------------
Wer das Projekt frisch auscheckt, hat eine leere Datenbank und kein Konto -
und kommt damit nicht einmal bis zur Anmeldung. Dieses Skript baut einen
Bestand, mit dem sich alles ausprobieren laesst, ohne dass jemand Zugang zu
den echten Daten braucht.

Die erzeugte Datei ist AUSDRUECKLICH zum Weitergeben gedacht und liegt im
Repository (siehe .gitignore). Deshalb gilt hier eine Regel ohne Ausnahme:

    Es kommt nichts hinein, was einen echten Menschen betrifft.

Alle Namen sind erfunden, alle Adressen liegen unter beispiel.de, und das
Passwort steht offen im Quelltext. Genau so ist es gemeint: Es schuetzt
nichts, weil es nichts zu schuetzen gibt.

Das Konto mit allen Rechten
---------------------------
Rechte kommen aus drei Quellen (kern/rechte.py): der Rolle, den Abteilungen,
fuer die jemand zustaendig ist, und persoenlichen Ausnahmen. Die Ausnahmen
zaehlen zuletzt und koennen auch entziehen - deshalb werden hier ALLE
Rechte ausdruecklich als persoenliche Ausnahme gesetzt und nicht etwa der
CTO-Rolle angehaengt. Zwei Gruende:

  * Es wirkt sicher. Was in der Rolle steht, laesst sich anderswo wieder
    ueberschreiben; eine persoenliche Freigabe nicht.
  * Es bleibt sichtbar. Im Dashboard steht unter „Rechte einzelner Personen"
    schwarz auf weiss, warum dieses Konto alles darf - statt dass jemand
    raetselt, wieso die CTO-Rolle hier mehr kann als im Betrieb.

Die drei Abteilungsfunktionen (Redaktionsplan, Ideensammlung, Bewerbungen
sichten) haengen an der Abteilung und nicht an der Person. Sie werden
deshalb bei der Exekutive eingeschaltet - der Abteilung des Testkontos.
"""

import argparse
import os
import shutil
import sys
from datetime import date, timedelta

HIER = os.path.dirname(os.path.abspath(__file__))
PROGRAMM = os.path.dirname(HIER)
sys.path.insert(0, PROGRAMM)

# Muss VOR jedem Import aus kern/ stehen: kern/einstellungen.py liest die
# Umgebung beim Import. Und es muss die Entwicklungsdatenbank sein - ein
# Testbestand, der versehentlich in der Produktion landet, waere der teuerste
# Fehler, den dieses Skript machen koennte.
os.environ["KONFIG_GELESEN"] = "1"
os.environ["DATEN_DIR"] = os.path.join(PROGRAMM, "daten-entwicklung")
os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("SECRET_KEY", "entwicklung-nicht-fuer-produktivbetrieb")
os.environ.setdefault("APP_ENV", "development")

DATEN_DIR = os.environ["DATEN_DIR"]

# Offen im Quelltext, und das ist der Punkt: Der Bestand ist erfunden, das
# Passwort schuetzt nichts. Lang genug fuer die Regel der Anwendung
# (mindestens zwoelf Zeichen), damit es sich im Dashboard auch aendern laesst.
PASSWORT = "TestZugang2026!"

VOLLZUGRIFF = "test@beispiel.de"

# Ein zweites, ganz normales Konto. Ohne das laesst sich die Haelfte nicht
# ausprobieren: Aufgaben zuteilen, Anwesenheit, Leistungswerte - alles
# braucht jemanden, der NICHT man selbst ist.
MITGLIED = "mitglied@beispiel.de"


def _leeren():
    """Die Entwicklungsdatenbank wegwerfen. Nur diese, nie eine andere."""
    if not os.path.isdir(DATEN_DIR):
        return
    for name in os.listdir(DATEN_DIR):
        if not name.startswith("ag_plattform.db"):
            continue
        try:
            os.remove(os.path.join(DATEN_DIR, name))
        except PermissionError:
            raise SystemExit(
                f"\n  Die Datei {name} ist noch offen.\n"
                "  Es läuft vermutlich noch ein Server darauf - bitte die\n"
                "  Fenster von start-entwicklung.bat schließen und noch\n"
                "  einmal versuchen.\n")
    for unterordner in ("backups", "redaktion_uploads", "support_uploads"):
        pfad = os.path.join(DATEN_DIR, unterordner)
        if os.path.isdir(pfad):
            shutil.rmtree(pfad, ignore_errors=True)
    print("  Alter Bestand entfernt.")


def _konto(db, email, vorname, nachname, rolle, abteilung):
    from kern.modelle import User
    from kern.sicherheit import passwort_hashen
    from kern.text import utcnow

    person = db.query(User).filter(User.email == email).first()
    if person:
        return person
    person = User(vorname=vorname, nachname=nachname, email=email,
                  password_hash=passwort_hashen(PASSWORT), role=rolle,
                  department=abteilung, status="aktiv", created_at=utcnow())
    db.add(person)
    db.flush()
    return person


def _alle_rechte(db, person):
    """Jedes einzelne Recht ausdruecklich freigeben."""
    from kern.modelle import UserPermission
    from kern.rechte import PERM_KEYS

    vorhanden = {z.perm: z for z in db.query(UserPermission).filter(
        UserPermission.user_id == person.id).all()}
    neu = 0
    for perm in PERM_KEYS:
        if perm in vorhanden:
            vorhanden[perm].wert = 1
            continue
        db.add(UserPermission(user_id=person.id, perm=perm, wert=1))
        neu += 1
    return len(PERM_KEYS), neu


def _abteilungsfunktionen(db):
    """Redaktionsplan, Ideensammlung und Bewerbungen sichten fuer die
    Exekutive. Sie haengen an der Abteilung, nicht an der Person - ohne das
    fehlen dem Testkonto genau diese drei Bereiche."""
    from kern.modelle import Department
    from kern.rechte import DEPT_FEATURE_KEYS

    exe = db.query(Department).filter(Department.key == "exekutive").first()
    if not exe:
        return ()
    for feature in DEPT_FEATURE_KEYS:
        setattr(exe, feature, 1)
    return DEPT_FEATURE_KEYS


def _mitglieder(db):
    """Ein kleiner, aber bunter Bestand an Konten.

    "Bunt" heisst hier: alle vier Abteilungen, mehrere Rollen, ein inaktives
    Konto (jeder AG-Bestand hat irgendwann eins), unterschiedliche
    Eintrittsdaten. Wer nur ein einzelnes Testkonto vor sich hat, findet
    Listen, Filter und Verteiler-Formulare langweilig und ungeprueft - mit
    zwoelf Personen sieht man zum ersten Mal, ob eine Sortierung stimmt.

    Namen und Adressen sind erfunden (beispiel.de) - siehe Modulkopf.
    """
    from kern.text import utcnow

    heute = date.today()
    entwurf = (
        # (Vorname, Nachname, Rolle, Abteilung, Status, Tage seit Eintritt)
        ("Jonas", "Weber", "coo", "exekutive", "aktiv", 720),
        ("Sophie", "Klein", "cmo", "marketing", "aktiv", 640),
        ("Ben", "Fischer", "cro", "recruitment", "aktiv", 560),
        ("Lea", "Hoffmann", "member", "tech", "aktiv", 300),
        ("Noah", "Wagner", "member", "tech", "aktiv", 260),
        ("Emilia", "Becker", "member", "marketing", "aktiv", 200),
        ("Finn", "Schulz", "member", "marketing", "aktiv", 180),
        ("Mila", "Hartmann", "member", "recruitment", "aktiv", 150),
        ("Elias", "Krüger", "member", "recruitment", "aktiv", 120),
        ("Anna", "Lorenz", "member", "exekutive", "aktiv", 90),
        ("Paul", "Schuster", "member", "tech", "aktiv", 40),
        # Wer die AG verlassen hat, verschwindet nicht aus der Datenbank -
        # er wird auf inaktiv gesetzt. Ohne ein solches Konto liesse sich der
        # Unterschied zwischen "inaktiv" und "geloescht" nie sehen.
        ("Tom", "Neumann", "member", "tech", "inaktiv", 500),
    )
    personen = []
    for i, (vorname, nachname, rolle, abteilung, status, tage) in enumerate(entwurf):
        adresse = f"{vorname.lower()}.{nachname.lower()}@beispiel.de"
        person = _konto(db, adresse, vorname, nachname, rolle, abteilung)
        person.status = status
        person.eintrittsdatum = heute - timedelta(days=tage)
        personen.append(person)
    db.flush()
    return personen


def _bewerbungen(db):
    """Bewerbungen in jedem Stand, den die Liste kennt - sonst probiert
    niemand die Filter aus, weil unter jedem außer "neu" nichts steht."""
    from kern.modelle import Application
    from kern.text import utcnow

    if db.query(Application).count() > 0:
        return
    heute = date.today()
    entwurf = (
        ("Ela", "Vogel", "10", "tech", "neu", 2),
        ("Timo", "Brandt", "11", "marketing", "neu", 0),
        ("Nora", "Keller", "9", "recruitment", "in_pruefung", 5),
        ("Jakob", "Winter", "12", "tech", "in_pruefung", 6),
        ("Ida", "Lang", "10", "marketing", "angenommen", 30),
        ("Levi", "Frank", "11", "recruitment", "abgelehnt", 45),
        ("Frieda", "Busch", "9", "tech", "neu", 1),
    )
    for i, (vorname, nachname, klasse, abteilung, status, tage_alt) in enumerate(entwurf):
        wann = utcnow() - timedelta(days=tage_alt)
        db.add(Application(
            vorname=vorname, nachname=nachname, klasse=klasse,
            email=f"{vorname.lower()}.{nachname.lower()}@beispiel.de",
            telefonnummer="0151 2345678", department=abteilung,
            status=status, email_sent=1,
            motivation=("Ich interessiere mich sehr für Wirtschaft und "
                       "würde gerne bei euch mitmachen."),
            interessen="Börse, Unternehmertum, " + abteilung,
            vorwissen="Keines" if i % 2 else None,
            created_at=wann))


def _aufgaben(db, personen):
    """Aufgaben in jedem Status, jeder Prioritaet, an Personen UND an
    Abteilungen - beides kommt in der echten Nutzung vor und sieht in der
    Liste unterschiedlich aus."""
    from kern.modelle import Task
    from kern import leistung
    from kern.text import utcnow

    if db.query(Task).count() > 0:
        return []
    chef = personen["chef"]
    heute = date.today()
    entwurf = (
        ("Website-Text überarbeiten",
         "Die Startseite liest sich noch wie letztes Jahr.",
         personen["mitglied"], None, "marketing", "offen", "mittel",
         heute + timedelta(days=7)),
        ("Planspiel Börse anmelden",
         "Frist beachten, Anmeldung läuft über die Schule.",
         None, "exekutive", "exekutive", "in_bearbeitung", "hoch",
         heute + timedelta(days=2)),
        ("Protokoll vom letzten Treffen tippen", None,
         chef, None, "exekutive", "erledigt", "niedrig", None),
        ("Instagram-Post zum Bewerbungsstart entwerfen",
         "Vorlage liegt im Redaktionsplan.",
         personen["emilia"], None, "marketing", "in_bearbeitung", "mittel",
         heute + timedelta(days=3)),
        ("Kandidatinnen für Recruiting-Stand ansprechen", None,
         personen["ben"], None, "recruitment", "offen", "mittel",
         heute + timedelta(days=10)),
        ("Dashboard-Bug bei der Anwesenheitsliste prüfen",
         "Meldung kam über den Support.",
         personen["lea"], None, "tech", "offen", "hoch",
         heute + timedelta(days=1)),
        ("Kassenbuch für März abschließen", None,
         personen["jonas"], None, "exekutive", "erledigt", "mittel", None),
        ("Sponsoren für Planspiel anschreiben", None,
         None, "exekutive", "exekutive", "offen", "niedrig",
         heute + timedelta(days=14)),
        ("Neue Mitglieder in WhatsApp-Gruppe einladen", None,
         personen["mila"], None, "recruitment", "erledigt", "niedrig", None),
        ("Server-Backup testen",
         "Einmal wirklich zurückspielen, nicht nur prüfen, ob die Datei da ist.",
         personen["noah"], None, "tech", "offen", "hoch",
         heute + timedelta(days=5)),
    )
    erledigt = []
    for titel, beschreibung, wer, wessen_abteilung, task_abt, status, prio, frist in entwurf:
        aufgabe = Task(
            titel=titel, beschreibung=beschreibung,
            assignee_id=wer.id if wer else None,
            assignee_department=wessen_abteilung,
            task_department=task_abt, status=status, priority=prio,
            deadline=frist, creator_id=chef.id, created_at=utcnow())
        if status == "erledigt":
            aufgabe.completed_at = utcnow() - timedelta(days=1)
        db.add(aufgabe)
        if status == "erledigt" and wer:
            erledigt.append(aufgabe)
    db.flush()
    for aufgabe in erledigt:
        leistung.aufgabe_erledigt(db, aufgabe)
    return erledigt


def _treffen(db, personen):
    """Zwei vergangene Treffen mit Protokoll und Anwesenheit, zwei kommende
    mit offenen Zu-/Absagen und einer Tagesordnung. Ohne ein vergangenes
    Treffen bleibt die Anwesenheitsliste leer und der Leadership-Wert auf
    null - beides Kernstuecke des Dashboards."""
    from kern.modelle import (Attendance, Meeting, MeetingPunkt,
                              MeetingRueckmeldung)
    from kern import leistung
    from kern.text import utcnow

    if db.query(Meeting).count() > 0:
        return
    chef = personen["chef"]
    heute = date.today()
    alle = list(personen.values())

    vergangen_1 = Meeting(
        title="AG-Treffen", date=heute - timedelta(days=14),
        start_time="15:30", end_time="17:00", location="Raum 204",
        protocol=("Planspiel Börse besprochen, Teams eingeteilt. Ida hat "
                  "das Kassenbuch für Februar vorgestellt."),
        attendees="Die meisten da, zwei entschuldigt.",
        created_at=utcnow() - timedelta(days=14))
    vergangen_2 = Meeting(
        title="AG-Treffen", date=heute - timedelta(days=28),
        start_time="15:30", end_time="17:00", location="Raum 204",
        protocol="Halbjahresplanung fürs Unternehmertum-Modul.",
        attendees="Vollzählig.",
        created_at=utcnow() - timedelta(days=28))
    kommend_1 = Meeting(
        title="AG-Treffen", date=heute + timedelta(days=7),
        start_time="15:30", end_time="17:00", location="Raum 204",
        created_at=utcnow())
    kommend_2 = Meeting(
        title="AG-Treffen", date=heute + timedelta(days=21),
        start_time="15:30", end_time="17:00", location="Raum 204",
        created_at=utcnow())
    for treffen in (vergangen_1, vergangen_2, kommend_1, kommend_2):
        db.add(treffen)
    db.flush()

    # Anwesenheit fuer das juengere vergangene Treffen: die meisten da, zwei
    # nicht - erst DANACH sieht man in der Auswertung einen Unterschied.
    da_gewesen = alle[:-2]
    for person in da_gewesen:
        eintrag = Attendance(user_id=person.id, meeting_id=vergangen_1.id,
                             event_type="Treffen", event_date=vergangen_1.date,
                             created_at=utcnow() - timedelta(days=14))
        db.add(eintrag)
        db.flush()
        leistung.anwesenheit_erfasst(db, eintrag)
    for person in alle:
        eintrag = Attendance(user_id=person.id, meeting_id=vergangen_2.id,
                             event_type="Treffen", event_date=vergangen_2.date,
                             created_at=utcnow() - timedelta(days=28))
        db.add(eintrag)
        db.flush()
        leistung.anwesenheit_erfasst(db, eintrag)

    # Zu-/Absagen zum naechsten Treffen - deshalb "kommend_1" und nicht 2:
    # ein Treffen, zu dem schon geantwortet wurde, aber noch nichts
    # abgerechnet ist, ist der interessantere Anblick als ein leeres.
    for i, person in enumerate(alle):
        antwort = "nein" if i % 5 == 0 else "ja"
        db.add(MeetingRueckmeldung(
            meeting_id=kommend_1.id, user_id=person.id, antwort=antwort,
            grund="Klausurwoche" if antwort == "nein" else None,
            created_at=utcnow()))

    db.add(MeetingPunkt(meeting_id=kommend_1.id, user_id=chef.id,
                        text="Stand Planspiel Börse", created_at=utcnow()))
    db.add(MeetingPunkt(meeting_id=kommend_1.id, user_id=personen["sophie"].id,
                        text="Instagram-Kampagne zum Bewerbungsstart",
                        erledigt=0, created_at=utcnow()))


def _kalender(db, personen):
    from kern.modelle import CalendarEvent
    from kern.text import utcnow

    if db.query(CalendarEvent).count() > 0:
        return
    heute = date.today()
    chef = personen["chef"]
    db.add(CalendarEvent(title="Abgabe Wettbewerbsbeitrag",
                         start_date=heute + timedelta(days=21),
                         created_by=chef.id, target_type="alle",
                         created_at=utcnow()))
    db.add(CalendarEvent(title="Redaktionsschluss Instagram-Kampagne",
                         description="Bilder und Texte müssen fertig sein.",
                         start_date=heute + timedelta(days=4),
                         created_by=chef.id, target_type="department",
                         target_department="marketing", created_at=utcnow()))
    db.add(CalendarEvent(title="Vorstellungsgespräche Recruiting",
                         start_date=heute + timedelta(days=9),
                         start_time="16:00", end_time="18:00",
                         location="Raum 204",
                         created_by=chef.id, target_type="department",
                         target_department="recruitment", created_at=utcnow()))


def _wettbewerbe(db, personen):
    """Ein abgeschlossener Wettbewerb mit Platzierungen, einer, der noch
    läuft - Punkte fließen nur beim ersten in den Leadership-Wert ein."""
    from kern.modelle import Competition, CompetitionParticipant
    from kern import leistung
    from kern.text import utcnow

    if db.query(Competition).count() > 0:
        return
    heute = date.today()
    chef = personen["chef"]
    abgeschlossen = Competition(
        title="Planspiel Börse (Herbstrunde)",
        description="Bundesweiter Wettbewerb der Sparkassen.",
        date=heute - timedelta(days=60), location="online",
        organizer_id=chef.id, status="abgeschlossen", created_at=utcnow())
    laufend = Competition(
        title="Jugend Gründet", description="Ideenwettbewerb für Schülerteams.",
        date=heute + timedelta(days=90), location="online",
        organizer_id=chef.id, status="aktiv", created_at=utcnow())
    db.add(abgeschlossen)
    db.add(laufend)
    db.flush()

    platzierungen = ((personen["jonas"], "Team Nord", 1, 100),
                     (personen["lea"], "Team Nord", 1, 100),
                     (personen["sophie"], "Team Süd", 3, 60))
    for person, team, platz, punkte in platzierungen:
        teilnahme = CompetitionParticipant(
            competition_id=abgeschlossen.id, user_id=person.id,
            team_name=team, placement=platz, points=punkte,
            created_at=utcnow() - timedelta(days=55))
        db.add(teilnahme)
        db.flush()
        leistung.wettbewerb_erfasst(db, teilnahme)

    for person in (personen["ben"], personen["mila"]):
        db.add(CompetitionParticipant(
            competition_id=laufend.id, user_id=person.id,
            team_name="Team Ost", created_at=utcnow()))


def _projekte(db, personen):
    from kern.modelle import Project, ProjectTeamMember
    from kern import leistung
    from kern.text import utcnow

    if db.query(Project).count() > 0:
        return
    heute = date.today()
    laufend = Project(
        title="Eigener Merch-Verkauf", description="T-Shirts mit AG-Logo.",
        status="laufend", lead_id=personen["ben"].id,
        deadline=heute + timedelta(days=30), progress=40, created_at=utcnow())
    fertig = Project(
        title="Neuer Instagram-Auftritt", description="Feed neu geordnet.",
        status="abgeschlossen", lead_id=personen["sophie"].id,
        progress=100, created_at=utcnow() - timedelta(days=40))
    db.add(laufend)
    db.add(fertig)
    db.flush()

    mitarbeit = (
        (laufend, personen["ben"], "Leitung"),
        (laufend, personen["mila"], "Mitarbeit"),
        (laufend, personen["elias"], "Mitarbeit"),
        (fertig, personen["sophie"], "Leitung"),
        (fertig, personen["emilia"], "Mitarbeit"),
    )
    for projekt, person, rolle in mitarbeit:
        mitglied = ProjectTeamMember(project_id=projekt.id, user_id=person.id,
                                     role=rolle, joined_at=utcnow())
        db.add(mitglied)
        db.flush()
        leistung.projekt_mitarbeit(db, mitglied)


def _redaktionsplan(db, personen):
    from kern.modelle import ContentItem
    from kern.text import utcnow

    if db.query(ContentItem).count() > 0:
        return
    heute = date.today()
    entwurf = (
        ("marketing", "Bewerbungsstart ankündigen", "instagram", "geplant",
         personen["sophie"], heute + timedelta(days=4)),
        ("marketing", "Rückblick Planspiel Börse", "instagram", "idee",
         personen["emilia"], None),
        ("marketing", "Aushang fürs schwarze Brett", "aushang", "in_arbeit",
         personen["finn"], heute + timedelta(days=2)),
        ("recruitment", "Newsletter an Interessierte", "newsletter",
         "veroeffentlicht", personen["ben"], heute - timedelta(days=10)),
        ("exekutive", "Startseiten-Text zum Halbjahreswechsel", "website",
         "idee", None, None),
    )
    for abteilung, titel, kanal, status, wer, wann in entwurf:
        db.add(ContentItem(
            abteilung=abteilung, titel=titel, kanal=kanal, status=status,
            verantwortlich_id=wer.id if wer else None, datum=wann,
            creator_id=personen["chef"].id, created_at=utcnow()))


def _kassenbuch(db, personen):
    from kern.modelle import Buchung, Budget, Dauerauftrag
    from kern.text import utcnow

    if db.query(Buchung).count() > 0:
        return
    heute = date.today()
    chef = personen["chef"]
    entwurf = (
        # (Tage zurück, Zweck, Cent, Kategorie, Abteilung)
        (60, "Mitgliedsbeiträge Februar", 8000, "mitgliedsbeitrag", None),
        (55, "Materialkosten Bastelnachmittag", -2340, "material", "marketing"),
        (40, "Sponsoring Sparkasse", 25000, "sponsoring", None),
        (35, "Fahrtkosten Planspiel-Finale", -4500, "fahrtkosten", "exekutive"),
        (30, "Merch-Verkauf T-Shirts", 6200, "verkauf", "recruitment"),
        (20, "Startgeld Jugend Gründet", -1500, "veranstaltung", "exekutive"),
        (14, "Mitgliedsbeiträge März", 8200, "mitgliedsbeitrag", None),
        (10, "Druckkosten Aushänge", -890, "material", "marketing"),
        (5, "Getränke AG-Treffen", -1200, "veranstaltung", "exekutive"),
        (1, "Spende Elternbeirat", 5000, "sponsoring", None),
    )
    for tage, zweck, cent, kategorie, abteilung in entwurf:
        db.add(Buchung(datum=heute - timedelta(days=tage), zweck=zweck,
                       betrag_cent=cent, kategorie=kategorie,
                       abteilung=abteilung, erfasser_id=chef.id,
                       created_at=utcnow() - timedelta(days=tage)))

    db.add(Budget(abteilung="marketing", bezeichnung="Aushänge & Druck",
                  von=heute.replace(day=1), bis=heute + timedelta(days=60),
                  betrag_cent=15000, created_at=utcnow()))
    db.add(Dauerauftrag(
        zweck="Cloud-Speicher fürs Archiv", betrag_cent=-499,
        kategorie="sonstiges", rhythmus="monatlich",
        start_datum=heute - timedelta(days=90),
        naechste_faelligkeit=heute + timedelta(days=15),
        ausfuehrungen=3, aktiv=1, angelegt_von=chef.id, created_at=utcnow()))


def _nachrichten(db, personen):
    """Kontaktanfragen von der Website in jedem Stand, dazu zwei
    Rundnachrichten - sonst bleibt "Nachrichten" der leerste Bereich im
    ganzen Dashboard, obwohl er fast taeglich benutzt wird."""
    from kern.modelle import ContactMessage, DirectMessage, DirectMessageRecipient
    from kern.text import utcnow

    if db.query(ContactMessage).count() == 0:
        db.add(ContactMessage(
            name="Familie Roth", email="familie.roth@beispiel.de",
            message="Kann mein Kind auch mitten im Schuljahr einsteigen?",
            reply="Ja, jederzeit - am besten zum nächsten Treffen dazukommen.",
            replied_by=personen["chef"].id,
            replied_at=utcnow() - timedelta(days=2),
            reply_mail_ok=1, created_at=utcnow() - timedelta(days=3)))
        db.add(ContactMessage(
            name="Herr Alt", email="herr.alt@beispiel.de",
            message="Gibt es die AG auch für die Unterstufe?",
            created_at=utcnow() - timedelta(hours=6)))
        db.add(ContactMessage(
            name="Frau Sander", email="frau.sander@beispiel.de",
            message="Wo finde ich die Termine für das Planspiel?",
            reply="Die stehen ab nächster Woche auf der Startseite.",
            replied_by=personen["chef"].id,
            replied_at=utcnow() - timedelta(hours=1),
            reply_mail_ok=0,
            reply_mail_fehler="SMTPAuthenticationError: Testbestand ohne "
                              "Mailversand.",
            created_at=utcnow() - timedelta(days=1)))

    if db.query(DirectMessage).count() == 0:
        rund_1 = DirectMessage(
            sender_id=personen["chef"].id, subject="Neues Dashboard ist da",
            body="Ab sofort läuft alles über die neue Version - schaut euch "
                "in Ruhe um, Fragen gerne im Support.",
            created_at=utcnow() - timedelta(days=5))
        rund_2 = DirectMessage(
            sender_id=personen["chef"].id, subject="Erinnerung: AG-Treffen",
            body="Nicht vergessen: Diese Woche ist wieder Treffen, 15:30 in "
                "Raum 204.",
            created_at=utcnow() - timedelta(hours=3))
        db.add(rund_1)
        db.add(rund_2)
        db.flush()
        for person in personen.values():
            db.add(DirectMessageRecipient(
                message_id=rund_1.id, user_id=person.id,
                read_at=utcnow() if person is personen["chef"] else None))
            db.add(DirectMessageRecipient(
                message_id=rund_2.id, user_id=person.id))


def _support(db, personen):
    from kern.modelle import SupportTicket
    from kern.text import utcnow

    if db.query(SupportTicket).count() > 0:
        return
    db.add(SupportTicket(
        user_id=personen["lea"].id, subject="Anwesenheitsliste zeigt Fehler",
        message="Beim Eintragen der Anwesenheit für das letzte Treffen kam "
                "eine Fehlermeldung, die ich nicht verstanden habe.",
        status="offen", created_at=utcnow() - timedelta(hours=4)))
    db.add(SupportTicket(
        user_id=personen["mila"].id, subject="Passwort zurücksetzen ging nicht",
        message="Der Link aus der Mail war schon abgelaufen, als ich ihn "
                "geöffnet habe.",
        reply="Sollte jetzt 24 statt 2 Stunden gelten - bitte nochmal "
             "versuchen und melden, falls nicht.",
        replied_by=personen["chef"].id,
        replied_at=utcnow() - timedelta(days=1),
        status="erledigt", created_at=utcnow() - timedelta(days=2)))


def _leistungswerte(personen):
    """Die Leadership-Werte einmal fuer alle rechnen - sonst zeigt der
    Bereich "Leistung" nur Nullen, obwohl Aufgaben, Anwesenheit und
    Wettbewerbe schon Punkte gebracht haben."""
    from kern.leistung import alle_neu_rechnen
    return alle_neu_rechnen()


def _inhalte(db):
    """Den ganzen Testbestand aufbauen - Personen zuerst, danach alles, was
    an ihnen haengt. Jede Teilfunktion ist fuer sich lesbar und laesst sich
    einzeln nachvollziehen; hier steht nur die Reihenfolge."""
    chef = _konto(db, VOLLZUGRIFF, "Test", "Vollzugriff", "cto", "exekutive")
    mitglied = _konto(db, MITGLIED, "Mia", "Mitglied", "member", "marketing")
    weitere = _mitglieder(db)

    personen = {"chef": chef, "mitglied": mitglied}
    for person in weitere:
        personen[person.vorname.lower()] = person

    _bewerbungen(db)
    _aufgaben(db, personen)
    _treffen(db, personen)
    _kalender(db, personen)
    _wettbewerbe(db, personen)
    _projekte(db, personen)
    _redaktionsplan(db, personen)
    _kassenbuch(db, personen)
    _nachrichten(db, personen)
    _support(db, personen)
    return chef, mitglied, personen


def _bilanz(db) -> dict:
    """Was am Ende wirklich in der Datenbank steht - fuer die Ausgabe.

    Nicht dieselben Zahlen, die die einzelnen Bauschritte schon kennen: Die
    haben nur den Teil gesehen, den sie selbst angelegt haben. Hier zaehlt
    dieselbe Abfrage, die auch die Anwendung benutzen wuerde - so faellt
    ein Zaehlfehler in einer der _funktionen() sofort auf, statt sich in
    einer optimistischen Ausgabe zu verstecken.
    """
    from kern.modelle import (Application, Buchung, CalendarEvent,
                              Competition, ContactMessage, ContentItem,
                              DirectMessage, Meeting, Project, SupportTicket,
                              Task, User)

    inaktiv = db.query(User).filter(User.status == "inaktiv").count()
    zeilen = [
        f"Bewerbungen : {db.query(Application).count()}",
        f"Aufgaben    : {db.query(Task).count()}",
        f"Treffen     : {db.query(Meeting).count()}",
        f"Termine     : {db.query(CalendarEvent).count()}",
        f"Wettbewerbe : {db.query(Competition).count()}",
        f"Projekte    : {db.query(Project).count()}",
        f"Redaktion   : {db.query(ContentItem).count()}",
        f"Buchungen   : {db.query(Buchung).count()}",
        f"Nachrichten : {db.query(ContactMessage).count()} Kontaktanfragen, "
        f"{db.query(DirectMessage).count()} Rundnachrichten",
        f"Support     : {db.query(SupportTicket).count()}",
    ]
    return {"inaktiv": inaktiv, "zeilen": zeilen}


def _zusammenlegen():
    """Alles in die eine Datei schreiben, die auch weitergegeben wird.

    SQLite schreibt im WAL-Modus zuerst in ag_plattform.db-wal und erst
    spaeter in die Datenbank selbst. Genau diese Nebendatei ist aber in
    .gitignore gesperrt - committet wuerde also ein Stand, dem die letzten
    Aenderungen fehlen. Der naechste, der das Projekt auscheckt, faende ein
    Testkonto ohne Rechte vor und suchte den Fehler in der Anwendung.

    VACUUM raeumt zusaetzlich auf: Ohne das bleibt der Platz geloeschter
    Zeilen in der Datei stehen, und sie waechst mit jedem Neubau.
    """
    import sqlite3
    pfad = os.path.join(DATEN_DIR, "ag_plattform.db")
    verbindung = sqlite3.connect(pfad)
    try:
        verbindung.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        verbindung.execute("VACUUM")
        verbindung.commit()
    finally:
        verbindung.close()
    for anhang in ("-wal", "-shm"):
        nebendatei = pfad + anhang
        if os.path.exists(nebendatei):
            try:
                os.remove(nebendatei)
            except OSError:                                  # pragma: no cover
                pass


def bauen(neu: bool) -> None:
    if neu:
        _leeren()

    from kern.migration import migriere
    migriere(still=True)

    from kern.datenbank import SessionLocal
    from kern.rechte import cache_verwerfen, rechte_von

    db = SessionLocal()
    try:
        chef, mitglied, personen = _inhalte(db)
        gesamt, neu_vergeben = _alle_rechte(db, chef)
        funktionen = _abteilungsfunktionen(db)
        db.commit()
        cache_verwerfen()

        # Nachsehen statt hoffen: Was am Ende WIRKLICH gilt, entscheidet
        # rechte_von() - nicht das, was hier eingetragen wurde.
        person = db.query(type(chef)).filter(
            type(chef).email == VOLLZUGRIFF).first()
        person._rechte_ausnahmen = None
        wirksam = rechte_von(person, db)
        fehlend = sorted(k for k, v in wirksam.items() if not v)

        bilanz = _bilanz(db)
    finally:
        db.close()

    # Eigene, kurzlebige Sitzung (siehe kern/leistung.py) - erst NACH dem
    # commit oben, sonst rechnet sie mit einem Stand, der die eben
    # eingetragenen Aufgaben und Anwesenheiten noch nicht kennt und der
    # Bereich "Leistung" zeigt nur Nullen.
    from kern.leistung import alle_neu_rechnen
    alle_neu_rechnen()

    _zusammenlegen()

    print()
    print("  Datenbank   : " + os.path.join(DATEN_DIR, "ag_plattform.db"))
    print(f"  Konten      : {len(personen)} ({bilanz['inaktiv']} inaktiv)")
    print(f"  Rechte      : {gesamt} vergeben ({neu_vergeben} neu), "
          f"{len(fehlend)} fehlen")
    print("  Abteilung   : " + ", ".join(funktionen) + " für die Exekutive")
    for zeile in bilanz["zeilen"]:
        print("  " + zeile)
    if fehlend:
        print("  ! Nicht wirksam: " + ", ".join(fehlend))
        raise SystemExit(1)
    print()
    print("  Anmelden mit")
    print(f"    {VOLLZUGRIFF:<24} {PASSWORT}   (alle Rechte)")
    print(f"    {MITGLIED:<24} {PASSWORT}   (einfaches Mitglied)")
    print()
    print("  Starten mit  start-entwicklung.bat")
    print("  Website      http://localhost:8010")
    print("  Dashboard    http://localhost:8011")


if __name__ == "__main__":
    zerleger = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    zerleger.add_argument("--neu", action="store_true",
                          help="Bestehende Entwicklungsdatenbank vorher löschen.")
    bauen(zerleger.parse_args().neu)
