"""Hochgeladene Dateien - Screenshots aus dem Support, Anhaenge der Redaktion.

Bis hierher lagen sie als Dateien im Datenordner (support_uploads,
redaktion_uploads), waehrend die Datenbank laengst bei Supabase liegt. Das
geht nur so lange gut, wie es genau einen Rechner gibt: Zieht die Anwendung
um oder wird der Datenordner nicht mitgenommen, steht in der Datenbank der
Dateiname - und im Ordner liegt nichts. Der Support saehe bei jedem
Screenshot "Nicht gefunden", und niemand koennte sagen, ob das Bild je da
war.

Deshalb geht jede hochgeladene Datei in den Supabase-Storage, sobald ein
Schluessel eingetragen ist. Ohne Schluessel (Entwicklung, Testlauf) bleibt
alles beim Datenordner - die Anwendung laeuft dann ohne Netz und ohne Zugang
genau wie vorher.

Zwei Entscheidungen, die man spaeter nicht mehr sieht:

* Der Bucket ist NICHT oeffentlich. Wer ein Bild sehen darf, entscheidet
  weiterhin die Route im Dashboard, die Datei wird von dort durchgereicht.
  Ein oeffentlicher Bucket machte jeden Screenshot fuer jeden lesbar, der die
  Adresse kennt - und Support-Screenshots zeigen regelmaessig Namen,
  Nachrichten und halbe Postfaecher.

* Gelesen wird zuerst von der Platte. Was vor dem Umzug hochgeladen wurde,
  liegt dort noch; so bleibt es sichtbar, auch wenn es nie in den Bucket
  gewandert ist. Die Namen sind Zufallswerte und werden nie neu vergeben -
  dieselbe Datei kann also nicht in zwei Fassungen existieren.
"""

import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request

from kern import einstellungen as cfg

#  Die beiden Bereiche. Sie sind zugleich der Ordner auf der Platte und der
#  Unterordner im Bucket - so heisst dasselbe an beiden Orten gleich.
SUPPORT = "support"
REDAKTION = "redaktion"

ORDNER = {
    SUPPORT: cfg.SUPPORT_UPLOAD_DIR,
    REDAKTION: cfg.REDAKTION_UPLOAD_DIR,
}

# 30 Sekunden: Eine 10-MB-Datei ueber eine Schulleitung braucht laenger als
# die 20, die anderswo genuegen.
ZEITGRENZE = 30


class SpeicherFehler(RuntimeError):
    """Die Datei liess sich nicht ablegen, holen oder loeschen."""


def in_supabase() -> bool:
    """Gehen neue Dateien in den Bucket?"""
    return bool(cfg.SUPABASE_URL and cfg.SUPABASE_SERVICE_KEY)


def _schluessel(bereich: str, name: str) -> str:
    """Der Pfad im Bucket - und zugleich die Pruefung des Namens.

    Der Name kommt aus der Datenbank und ist dort immer ein Zufallswert. Ihn
    trotzdem zu pruefen kostet nichts und verhindert, dass ein spaeterer
    Aufrufer ueber ".." aus dem Bereich herausklettert.
    """
    if bereich not in ORDNER:
        raise SpeicherFehler(f"Unbekannter Bereich: {bereich}")
    if not name or "/" in name or "\\" in name or ".." in name:
        raise SpeicherFehler("Unzulässiger Dateiname.")
    return f"{bereich}/{name}"


def plattenpfad(bereich: str, name: str) -> str:
    """Wo die Datei auf der Platte laege."""
    _schluessel(bereich, name)
    return os.path.join(ORDNER[bereich], name)


def _typ_zu(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _bucket() -> str:
    return urllib.parse.quote(cfg.SUPABASE_BUCKET, safe="")


def _fehlertext(problem) -> str:
    """Was Supabase zu einem Fehlschlag sagt - kurz und ohne Schluessel."""
    try:
        rumpf = problem.read().decode("utf-8", "replace")
    except Exception:                                        # pragma: no cover
        return str(problem)
    try:
        rumpf = json.loads(rumpf).get("message", rumpf)
    except (ValueError, AttributeError):
        pass
    return (rumpf or str(problem))[:200]


def _anfrage(methode: str, pfad: str, daten=None, inhaltstyp: str = "",
             kopf: dict = None, fehlt_ist_leer: bool = False):
    """Ein Aufruf an die Storage-API. Gibt den Rumpf als bytes zurueck.

    fehlt_ist_leer=True macht aus "gibt es nicht" ein None statt einer
    Ausnahme - beim Holen und Loeschen ist das eine Antwort und kein Fehler.
    Beim Ablegen dagegen hiesse dieselbe Meldung, dass der Bucket fehlt; das
    muss auffallen.
    """
    kopfzeilen = {"Authorization": f"Bearer {cfg.SUPABASE_SERVICE_KEY}",
                  "apikey": cfg.SUPABASE_SERVICE_KEY,
                  "User-Agent": "WAG-Plattform"}
    if inhaltstyp:
        kopfzeilen["Content-Type"] = inhaltstyp
    kopfzeilen.update(kopf or {})
    anfrage = urllib.request.Request(f"{cfg.SUPABASE_URL}/storage/v1{pfad}",
                                     data=daten, method=methode,
                                     headers=kopfzeilen)
    try:
        with urllib.request.urlopen(anfrage, timeout=ZEITGRENZE) as antwort:
            return antwort.read()
    except urllib.error.HTTPError as problem:
        # Supabase antwortet auf eine fehlende Datei mit 400 "Object not
        # found", nicht mit 404. Beides zaehlt hier als "gibt es nicht".
        if problem.code in (400, 404) and fehlt_ist_leer:
            return None
        raise SpeicherFehler(
            f"Supabase Storage {problem.code}: {_fehlertext(problem)}") from problem
    except (urllib.error.URLError, TimeoutError, OSError) as problem:
        raise SpeicherFehler(
            f"Supabase Storage nicht erreichbar: {problem}") from problem


def ablegen(bereich: str, name: str, daten: bytes, inhaltstyp: str = "") -> None:
    """Eine hochgeladene Datei sichern.

    Wirft SpeicherFehler, wenn das nicht klappt - und schreibt dann bewusst
    NICHT ersatzweise auf die Platte. Genau diese halbe Loesung waere der
    Zustand, den dieses Modul beseitigen soll: ein Teil der Dateien hier, ein
    Teil dort, und niemand weiss, welcher. Besser eine ehrliche Meldung, die
    zum zweiten Versuch auffordert.
    """
    schluessel = _schluessel(bereich, name)
    if not in_supabase():
        os.makedirs(ORDNER[bereich], exist_ok=True)
        with open(os.path.join(ORDNER[bereich], name), "wb") as ziel:
            ziel.write(daten)
        return
    _anfrage("POST", f"/object/{_bucket()}/{schluessel}", daten=daten,
             inhaltstyp=inhaltstyp or _typ_zu(name),
             kopf={"x-upsert": "true", "cache-control": "3600"})


async def ablegen_aus_route(bereich: str, name: str, daten: bytes,
                            inhaltstyp: str = "") -> None:
    """ablegen() aus einer async-Route heraus.

    Der Upload geht ueber das Netz und dauert; direkt aufgerufen legte er
    solange den ganzen Server still - alle async-Routen teilen sich einen
    Faden. Starlette hat dafuer einen Threadpool, in dem ohnehin jede
    gewoehnliche def-Route laeuft.
    """
    from starlette.concurrency import run_in_threadpool
    await run_in_threadpool(ablegen, bereich, name, daten, inhaltstyp)


def aus_bucket(bereich: str, name: str):
    """Der Inhalt aus dem Bucket - ohne Blick auf die Platte.

    Getrennt von holen(), weil der Umzug beide Seiten vergleichen muss: Wer
    dort die Platte mitzaehlte, vergliche eine Datei mit sich selbst.
    """
    schluessel = _schluessel(bereich, name)
    if not in_supabase():
        return None
    return _anfrage("GET", f"/object/{_bucket()}/{schluessel}",
                    fehlt_ist_leer=True)


def holen(bereich: str, name: str):
    """Der Inhalt der Datei - oder None, wenn es sie nirgends gibt."""
    pfad = plattenpfad(bereich, name)
    if os.path.exists(pfad):
        with open(pfad, "rb") as datei:
            return datei.read()
    return aus_bucket(bereich, name)


def entfernen(bereich: str, name: str) -> None:
    """Die Datei vergessen - im Bucket und, falls noch da, auf der Platte.

    Scheitert der Bucket-Teil, bleibt es dabei: Der Aufrufer loescht gerade
    einen Eintrag, und den deswegen stehen zu lassen waere die schlechtere
    Ueberraschung. Was bleibt, ist eine Datei ohne Verweis - der naechste
    Durchlauf von werkzeuge/dateien_nach_supabase.py --pruefen zeigt sie an.
    """
    schluessel = _schluessel(bereich, name)
    pfad = os.path.join(ORDNER[bereich], name)
    try:
        if os.path.exists(pfad):
            os.remove(pfad)
    except OSError:
        pass
    if not in_supabase():
        return
    try:
        _anfrage("DELETE", f"/object/{_bucket()}/{schluessel}",
                 fehlt_ist_leer=True)
    except SpeicherFehler:
        pass


def _anhang_kopf(dateiname: str) -> dict:
    """Content-Disposition fuer einen Download - Umlaute inbegriffen.

    FileResponse baut das selbst; wer die Datei aus dem Bucket durchreicht,
    muss es von Hand tun. Ohne den utf-8-Zweig hiesse "Präsentation.pdf" beim
    Herunterladen anders als im Dashboard.
    """
    sicher = "".join(z for z in dateiname if z not in '"\\\r\n') or "datei"
    try:
        sicher.encode("ascii")
        return {"content-disposition": f'attachment; filename="{sicher}"'}
    except UnicodeEncodeError:
        return {"content-disposition":
                "attachment; filename*=utf-8''" + urllib.parse.quote(sicher)}


def antwort(bereich: str, name: str, dateiname: str = None):
    """Die Datei als HTTP-Antwort - egal, wo sie liegt.

    Mit dateiname wird sie zum Download unter diesem Namen; ohne zeigt der
    Browser das Bild direkt an, so wie es im Support gedacht ist.
    """
    from fastapi.responses import FileResponse, Response
    try:
        pfad = plattenpfad(bereich, name)
    except SpeicherFehler:
        return Response("Nicht gefunden", status_code=404,
                        media_type="text/plain")
    if os.path.exists(pfad):
        return (FileResponse(pfad, filename=dateiname) if dateiname
                else FileResponse(pfad))
    try:
        daten = holen(bereich, name)
    except SpeicherFehler as problem:
        return Response(f"Die Datei ist gerade nicht erreichbar. ({problem})",
                        status_code=502, media_type="text/plain")
    if daten is None:
        return Response("Nicht gefunden", status_code=404,
                        media_type="text/plain")
    return Response(daten, media_type=_typ_zu(dateiname or name),
                    headers=_anhang_kopf(dateiname) if dateiname else None)


#  Nur fuer werkzeuge/dateien_nach_supabase.py
def bucket_anlegen() -> bool:
    """Legt den Bucket an, falls es ihn nicht gibt. True = neu angelegt.

    Nicht oeffentlich, und mit denselben Grenzen wie die Formulare: Was das
    Dashboard nicht annimmt, soll auch ueber einen abhandengekommenen
    Schluessel nicht hineinkommen.
    """
    if _anfrage("GET", f"/bucket/{_bucket()}", fehlt_ist_leer=True) is not None:
        return False
    erlaubt = sorted(set(cfg.ERLAUBTE_ANHANGTYPEN) | set(cfg.ERLAUBTE_BILDTYPEN))
    koerper = json.dumps({"id": cfg.SUPABASE_BUCKET,
                          "name": cfg.SUPABASE_BUCKET,
                          "public": False,
                          "file_size_limit": cfg.MAX_REDAKTION_BYTES,
                          "allowed_mime_types": erlaubt}).encode("utf-8")
    _anfrage("POST", "/bucket", daten=koerper, inhaltstyp="application/json")
    return True


def liste(bereich: str) -> set:
    """Die Namen, die im Bucket unter diesem Bereich liegen."""
    if bereich not in ORDNER:
        raise SpeicherFehler(f"Unbekannter Bereich: {bereich}")
    namen, versatz = set(), 0
    while True:
        koerper = json.dumps({"prefix": f"{bereich}/", "limit": 100,
                              "offset": versatz,
                              "sortBy": {"column": "name", "order": "asc"}
                              }).encode("utf-8")
        roh = _anfrage("POST", f"/object/list/{_bucket()}", daten=koerper,
                       inhaltstyp="application/json")
        eintraege = json.loads(roh.decode("utf-8")) if roh else []
        if not eintraege:
            return namen
        namen.update(e.get("name", "") for e in eintraege if e.get("name"))
        versatz += len(eintraege)


def auf_platte(bereich: str) -> list:
    """Was im Datenordner liegt - die Vorlage fuer den Umzug."""
    ordner = ORDNER[bereich]
    if not os.path.isdir(ordner):
        return []
    return sorted(n for n in os.listdir(ordner)
                  if os.path.isfile(os.path.join(ordner, n)))
