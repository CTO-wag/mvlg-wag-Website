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
const FASSUNG = "2026-08-21-a";

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

/* In welche Abteilung man sich bewerben kann. Fest eingetragen und nicht vom
   Server geholt - der antwortet ja gerade nicht. Aendert sich die Liste im
   Dashboard, muss sie hier nachgezogen werden; die Plattform prueft die
   Angabe beim Einlesen aber ohnehin noch einmal, eine veraltete Liste kostet
   also hoechstens eine Rueckfrage. Die Exekutive fehlt mit Absicht: In die
   bewirbt man sich nicht. */
/* Schuladressen kommen nicht durch - dieselbe Regel wie im echten Formular
   (website/routen/bewerbung.py). Hier draussen geprueft, damit die Person es
   sofort erfaehrt und nicht erst, wenn die Plattform Stunden spaeter einliest
   und die Bewerbung stillschweigend verwirft. */
const GESPERRTE_MAILDOMAENEN = ["mvlg-ko.de"];

const ABTEILUNGEN = [
  { key: "tech", label: "Tech" },
  { key: "marketing", label: "Marketing" },
  { key: "recruitment", label: "Recruitment" },
];


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
      const antwort = await fetch(anfrage);
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
  const leer = { meldungen: [], bewerbungen: [] };
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
        && (kennung.startsWith("meldung:") || kennung.startsWith("bewerbung:"))) {
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

/**
 * Die Ersatzseite. Alles darin ist eingebaut - kein Bild, keine Schrift, keine
 * zweite Datei. Das ist der ganze Punkt: Der Server, von dem die sonst kaemen,
 * ist ja gerade der, der nicht antwortet.
 */
function ausfallseite(adresse, umgebung, grund) {
  const meldenMoeglich = Boolean(umgebung.LAGER);
  /* Auf der oeffentlichen Seite steht, wer wir sind - auf dem Dashboard
     nicht. Wer sich dort anmelden wollte, ist in der AG und braucht keine
     Vorstellung; ihm waere sie nur im Weg. Erkannt am Namen: Das Dashboard
     liegt unter app.*, notfalls per Variable DASHBOARD_HOST festgelegt. */
  const istDashboard = umgebung.DASHBOARD_HOST
    ? adresse.hostname === umgebung.DASHBOARD_HOST
    : adresse.hostname.startsWith("app.");
  const seite = HTML_FERTIG
    .replace(/%%GRUND%%/g, maskiert(grund))
    .replace(/%%MELDEN%%/g, meldenMoeglich ? "" : "hidden")
    .replace(/%%LANDING%%/g, istDashboard ? "" : landingHtml(meldenMoeglich))
    .replace(/%%FASSUNG%%/g, FASSUNG)
    .replace(/%%WOHER%%/g, maskiert(adresse.pathname + adresse.search));
  return new Response(seite, {
    /* 503 und nicht 200: Fuer Menschen steht es auf der Seite, fuer Maschinen
       im Status. Ein Suchdienst darf diese Seite nicht als unseren Inhalt
       verstehen und statt der Startseite aufnehmen. Retry-After sagt ihm
       ausserdem, dass es sich lohnt, spaeter wiederzukommen. */
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

/**
 * Die Seite, die ein Besucher unter der Fehlermeldung sieht.
 *
 * Der Auftrag dazu war deutlich: Bewerbungen sollen IMMER entgegengenommen
 * werden. Ein Interessent, der zufaellig in einen Ausfall geraet, ist der
 * teuerste Verlust dieser Anlage - er kommt nicht wieder, und niemand
 * erfaehrt je davon.
 *
 * Deshalb steht hier die Startseite noch einmal, fest eingetragen. Was im
 * Dashboard gepflegt wird (Aktivitaeten, Arbeitsproben, Vorteilsliste, Quiz),
 * fehlt bewusst: Es kaeme aus derselben Datenbank, die gerade nicht
 * antwortet. Was bleibt, ist das, was sich seit der Gruendung nicht aendert -
 * wer wir sind, wie das Jahr laeuft, und das Formular.
 */
function landingHtml(meldenMoeglich) {
  const wahl = ABTEILUNGEN.map(function (a) {
    return '<option value="' + a.key + '">' + a.label + "</option>";
  }).join("");
  /* Den Meldeknopf hier selbst einsetzen und nicht draussen: Die aeussere
     Vorlage ersetzt ihre Platzhalter, bevor dieser Block ueberhaupt
     eingefuegt wird - der Platzhalter darin bliebe sonst stehen. */
  return LANDING_FERTIG
    .replace("%%ABTEILUNGEN%%", wahl)
    .replace(/%%MELDEN%%/g, meldenMoeglich ? "" : "hidden");
}

const LANDING_HTML = `
<main class="huelle">

  <section class="abschnitt aufmacher">
    <div>
      <span class="hut">Sch&uuml;ler-AG am Max-von-Laue-Gymnasium Koblenz</span>
      <h1>Deine erste Aktie kaufst du nicht im Unterricht. Bei uns schon.</h1>
      <p class="motto">An alle, die gr&ouml;&szlig;er denken.</p>
      <p class="fuehrung">Steuern, Vertr&auml;ge, B&ouml;rse. Sachen, die
        sp&auml;ter einfach wichtig werden, kommen in der Schule kaum vor. Wir
        holen das nach. Kein Frontalvortrag: Wir simulieren Portfolios, rechnen
        eigene Ideen durch und treten bei echten Wettbewerben an.</p>
      <div class="knopfzeile">
        <a class="btn" href="#bewerbung">Jetzt bewerben</a>
        <a class="btn btn-zweit" href="#ueber-uns">Mehr erfahren</a>
      </div>
    </div>
    <div class="wappen-feld" aria-hidden="true">
      <img src="data:image/webp;base64,%%LOGO%%" width="226" height="180" alt="">
    </div>
    <ul class="eckdaten">
      <li><strong>Klasse 9&ndash;13</strong><span>Egal, welcher Schnitt</span></li>
      <li><strong>Alle zwei Wochen</strong><span>Feste Treffen</span></li>
      <li><strong>Vier Abteilungen</strong><span>Such dir deine aus</span></li>
      <li><strong>Kein Vorwissen</strong><span>Nur Interesse</span></li>
    </ul>
  </section>

  <section class="abschnitt" id="ueber-uns">
    <div class="raster-2">
      <div>
        <span class="hut">&Uuml;ber uns</span>
        <h2>Von Sch&uuml;lern geleitet. Sonst niemandem.</h2>
        <p>Wir entscheiden selbst, woran wir arbeiten, wer was &uuml;bernimmt
          und wer wann Verantwortung tr&auml;gt. Wer will, leitet irgendwann
          ein eigenes Projekt oder landet im Core-Team, das die AG f&uuml;hrt.</p>
        <p>Getroffen wird alle zwei Wochen. Dazwischen l&auml;uft alles
          &uuml;ber unser eigenes Dashboard: Aufgaben, Termine,
          Beschl&uuml;sse, alles an einem Ort.</p>
        <p>Klassenstufen 9 bis 13. Vorkenntnisse brauchst du keine.
          Einser-Schnitt auch nicht.</p>
      </div>
      <div class="vorteile">
        <h3>Was du mitnimmst</h3>
        <ul>
          <li>Wie M&auml;rkte, Zinsen und Risiko wirklich zusammenh&auml;ngen</li>
          <li>Ein eigenes Projekt von der Idee bis zur Pr&auml;sentation</li>
          <li>Auftritte bei echten Wettbewerben</li>
          <li>Verantwortung, die man dir nicht wieder abnimmt</li>
          <li>Leute, die dasselbe interessiert</li>
        </ul>
      </div>
    </div>
  </section>

  <section class="abschnitt">
    <span class="hut">Jahresablauf</span>
    <h2>Zwei Halbjahre, zwei Welten</h2>
    <div class="raster-2" style="margin-top:var(--r6);">
      <div class="tafel halbjahr">
        <span class="nummer" aria-hidden="true">1</span>
        <h3>Wirtschaft &amp; Investment</h3>
        <p>Angebot und Nachfrage, Risiko und Rendite, Diversifikation. Wir
          arbeiten mit fiktiven Portfolios, checken echte Marktentwicklungen
          und starten beim Planspiel B&ouml;rse. Wer richtig gut ist,
          qualifiziert sich f&uuml;r die Wharton Investment Challenge.</p>
      </div>
      <div class="tafel halbjahr zwei">
        <span class="nummer" aria-hidden="true">2</span>
        <h3>Unternehmertum &amp; eigene Projekte</h3>
        <p>Ihr entwickelt in Teams eigene Gesch&auml;ftsideen, baut ein
          Gesch&auml;ftsmodell und findet raus, wer eure Zielgruppe
          &uuml;berhaupt ist. Ziel ist Jugend Gr&uuml;ndet oder Startup Teens,
          mit einem Konzept, das ihr wirklich pr&auml;sentieren k&ouml;nnt.</p>
      </div>
    </div>
    <p class="nachsatz">Erst verstehen, dann machen, dann draufschauen, was
      dabei rauskam. In der Reihenfolge.</p>
  </section>

  <section class="abschnitt">
    <span class="hut">Dein Weg</span>
    <h2>Du f&auml;ngst an, wo du stehst</h2>
    <ol class="stufen">
      <li><strong>Mitglied</strong>
        <span>Du bist dabei, arbeitest mit und lernst, wie die AG
        funktioniert.</span></li>
      <li><strong>Eigene Aufgaben</strong>
        <span>Du &uuml;bernimmst Dinge, die wirklich jemand braucht &ndash;
        und bringst sie zu Ende.</span></li>
      <li><strong>Projektleitung</strong>
        <span>Du f&uuml;hrst ein Team durch ein eigenes Projekt.</span></li>
      <li><strong>Core-Team</strong>
        <span>Du entscheidest mit, wohin die AG geht.</span></li>
    </ol>
    <p class="nachsatz">Aufstieg nach Engagement, nicht nach Alter. Und den
      Schwerpunkt kannst du jederzeit wechseln.</p>
  </section>

  <section class="abschnitt bewerbung" id="bewerbung">
    <span class="hut">Bewerbung</span>
    <h2>Klingt nach dir?</h2>
    <p class="fuehrung">Keine Vorkenntnisse n&ouml;tig, kein Einser-Schnitt
      gefordert. Interesse und Zuverl&auml;ssigkeit reichen. Die Bewerbung
      dauert f&uuml;nf Minuten, dann melden wir uns.</p>
    <p class="fuehrung"><strong>Das geht auch jetzt.</strong> Deine Bewerbung
      wird sicher hinterlegt und eingetragen, sobald die Plattform wieder
      l&auml;uft &ndash; meist innerhalb weniger Minuten. Es geht nichts
      verloren.</p>

    <div class="karte-formular">
      <form id="bewerbung-formular" novalidate>
        <div class="felder">
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
          <label>Wunsch-Abteilung
            <span class="meta">Nicht bindend &ndash; wir sprechen
              dar&uuml;ber.</span>
            <select id="b-abteilung" required>
              <option value="" disabled selected>Bitte ausw&auml;hlen</option>
              %%ABTEILUNGEN%%
            </select>
          </label>
          <label>E-Mail
            <span class="meta">Bitte privat &ndash; keine Schuladresse.</span>
            <input type="email" id="b-email" maxlength="160" required
                   autocomplete="email">
          </label>
          <label>Telefonnummer
            <span class="meta">F&uuml;r die WhatsApp-Gruppe, wenn es
              klappt.</span>
            <input type="tel" id="b-telefon" maxlength="40" required
                   inputmode="tel" placeholder="0163 1234567" autocomplete="tel">
          </label>
          <label class="voll">Warum willst du mitmachen?
            <textarea id="b-motivation" maxlength="3000" required
                      placeholder="Ein paar S&auml;tze reichen."></textarea>
          </label>
          <label class="voll">Was interessiert dich besonders?
            <textarea id="b-interessen" maxlength="3000" required
                      placeholder="B&ouml;rse, Gr&uuml;nden, Marketing, Technik &hellip;"></textarea>
          </label>
          <label class="voll">Vorwissen
            <span class="meta">Optional. &bdquo;Keines&ldquo; ist eine
              v&ouml;llig normale Antwort.</span>
            <textarea id="b-vorwissen" maxlength="3000"></textarea>
          </label>
        </div>
        <div class="lesehilfe" aria-hidden="true">
          <label>Bitte leer lassen
            <input type="text" id="b-webseite" tabindex="-1" autocomplete="off">
          </label>
        </div>
        <div class="formular-fuss">
          <button type="submit" class="btn" id="b-absenden">Bewerbung
            abschicken</button>
          <span class="meta">Mit dem Absenden stimmst du zu, dass wir deine
            Angaben zur Bearbeitung speichern.</span>
        </div>
      </form>
      <div class="danke" id="b-danke" hidden></div>
    </div>

    <details class="melden" id="melden" %%MELDEN%%>
      <summary>St&ouml;rung an den CTO melden</summary>
      <p style="margin-top:var(--r3);">Damit er wei&szlig;, dass es nicht
        l&auml;uft &ndash; und ab wann. Anmelden musst du dich daf&uuml;r
        nicht, das geht gerade ohnehin nicht.</p>
      <form id="formular" novalidate>
        <div class="felder">
          <label class="voll">Was wolltest du gerade machen?
            <textarea id="f-text" maxlength="2000" required
              placeholder="Zum Beispiel: Ich wollte meine Aufgaben ansehen."></textarea>
          </label>
          <label>Dein Name
            <span class="meta">Damit er wei&szlig;, wer es gemeldet hat.</span>
            <input id="f-name" maxlength="80" autocomplete="name">
          </label>
          <label>E-Mail
            <span class="meta">Freiwillig, f&uuml;r eine Antwort.</span>
            <input id="f-kontakt" type="email" maxlength="120"
                   autocomplete="email">
          </label>
        </div>
        <button type="submit" class="btn-zweit" id="absenden">Meldung
          abschicken</button>
      </form>
      <p class="antwort" id="antwort" hidden></p>
    </details>
  </section>

</main>
`;

const HTML = `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<meta name="theme-color" content="#0E2647">
<title>Gerade nicht erreichbar | Wirtschafts- &amp; Investment-AG</title>
<style>
  /* Die Schrift der Ueberschriften kommt eingebettet mit - sie ist das, was
     die Seite als unsere erkennbar macht. Der Fliesstext bleibt bei der
     Systemschrift: IBM Plex Sans waere noch einmal 60 KB, und der Unterschied
     faellt im Absatz kaum auf, in einer Ueberschrift dagegen sofort. */
  @font-face{
    font-family:'Space Grotesk'; font-style:normal; font-weight:600;
    font-display:swap;
    src:url(data:font/woff2;base64,%%GROTESK%%) format('woff2');
  }

  :root{
    --bg:#F6F7F4; --bg-tief:#EEF2EF;
    --flaeche:#FFFFFF; --flaeche-2:#EEF2EF; --flaeche-3:#E4EAE6;
    --text:#18211F; --text-stark:#101917;
    --gedaempft:#66726D; --gedaempft-2:#8A9691;
    --linie:rgba(24,33,31,0.12); --linie-stark:rgba(24,33,31,0.22);
    --navy:#0E2647; --navy-tief:#081A33; --navy-weich:#1E3F6E;
    --navy-hauch:rgba(14,38,71,0.08);
    --amber:#B7791F; --amber-hell:#D9A441;
    --amber-hauch:rgba(183,121,31,0.10);
    --r1:.25rem; --r2:.5rem; --r3:.75rem; --r4:1rem;
    --r5:1.5rem; --r6:2rem; --r7:3rem; --r8:4.5rem;
    --rund:10px; --rund-klein:7px;
    --schatten:0 1px 2px rgba(24,33,31,.05), 0 14px 34px -26px rgba(24,33,31,.32);
    --schatten-hoch:0 2px 6px rgba(24,33,31,.07), 0 24px 48px -28px rgba(24,33,31,.40);
    --schrift:system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
    --schrift-titel:'Space Grotesk', system-ui, sans-serif;
    --schrift-mono:ui-monospace, 'SF Mono', 'Cascadia Mono', Consolas, monospace;
    --seitenrand:clamp(1.1rem, 5vw, 2.5rem);
  }

  *{box-sizing:border-box;}
  html{-webkit-text-size-adjust:100%;}
  body{
    margin:0; background:var(--bg); color:var(--text);
    font-family:var(--schrift); line-height:1.7; font-size:1rem;
    padding:0 0 env(safe-area-inset-bottom,0px);
    -webkit-font-smoothing:antialiased;
  }
  .huelle{
    max-width:64rem; margin:0 auto;
    padding-left:calc(var(--seitenrand) + env(safe-area-inset-left,0px));
    padding-right:calc(var(--seitenrand) + env(safe-area-inset-right,0px));
  }
  h1,h2,h3{font-family:var(--schrift-titel); font-weight:600; line-height:1.2;
           margin:0; letter-spacing:-.015em;}
  p{margin:0 0 var(--r3);}
  a{color:var(--navy); text-underline-offset:3px;}

  /* Kapitelmarke: ein kurzer Strich vor der kleinen Ueberschrift - dieselbe
     Geste wie auf der echten Seite. Sie sagt dem Auge beim Scrollen "hier
     faengt etwas Neues an". */
  .hut{
    display:block; font-size:.72rem; font-weight:700;
    text-transform:uppercase; color:var(--amber); margin-bottom:var(--r2);
    letter-spacing:.12em;
  }
  .abschnitt .hut::before{
    content:""; display:inline-block; vertical-align:middle;
    width:1.7rem; height:2px; margin-right:.55rem;
    background:var(--amber); border-radius:2px;
  }

  /* --- Die Störungsmeldung ganz oben ------------------------------------
     Ein schmales Band, kein Kasten in der Bildmitte: Die Nachricht ist
     wichtig, aber sie ist nicht der Grund, aus dem jemand hier ist. */
  .band{
    background:var(--navy); color:#fff;
    padding:calc(var(--r4) + env(safe-area-inset-top,0px)) 0 var(--r4);
    border-bottom:3px solid var(--amber);
  }
  .band .huelle{display:flex; gap:var(--r4); align-items:flex-start;
                flex-wrap:wrap;}
  .band-text{flex:1 1 20rem; min-width:0;}
  .band h1{font-size:clamp(1.15rem, .9rem + 1vw, 1.5rem); color:#fff;
           margin-bottom:var(--r2);}
  .band p{color:#C8D6E8; margin:0; font-size:.94rem;}
  .band .knopfzeile{margin-top:var(--r3);}
  .band-uhr{
    display:flex; align-items:flex-start; gap:.55rem; font-size:.85rem;
    color:#9FB6D1; margin-top:var(--r3);
  }
  .punkt{
    width:.5rem; height:.5rem; border-radius:50%; background:var(--amber-hell);
    flex:0 0 auto; margin-top:.5rem;
    animation:pulsieren 1.8s ease-in-out infinite;
  }
  @keyframes pulsieren{0%,100%{opacity:.35;}50%{opacity:1;}}
  @media (prefers-reduced-motion: reduce){.punkt{animation:none;}}

  /* --- Knöpfe -------------------------------------------------------------- */
  .btn, button{
    font:inherit; font-weight:600; cursor:pointer; border:1px solid transparent;
    border-radius:var(--rund-klein); padding:.72rem 1.35rem; min-height:2.75rem;
    display:inline-flex; align-items:center; justify-content:center;
    text-decoration:none; transition:background .18s ease, transform .18s ease;
  }
  .btn{background:var(--navy); color:#fff;}
  .btn:hover{background:var(--navy-weich); transform:translateY(-1px);}
  .btn-hell{background:var(--amber-hell); color:var(--navy-tief);}
  .btn-hell:hover{background:#E7B75C;}
  .btn-rand{background:transparent; color:#fff; border-color:rgba(255,255,255,.4);}
  .btn-rand:hover{background:rgba(255,255,255,.12);}
  .btn-zweit{background:transparent; color:var(--navy); border-color:var(--linie-stark);}
  .btn-zweit:hover{background:var(--navy-hauch);}
  button[disabled]{opacity:.5; cursor:default; transform:none;}
  .knopfzeile{display:flex; flex-wrap:wrap; gap:var(--r3);}

  /* --- Aufmacher ----------------------------------------------------------- */
  .abschnitt{margin-bottom:var(--r7); scroll-margin-top:2rem;}
  .aufmacher{
    display:grid; grid-template-columns:minmax(0,1.25fr) minmax(0,.75fr);
    gap:var(--r6); align-items:center; padding:var(--r7) 0 var(--r6);
  }
  .aufmacher .hut::before{display:none;}
  .aufmacher h1{
    max-width:20ch; font-size:clamp(2rem, 1.2rem + 3.2vw, 3.1rem);
    background:linear-gradient(100deg, var(--navy) 35%, var(--amber) 82%);
    -webkit-background-clip:text; background-clip:text; color:transparent;
  }
  .motto{
    font-family:var(--schrift-mono); font-size:.86rem; letter-spacing:.02em;
    color:var(--amber); margin:var(--r3) 0 var(--r4);
  }
  .fuehrung{font-size:1.03rem; color:var(--gedaempft); max-width:52ch;
            line-height:1.8;}
  .aufmacher .knopfzeile{margin-top:var(--r5);}
  /* Das Wappen mit einem warmen Schein dahinter - sonst schwebt es im Nichts. */
  .wappen-feld{position:relative; display:flex; justify-content:center;}
  .wappen-feld::before{
    content:""; position:absolute; inset:-12% -6%;
    background:radial-gradient(circle at 50% 45%, var(--amber-hauch) 0%,
               transparent 68%);
  }
  .wappen-feld img{
    position:relative; width:100%; max-width:300px; height:auto;
    filter:drop-shadow(0 18px 34px rgba(8,15,26,.28));
  }
  .eckdaten{
    list-style:none; margin:var(--r5) 0 0; padding:0;
    display:grid; gap:var(--r3) var(--r5);
    grid-template-columns:repeat(auto-fit, minmax(11rem, 1fr));
    grid-column:1 / -1;
  }
  .eckdaten li{
    display:flex; flex-direction:column; gap:.1rem;
    border-left:3px solid var(--amber); padding-left:var(--r3);
  }
  .eckdaten strong{font-family:var(--schrift-titel); font-size:1rem;}
  .eckdaten span{color:var(--gedaempft); font-size:.9rem;}

  /* --- Zweispalter und Tafeln ---------------------------------------------- */
  .raster-2{display:grid; grid-template-columns:1fr 1fr; gap:var(--r5);
            align-items:start;}
  .tafel{
    background:var(--flaeche); border:1px solid var(--linie);
    border-radius:var(--rund); padding:var(--r5); box-shadow:var(--schatten);
  }
  .halbjahr{position:relative; padding-left:4.2rem;
            border-left:4px solid var(--navy);}
  .halbjahr.zwei{border-left-color:var(--amber);}
  .halbjahr h3{margin-bottom:var(--r2);}
  .halbjahr p{margin:0; color:var(--gedaempft);}
  .nummer{
    position:absolute; left:1.4rem; top:1.3rem;
    font-family:var(--schrift-titel); font-size:2.1rem; font-weight:600;
    line-height:1; color:var(--navy); opacity:.22;
  }
  .halbjahr.zwei .nummer{color:var(--amber); opacity:.35;}
  .nachsatz{margin:var(--r5) 0 0; color:var(--gedaempft); font-size:.94rem;}
  .vorteile{
    background:var(--flaeche-2); border:1px solid var(--linie);
    border-radius:var(--rund); padding:var(--r5);
  }
  .vorteile h3{margin-bottom:var(--r3); font-size:1.05rem;}
  .vorteile ul{list-style:none; margin:0; padding:0; display:grid; gap:.6rem;}
  .vorteile li{position:relative; padding-left:1.5rem; color:var(--gedaempft);}
  .vorteile li::before{
    content:""; position:absolute; left:0; top:.62rem; width:.55rem;
    height:.55rem; border-radius:50%; border:2px solid var(--amber);
  }

  /* --- Dein Weg: nummerierte Kreise an einer Linie -------------------------- */
  .stufen{
    list-style:none; counter-reset:stufe; margin:var(--r6) 0 0;
    padding:0 0 0 .2rem; position:relative;
  }
  .stufen::before{
    content:""; position:absolute; left:1.05rem; top:.9rem; bottom:.9rem;
    width:2px; background:var(--linie);
  }
  .stufen li{
    counter-increment:stufe; position:relative;
    padding:0 0 var(--r5) 3.2rem; display:flex; flex-direction:column; gap:.15rem;
  }
  .stufen li:last-child{padding-bottom:0;}
  .stufen li::before{
    content:counter(stufe); position:absolute; left:0; top:-.1rem;
    width:2.2rem; height:2.2rem; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    background:var(--flaeche); border:2px solid var(--navy); color:var(--navy);
    font-family:var(--schrift-mono); font-size:.85rem; font-weight:600;
  }
  .stufen strong{font-family:var(--schrift-titel); font-size:1.02rem;}
  .stufen span{color:var(--gedaempft);}

  /* --- Bewerbung ------------------------------------------------------------ */
  .bewerbung{
    background:linear-gradient(135deg, var(--amber-hauch) 0%,
               var(--navy-hauch) 100%);
    border:1px solid color-mix(in srgb, var(--amber) 16%, transparent);
    border-radius:var(--rund); padding:var(--r6) var(--r5);
  }
  .bewerbung h2{margin-bottom:var(--r3);}
  .karte-formular{
    background:var(--flaeche); border:1px solid var(--linie);
    border-radius:var(--rund); padding:var(--r5); margin-top:var(--r5);
    box-shadow:var(--schatten);
  }
  .felder{display:grid; gap:var(--r4); grid-template-columns:1fr;
          margin-bottom:var(--r5);}
  @media (min-width: 40rem){
    .felder{grid-template-columns:1fr 1fr;}
    .felder .voll{grid-column:1 / -1;}
  }
  label{display:block; font-weight:600; font-size:.92rem;}
  .meta{display:block; font-weight:400; color:var(--gedaempft);
        font-size:.83rem; margin:.1rem 0 .35rem;}
  input,textarea,select{
    width:100%; font:inherit; padding:.7rem .8rem; border-radius:var(--rund-klein);
    border:1px solid var(--linie-stark); background:var(--flaeche);
    color:var(--text); margin-top:.3rem;
  }
  input:focus,textarea:focus,select:focus{
    outline:2px solid var(--amber); outline-offset:1px; border-color:var(--amber);
  }
  textarea{min-height:6rem; resize:vertical; line-height:1.6;}
  select{min-height:2.9rem;}
  .formular-fuss{display:flex; flex-wrap:wrap; align-items:center;
                 gap:var(--r4);}
  .formular-fuss .meta{flex:1 1 15rem; margin:0;}
  /* Der Honigtopf. Nicht display:none - manche Skripte ueberspringen das. */
  .lesehilfe{
    position:absolute; width:1px; height:1px; overflow:hidden;
    clip:rect(0 0 0 0); white-space:nowrap;
  }
  .danke{
    border-left:4px solid var(--amber); background:var(--flaeche-2);
    padding:var(--r4) var(--r5); border-radius:var(--rund-klein);
    margin-top:var(--r4);
  }
  .danke strong{display:block; font-family:var(--schrift-titel);
                color:var(--navy); margin-bottom:.2rem;}

  /* --- Meldung an den CTO --------------------------------------------------- */
  .melden{margin-top:var(--r6);}
  .melden summary{
    cursor:pointer; font-weight:600; color:var(--navy); list-style:none;
    display:flex; align-items:center; gap:.5rem; min-height:2.5rem;
  }
  .melden summary::-webkit-details-marker{display:none;}
  .melden summary::before{content:"+"; font-weight:700; color:var(--amber);
                          font-size:1.1rem;}
  .melden[open] summary::before{content:"\\2013";}
  .antwort{
    border-left:4px solid var(--amber); background:var(--flaeche-2);
    padding:var(--r3) var(--r4); border-radius:var(--rund-klein);
    margin-top:var(--r4); font-size:.92rem;
  }

  /* --- Fuss ----------------------------------------------------------------- */
  .seitenfuss{
    background:var(--navy-tief); color:#C8D6E8; margin-top:var(--r7);
    padding:var(--r6) 0 calc(var(--r6) + env(safe-area-inset-bottom,0px));
    font-size:.85rem;
  }
  .seitenfuss a{color:#98B3D1;}
  .seitenfuss code{font-size:.75rem; opacity:.6;}
  .seitenfuss p{margin:0 0 var(--r2);}
  .seitenfuss p:last-child{margin-bottom:0;}

  @media (max-width:860px){
    .aufmacher{grid-template-columns:1fr; padding-top:var(--r5);}
    .wappen-feld{order:-1;}
    .wappen-feld img{max-width:160px;}
    .raster-2{grid-template-columns:1fr;}
  }
  @media (max-width:720px){
    .halbjahr{padding-left:var(--r5);}
    .nummer{position:static; display:block; margin-bottom:.2rem;
            font-size:1.6rem;}
  }
  [hidden]{display:none !important;}
</style>
</head>
<body>
<div class="band">
  <div class="huelle">
    <div class="band-text">
      <h1>Die Plattform ist gerade nicht erreichbar.</h1>
      <p>Das liegt nicht an dir und nicht an deinem Ger&auml;t. Sie l&auml;uft
        auf einem Rechner in der Schule &ndash; ist der aus oder gerade neu
        gestartet, antwortet f&uuml;r ein paar Minuten niemand. Deine Daten
        sind davon nicht betroffen.</p>
      <p class="band-uhr">
        <span class="punkt" aria-hidden="true"></span>
        <span id="warten-text" aria-live="polite">Wir pr&uuml;fen alle 15
          Sekunden im Hintergrund nach. Neu geladen wird die Seite erst,
          wenn du es sagst &ndash; sonst w&auml;re ein halb ausgef&uuml;lltes
          Formular weg.</span>
      </p>
    </div>
    <div class="knopfzeile">
      <button type="button" class="btn-hell" id="wieder-da" hidden>Seite
        jetzt neu laden</button>
      <button type="button" class="btn-hell" id="nochmal">Nochmal
        versuchen</button>
      <button type="button" class="btn-rand" id="melden-auf" %%MELDEN%%>
        Dem CTO melden</button>
    </div>
  </div>
</div>

%%LANDING%%

<footer class="seitenfuss">
  <div class="huelle">
    <p><strong>Wirtschafts- &amp; Investment-AG</strong> am
      Max-von-Laue-Gymnasium Koblenz &middot;
      <a href="mailto:cto@tech.mvlg-wag.de">cto@tech.mvlg-wag.de</a></p>
    <p>Diese Notfassung liefert Cloudflare aus, weil die Plattform gerade
      nicht antwortet. Sobald sie wieder l&auml;uft, siehst du hier die
      vollst&auml;ndige Seite.</p>
    <p><code>%%GRUND%% &middot; %%WOHER%% &middot; Auffangnetz
      %%FASSUNG%%</code></p>
  </div>
</footer>
<script>
(function () {
  "use strict";
  var nochmal = document.getElementById("nochmal");
  var wartenText = document.getElementById("warten-text");
  var formular = document.getElementById("formular");
  var antwort = document.getElementById("antwort");
  var absenden = document.getElementById("absenden");
  var meldenAuf = document.getElementById("melden-auf");
  var melden = document.getElementById("melden");
  var wiederDa = document.getElementById("wieder-da");

  function sagen(text) {
    antwort.textContent = text;
    antwort.hidden = false;
  }

  if (meldenAuf && melden) {
    meldenAuf.addEventListener("click", function () {
      melden.open = true;
      melden.scrollIntoView({ behavior: "smooth", block: "nearest" });
      var feld = document.getElementById("f-text");
      if (feld) { feld.focus(); }
    });
  }

  /* Von selbst weiterprobieren, aber mit wachsendem Abstand. Ein Gerät, das
     mit offener Seite über Nacht liegen bleibt, soll nicht bis zum Morgen
     alle fünfzehn Sekunden anfragen. */
  var abstaende = [15, 15, 30, 30, 60, 120, 300];
  var stelle = 0;
  var restlich = abstaende[0];
  var uhr = null;

  function weiter() {
    stelle = Math.min(stelle + 1, abstaende.length - 1);
    restlich = abstaende[stelle];
    wartenText.textContent = "Noch nicht. Nächster Versuch in " + restlich
      + " Sekunden.";
  }

  function pruefen(danach) {
    fetch("/__ausfall/lebt", { cache: "no-store" })
      .then(function (a) { return a.text(); })
      .then(function (t) { danach(t.trim() === "ja"); })
      .catch(function () { danach(false); });
  }

  /* Wieder da - und trotzdem NICHT von selbst neu laden. Auf dieser Seite
     steht das Bewerbungsformular; ein Reload mitten im Tippen wirft alles
     weg, was jemand schon geschrieben hat, und er fängt kein zweites Mal
     an. Das Neuladen ist deshalb ein Knopf: Wer nichts ausgefüllt hat,
     drückt ihn sofort, wer mittendrin ist, schickt erst ab. Abschicken
     geht auch jetzt noch - /__ausfall/bewerben nimmt der Worker entgegen,
     nicht der Server. Fokus wird bewusst nicht gesetzt: Wer gerade tippt,
     soll nicht plötzlich in einen Knopf schreiben. */
  function daIst() {
    if (uhr) { window.clearInterval(uhr); uhr = null; }
    wartenText.textContent = "Die Plattform ist wieder da. Schick zu Ende, "
      + "was du angefangen hast - danach kannst du die Seite neu laden.";
    nochmal.hidden = true;
    if (wiederDa) { wiederDa.hidden = false; }
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
      weiter();
    });
  }

  uhr = window.setInterval(ticken, 1000);

  if (wiederDa) {
    wiederDa.addEventListener("click", function () {
      window.location.reload();
    });
  }

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

  if (formular) {
    formular.addEventListener("submit", function (e) {
      e.preventDefault();
      var text = document.getElementById("f-text").value.trim();
      if (text.length < 3) {
        sagen("Schreib bitte kurz, was du gemacht hast - sonst weiß er "
            + "nicht, wo er suchen soll.");
        return;
      }
      absenden.disabled = true;
      sagen("Wird abgeschickt …");
      fetch("/__ausfall/melden", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          text: text,
          name: document.getElementById("f-name").value,
          kontakt: document.getElementById("f-kontakt").value,
          lage: window.location.pathname + window.location.search,
          grund: "Fehlerseite"
        })
      })
        .then(function (a) {
          return a.json().then(function (d) {
            return { code: a.status, d: d };
          });
        })
        .then(function (x) {
          if (x.d && x.d.ok) {
            formular.hidden = true;
            /* Nur behaupten, was wirklich passiert ist. Vorher stand hier
               immer "bekommt sofort eine Meldung aufs Telefon" - auch dann,
               wenn gar kein ntfy-Thema hinterlegt war. Eine Zusage, die man
               nicht einhält, ist schlimmer als ein ehrliches "das ging
               nicht". */
            sagen(x.d.geklingelt
              ? "Angekommen. Der CTO hat eine Meldung aufs Telefon bekommen, "
                + "und sobald die Plattform wieder läuft, wird daraus ein "
                + "Support-Ticket. Du musst nichts weiter tun."
              : "Gespeichert. Sobald die Plattform wieder läuft, wird daraus "
                + "ein Support-Ticket für den CTO. Du musst nichts weiter "
                + "tun.");
            return;
          }
          absenden.disabled = false;
          sagen((x.d && x.d.grund) || "Das hat nicht geklappt. Bitte "
              + "später noch einmal versuchen.");
        })
        .catch(function () {
          absenden.disabled = false;
          sagen("Die Meldung ließ sich nicht abschicken - im Moment ist "
              + "gar keine Verbindung da. Bitte in ein paar Minuten noch "
              + "einmal.");
        });
    });
  }

  /* --- Bewerbung ---------------------------------------------------------
     Der wichtigste Teil dieser Seite. Sie darf unter keinen Umständen
     stillschweigend scheitern: Wer sich bewirbt und nichts hört, bewirbt
     sich kein zweites Mal. Deshalb bekommt jeder Fehlerfall einen Satz, der
     sagt, was jetzt zu tun ist - notfalls die Mailadresse. */
  var bForm = document.getElementById("bewerbung-formular");
  var bDanke = document.getElementById("b-danke");
  if (bForm) {
    var bAbsenden = document.getElementById("b-absenden");
    var wert = function (id) {
      var f = document.getElementById(id);
      return f ? f.value.trim() : "";
    };
    var bSagen = function (titel, text) {
      bDanke.innerHTML = "";
      var stark = document.createElement("strong");
      stark.textContent = titel;
      bDanke.appendChild(stark);
      bDanke.appendChild(document.createTextNode(text));
      bDanke.hidden = false;
      bDanke.scrollIntoView({ behavior: "smooth", block: "nearest" });
    };

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
        bSagen("Da fehlt noch etwas. ",
               "Bitte fülle alle Felder aus - nur „Vorwissen“ darf leer "
               + "bleiben.");
        return;
      }
      if (daten.motivation.length < 20) {
        bSagen("Ein bisschen mehr, bitte. ",
               "Schreib ein paar Sätze zu deiner Motivation - daran "
               + "entscheidet sich einiges.");
        return;
      }
      bAbsenden.disabled = true;
      bSagen("Wird abgeschickt … ", "");
      fetch("/__ausfall/bewerben", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(daten)
      })
        .then(function (a) {
          return a.json().then(function (d) { return d; });
        })
        .then(function (d) {
          if (d && d.ok) {
            bForm.hidden = true;
            bSagen("Danke, " + daten.vorname + ". ",
                   "Deine Bewerbung liegt sicher. Sie wird eingetragen, "
                   + "sobald die Plattform wieder läuft - meist innerhalb "
                   + "weniger Minuten. Danach bekommst du eine Bestätigung "
                   + "an " + daten.email + ".");
            return;
          }
          bAbsenden.disabled = false;
          bSagen("Das hat nicht geklappt. ",
                 (d && d.grund ? d.grund + " " : "")
                 + "Falls es dabei bleibt: schreib bitte an "
                 + "cto@tech.mvlg-wag.de, dann geht nichts verloren.");
        })
        .catch(function () {
          bAbsenden.disabled = false;
          bSagen("Die Bewerbung ließ sich nicht abschicken. ",
                 "Im Moment ist gar keine Verbindung da. Bitte gleich noch "
                 + "einmal versuchen - oder an cto@tech.mvlg-wag.de "
                 + "schreiben, dann geht nichts verloren.");
        });
    });
  }
})();
</script>
</body>
</html>`;


/* ------------------------------------------------------------------------- */
/*  Eingebettete Sachen                                                      */
/* ------------------------------------------------------------------------- */
/* Die Schrift der Ueberschriften und das Wappen. Sie muessen mit in die
   Datei: Der Server, von dem sie sonst kaemen, ist genau der ausgefallene.
   Sie stehen ganz unten, weil 57 KB Base64 mitten im Text jeden Ueberblick
   zerstoeren. Erzeugt aus statisch/schrift/space-grotesk-700-latin.woff2
   und statisch/bilder/logo-klein.webp. */
const SCHRIFT_GROTESK = "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";
const WAPPEN = "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";

/* Einmal beim Start zusammengesetzt statt bei jeder Anfrage: Die beiden
   Zeichenketten sind zusammen 57 KB, und ein Auffangnetz soll im Ernstfall
   nicht auch noch rechnen. */
const LANDING_FERTIG = LANDING_HTML.replace("%%LOGO%%", WAPPEN);
const HTML_FERTIG = HTML.replace("%%GROTESK%%", SCHRIFT_GROTESK);
