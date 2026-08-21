"""Das Kalender-Abo ausliefern - von beiden Seiten aus.

Gemeldet: "Kalender nicht gefunden" in der Kalender-App. Der Abruf selbst
funktioniert (nachgemessen: 200, text/calendar, gueltige Datei) - aber er
haengt an genau einem Namen. Faellt der aus, ist er falsch abgeschrieben oder
kennt das Telefon ihn nicht, sieht man nur "nicht gefunden" und hat keine
Handhabe.

Deshalb liegt dieselbe Auslieferung jetzt auf BEIDEN Seiten: unter
mvlg-wag.de und unter app.mvlg-wag.de. Die Kennung in der Adresse entscheidet,
wer etwas zu sehen bekommt - dafuer ist kein Anmelden noetig, und die
oeffentliche Seite kann das genauso wie das Dashboard.

Alte Adressen bleiben gueltig, denn der Pfad ist auf beiden Seiten derselbe.
"""

from fastapi import APIRouter
from fastapi.responses import Response

from kern import kalender
from kern.datenbank import sitzung
from kern.modelle import User
from kern.text import utcnow

PFAD = "/dashboard/kalender/{token}.ics"

# Hoechstens einmal je Stunde vermerken, dass abgeholt wurde. Eine
# Kalender-App fragt alle paar Minuten nach.
VERMERK_ABSTAND = 3600


def ausliefern(token: str) -> Response:
    """Die persoenliche Kalenderdatei - oder eine verstaendliche Absage."""
    with sitzung() as db:
        person = db.query(User).filter(User.calendar_token == token).first()
        if not person or person.status != "aktiv":
            # Klartext statt "Nicht gefunden": Wer die Adresse im Browser
            # oeffnet, soll erfahren, woran es liegt. Die Kalender-App zeigt
            # den Text zwar nicht an, aber der Mensch daneben schon.
            return Response(
                "Zu dieser Adresse gibt es kein Kalender-Abo.\n\n"
                "Mögliche Gründe:\n"
                "- Die Adresse wurde nur teilweise kopiert.\n"
                "- Sie wurde im Dashboard neu erzeugt; dann gilt nur die neue.\n"
                "- Das Konto ist nicht mehr aktiv.\n\n"
                "Die gültige Adresse steht im Dashboard unter „Mein Konto“ "
                "oder unter „Kalender“.\n",
                status_code=404, media_type="text/plain; charset=utf-8")

        inhalt = kalender.als_ics(db, person)
        jetzt = utcnow()
        vorher = person.calendar_last_fetch
        if not vorher or (jetzt - vorher).total_seconds() > VERMERK_ABSTAND:
            person.calendar_last_fetch = jetzt
            db.commit()

    return Response(
        inhalt, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="ag-termine.ics"',
                 "Cache-Control": "private, max-age=900"})


def baue_router() -> APIRouter:
    """Denselben Weg fuer beide Anwendungen."""
    r = APIRouter()

    @r.get(PFAD, include_in_schema=False)
    def kalender_abo(token: str):
        return ausliefern(token)

    return r


def _einmal_abrufen(adresse: str) -> tuple:
    """(zustand, meldung) fuer genau eine Adresse.

    zustand: "gut", "kein_kalender", "unbekannt" (404) oder "unerreichbar".
    """
    import urllib.error
    import urllib.request
    anfrage = urllib.request.Request(
        adresse, headers={"User-Agent": "WAG-Dashboard Selbsttest"})
    try:
        antwort = urllib.request.urlopen(anfrage, timeout=12)
        roh = antwort.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as fehler:
        if fehler.code == 404:
            return "unbekannt", "404"
        return "unerreichbar", f"Antwort {fehler.code}"
    except Exception as fehler:
        return "unerreichbar", type(fehler).__name__

    art = (antwort.headers.get("content-type") or "").split(";")[0]
    if "calendar" not in art or "BEGIN:VCALENDAR" not in roh:
        return "kein_kalender", art or "unbekannter Typ"
    return "gut", str(roh.count("BEGIN:VEVENT"))


def _andere_adresse(adresse: str) -> str:
    """Dieselbe Datei unter dem jeweils anderen Namen - oder leer."""
    from kern import einstellungen as cfg
    for hier, dort in ((cfg.DASHBOARD_URL, cfg.WEBSITE_URL),
                       (cfg.WEBSITE_URL, cfg.DASHBOARD_URL)):
        if hier and dort and hier != dort and adresse.startswith(hier):
            return dort + adresse[len(hier):]
    return ""


def pruefe(adresse: str) -> tuple:
    """Holt die eigene Abo-Adresse ab, so wie eine Kalender-App es taete.

    (gut, Meldung). Gedacht fuer den Knopf im Dashboard: "Bei mir steht
    Kalender nicht gefunden" liess sich vorher von niemandem nachpruefen -
    man wusste nicht einmal, ob die Adresse von aussen ueberhaupt erreichbar
    ist. Die Anfrage geht denselben Weg wie die des Telefons: ueber das
    offene Netz, nicht ueber die Hintertuer.
    """
    zustand, angabe = _einmal_abrufen(adresse)
    if zustand == "gut":
        termine = int(angabe)
        if not termine:
            return True, ("Die Adresse funktioniert. Es stehen nur gerade "
                          "keine Termine drin - manche Kalender-Apps zeigen "
                          "ein leeres Abo gar nicht erst an, das ist kein "
                          "Fehler.")
        return True, (f"Die Adresse funktioniert: {termine} Termin"
                      f"{'e' if termine != 1 else ''} werden ausgeliefert.")

    # Nicht gleich die Kennung verdaechtigen: Vielleicht antwortet nur dieser
    # eine Name nicht. Genau das war der Fall, als unter dem Hauptnamen noch
    # die alte Fassung lief - dieselbe Kennung lieferte dort 404 und unter
    # dem anderen Namen die Datei. Das darf keine Fehlersuche nach einem
    # falsch kopierten Zeichen ausloesen.
    zweite = _andere_adresse(adresse)
    if zweite:
        zustand2, angabe2 = _einmal_abrufen(zweite)
        if zustand2 == "gut":
            return False, (
                f"Unter dieser Adresse antwortet der Server nicht "
                f"({'404' if zustand == 'unbekannt' else angabe}), unter "
                f"{zweite.split('/dashboard')[0]} aber schon. Deine Kennung "
                "ist also in Ordnung - nimm vorerst die andere Adresse. "
                "Sobald überall dieselbe Fassung läuft, funktionieren beide.")

    if zustand == "unbekannt":
        return False, ("Der Server kennt diese Adresse nicht (404). Meist ist "
                       "sie nur halb kopiert oder wurde neu erzeugt - dann "
                       "gilt nur die neue.")
    if zustand == "kein_kalender":
        return False, (f"Es kommt zwar etwas zurück, aber kein Kalender "
                       f"(„{angabe}“). Kalender-Apps lehnen das ab.")
    return False, (f"Die Adresse ist von außen nicht erreichbar ({angabe}). "
                   "Läuft der Tunnel?")
