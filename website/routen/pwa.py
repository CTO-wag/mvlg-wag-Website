"""Manifest und Hintergrundskript - macht die Seite installierbar.

Beides muss vom selben Server kommen wie die Seite selbst, sonst laesst der
Browser die Registrierung nicht zu. Deshalb liegt es zweimal: einmal hier und
einmal im Dashboard-Prozess (dort mit eigenem Startpunkt).
"""

from fastapi import APIRouter, Response


router = APIRouter()

MANIFEST_VORLAGE = {
    "description": "Schüler-AG für Wirtschaft, Finanzen und Investments am "
                   "Max-von-Laue-Gymnasium Koblenz.",
    "lang": "de",
    "display": "standalone",
    "orientation": "portrait-primary",
    "background_color": "#F6F7F4",
    "theme_color": "#0E2647",
    "icons": [
        {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/static/icon-maskable-512.png", "sizes": "512x512",
         "type": "image/png", "purpose": "maskable"},
    ],
}

# Das Hintergrundskript. Zwei Aufgaben, mehr nicht:
#   1. Push-Meldungen anzeigen und beim Antippen das Dashboard oeffnen.
#   2. Bei fehlendem Netz eine verstaendliche Seite zeigen statt des
#      Dinosauriers.
# Bewusst OHNE Zwischenspeicher fuer Seiteninhalte: eine Verwaltungsoberflaeche
# mit veralteten Daten anzuzeigen ist schlimmer, als sie gar nicht anzuzeigen.
SERVICE_WORKER = """
const OFFLINE_SEITE = 'wag-offline-v2';
const OFFLINE_HTML = `<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Keine Verbindung</title><style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui,sans-serif;background:#F6F7F4;color:#18211F;padding:1.5rem;}
.k{max-width:26rem;text-align:center;background:#fff;border:1px solid rgba(24,33,31,.12);
border-radius:10px;padding:2rem;}h1{font-size:1.3rem;margin:0 0 .6rem;color:#0E2647;}
p{color:#66726D;line-height:1.6;margin:0 0 1.2rem;}
button{background:#0E2647;color:#fff;border:0;border-radius:7px;padding:.7rem 1.3rem;
font-size:.95rem;font-weight:600;cursor:pointer;}
@media (prefers-color-scheme:dark){body{background:#0A0F1A;color:#EDF0F7;}
.k{background:#131B2C;border-color:rgba(237,240,247,.13);}h1{color:#82A6F2;}p{color:#9AA7C2;}}
</style></head><body><div class="k"><h1>Keine Verbindung</h1>
<p>Das Gerät ist gerade offline. Sobald wieder Netz da ist, geht es weiter.</p>
<button onclick="location.reload()">Erneut versuchen</button></div></body></html>`;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(OFFLINE_SEITE).then((c) =>
    c.put('/offline', new Response(OFFLINE_HTML, {headers: {'Content-Type': 'text/html; charset=utf-8'}}))
  ).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((namen) => Promise.all(
    namen.filter((n) => n !== OFFLINE_SEITE).map((n) => caches.delete(n))
  )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  // Nur normale Seitenaufrufe abfangen. Formulare und Datenabrufe muessen
  // scheitern duerfen - eine gecachte Antwort waere dort schlicht falsch.
  if (e.request.mode !== 'navigate') { return; }
  e.respondWith(fetch(e.request).catch(() => caches.match('/offline')));
});

self.addEventListener('push', (e) => {
  let daten = {titel: 'Wirtschafts- & Investment-AG', text: '', url: '/'};
  try { if (e.data) { daten = Object.assign(daten, e.data.json()); } }
  catch (err) { if (e.data) { daten.text = e.data.text(); } }
  e.waitUntil(self.registration.showNotification(daten.titel, {
    body: daten.text,
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    data: {url: daten.url},
    // Gleicher tag = die vorige Meldung wird ersetzt statt gestapelt.
    tag: 'wag-meldung',
    renotify: true
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const ziel = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(clients.matchAll({type: 'window', includeUncontrolled: true})
    .then((fenster) => {
      // Ein bereits offenes Fenster nach vorn holen, statt ein zweites zu
      // oeffnen - sonst sammeln sich nach einem Tag zehn Tabs an.
      for (const f of fenster) {
        if (f.url.startsWith(ziel) && 'focus' in f) { return f.focus(); }
      }
      return clients.openWindow(ziel);
    }));
});
"""


def _manifest(startpunkt: str, name: str, kurz: str) -> dict:
    daten = dict(MANIFEST_VORLAGE)
    daten["name"] = name
    daten["short_name"] = kurz
    daten["start_url"] = startpunkt
    daten["scope"] = "/"
    daten["id"] = startpunkt
    return daten


def baue_router(ist_dashboard: bool) -> APIRouter:
    """Manifest und Hintergrundskript fuer einen der beiden Server.

    Beides muss vom SELBEN Ursprung kommen wie die Seite - sonst laesst der
    Browser die Registrierung nicht zu. Genau daran scheiterte Push im
    Dashboard: Es lieferte kein /sw.js aus, die Registrierung lief in einen
    404, und der Knopf meldete einen nichtssagenden Fehler.

    Die Push-Anmeldung haengt am Ursprung. Laufen Website und Dashboard unter
    verschiedenen Hosts, sind es zwei getrennte Anmeldungen - wer die
    Startseite auf den Startbildschirm legt, bekommt dann die Meldungen des
    Dashboards NICHT. Wer beides unter einer Adresse haben will, laesst den
    Tunnel /dashboard auf Port 8001 und alles andere auf 8000 zeigen.
    """
    r = APIRouter()
    startpunkt = "/dashboard" if ist_dashboard else "/"
    name = ("Wirtschafts- & Investment-AG · Dashboard" if ist_dashboard
            else "Wirtschafts- & Investment-AG")
    kurz = "WAG Dashboard" if ist_dashboard else "WAG"

    @r.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        import json
        return Response(
            json.dumps(_manifest(startpunkt, name, kurz), ensure_ascii=False),
            media_type="application/manifest+json")

    @r.get("/sw.js", include_in_schema=False)
    def service_worker():
        return Response(SERVICE_WORKER, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

    @r.get("/offline", include_in_schema=False)
    def offline():
        # Nur als Rueckfall, falls jemand die Adresse direkt aufruft.
        return Response("Offline", media_type="text/plain")

    return r


# Der Router der oeffentlichen Seite - so bleibt der bisherige Import gueltig.
router = baue_router(ist_dashboard=False)
