/* Der Worker unter Laborbedingungen: nachgebautes KV, nachgebauter Ursprung.
 *
 * Aufruf:  node tests/auffangnetz.mjs <file:///pfad/zu/worker.js>
 *
 * Der Worker laeuft bei Cloudflare und laesst sich hier nicht wirklich
 * betreiben. Was sich pruefen laesst, ist sein Verhalten: Was gibt er zurueck,
 * wenn der Ursprung 502 sagt? Nimmt er eine Meldung an, waehrend die Plattform
 * laeuft? Loescht er sie beim Abholen oder erst beim Bestaetigen? Genau das
 * sind die Stellen, an denen ein Auffangnetz still versagen koennte.
 *
 * Angebunden ist das an die Python-Suite (tests/test_auffangnetz.py), damit es
 * bei jedem Lauf mitgeprueft wird und nicht nur an dem Tag, an dem es
 * geschrieben wurde.
 */
const netz = (await import(process.argv[2])).default;

let ursprungStatus = 200;         // was der "Tunnel" antwortet
let ntfyRufe = [];
const lager = new Map();

const LAGER = {
  async get(k) { const e = lager.get(k); return e === undefined ? null : e; },
  async put(k, v) { lager.set(k, v); },
  async delete(k) { lager.delete(k); },
  async list({ prefix, limit }) {
    return { keys: [...lager.keys()].filter(k => k.startsWith(prefix))
                     .slice(0, limit).map(name => ({ name })) };
  },
};

const echtesFetch = globalThis.fetch;
globalThis.fetch = async (ziel, optionen) => {
  const adresse = typeof ziel === "string" ? ziel : ziel.url;
  if (adresse.includes("ntfy")) {
    ntfyRufe.push(JSON.parse(optionen.body));
    return new Response("ok", { status: 200 });
  }
  if (ursprungStatus === 0) { throw new TypeError("kein Netz"); }
  return new Response("echte Seite", { status: ursprungStatus });
};

const umgebung = { LAGER, ABHOL_SCHLUESSEL: "geheim-".padEnd(45, "x"),
                   NTFY_THEMA: "wag-ausfall-test" };
let fehler = 0;
function pruefe(name, bedingung, zusatz = "") {
  console.log((bedingung ? "  ok   " : "  FEHL ") + name + (bedingung ? "" : "   " + zusatz));
  if (!bedingung) { fehler += 1; }
}
const hole = (weg, opt = {}) =>
  netz.fetch(new Request("https://mvlg-wag.de" + weg, opt), umgebung);

/* --- 1. Normalbetrieb: nur durchleiten ---------------------------------- */
ursprungStatus = 200;
let a = await hole("/dashboard/aufgaben");
pruefe("Normalbetrieb wird unveraendert durchgeleitet",
       a.status === 200 && (await a.text()) === "echte Seite", a.status);

/* Ein 500 der Anwendung darf NICHT ueberdeckt werden */
ursprungStatus = 500;
a = await hole("/dashboard");
pruefe("Ein 500 der Anwendung bleibt sichtbar", a.status === 500, a.status);

/* --- 2. Ausfall: eigene Seite ------------------------------------------- */
for (const s of [502, 530, 521]) {
  ursprungStatus = s;
  a = await hole("/dashboard/kalender?x=1");
  const html = await a.text();
  pruefe(`Status ${s} liefert die eigene Seite`,
         a.status === 503 && html.includes("nicht erreichbar")
         && html.includes(String(s)), a.status);
}
ursprungStatus = 0;
a = await hole("/");
let html = await a.text();
pruefe("Gar keine Antwort liefert die eigene Seite",
       a.status === 503 && html.includes("keine Verbindung"));
pruefe("Seite traegt noindex und Retry-After",
       a.headers.get("x-robots-tag") === "noindex"
       && a.headers.get("retry-after") === "120");
pruefe("Seite ist in sich geschlossen (kein externer Verweis)",
       !/src="http|href="http|@import|fonts\./.test(html));
pruefe("Meldeknopf ist da, wenn ein Lager haengt",
       !/id="melden-auf" hidden/.test(html));
pruefe("Keine Emojis auf der Seite",
       !/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(html));

/* Ohne Lager: kein Knopf, der nichts tut */
a = await netz.fetch(new Request("https://mvlg-wag.de/"), { ABHOL_SCHLUESSEL: "x" });
html = await a.text();
pruefe("Ohne Lager wird der Meldeknopf ausgeblendet",
       /id="melden-auf" hidden/.test(html) && /id="melden" hidden/.test(html));

/* --- 3. Lebt-Nachfrage -------------------------------------------------- */
ursprungStatus = 0;
pruefe("lebt sagt nein, wenn nichts antwortet",
       (await (await hole("/__ausfall/lebt")).text()) === "nein");
ursprungStatus = 200;
pruefe("lebt sagt ja, sobald es wieder geht",
       (await (await hole("/__ausfall/lebt")).text()) === "ja");

/* --- 4. Meldungen ------------------------------------------------------- */
const senden = (koerper) => hole("/__ausfall/melden", {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify(koerper) });

ursprungStatus = 200;                       // Plattform laeuft -> Tuer zu
let r = await senden({ text: "Test" });
pruefe("Solange die Plattform laeuft, nimmt der Worker nichts an",
       r.status === 409 && (await r.json()).ok === false, r.status);

ursprungStatus = 0;                         // Ausfall -> Tuer offen
r = await senden({ text: "ab" });
pruefe("Zu kurzer Text wird abgelehnt", r.status === 400);

r = await senden({ text: "Ich wollte meine Aufgaben ansehen. Umlaute: äöüß",
                   name: "Max Muster", kontakt: "max@example.org",
                   lage: "/dashboard/aufgaben" });
pruefe("Meldung wird angenommen", r.status === 200 && (await r.json()).ok === true);
pruefe("Meldung liegt im Lager",
       [...lager.keys()].filter(k => k.startsWith("meldung:")).length === 1);
const meldungsRufe = () => ntfyRufe.filter(r => r.title.startsWith("Ausfallmeldung"));
pruefe("Telefon hat geklingelt", meldungsRufe().length === 1
       && meldungsRufe()[0].message.includes("Max Muster"),
       JSON.stringify(ntfyRufe));

/* Zweite Meldung: Ruhefrist -> gespeichert, aber kein zweites Klingeln */
await senden({ text: "Bei mir auch nicht", name: "Lena" });
pruefe("Zweite Meldung wird gespeichert",
       [...lager.keys()].filter(k => k.startsWith("meldung:")).length === 2);
pruefe("Aber das Telefon klingelt nicht zweimal", meldungsRufe().length === 1);

/* --- 5. Abholen und Bestaetigen ---------------------------------------- */
r = await hole("/__ausfall/abholen");
pruefe("Abholen ohne Schluessel wird verweigert", r.status === 403);
r = await hole("/__ausfall/abholen", { headers: { "x-ausfall-schluessel": "falsch" } });
pruefe("Falscher Schluessel wird verweigert", r.status === 403);
r = await hole("/__ausfall/abholen",
               { headers: { "x-ausfall-schluessel": umgebung.ABHOL_SCHLUESSEL } });
const paket = await r.json();
const liste = paket.meldungen;
pruefe("Mit Schluessel kommen beide Meldungen", liste.length === 2, liste.length);
pruefe("Und ein eigenes Fach fuer Bewerbungen",
       Array.isArray(paket.bewerbungen));
pruefe("Umlaute sind unbeschaedigt",
       liste.some(m => m.text.includes("äöüß")));
pruefe("Jede Meldung hat eine Kennung",
       liste.every(m => (m.kennung || "").startsWith("meldung:")));

/* Abholen loescht NICHT - erst das Bestaetigen */
pruefe("Abholen laesst die Meldungen liegen",
       [...lager.keys()].filter(k => k.startsWith("meldung:")).length === 2);
r = await hole("/__ausfall/bestaetigen", {
  method: "POST", headers: { "x-ausfall-schluessel": umgebung.ABHOL_SCHLUESSEL,
                             "content-type": "application/json" },
  body: JSON.stringify({ kennungen: liste.map(m => m.kennung) }) });
pruefe("Bestaetigen raeumt sie weg", (await r.json()).entfernt === 2
       && [...lager.keys()].filter(k => k.startsWith("meldung:")).length === 0);

/* --- 6. Deckel --------------------------------------------------------- */
ntfyRufe = [];
for (let i = 0; i < 35; i += 1) { await senden({ text: "Flut " + i }); }
const gespeichert = [...lager.keys()].filter(k => k.startsWith("meldung:")).length;
pruefe("Der Deckel je Stunde greift", gespeichert <= 30, gespeichert);


/* --- 7. Alibi-Inhalt fuer Besucher ------------------------------------- */
ursprungStatus = 0;
a = await hole("/");
html = await a.text();
pruefe("Oeffentliche Seite bringt die ganze Startseite",
       html.includes("Max-von-Laue-Gymnasium")
       && html.includes("Zwei Halbjahre") && html.includes("Dein Weg")
       && html.includes("Von Sch"));
pruefe("Und ein vollstaendiges Bewerbungsformular",
       html.includes('id="bewerbung-formular"') && html.includes("b-motivation")
       && html.includes("b-telefon") && html.includes("b-vorwissen")
       && html.includes('value="recruitment"'));
pruefe("Mit Honigtopf gegen Skripte", html.includes("b-webseite"));
a = await netz.fetch(new Request("https://app.mvlg-wag.de/dashboard"), umgebung);
const dashHtml = await a.text();
pruefe("Auf dem Dashboard bleibt das alles weg",
       !dashHtml.includes('id="bewerbung-formular"')
       && !dashHtml.includes("Zwei Halbjahre")
       && !dashHtml.includes("%%LANDING%%"));

/* --- 8. Ehrliche Rueckmeldung ueber das Klingeln ------------------------ */
ntfyRufe = [];
lager.delete("klingel");
// Der Stundendeckel aus Abschnitt 6 steht noch - hier faengt ein neuer Fall an.
[...lager.keys()].filter(k => k.startsWith("zaehler:")).forEach(k => lager.delete(k));
r = await senden({ text: "Mit Thema", name: "Anna" });
let d = await r.json();
pruefe("Mit ntfy-Thema meldet der Worker das Klingeln",
       d.ok === true && d.geklingelt === true, JSON.stringify(d));

const ohneThema = { LAGER, ABHOL_SCHLUESSEL: umgebung.ABHOL_SCHLUESSEL };
r = await netz.fetch(new Request("https://mvlg-wag.de/__ausfall/melden", {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ text: "Ohne Thema" }) }), ohneThema);
d = await r.json();
pruefe("Ohne Thema wird kein Klingeln behauptet",
       d.ok === true && d.geklingelt === false
       && /NTFY_THEMA/.test(d.klingelgrund || ""), JSON.stringify(d));

/* --- 9. Selbsttest ------------------------------------------------------ */
r = await hole("/__ausfall/selbsttest");
html = await r.text();
pruefe("Selbsttest antwortet", r.status === 200 && html.includes("Selbsttest"));
pruefe("Selbsttest nennt die vier Bausteine",
       html.includes("Zwischenspeicher") && html.includes("Abholschluessel")
       && html.includes("ntfy-Thema") && html.includes("Meldungen"));
pruefe("Selbsttest verraet keine Geheimnisse",
       !html.includes(umgebung.ABHOL_SCHLUESSEL)
       && !html.includes(umgebung.NTFY_THEMA));

r = await netz.fetch(new Request("https://mvlg-wag.de/__ausfall/selbsttest"),
                     { ABHOL_SCHLUESSEL: "x" });
html = await r.text();
pruefe("Fehlendes KV wird als offener Punkt gezeigt",
       html.includes("fehlt") && html.includes("Punkt"));

/* --- 8b. Bewerbungen ---------------------------------------------------- */
//  Der wichtigste Teil: Eine Bewerbung darf unter keinen Umstaenden verloren
//  gehen, auch nicht, wenn die Plattform mitten im Tippen zurueckkommt.
const bewerbung = (zusatz) => hole("/__ausfall/bewerben", {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify(Object.assign({
    vorname: "Mara", nachname: "Winkler", klasse: "11",
    abteilung: "tech", email: "mara@example.org",
    telefonnummer: "0163 1234567",
    motivation: "Ich interessiere mich sehr fuer Boerse und will endlich "
              + "verstehen, wie das mit den Aktien laeuft.",
    interessen: "Boerse, Gruenden", vorwissen: "Keines",
  }, zusatz || {})) });

[...lager.keys()].filter(k => k.startsWith("bzaehler:")).forEach(k => lager.delete(k));
ursprungStatus = 0;
r = await bewerbung();
pruefe("Bewerbung wird angenommen", r.status === 200 && (await r.json()).ok === true);
pruefe("Und liegt im Lager",
       [...lager.keys()].filter(k => k.startsWith("bewerbung:")).length === 1);

ursprungStatus = 200;                       // Plattform kommt zurueck
r = await bewerbung({ email: "zweite@example.org" });
pruefe("Auch wenn die Plattform wieder laeuft, wird sie angenommen",
       r.status === 200 && (await r.json()).ok === true);
pruefe("Eine Bewerbung geht also nie verloren",
       [...lager.keys()].filter(k => k.startsWith("bewerbung:")).length === 2);
ursprungStatus = 0;

r = await bewerbung({ email: "keine-mail" });
pruefe("Unsinnige E-Mail wird abgelehnt", r.status === 400);
r = await bewerbung({ abteilung: "exekutive" });
pruefe("In die Exekutive bewirbt man sich nicht", r.status === 400);
r = await bewerbung({ motivation: "kurz" });
pruefe("Zu kurze Motivation wird abgelehnt", r.status === 400);
r = await bewerbung({ vorname: "" });
pruefe("Fehlendes Pflichtfeld wird abgelehnt", r.status === 400);

const vorher = [...lager.keys()].filter(k => k.startsWith("bewerbung:")).length;
r = await bewerbung({ webseite: "http://spam.example" });
pruefe("Der Honigtopf schluckt Skripte still",
       r.status === 200 && (await r.json()).still === true
       && [...lager.keys()].filter(k => k.startsWith("bewerbung:")).length === vorher);

r = await hole("/__ausfall/abholen",
               { headers: { "x-ausfall-schluessel": umgebung.ABHOL_SCHLUESSEL } });
const gepackt = await r.json();
pruefe("Bewerbungen kommen mit der Abholung",
       gepackt.bewerbungen.length === 2, gepackt.bewerbungen.length);
pruefe("Vollstaendig und mit Zeitpunkt",
       gepackt.bewerbungen.every(b => b.vorname && b.email && b.abteilung
                                      && b.zeitpunkt && b.kennung));
r = await hole("/__ausfall/bestaetigen", {
  method: "POST", headers: { "x-ausfall-schluessel": umgebung.ABHOL_SCHLUESSEL,
                             "content-type": "application/json" },
  body: JSON.stringify({ kennungen: gepackt.bewerbungen.map(b => b.kennung) }) });
pruefe("Und lassen sich bestaetigen",
       (await r.json()).entfernt === 2
       && [...lager.keys()].filter(k => k.startsWith("bewerbung:")).length === 0);

/* --- 8c. Alarm beim Ausfall --------------------------------------------- */
//  Der Alarm laeuft absichtlich NEBEN der Antwort - der Besucher soll seine
//  Seite sofort bekommen. Im Betrieb erledigt das Cloudflare mit waitUntil;
//  hier muss kurz gewartet werden, sonst prueft man, bevor es passiert ist.
const ruhe = () => new Promise(r => setTimeout(r, 30));
//  Gewuenscht: Merkt der Worker, dass nichts antwortet, soll der CTO das
//  sofort erfahren - ohne dass jemand einen Knopf druecken muss.
lager.clear();
ntfyRufe = [];
const alarme = (was) => ntfyRufe.filter(r => r.title.includes(was)).length;

ursprungStatus = 0;
await hole("/"); await ruhe();
pruefe("Der erste Ausfall meldet sich von selbst",
       alarme("NICHT erreichbar") === 1, JSON.stringify(ntfyRufe));

await hole("/dashboard/aufgaben");
await hole("/bewerbung"); await ruhe();
pruefe("Aber nicht bei jedem Seitenaufruf erneut",
       alarme("NICHT erreichbar") === 1, alarme("NICHT erreichbar"));

ursprungStatus = 200;
await hole("/__ausfall/lebt"); await ruhe();
pruefe("Die Rueckkehr gibt Entwarnung",
       alarme("wieder erreichbar") === 1, JSON.stringify(ntfyRufe));

ursprungStatus = 0;
lager.delete("alarm_ausfall");        // Ruhefrist beiseite, neuer Ausfall
await hole("/"); await ruhe();
pruefe("Ein zweiter Ausfall meldet sich wieder",
       alarme("NICHT erreichbar") === 2, alarme("NICHT erreichbar"));

// Die Ruhefrist faengt ab, was der Zustandsmerker nicht schafft.
lager.delete("zustand");
await hole("/"); await ruhe();
pruefe("Die Ruhefrist verhindert eine Salve",
       alarme("NICHT erreichbar") === 2, alarme("NICHT erreichbar"));

ntfyRufe = [];
await netz.fetch(new Request("https://mvlg-wag.de/"), { NTFY_THEMA: "x" });
await ruhe();
pruefe("Ohne Lager wird kein Alarm geraten", ntfyRufe.length === 0);

lager.clear();
ntfyRufe = [];
ursprungStatus = 200;
await hole("/"); await ruhe();
pruefe("Die erste Beobachtung im Normalbetrieb klingelt nicht",
       ntfyRufe.length === 0, JSON.stringify(ntfyRufe));

/* --- 8d. Ein behobener Fehler bleibt nicht rot -------------------------- */
//  Gemeldet: "der Selbsttest sagt trotzdem nein" - obwohl alles eingerichtet
//  war. Es stand nur noch ein Fehlereintrag von vorher da. Wer eine Warnung
//  sieht, die nichts mehr bedeutet, glaubt der naechsten auch nicht mehr.
lager.clear();
ntfyRufe = [];
ursprungStatus = 0;
// Erst ein Fehlschlag ohne Thema, dann ein Erfolg mit.
await netz.fetch(new Request("https://mvlg-wag.de/"), { LAGER }); await ruhe();
pruefe("Ein Fehlschlag wird vermerkt",
       Boolean(await LAGER.get("klingel_fehler")));
r = await hole("/__ausfall/selbsttest");
html = await r.text();
pruefe("Er steht im Selbsttest, zaehlt aber nicht als offener Punkt",
       html.includes("Letzter Fehler beim Klingeln")
       && !/class="stand offen"/.test(html), html.slice(0, 0) || "");

lager.delete("zustand");
lager.delete("alarm_ausfall");
await hole("/"); await ruhe();          // jetzt mit Thema
pruefe("Ein geglueckter Ruf raeumt ihn weg",
       (await LAGER.get("klingel_fehler")) === null,
       String(await LAGER.get("klingel_fehler")));

/* --- 9b. Fassung nachweisbar -------------------------------------------- */
//  Ohne Kennzeichen laesst sich "ich habe den neuen Code eingespielt, aber
//  die Seite sieht aus wie vorher" nicht beantworten.
ursprungStatus = 0;
a = await hole("/");
html = await a.text();
const fassung = a.headers.get("x-auffangnetz");
pruefe("Fehlerseite traegt die Fassung als Kopfzeile", Boolean(fassung), fassung);
pruefe("Und sichtbar im Fusstext", html.includes(fassung));
r = await hole("/__ausfall/selbsttest");
html = await r.text();
pruefe("Selbsttest nennt dieselbe Fassung",
       r.headers.get("x-auffangnetz") === fassung && html.includes(fassung));

/* --- 10. Probemeldung --------------------------------------------------- */
ntfyRufe = [];
lager.delete("probe");
r = await hole("/__ausfall/probe", { method: "POST" });
pruefe("Probemeldung geht raus", r.status === 200 && ntfyRufe.length === 1,
       JSON.stringify(ntfyRufe));
r = await hole("/__ausfall/probe", { method: "POST" });
pruefe("Und laesst sich nicht als Klingelstreich missbrauchen",
       r.status === 429 && ntfyRufe.length === 1);

globalThis.fetch = echtesFetch;
/* Schlusszeile bewusst ohne Umlaute: Sie wird von der Python-Suite
   gelesen, und Windows liest Prozessausgaben nicht immer als UTF-8. */
console.log("");
console.log(fehler ? fehler + " PRUEFUNG(EN) FEHLGESCHLAGEN"
                   : "ALLE PRUEFUNGEN BESTANDEN");
process.exit(fehler ? 1 : 0);
