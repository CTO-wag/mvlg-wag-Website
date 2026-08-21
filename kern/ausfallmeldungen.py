"""Meldungen und Bewerbungen abholen, die waehrend eines Ausfalls beim
Cloudflare-Worker liegen geblieben sind (siehe cloudflare/worker.js).

Abholen und Bestaetigen sind getrennt: Der Worker wirft erst weg, wenn hier
ein Ticket steht. Ein doppeltes Ticket sieht man, ein fehlendes nicht.
"""

import json
import urllib.error
import urllib.request

from kern import einstellungen as cfg
from kern.datenbank import sitzung
from kern.modelle import SupportTicket, User
from kern.text import kuerzen, sauber, utcnow

# Steht am Anfang des Betreffs. Daran erkennt der naechste Lauf seine eigenen
# Tickets wieder - und der CTO in der Liste, worum es geht, ohne zu oeffnen.
BETREFF_MARKE = "Ausfallmeldung"

# In dieser Zeile im Text steht die Kennung der Meldung. Sie muss maschinen-
# lesbar sein, aber im Ticket nicht stoeren - deshalb eine eigene letzte Zeile.
KENNUNG_MARKE = "[Meldung: "

ZEITGRENZE = 15


def eingerichtet() -> bool:
    """Ist ein Auffangnetz hinterlegt? Ohne das tut dieses Modul nichts."""
    return bool(cfg.AUSFALL_WORKER_URL and cfg.AUSFALL_SCHLUESSEL)


def _rufen(weg: str, daten=None):
    """Eine Anfrage an das Auffangnetz. Gibt die gelesene Antwort zurueck."""
    adresse = cfg.AUSFALL_WORKER_URL.rstrip("/") + weg
    koerper = None if daten is None else json.dumps(daten).encode("utf-8")
    anfrage = urllib.request.Request(adresse, data=koerper, headers={
        "x-ausfall-schluessel": cfg.AUSFALL_SCHLUESSEL,
        "content-type": "application/json",
        "user-agent": "WAG-Plattform",
    })
    with urllib.request.urlopen(anfrage, timeout=ZEITGRENZE) as antwort:
        roh = antwort.read(400000).decode("utf-8", "replace")
    return json.loads(roh) if roh.strip() else None


def _empfaenger(db):
    """Wem das Ticket gehoert, wenn sich kein Absender finden laesst."""
    from kern.stoerung import empfaenger
    leute = empfaenger(db)
    return leute[0] if leute else None


def _absender(db, meldung: dict):
    """Das Konto zur angegebenen E-Mail - oder None.

    Bewusst nur ueber die E-Mail und nicht ueber den Namen: Ein Name aus einem
    offenen Feld beweist nichts. Wer "Jan Weber" hineinschreibt, bekommt kein
    Ticket im Namen von Jan Weber.
    """
    post = sauber(meldung.get("kontakt")).lower()
    if not post or "@" not in post:
        return None
    return db.query(User).filter(User.email == post,
                                 User.status == "aktiv").first()


def _text_bauen(meldung: dict, selbst: bool) -> str:
    zeilen = [sauber(meldung.get("text")) or "(kein Text)"]
    zeilen.append("")
    zeilen.append("--- vom Auffangnetz aufgenommen ---")
    if meldung.get("zeitpunkt"):
        zeilen.append(f"Zeitpunkt: {meldung['zeitpunkt']} (UTC)")
    if meldung.get("seite"):
        zeilen.append(f"Adresse: {meldung['seite']}{meldung.get('lage') or ''}")
    if meldung.get("name"):
        zeilen.append(f"Angegebener Name: {meldung['name']}")
    if meldung.get("kontakt"):
        zeilen.append(f"Angegebene E-Mail: {meldung['kontakt']}")
    if not selbst:
        zeilen.append("")
        zeilen.append("Dieses Ticket kam anonym von der Fehlerseite herein - "
                      "die angegebene E-Mail gehoert zu keinem aktiven Konto. "
                      "Eine Antwort im Ticket erreicht die Person also nicht; "
                      "falls eine Adresse dabeisteht, geht es nur per Mail.")
    zeilen.append("")
    zeilen.append(KENNUNG_MARKE + str(meldung.get("kennung", "?")) + "]")
    return "\n".join(zeilen)


def _schon_bekannt(db, kennungen: list) -> set:
    """Welche dieser Meldungen haben schon ein Ticket?"""
    if not kennungen:
        return set()
    treffer = set()
    # Nur die Ausfall-Tickets ansehen, und nur die neueren. Eine Meldung, die
    # laenger als vier Wochen liegt, gibt es beim Worker nicht mehr.
    for ticket in (db.query(SupportTicket)
                   .filter(SupportTicket.subject.ilike(BETREFF_MARKE + "%"))
                   .order_by(SupportTicket.id.desc()).limit(300).all()):
        for kennung in kennungen:
            if KENNUNG_MARKE + kennung + "]" in (ticket.message or ""):
                treffer.add(kennung)
    return treffer


def abholen() -> dict:
    """Meldungen holen, Tickets anlegen, beim Worker bestaetigen.

    Gibt eine Bilanz zurueck: {"neu": n, "doppelt": n, "fehler": text}.
    Wirft nichts - das hier laeuft in einem Hintergrundfaden, und ein
    unerreichbares Auffangnetz ist kein Grund, den Faden zu beenden.
    """
    bilanz = {"neu": 0, "doppelt": 0, "bewerbungen": 0,
              "bewerbungen_doppelt": 0, "fehler": ""}
    if not eingerichtet():
        return bilanz

    try:
        meldungen = _rufen("/__ausfall/abholen") or []
    except urllib.error.HTTPError as fehler:
        bilanz["fehler"] = f"Antwort {fehler.code} vom Auffangnetz"
        return bilanz
    except Exception as fehler:
        bilanz["fehler"] = f"{type(fehler).__name__}: {fehler}"
        return bilanz

    # Seit dem Auffangnetz auch Bewerbungen aufnimmt, kommt ein Paket mit zwei
    # Faechern. Die alte Form (eine blanke Liste) wird noch verstanden, damit
    # ein Worker, der noch nicht neu ausgerollt ist, nichts blockiert.
    if isinstance(meldungen, dict):
        bewerbungen = meldungen.get("bewerbungen") or []
        meldungen = meldungen.get("meldungen") or []
    else:
        bewerbungen = []

    if bewerbungen:
        b_bilanz = _bewerbungen_eintragen(bewerbungen)
        bilanz["bewerbungen"] = b_bilanz["neu"]
        bilanz["bewerbungen_doppelt"] = b_bilanz["doppelt"]
        if b_bilanz["fehler"] and not bilanz["fehler"]:
            bilanz["fehler"] = b_bilanz["fehler"]

    if not meldungen:
        return bilanz

    erledigt = []
    angelegt = []
    with sitzung() as db:
        vorstand = _empfaenger(db)
        if not vorstand:
            bilanz["fehler"] = "Kein Empfaenger vorhanden (kein aktives Konto)"
            return bilanz

        bekannt = _schon_bekannt(db, [m.get("kennung", "") for m in meldungen])
        for meldung in meldungen:
            kennung = meldung.get("kennung") or ""
            if kennung in bekannt:
                bilanz["doppelt"] += 1
                erledigt.append(kennung)
                continue

            person = _absender(db, meldung)
            wer = person.name if person else (sauber(meldung.get("name"))
                                              or "anonym")
            ticket = SupportTicket(
                user_id=(person or vorstand).id,
                subject=kuerzen(f"{BETREFF_MARKE}: {wer} konnte die Plattform "
                                f"nicht erreichen", 160),
                message=_text_bauen(meldung, bool(person)),
                status="offen",
                created_at=utcnow(),
            )
            db.add(ticket)
            bilanz["neu"] += 1
            erledigt.append(kennung)
            angelegt.append((wer, sauber(meldung.get("text"))))
        db.commit()

    # Erst jetzt darf der Worker sie wegwerfen. Scheitert das, bleiben sie
    # liegen und werden beim naechsten Lauf als "doppelt" erkannt - unschoen,
    # aber nichts geht verloren.
    if erledigt:
        try:
            _rufen("/__ausfall/bestaetigen", {"kennungen": erledigt})
        except Exception as fehler:                          # pragma: no cover
            bilanz["fehler"] = (f"Tickets angelegt, aber nicht bestaetigt "
                                f"({type(fehler).__name__}) - beim naechsten "
                                f"Lauf werden sie uebersprungen")

    # Der CTO soll es auch erfahren, wenn er das Telefon-Klingeln des Workers
    # verpasst hat oder gar kein ntfy-Thema eingetragen ist.
    if angelegt:
        _vorstand_benachrichtigen(angelegt)
    return bilanz


#  Bewerbungen aus der Zeit ohne Verbindung
def _bewerbungen_eintragen(rohe: list) -> dict:
    """Aus hinterlegten Bewerbungen echte Eintraege machen.

    Zwei Dinge sind hier wichtiger als anderswo:

    * **Nichts wird geglaubt.** Der Worker prueft schon, aber er steht im
      offenen Netz. Alles wird hier noch einmal geprueft, mit denselben
      Regeln wie im echten Formular - eine Bewerbung, die ueber diesen Weg
      hereinkommt, ist am Ende von einer normalen nicht zu unterscheiden.
    * **Der Zeitpunkt kommt aus der Bewerbung, nicht von der Uhr.** Sonst
      stuende dort der Moment, in dem der Rechner wieder anging - und die
      Erinnerung "liegt seit drei Tagen unbeantwortet" begaenne zu spaet.
    """
    from datetime import datetime
    from kern import benachrichtigung, mail
    from kern.modelle import Application
    from kern.rechte import abteilung_label, bewerbbare_abteilungen
    from kern.text import (email_gueltig, email_normal, telefon_anzeige,
                           telefon_gueltig)

    bilanz = {"neu": 0, "doppelt": 0, "fehler": ""}
    erledigt = []
    angelegt = []

    with sitzung() as db:
        erlaubte = {a["key"] for a in bewerbbare_abteilungen()}
        for roh in rohe:
            kennung = roh.get("kennung") or ""
            post = email_normal(sauber(roh.get("email")))[:160]
            vorname = sauber(roh.get("vorname"))[:80]
            nachname = sauber(roh.get("nachname"))[:80]
            klasse = sauber(roh.get("klasse"))[:40]
            telefon = sauber(roh.get("telefonnummer"))[:40]
            abteilung = sauber(roh.get("abteilung"))
            motivation = sauber(roh.get("motivation"))[:3000]
            interessen = sauber(roh.get("interessen"))[:3000]

            if not all([vorname, nachname, klasse, post, telefon, motivation,
                        interessen]):
                # Unbrauchbar. Wegwerfen, sonst liegt sie vier Wochen im Weg
                # und wird bei jedem Lauf neu geprueft.
                erledigt.append(kennung)
                continue
            # Rueckhalt, falls jemand am Formular vorbei sendet. Der Worker
            # prueft dasselbe schon und sagt es sofort - hier landet also nur,
            # was ihn umgangen hat.
            from website.routen.bewerbung import schuladresse
            if (not email_gueltig(post) or abteilung not in erlaubte
                    or schuladresse(post)):
                erledigt.append(kennung)
                continue
            if telefon_gueltig(telefon):
                telefon = telefon_anzeige(telefon)

            wann = _zeitpunkt(roh.get("zeitpunkt"))
            # Dieselbe Doppelklick-Sperre wie im echten Formular, nur ueber
            # den ganzen Bestand: Wer sich waehrend des Ausfalls zweimal
            # beworben hat, soll nicht zweimal in der Liste stehen.
            schon_da = db.query(Application).filter(
                Application.email == post,
                Application.created_at >= wann.replace(
                    hour=0, minute=0, second=0, microsecond=0)).first()
            if schon_da:
                bilanz["doppelt"] += 1
                erledigt.append(kennung)
                continue

            bewerbung = Application(
                vorname=vorname, nachname=nachname, klasse=klasse, email=post,
                telefonnummer=telefon, motivation=motivation,
                interessen=interessen,
                vorwissen=sauber(roh.get("vorwissen"))[:3000] or None,
                department=abteilung, status="neu", created_at=wann)
            db.add(bewerbung)
            db.flush()
            bilanz["neu"] += 1
            erledigt.append(kennung)
            angelegt.append((bewerbung.id, vorname, nachname, klasse,
                             post, abteilung))
        db.commit()

    if erledigt:
        try:
            _rufen("/__ausfall/bestaetigen", {"kennungen": erledigt})
        except Exception as fehler:                          # pragma: no cover
            bilanz["fehler"] = (f"Bewerbungen eingetragen, aber nicht "
                                f"bestaetigt ({type(fehler).__name__})")

    for kennung, vorname, nachname, klasse, post, abteilung in angelegt:
        _bewerbung_bestaetigen(kennung, vorname, nachname, post, abteilung)
        try:
            with sitzung() as db:
                benachrichtigung.melde_rechteinhabern(
                    db, "bewerbungen", "applications",
                    "Bewerbung aus der Ausfallzeit",
                    f"{vorname} {nachname} ({klasse}) hat sich beworben, "
                    "während die Plattform nicht erreichbar war.")
                db.commit()
        except Exception as fehler:                          # pragma: no cover
            print(f"[Ausfallmeldungen] Benachrichtigung: {fehler}")
    return bilanz


def _zeitpunkt(roh):
    """Der Zeitpunkt aus dem Auffangnetz - oder jetzt, wenn er unlesbar ist."""
    from datetime import datetime
    if not roh:
        return utcnow()
    try:
        return datetime.fromisoformat(str(roh).replace("Z", "+00:00")).replace(
            tzinfo=None)
    except ValueError:
        return utcnow()


def _bewerbung_bestaetigen(bewerbung_id, vorname, nachname, post, abteilung):
    """Die Eingangsbestaetigung nachholen.

    Sie konnte waehrend des Ausfalls nicht rausgehen - dafuer haette es einen
    Mailserver gebraucht, den es am Rand des Netzes nicht gibt. Jetzt geht sie
    raus, und zwar mit demselben Vordruck wie sonst: Fuer die bewerbende
    Person soll sich der Umweg nicht bemerkbar machen.
    """
    from kern import mail
    from kern.modelle import Application
    from kern.rechte import abteilung_label
    if not mail.versand_moeglich():
        return
    try:
        with sitzung() as db:
            eintrag = db.get(Application, bewerbung_id)
            if not eintrag or eintrag.email_sent:
                return

            class _Empfaenger:
                id = None
                role = "member"
                department = "exekutive"

            empfaenger = _Empfaenger()
            empfaenger.vorname = vorname
            empfaenger.nachname = nachname
            empfaenger.email = post
            empfaenger.name = f"{vorname} {nachname}"
            versandt = mail.sende_vordruck(
                db, empfaenger, "application_received",
                abteilung=abteilung_label(abteilung) if abteilung else "offen")
            if versandt:
                eintrag.email_sent = 1
                db.commit()
    except Exception as fehler:                              # pragma: no cover
        print(f"[Ausfallmeldungen] Bestätigungsmail: {fehler}")


def _vorstand_benachrichtigen(angelegt: list) -> None:
    """Der Vorstand soll es auch ohne ntfy-Thema erfahren.

    Kein Weg ueber `stoerung.melde()`: Das hat eine Ruhefrist von zwoelf
    Stunden, und die waere hier falsch. Diese Meldungen kommen ohnehin nur
    gebuendelt, wenn die Plattform hochfaehrt - hoechstens eine je Neustart.
    Kategorie "system" wie bei den Stoerungen, damit sie in derselben Ecke der
    Einstellungen an- und abschaltbar sind.
    """
    from kern import benachrichtigung
    from kern.stoerung import empfaenger
    anzahl = len(angelegt)
    wer = ", ".join(name for name, _ in angelegt[:3])
    if anzahl > 3:
        wer += f" und {anzahl - 3} weitere"
    titel = ("Ausfallmeldung von der Fehlerseite" if anzahl == 1
             else f"{anzahl} Ausfallmeldungen von der Fehlerseite")
    text = (f"{wer} konnte die Plattform nicht erreichen, während sie aus war. "
            f"Steht als Ticket unter „Support“.")
    try:
        with sitzung() as db:
            leute = empfaenger(db)
            if leute:
                benachrichtigung.melde_vielen(db, leute, "system", titel, text,
                                              dringend=True,
                                              anlass="ausfallmeldung")
                db.commit()
    except Exception as fehler:                              # pragma: no cover
        print(f"[Ausfallmeldungen] Benachrichtigung fehlgeschlagen: {fehler}")
