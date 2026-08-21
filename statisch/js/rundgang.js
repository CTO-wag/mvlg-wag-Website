/* ===========================================================================
   Der geführte Rundgang.

   Die Schritte kommen als JSON vom Server - dort stehen das persönliche
   ntfy-Thema und die Kalenderadresse drin, die nicht ins Markup gehören.
   Alles, was hier erzeugt wird, hängt an <body> und wird beim Beenden
   restlos entfernt.

   Gegenüber V1 geändert:
     * Die Karte hat einen festen Kopf, einen rollenden Körper und eine
       feste Fußzeile. Der "Weiter"-Knopf kann dadurch nicht mehr unterhalb
       der Bildschirmkante landen - das war der Fehler auf dem Handy.
     * Auf schmalen Bildschirmen wird gar nicht mehr gerechnet, wo die Karte
       hinsoll: sie klebt unten. Das Loch wird trotzdem gesetzt, damit man
       sieht, worum es geht.
     * Der Inhalt wird über DOM-Bausteine erzeugt statt über innerHTML mit
       zusammengesetzten Zeichenketten.
   ========================================================================= */
(function () {
  'use strict';

  var schritte = [], stelle = 0, loch = null, karte = null, koerper = null;
  var SCHMAL = 640;

  /* Es gibt zwei Rundgaenge mit derselben Mechanik: die Einfuehrung fuer
     Neue und die Liste der Aenderungen nach dem Umzug fuer alle anderen.
     Nur Adresse und Beschriftung unterscheiden sich - deshalb ein
     Verzeichnis statt einer zweiten Kopie dieser Datei. */
  var ARTEN = {
    rundgang: {
      quelle: '/dashboard/rundgang',
      merken: '/dashboard/rundgang/gesehen',
      aufschrift: 'Rundgang durch das Dashboard',
      abbruch: 'Rundgang abbrechen',
      fehler: 'Der Rundgang lässt sich gerade nicht laden. '
        + 'Bitte die Seite neu laden und noch einmal versuchen.'
    },
    neuerungen: {
      quelle: '/dashboard/neuerungen',
      merken: '/dashboard/neuerungen/gesehen',
      aufschrift: 'Was sich nach dem Umzug geändert hat',
      abbruch: 'Später weitermachen',
      fehler: 'Die Neuerungen lassen sich gerade nicht laden. '
        + 'Bitte die Seite neu laden und noch einmal versuchen.'
    }
  };
  var art = ARTEN.rundgang;

  function schmal() { return window.innerWidth <= SCHMAL; }

  function ziel(schritt) {
    if (!schritt.ziel) { return null; }
    var kandidaten = schritt.ziel.split('|');
    for (var i = 0; i < kandidaten.length; i++) {
      var el = document.querySelector(kandidaten[i].trim());
      if (!el) { continue; }
      /* Nur wirklich sichtbare Elemente: auf dem Handy steht die Seitenleiste
         zwar im Dokument, ist aber nach links aus dem Bild geschoben. Am PC
         fehlt dafür der Menü-Knopf. */
      var r = el.getBoundingClientRect();
      if (r.width > 0 && r.right > 0 && r.left < window.innerWidth) { return el; }
    }
    return null;
  }

  function el(tag, klasse, text) {
    var k = document.createElement(tag);
    if (klasse) { k.className = klasse; }
    if (text != null) { k.textContent = text; }
    return k;
  }

  /* Der Text eines Schrittes kommt als Liste von Bausteinen vom Server:
     {art: 'absatz'|'liste'|'hinweis'|'kopieren'|'geraete', ...} */
  function baustein(teil) {
    if (teil.art === 'absatz') {
      var p = el('p');
      (teil.teile || [{t: teil.text}]).forEach(function (s) {
        p.appendChild(s.stark ? el('strong', null, s.t) : document.createTextNode(s.t));
      });
      return p;
    }
    if (teil.art === 'liste') {
      var liste = el(teil.nummeriert ? 'ol' : 'ul');
      (teil.punkte || []).forEach(function (punkt) {
        var li = el('li');
        if (typeof punkt === 'string') {
          li.textContent = punkt;
        } else {
          li.appendChild(el('strong', null, punkt.titel + ' '));
          li.appendChild(document.createTextNode(punkt.text || ''));
        }
        liste.appendChild(li);
      });
      return liste;
    }
    if (teil.art === 'hinweis') {
      var kasten = el('div', 'tour-hinweis');
      kasten.appendChild(el('p', null, teil.text || ''));
      if (teil.schritte && teil.schritte.length) {
        var auf = el('details');
        auf.appendChild(el('summary', null, teil.titel || 'So geht das'));
        var ol = el('ol');
        teil.schritte.forEach(function (s) { ol.appendChild(el('li', null, s)); });
        auf.appendChild(ol);
        kasten.appendChild(auf);
      }
      return kasten;
    }
    if (teil.art === 'kopieren') {
      var zeile = el('div', 'tour-kopieren');
      var feld = el('input');
      feld.type = 'text';
      feld.readOnly = true;
      feld.value = teil.wert || '';
      feld.id = 'tour-kopierfeld-' + Math.random().toString(36).slice(2, 8);
      var knopf = el('button', 'btn-zweit btn-klein', 'Kopieren');
      knopf.type = 'button';
      knopf.setAttribute('data-kopieren', '#' + feld.id);
      zeile.appendChild(feld);
      zeile.appendChild(knopf);
      return zeile;
    }
    if (teil.art === 'geraete') {
      var reihe = el('div', 'tour-geraete');
      (teil.namen || []).forEach(function (name, i) {
        var k = el('button', 'tour-geraet' + (i === 0 ? ' aktiv' : ''), name);
        k.type = 'button';
        k.addEventListener('click', function () {
          reihe.querySelectorAll('.tour-geraet').forEach(function (x) {
            x.classList.remove('aktiv');
          });
          k.classList.add('aktiv');
          var inhalte = karte.querySelectorAll('[data-geraet]');
          inhalte.forEach(function (x) {
            x.hidden = x.getAttribute('data-geraet') !== name;
          });
        });
        reihe.appendChild(k);
      });
      return reihe;
    }
    return el('p', null, teil.text || '');
  }

  /* Markierung und Blatt an die Stelle setzen, an der das Element GERADE ist.
     Beides liegt fest im Fenster (position:fixed), die Werte gelten also nur
     für den Augenblick. Wer scrollt, verschiebt das Element darunter weg -
     deshalb wird diese Funktion auch bei jedem Rollen und jeder Größen-
     änderung erneut aufgerufen, nicht nur beim Schrittwechsel. */
  function positionieren() {
    var schritt = schritte[stelle];
    if (!schritt || !loch || !karte) { return; }
    var e = ziel(schritt);
    var r = e ? e.getBoundingClientRect() : null;
    /* Ganz aus dem Bild gerollt: dann markiert das Loch nur noch Leere. */
    var sichtbar = r && r.bottom > 0 && r.top < window.innerHeight
                     && r.width > 0 && r.height > 0;

    if (sichtbar) {
      var luft = 8;
      loch.hidden = false;
      loch.style.top = (r.top - luft) + 'px';
      loch.style.left = (r.left - luft) + 'px';
      loch.style.width = (r.width + luft * 2) + 'px';
      loch.style.height = (r.height + luft * 2) + 'px';
    } else {
      loch.hidden = true;
    }

    /* Auf dem Handy klebt das Blatt unten - da ist nichts zu rechnen. */
    if (schmal() || !sichtbar) {
      karte.classList.toggle('mittig', !schmal() && !sichtbar);
      karte.style.top = ''; karte.style.left = ''; karte.style.transform = '';
      return;
    }
    karte.classList.remove('mittig');
    var hoehe = karte.offsetHeight || 260;
    var oben = (r.bottom + 16 + hoehe < window.innerHeight)
      ? r.bottom + 16
      : Math.max(12, r.top - hoehe - 16);
    karte.style.top = Math.max(12, Math.min(
      oben, window.innerHeight - hoehe - 12)) + 'px';
    karte.style.left = Math.max(12, Math.min(
      r.left, window.innerWidth - karte.offsetWidth - 12)) + 'px';
    karte.style.transform = '';
  }

  /* Beim Rollen nicht bei jedem einzelnen Ereignis rechnen - auf dem Handy
     kommen davon leicht hundert in der Sekunde. Der erste Aufruf zieht sofort
     nach (sonst hinkt die Markierung sichtbar hinterher), die weiteren
     hoechstens alle 16 Millisekunden.

     Bewusst mit Zeitstempel statt requestAnimationFrame: in einem Tab im
     Hintergrund laeuft rAF gar nicht, und dann bliebe die Markierung nach dem
     Zurueckwechseln an der falschen Stelle stehen. */
  var letzteRechnung = 0, nachzuegler = null;
  function positionAnfordern() {
    /* Mitwandern ohne Übergang - siehe .tour-loch.springt in rundgang.css. */
    if (loch) { loch.classList.add('springt'); }
    var jetzt = Date.now();
    if (jetzt - letzteRechnung >= 16) {
      letzteRechnung = jetzt;
      positionieren();
      return;
    }
    if (nachzuegler) { return; }
    nachzuegler = window.setTimeout(function () {
      nachzuegler = null;
      letzteRechnung = Date.now();
      positionieren();
    }, 16);
  }

  function zeichne() {
    var schritt = schritte[stelle];
    if (!schritt) { beenden(); return; }
    var element = ziel(schritt);

    if (element) { element.scrollIntoView({block: 'center', behavior: 'smooth'}); }

    /* Erst nach dem Rollen messen - vorher stimmt die Stelle nicht. Danach
       hält positionAnfordern() sie nach. Beim Schrittwechsel darf die
       Markierung weich hinüberwandern, also ohne "springt". */
    setTimeout(function () {
      positionieren();
      if (loch) { loch.classList.remove('springt'); }
    }, element ? 260 : 0);

    /* --- Inhalt aufbauen ------------------------------------------------- */
    karte.textContent = '';

    var kopf = el('div', 'tour-kopf');
    kopf.appendChild(el('p', 'tour-zaehler',
      'Schritt ' + (stelle + 1) + ' von ' + schritte.length));
    kopf.appendChild(el('h3', null, schritt.titel));
    karte.appendChild(kopf);

    koerper = el('div', 'tour-koerper');
    (schritt.teile || []).forEach(function (teil) {
      koerper.appendChild(baustein(teil));
    });
    karte.appendChild(koerper);

    var fuss = el('div', 'tour-fuss');
    var punkte = el('div', 'tour-punkte');
    schritte.forEach(function (_, i) {
      punkte.appendChild(el('span', 'tour-punkt' + (i === stelle ? ' aktiv' : '')));
    });
    fuss.appendChild(punkte);

    if (stelle > 0) {
      var zurueck = el('button', 'btn-zweit btn-klein', 'Zurück');
      zurueck.type = 'button';
      zurueck.addEventListener('click', vorher);
      fuss.appendChild(zurueck);
    }
    var weiter = el('button', 'tour-weiter',
      stelle === schritte.length - 1 ? 'Fertig' : 'Weiter');
    weiter.type = 'button';
    weiter.addEventListener('click', naechster);
    fuss.appendChild(weiter);

    if (stelle !== schritte.length - 1) {
      var ab = el('button', 'tour-abbrechen', art.abbruch);
      ab.type = 'button';
      ab.addEventListener('click', beenden);
      fuss.appendChild(ab);
    }
    karte.appendChild(fuss);

    /* Der Körper rollt für sich - beim Schrittwechsel wieder nach oben. */
    koerper.scrollTop = 0;
    weiter.focus({preventScroll: true});
  }

  function bereichOeffnen(schritt, fertig) {
    if (!schritt || !schritt.bereich) { fertig(); return; }
    var punkt = document.querySelector(
      '.leisten-punkt[data-bereich="' + schritt.bereich + '"]');
    if (!punkt || punkt.classList.contains('aktiv')) { fertig(); return; }
    var inhalt = document.getElementById('tab-inhalt');
    var erledigt = false;
    var ab = function () { if (!erledigt) { erledigt = true; fertig(); } };
    if (inhalt) { inhalt.addEventListener('htmx:afterSettle', ab, {once: true}); }
    punkt.click();
    /* Falls htmx aus irgendeinem Grund nicht meldet, geht es trotzdem weiter. */
    setTimeout(ab, 1400);
  }

  function naechster() {
    if (stelle >= schritte.length - 1) {
      merken(true);
      beenden();
      return;
    }
    stelle++;
    bereichOeffnen(schritte[stelle], zeichne);
  }

  function vorher() {
    if (stelle === 0) { return; }
    stelle--;
    bereichOeffnen(schritte[stelle], zeichne);
  }

  function taste(e) {
    if (e.key === 'Escape') { beenden(); }
    else if (e.key === 'ArrowRight') { naechster(); }
    else if (e.key === 'ArrowLeft') { vorher(); }
  }

  function beenden() {
    if (loch) { loch.remove(); loch = null; }
    if (karte) { karte.remove(); karte = null; }
    document.removeEventListener('keydown', taste);
    window.removeEventListener('resize', positionAnfordern);
    window.removeEventListener('scroll', positionAnfordern, true);
    if (nachzuegler) { window.clearTimeout(nachzuegler); nachzuegler = null; }
    document.body.style.overflow = '';
  }

  function merken(erledigt) {
    var feld = document.getElementById('dash-csrf');
    fetch(art.merken, {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'csrf=' + encodeURIComponent(feld ? feld.value : '')
            + '&erledigt=' + (erledigt ? '1' : '')
    }).catch(function () { });
  }

  /* Holt die Schritte und startet. Bewusst per fetch statt über htmx:
     Ein nachgeladenes <script> läuft unter der Nonce-Richtlinie nicht (htmx
     baut es neu auf, und die Nonce liest sich dabei leer aus) - genau daran
     scheiterte der Rundgang vorher. */
  function starten(welche) {
    art = ARTEN[welche] || ARTEN.rundgang;
    fetch(art.quelle, {headers: {'Accept': 'application/json'}})
      .then(function (a) {
        if (!a.ok) { throw new Error('Status ' + a.status); }
        return a.json();
      })
      .then(function (daten) {
        if (!Array.isArray(daten) || !daten.length) { return; }
        schritte = daten;
        aufbauen();
      })
      .catch(function (e) {
        window.alert(art.fehler);
        if (window.console) { console.warn('Rundgang:', e); }
      });
  }

  function aufbauen() {
    beenden();
    stelle = 0;
    loch = el('div', 'tour-loch');
    karte = el('div', 'tour-karte');
    karte.setAttribute('role', 'dialog');
    karte.setAttribute('aria-modal', 'true');
    karte.setAttribute('aria-label', art.aufschrift);
    document.body.appendChild(loch);
    document.body.appendChild(karte);
    document.addEventListener('keydown', taste);
    window.addEventListener('resize', positionAnfordern);
    /* true = auch das Rollen innerhalb eines Kastens melden. Ohne das bleibt
       die Markierung stehen, sobald man in einer langen Liste scrollt. */
    window.addEventListener('scroll', positionAnfordern, true);
    bereichOeffnen(schritte[0], zeichne);
  }

  /* --- Einladung --------------------------------------------------------- */
  function einladungWeg() {
    var k = document.getElementById('tour-einladung');
    if (k) { k.remove(); }
    document.body.style.overflow = '';
  }

  /* Ein Klickhorcher fuer beide Arten. 'merken(true)' beim Start ist
     Absicht: Wer ihn einmal geoeffnet hat, soll nicht beim naechsten
     Anmelden erneut gefragt werden - auch dann nicht, wenn er ihn
     mittendrin abbricht. */
  var KNOEPFE = [
    ['rundgang', 'rundgang-start', 'rundgang-spaeter', 'rundgang-nie'],
    ['neuerungen', 'neuerungen-start', 'neuerungen-spaeter', 'neuerungen-nie']
  ];

  document.addEventListener('click', function (e) {
    for (var i = 0; i < KNOEPFE.length; i++) {
      var welche = KNOEPFE[i][0];
      if (e.target.closest('[data-' + KNOEPFE[i][1] + ']')) {
        e.preventDefault();
        art = ARTEN[welche];
        einladungWeg();
        merken(true);
        starten(welche);
        return;
      }
      if (e.target.closest('[data-' + KNOEPFE[i][2] + ']')) {
        einladungWeg();
        return;
      }
      if (e.target.closest('[data-' + KNOEPFE[i][3] + ']')) {
        art = ARTEN[welche];
        merken(true);
        einladungWeg();
        return;
      }
    }
  });

  /* Das Skript wird per htmx nachgeladen und ruft sich dann selbst auf. */
  window.rundgangStarten = function () { starten('rundgang'); };
  window.neuerungenStarten = function () { starten('neuerungen'); };

  /* Steht die Einladung schon da, Hintergrund sperren und Fokus hineinsetzen -
     sonst tippt man beim Weiterklicken ins Nichts. */
  var einladung = document.getElementById('tour-einladung');
  if (einladung) {
    document.body.style.overflow = 'hidden';
    var ersterKnopf = einladung.querySelector('button');
    if (ersterKnopf) { ersterKnopf.focus(); }
  }
})();
