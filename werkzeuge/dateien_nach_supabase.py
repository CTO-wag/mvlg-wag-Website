"""Hochgeladene Dateien vom Datenordner in den Supabase-Storage bringen.

    python werkzeuge/dateien_nach_supabase.py --pruefen
    python werkzeuge/dateien_nach_supabase.py --umziehen
    python werkzeuge/dateien_nach_supabase.py --aufraeumen

--pruefen    verbindet sich, zaehlt beide Seiten und aendert nichts.
--umziehen   legt den Bucket an (falls noetig) und laedt alles hinauf.
--aufraeumen loescht die oertlichen Kopien - aber nur die, die nachweislich
             im Bucket liegen und dort dieselbe Groesse haben.

Der Umzug laesst die Dateien im Datenordner zunaechst liegen. Das ist Absicht:
Solange sie dort sind, zeigt die Anwendung sie von der Platte, und ein
Fehlschlag beim Hochladen faellt niemandem auf die Fuesse. Erst
--aufraeumen macht den Schritt endgueltig.

Die Namen in der Datenbank aendern sich nicht. Dort steht nur der Dateiname;
wo die Datei liegt, entscheidet kern/speicher.py.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _vorbereiten():
    """config.cmd einlesen, BEVOR kern.einstellungen die Umgebung liest."""
    from server import _config_einlesen
    quelle = _config_einlesen()
    if quelle:
        print(f"Konfiguration: {quelle}")
    from kern import einstellungen as cfg
    from kern import speicher
    return cfg, speicher


def _lage(speicher) -> dict:
    """Was wo liegt - je Bereich."""
    befund = {}
    for bereich in (speicher.SUPPORT, speicher.REDAKTION):
        oertlich = speicher.auf_platte(bereich)
        im_bucket = speicher.liste(bereich)
        befund[bereich] = {
            "ordner": speicher.ORDNER[bereich],
            "oertlich": oertlich,
            "im_bucket": im_bucket,
            "fehlt_oben": [n for n in oertlich if n not in im_bucket],
        }
    return befund


def _erwartet(speicher) -> dict:
    """Welche Dateinamen die Datenbank ueberhaupt erwartet.

    Damit der Bericht die eine Frage beantwortet, auf die es ankommt: Gibt es
    einen Verweis, hinter dem weder oben noch unten etwas liegt? Solche
    Verweise sind nicht neu - sie fallen nur jetzt zum ersten Mal auf.
    """
    from kern.datenbank import sitzung
    from kern.modelle import ContentAttachment, SupportMessage, SupportTicket

    erwartet = {speicher.SUPPORT: set(), speicher.REDAKTION: set()}
    with sitzung() as db:
        for modell in (SupportTicket, SupportMessage):
            for (name,) in db.query(modell.attachment_filename).filter(
                    modell.attachment_filename.isnot(None)).all():
                if name:
                    erwartet[speicher.SUPPORT].add(name)
        for (name,) in db.query(ContentAttachment.speichername).all():
            if name:
                erwartet[speicher.REDAKTION].add(name)
    return erwartet


def bericht(cfg, speicher) -> int:
    print(f"Storage      : {cfg.SUPABASE_URL}")
    print(f"Bucket       : {cfg.SUPABASE_BUCKET}")
    befund = _lage(speicher)
    erwartet = _erwartet(speicher)
    verloren = 0
    for bereich, stand in befund.items():
        print(f"\n{bereich}")
        print(f"   Ordner        : {stand['ordner']}")
        print(f"   auf der Platte: {len(stand['oertlich'])}")
        print(f"   im Bucket     : {len(stand['im_bucket'])}")
        print(f"   noch zu laden : {len(stand['fehlt_oben'])}")
        nirgends = sorted(erwartet[bereich]
                          - set(stand["oertlich"]) - stand["im_bucket"])
        if nirgends:
            verloren += len(nirgends)
            print(f"   OHNE DATEI    : {len(nirgends)} Verweis(e) in der "
                  "Datenbank zeigen ins Leere:")
            for name in nirgends[:10]:
                print(f"      {name}")
            if len(nirgends) > 10:
                print(f"      ... und {len(nirgends) - 10} weitere")
    if verloren:
        print("\nDie Dateien ohne Verweis sind vor diesem Umzug "
              "verlorengegangen -")
        print("sie liegen weder im Datenordner noch im Bucket. Hier ist "
              "nichts zu retten;")
        print("der Umzug sorgt dafuer, dass es kuenftig nicht mehr passiert.")
    return 0


def hochladen(cfg, speicher) -> int:
    if speicher.bucket_anlegen():
        print(f"Bucket „{cfg.SUPABASE_BUCKET}“ angelegt (nicht oeffentlich).")
    else:
        print(f"Bucket „{cfg.SUPABASE_BUCKET}“ ist da.")

    geladen = fehlgeschlagen = 0
    for bereich, stand in _lage(speicher).items():
        offen = stand["fehlt_oben"]
        print(f"\n{bereich}: {len(offen)} Datei(en) zu laden")
        for name in offen:
            pfad = os.path.join(stand["ordner"], name)
            try:
                with open(pfad, "rb") as datei:
                    speicher.ablegen(bereich, name, datei.read())
                geladen += 1
                print(f"   ok   {name}")
            except (OSError, speicher.SpeicherFehler) as problem:
                fehlgeschlagen += 1
                print(f"   FEHL {name}: {problem}")

    print(f"\n{geladen} Datei(en) hochgeladen, {fehlgeschlagen} fehlgeschlagen.")
    print("Die oertlichen Kopien bleiben liegen. Wenn alles stimmt:")
    print("   python werkzeuge/dateien_nach_supabase.py --aufraeumen")
    return 1 if fehlgeschlagen else 0


def aufraeumen(cfg, speicher) -> int:
    """Oertliche Kopien loeschen - nur mit Nachweis im Bucket.

    Der Nachweis ist die Groesse, nicht der blosse Name: Ein abgebrochener
    Upload hinterlaesst durchaus einen Eintrag, nur eben einen leeren. Diese
    eine Datei zu loeschen, weil sie oben "steht", waere der teuerste
    denkbare Fehler dieses Werkzeugs.
    """
    geloescht = behalten = 0
    for bereich in (speicher.SUPPORT, speicher.REDAKTION):
        ordner = speicher.ORDNER[bereich]
        print(f"\n{bereich}")
        for name in speicher.auf_platte(bereich):
            pfad = os.path.join(ordner, name)
            hier = os.path.getsize(pfad)
            try:
                oben = speicher.aus_bucket(bereich, name)
            except speicher.SpeicherFehler as problem:
                print(f"   BLEIBT {name}: {problem}")
                behalten += 1
                continue
            if oben is None or len(oben) != hier:
                print(f"   BLEIBT {name}: oben {'fehlt' if oben is None else len(oben)}, "
                      f"hier {hier} Byte")
                behalten += 1
                continue
            try:
                os.remove(pfad)
                geloescht += 1
            except OSError as problem:
                print(f"   BLEIBT {name}: {problem}")
                behalten += 1
    print(f"\n{geloescht} oertliche Kopie(n) geloescht, {behalten} behalten.")
    if behalten:
        print("Behaltene bitte erst mit --umziehen nachladen.")
    return 0


def main() -> int:
    zerleger = argparse.ArgumentParser(
        description="Hochgeladene Dateien nach Supabase Storage")
    zerleger.add_argument("--pruefen", action="store_true",
                          help="zaehlen, nichts aendern")
    zerleger.add_argument("--umziehen", action="store_true",
                          help="Bucket anlegen und Dateien hochladen")
    zerleger.add_argument("--aufraeumen", action="store_true",
                          help="oertliche Kopien loeschen (nur nachgewiesene)")
    args = zerleger.parse_args()
    if not (args.pruefen or args.umziehen or args.aufraeumen):
        zerleger.print_help()
        return 1

    cfg, speicher = _vorbereiten()
    if not speicher.in_supabase():
        print("\nDer Supabase-Storage ist nicht eingerichtet.")
        if not cfg.SUPABASE_URL:
            print("Es fehlt SUPABASE_URL - und aus der DATABASE_URL liess "
                  "sich keine ableiten.")
        if not cfg.SUPABASE_SERVICE_KEY:
            print("Es fehlt SUPABASE_SERVICE_KEY. Der Schluessel steht im "
                  "Supabase-Dashboard")
            print("unter Project Settings -> API Keys -> service_role und "
                  "gehoert in die")
            print('config.cmd:   set "SUPABASE_SERVICE_KEY=..."')
        return 1

    try:
        if args.aufraeumen:
            return aufraeumen(cfg, speicher)
        if args.umziehen:
            return hochladen(cfg, speicher)
        return bericht(cfg, speicher)
    except speicher.SpeicherFehler as problem:
        print(f"\n{problem}")
        print("\nHaeufigste Ursachen: falscher oder abgelaufener "
              "service_role-Schluessel,")
        print("der Bucket gehoert einem anderen Projekt, oder das Projekt "
              "ist pausiert.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
