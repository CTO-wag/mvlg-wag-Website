/* ===========================================================================
   Was der Browser über sich selbst weiß - für den Support.

   Der Server sieht bei jedem Aufruf nur die Kopfzeilen. Die sagen, welcher
   Browser das ist, aber nicht, wie schnell die Leitung ist, wie groß der
   Bildschirm, ob die Seite als App läuft oder ob Push überhaupt erlaubt
   wurde. Genau das sind aber die Fragen, an denen eine Support-Anfrage
   hängenbleibt ("bei mir ist alles winzig", "ich bekomme keine Meldungen",
   "es lädt ewig").

   Deshalb schickt diese Datei die Angaben einmal je Browsersitzung an
   /diagnose/melden - und meldet außerdem JavaScript-Fehler sofort, denn ein
   Fehler auf einem fremden Handy hinterlässt auf dem Server sonst keine
   einzige Spur.

   Absichtlich NICHT erhoben: Standort, Verlauf, Eingaben, Canvas- oder
   Schrift-Fingerabdruck. Das wäre möglich und beantwortet keine Frage,
   die der Support stellt.

   Ohne Bibliothek, ohne Modulsystem, ohne inline-Code - wie basis.js. Alles
   ist in try/catch gekapselt: Ein Browser, der eine Angabe nicht kennt,
   darf daran nicht scheitern. Diese Datei ist Beiwerk und darf niemals der
   Grund sein, warum eine Seite nicht funktioniert.
   ========================================================================= */
(function () {
  'use strict';

  var ZIEL = '/diagnose/melden';
  var MERKER = 'wag_diagnose_gesendet';
  var fehler_gesendet = 0;              /* Bremse gegen Fehlerschleifen */
  var FEHLER_HOECHSTENS = 5;

  /* --- Senden ------------------------------------------------------------
     keepalive, damit die Meldung auch dann noch rausgeht, wenn die Person
     im selben Moment weiterklickt. sendBeacon als Rückfallebene für ältere
     Browser - genau die, deren Angaben am interessantesten sind. */
  function senden(daten) {
    var text;
    try { text = JSON.stringify(daten); } catch (e) { return; }
    try {
      if (window.fetch) {
        fetch(ZIEL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: text,
          credentials: 'same-origin',
          keepalive: true
        }).catch(function () { /* Diagnose scheitert still */ });
        return;
      }
      if (navigator.sendBeacon) {
        navigator.sendBeacon(ZIEL, new Blob([text], { type: 'application/json' }));
      }
    } catch (e) { /* nicht schlimm */ }
  }

  /* --- Kleine Helfer ----------------------------------------------------- */
  function versuch(fn, ersatz) {
    try {
      var wert = fn();
      return (wert === undefined || wert === null) ? ersatz : wert;
    } catch (e) { return ersatz; }
  }

  function medienfrage(frage) {
    return versuch(function () {
      return window.matchMedia && window.matchMedia(frage).matches;
    }, false);
  }

  /* Der Name der Grafikeinheit. Bei Handys steht dort das genaueste, was
     überhaupt zu bekommen ist - "Apple A17 Pro GPU" oder "Mali-G715", und
     damit indirekt das Modell. Der Kontext wird sofort wieder freigegeben;
     ein offener WebGL-Kontext kostet Speicher. */
  function grafikeinheit() {
    return versuch(function () {
      var leinwand = document.createElement('canvas');
      var gl = leinwand.getContext('webgl') || leinwand.getContext('experimental-webgl');
      if (!gl) { return ''; }
      var info = gl.getExtension('WEBGL_debug_renderer_info');
      var name = info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : '';
      var verlust = gl.getExtension('WEBGL_lose_context');
      if (verlust) { verlust.loseContext(); }
      return String(name || '').slice(0, 200);
    }, '');
  }

  function ablageGeht() {
    return versuch(function () {
      localStorage.setItem('wag_test', '1');
      localStorage.removeItem('wag_test');
      return true;
    }, false);
  }

  /* --- Alles einsammeln --------------------------------------------------
     Was sofort dasteht. Die drei Angaben, die ein Versprechen zurückgeben
     (Akku, Speicherplatz, Hintergrundskript), kommen danach dazu. */
  function sofortiges() {
    var n = navigator || {};
    var d = {};

    d.bildschirm = versuch(function () {
      return screen.width + ' × ' + screen.height;
    }, '');
    d.fenster = versuch(function () {
      return window.innerWidth + ' × ' + window.innerHeight;
    }, '');
    d.pixelverhaeltnis = versuch(function () {
      return Math.round((window.devicePixelRatio || 1) * 100) / 100;
    }, 1);
    d.gpu = grafikeinheit();
    d.cpu_kerne = versuch(function () { return n.hardwareConcurrency; }, null);
    d.speicher_gb = versuch(function () { return n.deviceMemory; }, null);
    d.touchpunkte = versuch(function () { return n.maxTouchPoints; }, null);

    var verbindung = versuch(function () {
      return n.connection || n.mozConnection || n.webkitConnection;
    }, null);
    if (verbindung) {
      d.netz_art = versuch(function () { return verbindung.effectiveType; }, '');
      d.netz_tempo = versuch(function () { return verbindung.downlink; }, null);
      d.netz_rtt = versuch(function () { return verbindung.rtt; }, null);
      d.datensparmodus = versuch(function () { return !!verbindung.saveData; }, false);
    }
    d.online = versuch(function () { return n.onLine !== false; }, true);

    d.zeitzone = versuch(function () {
      return Intl.DateTimeFormat().resolvedOptions().timeZone;
    }, '');
    d.sprachen = versuch(function () {
      return (n.languages || [n.language]).join(', ');
    }, '');
    d.farbschema = medienfrage('(prefers-color-scheme: dark)') ? 'dunkel' : 'hell';
    d.kontrast = medienfrage('(prefers-contrast: more)');
    d.weniger_bewegung = medienfrage('(prefers-reduced-motion: reduce)');
    /* Der einzige verlässliche Weg zu der Frage, die bei Push-Problemen als
       erste zu klären ist: Browser-Tab oder Startbildschirm? */
    d.als_app = medienfrage('(display-mode: standalone)')
      || medienfrage('(display-mode: minimal-ui)')
      || versuch(function () { return n.standalone === true; }, false);
    d.zeiger = medienfrage('(pointer: coarse)') ? 'Finger' : 'Maus';

    d.push_erlaubnis = versuch(function () {
      return window.Notification ? Notification.permission : 'nicht unterstützt';
    }, '');
    d.cookies = versuch(function () { return !!n.cookieEnabled; }, false);
    d.ablage = ablageGeht();
    d.automatisiert = versuch(function () { return !!n.webdriver; }, false);

    /* Ladezeiten. Die neue Schnittstelle zuerst, weil die alte
       (performance.timing) in neuen Browsern nur noch aus Rücksicht auf
       alten Code existiert. */
    versuch(function () {
      var eintrag = performance.getEntriesByType('navigation')[0];
      if (eintrag) {
        d.ladezeit = Math.round(eintrag.duration);
        d.serverzeit = Math.round(eintrag.responseStart - eintrag.requestStart);
      } else if (performance.timing) {
        var t = performance.timing;
        if (t.loadEventEnd > 0) {
          d.ladezeit = t.loadEventEnd - t.navigationStart;
          d.serverzeit = t.responseStart - t.requestStart;
        }
      }
      var malerei = performance.getEntriesByName('first-contentful-paint')[0];
      if (malerei) { d.darstellzeit = Math.round(malerei.startTime); }
      return true;
    }, false);

    /* Leere Werte gar nicht erst mitschicken - der Server wirft sie
       ohnehin weg, und die Meldung bleibt lesbar. */
    var sauber = {};
    for (var schluessel in d) {
      if (Object.prototype.hasOwnProperty.call(d, schluessel)) {
        var wert = d[schluessel];
        if (wert !== null && wert !== undefined && wert !== '') {
          sauber[schluessel] = wert;
        }
      }
    }
    return sauber;
  }

  /* Die Angaben, die auf sich warten lassen. Jedes Versprechen einzeln
     abgesichert: Safari kennt getBattery nicht, Firefox nicht deviceMemory,
     und ein abgelehntes Versprechen darf die anderen nicht mitreißen. */
  function nachzuegler(daten) {
    var offen = [];

    offen.push(versuch(function () {
      return navigator.getBattery().then(function (akku) {
        daten.akku = Math.round(akku.level * 100);
        daten.akku_laedt = !!akku.charging;
      });
    }, null));

    offen.push(versuch(function () {
      return navigator.storage.estimate().then(function (platz) {
        if (platz.usage) { daten.speicher_belegt = Math.round(platz.usage / 1048576); }
        if (platz.quota) { daten.speicher_frei = Math.round(platz.quota / 1048576); }
      });
    }, null));

    offen.push(versuch(function () {
      if (!navigator.serviceWorker) {
        daten.sw_status = 'nicht unterstützt';
        return null;
      }
      return navigator.serviceWorker.getRegistration().then(function (reg) {
        daten.sw_status = !reg ? 'nicht angemeldet'
          : (navigator.serviceWorker.controller ? 'aktiv' : 'angemeldet, inaktiv');
      });
    }, null));

    var echte = [];
    for (var i = 0; i < offen.length; i++) {
      if (offen[i] && typeof offen[i].then === 'function') {
        echte.push(offen[i].catch(function () { /* egal */ }));
      }
    }
    if (!echte.length || !window.Promise) { return Promise.resolve(daten); }
    return Promise.all(echte).then(function () { return daten; });
  }

  /* --- Einmal je Browsersitzung melden ------------------------------------
     Nicht bei jedem Seitenaufruf: Diese Angaben ändern sich innerhalb einer
     Sitzung praktisch nicht, und der Server würde für nichts schreiben.
     Fällt sessionStorage aus (Privatmodus), wird eben jedes Mal gemeldet -
     das ist die harmlosere Richtung. */
  function schonGemeldet() {
    return versuch(function () {
      return sessionStorage.getItem(MERKER) === '1';
    }, false);
  }

  function alsGemeldetMerken() {
    versuch(function () { return sessionStorage.setItem(MERKER, '1'); }, null);
  }

  function melden() {
    if (schonGemeldet()) { return; }
    alsGemeldetMerken();
    var daten = sofortiges();
    if (window.Promise) {
      nachzuegler(daten).then(senden, function () { senden(daten); });
    } else {
      senden(daten);
    }
  }

  /* --- Fehler melden ------------------------------------------------------
     Der eigentliche Gewinn: Was im Browser schiefgeht, wusste bisher nur
     der Browser. Mit Obergrenze, damit eine Schleife im Skript nicht die
     Datenbank vollschreibt - der Server bremst zwar auch, aber erst
     nachdem die Anfrage schon da war. */
  function fehlerMelden(art, meldung, quelle, zeile, stapel) {
    if (fehler_gesendet >= FEHLER_HOECHSTENS || !meldung) { return; }
    fehler_gesendet++;
    senden({
      art: art,
      meldung: String(meldung).slice(0, 500),
      quelle: String(quelle || '').slice(0, 300),
      zeile: typeof zeile === 'number' ? zeile : null,
      stapel: String(stapel || '').slice(0, 4000),
      adresse: String(location.pathname + location.search).slice(0, 300)
    });
  }

  window.addEventListener('error', function (e) {
    /* Zwei verschiedene Ereignisse tragen denselben Namen: ein echter
       JavaScript-Fehler (hat e.message) und eine Datei, die nicht geladen
       werden konnte (hat ein Ziel mit src). Das zweite ist bei einer PWA
       der häufigere Fall - ein veralteter Zwischenspeicher zeigt auf eine
       Datei, die es nicht mehr gibt. */
    if (e && e.message) {
      fehlerMelden('js', e.message, e.filename, e.lineno,
        e.error && e.error.stack);
    } else if (e && e.target && (e.target.src || e.target.href)) {
      fehlerMelden('netz', 'Datei konnte nicht geladen werden',
        e.target.src || e.target.href, null, '');
    }
  }, true);

  window.addEventListener('unhandledrejection', function (e) {
    var grund = e && e.reason;
    fehlerMelden('versprechen',
      (grund && (grund.message || grund)) || 'Unbehandelte Ablehnung',
      '', null, grund && grund.stack);
  });

  /* Erst nach dem Laden, sonst stehen die Ladezeiten noch nicht fest. Das
     kurze Warten danach ist für die Zeitmessung selbst: loadEventEnd wird
     erst gesetzt, wenn das load-Ereignis durch ist. */
  function starten() {
    setTimeout(melden, 1200);
  }

  if (document.readyState === 'complete') {
    starten();
  } else {
    window.addEventListener('load', starten);
  }
})();
