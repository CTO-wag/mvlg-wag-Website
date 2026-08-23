"""Hintergrundlaeufe: Sicherungen, Erinnerungen, Scoring, Aufraeumen.

Alle laufen als Faeden im Dashboard-Prozess. Bewusst nur dort: liefe dasselbe
in beiden Prozessen, gaebe es jede Sicherung doppelt und jede Erinnerung
zweimal - und zwar so, dass es niemandem auffiele, ausser den Leuten, die
morgens zwei identische Push-Meldungen bekommen.

Jeder Lauf faengt seine Fehler selbst ab. Ein gescheiterter Sicherungslauf
darf nicht den Faden beenden, sonst laeuft er bis zum naechsten Neustart
ueberhaupt nicht mehr - genau so stand die Plattform in V1 einmal dreizehn
Stunden ohne Sicherung da.
"""

import threading
import time
from datetime import datetime, timedelta

from kern import einstellungen as cfg
from kern.text import BERLIN_TZ


def _sekunden_bis(stunde: int) -> float:
    """Wartezeit bis zur naechsten vollen Stunde X deutscher Zeit."""
    jetzt = datetime.now(BERLIN_TZ)
    ziel = jetzt.replace(hour=stunde, minute=0, second=0, microsecond=0)
    if ziel <= jetzt:
        ziel += timedelta(days=1)
    return max(60.0, (ziel - jetzt).total_seconds())


def _faden(name: str, arbeit) -> None:
    threading.Thread(target=arbeit, daemon=True, name=name).start()


def _sicherungen():
    from kern.sicherung import erstelle
    from kern import stoerung
    # Beim Start eine anlegen, danach im eingestellten Abstand. Die erste
    # sofort, weil ein Rechner, der nur abends laeuft, sonst nie eine bekaeme.
    while True:
        try:
            pfad = erstelle()
            if pfad:
                print(f"[Sicherung] {pfad}")
            # Lief es wieder, nachdem es einmal nicht lief? Dann Entwarnung.
            stoerung.entwarnung(
                "sicherung", "Sicherungen laufen wieder",
                "Die Datenbank wird wieder regelmäßig gesichert.")
        except Exception as problem:
            print(f"[Sicherung] fehlgeschlagen: {problem}")
            # Eine Anlage ohne Sicherung merkt man erst, wenn man sie
            # braucht. Deshalb geht das an den Vorstand, nicht nur ins
            # Konsolenfenster.
            stoerung.melde(
                "sicherung", "Sicherung fehlgeschlagen",
                f"Die Datenbank konnte nicht gesichert werden: {problem}. "
                "Bis das behoben ist, gibt es keine neuen Sicherungen.")
        time.sleep(cfg.BACKUP_INTERVAL_HOURS * 3600)


def _erinnerungen():
    from kern.aufgaben import erinnerungen_verschicken
    from kern import hinweise
    while True:
        time.sleep(_sekunden_bis(cfg.REMINDER_HOUR_LOCAL))
        try:
            anzahl = erinnerungen_verschicken()
            if anzahl:
                print(f"[Erinnerung] {anzahl} Hinweis(e) zu Aufgaben.")
        except Exception as problem:                         # pragma: no cover
            print(f"[Erinnerung] Aufgaben fehlgeschlagen: {problem}")
        # Getrennt abgesichert: Faellt eines aus, laufen die anderen weiter.
        try:
            bilanz = hinweise.alle()
            if any(bilanz.values()):
                print(f"[Erinnerung] {bilanz}")
        except Exception as problem:                         # pragma: no cover
            print(f"[Erinnerung] Treffen/Termine/Bewerbungen: {problem}")


def _scoring():
    from kern.leistung import alle_neu_rechnen, treffen_abrechnen

    # Beim Start nicht bis zum naechsten Tageslauf warten. So sind die
    # Leadership-Werte nach einem Neustart sofort aktuell.
    try:
        anzahl = alle_neu_rechnen()
        print(f"[Leistung] Werte beim Start fuer {anzahl} Konten berechnet.")
    except Exception as problem:                         # pragma: no cover
        print(f"[Leistung] Startberechnung fehlgeschlagen: {problem}")

    while True:
        time.sleep(_sekunden_bis(cfg.SCORING_HOUR_LOCAL))
        # Erst abrechnen, dann rechnen: Aus einer Zusage wird nach dem
        # Treffen entweder ein gehaltenes Wort oder nichts, und das soll in
        # denselben Werten stehen, die gleich danach neu gebildet werden.
        try:
            treffen = treffen_abrechnen()
            if treffen:
                print(f"[Leistung] {treffen} Treffen abgerechnet "
                      "(Zusagen gegen Anwesenheit).")
        except Exception as problem:                         # pragma: no cover
            print(f"[Leistung] Treffen-Abrechnung fehlgeschlagen: {problem}")
        try:
            anzahl = alle_neu_rechnen()
            print(f"[Leistung] Werte für {anzahl} Konten neu berechnet.")
        except Exception as problem:                         # pragma: no cover
            print(f"[Leistung] Neuberechnung fehlgeschlagen: {problem}")


def _taegliches_aufraeumen():
    from kern.aufbewahrung import bewerbungen_aufraeumen
    from kern.papierkorb import aufraeumen as papierkorb_aufraeumen
    from kern.protokoll import aufraeumen as protokoll_aufraeumen
    while True:
        time.sleep(_sekunden_bis(4))
        try:
            entfernt = papierkorb_aufraeumen()
            if entfernt:
                print(f"[Papierkorb] {entfernt} Eintrag/Einträge endgültig entfernt.")
            bilanz = protokoll_aufraeumen()
            if bilanz:
                print(f"[Protokoll] aufgeräumt: {bilanz}")
        except Exception as problem:                         # pragma: no cover
            print(f"[Aufräumen] fehlgeschlagen: {problem}")
        # Getrennt abgesichert: Eine Loeschfrist darf nicht ausfallen, nur
        # weil der Papierkorb hakt.
        try:
            weg = bewerbungen_aufraeumen()
            if weg:
                print(f"[Aufbewahrung] Bewerbungen gelöscht: {weg}")
        except Exception as problem:                         # pragma: no cover
            print(f"[Aufbewahrung] fehlgeschlagen: {problem}")


def _whatsapp():
    from kern.whatsapp import einsatzbereit, korb_abarbeiten, modus
    from kern import stoerung
    if modus() == "manuell":
        return          # nichts zu verschicken, der Korb wartet auf Klicks
    while True:
        time.sleep(300)
        try:
            korb_abarbeiten()
        except Exception as problem:                         # pragma: no cover
            print(f"[WhatsApp] Korb fehlgeschlagen: {problem}")
        # Verliert der Beiwagen die Kopplung, bleiben die Willkommens-
        # nachrichten still im Korb liegen. Fruehestens beim naechsten
        # Neuzugang faellt das auf - und dann hat er schon gewartet.
        try:
            bereit, meldung = einsatzbereit()
            if bereit:
                stoerung.entwarnung(
                    "whatsapp", "WhatsApp-Bot ist wieder verbunden", meldung)
            elif "geprüft" not in meldung and "startet" not in meldung:
                stoerung.melde(
                    "whatsapp", "WhatsApp-Bot nicht einsatzbereit",
                    f"{meldung} Neue Mitglieder bekommen so lange keine "
                    "Begrüßung. Im Dashboard unter „WhatsApp-Bot“ neu koppeln.")
        except Exception as problem:                         # pragma: no cover
            print(f"[WhatsApp] Zustand nicht prüfbar: {problem}")


def _kasse():
    from kern.kasse import dauerauftraege_ausfuehren
    from kern.datenbank import sitzung
    while True:
        time.sleep(_sekunden_bis(5))
        try:
            with sitzung() as db:
                anzahl = dauerauftraege_ausfuehren(db)
                db.commit()
            if anzahl:
                print(f"[Kasse] {anzahl} wiederkehrende Buchung(en) angelegt.")
        except Exception as problem:                         # pragma: no cover
            print(f"[Kasse] Daueraufträge fehlgeschlagen: {problem}")


def _ausfallmeldungen():
    """Was gemeldet wurde, waehrend die Plattform aus war, hereinholen.

    Der erste Lauf kommt gleich beim Start und nicht erst nach dem Abstand: Der
    haeufigste Fall ist genau dieser - der Rechner war aus, jemand hat es
    gemeldet, und jetzt laeuft es wieder. Das Ticket soll dann schon da sein,
    bevor jemand nachfragt, warum niemand reagiert.
    """
    from kern import ausfallmeldungen
    zuerst = True
    while True:
        if not zuerst:
            time.sleep(max(60, cfg.AUSFALL_ABHOLUNG_MINUTEN * 60))
        zuerst = False
        try:
            bilanz = ausfallmeldungen.abholen()
            if bilanz["neu"]:
                print(f"[Ausfallmeldungen] {bilanz['neu']} neue(s) Ticket(s) "
                      f"aus der Zeit ohne Verbindung angelegt.")
            if bilanz.get("bewerbungen"):
                print(f"[Ausfallmeldungen] {bilanz['bewerbungen']} Bewerbung(en) "
                      f"aus der Ausfallzeit eingetragen.")
            if bilanz["fehler"]:
                print(f"[Ausfallmeldungen] {bilanz['fehler']}")
        except Exception as problem:                         # pragma: no cover
            print(f"[Ausfallmeldungen] fehlgeschlagen: {problem}")


def alles_starten() -> None:
    """Vom Dashboard-Prozess aufzurufen."""
    if cfg.BACKUPS_ENABLED:
        _faden("sicherungen", _sicherungen)
        print(f"  Sicherungen  : alle {cfg.BACKUP_INTERVAL_HOURS} h, "
              f"{cfg.BACKUP_KEEP} werden aufbewahrt")
    if cfg.REMINDERS_ENABLED:
        _faden("erinnerungen", _erinnerungen)
        print(f"  Erinnerungen : täglich ab {cfg.REMINDER_HOUR_LOCAL}:00 Uhr")
    _faden("scoring", _scoring)
    print(f"  Leistung     : täglich {cfg.SCORING_HOUR_LOCAL}:00 Uhr, "
          "sonst laufend bei jedem Ereignis")
    _faden("aufraeumen", _taegliches_aufraeumen)
    _faden("whatsapp", _whatsapp)
    _faden("kasse", _kasse)
    from kern import ausfallmeldungen
    if ausfallmeldungen.eingerichtet():
        _faden("ausfallmeldungen", _ausfallmeldungen)
        print(f"  Auffangnetz  : Meldungen alle "
              f"{cfg.AUSFALL_ABHOLUNG_MINUTEN} min abholen")

    # Faellige wiederkehrende Buchungen sofort nachholen: war der Rechner drei
    # Wochen aus, soll die Kasse beim Einschalten stimmen und nicht erst am
    # naechsten Morgen.
    try:
        from kern.datenbank import sitzung
        from kern.kasse import dauerauftraege_ausfuehren
        with sitzung() as db:
            nachgeholt = dauerauftraege_ausfuehren(db)
            db.commit()
        if nachgeholt:
            print(f"  Kasse        : {nachgeholt} Buchung(en) nachgeholt")
    except Exception as problem:                             # pragma: no cover
        print(f"  Kasse        : Daueraufträge übersprungen ({problem})")


def nur_aufraeumen_starten() -> None:
    """Fuer den Website-Prozess: nichts, was doppelt laufen darf."""
    return
