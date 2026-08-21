"""Meldet dem Vorstand, wenn etwas Stilles kaputtgeht - ein gescheiterter
Sicherungslauf, ein WhatsApp-Bot ohne Kopplung.

Zwei Regeln: hoechstens eine Meldung je Ruhefrist (12 Stunden), und eine
Entwarnung, sobald es wieder laeuft. Der Stand steht in app_settings, damit
ein Neustart die Ruhefrist nicht zuruecksetzt.
"""

from datetime import timedelta

from kern import werte
from kern.datenbank import sitzung
from kern.modelle import User
from kern.text import utcnow

# Wie lange dieselbe Stoerung schweigt, nachdem sie einmal gemeldet wurde.
RUHEFRIST_STUNDEN = 12

_MARKE = "stoerung_"


def empfaenger(db) -> list:
    """Der Vorstand. Faellt der CTO aus, bleibt es bei den Verwaltern.

    Bewusst ueber die Rolle und nicht ueber ein Recht: Es geht um den
    Betrieb der Anlage, nicht um einen Fachbereich. Wer sie am Laufen haelt,
    ist der CTO - und wenn es den gerade nicht gibt, jeder, der Konten
    verwalten darf.

    Oeffentlich, weil dieselbe Frage inzwischen an zwei Stellen gebraucht wird:
    hier und bei den Ausfallmeldungen von der Fehlerseite
    (kern/ausfallmeldungen.py). Wer "wer haelt die Anlage am Laufen" zweimal
    beantwortet, beantwortet es irgendwann verschieden.
    """
    vorstand = db.query(User).filter(User.role == "cto",
                                     User.status == "aktiv").all()
    if vorstand:
        return vorstand
    from kern.rechte import personen_mit_recht
    return personen_mit_recht(db, "accounts_all")


# Alter Name, damit nichts bricht, was ihn noch benutzt.
_empfaenger = empfaenger


def melde(schluessel: str, titel: str, text: str) -> bool:
    """Eine Stoerung melden. Gibt zurueck, ob wirklich etwas verschickt wurde."""
    from kern import benachrichtigung
    jetzt = utcnow()
    with sitzung() as db:
        stand = werte.hole_db(db, _MARKE + schluessel, "")
        if stand:
            try:
                from datetime import datetime
                zuletzt = datetime.fromisoformat(stand)
                if jetzt - zuletzt < timedelta(hours=RUHEFRIST_STUNDEN):
                    return False
            except ValueError:                               # pragma: no cover
                pass
        werte.setze(db, _MARKE + schluessel, jetzt.isoformat())
        personen = _empfaenger(db)
        if not personen:                                     # pragma: no cover
            print(f"[Störung] {titel}: niemand zu benachrichtigen.")
            return False
        benachrichtigung.melde_vielen(db, personen, "system", titel, text,
                                      dringend=True)
        db.commit()
    print(f"[Störung] {titel} - Vorstand benachrichtigt.")
    return True


def entwarnung(schluessel: str, titel: str, text: str) -> bool:
    """Meldet, dass es wieder laeuft - aber nur, wenn vorher etwas war."""
    from kern import benachrichtigung
    with sitzung() as db:
        if not werte.hole_db(db, _MARKE + schluessel, ""):
            return False
        werte.setze(db, _MARKE + schluessel, "")
        personen = _empfaenger(db)
        if not personen:                                     # pragma: no cover
            return False
        benachrichtigung.melde_vielen(db, personen, "system", titel, text)
        db.commit()
    print(f"[Störung] {titel}")
    return True
