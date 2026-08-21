/* ===========================================================================
   WhatsApp-Beiwagen auf Basis von whatsapp-web.js
   ===========================================================================
   Ein kleiner Node-Dienst neben der Python-Anwendung. Er hält eine
   WhatsApp-Web-Sitzung offen und nimmt über eine winzige HTTP-Schnittstelle
   Sendeaufträge entgegen.

   Warum ein eigener Prozess und nicht alles in Python?
   whatsapp-web.js steuert einen echten Chromium im Hintergrund. Das ist ein
   Node-Programm und lässt sich nicht sinnvoll aus Python heraus betreiben.
   Als eigener Prozess kann er außerdem abstürzen, ohne die Plattform
   mitzureißen - die Nachrichten bleiben dann im Ausgangskorb liegen und
   gehen raus, sobald er wieder da ist.

   Wichtig zu wissen:
   Das ist NICHT die offizielle Schnittstelle von Meta, sondern eine
   Fernsteuerung von WhatsApp Web. Sie braucht kein Business-Konto und keine
   genehmigten Vorlagen - dafür verstößt Automatisierung gegen die
   Nutzungsbedingungen von WhatsApp, und die verwendete Nummer kann gesperrt
   werden. Deshalb: sparsam senden, nur an eigene Mitglieder, und besser eine
   Zweitnummer verwenden als die private des Vorstands.

   Erreichbar ist der Dienst nur über 127.0.0.1 und nur mit dem Token aus
   config.cmd. Er darf unter keinen Umständen ins Netz.
   ========================================================================= */

'use strict';

const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs');

const PORT = parseInt(process.env.WHATSAPP_WEB_PORT || '8099', 10);
const TOKEN = process.env.WHATSAPP_WEB_TOKEN || '';
const SITZUNGSORDNER = process.env.WHATSAPP_WEB_SITZUNG
  || path.join(__dirname, '.sitzung');

if (!TOKEN) {
  console.error('[WhatsApp] WHATSAPP_WEB_TOKEN fehlt. Ohne Token startet der '
    + 'Dienst nicht - sonst könnte jedes Programm auf diesem Rechner in eurem '
    + 'Namen Nachrichten verschicken.');
  process.exit(1);
}

let Client, LocalAuth, qrcode;
try {
  ({ Client, LocalAuth } = require('whatsapp-web.js'));
  qrcode = require('qrcode');
} catch (e) {
  console.error('[WhatsApp] Die Pakete fehlen. Im Ordner whatsapp-dienst '
    + 'einmal "npm install" ausführen.');
  process.exit(1);
}

fs.mkdirSync(SITZUNGSORDNER, { recursive: true });

/* --- Welchen Browser fernsteuern? -----------------------------------------
   whatsapp-web.js braucht einen Chromium. Puppeteer bringt normalerweise
   einen eigenen mit - der Download ist aber 200 MB gross und bricht in
   Schulnetzen gerne ab; danach liegt ein halber Ordner herum und jedes
   "npm install" scheitert. Deshalb laedt .npmrc ihn gar nicht erst herunter
   und wir nehmen den Browser, der auf Windows ohnehin installiert ist.
   Edge ist Chromium - fuer die Fernsteuerung macht das keinen Unterschied. */
function browserPfad() {
  const kandidaten = [];
  if (process.env.WHATSAPP_BROWSER) { kandidaten.push(process.env.WHATSAPP_BROWSER); }

  // Ein selbst heruntergeladener Chromium hat Vorrang vor dem Systembrowser:
  // wer ihn ausdruecklich geholt hat, will ihn auch benutzen.
  const cache = path.join(process.env.USERPROFILE || process.env.HOME || '',
    '.cache', 'puppeteer', 'chrome');
  try {
    for (const ordner of fs.readdirSync(cache)) {
      kandidaten.push(path.join(cache, ordner, 'chrome-win64', 'chrome.exe'));
      kandidaten.push(path.join(cache, ordner, 'chrome-linux64', 'chrome'));
    }
  } catch (e) { /* kein Cache-Ordner - normal */ }

  const pf = process.env['ProgramFiles'] || 'C:\\Program Files';
  const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
  const lokal = process.env.LOCALAPPDATA || '';
  for (const wurzel of [pf, pf86, lokal]) {
    if (!wurzel) { continue; }
    kandidaten.push(path.join(wurzel, 'Google', 'Chrome', 'Application', 'chrome.exe'));
  }
  for (const wurzel of [pf86, pf, lokal]) {
    if (!wurzel) { continue; }
    kandidaten.push(path.join(wurzel, 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
  }

  for (const p of kandidaten) {
    try { if (p && fs.statSync(p).isFile()) { return p; } } catch (e) { /* weiter */ }
  }
  return null;
}

const BROWSER = browserPfad();
if (!BROWSER) {
  console.error('[WhatsApp] Kein Browser gefunden. Der Dienst steuert einen '
    + 'Chromium fern und braucht dafuer Chrome oder Edge. Entweder Chrome '
    + 'installieren, oder im Ordner whatsapp-dienst einmal '
    + '"npx puppeteer browsers install chrome" ausfuehren, oder in config.cmd '
    + 'WHATSAPP_BROWSER auf eine chrome.exe zeigen lassen.');
  process.exit(1);
}
console.log('[WhatsApp] Browser: ' + BROWSER);

/* --- Zustand --------------------------------------------------------------
   "start"    Chromium fährt hoch
   "qr"       wartet auf das Scannen des Codes
   "bereit"   angemeldet, kann senden
   "getrennt" Verbindung weg (Handy offline, abgemeldet)
   "fehler"   etwas ist grundsätzlich kaputt                                */
let zustand = 'start';
let qrBild = '';
let meldung = 'Der Dienst startet.';
let ich = null;
let seit = Date.now();

function setzeZustand(neu, text) {
  if (zustand !== neu) { seit = Date.now(); }
  zustand = neu;
  meldung = text || '';
  console.log(`[WhatsApp] ${neu}: ${meldung}`);
}

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: SITZUNGSORDNER }),
  puppeteer: {
    headless: true,
    executablePath: BROWSER,
    // Ohne diese beiden Schalter startet Chromium in manchen
    // Windows-Umgebungen gar nicht.
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  },
});

client.on('qr', async (rohdaten) => {
  try {
    qrBild = await qrcode.toDataURL(rohdaten, { margin: 1, width: 320 });
  } catch (e) {
    qrBild = '';
  }
  setzeZustand('qr', 'Bitte den Code im Dashboard mit WhatsApp scannen.');
});

client.on('authenticated', () => {
  qrBild = '';
  setzeZustand('start', 'Angemeldet, wird vorbereitet …');
});

client.on('ready', () => {
  qrBild = '';
  ich = client.info && client.info.wid ? client.info.wid.user : null;
  setzeZustand('bereit', ich ? `Verbunden als ${ich}.` : 'Verbunden.');
});

client.on('auth_failure', (m) => {
  setzeZustand('fehler', 'Anmeldung fehlgeschlagen: ' + m);
});

client.on('disconnected', (grund) => {
  ich = null;
  setzeZustand('getrennt', 'Verbindung getrennt (' + grund + '). '
    + 'Der Dienst versucht es gleich erneut.');
  // Neu aufbauen. Ohne das bleibt der Dienst tot, bis jemand ihn von Hand
  // neu startet - und das merkt niemand, bis Nachrichten liegen bleiben.
  setTimeout(() => {
    client.initialize().catch((e) =>
      setzeZustand('fehler', 'Neustart fehlgeschlagen: ' + e.message));
  }, 5000);
});

/* --- Senden ---------------------------------------------------------------- */
async function senden(nummer, text) {
  if (zustand !== 'bereit') {
    return { ok: false, fehler: 'Nicht verbunden (' + zustand + '): ' + meldung };
  }
  const sauber = String(nummer || '').replace(/\D/g, '');
  if (sauber.length < 8) {
    return { ok: false, fehler: 'Die Nummer sieht nicht nach einer Rufnummer aus.' };
  }
  try {
    // Erst nachsehen, ob die Nummer überhaupt WhatsApp hat. Ohne diese
    // Prüfung landet die Nachricht im Nichts und der Korb meldet Erfolg.
    const kennung = await client.getNumberId(sauber);
    if (!kennung) {
      return { ok: false, fehler: 'Diese Nummer hat kein WhatsApp.' };
    }
    await client.sendMessage(kennung._serialized, String(text || ''));
    return { ok: true };
  } catch (e) {
    return { ok: false, fehler: (e && e.message) || 'Unbekannter Fehler' };
  }
}

/* --- HTTP ------------------------------------------------------------------ */
function antworte(res, code, daten) {
  const koerper = JSON.stringify(daten);
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(koerper),
    'Cache-Control': 'no-store',
  });
  res.end(koerper);
}

function tokenStimmt(req) {
  const kopf = req.headers['x-token'] || '';
  if (kopf.length !== TOKEN.length) { return false; }
  // Zeitunabhängiger Vergleich - sonst ließe sich das Token über die
  // Antwortzeit Zeichen für Zeichen erraten.
  let unterschied = 0;
  for (let i = 0; i < TOKEN.length; i++) {
    unterschied |= kopf.charCodeAt(i) ^ TOKEN.charCodeAt(i);
  }
  return unterschied === 0;
}

const server = http.createServer((req, res) => {
  if (!tokenStimmt(req)) {
    return antworte(res, 403, { fehler: 'Token stimmt nicht.' });
  }

  if (req.method === 'GET' && req.url === '/zustand') {
    return antworte(res, 200, {
      zustand, meldung, qr: qrBild, nummer: ich,
      sekunden: Math.round((Date.now() - seit) / 1000),
    });
  }

  if (req.method === 'POST' && req.url === '/senden') {
    let roh = '';
    req.on('data', (stueck) => {
      roh += stueck;
      // Eine Willkommensnachricht ist nie 100 KB groß. Abbrechen statt
      // Speicher volllaufen lassen.
      if (roh.length > 100000) { req.destroy(); }
    });
    req.on('end', async () => {
      let daten;
      try { daten = JSON.parse(roh); }
      catch (e) { return antworte(res, 400, { ok: false, fehler: 'Kein gültiges JSON.' }); }
      const ergebnis = await senden(daten.nummer, daten.text);
      antworte(res, ergebnis.ok ? 200 : 502, ergebnis);
    });
    return undefined;
  }

  if (req.method === 'POST' && req.url === '/abmelden') {
    client.logout()
      .then(() => { ich = null; setzeZustand('getrennt', 'Abgemeldet.'); })
      .catch(() => { });
    return antworte(res, 200, { ok: true });
  }

  return antworte(res, 404, { fehler: 'Unbekannter Aufruf.' });
});

// Ausdrücklich nur auf 127.0.0.1 - der Dienst darf niemals aus dem Netz
// erreichbar sein.
server.listen(PORT, '127.0.0.1', () => {
  console.log(`[WhatsApp] Dienst läuft auf http://127.0.0.1:${PORT}`);
  console.log(`[WhatsApp] Sitzung liegt in ${SITZUNGSORDNER}`);
});

client.initialize().catch((e) => {
  setzeZustand('fehler', 'Chromium ließ sich nicht starten: ' + e.message);
});

for (const zeichen of ['SIGINT', 'SIGTERM']) {
  process.on(zeichen, async () => {
    console.log('[WhatsApp] Wird beendet …');
    try { await client.destroy(); } catch (e) { /* egal */ }
    process.exit(0);
  });
}
