"""Taegliche Erinnerungen, die nicht an Aufgaben haengen: Treffen, Termine und
Bewerbungen, die zu lange unbeantwortet liegen.

Jeder Hinweis traegt einen Vermerk am Datensatz, damit ein Neustart am
selben Tag nicht dieselbe Meldung ein zweites Mal schickt.
"""

from datetime import date, timedelta

from kern.datenbank import sitzung
from kern.modelle import Application, CalendarEvent, Meeting, User

# Wie viele Tage im Voraus an ein Treffen erinnert wird. Einen Tag vorher ist
# die Nachricht noch handlungsfaehig ("morgen ist AG"), am selben Morgen
# nochmal, weil dazwischen eine Nacht liegt.
VORLAUF_TAGE = 1

# Ab wann eine unbeantwortete Bewerbung als liegengeblieben gilt, und in
# welchem Abstand danach erinnert wird.
BEWERBUNG_TAGE = 3
BEWERBUNG_ABSTAND_TAGE = 3


def _tagesform(wann: date, heute: date) -> str:
    if wann == heute:
        return "heute"
    if wann == heute + timedelta(days=1):
        return "morgen"
    return wann.strftime("%d.%m.")


def treffen_erinnern(heute: date = None) -> int:
    """An Treffen von heute und morgen erinnern. Gibt die Anzahl zurueck."""
    from kern import benachrichtigung
    heute = heute or date.today()
    verschickt = 0
    with sitzung() as db:
        anstehend = db.query(Meeting).filter(
            Meeting.date >= heute,
            Meeting.date <= heute + timedelta(days=VORLAUF_TAGE),
        ).all()
        for treffen in anstehend:
            if treffen.erinnert_am == heute:
                continue
            personen = db.query(User).filter(User.status == "aktiv").all()
            wann = _tagesform(treffen.date, heute)
            benachrichtigung.melde_vielen(
                db, personen, "messages",
                f"AG-Treffen {wann}",
                f"„{treffen.title}“ – {treffen.date.strftime('%d.%m.%Y')}. "
                "Wer nicht kann, sagt im Dashboard unter „AG-Treffen“ ab.",
                anlass="treffen")
            treffen.erinnert_am = heute
            verschickt += 1
        db.commit()
    return verschickt


def termine_erinnern(heute: date = None) -> int:
    """An Kalendertermine von heute und morgen erinnern - nur die Betroffenen."""
    from kern import benachrichtigung, kalender
    heute = heute or date.today()
    verschickt = 0
    with sitzung() as db:
        anstehend = db.query(CalendarEvent).filter(
            CalendarEvent.start_date >= heute,
            CalendarEvent.start_date <= heute + timedelta(days=VORLAUF_TAGE),
        ).all()
        for termin in anstehend:
            if termin.erinnert_am == heute:
                continue
            personen = kalender.betroffene_personen(db, termin)
            if personen:
                wann = _tagesform(termin.start_date, heute)
                zeit = f" um {termin.start_time} Uhr" if termin.start_time else ""
                ort = f", {termin.location}" if termin.location else ""
                benachrichtigung.melde_vielen(
                    db, personen, "messages",
                    f"Termin {wann}",
                    f"„{termin.title}“{zeit}{ort}.", anlass="termin")
                verschickt += 1
            termin.erinnert_am = heute
        db.commit()
    return verschickt


def bewerbungen_anstossen(heute: date = None) -> int:
    """Erinnert alle Zustaendigen an Bewerbungen, die unbeantwortet liegen."""
    from kern import benachrichtigung
    heute = heute or date.today()
    grenze = heute - timedelta(days=BEWERBUNG_TAGE)
    with sitzung() as db:
        offen = [b for b in db.query(Application).filter(
            Application.status == "neu").all()
            if b.created_at and b.created_at.date() <= grenze
            and (b.erinnert_am is None
                 or b.erinnert_am <= heute - timedelta(days=BEWERBUNG_ABSTAND_TAGE))]
        if not offen:
            return 0
        # Eine Meldung fuer alle zusammen, nicht eine je Bewerbung: Wer
        # fuenf Meldungen auf einmal bekommt, liest keine davon.
        aelteste = min(b.created_at.date() for b in offen)
        tage = (heute - aelteste).days
        if len(offen) == 1:
            b = offen[0]
            titel = "Bewerbung wartet auf Antwort"
            text = (f"{b.vorname} {b.nachname} hat sich vor {tage} Tagen "
                    "beworben und noch keine Antwort bekommen.")
        else:
            titel = f"{len(offen)} Bewerbungen warten"
            text = (f"{len(offen)} Bewerbungen sind noch unbeantwortet, die "
                    f"älteste seit {tage} Tagen.")
        benachrichtigung.melde_rechteinhabern(
            db, "bewerbungen", "applications", titel, text)
        for b in offen:
            b.erinnert_am = heute
        db.commit()
    return len(offen)


def alle(heute: date = None) -> dict:
    """Alles auf einmal - so ruft der Planer es auf."""
    return {
        "treffen": treffen_erinnern(heute),
        "termine": termine_erinnern(heute),
        "bewerbungen": bewerbungen_anstossen(heute),
    }
