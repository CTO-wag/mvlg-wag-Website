"""Bringt eine bestehende Datenbank auf den aktuellen Stand.

Nur anhaengend: neue Tabellen, neue Spalten, Vorbelegungen. Es wird nichts
geloescht und nichts umbenannt. Vor jedem Lauf, der etwas aendert, entsteht
eine Sicherheitskopie.
"""

import json
import os
import shutil
from datetime import datetime

from sqlalchemy import inspect, text

from kern.datenbank import Base, SessionLocal, engine
from kern.einstellungen import BACKUP_DIR, DATENBANK_DATEI
from kern.modelle import (
    AppSetting, Attendance, CompetitionParticipant, Inhalt, Leistung,
    ProjectTeamMember, Task, TrashItem, User,
)
from kern.rechte import (
    CTO_KERNRECHTE, DEPT_PERM_KEYS, PERMISSIONS, PERM_KEYS, ROLE_RANG,
    abteilungen_anlegen, cache_verwerfen, rollen_anlegen,
)
from kern.text import utcnow

MIGRATIONS_MARKE = "v2_migration_stand"
# 5: Umzugs-Rundgang (user_preferences.neuerungen_*) und der letzte
#    Abruf des Kalender-Abos (users.calendar_last_fetch).
# 6: Ersatzcodes fuer den zweiten Faktor, Zu-/Absagen und
#    Tagesordnung fuer Treffen.
AKTUELLER_STAND = 6


def _spalten(tabelle: str) -> set:
    try:
        return {s["name"] for s in inspect(engine).get_columns(tabelle)}
    except Exception:
        return set()


def _tabellen() -> set:
    return set(inspect(engine).get_table_names())


def _spalte_anhaengen(tabelle: str, name: str, typ: str, standard=None) -> bool:
    """Haengt eine Spalte an, wenn sie fehlt. Gibt zurueck, ob etwas geschah.

    SQLite kann Spalten nur anhaengen, nicht einfuegen - das genuegt hier.
    Ein NOT NULL braucht zwingend einen Standardwert, sonst weigert sich
    SQLite bei einer Tabelle, in der schon Zeilen stehen.
    """
    if name in _spalten(tabelle):
        return False
    satz = f'ALTER TABLE "{tabelle}" ADD COLUMN "{name}" {typ}'
    if standard is not None:
        satz += f" DEFAULT {standard}"
    with engine.begin() as verbindung:
        verbindung.execute(text(satz))
    return True


def _steht_etwas_an() -> bool:
    """Wird die Migration ueberhaupt etwas veraendern?

    Frueher wurde vor JEDEM Start eine Sicherung angelegt - auch dann, wenn
    die Datenbank laengst auf dem aktuellen Stand war und die Migration nur
    noch durchlief, ohne etwas zu tun. Der Ordner fuellte sich mit fast
    gleichen Dateien, und die eine Sicherung, auf die es ankommt, ging darin
    unter.

    Massgeblich ist die Marke in app_settings: steht dort der aktuelle Stand,
    ist strukturell nichts offen. Laesst sie sich nicht lesen (frische oder
    beschaedigte Datenbank), wird im Zweifel gesichert.
    """
    try:
        with engine.begin() as verbindung:
            zeile = verbindung.execute(
                text('SELECT value FROM app_settings WHERE key = :k'),
                {"k": MIGRATIONS_MARKE}).fetchone()
    except Exception:
        return True
    return not (zeile and str(zeile[0]) == str(AKTUELLER_STAND))


def _sicherung_vor_migration() -> None:
    """Einmal die Datenbank wegkopieren, bevor etwas veraendert wird.

    Kostet ein paar hundert Kilobyte und beantwortet die einzige Frage, die
    bei einem Umstieg wirklich zaehlt: Kommt man zurueck, wenn etwas schiefgeht?
    """
    if not os.path.exists(DATENBANK_DATEI):
        return
    ziel = os.path.join(
        BACKUP_DIR,
        f"vor-migration-{datetime.now().strftime('%Y-%m-%d_%H-%M')}.db")
    if os.path.exists(ziel):
        return
    try:
        # Ueber die SQLite-eigene Sicherung, damit auch offene WAL-Inhalte
        # mitkommen - ein blosses Kopieren der Datei kann sie verlieren.
        import sqlite3
        quelle = sqlite3.connect(DATENBANK_DATEI)
        try:
            kopie = sqlite3.connect(ziel)
            with kopie:
                quelle.backup(kopie)
            kopie.close()
        finally:
            quelle.close()
        print(f"[Migration] Sicherung angelegt: {os.path.basename(ziel)}")
    except Exception as fehler:                              # pragma: no cover
        # Notfalls die einfache Kopie - besser als gar keine Sicherung.
        try:
            shutil.copy2(DATENBANK_DATEI, ziel)
        except Exception:
            print(f"[Migration] Sicherung fehlgeschlagen: {fehler}")


#  Einzelschritte
def _neue_spalten() -> int:
    """Alles, was V2 zusaetzlich braucht."""
    getan = 0
    neu = [
        # users
        ("users", "totp_secret", "VARCHAR(64)", None),
        ("users", "totp_aktiv", "INTEGER NOT NULL", "0"),
        ("users", "totp_ersatzcodes", "TEXT", None),
        # Vermerke fuer die taeglichen Hinweise (kern/hinweise.py)
        ("meetings", "erinnert_am", "DATE", None),
        ("calendar_events", "erinnert_am", "DATE", None),
        ("applications", "erinnert_am", "DATE", None),
        ("users", "passwort_geaendert_am", "DATETIME", None),
        ("users", "willkommen_gesendet_am", "DATETIME", None),
        # user_sessions
        ("user_sessions", "geraete_hash", "VARCHAR(64)", None),
        ("user_sessions", "dauerhaft", "INTEGER NOT NULL", "1"),
        ("user_preferences", "als_app_am", "DATETIME", None),
        ("meetings", "leistung_verrechnet", "DATE", None),
        # user_preferences
        ("user_preferences", "startbereich", "VARCHAR(40)", None),
        ("user_preferences", "kompakt", "INTEGER NOT NULL", "0"),
        # Umzugs-Rundgang: eigener Zaehler, siehe UserPreference.
        ("user_preferences", "neuerungen_version", "VARCHAR(20)", None),
        ("user_preferences", "neuerungen_erledigt", "INTEGER NOT NULL", "0"),
        ("user_preferences", "neuerungen_gefragt", "INTEGER NOT NULL", "0"),
        ("user_preferences", "umzug_ohne_kalender", "INTEGER NOT NULL", "0"),
        ("user_preferences", "startpasswort_egal", "INTEGER NOT NULL", "0"),
        # users: letzter Abruf des Kalender-Abos
        ("users", "calendar_last_fetch", "DATETIME", None),
        # roles
        # Standard 0, nicht 50: an der 0 erkennt die Vorbelegung unten, dass
        # der Rang noch nie gesetzt wurde. Mit einem Standard ungleich 0 saehe
        # jede Rolle bereits "gepflegt" aus und alle haetten denselben Rang.
        ("roles", "rang", "INTEGER NOT NULL", "0"),
        ("roles", "beschreibung", "TEXT", None),
        # notification_preferences
        ("notification_preferences", "ruhe_von", "VARCHAR(5)", None),
        ("notification_preferences", "ruhe_bis", "VARCHAR(5)", None),
        ("notification_preferences", "system", "INTEGER NOT NULL", "1"),
        # leadership_scores
        ("leadership_scores", "gesamt", "INTEGER NOT NULL", "0"),
        ("leadership_scores", "zuverlaessigkeit", "INTEGER NOT NULL", "0"),
        ("leadership_scores", "initiative", "INTEGER NOT NULL", "0"),
        # seiten_inhalte: Portfolio-Angaben
        ("seiten_inhalte", "zeitraum", "VARCHAR(60)", None),
        ("seiten_inhalte", "ergebnis", "VARCHAR(120)", None),
        # push_subscriptions: Website und Dashboard duerfen sich beide
        # anmelden. Woher die Anmeldung kam und welches Geraet dahintersteckt,
        # steht ab jetzt dabei - sonst bekaeme dasselbe Handy jede Meldung
        # zweimal. Bestehende Zeilen bleiben leer und werden weiter zugestellt.
        ("push_subscriptions", "ursprung", "VARCHAR(16)", None),
        ("push_subscriptions", "geraete_id", "VARCHAR(40)", None),
    ]
    vorhandene_tabellen = _tabellen()
    for tabelle, name, typ, standard in neu:
        if tabelle not in vorhandene_tabellen:
            continue
        if _spalte_anhaengen(tabelle, name, typ, standard):
            getan += 1
    # Rechtespalten in roles und departments
    for tabelle, schluessel in (("roles", PERM_KEYS), ("departments", DEPT_PERM_KEYS)):
        if tabelle not in vorhandene_tabellen:
            continue
        for perm in schluessel:
            if _spalte_anhaengen(tabelle, perm, "INTEGER NOT NULL", "0"):
                getan += 1
    return getan


def _neue_rechte_vorbelegen() -> None:
    """Neue Rechte sinnvoll setzen statt ueberall auf 0 zu lassen.

    Eine frisch angehaengte Spalte steht auf 0. Waere das so geblieben, haette
    nach dem Umstieg niemand mehr die Startseite bearbeiten oder den
    WhatsApp-Bot bedienen koennen - auch der CTO nicht. Deshalb bekommen die
    in V2 hinzugekommenen Rechte ihre Vorbelegung genau einmal, danach nie
    wieder: wer sie spaeter bewusst abwaehlt, soll das behalten duerfen.
    """
    from kern.modelle import Role                     # spaet, wegen Spalten
    db = SessionLocal()
    try:
        marke = db.get(AppSetting, "v2_rechte_vorbelegt")
        if marke:
            return
        for rolle in db.query(Role).all():
            vorlage = PERMISSIONS.get(rolle.key)
            for perm in ("rechte_personen", "whatsapp_bot", "seiteninhalte",
                         "sicherheit"):
                if perm not in PERM_KEYS:
                    continue
                if vorlage is not None:
                    setattr(rolle, perm, int(vorlage.get(perm, False)))
                elif rolle.key == "cto":
                    setattr(rolle, perm, 1)
            if rolle.key == "cto":
                for perm in CTO_KERNRECHTE:
                    setattr(rolle, perm, 1)
            # Rang genau einmal setzen. Selbst angelegte Rollen bekommen 20 -
            # ueber einem Mitglied, unter jeder Vorstandsrolle. Wer das anders
            # will, stellt es danach im Rollen-Tab ein.
            rolle.rang = ROLE_RANG.get(rolle.key, 20)
        db.add(AppSetting(key="v2_rechte_vorbelegt", value="1"))
        db.commit()
        print("[Migration] Neue Rechte vorbelegt.")
    except Exception as fehler:                              # pragma: no cover
        db.rollback()
        print(f"[Migration] Rechte-Vorbelegung übersprungen: {fehler}")
    finally:
        db.close()
    cache_verwerfen()


def _leistungen_aufbauen() -> None:
    """Baut den dauerhaften Leistungsnachweis einmalig aus dem Bestand auf.

    Quellen, in dieser Reihenfolge:
      1. erledigte Aufgaben, die es noch gibt
      2. erledigte Aufgaben, die im Papierkorb liegen - genau die, die in V1
         beim Loeschen aus dem Score verschwanden
      3. Anwesenheiten, Wettbewerbsplatzierungen, Projektmitgliedschaften

    Danach schreibt die Anwendung jede weitere Erledigung sofort mit.
    """
    db = SessionLocal()
    try:
        if db.get(AppSetting, "v2_leistungen_aufgebaut"):
            return
        vorhanden = {(l.user_id, l.art, l.quelle_id) for l in db.query(
            Leistung.user_id, Leistung.art, Leistung.quelle_id).all()}
        neu = 0

        def merken(user_id, art, quelle_id, titel, zeitpunkt, punkte=1,
                   abteilung=None):
            nonlocal neu
            if not user_id:
                return
            schluessel = (user_id, art, quelle_id)
            if schluessel in vorhanden:
                return
            vorhanden.add(schluessel)
            db.add(Leistung(user_id=user_id, art=art, quelle_id=quelle_id,
                            titel=(titel or "")[:200], abteilung=abteilung,
                            punkte=punkte, zeitpunkt=zeitpunkt or utcnow()))
            neu += 1

        for t in db.query(Task).filter(Task.status == "erledigt").all():
            merken(t.assignee_id, "aufgabe", t.id, t.titel,
                   t.completed_at or t.updated_at or t.created_at,
                   abteilung=t.task_department)

        # Aus dem Papierkorb: dort liegt der komplette Datensatz als JSON.
        for eintrag in db.query(TrashItem).filter(
                TrashItem.entity_type == "task").all():
            try:
                daten = json.loads(eintrag.payload)
            except Exception:
                continue
            if daten.get("status") != "erledigt":
                continue
            zeit = daten.get("completed_at") or daten.get("updated_at")
            try:
                zeit = datetime.fromisoformat(zeit) if zeit else eintrag.deleted_at
            except Exception:
                zeit = eintrag.deleted_at
            merken(daten.get("assignee_id"), "aufgabe", daten.get("id"),
                   daten.get("titel"), zeit,
                   abteilung=daten.get("task_department"))

        for a in db.query(Attendance).all():
            merken(a.user_id, "anwesenheit", a.id, a.event_type,
                   datetime.combine(a.event_date, datetime.min.time())
                   if a.event_date else a.created_at)

        for cp in db.query(CompetitionParticipant).all():
            punkte = 3 if (cp.placement and cp.placement <= 3) else 1
            merken(cp.user_id, "wettbewerb", cp.id, cp.team_name or "Teilnahme",
                   cp.created_at, punkte=punkte)

        for pm in db.query(ProjectTeamMember).all():
            merken(pm.user_id, "projekt", pm.id, pm.role or "Mitarbeit",
                   pm.joined_at)

        db.add(AppSetting(key="v2_leistungen_aufgebaut", value="1"))
        db.commit()
        if neu:
            print(f"[Migration] {neu} Leistungsnachweis(e) aus dem Bestand übernommen.")
    except Exception as fehler:                              # pragma: no cover
        db.rollback()
        print(f"[Migration] Leistungsaufbau übersprungen: {fehler}")
    finally:
        db.close()


# Die vier Karten aus "Was wir konkret machen" - Text unveraendert aus V1.
# Sie beschreiben, WOMIT sich die AG beschaeftigt, und heissen deshalb jetzt
# "angebot". Was die AG bereits GETAN hat, steht getrennt davon im Portfolio.
ANGEBOT_VORBELEGUNG = (
    ("Börse verstehen",
     "Wie liest man einen Geschäftsbericht? Was ist ein ETF, was ein Index? "
     "Wir gehen es an echten Unternehmen durch, nicht am Whiteboard.",
     "#0E2647"),
    ("Eigene Projekte",
     "Kleine Teams, eine Idee, ein Fahrplan. Ihr rechnet sie durch und stellt "
     "sie der ganzen AG vor.",
     "#B7791F"),
    ("Planspiele & Wettbewerbe",
     "Planspiel Börse, Wharton Investment Challenge, Jugend Gründet, Startup "
     "Teens. Spielgeld oder Konzeptpapier, aber echte Kurse, echte Kriterien, "
     "echter Ehrgeiz.",
     "#2F855A"),
    ("Austausch",
     "Andere treffen, die auf dasselbe Thema stehen wie du, über Jahrgänge "
     "hinweg. Ab und zu bringen wir Leute aus der Praxis mit dazu.",
     "#B83280"),
)

VORTEILE_VORBELEGUNG = (
    "Du blickst durch, wie Börse und Unternehmen wirklich funktionieren",
    "Du hast ein eigenes Projekt von der Idee bis zur Präsentation durchgezogen",
    "Du stehst vor einer Gruppe und redest, ohne dass dir die Stimme wegbricht",
    "Du hast bei echten Wettbewerben mitgemischt, nicht nur simuliert",
    "Zeugnis, Lebenslauf, Bewerbungsgespräch. Du hast was vorzuweisen",
)

STUFEN_VORBELEGUNG = (
    ("Einstieg.", "Sitzungen, Grundlagen, erste Simulationen"),
    ("Vertiefung.", "Eigenes Projekt, erste Wettbewerbe, ein Schwerpunkt"),
    ("Projektteam.", "Eigenständig an Wettbewerbsbeiträgen arbeiten"),
    ("Core-Team.", "Jahresplanung, Projekte, die AG mitgestalten"),
)


def _seiteninhalte_vorbelegen() -> None:
    db = SessionLocal()
    try:
        if not db.query(Inhalt).count():
            for nr, (titel, text_, farbe) in enumerate(ANGEBOT_VORBELEGUNG, start=1):
                db.add(Inhalt(bereich="angebot", titel=titel, text=text_,
                              farbe=farbe, reihenfolge=nr * 10))
            for nr, zeile in enumerate(VORTEILE_VORBELEGUNG, start=1):
                db.add(Inhalt(bereich="vorteile", titel=zeile, reihenfolge=nr * 10))
            for nr, (titel, text_) in enumerate(STUFEN_VORBELEGUNG, start=1):
                db.add(Inhalt(bereich="stufen", titel=titel, text=text_,
                              reihenfolge=nr * 10))
            db.commit()
            print("[Migration] Startseiten-Blöcke angelegt (Text wie bisher).")

        # Aus "arbeit" ist zweierlei geworden: "angebot" beschreibt, womit wir
        # uns beschaeftigen, "portfolio" zeigt, was schon dabei herauskam. Die
        # vorhandenen Bloecke sind Beschreibungen - sie wandern zum Angebot.
        umgezogen = db.query(Inhalt).filter(Inhalt.bereich == "arbeit").update(
            {"bereich": "angebot", "icon": None}, synchronize_session=False)
        # Die Bildzeichen fallen ueberall weg - die Seite kommt ohne aus.
        db.query(Inhalt).filter(Inhalt.icon.isnot(None)).update(
            {"icon": None}, synchronize_session=False)
        if umgezogen:
            db.commit()
            print(f"[Migration] {umgezogen} Startseiten-Block/Blöcke nach "
                  "„Womit wir uns beschäftigen“ übernommen.")
        else:
            db.commit()
    except Exception as fehler:                              # pragma: no cover
        db.rollback()
        print(f"[Migration] Startseiten-Blöcke übersprungen: {fehler}")
    finally:
        db.close()


def _altlasten_pruefen() -> None:
    """Meldet Tabellen, die kein Modell mehr hat - loescht sie aber nicht.

    In der Datenbank stehen noch chats, chat_participants, chat_messages und
    news aus einer frueheren Fassung. Sie stoeren nicht, und sie zu loeschen
    waere genau die Art Aufraeumen, die man spaeter bereut. Sie werden nur
    einmal genannt, damit niemand sie fuer aktiv haelt.
    """
    bekannt = set(Base.metadata.tables.keys())
    unbekannt = sorted(t for t in _tabellen()
                       if t not in bekannt and not t.startswith("sqlite_"))
    if unbekannt:
        print(f"[Migration] Nicht mehr benutzte Tabellen bleiben unberührt: "
              f"{', '.join(unbekannt)}")


def _daten_saeubern() -> None:
    """Entschaerft unvollstaendige Altdaten, damit nichts abstuerzt."""
    from kern.rechte import abteilungs_keys, rollen_keys
    from kern.text import email_gueltig, email_normal, sauber
    from kern.modelle import USER_STATUS

    db = SessionLocal()
    try:
        gueltige_rollen = set(rollen_keys())
        gueltige_abteilungen = set(abteilungs_keys())
        geaendert = False
        for user in db.query(User).all():
            if user.role not in gueltige_rollen:
                user.role, geaendert = "member", True
            if user.department not in gueltige_abteilungen:
                user.department, geaendert = "exekutive", True
            if user.status not in USER_STATUS:
                user.status, geaendert = "inaktiv", True
            if not sauber(user.vorname):
                user.vorname, geaendert = "Unvollständig", True
            if not sauber(user.nachname):
                user.nachname, geaendert = f"Konto {user.id}", True
            adresse = email_normal(user.email)
            if not email_gueltig(adresse):
                user.email = f"unvollstaendig-{user.id}@invalid.local"
                user.status, geaendert = "inaktiv", True
            elif adresse != user.email:
                user.email, geaendert = adresse, True
        if geaendert:
            db.commit()
    finally:
        db.close()


#  Einstieg
def migriere(still: bool = False) -> None:
    """Alles, was beim Start einmal passieren muss - in dieser Reihenfolge."""
    schon_da = bool(_tabellen())
    if schon_da and _steht_etwas_an():
        _sicherung_vor_migration()

    # 1. Fehlende Tabellen anlegen. Bestehende laesst create_all in Ruhe.
    Base.metadata.create_all(engine)

    # 2. Fehlende Spalten anhaengen.
    angehaengt = _neue_spalten()
    if angehaengt and not still:
        print(f"[Migration] {angehaengt} neue Spalte(n) angelegt.")

    # 3. Rollen und Abteilungen ergaenzen (nicht ueberschreiben).
    rollen_anlegen()
    abteilungen_anlegen()

    # 4. Einmalige Nacharbeiten.
    _neue_rechte_vorbelegen()
    _leistungen_aufbauen()
    _seiteninhalte_vorbelegen()
    _daten_saeubern()

    db = SessionLocal()
    try:
        stand = db.get(AppSetting, MIGRATIONS_MARKE)
        if stand:
            stand.value = str(AKTUELLER_STAND)
        else:
            db.add(AppSetting(key=MIGRATIONS_MARKE, value=str(AKTUELLER_STAND)))
        db.commit()
    finally:
        db.close()

    # Bei jedem Start aufraeumen, nicht nur wenn gerade gesichert wurde.
    # Sonst blieben die Dateien aus der Zeit vor dieser Aenderung fuer immer
    # liegen. Der Rueckweg nach V1 ist davon ausgenommen (kern/sicherung.py).
    try:
        from kern.sicherung import alte_entfernen
        weg = alte_entfernen()
        if weg and not still:
            print(f"[Migration] {weg} alte Sicherung(en) aufgeraeumt.")
    except Exception as problem:                             # pragma: no cover
        print(f"[Migration] Aufraeumen der Sicherungen: {problem}")

    if not still:
        _altlasten_pruefen()
