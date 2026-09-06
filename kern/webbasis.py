"""Gemeinsames Fundament beider FastAPI-Anwendungen.

Hier steht alles, was Website und Dashboard gleich machen muessen:
Sicherheitskopfzeilen, Anmeldebremse, Fehlerseiten, Sitzungs-Cookie,
Kompression und die Auslieferung der statischen Dateien.

Warum ueberhaupt zwei Anwendungen? Weil sie voellig verschiedene Aufgaben
haben. Die Website ist oeffentlich, wird von Suchmaschinen gelesen und muss
schnell sein. Das Dashboard ist ein Arbeitswerkzeug hinter der Anmeldung.
Getrennt lassen sie sich getrennt haerten (das Dashboard bekommt strengere
Kopfzeilen und faellt aus dem Index), getrennt neu starten und im Ernstfall
getrennt abschalten - eine Ueberlastung der oeffentlichen Seite legt dann
nicht die Verwaltung mit lahm.
"""

import re
import secrets
import threading
import time
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from kern import einstellungen as cfg
from kern.datenbank import SessionLocal
from kern.sicherheit import RATE_LIMITS, bremse
from kern.sitzung import angemeldete_person, client_ip
from kern.vorlagen import zeige

STATISCH_CACHE_SEKUNDEN = 7 * 24 * 60 * 60


class _StatischMitCache(StaticFiles):
    """Statische Dateien mit Aufbewahrungsfrist.

    Ohne diese Angabe fragt der Browser bei jedem Seitenaufruf neu nach - beim
    Logo hiess das einmal Logo pro Klick. Dateien mit ?v=... im Aufruf tragen
    eine Pruefsumme und duerfen ein Jahr bleiben.
    """

    async def get_response(self, path, scope):
        antwort = await super().get_response(path, scope)
        if antwort.status_code in (200, 304):
            fragt_nach_fassung = b"v=" in scope.get("query_string", b"")
            dauer = 31536000 if fragt_nach_fassung else STATISCH_CACHE_SEKUNDEN
            unveraenderlich = ", immutable" if fragt_nach_fassung else ""
            antwort.headers["Cache-Control"] = f"public, max-age={dauer}{unveraenderlich}"
        return antwort


def _fehlerseite(request: Request, status: int, detail: str = "") -> HTMLResponse:
    db = SessionLocal()
    try:
        user = angemeldete_person(request, db)
    except Exception:
        user = None
    finally:
        db.close()
    antwort = zeige("fehler.html", request=request, user=user, status=status,
                    detail=detail,
                    # Fuer den Meldeknopf: Ohne die Adresse steht im Ticket
                    # "Fehler 500" und sonst nichts, und die Suche beginnt bei
                    # null. Bewusst nicht als `pfad` - das setzt den
                    # Kanonisierungs-Verweis im Seitenkopf.
                    angefragt=request.url.path,
                    seitentitel=f"Fehler {status} | Wirtschafts- & Investment-AG",
                    robots="noindex, nofollow")
    # Der Statuscode muss ausdruecklich gesetzt werden: zeige() liefert eine
    # HTMLResponse und die steht auf 200. Ohne diese Zeile bekaeme eine
    # Suchmaschine fuer jede fehlende Seite ein "alles in Ordnung" - und der
    # Browser wuerde eine 403 nicht als Fehler behandeln.
    antwort.status_code = status
    return antwort


def _wirt_aus(scope) -> str:
    """Der angesprochene Rechnername aus dem ASGI-Scope, ohne Port."""
    roh = ""
    for kopf, wert in scope.get("headers") or ():
        if kopf == b"host":
            roh = wert.decode("latin-1")
            break
    roh = roh.strip().lower()
    if roh.startswith("["):                       # IPv6: [::1]:8000
        return roh[1:roh.index("]")] if "]" in roh else roh[1:]
    return roh.split(":")[0]


class OertlicheCookies:
    """Nimmt Cookies auf dem eigenen Rechner die Domain-Angabe.

    Der Sitzungs-Cookie gilt fuer ".mvlg-wag.de", damit Website und Dashboard
    dieselbe Anmeldung sehen. Ein Browser wirft einen Cookie mit dieser
    Domain auf localhost aber weg - man kaeme beim oertlichen Testen nie
    ueber die Anmeldung hinaus, weil der Server die Sitzung nie
    zurueckbekommt. Auf localhost gilt der Cookie deshalb nur fuer localhost;
    das reicht dort auch, denn beide Haelften laufen unter demselben Namen.

    Muss ausserhalb der Sitzungs-Middleware liegen, sonst ist der Cookie noch
    gar nicht gesetzt.
    """

    _DOMAIN = re.compile(rb";\s*[Dd]omain=[^;]*")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        wirt = _wirt_aus(scope)
        # Leerer Host oder eine Proxy-Spur: Finger weg. Siehe cfg.ueber_proxy()
        # - saehe die Anwendung hinter einem Tunnel einen oertlichen Aufruf,
        # verloere der Sitzungs-Cookie seine Domain und die Anmeldung gaelte
        # nicht mehr fuer beide Namen.
        if (scope.get("type") != "http" or not wirt
                or wirt not in cfg.LOKALE_NAMEN
                or any(name.decode("latin-1").lower() in cfg.PROXY_SPUREN
                       for name, _ in (scope.get("headers") or ()))):
            return await self.app(scope, receive, send)

        async def senden(ereignis):
            if ereignis["type"] == "http.response.start":
                ereignis = dict(ereignis)
                ereignis["headers"] = [
                    (kopf, self._DOMAIN.sub(b"", wert))
                    if kopf.lower() == b"set-cookie" else (kopf, wert)
                    for kopf, wert in ereignis["headers"]]
            await send(ereignis)

        await self.app(scope, receive, senden)


def baue_app(name: str, *, ist_dashboard: bool) -> FastAPI:
    """Erzeugt eine vorkonfigurierte Anwendung.

    Die Reihenfolge der Middleware ist bedeutsam: Starlette ruft sie in
    umgekehrter Reihenfolge der Registrierung auf. Die Sitzung muss deshalb
    ZULETZT hinzugefuegt werden, damit sie als erste laeuft und request.session
    fuer alle darunter bereitsteht.
    """
    anwendung = FastAPI(title=name, docs_url=None, redoc_url=None,
                        openapi_url=None)
    # Damit cfg.adressen_fuer() weiss, welche der beiden Adressen die eigene
    # ist - siehe dort.
    anwendung.state.ist_dashboard = ist_dashboard

    # --- Fehlerseiten ------------------------------------------------------
    @anwendung.exception_handler(StarletteHTTPException)
    async def _http_fehler(request: Request, fehler: StarletteHTTPException):
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": fehler.detail},
                                status_code=fehler.status_code)
        # Bei htmx nur den Inhaltsbereich ersetzen, nicht die ganze Seite in
        # den Kasten laden.
        if request.headers.get("HX-Request") == "true":
            return HTMLResponse(
                f'<div class="panel meldung meldung-fehler">'
                f'<p>{fehler.detail or "Das hat nicht geklappt."}</p></div>',
                status_code=fehler.status_code)
        return _fehlerseite(request, fehler.status_code, str(fehler.detail or ""))

    @anwendung.exception_handler(Exception)
    async def _unerwarteter_fehler(request: Request, fehler: Exception):
        # In die Konsole mit vollem Verlauf, an den Browser nur die knappe
        # Meldung: eine Stacktrace im Browser verraet Pfade und Bibliotheks-
        # fassungen.
        print(f"[Fehler] {request.method} {request.url.path}: {fehler!r}")
        traceback.print_exc()
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": "Interner Serverfehler."}, status_code=500)
        if request.headers.get("HX-Request") == "true":
            return HTMLResponse(
                '<div class="panel meldung meldung-fehler"><p>Da ist etwas '
                'schiefgelaufen. Bitte noch einmal versuchen.</p></div>',
                status_code=500)
        return _fehlerseite(request, 500,
                            "Es ist ein unerwarteter Fehler aufgetreten.")

    # --- Kopfzeilen und Bremse --------------------------------------------
    @anwendung.middleware("http")
    async def _schutz(request: Request, weiter):
        # Ein frischer Nonce je Anfrage. Nur Skripte, die ihn tragen, laesst
        # der Browser laufen - eingeschleustes <script> hat ihn nicht.
        request.state.nonce = secrets.token_urlsafe(12)

        ip = client_ip(request, cfg.TRUST_PROXY_HEADERS)
        regel = RATE_LIMITS.get(request.url.path)
        merker = None
        if request.method == "POST" and regel:
            maximum, fenster, nur_fehler = regel
            erlaubt, warten, m = bremse.pruefen(request.url.path, ip, maximum, fenster)
            if not erlaubt:
                minuten = max(1, round(warten / 60))
                text = (f"Von diesem Anschluss kamen gerade sehr viele Versuche. "
                        f"Bitte warte etwa {minuten} Minute"
                        f"{'n' if minuten != 1 else ''} und versuche es dann erneut.")
                antwort = _fehlerseite(request, 429, text)
                antwort.headers["Retry-After"] = str(warten)
                return antwort
            if nur_fehler:
                merker = m

        antwort = await weiter(request)

        # Hat die Route den Aufruf als harmlos gemeldet (gelungene Anmeldung),
        # zaehlt er nicht mit.
        if merker and getattr(request.state, "bremse_frei", False):
            bremse.gutschreiben(merker)

        antwort.headers["X-Content-Type-Options"] = "nosniff"
        antwort.headers["X-Frame-Options"] = "DENY"
        antwort.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        antwort.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
            "interest-cohort=()")
        # Trennt das Fenster von allem, was es geoeffnet hat - ohne das kann
        # eine fremde Seite auf window.opener zugreifen.
        antwort.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        antwort.headers["X-Permitted-Cross-Domain-Policies"] = "none"

        # Client Hints anfordern. Ohne diese Zeile schickt Chrome nur die
        # grobe Kennung; erst auf Nachfrage nennt er das echte Geraetemodell
        # und die echte Systemfassung. Genau das braucht der Support bei
        # "auf meinem Handy ist alles verrutscht" - der User-Agent von
        # Chrome behauptet dort seit der "User-Agent Reduction" bei jedem
        # Android-Geraet dasselbe.
        #
        # Bewusst ohne Critical-CH: Das wuerde den ersten Aufruf jeder
        # Sitzung sofort wiederholen lassen, damit die Angaben schon dort
        # dabei sind. Einen Seitenaufbau doppelt zu laden ist der Diagnose
        # nicht wert - ab dem zweiten Aufruf sind sie ohnehin da.
        if cfg.DIAGNOSE_AKTIV:
            antwort.headers["Accept-CH"] = (
                "Sec-CH-UA-Platform-Version, Sec-CH-UA-Model, "
                "Sec-CH-UA-Full-Version-List, Sec-CH-UA-Arch, "
                "Sec-CH-UA-Bitness")

        nonce = request.state.nonce
        # Kein 'unsafe-inline' bei script-src: das war in V1 der groesste
        # Schwachpunkt der Richtlinie. Skripte laufen nur mit Nonce.
        csp = [
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}'",
            # Seit die Schriften lokal liegen, darf hier kein fremder Rechner
            # mehr stehen: was nicht erlaubt ist, kann auch nicht nachgeladen
            # werden - auch nicht von eingeschleustem Markup.
            "style-src 'self' 'unsafe-inline'",
            "font-src 'self'",
            "img-src 'self' data: blob:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "object-src 'none'",
            # Beim oertlichen Testen kommen die localhost-Adressen dazu,
            # sonst blockt der Browser das Anmeldeformular.
            f"form-action 'self' {' '.join(cfg.form_action_ziele(request))}",
        ]
        antwort.headers["Content-Security-Policy"] = "; ".join(csp)

        if ist_dashboard:
            # Das Dashboard gehoert nicht in Suchmaschinen und nicht in den
            # Zwischenspeicher eines geteilten Rechners.
            antwort.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            if request.url.path.startswith("/dashboard") or request.url.path == "/":
                antwort.headers.setdefault(
                    "Cache-Control", "no-store, no-cache, must-revalidate, private")

        ueber_https = request.url.scheme == "https" or (
            cfg.TRUST_PROXY_HEADERS
            and request.headers.get("x-forwarded-proto") == "https")
        if cfg.HSTS_ENABLED and ueber_https:
            antwort.headers["Strict-Transport-Security"] = f"max-age={cfg.HSTS_MAX_AGE}"
        return antwort

    # --- Kompression -------------------------------------------------------
    from fastapi.middleware.gzip import GZipMiddleware
    anwendung.add_middleware(GZipMiddleware, minimum_size=800, compresslevel=6)

    # --- Sitzung (zuletzt registriert = laeuft zuerst) ---------------------
    anwendung.add_middleware(
        SessionMiddleware,
        secret_key=cfg.SECRET_KEY,
        same_site="lax",
        https_only=cfg.HTTPS_ONLY_COOKIES,
        # Der Cookie lebt laenger als die Sitzung selbst - abgelaufen wird
        # serverseitig (siehe kern/sitzung.py). Ein zu kurzer Cookie wuerde
        # jemanden mitten in der Arbeit hinauswerfen, ohne dass der Server
        # das ueberhaupt merkt.
        # So lang wie die laengstmoegliche Sitzung. Wie lange sie
        # wirklich gilt, entscheidet der Server (kern/sitzung.py) -
        # ein Cookie, der frueher stirbt, wuerde die Wahl
        # "eingeloggt bleiben" heimlich aushebeln.
        max_age=cfg.SITZUNG_DAUERHAFT_TAGE * 86400,
        session_cookie="wag_sitzung",
        # Liegen Website und Dashboard auf verschiedenen Namen derselben
        # Domain, muss der Cookie fuer die ganze Domain gelten - sonst kennt
        # das Dashboard die Anmeldung von der Website nicht.
        domain=cfg.COOKIE_DOMAIN or None,
    )
    # Ganz aussen: siehe OertlicheCookies. Nur dort kommt der eben gesetzte
    # Sitzungs-Cookie noch einmal vorbei.
    anwendung.add_middleware(OertlicheCookies)

    # --- Statische Dateien -------------------------------------------------
    anwendung.mount("/statisch",
                    _StatischMitCache(directory=cfg.STATISCH_DIR),
                    name="statisch")
    # V1 lieferte Bilder unter /static aus. Bestehende Verweise - etwa in
    # bereits verschickten E-Mails oder in der auf dem Startbildschirm
    # abgelegten App - sollen nicht ins Leere laufen.
    anwendung.mount("/static",
                    _StatischMitCache(directory=cfg.STATISCH_DIR + "/bilder"),
                    name="static_alt")

    return anwendung


def bremse_aufraeumer_starten() -> None:
    """Raeumt die Zaehler der Anmeldebremse regelmaessig auf."""
    def schleife():
        while True:
            time.sleep(600)
            try:
                bremse.aufraeumen(max(f for _, f, _ in RATE_LIMITS.values()))
            except Exception:                                # pragma: no cover
                pass

    threading.Thread(target=schleife, daemon=True, name="bremse-aufraeumen").start()


def leere_antwort() -> Response:
    """204 - fuer htmx-Aufrufe, die nichts austauschen sollen."""
    return Response(status_code=204)
