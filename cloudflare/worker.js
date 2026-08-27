/**
 * Auffangnetz vor der Plattform.
 *
 * Laeuft bei Cloudflare am Rand des Netzes, nicht auf dem Laptop. Normalerweise
 * leitet er einfach durch. Antwortet der Tunnel nicht - Laptop aus, cloudflared
 * beendet, Anwendung abgestuerzt -, zeigte Cloudflare bisher seine eigene
 * Fehlerseite: "Error 1033", englisch, mit fremdem Logo. Wer die zum ersten Mal
 * sieht, haelt die AG fuer unserioes und nicht den Rechner fuer aus.
 *
 * Ab jetzt kommt stattdessen eine eigene Seite, die drei Dinge tut:
 *   1. in einem Satz sagen, was los ist,
 *   2. von selbst weiterprobieren und laden, sobald es wieder geht,
 *   3. eine Meldung an den CTO aufnehmen - denn wenn nichts laeuft, kann man
 *      sich auch nicht anmelden, um es zu melden.
 *
 * Die Meldung wird bei Cloudflare zwischengelagert (KV) und, wenn ein Thema
 * eingetragen ist, sofort per ntfy aufs Telefon geschickt. Sobald die Plattform
 * wieder laeuft, holt sie die Meldungen ab und macht echte Support-Tickets
 * daraus (kern/ausfallmeldungen.py).
 *
 * Grundregel fuer alles hier drin: Ein Fehler im Auffangnetz darf die Seite
 * nicht schlechter machen als ohne Netz. Deshalb ist der Normalfall ein
 * blankes Durchleiten, und jeder Zusatz steht in einem eigenen try.
 */

/* Stylesheet, Schriften, Wappen und die pflegbaren Bloecke der Startseite.
 *
 * Erzeugt aus statisch/ - nicht von Hand pflegen:
 *
 *     python werkzeuge/auffangnetz_bauen.py
 *
 * Sie muessen mit in die Datei: Der Server, von dem sie sonst kaemen, ist
 * genau der ausgefallene. */
import { SCHRIFTEN, STIL, WAPPEN, LOGO, FAVICON, ABTEILUNGEN, QUIZ_JS,
         QUIZ_FRAGEN, INHALTE } from "./eingebettet.js";

/* Welche Fassung gerade laeuft.
 *
 * Gebaut nach der Frage "ich habe den neuen Code eingespielt, aber die Seite
 * sieht aus wie vorher". Ohne Kennzeichen ist das nicht zu beantworten, ohne
 * die halbe Seite abzusuchen - und bei einem Auffangnetz, das man nur alle
 * paar Monate anfasst, ist genau das die Frage, die man jedes Mal hat.
 *
 * Die Nummer steht an drei Stellen: als Kopfzeile x-auffangnetz auf jeder
 * Antwort, die vom Worker selbst kommt, im Selbsttest und klein unten auf der
 * Fehlerseite. Bei jeder Aenderung hochzaehlen. */
const FASSUNG = "2026-08-27-a";

/* Diese Antworten kommen von Cloudflare selbst und heissen "die Anwendung war
   nicht erreichbar". Ein blankes 500 steht bewusst NICHT dabei: Das hat die
   Anwendung selbst geschickt, sie laeuft also - und ihre eigene Fehlerseite ist
   dann die richtige Antwort, nicht unsere. */
const NICHT_ERREICHBAR = new Set(
  [502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530]);

/* Hoechstlaengen fuer die Meldung. Ohne Grenze waere das offene Feld eine
   Einladung, den Speicher vollzuschreiben. */
const MAX_TEXT = 2000;
const MAX_NAME = 80;
const MAX_KONTAKT = 120;

/* Wie lange eine Meldung bei Cloudflare liegen bleibt, wenn sie niemand
   abholt. Vier Wochen: laenger als jeder Ausfall, den wir ueberleben wollen. */
const AUFBEWAHRUNG_SEKUNDEN = 60 * 60 * 24 * 28;

/* Fruehestens so oft klingelt das Telefon des CTO wegen Ausfallmeldungen.
   Faellt die Plattform waehrend einer AG-Stunde aus, melden es sonst acht Leute
   hintereinander - und beim achten Mal schaltet er die Meldungen ab. */
const KLINGEL_RUHE_SEKUNDEN = 600;

/* Mehr Meldungen als das nimmt der Worker pro Stunde nicht an. Die Adresse ist
   oeffentlich; ohne Deckel waere sie ein Briefkasten fuer jeden. */
const MELDUNGEN_JE_STUNDE = 30;

/* Dasselbe fuer Bewerbungen, aber grosszuegiger: Eine verlorene Bewerbung ist
   teurer als eine doppelte. Der Deckel ist nur gegen Fluten da, nicht gegen
   den zweiten Versuch eines Menschen. */
const BEWERBUNGEN_JE_STUNDE = 60;

/* Schuladressen kommen nicht durch - dieselbe Regel wie im echten Formular
   (website/routen/bewerbung.py). Hier draussen geprueft, damit die Person es
   sofort erfaehrt und nicht erst, wenn die Plattform Stunden spaeter einliest
   und die Bewerbung stillschweigend verwirft. */
const GESPERRTE_MAILDOMAENEN = ["mvlg-ko.de"];

/* In welche Abteilung man sich bewerben kann, kommt aus eingebettet.js - beim
   Bauen aus der Datenbank gelesen. Von Hand gepflegt lag die Liste prompt
   daneben: "Unsicher" gab es im echten Formular seit einer Weile, hier nie.
   Die Exekutive ist nicht dabei; in die bewirbt man sich nicht. */


export default {
  async fetch(anfrage, umgebung, ablauf) {
    const adresse = new URL(anfrage.url);

    /* Die eigenen Wege des Auffangnetzes. Sie beginnen mit zwei Unterstrichen,
       damit sie mit keinem Weg der Anwendung zusammenstossen koennen. */
    if (adresse.pathname === "/__ausfall/melden" && anfrage.method === "POST") {
      return meldungAufnehmen(anfrage, umgebung, adresse);
    }
    if (adresse.pathname === "/__ausfall/bewerben"
        && anfrage.method === "POST") {
      return bewerbungAufnehmen(anfrage, umgebung);
    }
    if (adresse.pathname === "/__ausfall/nachricht"
        && anfrage.method === "POST") {
      return nachrichtAufnehmen(anfrage, umgebung);
    }
    if (adresse.pathname === "/__ausfall/abholen") {
      return meldungenAusliefern(anfrage, umgebung);
    }
    if (adresse.pathname === "/__ausfall/bestaetigen"
        && anfrage.method === "POST") {
      return meldungenBestaetigen(anfrage, umgebung);
    }
    if (adresse.pathname === "/__ausfall/selbsttest") {
      return selbsttest(anfrage, umgebung);
    }
    if (adresse.pathname === "/__ausfall/probe" && anfrage.method === "POST") {
      return probeKlingeln(umgebung);
    }
    if (adresse.pathname === "/__ausfall/lebt") {
      /* Von der Fehlerseite aus gefragt: Geht es wieder? Absichtlich ein
         eigener Weg und nicht "/" - so kostet die Nachfrage keine ganze
         Seite und verfaengt sich nicht in einem Zwischenspeicher. */
      const lebt = await erreichbar(anfrage);
      /* Genau hier kommt die Entwarnung her: Die Fehlerseite fragt alle paar
         Sekunden nach, also merkt der Worker die Rueckkehr in dem Moment, in
         dem sie passiert - ohne dafuer selbst pollen zu muessen. */
      nebenbei(ablauf, zustandPflegen(umgebung, lebt, "", true));
      return new Response(lebt ? "ja" : "nein", {
        headers: { "content-type": "text/plain; charset=utf-8",
                   "cache-control": "no-store" },
      });
    }

    /* Aufgeruestete Verbindungen (WebSocket) nicht anfassen - eine solche
       Antwort laesst sich nicht anschauen, ohne sie zu zerstoeren. */
    if (anfrage.headers.get("Upgrade")) {
      return fetch(anfrage);
    }

    try {
      /* Eine zuvor ausgelieferte Notfallseite darf weder aus dem Browser-
         noch aus einem vorgeschalteten Cache wiederkommen. Der Reload-
         Parameter wird nicht an die eigentliche Anwendung weitergegeben. */
      const weiterleitung = new URL(anfrage.url);
      weiterleitung.searchParams.delete("_auffangnetz_reload");
      const ursprungsAnfrage = new Request(weiterleitung.toString(), anfrage);
      const antwort = await fetch(ursprungsAnfrage, { cache: "no-store" });
      if (!NICHT_ERREICHBAR.has(antwort.status)) {
        /* Im Normalbetrieb hoechstens einmal je Minute nachhalten - eine
           KV-Abfrage bei JEDER Anfrage waere die teuerste Zeile der ganzen
           Datei, und der Worker steht vor allem. */
        if (Date.now() - letzteZustandspflege > 60000) {
          letzteZustandspflege = Date.now();
          nebenbei(ablauf, zustandPflegen(umgebung, true, "", false));
        }
        return antwort;
      }
      const grund = String(antwort.status);
      nebenbei(ablauf, zustandPflegen(umgebung, false, grund, false));
      return ausfallseite(adresse, umgebung, grund);
    } catch (fehler) {
      /* Kam gar keine Antwort zustande. Fuer den Nutzer dasselbe Bild. */
      nebenbei(ablauf, zustandPflegen(umgebung, false, "keine Verbindung",
                                      false));
      return ausfallseite(adresse, umgebung, "keine Verbindung");
    }
  },

  /**
   * Nur aktiv, wenn in wrangler.toml ein Zeitplan eingetragen ist.
   *
   * Der Worker sieht einen Ausfall sonst erst, wenn jemand die Seite oeffnet.
   * Faellt die Plattform Freitagabend aus, erfaehrt es niemand bis Montag.
   * Diese Uhr schaut regelmaessig nach und meldet den Wechsel - einmal beim
   * Ausfall, einmal bei der Rueckkehr, nicht dazwischen.
   */
  async scheduled(_ereignis, umgebung) {
    if (!umgebung.LAGER) { return; }
    let lebt = false;
    let grund = "keine Verbindung";
    try {
      const antwort = await fetch(
        umgebung.PRUEF_ADRESSE || "https://mvlg-wag.de/",
        { method: "GET", redirect: "manual",
          headers: { "user-agent": "WAG-Auffangnetz" } });
      lebt = !NICHT_ERREICHBAR.has(antwort.status);
      grund = String(antwort.status);
    } catch (fehler) {
      lebt = false;
    }
    /* Dieselbe Stelle wie im Seitenweg. Zwei Fassungen derselben Regel gehen
       irgendwann auseinander, und dann klingelt es zweimal oder gar nicht. */
    await zustandPflegen(umgebung, lebt, grund, false);
  },
};


/* ------------------------------------------------------------------------- */
/*  Alarm beim Ausfall                                                       */
/* ------------------------------------------------------------------------- */

/* Wann dieses Isolat zuletzt nachgehalten hat, dass alles laeuft. Steht im
   Arbeitsspeicher und ueberlebt keinen Neustart - genau richtig: Der Wert
   soll nur verhindern, dass bei jeder einzelnen Anfrage eine KV-Abfrage
   anfaellt. Geht er verloren, wird eben einmal zu frueh nachgesehen. */
let letzteZustandspflege = 0;

/* Fruehestens so oft klingelt derselbe Alarm erneut. Der Zustandsmerker
   allein reicht nicht: KV ist nicht sofort ueberall gleich, und wenn acht
   Leute im selben Moment die Seite oeffnen, koennen mehrere davon noch den
   alten Wert lesen. Diese Frist faengt das ab. */
const ALARM_RUHE_SEKUNDEN = 300;

/**
 * Nebenbei erledigen, ohne die Antwort aufzuhalten.
 *
 * Der Besucher soll seine Seite sofort bekommen; ob danach noch ein Telefon
 * klingelt, geht ihn nichts an. Ohne `ablauf` (etwa im Labor) wird schlicht
 * gewartet - dann ist der Ablauf derselbe, nur langsamer.
 */
function nebenbei(ablauf, versprechen) {
  if (ablauf && typeof ablauf.waitUntil === "function") {
    ablauf.waitUntil(versprechen.catch(() => {}));
    return null;
  }
  return versprechen.catch(() => {});
}

/**
 * Den Zustand nachhalten und beim Wechsel den CTO benachrichtigen.
 *
 * Gewuenscht: "Wenn der Worker checkt, dass das System down ist, soll er
 * unverzueglich den CTO benachrichtigen." Bis jetzt erfuhr er es nur, wenn
 * jemand von Hand auf "Dem CTO melden" tippte - also fruehestens dann, wenn
 * ueberhaupt jemand die Seite aufrief und sich die Muehe machte.
 *
 * Gemeldet wird der WECHSEL, nicht der Zustand. Sonst klingelt es bei jedem
 * einzelnen Seitenaufruf: Acht Leute in einer AG-Stunde waeren acht
 * Nachrichten, und beim dritten Mal schaltet man sie ab.
 *
 * Die Entwarnung gehoert dazu. Ohne sie weiss niemand, ob es behoben ist
 * oder nur gerade niemand hinsieht - und der Merker bliebe auf "aus"
 * stehen, sodass der naechste echte Ausfall stumm bliebe.
 */
async function zustandPflegen(umgebung, lebt, grund, nurEntwarnung) {
  if (!umgebung.LAGER) { return "kein Lager"; }
  const jetzt = lebt ? "lebt" : "aus";
  const vorher = await umgebung.LAGER.get("zustand");
  if (vorher === jetzt) { return "unveraendert"; }
  /* Beim allerersten Lauf steht nichts im Lager. Dann ist das kein Wechsel,
     sondern nur die erste Beobachtung - eine Entwarnung fuer einen Ausfall,
     den es nie gab, waere Unsinn. Ein Ausfall dagegen wird gemeldet: Er ist
     auch dann echt, wenn wir vorher nichts wussten. */
  const erstesMal = vorher === null || vorher === undefined;
  await umgebung.LAGER.put("zustand", jetzt);
  if (nurEntwarnung && !lebt) { return "nicht zustaendig"; }
  if (erstesMal && lebt) { return "erste Beobachtung"; }

  const marke = lebt ? "alarm_entwarnung" : "alarm_ausfall";
  const zuletzt = parseInt(await umgebung.LAGER.get(marke) || "0", 10);
  const sekunden = Math.floor(Date.now() / 1000);
  if (sekunden - zuletzt < ALARM_RUHE_SEKUNDEN) { return "in der Ruhefrist"; }
  await umgebung.LAGER.put(marke, String(sekunden), { expirationTtl: 86400 });

  const ergebnis = await klingeln(umgebung, lebt
    ? ["Plattform ist wieder erreichbar",
       "Der Tunnel antwortet wieder. Was während des Ausfalls gemeldet oder "
       + "beworben wurde, wird jetzt eingetragen."]
    : ["Plattform ist NICHT erreichbar",
       "Besucher sehen gerade die Notfassung"
       + (grund ? " (" + grund + ")" : "") + ". Läuft der Rechner, und läuft "
       + "start.bat? Bewerbungen werden weiter angenommen."]);
  if (!ergebnis.ok) {
    await umgebung.LAGER.put("klingel_fehler",
                             new Date().toISOString() + " - " + ergebnis.grund,
                             { expirationTtl: 604800 });
  }
  return ergebnis.ok ? "gemeldet" : "Klingeln fehlgeschlagen";
}


/* ------------------------------------------------------------------------- */
/*  Meldungen                                                               */
/* ------------------------------------------------------------------------- */

/** Laeuft die Plattform gerade doch? Kurze Frist, das ist nur eine Nachfrage. */
async function erreichbar(anfrage) {
  const ziel = new URL(anfrage.url);
  ziel.pathname = "/";
  ziel.search = "";
  try {
    const antwort = await fetch(ziel.toString(), {
      method: "GET", redirect: "manual",
      headers: { "user-agent": "WAG-Auffangnetz" },
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    return !NICHT_ERREICHBAR.has(antwort.status);
  } catch (fehler) {
    return false;
  }
}

/**
 * Eine Meldung von der Fehlerseite annehmen.
 *
 * Zuerst wird geprueft, ob die Plattform ueberhaupt aus ist. Das ist keine
 * Foermlichkeit, sondern der Tuersteher: Die Adresse ist oeffentlich, und
 * solange die Plattform laeuft, nimmt sie nichts an - dann gehoert eine Meldung
 * ins Dashboard, wo sie einen Absender hat. Damit ist der offene Briefkasten
 * nur in genau den Minuten offen, in denen er gebraucht wird.
 */
async function meldungAufnehmen(anfrage, umgebung, adresse) {
  const kopf = { "content-type": "application/json; charset=utf-8",
                 "cache-control": "no-store" };

  if (await erreichbar(anfrage)) {
    return new Response(JSON.stringify({
      ok: false,
      grund: "Die Plattform antwortet wieder. Lade die Seite neu und melde es "
           + "im Dashboard unter Support - dort weiss man dann auch, von wem "
           + "die Meldung kommt.",
    }), { status: 409, headers: kopf });
  }

  if (!umgebung.LAGER) {
    return new Response(JSON.stringify({
      ok: false,
      grund: "Das Meldefeld ist noch nicht eingerichtet (es fehlt der "
           + "Zwischenspeicher). Bitte den CTO direkt erreichen.",
    }), { status: 503, headers: kopf });
  }

  let daten;
  try {
    daten = await anfrage.json();
  } catch (fehler) {
    return new Response(
      JSON.stringify({ ok: false, grund: "Unlesbare Angaben." }),
      { status: 400, headers: kopf });
  }

  const text = kuerzen(daten.text, MAX_TEXT);
  if (text.length < 3) {
    return new Response(JSON.stringify({
      ok: false, grund: "Schreib bitte kurz, was du gemacht hast.",
    }), { status: 400, headers: kopf });
  }

  /* Deckel je Stunde. Der Zaehler laeuft mit der Stunde ab, deshalb braucht ihn
     niemand aufzuraeumen. */
  const stunde = "zaehler:" + new Date().toISOString().slice(0, 13);
  const bisher = parseInt(await umgebung.LAGER.get(stunde) || "0", 10);
  if (bisher >= MELDUNGEN_JE_STUNDE) {
    return new Response(JSON.stringify({
      ok: false,
      grund: "Es sind gerade sehr viele Meldungen eingegangen - der CTO weiss "
           + "also Bescheid. Danke trotzdem.",
    }), { status: 429, headers: kopf });
  }
  await umgebung.LAGER.put(stunde, String(bisher + 1), { expirationTtl: 7200 });

  const meldung = {
    text: text,
    name: kuerzen(daten.name, MAX_NAME),
    kontakt: kuerzen(daten.kontakt, MAX_KONTAKT),
    lage: kuerzen(daten.lage, 200),
    seite: adresse.hostname,
    grund: kuerzen(daten.grund, 60),
    zeitpunkt: new Date().toISOString(),
    land: anfrage.headers.get("cf-ipcountry") || "",
  };
  const kennung = "meldung:" + meldung.zeitpunkt + "-"
                + crypto.randomUUID().slice(0, 8);
  await umgebung.LAGER.put(kennung, JSON.stringify(meldung),
                           { expirationTtl: AUFBEWAHRUNG_SEKUNDEN });

  /* Das Telefon ist der schnelle Weg, das Ticket der verlaessliche. Scheitert
     das Klingeln, ist die Meldung trotzdem gespeichert - deshalb steht es
     hinter der Speicherung und nicht davor.

     Das Ergebnis geht mit zurueck, damit die Seite nicht mehr behaupten muss,
     was sie nicht weiss. Vorher stand dort immer "der CTO bekommt sofort eine
     Meldung aufs Telefon" - auch dann, wenn gar kein Thema hinterlegt war. */
  let klingel = { ok: false, grund: "nicht versucht" };
  try {
    klingel = await klingelnMitRuhe(umgebung, meldung);
  } catch (fehler) {
    klingel = { ok: false, grund: fehler.name };
  }

  return new Response(JSON.stringify({
    ok: true, geklingelt: Boolean(klingel.ok), klingelgrund: klingel.grund || "",
  }), { headers: kopf });
}

/**
 * Eine Nachricht aus dem Kontaktformular annehmen.
 *
 * Das Formular steht auf der Startseite, und die Startseite steht seit dieser
 * Fassung auch dann, wenn der Server aus ist. Ein Formular, das freundlich
 * aussieht und nichts tut, waere schlimmer als gar keins: Die Person wartet
 * auf eine Antwort, die nie kommt, und haelt uns fuer unzuverlaessig - nicht
 * den Rechner fuer aus.
 *
 * Dieselbe Regel wie bei der Bewerbung: Es wird NICHT geprueft, ob die
 * Plattform vielleicht doch laeuft. Wer gerade tippt, hat die Seite vorher
 * geladen; ihn jetzt abzuweisen hiesse, seinen Text wegzuwerfen.
 *
 * Aus den Angaben wird beim naechsten Hochfahren eine echte Kontaktanfrage
 * (kern/ausfallmeldungen.py) - also genau das, was auch das richtige Formular
 * anlegt, mit Antwortmoeglichkeit per E-Mail.
 */
async function nachrichtAufnehmen(anfrage, umgebung) {
  const kopf = { "content-type": "application/json; charset=utf-8",
                 "cache-control": "no-store" };
  const nein = (grund, status) => new Response(
    JSON.stringify({ ok: false, grund: grund }),
    { status: status || 400, headers: kopf });

  if (!umgebung.LAGER) {
    return nein("Der Zwischenspeicher ist nicht eingerichtet.", 503);
  }

  let daten;
  try {
    daten = await anfrage.json();
  } catch (fehler) {
    return nein("Unlesbare Angaben.");
  }

  /* Der Honigtopf. Nach aussen so tun, als sei alles gut - sonst lernt der
     Automat, was ihn verraet. Dieselbe Regel wie im echten Formular
     (website/routen/oeffentlich.py). */
  if (kuerzen(daten.webseite, 40)) {
    return new Response(JSON.stringify({ ok: true }), { headers: kopf });
  }

  const name = kuerzen(daten.name, MAX_NAME);
  const post = kuerzen(daten.email, MAX_KONTAKT).toLowerCase();
  const text = kuerzen(daten.nachricht, MAX_TEXT);
  if (!name || !text) { return nein("Bitte Name und Nachricht ausfüllen."); }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(post)) {
    return nein("Diese E-Mail-Adresse sieht nicht richtig aus.");
  }
  if (text.length < 10) {
    return nein("Ein paar Worte mehr bitte – so können wir nichts damit "
              + "anfangen.");
  }

  const stunde = "zaehler-n:" + new Date().toISOString().slice(0, 13);
  const bisher = parseInt(await umgebung.LAGER.get(stunde) || "0", 10);
  if (bisher >= MELDUNGEN_JE_STUNDE) {
    return nein("Es sind gerade sehr viele Nachrichten eingegangen. Bitte "
              + "später noch einmal.", 429);
  }
  await umgebung.LAGER.put(stunde, String(bisher + 1), { expirationTtl: 7200 });

  const nachricht = {
    name: name, email: post, nachricht: text,
    zeitpunkt: new Date().toISOString(),
  };
  await umgebung.LAGER.put(
    "nachricht:" + nachricht.zeitpunkt + "-" + crypto.randomUUID().slice(0, 8),
    JSON.stringify(nachricht), { expirationTtl: AUFBEWAHRUNG_SEKUNDEN });

  return new Response(JSON.stringify({ ok: true }), { headers: kopf });
}

/**
 * Eine Bewerbung annehmen, waehrend die Plattform aus ist.
 *
 * Hier gilt eine andere Regel als bei den Stoerungsmeldungen: Es wird NICHT
 * geprueft, ob die Plattform vielleicht doch wieder laeuft, und es wird nichts
 * abgelehnt, was sich noch retten laesst. Eine Bewerbung ist der einzige
 * Grund, aus dem ein Fremder diese Seite je aufruft - sie zu verlieren, weil
 * gerade ein Rechner aus war, waere der teuerste Fehler, den diese Anlage
 * machen kann. Eine doppelte Bewerbung sieht man und loescht sie; eine
 * fehlende sieht niemand.
 *
 * Geprueft wird trotzdem, aber nur so weit, dass nichts Unbrauchbares
 * gespeichert wird. Die eigentliche Pruefung macht die Plattform beim
 * Einlesen noch einmal - hier draussen ist niemandem zu trauen, auch nicht
 * dem eigenen Formular.
 */
async function bewerbungAufnehmen(anfrage, umgebung) {
  const kopf = { "content-type": "application/json; charset=utf-8",
                 "cache-control": "no-store" };
  const nein = (grund, status) => new Response(
    JSON.stringify({ ok: false, grund }), { status: status || 400, headers: kopf });

  if (!umgebung.LAGER) {
    return nein("Das Bewerbungsfeld ist gerade nicht eingerichtet. Schreib "
              + "bitte an cto@tech.mvlg-wag.de - so geht nichts verloren.", 503);
  }

  let daten;
  try {
    daten = await anfrage.json();
  } catch (fehler) {
    return nein("Unlesbare Angaben.");
  }

  /* Honigtopf. Ein Mensch sieht dieses Feld nicht, ein Skript fuellt alles
     aus. Freundlich tun, nichts speichern - sonst weiss der Absender, woran
     er gescheitert ist, und probiert es ohne. */
  if (kuerzen(daten.webseite, 40)) {
    return new Response(JSON.stringify({ ok: true, still: true }),
                        { headers: kopf });
  }

  const b = {
    vorname: kuerzen(daten.vorname, 80),
    nachname: kuerzen(daten.nachname, 80),
    klasse: kuerzen(daten.klasse, 40),
    email: kuerzen(daten.email, 160).toLowerCase(),
    telefonnummer: kuerzen(daten.telefonnummer, 40),
    abteilung: kuerzen(daten.abteilung, 30),
    motivation: kuerzen(daten.motivation, 3000),
    interessen: kuerzen(daten.interessen, 3000),
    vorwissen: kuerzen(daten.vorwissen, 3000),
    zeitpunkt: new Date().toISOString(),
  };

  for (const feld of ["vorname", "nachname", "klasse", "email",
                      "telefonnummer", "motivation", "interessen"]) {
    if (!b[feld]) { return nein("Bitte alle Pflichtfelder ausfuellen."); }
  }
  if (!/^[^@\s]+@[^@\s.]+\.[^@\s]+$/.test(b.email)) {
    return nein("Diese E-Mail-Adresse sieht nicht richtig aus.");
  }
  const bereich = b.email.split("@")[1] || "";
  if (GESPERRTE_MAILDOMAENEN.some(
        (d) => bereich === d || bereich.endsWith("." + d))) {
    return nein("Bitte eine private E-Mail-Adresse angeben - die Schuladresse "
              + "geht nicht. Sie fällt mit dem Abschluss weg, und unsere Post "
              + "bleibt dort oft im Filter hängen.");
  }
  if (!ABTEILUNGEN.some((a) => a.key === b.abteilung)) {
    return nein("Bitte wähle eine Wunsch-Abteilung aus.");
  }
  if (b.motivation.length < 20) {
    return nein("Schreib bitte ein paar Sätze zu deiner Motivation - daran "
              + "entscheidet sich einiges.");
  }

  const stunde = "bzaehler:" + new Date().toISOString().slice(0, 13);
  const bisher = parseInt(await umgebung.LAGER.get(stunde) || "0", 10);
  if (bisher >= BEWERBUNGEN_JE_STUNDE) {
    return nein("Gerade kommen ungewöhnlich viele Einsendungen an. Bitte in "
              + "einer Stunde noch einmal - oder schreib an "
              + "cto@tech.mvlg-wag.de.", 429);
  }
  await umgebung.LAGER.put(stunde, String(bisher + 1), { expirationTtl: 7200 });

  const kennung = "bewerbung:" + b.zeitpunkt + "-"
                + crypto.randomUUID().slice(0, 8);
  await umgebung.LAGER.put(kennung, JSON.stringify(b),
                           { expirationTtl: AUFBEWAHRUNG_SEKUNDEN });

  /* Hier klingelt es OHNE Ruhefrist. Eine Bewerbung ist selten und wichtig -
     wer sich waehrend eines Ausfalls bewirbt, soll nicht deshalb zwei Tage
     auf eine Antwort warten, weil kurz vorher jemand eine Stoerung gemeldet
     hat. */
  try {
    await klingeln(umgebung, [
      "Bewerbung während des Ausfalls",
      b.vorname + " " + b.nachname + " (Stufe " + b.klasse + ", "
      + b.abteilung + ") hat sich beworben. Wird eingetragen, sobald die "
      + "Plattform läuft.",
    ]);
  } catch (fehler) { /* die Bewerbung liegt trotzdem sicher */ }

  return new Response(JSON.stringify({ ok: true }), { headers: kopf });
}

/** Die gelagerten Meldungen an die Plattform uebergeben. */
async function meldungenAusliefern(anfrage, umgebung) {
  if (!schluesselStimmt(anfrage, umgebung)) {
    return new Response("Nein.", { status: 403 });
  }
  const kopf = { "content-type": "application/json; charset=utf-8",
                 "cache-control": "no-store" };
  const leer = { meldungen: [], bewerbungen: [], nachrichten: [] };
  if (!umgebung.LAGER) {
    return new Response(JSON.stringify(leer), { headers: kopf });
  }

  /* Beides in einem Zug. Ein zweiter Weg fuer Bewerbungen waere ein zweiter
     Ort, an dem etwas liegen bleiben kann, ohne dass es jemandem auffaellt. */
  async function holen(vorsatz) {
    const liste = await umgebung.LAGER.list({ prefix: vorsatz, limit: 100 });
    const gefunden = [];
    for (const eintrag of liste.keys) {
      const roh = await umgebung.LAGER.get(eintrag.name);
      if (!roh) { continue; }
      try {
        gefunden.push(Object.assign({ kennung: eintrag.name }, JSON.parse(roh)));
      } catch (fehler) { /* unlesbar - wird beim Bestaetigen mit entsorgt */ }
    }
    return gefunden;
  }

  return new Response(JSON.stringify({
    meldungen: await holen("meldung:"),
    bewerbungen: await holen("bewerbung:"),
    nachrichten: await holen("nachricht:"),
  }), { headers: kopf });
}

/**
 * Erst wegwerfen, wenn die Plattform sagt, dass sie ein Ticket daraus gemacht
 * hat. Andersherum - beim Ausliefern loeschen - waere eine Meldung verloren,
 * wenn die Plattform zwischen Abholen und Speichern abstuerzt. Ein doppeltes
 * Ticket sieht man und loescht es; ein fehlendes sieht niemand.
 */
async function meldungenBestaetigen(anfrage, umgebung) {
  if (!schluesselStimmt(anfrage, umgebung)) {
    return new Response("Nein.", { status: 403 });
  }
  let kennungen;
  try {
    kennungen = (await anfrage.json()).kennungen || [];
  } catch (fehler) {
    return new Response("Unlesbar.", { status: 400 });
  }
  let weg = 0;
  for (const kennung of kennungen.slice(0, 200)) {
    if (typeof kennung === "string"
        && (kennung.startsWith("meldung:") || kennung.startsWith("bewerbung:")
            || kennung.startsWith("nachricht:"))) {
      await umgebung.LAGER.delete(kennung);
      weg += 1;
    }
  }
  return new Response(JSON.stringify({ entfernt: weg }), {
    headers: { "content-type": "application/json; charset=utf-8" } });
}

/** Zeichenweiser Vergleich ohne Abkuerzung - sonst verraet die Dauer den Wert. */
function schluesselStimmt(anfrage, umgebung) {
  const erwartet = umgebung.ABHOL_SCHLUESSEL || "";
  const bekommen = anfrage.headers.get("x-ausfall-schluessel") || "";
  if (!erwartet || erwartet.length !== bekommen.length) { return false; }
  let ungleich = 0;
  for (let i = 0; i < erwartet.length; i += 1) {
    ungleich |= erwartet.charCodeAt(i) ^ bekommen.charCodeAt(i);
  }
  return ungleich === 0;
}


/* ------------------------------------------------------------------------- */
/*  Klingeln (ntfy)                                                          */
/* ------------------------------------------------------------------------- */

/**
 * paar = [Titel, Text]. Gibt zurueck, was wirklich passiert ist.
 *
 * Frueher gab das nur true/false zurueck und verschluckte jeden Fehler. Genau
 * daran ist die erste Meldung gescheitert, ohne eine Spur zu hinterlassen:
 * Die Seite sagte "der CTO bekommt sofort eine Meldung aufs Telefon", und in
 * Wahrheit war gar kein Thema eingetragen. Eine Zusage, die man nicht
 * einhaelt, ist schlimmer als ein ehrliches "das ging nicht".
 */
async function klingeln(umgebung, paar) {
  const thema = umgebung.NTFY_THEMA;
  if (!thema) { return { ok: false, grund: "kein NTFY_THEMA hinterlegt" }; }
  const basis = (umgebung.NTFY_BASIS || "https://ntfy.sh").replace(/\/+$/, "");
  /* Als JSON an die Wurzel, nicht als Kopfzeile an /thema: Kopfzeilen duerfen
     nur ASCII enthalten, und "Plattform nicht erreichbar" ist noch harmlos -
     ein Meldungstext mit Umlauten waere es nicht. */
  try {
    const antwort = await fetch(basis + "/", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ topic: thema, title: paar[0], message: paar[1],
                             priority: 4, tags: ["warning"] }),
    });
    if (!antwort.ok) {
      const text = (await antwort.text()).slice(0, 200);
      return { ok: false, grund: "ntfy antwortet " + antwort.status
                                 + (text ? ": " + text : "") };
    }
    /* Hat es geklappt, ist der alte Fehler Geschichte. Ohne das steht im
       Selbsttest tagelang eine rote Zeile von einem Problem, das laengst
       behoben ist - und wer eine Warnung sieht, die nichts mehr bedeutet,
       glaubt der naechsten auch nicht mehr. */
    if (umgebung.LAGER) {
      try { await umgebung.LAGER.delete("klingel_fehler"); } catch (f) {}
    }
    return { ok: true, grund: "" };
  } catch (fehler) {
    return { ok: false, grund: "ntfy nicht erreichbar (" + fehler.name + ")" };
  }
}

/** Klingeln, aber nicht bei jeder einzelnen Meldung. */
async function klingelnMitRuhe(umgebung, meldung) {
  /* Das fehlende Thema zuerst, noch vor der Ruhefrist. Sonst meldete der
     Worker "hat geklingelt", nur weil vor acht Minuten jemand anderes eine
     Meldung geschickt hatte - obwohl gar kein Thema hinterlegt ist und nie
     etwas geklingelt hat. */
  if (!umgebung.NTFY_THEMA) {
    return { ok: false, grund: "kein NTFY_THEMA hinterlegt" };
  }
  const zuletzt = parseInt(await umgebung.LAGER.get("klingel") || "0", 10);
  const jetzt = Math.floor(Date.now() / 1000);
  if (jetzt - zuletzt < KLINGEL_RUHE_SEKUNDEN) {
    return { ok: true, grund: "", ruhe: true };
  }
  const wer = meldung.name || "Jemand";
  const ergebnis = await klingeln(umgebung, [
    "Ausfallmeldung von der Fehlerseite",
    wer + ": " + meldung.text.slice(0, 240),
  ]);
  /* Die Ruhefrist erst setzen, wenn es geklappt hat. Sonst schweigt der
     Worker zehn Minuten lang, weil ein Versuch fehlgeschlagen ist. */
  if (ergebnis.ok) {
    await umgebung.LAGER.put("klingel", String(jetzt), { expirationTtl: 86400 });
  } else {
    await umgebung.LAGER.put("klingel_fehler",
                             new Date().toISOString() + " - " + ergebnis.grund,
                             { expirationTtl: 604800 });
  }
  return ergebnis;
}


/* ------------------------------------------------------------------------- */
/*  Selbsttest                                                               */
/* ------------------------------------------------------------------------- */

/**
 * Zeigt, was eingerichtet ist und was fehlt.
 *
 * Gebaut nach der ersten Meldung aus dem Betrieb: "hab kein Ticket bekommen
 * und keine ntfy Benachrichtigung". Beides kann an vier verschiedenen Stellen
 * haengen, und keine davon war von aussen zu sehen - der Worker schwieg
 * einfach. Ein Auffangnetz, dessen Zustand man nicht pruefen kann, ist kein
 * Auffangnetz, sondern eine Hoffnung.
 *
 * Bewusst ohne Schluessel erreichbar: Zu sehen sind nur Ja/Nein-Angaben, kein
 * Geheimnis und kein Meldungstext. Wer die Adresse kennt, erfaehrt, dass es
 * ein Auffangnetz gibt - das steht ohnehin auf jeder Fehlerseite.
 */
async function selbsttest(anfrage, umgebung) {
  const adresse = new URL(anfrage.url);
  const lager = Boolean(umgebung.LAGER);
  const zeilen = [];
  let offen = 0;

  /* `zaehlt` unterscheidet zwei Sorten Zeilen: Einrichtungsschritte, die
     offen sein koennen, und blosse Zustandsangaben. Dass die Plattform
     gerade nicht antwortet, ist kein Einrichtungsfehler - es ist der Grund,
     warum man hier ist. Sonst stuende oben "2 Punkte sind offen", wo nur
     einer wirklich fehlt. */
  function zeile(name, gut, wert, hilfe, zaehlt) {
    if (!gut && zaehlt !== false) { offen += 1; }
    zeilen.push({ name, gut, wert, hilfe });
  }

  zeile("Fassung des Auffangnetzes", true, FASSUNG,
        "Steht hier eine aeltere Nummer als erwartet, ist der neue Code "
        + "nicht ausgerollt - im Worker auf Deploy druecken.");
  zeile("Worker liegt vor dieser Adresse", true, adresse.hostname,
        "Diese Seite kommt vom Worker - sonst waerst du hier nicht.");
  zeile("Zwischenspeicher (KV) haengt dran", lager,
        lager ? "verbunden" : "fehlt",
        "Ohne ihn kann die Fehlerseite keine Meldung aufnehmen. Settings, "
        + "Bindings, KV namespace, Variablenname LAGER.");
  zeile("Abholschluessel gesetzt", Boolean(umgebung.ABHOL_SCHLUESSEL),
        umgebung.ABHOL_SCHLUESSEL ? "gesetzt" : "fehlt",
        "Ohne ihn kann die Plattform die Meldungen nicht abholen, es "
        + "entstehen also keine Tickets. Settings, Variables and Secrets, "
        + "Secret ABHOL_SCHLUESSEL - und derselbe Wert in config.cmd.");
  zeile("ntfy-Thema hinterlegt", Boolean(umgebung.NTFY_THEMA),
        umgebung.NTFY_THEMA ? "gesetzt" : "fehlt",
        "Ohne es klingelt kein Telefon. Die Meldung wird trotzdem gespeichert "
        + "und wird spaeter ein Ticket. Wichtig: Das Thema erzeugt niemand "
        + "fuer dich - du denkst dir einen unerratbaren Namen aus und traegst "
        + "ihn an ZWEI Stellen zeichengenau ein: hier als Secret NTFY_THEMA "
        + "(Settings, Variables and Secrets) und in der ntfy-App als Abo.");

  let wartend = 0;
  let letzterFehler = "";
  if (lager) {
    try {
      const liste = await umgebung.LAGER.list({ prefix: "meldung:", limit: 100 });
      wartend = liste.keys.length;
      letzterFehler = await umgebung.LAGER.get("klingel_fehler") || "";
    } catch (fehler) {
      letzterFehler = "KV nicht lesbar: " + fehler.name;
    }
  }
  zeile("Meldungen, die auf Abholung warten", true, String(wartend),
        wartend
          ? "Sie werden zu Tickets, sobald die Plattform laeuft und die "
            + "beiden Zeilen in config.cmd stehen. Bleiben sie liegen, "
            + "stimmt der Abholschluessel nicht ueberein."
          : "Nichts liegt herum.");
  if (letzterFehler) {
    zeile("Letzter Fehler beim Klingeln", false, letzterFehler,
          "Ein Eintrag aus der Vergangenheit, kein offener Punkt - deshalb "
          + "zaehlt er oben nicht mit. Er verschwindet, sobald wieder etwas "
          + "durchgekommen ist. Zum Ausprobieren der Knopf unten.", false);
  }

  const gemerkt = lager ? await umgebung.LAGER.get("zustand") : null;
  zeile("Alarm beim Ausfall", Boolean(lager && umgebung.NTFY_THEMA),
        (lager && umgebung.NTFY_THEMA) ? "scharf" : "aus",
        "Merkt der Worker, dass nichts antwortet, klingelt das Telefon des "
        + "CTO sofort - ohne dass jemand einen Knopf druecken muss. Dafuer "
        + "braucht es den Zwischenspeicher UND das ntfy-Thema."
        + (gemerkt ? " Zuletzt gemerkter Zustand: " + gemerkt + "." : ""));

  const lebt = await erreichbar(anfrage);
  zeile("Plattform gerade erreichbar", lebt, lebt ? "ja" : "nein",
        lebt
          ? "Solange sie laeuft, nimmt der Worker keine Meldungen an - eine "
            + "Meldung gehoert dann ins Dashboard, wo sie einen Absender hat."
          : "Die Fehlerseite wird gerade ausgeliefert.", false);

  const teile = zeilen.map(function (z) {
    return "<tr class=\"" + (z.gut ? "gut" : "offen") + "\">"
         + "<td>" + maskiert(z.name) + "</td>"
         + "<td><strong>" + maskiert(z.wert) + "</strong></td>"
         + "<td>" + maskiert(z.hilfe) + "</td></tr>";
  }).join("");

  const seite = SELBSTTEST_HTML
    .replace("%%STAND%%", offen
      ? maskiert(offen + (offen === 1 ? " Punkt ist offen."
                                      : " Punkte sind offen."))
      : "Alles eingerichtet.")
    .replace("%%KLASSE%%", offen ? "offen" : "gut")
    .replace("%%ZEILEN%%", teile)
    .replace("%%KLINGEL%%", umgebung.NTFY_THEMA ? "" : "hidden");
  return new Response(seite, {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8",
               "cache-control": "no-store", "x-robots-tag": "noindex",
               "x-auffangnetz": FASSUNG },
  });
}

/**
 * Eine Probemeldung aufs Telefon - der schnellste Weg herauszufinden, ob die
 * Kette bis zum ntfy-Thema wirklich steht.
 *
 * Hoechstens einmal je Minute: Die Adresse ist oeffentlich und soll kein Weg
 * werden, jemandem das Telefon vollzuklingeln.
 */
async function probeKlingeln(umgebung) {
  const kopf = { "content-type": "application/json; charset=utf-8",
                 "cache-control": "no-store" };
  if (!umgebung.LAGER) {
    return new Response(JSON.stringify({ ok: false, grund: "kein KV" }),
                        { status: 503, headers: kopf });
  }
  const zuletzt = parseInt(await umgebung.LAGER.get("probe") || "0", 10);
  const jetzt = Math.floor(Date.now() / 1000);
  if (jetzt - zuletzt < 60) {
    return new Response(JSON.stringify({
      ok: false, grund: "Gerade eben schon probiert. Eine Minute warten.",
    }), { status: 429, headers: kopf });
  }
  await umgebung.LAGER.put("probe", String(jetzt), { expirationTtl: 3600 });
  const ergebnis = await klingeln(umgebung, [
    "Probemeldung vom Auffangnetz",
    "Wenn du das liest, kommen Ausfallmeldungen bei dir an.",
  ]);
  return new Response(JSON.stringify(ergebnis),
                      { status: ergebnis.ok ? 200 : 502, headers: kopf });
}

const SELBSTTEST_HTML = `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Auffangnetz &ndash; Selbsttest</title>
<style>
  :root{
    --grund:#F6F7F4; --flaeche:#FFFFFF; --text:#18211F; --leise:#66726D;
    --linie:rgba(24,33,31,.14); --navy:#0E2647; --amber:#B8862B;
    --rot:#A33A2E; --gruen:#2E7D5A;
  }
  @media (prefers-color-scheme: dark){
    :root{
      --grund:#0D1526; --flaeche:#161F33; --text:#EDF0F7; --leise:#9AA7C2;
      --linie:rgba(237,240,247,.13); --navy:#82A6F2; --amber:#EFB95C;
      --rot:#E8836F; --gruen:#7BC49B;
    }
  }
  *{box-sizing:border-box;}
  body{
    margin:0; background:var(--grund); color:var(--text); line-height:1.6;
    font-family:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
    padding:2rem 1.25rem;
  }
  main{max-width:52rem; margin:0 auto;}
  h1{font-size:1.35rem; color:var(--navy); margin:0 0 .6rem;}
  .stand{
    display:inline-block; font-weight:600; padding:.3rem .8rem;
    border-radius:99px; margin-bottom:1.5rem; font-size:.9rem;
  }
  .stand.gut{background:rgba(46,125,90,.14); color:var(--gruen);}
  .stand.offen{background:rgba(163,58,46,.13); color:var(--rot);}
  .umrandung{
    overflow-x:auto; border:1px solid var(--linie); border-radius:12px;
    background:var(--flaeche);
  }
  table{border-collapse:collapse; width:100%; min-width:34rem;}
  td{padding:.75rem 1rem; border-top:1px solid var(--linie); vertical-align:top;}
  tr:first-child td{border-top:0;}
  td:first-child{white-space:nowrap; color:var(--leise);}
  td:nth-child(2){white-space:nowrap;}
  td:last-child{color:var(--leise); font-size:.87rem;}
  tr.offen td:nth-child(2) strong{color:var(--rot);}
  tr.gut td:nth-child(2) strong{color:var(--gruen);}
  button{
    font:inherit; font-weight:600; cursor:pointer; border-radius:8px;
    padding:.7rem 1.2rem; border:0; background:var(--navy); color:#fff;
    min-height:2.75rem; margin-top:1.5rem;
  }
  @media (prefers-color-scheme: dark){ button{color:#0D1526;} }
  button[disabled]{opacity:.55; cursor:default;}
  #probe-antwort{
    margin-top:1rem; padding:.8rem 1rem; border-radius:8px;
    border-left:4px solid var(--amber); background:var(--flaeche);
    font-size:.9rem; color:var(--text);
  }
  p{color:var(--leise);}
  [hidden]{display:none !important;}
</style>
</head>
<body>
<main>
  <h1>Auffangnetz &ndash; Selbsttest</h1>
  <span class="stand %%KLASSE%%">%%STAND%%</span>
  <div class="umrandung"><table><tbody>%%ZEILEN%%</tbody></table></div>
  <button type="button" id="probe" %%KLINGEL%%>Probemeldung aufs Telefon</button>
  <p id="probe-antwort" hidden></p>
  <p style="margin-top:2rem;">Diese Seite ist nur eine Auskunft. Sie
    ver&auml;ndert nichts und zeigt keine Geheimnisse &ndash; nur, ob etwas
    gesetzt ist.</p>
</main>
<script>
(function () {
  "use strict";
  var knopf = document.getElementById("probe");
  var antwort = document.getElementById("probe-antwort");
  if (!knopf) { return; }
  knopf.addEventListener("click", function () {
    knopf.disabled = true;
    antwort.hidden = false;
    antwort.textContent = "Wird gesendet …";
    fetch("/__ausfall/probe", { method: "POST" })
      .then(function (a) { return a.json(); })
      .then(function (d) {
        knopf.disabled = false;
        antwort.textContent = d.ok
          ? "Abgeschickt. Kommt jetzt nichts auf dem Telefon an, stimmt das "
            + "Thema in der ntfy-App nicht mit dem Secret NTFY_THEMA überein."
          : "Hat nicht geklappt: " + (d.grund || "unbekannt");
      })
      .catch(function () {
        knopf.disabled = false;
        antwort.textContent = "Die Anfrage kam nicht durch.";
      });
  });
})();
</script>
</body>
</html>`;


/* ------------------------------------------------------------------------- */
/*  Die Seite                                                               */
/* ------------------------------------------------------------------------- */

/**
 * Kuerzen und saeubern.
 *
 * Bewusst zeichenweise statt mit einem regulaeren Ausdruck: Steuerzeichen in
 * einer Quelldatei sind unsichtbar, und eine Zeile, die man nicht lesen kann,
 * kann man auch nicht pruefen. Zeilenumbruch (10) und Tabulator (9) bleiben -
 * die tippt man wirklich. Alles andere unter 32 kommt aus keiner Tastatur,
 * wohl aber aus einem Skript, das die Ticket-Ansicht durcheinanderbringen will.
 */
function kuerzen(wert, laenge) {
  const roh = String(wert === undefined || wert === null ? "" : wert);
  let sauber = "";
  for (let i = 0; i < roh.length; i += 1) {
    const z = roh.charCodeAt(i);
    if (z === 127 || (z < 32 && z !== 9 && z !== 10)) { continue; }
    sauber += roh[i];
  }
  return sauber.trim().slice(0, laenge);
}

function maskiert(wert) {
  return String(wert).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* ------------------------------------------------------------------------- */
/*  Die Seite                                                                */
/* ------------------------------------------------------------------------- */

/**
 * Die Ersatzseite - und zwar dieselbe Seite wie sonst.
 *
 * Bis hierher stand hier eine eigene Notfallseite: eigenes Stylesheet, eigener
 * Aufbau, und ganz oben ein blaues Band mit "Die Plattform ist gerade nicht
 * erreichbar". Ehrlich, aber teuer. Wer zum ersten Mal auf mvlg-wag.de kommt,
 * weil ihm jemand von der AG erzaehlt hat, liest als Erstes eine
 * Stoerungsmeldung - und geht wieder. Fuer ihn ist der Ausfall voellig
 * belanglos: Er wollte lesen, worum es geht, und sich vielleicht bewerben.
 * Beides geht auch jetzt.
 *
 * Deshalb gilt ab jetzt: Der normale Besucher merkt nichts. Er bekommt die
 * Startseite, wie sie ist - dasselbe Stylesheet, dieselben Schriften, derselbe
 * Aufbau (siehe cloudflare/eingebettet.js, erzeugt aus statisch/). Bewerbung
 * und Kontaktformular nimmt der Worker selbst entgegen.
 *
 * Erst wer sich ANMELDEN will, erfaehrt es - denn nur dann ist es seine Sache.
 * Wer sich anmeldet, gehoert zur AG, und fuer ihn ist "das System ist gerade
 * aus" die richtige, vollstaendige Antwort auf seinen Klick.
 *
 * Was live aus der Datenbank kaeme, fehlt zwangslaeufig - die Datenbank ist ja
 * gerade der Teil, der nicht antwortet. Die vier pflegbaren Bloecke der
 * Startseite kommen deshalb aus INHALTE, eingebacken beim letzten Bauen. Das
 * Quiz dagegen ist vollstaendig da: Es rechnet ohnehin im Browser.
 */
function ausfallseite(adresse, umgebung, grund) {
  /* Wer hier landet, wollte sich anmelden: die Anmeldeseite selbst, das
     Dashboard, oder er ist ueberhaupt unter app.* unterwegs - dort gibt es
     nichts als das Dashboard. Fuer ihn steht der Hinweis gleich offen; alles
     andere waere ein Versteckspiel mit den eigenen Leuten. */
  const dashboardName = umgebung.DASHBOARD_HOST || "";
  const istDashboard = dashboardName
    ? adresse.hostname === dashboardName
    : adresse.hostname.startsWith("app.");
  const weg = adresse.pathname.toLowerCase().replace(/\/+$/, "") || "/";
  const wollteAnmelden = istDashboard
    || weg === "/login" || weg.startsWith("/login/")
    || weg.startsWith("/dashboard") || weg === "/logout"
    || weg.startsWith("/passwort") || weg === "/email-bestaetigen";

  /* Drei Seiten kann das Auffangnetz. Alles andere - eine Unterseite, ein
     alter Verweis, ein Tippfehler in der Adresse - bekommt die Startseite:
     besser als jede Fehlermeldung, und dem Besucher faellt nichts auf. */
  const quiz = weg === "/quiz" && QUIZ;
  const schmal = weg === "/bewerbung" || quiz;
  const koerper = weg === "/bewerbung" ? BEWERBUNG_FERTIG
    : quiz ? QUIZ : LANDING_FERTIG;
  /* Auch der Fenstertitel gehoert dazu. Er steht in der Leiste des Browsers
     und im Lesezeichen - ein "Bewerbung: …", das ploetzlich zur Startseite
     zurueckfaellt, ist genau die Kleinigkeit, an der jemand merkt, dass hier
     etwas anders ist. */
  const kopfangaben = weg === "/bewerbung" ? TITEL.bewerbung
    : quiz ? TITEL.quiz : TITEL.start;

  return antwortSeite(seiteBauen({
    koerper: koerper,
    hauptklasse: schmal ? "schmal" : "",
    zusatzskript: quiz ? QUIZ_JS : "",
    titel: kopfangaben[0],
    beschreibung: kopfangaben[1],
    offen: wollteAnmelden,
    lager: Boolean(umgebung.LAGER),
    grund: grund,
    woher: adresse.pathname + adresse.search,
  }));
}

function antwortSeite(html) {
  return new Response(html, {
    /* 503 und nicht 200 - trotz allem. Fuer den Menschen aendert das nichts,
       seine Seite sieht aus wie immer. Fuer eine Maschine ist es der
       Unterschied zwischen "das ist der Inhalt dieser Adresse" und "komm
       spaeter wieder": Ohne 503 nimmt ein Suchdienst diese Fassung als
       unsere Startseite auf, samt fehlendem Quiz und altem Portfolio, und
       zeigt sie noch wochenlang. */
    status: 503,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, must-revalidate",
      "retry-after": "120",
      "x-robots-tag": "noindex",
      "x-auffangnetz": FASSUNG,
    },
  });
}

/** Das ganze Dokument.
 *
 * Ersetzt wird ueber eine Funktion, nicht ueber eine Zeichenkette: In einem
 * Ersatztext deutet String.replace ein "$&" als Rueckverweis - und das
 * eingebettete Stylesheet ist eine halbe Million Zeichen, in denen so etwas
 * irgendwann vorkommt.
 *
 * Bilder stehen zu diesem Zeitpunkt schon drin: Sie werden einmal beim Start
 * in KOPFZEILE_FERTIG und LANDING_FERTIG eingesetzt. Eine Ersetzung liest ihr
 * eigenes Ergebnis naemlich nicht noch einmal - ein "%%WAPPEN%%", das erst mit
 * dem Inhalt hereinkommt, bliebe sonst als Text in der Seite stehen. */
function seiteBauen(teile) {
  const ersatz = {
    "%%STIL%%": SCHRIFTEN + "\n" + STIL + "\n" + ZUSATZSTIL,
    "%%FAVICON%%": FAVICON,
    "%%KOPFZEILE%%": KOPFZEILE_FERTIG,
    "%%FUSSZEILE%%": FUSSZEILE,
    "%%HINWEIS%%": HINWEIS,
    "%%INHALT%%": teile.koerper,
    "%%ZUSATZSKRIPT%%": teile.zusatzskript || "",
    "%%HAUPTKLASSE%%": teile.hauptklasse || "",
    "%%TITEL%%": teile.titel,
    "%%BESCHREIBUNG%%": teile.beschreibung,
    "%%OFFEN%%": teile.offen ? "1" : "",
    "%%LAGER%%": teile.lager ? "1" : "",
    "%%FASSUNG%%": FASSUNG,
    "%%GRUND%%": maskiert(teile.grund || ""),
    "%%WOHER%%": maskiert(teile.woher || ""),
  };
  return SEITE.replace(/%%[A-Z]+%%/g, (marke) =>
    Object.prototype.hasOwnProperty.call(ersatz, marke) ? ersatz[marke] : marke);
}

/* Die vier im Dashboard pflegbaren Bloecke, wie sie zuletzt beim Bauen in der
   Datenbank standen. Aufbau und Klassennamen sind aus
   vorlagen/oeffentlich/start.html abgeschrieben - daran haengt, dass es
   gleich aussieht. */
function liste(bereich, wie) {
  const bloecke = (INHALTE && INHALTE[bereich]) || [];
  return bloecke.map(wie).join("\n");
}

const VORTEILE = liste("vorteile", (b) =>
  "<li>" + maskiert(b.titel) + "</li>");

const STUFEN = liste("stufen", (b) =>
  "<li><strong>" + maskiert(b.titel) + "</strong><span>"
  + maskiert(b.text || "") + "</span></li>");

const ANGEBOT = liste("angebot", (b) =>
  '<div class="panel arbeit-karte" style="--karte:'
  + maskiert(b.farbe || "#0E2647") + '"><h3>' + maskiert(b.titel)
  + "</h3><p>" + maskiert(b.text || "") + "</p></div>");

const PORTFOLIO = liste("portfolio", (b) =>
  '<li class="portfolio-karte" style="--karte:'
  + maskiert(b.farbe || "#0E2647") + '">'
  + (b.zeitraum ? '<span class="portfolio-zeit">' + maskiert(b.zeitraum)
                  + "</span>" : "")
  + '<div class="portfolio-inhalt"><h3>' + maskiert(b.titel) + "</h3>"
  + (b.text ? "<p>" + maskiert(b.text) + "</p>" : "")
  + (b.ergebnis ? '<p class="portfolio-ergebnis">' + maskiert(b.ergebnis)
                  + "</p>" : "")
  + "</div></li>");


/* ------------------------------------------------------------------------- */
/*  Bausteine der Seite                                                      */
/* ------------------------------------------------------------------------- */

/* Titel und Beschreibung je Seite - abgeschrieben aus
   website/routen/oeffentlich.py und vorlagen/basis.html. */
const TITEL = {
  start: ["Wirtschafts- &amp; Investment-AG (WAG) am MvLG Koblenz",
          "Sch&uuml;ler-AG am Max-von-Laue-Gymnasium Koblenz: B&ouml;rse, "
          + "Finanzen und eigene Gr&uuml;ndungsprojekte. Klasse 9 bis 13, "
          + "ohne Vorwissen, alle zwei Wochen."],
  bewerbung: ["Bewerbung: Wirtschafts- &amp; Investment-AG am MvLG Koblenz",
              "In f&uuml;nf Minuten beworben: Sch&uuml;ler-AG f&uuml;r "
              + "B&ouml;rse, Finanzen und Gr&uuml;nden am "
              + "Max-von-Laue-Gymnasium Koblenz. Klasse 9 bis 13, kein "
              + "Vorwissen n&ouml;tig."],
  quiz: ["Wirtschafts-Quiz | Wirtschafts- &amp; Investment-AG (MvLG Koblenz)",
         "Zehn Fragen zu Inflation, BIP, Angebot und Nachfrage &ndash; ohne "
         + "Anmeldung, mit sofortiger Auswertung."],
};

/* Kopf- und Fusszeile stehen woertlich in vorlagen/basis.html. Die Verweise
   sind hier relativ statt absolut: Auf app.* faende ein absoluter Verweis auf
   mvlg-wag.de zwar dieselbe Notfassung, aber der Wechsel des Namens waere in
   der Adresszeile zu sehen - und das ist genau der Hinweis, den wir nicht
   geben wollen. */
const KOPFZEILE = `
<a class="sprung" href="#inhalt">Zum Inhalt springen</a>
<header class="seite" id="kopfzeile">
  <a href="/" class="marke-logo">
    <img class="wappen" src="%%LOGO%%" width="226" height="180" alt="Logo der Wirtschafts- und Investment-AG">
    <span class="marke-text">Wirtschafts- &amp; Investment-AG<span class="marke-motto">An alle, die gr&ouml;&szlig;er denken.</span></span>
  </a>
  <button class="burger" type="button" aria-label="Men&uuml; &ouml;ffnen" aria-expanded="false" data-burger><span class="burger-striche" aria-hidden="true"><span></span><span></span><span></span></span></button>
  <nav aria-label="Hauptmen&uuml;">
    <a href="/#start">Start</a>
    <a href="/#ueber-uns">&Uuml;ber uns</a>
    <a href="/#arbeit">Aktivit&auml;ten</a>
    <a href="/#kontakt">Kontakt</a>
    <a href="/bewerbung">Bewerbung</a>
    <a href="/login" class="betont" data-anmelden>Login</a>
    <button class="thema-schalter" type="button" data-thema
            aria-label="Zwischen hellem und dunklem Erscheinungsbild wechseln"
            title="Dunkelmodus umschalten">
      <span class="knopf">
        <svg class="sonne" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
        <svg class="mond" viewBox="0 0 24 24" fill="currentColor"><path d="M20.9 14.6c-3.9 1.4-8.4-1-9.8-4.9-1-2.7-.4-5.6 1.4-7.7-4.4.6-7.9 4.3-7.9 8.9 0 5 4 9 9 9 4 0 7.4-2.6 8.6-6.2-.4.1-.9.2-1.3.3z"/></svg>
      </span>
    </button>
  </nav>
</header>
<div class="ticker" aria-hidden="true">
  <span>Wirtschafts- &amp; Investment-AG</span><span>Bewerbungen offen</span><span>Investments</span><span>Wettbewerbe</span><span>Planspiele</span>
</div>`;

const FUSSZEILE = `
<footer class="seite">
  <div class="fuss-links">
    <a href="/">Startseite</a>
    <a href="/#ueber-uns">&Uuml;ber uns</a>
    <a href="/#arbeit">Aktivit&auml;ten</a>
    <a href="/#kontakt">Kontakt</a>
    <a href="/bewerbung">Bewerbung</a>
    <a href="/impressum">Impressum</a>
    <a href="/datenschutz">Datenschutz</a>
  </div>
  <p class="fuss-zeile">Wirtschafts- &amp; Investment-AG &middot; Offizielle
    Sch&uuml;ler-AG des
    <a href="https://www.mvlg.de" rel="noopener">Max-von-Laue-Gymnasiums Koblenz (MvLG)</a></p>
  <p class="fuss-urheber">
    &copy; 2026 <strong>Wirtschafts- &amp; Investment-AG</strong> am
    Max-von-Laue-Gymnasium Koblenz. Alle Rechte vorbehalten.
  </p>
</footer>`;

/**
 * Der einzige Unterschied zur echten Seite.
 *
 * Aufgehen tut er, wenn jemand auf "Login" tippt - und sonst nie. Deshalb
 * steht die Stoerungsmeldung hier drin und nicht oben auf der Seite: Sie ist
 * die Antwort auf einen Klick, keine Ansage an alle.
 *
 * Das Meldefeld gehoert dazu und nicht in ein Support-Formular. Wenn nichts
 * laeuft, kann man sich auch nicht anmelden, um es zu melden - der offene
 * Briefkasten ist in diesen Minuten der einzige Weg.
 */
const HINWEIS = `
<div class="ausfall-schleier" id="ausfall" hidden role="dialog"
     aria-modal="true" aria-labelledby="ausfall-titel">
  <div class="ausfall-kasten panel">
    <button type="button" class="ausfall-zu" id="ausfall-zu"
            aria-label="Schlie&szlig;en">&times;</button>
    <span class="hut">Anmeldung</span>
    <h2 id="ausfall-titel">Das System ist gerade nicht erreichbar</h2>
    <p>Anmelden geht deshalb im Moment nicht. Die Plattform l&auml;uft auf
      einem Rechner in der Schule &ndash; ist der aus oder gerade neu
      gestartet, antwortet f&uuml;r ein paar Minuten niemand. An deinen Daten
      &auml;ndert das nichts.</p>
    <p class="meta ausfall-uhr">
      <span class="ausfall-punkt" aria-hidden="true"></span>
      <span id="warten-text" aria-live="polite">Wir sehen alle 15 Sekunden
        nach. Sobald es wieder geht, steht es hier.</span>
    </p>
    <div class="knopfzeile">
      <a class="btn" id="wieder-da" href="/login" hidden>Jetzt anmelden</a>
      <button type="button" class="btn btn-zweit" id="nochmal">Nochmal
        versuchen</button>
    </div>

    <details class="ausfall-melden" id="melden">
      <summary>Dem CTO melden</summary>
      <p class="meta" style="margin-top:var(--r3);">Damit er wei&szlig;, dass
        es nicht l&auml;uft &ndash; und ab wann. Anmelden musst du dich
        daf&uuml;r nicht, das geht gerade ohnehin nicht.</p>
      <form id="formular" class="formular" novalidate>
        <label class="voll">Was wolltest du gerade machen?
          <textarea id="f-text" maxlength="2000" required rows="3"
            placeholder="Zum Beispiel: Ich wollte meine Aufgaben ansehen."></textarea>
        </label>
        <label>Dein Name
          <span class="meta">Damit er wei&szlig;, wer es gemeldet hat.</span>
          <input id="f-name" maxlength="80" autocomplete="name">
        </label>
        <label>E-Mail
          <span class="meta">Freiwillig, f&uuml;r eine Antwort.</span>
          <input id="f-kontakt" type="email" maxlength="120" autocomplete="email">
        </label>
        <div class="formular-fuss">
          <button type="submit" id="absenden">Meldung abschicken</button>
        </div>
      </form>
      <div class="meldung meldung-gut" id="antwort" hidden><div></div></div>
    </details>
  </div>
</div>`;

/* Nur das, was die echte Seite nicht schon mitbringt: der Hinweiskasten und
   das kleine Band unter dem Aufmacher. Alles andere kommt aus basis.css und
   website.css - unveraendert, damit es sich nicht auseinanderentwickelt. */
const ZUSATZSTIL = `
.ausfall-schleier{
  position:fixed; inset:0; z-index:80; display:flex; align-items:center;
  justify-content:center; padding:var(--r4); overflow:auto;
  background:rgba(8,15,26,.58);
}
@supports (backdrop-filter: blur(3px)){
  .ausfall-schleier{ backdrop-filter:blur(3px); }
}
.ausfall-schleier[hidden]{ display:none; }
.ausfall-kasten{
  position:relative; width:100%; max-width:34rem; margin:auto;
  box-shadow:var(--schatten-hoch);
}
.ausfall-kasten h2{ margin-bottom:var(--r3); }
.ausfall-zu{
  position:absolute; top:.5rem; right:.5rem; width:2.2rem; height:2.2rem;
  min-height:0; padding:0; font-size:1.4rem; line-height:1;
  background:transparent; color:var(--gedaempft); border:0;
}
.ausfall-zu:hover{ background:var(--flaeche-2); color:var(--text); }
.ausfall-uhr{ display:flex; align-items:flex-start; gap:.55rem;
              margin:var(--r4) 0 var(--r4); }
.ausfall-punkt{
  width:.5rem; height:.5rem; border-radius:50%; background:var(--amber);
  flex:0 0 auto; margin-top:.5rem;
  animation:ausfall-pulsieren 1.8s ease-in-out infinite;
}
@keyframes ausfall-pulsieren{ 0%,100%{opacity:.35;} 50%{opacity:1;} }
@media (prefers-reduced-motion: reduce){ .ausfall-punkt{ animation:none; } }
.ausfall-melden{ margin-top:var(--r5); border-top:1px solid var(--linie);
                 padding-top:var(--r4); }
.ausfall-melden summary{ cursor:pointer; font-weight:600; color:var(--navy);
                         min-height:2.5rem; display:flex; align-items:center; }
html[data-theme="dark"] .ausfall-melden summary{ color:var(--amber); }
`;

/* ------------------------------------------------------------------------- */
/*  Die Startseite                                                           */
/* ------------------------------------------------------------------------- */

/* Abschnitt fuer Abschnitt aus vorlagen/oeffentlich/start.html. Was dort aus
   der Datenbank kommt, steht hier als eingebackene Liste; was gar nicht ohne
   Server geht - das Quiz -, faellt weg. Der Rest ist woertlich derselbe Text:
   Er ist geschrieben und geschliffen worden, daran wird nichts angefasst. */
const LANDING = `
<section id="start" class="abschnitt aufmacher">
  <div>
    <span class="hut">Sch&uuml;ler-AG am Max-von-Laue-Gymnasium Koblenz</span>
    <h1>Deine erste Aktie kaufst du nicht im Unterricht. Bei uns schon.</h1>
    <p class="aufmacher-motto">An alle, die gr&ouml;&szlig;er denken.</p>
    <p class="fuehrung">Steuern, Vertr&auml;ge, B&ouml;rse. Sachen, die
      sp&auml;ter einfach wichtig werden, kommen in der Schule kaum vor. Wir
      holen das nach. Kein Frontalvortrag. Wir simulieren Portfolios, rechnen
      eigene Ideen durch und treten bei echten Wettbewerben an.</p>
    <div class="knopfzeile">
      <a class="btn" href="/bewerbung">Jetzt bewerben</a>
      <a class="btn btn-zweit" href="#ueber-uns">Mehr erfahren</a>
    </div>
  </div>
  <div class="aufmacher-bild" aria-hidden="true">
    <img src="%%WAPPEN%%" width="480" height="381" alt="" decoding="async">
  </div>
</section>

<ul class="fakten" aria-label="Das Wichtigste in K&uuml;rze">
  <li><strong>Klasse 9&ndash;13</strong><span>Egal, welcher Schnitt</span></li>
  <li><strong>Alle zwei Wochen</strong><span>Ein Nachmittag, dazwischen das Dashboard</span></li>
  <li><strong>Ohne Vorwissen</strong><span>Interesse reicht als Voraussetzung</span></li>
  <li><strong>Echte Wettbewerbe</strong><span>Planspiel B&ouml;rse, Jugend Gr&uuml;ndet</span></li>
</ul>

<section id="ueber-uns" class="abschnitt">
  <div class="raster-2">
    <div>
      <span class="hut">&Uuml;ber uns</span>
      <h2>Von Sch&uuml;lern geleitet. Sonst niemandem.</h2>
      <p>Wir entscheiden selbst, woran wir arbeiten, wer was &uuml;bernimmt und
        wer wann Verantwortung tr&auml;gt. Wer will, leitet irgendwann ein
        eigenes Projekt oder landet im Core-Team, das die AG f&uuml;hrt.</p>
      <p>Getroffen wird alle zwei Wochen. Dazwischen l&auml;uft alles &uuml;ber
        unser eigenes Dashboard. Aufgaben, Termine, Beschl&uuml;sse, alles an
        einem Ort.</p>
      <p>Klassenstufen 9 bis 13. Vorkenntnisse brauchst du keine.
        Einser-Schnitt auch nicht.</p>
    </div>
    <div class="vorteile-kasten">
      <h3>Was du mitnimmst</h3>
      <ul class="vorteile-liste">
%%VORTEILE%%
      </ul>
    </div>
  </div>
</section>

<section id="halbjahre" class="abschnitt">
  <span class="hut">Jahresablauf</span>
  <h2>Zwei Halbjahre, zwei Welten</h2>
  <div class="raster-2" style="margin-top:var(--r6);">
    <div class="panel halbjahr">
      <span class="halbjahr-nummer" aria-hidden="true">1</span>
      <h3>Wirtschaft &amp; Investment</h3>
      <p>Angebot und Nachfrage, Risiko und Rendite, Diversifikation. Wir
        arbeiten mit fiktiven Portfolios, checken echte Marktentwicklungen und
        starten beim Planspiel B&ouml;rse. Wer richtig gut ist, qualifiziert
        sich f&uuml;r die Wharton Investment Challenge.</p>
    </div>
    <div class="panel halbjahr zwei">
      <span class="halbjahr-nummer" aria-hidden="true">2</span>
      <h3>Unternehmertum &amp; eigene Projekte</h3>
      <p>Ihr entwickelt in Teams eigene Gesch&auml;ftsideen, baut ein
        Gesch&auml;ftsmodell und findet raus, wer eure Zielgruppe
        &uuml;berhaupt ist. Ziel ist Jugend Gr&uuml;ndet oder Startup Teens,
        mit einem Konzept, das ihr wirklich pr&auml;sentieren k&ouml;nnt.</p>
    </div>
  </div>
  <p class="halbjahr-fazit">Erst verstehen, dann machen, dann draufschauen, was
    dabei rauskam. In der Reihenfolge.</p>
</section>

%%ANGEBOT_ABSCHNITT%%
%%PORTFOLIO_ABSCHNITT%%

<section id="weg" class="abschnitt">
  <span class="hut">Dein Weg</span>
  <h2>Du f&auml;ngst an, wo du stehst</h2>
  <ol class="stufen">
%%STUFEN%%
  </ol>
  <p class="stufen-fazit">Aufstieg nach Engagement, nicht nach Alter. Und den
    Schwerpunkt kannst du jederzeit wechseln.</p>
</section>

<section id="quiz-anriss" class="abschnitt panel quiz-anriss">
  <div>
    <span class="hut">Wissenstest</span>
    <h2>Wie gut kennst du dich schon aus?</h2>
    <p class="meta">%%QUIZANZAHL%% Fragen zu Inflation, BIP, Angebot und
      Nachfrage. Ein paar Minuten, Auswertung direkt danach. Keine Anmeldung,
      nichts wird gespeichert.</p>
  </div>
  <a class="btn" href="/quiz">Quiz starten</a>
</section>

<section class="abschnitt aufruf">
  <div>
    <h2>Klingt nach dir?</h2>
    <p>Keine Vorkenntnisse n&ouml;tig, kein Einser-Schnitt gefordert. Interesse
      und Zuverl&auml;ssigkeit reichen. Die Bewerbung dauert f&uuml;nf Minuten,
      dann melden wir uns.</p>
    <a class="btn" href="/bewerbung">Zur Bewerbung</a>
  </div>
</section>

<section id="kontakt" class="abschnitt panel">
  <span class="hut">Kontakt</span>
  <h2>Fragen? Schreib einfach.</h2>
  <div class="raster-2">
    <div>
      <p>Unsicher, ob die AG was f&uuml;r dich ist? Oder eine Frage zum Ablauf?
        Meld dich, wir antworten so schnell wie m&ouml;glich.</p>
      <div class="meldung meldung-gut" id="k-danke" hidden><div></div></div>
    </div>
    <form class="kontakt-formular" id="kontakt-formular" novalidate>
      <label>Dein Name
        <input type="text" id="k-name" maxlength="160" required autocomplete="name">
      </label>
      <label>Deine E-Mail
        <input type="email" id="k-email" maxlength="160" required autocomplete="email">
      </label>
      <label>Deine Nachricht
        <textarea id="k-text" maxlength="4000" required
                  placeholder="Worum geht es?"></textarea>
      </label>
      <div class="nur-lesehilfe" aria-hidden="true">
        <label>Bitte leer lassen<input type="text" id="k-webseite" tabindex="-1" autocomplete="off"></label>
      </div>
      <button type="submit" id="k-absenden">Nachricht senden</button>
    </form>
  </div>
</section>`;

/* Die beiden Abschnitte, die auf der echten Seite ganz verschwinden, wenn
   nichts drinsteht. Eine leere Erfolgsliste wirbt gegen die AG. */
const ANGEBOT_ABSCHNITT = ANGEBOT ? `
<section id="arbeit" class="abschnitt">
  <span class="hut">Aktivit&auml;ten</span>
  <h2>Was wir konkret machen</h2>
  <div class="raster-2" style="margin-top:var(--r6);">
` + ANGEBOT + `
  </div>
</section>` : "";

const PORTFOLIO_ABSCHNITT = PORTFOLIO ? `
<section id="arbeit" class="abschnitt">
  <span class="hut">Unsere Arbeit</span>
  <h2>Was dabei herausgekommen ist</h2>
  <p class="meta" style="max-width:56ch;">Kein Prospekt, sondern das, was
    tats&auml;chlich passiert ist &ndash; mit Zeitraum und Ergebnis.</p>
  <ol class="portfolio">
` + PORTFOLIO + `
  </ol>
</section>` : "";


/* ------------------------------------------------------------------------- */
/*  Das Quiz                                                                 */
/* ------------------------------------------------------------------------- */

/* Der einzige Teil der Seite, der ohne Server vollstaendig funktioniert - und
   deshalb der einzige, der hier vollstaendig steht. Die Fragen liegen im
   Markup, ausgewertet wird im Browser (statisch/js/quiz.js, mit eingebettet).
   Der Server hat davon noch nie etwas erfahren; es wird nichts gespeichert und
   nichts verschickt.

   Aufgebaut wie vorlagen/oeffentlich/quiz.html. */
const QUIZ = QUIZ_FRAGEN.length ? `
<section class="abschnitt">
  <span class="hut">Wissenstest</span>
  <h1>Wirtschafts-Quiz</h1>
  <p class="meta">` + QUIZ_FRAGEN.length + ` Fragen zu Geld, M&auml;rkten und
    Unternehmen &ndash; die Grundlagen, mit denen wir in der AG arbeiten. Nach
    jeder Antwort siehst du sofort, ob sie stimmt. Es wird nichts gespeichert
    und nichts verschickt.</p>
</section>

<section class="panel" id="quiz">
  <div class="quiz-fortschritt">
    <div class="quiz-fortschritt-kopf">
      <span id="quiz-zaehler">Frage 1 von ` + QUIZ_FRAGEN.length + `</span>
      <span id="quiz-stand">0 richtig</span>
    </div>
    <div class="balken" role="progressbar" aria-label="Fortschritt"
         aria-valuemin="0" aria-valuemax="` + QUIZ_FRAGEN.length + `"
         aria-valuenow="0" id="quiz-balken"><span id="quiz-fuellung"
         style="width:0"></span></div>
  </div>

  <noscript><div class="meldung meldung-fehler"><div>F&uuml;r das Quiz muss
    JavaScript aktiviert sein.</div></div></noscript>

` + QUIZ_FRAGEN.map((f, nr) =>
  '  <article class="quiz-frage" data-richtig="' + f.richtig + '" hidden>\n'
  + '    <h2 class="quiz-frage-text" tabindex="-1">' + maskiert(f.frage)
  + "</h2>\n"
  + '    <div class="quiz-optionen">\n'
  + f.optionen.map((text, i) =>
      '      <button type="button" class="quiz-option" data-nr="' + i + '">\n'
      + '        <span class="quiz-marke" aria-hidden="true">'
      + "ABCDEF"[i] + "</span>\n"
      + '        <span class="quiz-option-text">' + maskiert(text)
      + "</span>\n      </button>").join("\n") + "\n"
  + "    </div>\n"
  + '    <div class="quiz-rueckmeldung" role="status" hidden></div>\n'
  + '    <div class="quiz-fuss">\n'
  + '      <button type="button" class="quiz-weiter" hidden>'
  + (nr === QUIZ_FRAGEN.length - 1 ? "Ergebnis anzeigen" : "N&auml;chste Frage")
  + "</button>\n    </div>\n  </article>").join("\n") + `

  <div id="quiz-ergebnis" tabindex="-1" hidden>
    <span class="hut">Ergebnis</span>
    <p class="quiz-punktzahl"><span id="quiz-treffer">0</span> von
      ` + QUIZ_FRAGEN.length + `</p>
    <p id="quiz-urteil"></p>
    <ul class="quiz-bilanz" id="quiz-bilanz"></ul>
    <div class="quiz-ergebnis-knoepfe">
      <button type="button" id="quiz-neu">Noch einmal</button>
      <a class="btn btn-zweit" href="/bewerbung">Zur Bewerbung</a>
    </div>
  </div>
</section>` : "";
/* Leer, falls beim Bauen keine Frage mitkam. Dann faellt /quiz auf die
   Startseite zurueck und der Anriss verschwindet - eine leere Quizseite oder
   ein Knopf, der auf nichts fuehrt, waeren schlimmer als gar kein Quiz. */


/* ------------------------------------------------------------------------- */
/*  Die Bewerbungsseite                                                      */
/* ------------------------------------------------------------------------- */

/* Der wichtigste Teil des ganzen Auffangnetzes. Ein Interessent, der zufaellig
   in einen Ausfall geraet, ist der teuerste Verlust dieser Anlage - er kommt
   nicht wieder, und niemand erfaehrt je davon. Deshalb liegt die Seite hier
   vollstaendig, und das Formular geht an den Worker statt an den Server.

   Aufgebaut wie vorlagen/oeffentlich/bewerbung.html. Der einzige sichtbare
   Unterschied ist der Hinweis unter der Ueberschrift - und der steht nur da,
   weil eine Bewerbung, die "gleich" eingetragen wird, sonst wie eine wirkt,
   die nirgends ankommt. */
const BEWERBUNG = `
<section class="abschnitt">
  <span class="hut">Bewerbung</span>
  <h1>Mitmachen</h1>
  <p class="meta">F&uuml;nf Minuten, dann melden wir uns. Vorkenntnisse
    brauchst du keine &ndash; wir wollen wissen, was dich interessiert.</p>
</section>

<section class="panel">
  <form class="formular" id="bewerbung-formular" novalidate>
    <label>Vorname
      <input type="text" id="b-vorname" maxlength="80" required
             autocomplete="given-name">
    </label>
    <label>Nachname
      <input type="text" id="b-nachname" maxlength="80" required
             autocomplete="family-name">
    </label>
    <label>Stufe
      <select id="b-klasse" required>
        <option value="" disabled selected>Bitte ausw&auml;hlen</option>
        <option value="9">9</option>
        <option value="10">10</option>
        <option value="11">11</option>
        <option value="12">12</option>
        <option value="13">13</option>
      </select>
    </label>
    <label>E-Mail
      <span class="meta">Bitte privat &ndash; keine Schuladresse. Die
        f&auml;llt mit dem Abschluss weg, und unsere Post bleibt dort oft im
        Filter h&auml;ngen.</span>
      <input type="email" id="b-email" maxlength="160" required
             autocomplete="email">
    </label>
    <label>Telefonnummer
      <span class="meta">F&uuml;r die WhatsApp-Gruppe, wenn es klappt.</span>
      <input type="tel" id="b-telefon" maxlength="40" required inputmode="tel"
             placeholder="0163 1234567" autocomplete="tel">
    </label>
    <label>Wunsch-Abteilung
      <span class="meta">Bitte eine ausw&auml;hlen. Nicht bindend &ndash; wir
        sprechen dar&uuml;ber.</span>
      <select id="b-abteilung" required>
        <option value="" disabled selected>Bitte ausw&auml;hlen</option>
%%ABTEILUNGEN%%
      </select>
    </label>

    <label class="voll">Warum willst du mitmachen?
      <textarea id="b-motivation" maxlength="3000" required
                placeholder="Ein paar S&auml;tze reichen."></textarea>
    </label>
    <label class="voll">Was interessiert dich besonders?
      <textarea id="b-interessen" maxlength="3000" required
                placeholder="B&ouml;rse, Gr&uuml;nden, Marketing, Technik &hellip;"></textarea>
    </label>
    <label class="voll">Vorwissen <span class="meta">Optional.
      &bdquo;Keines&ldquo; ist eine v&ouml;llig normale Antwort.</span>
      <textarea id="b-vorwissen" maxlength="3000"></textarea>
    </label>

    <div class="nur-lesehilfe" aria-hidden="true">
      <label>Bitte leer lassen<input type="text" id="b-webseite" tabindex="-1" autocomplete="off"></label>
    </div>

    <div class="formular-fuss">
      <button type="submit" id="b-absenden">Bewerbung abschicken</button>
      <span class="meta">Mit dem Absenden stimmst du zu, dass wir deine Angaben
        zur Bearbeitung speichern. N&auml;heres in der
        <a href="/datenschutz">Datenschutzerkl&auml;rung</a>.</span>
    </div>
  </form>
  <div class="meldung meldung-gut" id="b-danke" hidden><div></div></div>
</section>`;


/* ------------------------------------------------------------------------- */
/*  Das Dokument                                                             */
/* ------------------------------------------------------------------------- */

const SEITE = `<!doctype html>
<html lang="de" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%%TITEL%%</title>
<meta name="description" content="%%BESCHREIBUNG%%">
<!-- noindex, weil diese Fassung nicht vollstaendig ist: Was aus der Datenbank
     kaeme, fehlt oder ist vom letzten Bauen. Ein Suchdienst darf sie nicht
     statt der echten Startseite aufnehmen. -->
<meta name="robots" content="noindex">
<meta name="theme-color" content="#0E2647">
<link rel="icon" type="image/png" href="%%FAVICON%%">
<script>(function(){try{var t=localStorage.getItem('thema');if(t!=='dark'&&t!=='light'){t='light';}document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>
<style>%%STIL%%</style>
</head>
<body>
%%KOPFZEILE%%
<main id="inhalt" class="%%HAUPTKLASSE%%">
%%INHALT%%
</main>
%%FUSSZEILE%%
%%HINWEIS%%
<!-- Auffangnetz %%FASSUNG%% · %%GRUND%% · %%WOHER%% -->
<script>
(function () {
  "use strict";
  var LAGER = "%%LAGER%%" === "1";
  var OFFEN = "%%OFFEN%%" === "1";
  var MAILADRESSE = "cto@tech.mvlg-wag.de";

  function id(name) { return document.getElementById(name); }
  function wert(name) { var f = id(name); return f ? f.value.trim() : ""; }

  /* --- Farbschema und Menü ----------------------------------------------
     Dieselben zwei Handgriffe wie in statisch/js/basis.js. Bewusst
     nachgebaut statt mitgeliefert: basis.js meldet auch den Service Worker
     an, und ein Hintergrundskript, das ausgerechnet die Notfassung in den
     Zwischenspeicher legt, wäre ein Fehler, den man wochenlang nicht mehr
     los wird. */
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-thema]")) {
      var wurzel = document.documentElement;
      var neu = wurzel.getAttribute("data-theme") === "dark" ? "light" : "dark";
      wurzel.setAttribute("data-theme", neu);
      try { localStorage.setItem("thema", neu); } catch (f) { /* Privatmodus */ }
      return;
    }
    var kopf = id("kopfzeile");
    var burger = e.target.closest("[data-burger]");
    if (burger && kopf) {
      var auf = !kopf.classList.contains("offen");
      kopf.classList.toggle("offen", auf);
      burger.setAttribute("aria-expanded", auf ? "true" : "false");
      return;
    }
    if (kopf && kopf.classList.contains("offen") && !kopf.contains(e.target)) {
      kopf.classList.remove("offen");
    }
  });

  /* --- Der Hinweis beim Anmelden ---------------------------------------- */
  var schleier = id("ausfall");
  var wartenText = id("warten-text");
  var nochmal = id("nochmal");
  var wiederDa = id("wieder-da");
  var uhr = null;
  var abstaende = [15, 15, 30, 30, 60, 120, 300];
  var stelle = 0;
  var restlich = abstaende[0];

  function pruefen(danach) {
    fetch("/__ausfall/lebt", { cache: "no-store" })
      .then(function (a) { return a.text(); })
      .then(function (t) { danach(t.trim() === "ja"); })
      .catch(function () { danach(false); });
  }

  function daIst() {
    if (uhr) { window.clearInterval(uhr); uhr = null; }
    wartenText.textContent = "Das System ist wieder da.";
    nochmal.hidden = true;
    wiederDa.hidden = false;
  }

  function ticken() {
    restlich -= 1;
    if (restlich > 0) {
      wartenText.textContent = "Nächster Versuch in " + restlich
        + " Sekunden. Sobald es wieder geht, steht es hier.";
      return;
    }
    wartenText.textContent = "Wird geprüft …";
    pruefen(function (lebt) {
      if (lebt) { daIst(); return; }
      stelle = Math.min(stelle + 1, abstaende.length - 1);
      restlich = abstaende[stelle];
      wartenText.textContent = "Noch nicht. Nächster Versuch in " + restlich
        + " Sekunden.";
    });
  }

  /* Nachgefragt wird erst, wenn der Kasten offen ist. Wer nur die Seite
     liest, soll deswegen keine Anfragen im Hintergrund verschicken - er hat
     mit dem Ausfall nichts zu tun und soll auch nichts davon merken. */
  function aufmachen() {
    if (!schleier || !schleier.hidden) { return; }
    schleier.hidden = false;
    document.body.style.overflow = "hidden";
    if (!uhr) { uhr = window.setInterval(ticken, 1000); }
    var zu = id("ausfall-zu");
    if (zu) { zu.focus(); }
  }

  function zumachen() {
    if (!schleier) { return; }
    schleier.hidden = true;
    document.body.style.overflow = "";
    if (uhr) { window.clearInterval(uhr); uhr = null; }
  }

  document.addEventListener("click", function (e) {
    var anmelden = e.target.closest("[data-anmelden]");
    if (anmelden) { e.preventDefault(); aufmachen(); return; }
    if (e.target.closest("#ausfall-zu") || e.target === schleier) {
      zumachen();
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && schleier && !schleier.hidden) { zumachen(); }
  });

  if (nochmal) {
    nochmal.addEventListener("click", function () {
      nochmal.disabled = true;
      wartenText.textContent = "Wird geprüft …";
      pruefen(function (lebt) {
        nochmal.disabled = false;
        if (lebt) { daIst(); return; }
        stelle = 0;
        restlich = abstaende[0];
        wartenText.textContent = "Noch nicht erreichbar. Wir probieren weiter.";
      });
    });
  }
  if (wiederDa) {
    wiederDa.addEventListener("click", function (e) {
      /* Ein eindeutiger GET. Sonst holt der Browser die Fehlerantwort
         von eben aus seinem Zwischenspeicher und es sieht aus, als wäre
         nichts passiert. */
      e.preventDefault();
      window.location.replace("/login?_auffangnetz_reload=" + Date.now());
    });
  }
  if (OFFEN) { aufmachen(); }

  /* --- Ein Formular abschicken ------------------------------------------
     Alle drei Formulare der Seite gehen denselben Weg: absperren, schicken,
     eine Zeile sagen, was daraus geworden ist. Keins darf stillschweigend
     scheitern - wer sich bewirbt und nichts hört, bewirbt sich kein zweites
     Mal. */
  function sagen(kasten, titel, text) {
    if (!kasten) { return; }
    var innen = kasten.querySelector("div") || kasten;
    innen.innerHTML = "";
    if (titel) {
      var stark = document.createElement("strong");
      stark.textContent = titel;
      innen.appendChild(stark);
      innen.appendChild(document.createElement("br"));
    }
    innen.appendChild(document.createTextNode(text));
    kasten.hidden = false;
    kasten.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function schicken(weg, daten, knopf, kasten, gut, schlecht) {
    knopf.disabled = true;
    fetch(weg, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(daten)
    })
      .then(function (a) { return a.json().catch(function () { return {}; }); })
      .then(function (d) {
        if (d && d.ok) { gut(d); return; }
        knopf.disabled = false;
        schlecht((d && d.grund) || "");
      })
      .catch(function () {
        knopf.disabled = false;
        schlecht("Im Moment ist gar keine Verbindung da.");
      });
  }

  /* --- Kontaktformular ---------------------------------------------------
     Es steht auf der Seite, also muss es auch etwas tun. Ein Formular, das
     freundlich aussieht und nichts bewirkt, ist schlimmer als keins: Die
     Person wartet auf eine Antwort, die nie kommt. */
  var kForm = id("kontakt-formular");
  if (kForm) {
    var kDanke = id("k-danke");
    var kKnopf = id("k-absenden");
    kForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var name = wert("k-name");
      var post = wert("k-email");
      var text = wert("k-text");
      if (!name || !post || text.length < 10) {
        sagen(kDanke, "Da fehlt noch etwas.",
              "Bitte Name, E-Mail und ein paar Sätze zu deiner Frage.");
        kDanke.className = "meldung meldung-warnung";
        return;
      }
      if (!LAGER) {
        sagen(kDanke, "Das geht gerade nicht.",
              "Schreib bitte direkt an " + MAILADRESSE + ".");
        kDanke.className = "meldung meldung-warnung";
        return;
      }
      schicken("/__ausfall/nachricht",
        { name: name, email: post, nachricht: text,
          webseite: wert("k-webseite") },
        kKnopf, kDanke,
        function () {
          kForm.hidden = true;
          kDanke.className = "meldung meldung-gut";
          sagen(kDanke, "Danke für deine Nachricht!",
                "Wir melden uns bei dir unter " + post + ".");
        },
        function (grund) {
          kDanke.className = "meldung meldung-fehler";
          sagen(kDanke, "Das hat nicht geklappt.",
                (grund ? grund + " " : "") + "Schreib sonst direkt an "
                + MAILADRESSE + ", dann geht nichts verloren.");
        });
    });
  }

  /* --- Bewerbung --------------------------------------------------------- */
  var bForm = id("bewerbung-formular");
  if (bForm) {
    var bDanke = id("b-danke");
    var bKnopf = id("b-absenden");
    bForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var daten = {
        vorname: wert("b-vorname"), nachname: wert("b-nachname"),
        klasse: wert("b-klasse"), abteilung: wert("b-abteilung"),
        email: wert("b-email"), telefonnummer: wert("b-telefon"),
        motivation: wert("b-motivation"), interessen: wert("b-interessen"),
        vorwissen: wert("b-vorwissen"), webseite: wert("b-webseite")
      };
      var fehlt = ["vorname", "nachname", "klasse", "abteilung", "email",
                   "telefonnummer", "motivation", "interessen"]
        .filter(function (f) { return !daten[f]; });
      if (fehlt.length) {
        bDanke.className = "meldung meldung-warnung";
        sagen(bDanke, "Da fehlt noch etwas.",
              "Bitte fülle alle Felder aus – nur „Vorwissen“ darf leer "
              + "bleiben.");
        return;
      }
      if (daten.motivation.length < 20) {
        bDanke.className = "meldung meldung-warnung";
        sagen(bDanke, "Ein bisschen mehr, bitte.",
              "Schreib ein paar Sätze zu deiner Motivation – daran "
              + "entscheidet sich einiges.");
        return;
      }
      if (!LAGER) {
        bDanke.className = "meldung meldung-warnung";
        sagen(bDanke, "Das geht gerade nicht.",
              "Schick deine Bewerbung bitte an " + MAILADRESSE
              + " – sie geht dann nicht verloren.");
        return;
      }
      schicken("/__ausfall/bewerben", daten, bKnopf, bDanke,
        function () {
          bForm.hidden = true;
          bDanke.className = "meldung meldung-gut";
          sagen(bDanke, "Danke, " + daten.vorname + "!",
                "Deine Bewerbung liegt bei uns. Der Vorstand sieht sich jede "
                + "in Ruhe an – du bekommst in der Regel innerhalb von zwei "
                + "Wochen eine Rückmeldung, in jedem Fall aber eine. Eine "
                + "Bestätigung kommt an " + daten.email + ".");
        },
        function (grund) {
          bDanke.className = "meldung meldung-fehler";
          sagen(bDanke, "Das hat nicht geklappt.",
                (grund ? grund + " " : "") + "Falls es dabei bleibt: schreib "
                + "bitte an " + MAILADRESSE + ", dann geht nichts verloren.");
        });
    });
  }

  /* --- Störung melden ---------------------------------------------------- */
  var mForm = id("formular");
  if (mForm) {
    var mAntwort = id("antwort");
    var mKnopf = id("absenden");
    mForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var text = wert("f-text");
      if (text.length < 3) {
        mAntwort.className = "meldung meldung-warnung";
        sagen(mAntwort, "", "Schreib bitte kurz, was du gemacht hast – sonst "
              + "weiß er nicht, wo er suchen soll.");
        return;
      }
      if (!LAGER) {
        mAntwort.className = "meldung meldung-warnung";
        sagen(mAntwort, "", "Das Meldefeld ist nicht eingerichtet. Bitte "
              + "direkt an " + MAILADRESSE + ".");
        return;
      }
      schicken("/__ausfall/melden",
        { text: text, name: wert("f-name"), kontakt: wert("f-kontakt"),
          lage: window.location.pathname + window.location.search,
          grund: "Anmeldung" },
        mKnopf, mAntwort,
        function (d) {
          mForm.hidden = true;
          mAntwort.className = "meldung meldung-gut";
          /* Nur behaupten, was wirklich passiert ist. Eine Zusage, die man
             nicht einhält, ist schlimmer als ein ehrliches "das ging
             nicht". */
          sagen(mAntwort, "", d.geklingelt
            ? "Angekommen. Der CTO hat eine Meldung aufs Telefon bekommen, "
              + "und sobald die Plattform wieder läuft, wird daraus ein "
              + "Support-Ticket. Du musst nichts weiter tun."
            : "Gespeichert. Sobald die Plattform wieder läuft, wird daraus "
              + "ein Support-Ticket für den CTO. Du musst nichts weiter tun.");
        },
        function (grund) {
          mAntwort.className = "meldung meldung-fehler";
          sagen(mAntwort, "", grund || "Das hat nicht geklappt. Bitte später "
                + "noch einmal versuchen.");
        });
    });
  }
})();
</script>
<!-- Nur auf /quiz gefuellt: die Auswertung aus statisch/js/quiz.js. Sie steht
     NACH dem Skript oben, weil sie beim Laden schon Fragen im Dokument
     erwartet. -->
<script>%%ZUSATZSKRIPT%%</script>
</body>
</html>`;


/* Einmal beim Start zusammengesetzt statt bei jeder Anfrage: Stylesheet und
   Schriften sind zusammen fast ein halbes Megabyte, und ein Auffangnetz soll
   im Ernstfall nicht auch noch rechnen. */
const KOPFZEILE_FERTIG = KOPFZEILE.replace(/%%LOGO%%/g, () => LOGO);

/* Ohne eingebackene Fragen faellt der ganze Anriss weg - sonst stuende dort
   ein Knopf, der auf die Startseite zurueckwirft. */
const QUIZ_ANRISS = /<section id="quiz-anriss"[\s\S]*?<\/section>/;

const LANDING_FERTIG = (QUIZ_FRAGEN.length ? LANDING
                                           : LANDING.replace(QUIZ_ANRISS, ""))
  .replace("%%VORTEILE%%", () => VORTEILE)
  .replace("%%STUFEN%%", () => STUFEN)
  .replace("%%ANGEBOT_ABSCHNITT%%", () => ANGEBOT_ABSCHNITT)
  .replace("%%PORTFOLIO_ABSCHNITT%%", () => PORTFOLIO_ABSCHNITT)
  .replace("%%QUIZANZAHL%%", () => String(QUIZ_FRAGEN.length))
  .replace(/%%WAPPEN%%/g, () => WAPPEN);

const BEWERBUNG_FERTIG = BEWERBUNG.replace("%%ABTEILUNGEN%%", () =>
  ABTEILUNGEN.map((a) =>
    '<option value="' + a.key + '">' + a.label + "</option>").join("\n"));
