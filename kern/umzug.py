"""Was jede Person nach dem Umzug auf V2 einmal selbst erledigen muss.

Startbildschirm, Kalender-Abo und Push haengen am Geraet und lassen sich
fuer niemanden von aussen einrichten. Dieses Modul sagt je Person, was noch
fehlt - wer alles gemacht hat, sieht nichts mehr davon.
"""

from datetime import datetime

from kern import einstellungen as cfg
from kern.modelle import PushSubscription, User

# Ab wann eine Anmeldung oder ein Abruf zur neuen Aufstellung gehoert.
# Alles davor stammt von den alten Adressen und beweist nichts.
UMZUG_AB = datetime(2026, 8, 14, 0, 0, 0)

# Fassung des Umzugs-Rundgangs. Aendert sie sich, wird er allen erneut
# angeboten - auch denen, die den vorigen schon abgehakt haben.
# Hochgezaehlt am 16.08.2026: Der Rundgang erklaert jetzt auch die Sachen,
# die nach dem Umzug dazugekommen sind (Ersatzcodes, Zu-/Absagen,
# Erinnerungen). Wer den alten schon abgehakt hatte, bekommt ihn deshalb
# noch einmal angeboten - genau dafuer ist diese Zeile da.
# Hochgezaehlt am 18.08.2026: Das Dashboard gehoert jetzt auf den
# Startbildschirm, und der Push-Schritt verlangt nur noch das Dashboard
# statt beider Adressen.
FASSUNG = "2026-08-umzug-3"


def _push_zeilen(db, user) -> list:
    return (db.query(PushSubscription)
            .filter(PushSubscription.user_id == user.id).all())


def kalender_erledigt(user: User) -> bool:
    """Hat die Kalender-App die neue Adresse schon einmal abgeholt?"""
    zeitpunkt = getattr(user, "calendar_last_fetch", None)
    return bool(zeitpunkt and zeitpunkt >= UMZUG_AB)


def push_stand(db, user) -> dict:
    """Welche Ursprünge diese Person seit dem Umzug angemeldet hat.

    Bewusst ueber alle Geraete hinweg: Wer sein Handy angemeldet hat, hat den
    Punkt erledigt, auch wenn er gerade am Schulrechner sitzt. Die Frage "ist
    DIESES Geraet angemeldet" beantwortet `push_anmeldung.stand()` - die
    gehoert auf die Nachrichten-Seite, nicht in eine Umzugsliste.
    """
    # Ohne Datum gilt eine Zeile als alt. Andersherum waere der Fehler
    # teurer: Die Person bekaeme den Hinweis nie und wuerde sich wundern,
    # warum nichts mehr ankommt.
    zeilen = _push_zeilen(db, user)
    neu = [z for z in zeilen if z.created_at and z.created_at >= UMZUG_AB]
    alt = [z for z in zeilen if not (z.created_at and z.created_at >= UMZUG_AB)]
    arten = {z.ursprung for z in neu}
    # Verlangt wird nur das Dashboard. Frueher standen beide Ursprünge da,
    # und der Hinweis blieb stehen, bis jemand sich auch auf der oeffentlichen
    # Seite angemeldet hatte - obwohl von dort nie etwas kommt, was nicht auch
    # im Dashboard steht. Das war eine Aufgabe ohne Nutzen, und eine Liste,
    # die man nie leer bekommt, liest man irgendwann nicht mehr.
    # Nur das Dashboard - auf der oeffentlichen Seite gibt es seit dem
    # 19.08.2026 gar keine Anmeldung mehr. Bestehende Anmeldungen von dort
    # bleiben gueltig und stellen weiter zu: Eine Push-Adresse haengt am
    # Geraet, nicht an der Seite, die sie einmal erzeugt hat. Wegwerfen
    # wuerde nur denen schaden, die schon eingerichtet waren.
    noetig = ["dashboard"]
    return {
        "website": "website" in arten,
        "dashboard": "dashboard" in arten,
        "noetig": noetig,
        "fehlend": [a for a in noetig if a not in arten],
        "alte": alt,
    }


def als_app_erledigt(db, user) -> bool:
    """Hat diese Person das Dashboard schon einmal als App geoeffnet?

    Gemeldet wird das vom Browser selbst (siehe statisch/js/basis.js): Wer im
    App-Modus laeuft, sagt es einmal je Sitzung. Ein Zeitpunkt in der Zukunft
    kann dabei nicht entstehen, ein fehlender heisst schlicht "noch nie".
    """
    from kern.modelle import UserPreference
    vorlieben = db.query(UserPreference).filter(
        UserPreference.user_id == user.id).first()
    return bool(vorlieben and vorlieben.als_app_am)


def als_app_vermerken(db, user) -> bool:
    """Vermerkt den heutigen App-Start. True, wenn es der erste ueberhaupt war."""
    from kern.modelle import UserPreference
    from kern.text import utcnow
    vorlieben = db.query(UserPreference).filter(
        UserPreference.user_id == user.id).first()
    if not vorlieben:
        vorlieben = UserPreference(user_id=user.id)
        db.add(vorlieben)
    erstmals = not vorlieben.als_app_am
    vorlieben.als_app_am = utcnow()
    db.commit()
    return erstmals


def _kalender_abgewaehlt(db, user) -> bool:
    """Hat die Person gesagt, dass sie kein Termin-Abo will?

    Ohne diesen Ausweg stuende die Liste bei jemandem, der seine Termine
    lieber abschreibt, fuer immer da - und eine Aufforderung, die man nicht
    erfuellen kann, lernt man zu uebersehen. Dann uebersieht man auch die
    naechste.
    """
    from kern.modelle import UserPreference
    vorlieben = db.query(UserPreference).filter(
        UserPreference.user_id == user.id).first()
    return bool(vorlieben and vorlieben.umzug_ohne_kalender)


def _push_abgewaehlt(db, user) -> bool:
    """Wer Web-Push in seinen Einstellungen abgeschaltet hat, soll nicht
    aufgefordert werden, es anzumelden."""
    from kern.modelle import NotificationPreference
    pref = db.query(NotificationPreference).filter(
        NotificationPreference.user_id == user.id).first()
    if not pref:
        return False
    return not (pref.enabled and pref.webpush)


def offene_punkte(db, user) -> list:
    """Die noch offenen Handgriffe dieser Person - leer heisst: fertig.

    Jeder Punkt bringt mit, wohin er fuehrt, damit die Anzeige daraus einen
    Knopf machen kann, statt jemanden suchen zu lassen.
    """
    punkte = []
    # Zuerst der Startbildschirm - er ist die Voraussetzung fuer den naechsten
    # Punkt. Auf dem iPhone laesst Apple Push ueberhaupt erst zu, wenn die
    # Seite dort liegt; wer die Reihenfolge umdreht, drueckt zuerst auf einen
    # Knopf, der nicht funktionieren kann.
    if not als_app_erledigt(db, user):
        punkte.append({
            "schluessel": "startbildschirm",
            "titel": "Dashboard auf den Startbildschirm legen",
            "text": "Das Dashboard gehört als App auf dein Gerät – nicht als "
                    "Lesezeichen im Browser. Nur so kommen Benachrichtigungen "
                    "an (auf dem iPhone lässt Apple sie sonst gar nicht zu), "
                    "und es startet ohne Adressleiste direkt hier.",
            "bereich": None,
            "knopf": "So geht das",
            "rundgang": True,
        })
    if not kalender_erledigt(user) and not _kalender_abgewaehlt(db, user):
        punkte.append({
            "schluessel": "kalender",
            "titel": "Kalender neu eintragen",
            "text": "Die Adresse deines Termin-Abos hat sich geändert. Bis du "
                    "die neue einträgst, bekommt deine Kalender-App keine "
                    "Termine mehr.",
            "bereich": "kalender",
            "knopf": "Zum Kalender",
            "abwahl": "Ich nutze keinen Kalender",
        })
    stand = push_stand(db, user)
    if stand["fehlend"] and not _push_abgewaehlt(db, user):
        punkte.append({
            "schluessel": "push",
            "titel": "Benachrichtigungen anmelden",
            "text": "Damit dich Aufgaben, Treffen und Nachrichten auch dann "
                    "erreichen, wenn das Dashboard gerade nicht offen ist. "
                    "Einmal antippen, dann fragt dein Gerät.",
            "bereich": "nachrichten",
            "knopf": "Zu den Nachrichten",
        })
    return punkte


def stand_fuer(db, user) -> dict:
    """Alles zusammen - fuer die Uebersicht und den Rundgang."""
    punkte = offene_punkte(db, user)
    return {
        "offen": punkte,
        "fertig": not punkte,
        "kalender": kalender_erledigt(user),
        "push": push_stand(db, user),
        "als_app": als_app_erledigt(db, user),
    }
