"""Eine Nachricht - drei Wege.

Wer eine Benachrichtigung ausloest, sagt nur, worum es geht. Welche Wege
benutzt werden, entscheidet diese Schicht anhand der persoenlichen
Einstellungen: Web Push aufs Handy, ntfy als zweiter Weg, E-Mail als dritter.

Neu gegenueber V1:

  * **Ein Weg genuegt.** Ist die Person ueber Push erreicht worden, geht nicht
    zusaetzlich eine E-Mail hinterher - ausser sie ist ausdruecklich gewuenscht.
    Vorher bekam man dieselbe Meldung dreifach.
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as WartezeitEnde
from datetime import datetime

from kern import mail, push, werte
from kern.modelle import NotificationPreference, User
from kern.protokoll import zustellung
from kern.rechte import hat_recht, personen_mit_recht
from kern.sicherheit import token_erzeugen
from kern.text import BERLIN_TZ, sauber

# Die Kategorien entsprechen den Spalten in notification_preferences.
KATEGORIEN = {
    "tasks": "Aufgaben",
    "applications": "Bewerbungen",
    "messages": "Nachrichten & Termine",
    "support": "Support",
    "direct": "Nachrichten vom Vorstand",
    "system": "Störungen der Anlage",
}
# Direktnachrichten gehen an jede Rolle - sie sind der Weg, auf dem der
# Vorstand alle erreicht. Die uebrigen Kategorien haengen an einem Recht:
# wer keine Bewerbungen sieht, braucht auch keine Meldung darueber.
KATEGORIE_RECHT = {
    "tasks": None,
    "applications": "bewerbungen",
    "messages": "nachrichten",
    "support": "support_verwaltung",
    "direct": None,
    # Wer sie bekommt, entscheidet der Absender (kern/stoerung.py) - das ist
    # der Vorstand. Ein Recht davorzuhaengen wuerde die Meldung nur ein
    # zweites Mal filtern und im Zweifel ganz verschlucken.
    "system": None,
}


def einstellung(db, user_id: int) -> NotificationPreference:
    """Die Einstellungen einer Person - notfalls neu angelegt.

    Das Thema wird nur einmal vergeben und danach nie geaendert: Es steht in
    der ntfy-App auf dem Handy, und ein neues Thema hiesse, dass die Person
    dort nichts mehr bekommt und es selbst merken muesste.
    """
    vorhanden = db.get(NotificationPreference, user_id)
    if vorhanden:
        return vorhanden
    from sqlalchemy.exc import IntegrityError
    while True:
        thema = "wag-" + token_erzeugen(32).replace("-", "x").replace("_", "y")[:52]
        if db.query(NotificationPreference).filter(
                NotificationPreference.topic == thema).first():
            continue
        neu = NotificationPreference(user_id=user_id, topic=thema)
        db.add(neu)
        try:
            db.commit()
            return neu
        except IntegrityError:
            # Zwei parallele Anfragen: eine gewinnt, die andere liest nach.
            db.rollback()
            vorhanden = db.get(NotificationPreference, user_id)
            if vorhanden:
                return vorhanden


def einstellungen_fuer(db, personen: list) -> dict:
    """Einstellungen fuer viele auf einmal - ohne Abfrage je Person.

    Einzeln in einer Schleife kostete in V1 pro Person mindestens einen
    Zugriff, fuer neue Konten sogar vier. Bei fuenfzig Konten war das der
    Unterschied zwischen einer schnellen und einer traegen Seite.
    """
    if not personen:
        return {}
    ids = [p.id for p in personen]
    gefunden = {e.user_id: e for e in db.query(NotificationPreference)
                .filter(NotificationPreference.user_id.in_(ids)).all()}
    fehlend = [i for i in ids if i not in gefunden]
    for user_id in fehlend:
        gefunden[user_id] = einstellung(db, user_id)
    return gefunden


def kategorien_erlaubt(user, db=None) -> dict:
    """Welche Kategorien fuer diese Person ueberhaupt in Frage kommen."""
    ergebnis = {}
    for kategorie, recht in KATEGORIE_RECHT.items():
        ergebnis[kategorie] = True if recht is None else hat_recht(user, recht, db)
    return ergebnis


def _testempfaenger(db) -> set:
    """Im Push-Testmodus gehen Meldungen nur an die Verwalter."""
    return {p.id for p in personen_mit_recht(db, "benachrichtigungen_admin")}


def melde(db, user_id: int, kategorie: str, titel: str, text: str,
          dringend: bool = False, anlass: str = None) -> None:
    """Der uebliche Weg: eine Person, eine Kategorie, fertig.

    Verschickt wird im Hintergrund. Der Aufrufer wartet nie auf einen
    Push-Dienst oder einen Mailserver.
    """
    person = db.get(User, user_id)
    if not person or person.status != "aktiv":
        return
    pref = einstellung(db, user_id)
    if not pref.enabled or not getattr(pref, kategorie, 1):
        return
    if not kategorien_erlaubt(person, db).get(kategorie, False):
        return
    if werte.an_db(db, werte.PUSH_TESTMODUS) and user_id not in _testempfaenger(db):
        zustellung("push", person.name, titel, False,
                   "Testmodus - nur an Verwalter", anlass or kategorie)
        return

    erreicht = False
    if pref.webpush:
        # Nur als "erreicht" zaehlen, wenn wirklich ein Geraet angemeldet ist.
        # Vorher genuegte der eingeschaltete Schalter - wer Web-Push an hatte,
        # aber (etwa nach dem Umzug) kein Geraet angemeldet, bekam weder Push
        # noch die E-Mail, die sonst eingesprungen waere.
        push.webpush_an_person(user_id, titel, text, ziel=person.name,
                               anlass=anlass or kategorie)
        erreicht = bool(push.empfaenger(db, user_id))
    if pref.ntfy:
        push.ntfy_an_thema(pref.topic, titel, text, ziel=person.name,
                           anlass=anlass or kategorie)
        erreicht = True
    # E-Mail als dritter Weg. Bei dringenden Sachen immer, sonst nur, wenn
    # sonst gar nichts greift - sonst kommt dieselbe Meldung dreifach an.
    if pref.email and mail.versand_moeglich() and (dringend or not erreicht):
        mail.sende_vordruck(db, person, "notification", titel=titel, text=text)


def melde_vielen(db, personen: list, kategorie: str, titel: str, text: str,
                 ausser_id: int = None, dringend: bool = False,
                 anlass: str = None) -> int:
    """Dieselbe Meldung an mehrere. Gibt zurueck, wie viele angesprochen wurden."""
    ziel = [p for p in personen
            if p and p.status == "aktiv" and p.id != ausser_id]
    if not ziel:
        return 0
    einstellungen_fuer(db, ziel)          # einmal vorab, spart Einzelabfragen
    for person in ziel:
        melde(db, person.id, kategorie, titel, text, dringend, anlass)
    return len(ziel)


def melde_abteilung(db, abteilung: str, kategorie: str, titel: str, text: str,
                    ausser_id: int = None) -> int:
    personen = db.query(User).filter(User.department == abteilung,
                                     User.status == "aktiv").all()
    return melde_vielen(db, personen, kategorie, titel, text, ausser_id)


def melde_rechteinhabern(db, recht: str, kategorie: str, titel: str, text: str,
                         ausser_id: int = None) -> int:
    """An alle, die ein bestimmtes Recht haben.

    Damit haengen Benachrichtigungen an der Zustaendigkeit statt an einer fest
    verdrahteten Rolle: wer den Support verwaltet, bekommt Support-Meldungen -
    egal, wie die Rolle heisst.
    """
    return melde_vielen(db, personen_mit_recht(db, recht), kategorie, titel,
                        text, ausser_id)


#  Gezielter Versand mit Rueckmeldung
def verteile(db, empfaenger: list, kanaele: set, titel: str, text: str,
             anlass: str = "manuell") -> dict:
    """Direktversand aus dem Dashboard - mit ehrlicher Bilanz.

    Hier sitzt jemand vor dem Bildschirm und will wissen, was angekommen ist.
    Deshalb wird gewartet, aber begrenzt: fuenfundzwanzig Sekunden fuer alles
    zusammen. Was laenger braucht, laeuft im Hintergrund weiter und steht
    hinterher im Zustellprotokoll.
    """
    bilanz = {"webpush": 0, "ntfy": 0, "email": 0, "fehler": []}
    if not empfaenger:
        return bilanz
    einstellungen_fuer(db, empfaenger)
    auftraege = []

    for person in empfaenger:
        pref = einstellung(db, person.id)
        if "webpush" in kanaele and pref.webpush:
            auftraege.append(("webpush", person.name, lambda p=person: (
                push.webpush_an_person(p.id, titel, text, warten=True,
                                       ziel=p.name, anlass=anlass))))
        if "ntfy" in kanaele and pref.ntfy:
            auftraege.append(("ntfy", person.name, lambda p=person, t=pref.topic: (
                push.ntfy_an_thema(t, titel, text, warten=True,
                                   ziel=p.name, anlass=anlass))))
        if "email" in kanaele and pref.email and mail.versand_moeglich():
            auftraege.append(("email", person.name, lambda p=person: (
                mail.sende_vordruck(db, p, "notification", warten=True,
                                    titel=titel, text=text), "")))

    if not auftraege:
        return bilanz

    with ThreadPoolExecutor(max_workers=min(8, len(auftraege))) as pool:
        laufend = {pool.submit(arbeit): (kanal, name)
                   for kanal, name, arbeit in auftraege}
        for zukunft in laufend:
            kanal, name = laufend[zukunft]
            try:
                ergebnis = zukunft.result(timeout=25)
                geklappt = ergebnis[0] if isinstance(ergebnis, tuple) else bool(ergebnis)
                if geklappt:
                    bilanz[kanal] += 1
                else:
                    grund = ergebnis[1] if isinstance(ergebnis, tuple) and len(ergebnis) > 1 else ""
                    bilanz["fehler"].append(f"{name}: {grund or 'nicht zugestellt'}")
            except WartezeitEnde:
                bilanz["fehler"].append(f"{name}: dauert länger, läuft weiter")
            except Exception as problem:                     # pragma: no cover
                bilanz["fehler"].append(f"{name}: {type(problem).__name__}")
    return bilanz
