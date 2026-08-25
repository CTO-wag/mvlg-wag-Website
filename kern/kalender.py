"""Termine und das persoenliche Kalender-Abo (.ics).

Das Abo ist der Grund, warum Termine ueberhaupt etwas nuetzen: Ein Termin,
den man nur sieht, wenn man sich anmeldet, wird verpasst. Ueber die
.ics-Adresse landet er im Kalender des Handys - und zwar nur die Termine,
die die Person wirklich betreffen.
"""

import secrets
from datetime import datetime, timedelta, timezone

from kern import einstellungen as cfg
from kern.modelle import CalendarEvent, User
from kern.rechte import zustaendige_abteilungen
from kern.text import BERLIN_TZ, utcnow


def sichtbar_fuer(termin: CalendarEvent, user: User) -> bool:
    """Betrifft dieser Termin diese Person?"""
    if not termin or not user:
        return False
    if termin.target_type == "alle":
        return True
    if termin.target_type == "person":
        return termin.target_user_id == user.id
    meine = set(zustaendige_abteilungen(user))
    if termin.target_type == "abteilung":
        return termin.target_department in meine
    if termin.target_type == "auswahl":
        for ziel in termin.targets:
            if ziel.user_id == user.id:
                return True
            if ziel.department and ziel.department in meine:
                return True
    return False


def betroffene_personen(db, termin: CalendarEvent) -> list:
    """Wen dieser Termin angeht - fuer die Benachrichtigung."""
    aktive = db.query(User).filter(User.status == "aktiv").all()
    return [p for p in aktive if sichtbar_fuer(termin, p)]


def abo_adresse(db, user: User) -> str:
    """Die persoenliche .ics-Adresse. Wird beim ersten Aufruf erzeugt."""
    if not user.calendar_token:
        user.calendar_token = secrets.token_urlsafe(24)[:48]
        db.commit()
    # Der Dashboard-Name, nicht der Hauptname. Das war einmal andersherum
    # gedacht ("der Hauptname ist stabiler"), bis eine Messung das Gegenteil
    # zeigte: Unter mvlg-wag.de laeuft noch die alte Fassung, die diesen Pfad
    # nicht kennt - dort kam 404. Unter app.mvlg-wag.de kam die Datei.
    # Ausgegeben wird deshalb die Adresse, die nachweislich antwortet.
    # Ausgeliefert wird sie von beiden Seiten (kern/kalender_abo.py); sobald
    # ueberall dieselbe Fassung laeuft, funktionieren also beide.
    return f"{cfg.DASHBOARD_URL}/dashboard/kalender/{user.calendar_token}.ics"


#  iCalendar
def _maskieren(text) -> str:
    """Sonderzeichen nach RFC 5545. Reihenfolge zaehlt: erst der Backslash."""
    return (str(text or "")
            .replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _falten(zeile: str) -> str:
    """Zeilen ueber 75 Oktett umbrechen - sonst lehnen manche Apps ab.

    Gezaehlt wird in Bytes, nicht in Zeichen: ein Umlaut braucht zwei, und
    ein Umbruch mitten in einem Zeichen macht die Datei unlesbar.
    """
    roh = zeile.encode("utf-8")
    if len(roh) <= 75:
        return zeile
    teile, rest = [], roh
    teile.append(rest[:73])
    rest = rest[73:]
    while rest:
        teile.append(rest[:72])
        rest = rest[72:]
    ausgabe = teile[0].decode("utf-8", "ignore")
    for weiter in teile[1:]:
        ausgabe += "\r\n " + weiter.decode("utf-8", "ignore")
    return ausgabe


def als_ics(db, user: User) -> str:
    """Alle Termine, die diese Person betreffen, als Kalenderdatei.

    Auch AG-Treffen kommen mit: Sie sind der wichtigste wiederkehrende Termin,
    und wer sie nicht im Kalender hat, hat den Kalender umsonst abonniert.
    """
    from kern.modelle import Meeting

    jetzt = utcnow().strftime("%Y%m%dT%H%M%SZ")
    zeilen = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Wirtschafts- und Investment-AG//Dashboard//DE",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:Wirtschafts- & Investment-AG",
        "X-WR-TIMEZONE:Europe/Berlin",
        # Wie oft die App nachfragen soll. Ohne Angabe fragen manche einmal
        # taeglich - dann kommt ein kurzfristiger Termin zu spaet an.
        "REFRESH-INTERVAL;VALUE=DURATION:PT2H",
        "X-PUBLISHED-TTL:PT2H",
    ]

    def termin_block(kennung, titel, start_datum, start_zeit, end_datum,
                     end_zeit, ort, beschreibung, geaendert):
        block = ["BEGIN:VEVENT", f"UID:{kennung}@mvlg-wag.de", f"DTSTAMP:{jetzt}"]
        if start_zeit:
            beginn = datetime.combine(
                start_datum, datetime.strptime(start_zeit, "%H:%M").time())
            beginn = beginn.replace(tzinfo=BERLIN_TZ)
            schluss = beginn + timedelta(hours=1)
            if end_zeit:
                ende = datetime.combine(
                    end_datum or start_datum,
                    datetime.strptime(end_zeit, "%H:%M").time())
                schluss = ende.replace(tzinfo=BERLIN_TZ)
                if schluss <= beginn:
                    schluss = beginn + timedelta(hours=1)
            # astimezone() OHNE Ziel rechnet in die Zeitzone des Rechners um -
            # und darunter stand trotzdem ein "Z", also die Behauptung, das sei
            # UTC. Auf einem deutschen Rechner kam damit die Berliner Uhrzeit
            # als UTC heraus, und jede Kalender-App legte den Termin ein bis
            # zwei Stunden daneben. Gemeldet als "im Kalender falsche Zeit".
            block.append("DTSTART:"
                         + beginn.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
            block.append("DTEND:"
                         + schluss.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        else:
            # Ganztaegig. DTEND ist bei VALUE=DATE ausschliesslich - ohne das
            # +1 verschwindet ein eintaegiger Termin in manchen Apps.
            letzter = (end_datum or start_datum) + timedelta(days=1)
            block.append("DTSTART;VALUE=DATE:" + start_datum.strftime("%Y%m%d"))
            block.append("DTEND;VALUE=DATE:" + letzter.strftime("%Y%m%d"))
        block.append("SUMMARY:" + _maskieren(titel))
        if ort:
            block.append("LOCATION:" + _maskieren(ort))
        if beschreibung:
            block.append("DESCRIPTION:" + _maskieren(beschreibung))
        if geaendert:
            block.append("LAST-MODIFIED:" + geaendert.strftime("%Y%m%dT%H%M%SZ"))
        block.append("END:VEVENT")
        return block

    grenze = utcnow().date() - timedelta(days=90)
    for termin in (db.query(CalendarEvent)
                   .filter(CalendarEvent.start_date >= grenze)
                   .order_by(CalendarEvent.start_date).all()):
        if not sichtbar_fuer(termin, user):
            continue
        zeilen += termin_block(
            f"termin-{termin.id}", termin.title, termin.start_date,
            termin.start_time, termin.end_date, termin.end_time,
            termin.location, termin.description, termin.updated_at)

    for treffen in (db.query(Meeting)
                    .filter(Meeting.date >= grenze,
                            Meeting.calendar_event_id.is_(None))
                    .order_by(Meeting.date).all()):
        zeilen += termin_block(
            f"treffen-{treffen.id}", f"AG-Treffen: {treffen.title}",
            treffen.date, treffen.start_time, None, treffen.end_time,
            treffen.location,
            (treffen.protocol or "")[:500] or None, None)

    zeilen.append("END:VCALENDAR")
    return "\r\n".join(_falten(z) for z in zeilen) + "\r\n"
