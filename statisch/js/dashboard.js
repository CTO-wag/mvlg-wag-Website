/* ===========================================================================
   Dashboard-Steuerung: Seitenleiste, Suche, htmx-Kleinkram.
   ========================================================================= */
(function () {
  'use strict';

  /* --- Seitenleiste ------------------------------------------------------- */
  function schublade(auf) {
    var leiste = document.getElementById('dash-leiste');
    var schleier = document.getElementById('leisten-schleier');
    var schalter = document.getElementById('leisten-schalter');
    if (!leiste) { return; }
    var offen = auf === undefined ? !leiste.classList.contains('offen') : auf;
    leiste.classList.toggle('offen', offen);
    if (schleier) { schleier.hidden = !offen; }
    if (schalter) { schalter.setAttribute('aria-expanded', offen ? 'true' : 'false'); }
    document.body.style.overflow = offen ? 'hidden' : '';
  }

  /* Klebt die Leiste oben fest - aber nur, solange sie ganz ins Fenster passt.
     Sonst wäre ihr unteres Ende nicht erreichbar, und ein eigener Rollbalken
     im Menü hieße: zweimal rollen, um nach unten zu kommen. */
  function klebenPruefen() {
    var leiste = document.getElementById('dash-leiste');
    if (!leiste) { return; }
    if (window.innerWidth <= 900) { leiste.classList.remove('mitlaufend'); return; }
    leiste.classList.remove('mitlaufend');   // ohne Klasse messen
    var oben = parseFloat(getComputedStyle(leiste).top) || 0;
    if (leiste.scrollHeight > window.innerHeight - oben - 16) {
      leiste.classList.add('mitlaufend');
    }
  }

  /* --- Bereich wechseln --------------------------------------------------- */
  function bereichAktiv(punkt) {
    document.querySelectorAll('.leisten-punkt').forEach(function (p) {
      p.classList.toggle('aktiv', p === punkt);
    });
    var ich = document.getElementById('dash-ich');
    if (ich) { ich.classList.remove('aktiv'); }
    var titel = document.getElementById('leisten-titel');
    if (titel && punkt) {
      titel.textContent = punkt.querySelector('.leisten-text').textContent;
    }
    if (window.innerWidth <= 900) { schublade(false); }
    /* Der Bereich landet in der Adresszeile, damit ein Neuladen dort bleibt,
       wo man war - in V1 fing man nach jedem F5 wieder bei der Übersicht an. */
    if (punkt && punkt.dataset.bereich && window.history.replaceState) {
      window.history.replaceState(null, '', '#' + punkt.dataset.bereich);
    }
  }

  document.addEventListener('click', function (e) {
    if (e.target.closest('#leisten-schalter')) { schublade(); return; }
    if (e.target.closest('#leisten-schleier')) { schublade(false); return; }

    var punkt = e.target.closest('.leisten-punkt');
    if (punkt) { e.preventDefault(); bereichAktiv(punkt); return; }

    var ich = e.target.closest('#dash-ich');
    if (ich) {
      e.preventDefault();
      document.querySelectorAll('.leisten-punkt').forEach(function (p) {
        p.classList.remove('aktiv');
      });
      ich.classList.add('aktiv');
    }
  });

  window.addEventListener('resize', klebenPruefen);

  /* --- Globale Suche ------------------------------------------------------ */
  var suchZeit = null, suchStelle = -1;

  function trefferKasten() { return document.getElementById('such-treffer'); }

  function suchen(sofort) {
    var feld = document.getElementById('such-feld');
    var kasten = trefferKasten();
    if (!feld || !kasten) { return; }
    var text = feld.value.trim();
    if (text.length < 2) { kasten.classList.remove('offen'); kasten.innerHTML = ''; return; }

    clearTimeout(suchZeit);
    suchZeit = setTimeout(function () {
      kasten.innerHTML = '<div class="such-laedt">Suche …</div>';
      kasten.classList.add('offen');
      fetch('/dashboard/suche?q=' + encodeURIComponent(text), {
        headers: {'HX-Request': 'true'}
      })
        .then(function (a) { return a.text(); })
        .then(function (html) {
          kasten.innerHTML = html;
          kasten.classList.add('offen');
          suchStelle = -1;
        })
        .catch(function () {
          kasten.innerHTML = '<div class="such-leer">Die Suche antwortet gerade nicht.</div>';
        });
    }, sofort ? 0 : 220);
  }

  function suchTaste(e) {
    var kasten = trefferKasten();
    if (!kasten || !kasten.classList.contains('offen')) { return; }
    var treffer = Array.prototype.slice.call(kasten.querySelectorAll('.suche-eintrag'));
    if (e.key === 'Escape') { kasten.classList.remove('offen'); return; }
    if (!treffer.length) { return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      suchStelle += e.key === 'ArrowDown' ? 1 : -1;
      if (suchStelle < 0) { suchStelle = treffer.length - 1; }
      if (suchStelle >= treffer.length) { suchStelle = 0; }
      treffer.forEach(function (t, i) { t.classList.toggle('aktiv', i === suchStelle); });
      treffer[suchStelle].scrollIntoView({block: 'nearest'});
    } else if (e.key === 'Enter' && suchStelle >= 0) {
      e.preventDefault();
      treffer[suchStelle].click();
    }
  }

  document.addEventListener('input', function (e) {
    if (e.target.id === 'such-feld') { suchen(false); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.target.id === 'such-feld') { suchTaste(e); return; }
    /* Strg+K springt ins Suchfeld - der Griff, den jedes Werkzeug hat. */
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      var feld = document.getElementById('such-feld');
      if (feld) { e.preventDefault(); feld.focus(); feld.select(); }
    }
  });
  document.addEventListener('click', function (e) {
    var kasten = trefferKasten();
    if (!kasten) { return; }
    if (!e.target.closest('.suche-feld')) { kasten.classList.remove('offen'); }
    /* Ein Treffer öffnet den passenden Bereich und markiert das Ziel. */
    var eintrag = e.target.closest('.suche-eintrag[data-bereich]');
    if (eintrag) {
      kasten.classList.remove('offen');
      var punkt = document.querySelector(
        '.leisten-punkt[data-bereich="' + eintrag.dataset.bereich + '"]');
      if (punkt) { punkt.click(); }
    }
  });

  /* =========================================================================
     Verhalten der einzelnen Bereiche

     Alles hier liegt bewusst in dieser dauerhaft geladenen Datei und NICHT
     als <script> in den Bereichs-Vorlagen. Grund: Bereiche werden per htmx
     nachgeladen, und ein so eingefügtes Skript läuft unter der
     Nonce-Richtlinie nicht - htmx baut das Element neu auf, und die Nonce
     liest sich dabei leer aus. Genau daran waren vorher der Rundgang und
     mehrere Knöpfe stillschweigend gescheitert.

     Deshalb: Ereignisse am document abfangen. Das gilt auch für Inhalte, die
     es beim Laden der Seite noch gar nicht gab.
     ========================================================================= */

  /* --- Übersicht: Sprung in einen Bereich --------------------------------- */
  document.addEventListener('click', function (e) {
    var sprung = e.target.closest('[data-springe]');
    if (!sprung) { return; }
    var punkt = document.querySelector(
      '.leisten-punkt[data-bereich="' + sprung.dataset.springe + '"]');
    if (punkt) { punkt.click(); }
  });

  /* --- Kalender: nur das passende Zielfeld zeigen -------------------------- */
  function zielfelderAnpassen(wahl) {
    var formular = wahl.closest('form');
    if (!formular) { return; }
    formular.querySelectorAll('[data-zielfeld]').forEach(function (feld) {
      feld.hidden = feld.getAttribute('data-zielfeld') !== wahl.value;
    });
  }
  document.addEventListener('change', function (e) {
    if (e.target.hasAttribute && e.target.hasAttribute('data-zielwahl')) {
      zielfelderAnpassen(e.target);
    }
  });

  /* --- Rollen: Vorlagen setzen die Kästchen -------------------------------- */
  document.addEventListener('click', function (e) {
    var knopf = e.target.closest('[data-vorlage]');
    if (!knopf) { return; }
    var quelle = document.getElementById('rollen-vorlagen');
    if (!quelle) { return; }
    var vorlagen;
    try {
      vorlagen = JSON.parse(quelle.dataset.vorlagen);
    } catch (err) {
      /* Nicht stillschweigend aufgeben - sonst tut der Knopf einfach nichts
         und niemand erfährt, warum. */
      if (window.console) { console.warn('Rollen-Vorlagen unlesbar:', err); }
      return;
    }
    var werte = vorlagen[knopf.getAttribute('data-vorlage')] || {};
    var formular = knopf.closest('form');
    if (!formular) { return; }
    formular.querySelectorAll('input[name="rechte"]').forEach(function (k) {
      if (k.disabled || k.type === 'hidden') { return; }
      k.checked = !!werte[k.value];
    });
  });

  /* --- WhatsApp: Platzhalter an der Cursorposition einfügen ---------------- */
  document.addEventListener('click', function (e) {
    var knopf = e.target.closest('[data-einfuegen]');
    if (!knopf) { return; }
    var feld = document.getElementById('wa-vorlage');
    if (!feld) { return; }
    var text = knopf.getAttribute('data-einfuegen');
    var anfang = feld.selectionStart, ende = feld.selectionEnd;
    feld.value = feld.value.slice(0, anfang) + text + feld.value.slice(ende);
    feld.focus();
    feld.selectionStart = feld.selectionEnd = anfang + text.length;
  });

  /* --- Personenauswahl: alle / keine / filtern ------------------------------
     Gilt für jeden Auswahlkasten, nicht nur für den Nachrichtenversand: die
     Anwesenheit wird jede Woche für dieselben zwanzig Leute erfasst, und
     zwanzig Klicks für "waren alle da" sind zwanzig zu viel. */
  function auswahlkasten(el) {
    return el.closest('.empfaenger-kasten')
        || (document.getElementById('empfaenger-liste') || {}).parentElement;
  }

  function auswahlZaehlen(kasten) {
    if (!kasten) { return; }
    var anzeige = kasten.querySelector('[data-empfaenger-zahl]');
    if (!anzeige) { return; }
    var gewaehlt = kasten.querySelectorAll('input[type="checkbox"]:checked').length;
    anzeige.textContent = gewaehlt ? gewaehlt + ' ausgewählt' : '';
  }

  document.addEventListener('click', function (e) {
    var knopf = e.target.closest('[data-empfaenger]');
    if (!knopf) { return; }
    var kasten = auswahlkasten(knopf);
    var liste = kasten && (kasten.querySelector('.empfaenger-liste') || kasten);
    if (!liste) { return; }
    var an = knopf.getAttribute('data-empfaenger') === 'alle';
    liste.querySelectorAll('input[type="checkbox"]').forEach(function (k) {
      /* Ausgeblendete überspringen: Wer erst filtert und dann "Alle" drückt,
         meint die gefilterten - nicht heimlich auch alle anderen. */
      var haken = k.closest('.haken');
      if (!haken || !haken.hidden) { k.checked = an; }
    });
    auswahlZaehlen(kasten);
  });

  document.addEventListener('input', function (e) {
    if (e.target.id !== 'empfaenger-suche'
        && !e.target.classList.contains('empfaenger-suche')) { return; }
    var kasten = auswahlkasten(e.target);
    var liste = kasten && (kasten.querySelector('.empfaenger-liste') || kasten);
    if (!liste) { return; }
    var worte = suchBegriffe(e.target.value);
    liste.querySelectorAll('.haken').forEach(function (h) {
      var suchtext = suchNormalisieren(
        (h.dataset.name || '') + ' ' + (h.textContent || '') + ' ' +
        Array.prototype.map.call(h.querySelectorAll('input, select'),
          function (feld) { return feld.value || ''; }).join(' '));
      h.hidden = worte.length && !worte.every(function (wort) {
        return suchtext.indexOf(wort) !== -1;
      });
    });
  });

  document.addEventListener('change', function (e) {
    if (e.target.type === 'checkbox' && e.target.closest('.empfaenger-kasten')) {
      auswahlZaehlen(e.target.closest('.empfaenger-kasten'));
    }
  });

  /* --- "Leg eine an" aus dem leeren Bereich --------------------------------
     Sucht das Anlegen-Formular des Bereichs, klappt es auf und setzt den
     Schreibzeiger ins erste Feld. Ohne das steht in einem leeren Bereich zwar
     "Leg unten eine an", aber man muss selbst finden, wo. */
  document.addEventListener('click', function (e) {
    if (!e.target.closest('[data-anlegen]')) { return; }
    var inhalt = document.getElementById('tab-inhalt');
    if (!inhalt) { return; }
    var kasten = null;
    inhalt.querySelectorAll('details').forEach(function (d) {
      if (kasten) { return; }
      var titel = (d.querySelector('summary') || {}).textContent || '';
      if (/anlegen|hinzufügen|neue|neuer|neues|erfassen/i.test(titel)) { kasten = d; }
    });
    if (!kasten) { kasten = inhalt.querySelector('details.block, details'); }
    if (!kasten) { return; }
    kasten.open = true;
    kasten.scrollIntoView({block: 'center', behavior: 'smooth'});
    var feld = kasten.querySelector('input:not([type=hidden]), textarea, select');
    if (feld) { setTimeout(function () { feld.focus({preventScroll: true}); }, 300); }
  });

  /* --- Suchleisten über den Listen ----------------------------------------
     Gefiltert wird im Browser. Bei den Mengen, um die es hier geht - ein paar
     Dutzend Zeilen - ist ein Rundweg zum Server pro Tastendruck reine
     Verschwendung; so bleibt die Liste beim Tippen sofort dabei.

     Was durchsucht wird, steht im Element selbst: sein sichtbarer Text. Der
     enthält Titel, Namen, Abteilung und Datum, also genau das, wonach man
     sucht. Er wird einmal gemerkt, damit nicht bei jedem Tastendruck der
     halbe Baum ausgelesen wird.

     Die zuletzt eingegebenen Wörter überleben einen htmx-Austausch: sonst
     steht nach jedem Erledigt-Klick wieder die ganze Liste da, obwohl man
     gerade gefiltert hatte. */
  var suchWorte = {};

  function suchNormalisieren(wert) {
    return String(wert || '').toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .replace(/\s+/g, ' ').trim();
  }

  function suchBegriffe(wert) {
    var normal = suchNormalisieren(wert);
    var woerter = normal.split(/\s+/).filter(Boolean);
    var ziffern = normal.replace(/\D/g, '');
    if (ziffern.length >= 3) {
      woerter = woerter.filter(function (wort) { return !/\d/.test(wort); });
      woerter.push(ziffern);
      if (ziffern.indexOf('00') === 0) {
        woerter.push(ziffern.slice(2));
      } else if (ziffern.indexOf('0') === 0) {
        woerter.push('49' + ziffern.slice(1));
      } else if (ziffern.indexOf('49') === 0) {
        woerter.push('0' + ziffern.slice(2));
      }
    }
    return woerter;
  }

  function suchtext(el) {
    if (!el.dataset.suchtext) {
      var werte = Array.prototype.map.call(
        el.querySelectorAll('input, select, textarea'),
        function (feld) {
          if (feld.tagName === 'SELECT') {
            return Array.prototype.map.call(feld.selectedOptions || [], function (o) {
              return o.textContent || o.value;
            }).join(' ');
          }
          return feld.value || feld.getAttribute('aria-label') || '';
        }).join(' ');
      var grund = el.getAttribute('data-suchinhalt') || el.textContent || '';
      var ziffern = (grund + ' ' + werte).replace(/\D/g, '');
      var telefonVarianten = ziffern;
      if (ziffern.indexOf('00') === 0) {
        telefonVarianten += ' ' + ziffern.slice(2);
      } else if (ziffern.indexOf('0') === 0) {
        telefonVarianten += ' 49' + ziffern.slice(1);
      } else if (ziffern.indexOf('49') === 0) {
        telefonVarianten += ' 0' + ziffern.slice(2);
      }
      el.dataset.suchtext = suchNormalisieren(grund + ' ' + werte + ' '
        + (ziffern.length >= 3 ? telefonVarianten : ''));
    }
    return el.dataset.suchtext;
  }

  function listeFiltern(leiste) {
    var behaelter = document.querySelector(leiste.dataset.suche);
    var feld = leiste.querySelector('input');
    if (!behaelter || !feld) { return; }

    var worte = suchBegriffe(feld.value);
    suchWorte[leiste.dataset.suche] = feld.value;

    var treffer = 0, gesamt = 0;
    behaelter.querySelectorAll('[data-suchbar]').forEach(function (el) {
      gesamt++;
      var text = suchtext(el);
      var passt = worte.every(function (w) { return text.indexOf(w) !== -1; });
      el.hidden = !passt;
      if (passt) { treffer++; }
    });

    /* Überschriften ohne sichtbare Einträge verschwinden mit - sonst bleiben
       leere Kästen mit einer Zahl stehen, die nicht mehr stimmt. */
    behaelter.querySelectorAll('[data-such-gruppe]').forEach(function (g) {
      g.hidden = !g.querySelector('[data-suchbar]:not([hidden])');
    });

    var zahl = leiste.querySelector('.such-zahl');
    if (zahl) {
      zahl.textContent = worte.length
        ? treffer + ' von ' + gesamt + ' ' + (leiste.dataset.sucheWort || '')
        : '';
    }
    var leeren = leiste.querySelector('.such-leeren');
    if (leeren) { leeren.hidden = !worte.length; }

    var nichts = behaelter.querySelector('.such-nichts');
    if (worte.length && !treffer) {
      if (!nichts) {
        nichts = document.createElement('div');
        nichts.className = 'panel such-nichts';
        behaelter.appendChild(nichts);
      }
      nichts.textContent = 'Nichts gefunden für „' + feld.value + '“.';
      nichts.hidden = false;
    } else if (nichts) {
      nichts.hidden = true;
    }
  }

  document.addEventListener('input', function (e) {
    var leiste = e.target.closest('[data-suche]');
    if (leiste) { listeFiltern(leiste); }
  });

  document.addEventListener('click', function (e) {
    var leeren = e.target.closest('.such-leeren');
    if (!leeren) { return; }
    var leiste = leeren.closest('[data-suche]');
    var feld = leiste.querySelector('input');
    feld.value = '';
    listeFiltern(leiste);
    feld.focus();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') { return; }
    var leiste = e.target.closest && e.target.closest('[data-suche]');
    if (!leiste) { return; }
    leiste.querySelector('input').value = '';
    listeFiltern(leiste);
  });

  /* --- Nach jedem Bereichswechsel einmal aufräumen ------------------------- */
  function bereichEingerichtet() {
    document.querySelectorAll('[data-zielwahl]').forEach(zielfelderAnpassen);
    document.querySelectorAll('[data-suche]').forEach(function (leiste) {
      var alt = suchWorte[leiste.dataset.suche];
      if (alt) { leiste.querySelector('input').value = alt; }
      if (alt) { listeFiltern(leiste); }
    });
  }

  /* --- Eingaben überleben einen Fehler -------------------------------------
     Der Server schickt bei einem Fehler den ganzen Bereich neu - und damit
     ein leeres Formular. Wer zehn Zeilen getippt und das Datum vergessen
     hat, fängt von vorn an. Das ist der sicherste Weg, Leute zu vergraulen.

     Deshalb: Vor dem Abschicken merken, was im Formular stand. Kommt eine
     Antwort MIT Fehlermeldung zurück, wird es wieder eingesetzt. Kommt sie
     ohne, hat es geklappt und das Gemerkte wird verworfen - ein leeres
     Formular ist dann richtig. */
  var gemerkteEingaben = null;

  function formularLesen(formular) {
    var werte = [];
    formular.querySelectorAll('input, select, textarea').forEach(function (feld) {
      if (!feld.name || feld.name === 'csrf' || feld.type === 'hidden'
          || feld.type === 'file' || feld.type === 'password') { return; }
      if (feld.type === 'checkbox' || feld.type === 'radio') {
        werte.push({name: feld.name, wert: feld.value, an: feld.checked, haken: true});
      } else {
        werte.push({name: feld.name, wert: feld.value, haken: false});
      }
    });
    return werte;
  }

  function etwasEingetippt(werte) {
    return werte.some(function (f) {
      return f.haken ? f.an : String(f.wert || '').trim().length > 0;
    });
  }

  function formularFuellen(formular, werte) {
    werte.forEach(function (f) {
      var felder = formular.querySelectorAll('[name="' + f.name + '"]');
      felder.forEach(function (feld) {
        if (f.haken) {
          if (feld.value === f.wert) { feld.checked = f.an; }
          return;
        }
        if (feld.tagName === 'SELECT') {
          /* Ein Auswahlfeld ist nie "leer" - es steht auf der Vorgabe. Die
             getroffene Wahl muss also aktiv zurückgesetzt werden, sonst
             springt die Priorität beim zweiten Versuch wieder auf "mittel".
             Nur, wenn es den Eintrag noch gibt: eine inzwischen gelöschte
             Person darf nicht als leere Auswahl zurückbleiben. */
          var gibtes = [].some.call(feld.options, function (o) {
            return o.value === f.wert;
          });
          if (gibtes) { feld.value = f.wert; }
          return;
        }
        if (!feld.value) { feld.value = f.wert; }
      });
    });
  }

  document.body.addEventListener('htmx:beforeRequest', function (e) {
    var formular = e.detail.elt && e.detail.elt.closest
      ? (e.detail.elt.tagName === 'FORM' ? e.detail.elt : e.detail.elt.closest('form'))
      : null;
    if (!formular) { return; }
    var werte = formularLesen(formular);
    var ziel = formular.getAttribute('hx-post')
      || (e.detail.pathInfo && e.detail.pathInfo.requestPath);
    gemerkteEingaben = etwasEingetippt(werte) ? {ziel: ziel, werte: werte} : null;
  });

  function eingabenZurueckholen(bereich) {
    if (!gemerkteEingaben) { return; }
    var hat_fehler = bereich.querySelector('.meldung-fehler');
    if (!hat_fehler) { gemerkteEingaben = null; return; }

    var formular = bereich.querySelector('[hx-post="' + gemerkteEingaben.ziel + '"]');
    if (formular && formular.tagName !== 'FORM') { formular = formular.closest('form'); }
    if (formular) {
      formularFuellen(formular, gemerkteEingaben.werte);
      /* Aufgeklappte Kästen wieder öffnen - sonst ist das Formular zwar
         gefüllt, aber unsichtbar. */
      var kasten = formular.closest('details');
      while (kasten) { kasten.open = true; kasten = kasten.parentElement.closest('details'); }
      var erstes = formular.querySelector('input:not([type=hidden]), textarea, select');
      if (erstes) { erstes.focus({preventScroll: true}); }
      hat_fehler.scrollIntoView({block: 'center', behavior: 'smooth'});
    }
    gemerkteEingaben = null;
  }

  /* --- Nicht versehentlich wegklicken --------------------------------------
     Wer einen halben Absatz getippt hat und dann links auf einen anderen
     Bereich tippt, verliert ihn ersatzlos. Einmal nachfragen ist hier
     angemessen - beim Speichern selbst wird nicht gefragt. */
  function ungespeicherteEingabe() {
    var inhalt = document.getElementById('tab-inhalt');
    if (!inhalt) { return false; }
    var laenge = 0;
    inhalt.querySelectorAll('form input[type=text], form input[type=email], '
                            + 'form input[type=tel], form input[type=number], '
                            + 'form textarea').forEach(function (feld) {
      if (feld.readOnly || feld.disabled) { return; }
      /* Vorbelegte Werte zählen nicht - nur, was jemand selbst getippt hat. */
      if (feld.value && feld.value !== feld.defaultValue) {
        laenge += feld.value.trim().length;
      }
    });
    return laenge >= 25;
  }

  document.body.addEventListener('htmx:confirm', function (e) {
    var punkt = e.detail.elt && e.detail.elt.closest
      ? e.detail.elt.closest('.leisten-punkt, #dash-ich') : null;
    if (!punkt || !ungespeicherteEingabe()) { return; }
    e.preventDefault();
    if (window.confirm('Du hast etwas eingetippt, das noch nicht gespeichert '
        + 'ist. Beim Wechseln geht es verloren.\n\nTrotzdem wechseln?')) {
      e.detail.issueRequest(true);
    }
  });

  /* --- Rueckmeldungen dorthin, wo man gerade steht ------------------------
     Vorher stand die Antwort des Servers immer ganz oben im Bereich. Wer
     unten in einem Formular etwas abschickte, sah sie nicht - und wurde
     obendrein nach oben geworfen. Beides zusammen war die haeufigste
     Beschwerde.

     Jetzt wird die Meldung aus dem Bereich herausgenommen und in einen
     festen Kasten am unteren Rand gehaengt. Die Seite bewegt sich nicht,
     und die Antwort steht dort, wo der Blick ohnehin ist.

     Erfolg verschwindet von selbst, Fehler und Warnungen bleiben stehen -
     die will man lesen und meistens auch etwas tun. Angetippt geht jede
     weg. */
  var standVorDemAbschicken = null;

  function meldungsplatz() {
    var platz = document.getElementById('meldungsplatz');
    if (!platz) {
      platz = document.createElement('div');
      platz.id = 'meldungsplatz';
      platz.setAttribute('aria-live', 'polite');
      document.body.appendChild(platz);
    }
    return platz;
  }

  function meldungHolen(bereich) {
    var platz = meldungsplatz();
    while (platz.firstChild) { platz.removeChild(platz.firstChild); }
    var meldung = bereich.querySelector('.meldung[data-rueckmeldung]');
    if (!meldung) { return; }
    platz.appendChild(meldung);          // umhaengen, nicht kopieren
    meldung.classList.add('meldung-schwebt');

    var weg = function () {
      if (meldung.parentNode === platz) { platz.removeChild(meldung); }
    };
    meldung.addEventListener('click', function (e) {
      /* Ein Knopf in der Meldung ("Im Papierkorb ansehen") soll zuerst
         seine Arbeit tun - deshalb nur schliessen, wenn daneben getippt
         wurde. */
      if (!e.target.closest('button, a')) { weg(); }
    });
    if (meldung.classList.contains('meldung-gut')
        || meldung.classList.contains('meldung-info')) {
      window.setTimeout(weg, 7000);
    }
  }

  /* --- htmx-Feinschliff --------------------------------------------------- */
  document.body.addEventListener('htmx:afterSwap', function (e) {
    if (e.detail.target.id === 'tab-inhalt') {
      eingabenZurueckholen(e.detail.target);
      /* Zwei ganz verschiedene Faelle, die vorher gleich behandelt wurden:

         BEREICHSWECHSEL (GET, Klick in der Leiste): nach oben. Sonst steht
         man mitten in einer langen Liste, obwohl man gerade den Bereich
         gewechselt hat.

         FORMULAR ABGESCHICKT (POST): stehen bleiben. Vorher sprang die
         Seite auch hier nach oben - wer unten in einer langen Liste etwas
         eintrug, wurde jedes Mal an den Anfang geworfen und musste sich
         zurueckscrollen. Und war es eine Fehlermeldung, blieb man zwar
         stehen, die Meldung stand aber ganz oben ausser Sicht.
         Jetzt kommt die Meldung zum Menschen statt umgekehrt. */
      var anfrage = e.detail.requestConfig || {};
      var warPost = String(anfrage.verb || '').toLowerCase() === 'post';
      if (!warPost) {
        window.scrollTo({top: 0, behavior: 'smooth'});
      } else {
        /* Genau da bleiben, wo man war. Der Bereich wird beim Abschicken
           komplett ersetzt; ohne das Zuruecksetzen landet man am Anfang,
           auch ohne dass jemand scrollt. Der vorige Stand steht in
           standVorDemAbschicken (siehe htmx:beforeSwap). */
        if (standVorDemAbschicken !== null) {
          window.scrollTo(0, standVorDemAbschicken);
          standVorDemAbschicken = null;
        }
        meldungHolen(e.detail.target);
      }
      klebenPruefen();
      if (window.augeAnhaengen) { window.augeAnhaengen(e.detail.target); }
    }
    bereichEingerichtet();
  });

  /* Läuft eine Anfrage länger als eine Viertelsekunde, wird der Bereich
     blass. Kürzer wäre nur Geflacker. */
  document.body.addEventListener('htmx:beforeRequest', function (e) {
    var ziel = e.detail.target;
    if (ziel && ziel.id === 'tab-inhalt') {
      ziel.dataset.warteZeit = setTimeout(function () {
        ziel.classList.add('htmx-request');
      }, 250);
    }
  });
  document.body.addEventListener('htmx:afterRequest', function (e) {
    var ziel = e.detail.target;
    if (ziel && ziel.dataset.warteZeit) {
      clearTimeout(+ziel.dataset.warteZeit);
      delete ziel.dataset.warteZeit;
      ziel.classList.remove('htmx-request');
    }
  });

  /* Abgelaufene Anmeldung (401): Die Erklärung des Servers wird eingesetzt,
     statt sie zu verwerfen. htmx tauscht bei Fehlercodes von sich aus nichts
     ein - hier ist der Text aber genau das, was jemand jetzt braucht. Das
     Formular daneben bleibt stehen, der getippte Text ist nicht verloren. */
  document.body.addEventListener('htmx:beforeSwap', function (e) {
    /* Vor dem Austausch merken, wie weit die Seite gerollt war - nachher
       laesst sich der Stand nur so wiederherstellen. */
    var anfrage = e.detail.requestConfig || {};
    if (String(anfrage.verb || '').toLowerCase() === 'post') {
      standVorDemAbschicken = window.scrollY || window.pageYOffset || 0;
    }
    if (e.detail.xhr && e.detail.xhr.status === 401) {
      e.detail.shouldSwap = true;
      e.detail.isError = false;
    }
  });

  /* Antwortet der Server gar nicht, darf der Bereich nicht leer bleiben. */
  document.body.addEventListener('htmx:responseError', function (e) {
    if (e.detail.target && e.detail.target.id === 'tab-inhalt'
        && e.detail.xhr.status >= 500) {
      e.detail.target.innerHTML =
        '<div class="panel meldung meldung-fehler"><div>Der Server hat nicht '
        + 'geantwortet. Bitte den Bereich noch einmal öffnen.</div></div>';
    }
  });

  /* --- Start -------------------------------------------------------------- */
  function los() {
    klebenPruefen();
    var inhalt = document.getElementById('tab-inhalt');
    var schon = inhalt ? inhalt.dataset.start : '';
    /* Den Bereich aus der Adresszeile öffnen, sonst den ersten. */
    var wunsch = (window.location.hash || '').replace('#', '');
    var punkt = wunsch
      ? document.querySelector('.leisten-punkt[data-bereich="' + wunsch + '"]')
      : null;

    /* Steht der gewünschte Bereich schon fertig da, nicht noch einmal holen.
       Der Server legt die Übersicht bereits in den Rahmen; ein sofortiges
       Nachladen wäre ein zweiter Rundweg für dasselbe Ergebnis - und ein
       sichtbares Aufblitzen. */
    if (schon && (!wunsch || wunsch === schon)) {
      bereichAktiv(document.querySelector('.leisten-punkt[data-bereich="' + schon + '"]'));
      bereichEingerichtet();
      return;
    }
    (punkt || document.querySelector('.leisten-punkt')).click();
  }

  if (document.readyState !== 'loading') { los(); }
  else { document.addEventListener('DOMContentLoaded', los); }
})();
