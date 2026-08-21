"""Der Rundgang durch das, was sich geaendert hat - und die Liste dessen, was
jede Person noch selbst einrichten muss (siehe kern/umzug.py).
"""

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from dashboard.hilfen import Anmeldung
from kern import benachrichtigung, kalender, umzug
from kern import einstellungen as cfg
from kern.modelle import UserPreference
from kern.rechte import rechte_von
from kern.sicherheit import ersatzcodes_offen

router = APIRouter(prefix="/dashboard")

# Wie oft jemand die Einladung hoechstens zu sehen bekommt.
MAX_FRAGEN = 3


#  Stand je Person
def _stand(db, user) -> UserPreference:
    vorlieben = db.query(UserPreference).filter(
        UserPreference.user_id == user.id).first()
    if not vorlieben:
        vorlieben = UserPreference(user_id=user.id)
        db.add(vorlieben)
        db.commit()
    if (vorlieben.neuerungen_version or "") != umzug.FASSUNG:
        vorlieben.neuerungen_erledigt = 0
        vorlieben.neuerungen_gefragt = 0
        vorlieben.neuerungen_version = umzug.FASSUNG
        db.commit()
    return vorlieben


def faellig(db, user) -> bool:
    """Soll die Einladung erscheinen?

    Nicht fuer jemanden, der den ersten Rundgang noch vor sich hat - zwei
    Einladungen uebereinander sind eine zu viel. Der Zaehler steigt erst,
    wenn wirklich eingeladen wird; ein Seitenaufruf ohne sichtbare Einladung
    verbraucht keine Frage.
    """
    from dashboard.routen.konto import MAX_FRAGEN as ERST_MAX
    vorlieben = _stand(db, user)
    if vorlieben.neuerungen_erledigt:
        return False
    erst_offen = (not vorlieben.tutorial_erledigt
                  and (vorlieben.tutorial_gefragt or 0) < ERST_MAX)
    if erst_offen:
        return False
    if (vorlieben.neuerungen_gefragt or 0) >= MAX_FRAGEN:
        return False
    vorlieben.neuerungen_gefragt = (vorlieben.neuerungen_gefragt or 0) + 1
    db.commit()
    return True


@router.post("/neuerungen/gesehen")
def gesehen(erledigt: str = Form(""), csrf: str = Form(""),
            a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    vorlieben = _stand(a.db, a.user)
    if erledigt:
        vorlieben.neuerungen_erledigt = 1
        vorlieben.neuerungen_version = umzug.FASSUNG
    a.db.commit()
    return PlainTextResponse("ok")


@router.post("/neuerungen/ohne-kalender")
def ohne_kalender(csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Den Kalender-Punkt abwaehlen.

    Kein Haken auf "erledigt": Das waere eine Falschaussage, sobald jemand
    ihn zu frueh setzt. Hier steht ausdruecklich etwas anderes drin - diese
    Person will kein Termin-Abo. Rueckgaengig geht es im Bereich Kalender,
    sobald das Abo doch einmal abgeholt wird.
    """
    a.pruefe_csrf(csrf)
    vorlieben = _stand(a.db, a.user)
    vorlieben.umzug_ohne_kalender = 1
    a.db.commit()
    from dashboard.routen.uebersicht import uebersicht
    return uebersicht(a)


@router.post("/als-app")
def als_app_melden(csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Der Browser meldet: Diese Seite laeuft gerade als App.

    Kein Formular dahinter, sondern eine Feststellung des Geraets - deshalb
    auch keine Antwortseite, sondern 204. Der Aufruf kommt einmal je Sitzung
    (siehe statisch/js/basis.js); haeufiger waere er sinnlos, seltener wuerde
    man das Umziehen auf ein neues Geraet nicht mitbekommen.
    """
    a.pruefe_csrf(csrf)
    umzug.als_app_vermerken(a.db, a.user)
    return Response(status_code=204)


@router.post("/hinweis/passwort-behalten")
def passwort_behalten(csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Den Hinweis auf das Startpasswort abstellen.

    Der Hinweis ist ein Rat, keine Vorschrift: Wer sein Passwort behalten
    will, darf das. Er verschwindet ohnehin, sobald das Passwort einmal
    geaendert wird - hier verschwindet er auch ohne das. Sonst liest man ihn
    nach dem dritten Mal nicht mehr, und damit auch keinen anderen Hinweis an
    dieser Stelle.
    """
    a.pruefe_csrf(csrf)
    vorlieben = _stand(a.db, a.user)
    vorlieben.startpasswort_egal = 1
    a.db.commit()
    from dashboard.routen.uebersicht import uebersicht
    return uebersicht(a)


#  Die Schritte
@router.get("/neuerungen")
def schritte_holen(a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Die Schritte als JSON. Bausteine wie beim Rundgang (`konto.py`)."""
    db, user = a.db, a.user
    r = rechte_von(user, db)
    pref = benachrichtigung.einstellung(db, user.id)
    stand = umzug.stand_fuer(db, user)
    website, dashboard = cfg.adressen_fuer(a.request)
    schritte = []

    def schritt(titel, teile, bereich=None, ziel=None):
        schritte.append({"titel": titel, "teile": teile,
                         "bereich": bereich, "ziel": ziel})

    def absatz(*stuecke):
        return {"art": "absatz", "teile": [
            s if isinstance(s, dict) else {"t": s} for s in stuecke]}

    # --- 1. Warum das hier aufgeht ---------------------------------------
    # Die Zahl kommt aus der Liste, nicht aus einer Annahme: Frueher stand
    # hier fest "zwei Handgriffe" fuer alles ausser null und eins. Als ein
    # dritter Punkt dazukam, log der Satz - und wer merkt, dass ihm die Anlage
    # etwas Falsches erzaehlt, glaubt ihr auch beim naechsten Satz nicht mehr.
    offen = len(stand["offen"])
    if offen == 0:
        lage = ("Bei dir ist schon alles eingerichtet - App, Kalender und "
                "Benachrichtigungen laufen. Hier steht trotzdem kurz, was "
                "sich geändert hat.")
    elif offen == 1:
        lage = ("Ein Handgriff fehlt bei dir noch. Er dauert keine Minute, "
                "und ohne ihn bekommst du etwas nicht mehr mit.")
    else:
        worte = {2: "Zwei", 3: "Drei", 4: "Vier"}.get(offen, str(offen))
        lage = (f"{worte} Handgriffe fehlen bei dir noch. Zusammen dauern sie "
                "keine zwei Minuten - und ohne sie bekommst du Termine und "
                "Meldungen nicht mehr mit.")
    schritt("Es hat sich etwas geändert, " + user.vorname, [
        absatz("Die Plattform ist umgezogen und hat seitdem einiges dazu "
               "bekommen. Zuerst der Umzug: Es gibt jetzt zwei Adressen, die "
               "öffentliche Seite und das Dashboard."),
        absatz(lage),
        absatz("Du kannst jederzeit abbrechen - unter „Support“ lässt sich "
               "das hier neu starten."),
    ])

    # --- 2. Die neuen Adressen -------------------------------------------
    schritt("Die zwei neuen Adressen", [
        absatz({"t": "Öffentliche Seite", "stark": True},
               " - Startseite, Bewerbung, Anmeldung:"),
        {"art": "kopieren", "wert": website},
        absatz({"t": "Dashboard", "stark": True},
               " - alles, was du hier gerade siehst:"),
        {"art": "kopieren", "wert": dashboard},
        absatz("Alte Lesezeichen funktionieren weiter, führen aber über eine "
               "Weiterleitung. Einmal neu setzen spart den Umweg."),
    ])

    # --- 2b. Das Dashboard als App ---------------------------------------
    #  Steht bewusst VOR Kalender und Push: Auf dem iPhone laesst Apple Push
    #  ueberhaupt erst zu, wenn die Seite auf dem Startbildschirm liegt. Wer
    #  die Schritte in der anderen Reihenfolge abarbeitet, drueckt zuerst auf
    #  einen Knopf, der bei ihm gar nicht funktionieren kann - und haelt das
    #  dann fuer einen Fehler der Anlage.
    teile = [
        absatz("Das Dashboard gehört als App auf dein Gerät, nicht als "
               "Lesezeichen. Es startet dann ohne Adressleiste direkt hier - "
               "und, wichtiger: Benachrichtigungen kommen überhaupt nur so an."),
    ]
    if stand["als_app"]:
        teile.append({"art": "hinweis",
                      "text": "Bei dir ist das erledigt - du hast das "
                              "Dashboard schon als App geöffnet."})
    teile += [
        {"art": "hinweis",
         "text": "Auf dem iPhone und iPad",
         "titel": "So geht das",
         "schritte": ["Diese Adresse in Safari öffnen (nicht Chrome - dort "
                      "fehlt der Punkt)",
                      "Das Teilen-Symbol antippen: Quadrat mit Pfeil nach oben",
                      "Nach unten wischen, „Zum Home-Bildschirm“ wählen",
                      "Ab jetzt immer über dieses Symbol öffnen"]},
        {"art": "hinweis",
         "text": "Auf Android",
         "titel": "So geht das",
         "schritte": ["Diese Adresse in Chrome öffnen",
                      "Die drei Punkte oben rechts antippen",
                      "„App installieren“ oder „Zum Startbildschirm zufügen“",
                      "Ab jetzt immer über dieses Symbol öffnen"]},
        {"art": "hinweis",
         "text": "Am Rechner",
         "titel": "So geht das",
         "schritte": ["In Chrome oder Edge rechts in der Adresszeile auf das "
                      "Installieren-Symbol klicken",
                      "Bestätigen - das Dashboard bekommt ein eigenes Fenster",
                      "Am Mac in Safari: Ablage, „Zum Dock hinzufügen“"]},
        {"art": "kopieren", "wert": dashboard},
        absatz("Deine Daten bleiben dabei, wie sie sind - es ist dieselbe "
               "Seite, nur ohne Browser drumherum. Nichts wird heruntergeladen "
               "und nichts neu eingerichtet."),
    ]
    schritt("Leg das Dashboard auf deinen Startbildschirm", teile)

    # --- 3. Kalender ------------------------------------------------------
    teile = [
        absatz("Deine persönliche Termin-Adresse hat sich geändert. Die alte "
               "holt nichts mehr ab, und zwar ohne Fehlermeldung: Die Termine "
               "im Handy bleiben einfach stehen. Man merkt es erst, wenn man "
               "einen verpasst hat."),
    ]
    if stand["kalender"]:
        teile.append({"art": "hinweis",
                      "text": "Bei dir ist das erledigt - deine Kalender-App "
                              "hat die neue Adresse abgeholt."})
    else:
        teile.append({
            "art": "hinweis",
            "text": "Bei dir steht das noch aus.",
            "titel": "So geht das",
            "schritte": [
                "In der Kalender-App das alte AG-Abo löschen - sonst stehen "
                "die Termine später doppelt",
                "Die Adresse unten kopieren",
                "Neues Abo „per Adresse/URL“ anlegen und einfügen",
                "Fertig - neue Termine kommen ab dann von selbst"]})
    teile += [
        {"art": "kopieren", "wert": kalender.abo_adresse(db, user)},
        {"art": "geraete", "namen": ["iPhone", "Android", "Rechner"]},
        absatz("Die Adresse ist persönlich - du siehst nur, was dich "
               "betrifft. Nicht weitergeben."),
    ]
    schritt("Dein Kalender muss neu eingetragen werden", teile,
            bereich="kalender", ziel='.leisten-punkt[data-bereich="kalender"]')

    # --- 4. Benachrichtigungen -------------------------------------------
    push = stand["push"]
    teile = [
        absatz("Aufgaben, Treffen und Nachrichten erreichen dich damit auch "
               "dann, wenn das Dashboard gerade nicht offen ist. Angemeldet "
               "wird hier im Dashboard, unter „Nachrichten“ - ein Knopf, "
               "danach fragt dein Gerät einmal."),
        {"art": "hinweis",
         "text": "Bei dir ist das erledigt." if push["dashboard"] else
                 "Bei dir steht das noch aus - unter „Nachrichten“, "
                 "„Dieses Gerät anmelden“."},
    ]
    teile.append(absatz(
        "Angemeldet wird nur noch hier. Auf der öffentlichen Seite gab es "
        "denselben Knopf früher ein zweites Mal - das hat mehr verwirrt, als "
        "es genützt hat, und ist weg."))
    if push["alte"]:
        teile.append(absatz(
            "Du hast " + str(len(push["alte"])) + " ältere Anmeldung(en) von "
            "vor dem Umzug. Die bleiben bestehen, es geht nichts verloren - "
            "ob sie noch zustellen, hängt am alten Namen. Deshalb einmal neu."))
    teile += [
        absatz("Voraussetzung ist der Schritt davor: Solange das Dashboard "
               "nicht als App auf dem Startbildschirm liegt, lässt Apple "
               "Benachrichtigungen auf dem iPhone gar nicht erst zu."),
        absatz({"t": "Ohne App-Store geht auch ntfy:", "stark": True},
               " kostenlose App, dann dieses Thema abonnieren:"),
        {"art": "kopieren", "wert": pref.topic},
        absatz("Das Thema ist geheim - wer es kennt, liest mit."),
    ]
    schritt("Benachrichtigungen neu anmelden", teile, bereich="nachrichten",
            ziel='.leisten-punkt[data-bereich="nachrichten"]')

    # --- 4b. Zweiter Faktor ohne Ersatzcodes ------------------------------
    #  Nur fuer die, die ihn vor dieser Aenderung eingeschaltet haben: Ihre
    #  Codes gibt es noch nicht, und ohne sie ist ein verlorenes Handy ein
    #  verlorenes Konto. Wer keinen zweiten Faktor hat, liest hier nichts.
    if user.totp_aktiv and ersatzcodes_offen(user.totp_ersatzcodes) == 0:
        schritt("Hol dir Ersatzcodes für den zweiten Faktor", [
            absatz("Du hast den zweiten Faktor an - gut. Bisher gab es dazu "
                   "aber keinen Rückweg: Handy weg hieß Konto weg."),
            absatz("Ab jetzt gibt es acht Ersatzcodes, jeder gilt einmal "
                   "statt des Codes aus der App. Deine musst du dir einmal "
                   "abholen, weil es sie beim Einschalten noch nicht gab."),
            {"art": "hinweis",
             "text": "Unter „Mein Konto“ → Zweiter Faktor → Neue Ersatzcodes "
                     "erzeugen. Aufschreiben, dann sind sie sicher.",
             "titel": "Und wenn auch die weg sind?",
             "schritte": ["Der Vorstand kann den zweiten Faktor zurücksetzen",
                          "Danach kommst du mit Passwort allein wieder hinein",
                          "Und richtest ihn neu ein"]},
        ], ziel="#dash-ich")

    # --- 5. Was sonst neu ist --------------------------------------------
    #  Nur, was diese Rolle auch sieht. Ein Mitglied ohne Kassenrecht braucht
    #  nichts ueber Budgets zu lesen.
    # Zuerst das, was jeder merkt und jeder benutzt. Die Reihenfolge ist
    # nicht zufaellig: Wer nach drei Punkten aufhoert zu lesen, hat die
    # wichtigsten gelesen.
    neues = [
        {"titel": "AG-Treffen:",
         "text": "vorher zusagen oder absagen, und Punkte für die "
                 "Tagesordnung eintragen - im Treffen werden sie abgehakt"},
        {"titel": "Erinnerungen:",
         "text": "an Treffen und Termine meldet sich die Anlage jetzt von "
                 "selbst, am Tag davor und am Tag selbst"},
        {"titel": "Suche in jeder Liste:",
         "text": "oben in Aufgaben, Personen, Projekten - tippen genügt"},
        {"titel": "Papierkorb:",
         "text": "Gelöschtes lässt sich zurückholen, nichts ist sofort weg"},
        {"titel": "Hell und dunkel:",
         "text": "der Schalter oben rechts, deine Wahl bleibt gespeichert"},
        {"titel": "Eingaben bleiben stehen:",
         "text": "auch bei einer Fehlermeldung oder abgelaufenen Sitzung"},
        {"titel": "Zweiter Faktor:",
         "text": "wer ihn einschaltet, bekommt acht Ersatzcodes für den Fall, "
                 "dass das Handy weg ist"},
        {"titel": "Ruhezeiten sind weg:",
         "text": "die Felder für „nachts nichts“ gibt es nicht mehr - was du "
                 "nicht bekommen willst, schaltest du je Art einzeln ab"},
    ]
    if r.get("aufgaben_verwalten"):
        neues.append({"titel": "Aufgaben:",
                      "text": "entweder an eine Person oder an eine Abteilung, "
                              "nicht mehr beides gleichzeitig"})
    if r.get("finanzen"):
        neues.append({"titel": "Kassenbuch:",
                      "text": "Budgets je Abteilung und Daueraufträge für "
                              "wiederkehrende Buchungen"})
    if r.get("leadership"):
        neues.append({"titel": "Leadership:",
                      "text": "rechnet sich von selbst; Erledigtes zählt auch "
                              "dann, wenn die Aufgabe später gelöscht wird"})
    if r.get("bewerbungen"):
        neues.append({"titel": "Bewerbungen:",
                      "text": "Sterne und Begründung je Person - und wer drei "
                              "Tage unbeantwortet liegt, meldet sich von selbst"})
    # Nur fuer die, die die Anlage am Laufen halten.
    if r.get("datenbank"):
        neues.append({"titel": "Sicherungen:",
                      "text": "lassen sich jetzt auch wieder einspielen, nicht "
                              "nur herunterladen"})
    if r.get("accounts_all"):
        neues.append({"titel": "Zweiter Faktor zurücksetzen:",
                      "text": "unter Konten, falls jemand Handy und "
                              "Ersatzcodes verloren hat"})
    if r.get("sicherheit") or user.role == "cto":
        neues.append({"titel": "Störungen melden sich:",
                      "text": "scheitert eine Sicherung oder verliert der "
                              "WhatsApp-Bot die Kopplung, bekommt der Vorstand "
                              "eine Nachricht statt einer Zeile im Fenster"})
    schritt("Was sonst neu ist", [
        absatz("Kurz der Rest - nichts davon musst du einrichten:"),
        {"art": "liste", "punkte": neues},
    ])

    # --- 6. Schluss -------------------------------------------------------
    schluss = [absatz("Das war es schon.")]
    if stand["offen"]:
        schluss.append(absatz(
            "Was bei dir noch offen ist, steht oben auf der Übersicht, "
            "bis es erledigt ist. Du kannst es also auch später machen."))
    schluss.append(absatz("Wenn etwas nicht klappt: unter „Support“ fragen. "
                          "Dort lässt sich das hier auch neu starten."))
    schritt("Fertig", schluss)

    return JSONResponse(schritte)
