/* ===========================================================================
   Gemeinsames Skript beider Seiten: Farbschema, Menü, kleine Helfer.

   Bewusst ohne Bibliothek und ohne Modulsystem: eine Datei, die der Browser
   in einem Zug lädt. Alles hängt an Datenattributen im Markup statt an
   onclick="" - so kommt die Sicherheitsrichtlinie ohne 'unsafe-inline' aus.
   ========================================================================= */
(function () {
  'use strict';

  /* --- Farbschema -------------------------------------------------------- */
  function themaUmschalten() {
    var wurzel = document.documentElement;
    var neu = wurzel.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    wurzel.setAttribute('data-theme', neu);
    try { localStorage.setItem('thema', neu); } catch (e) { /* Privatmodus */ }
  }

  /* --- Menü auf schmalen Bildschirmen ------------------------------------ */
  function menueUmschalten(kopf, knopf, offen) {
    var auf = offen === undefined ? !kopf.classList.contains('offen') : offen;
    kopf.classList.toggle('offen', auf);
    if (knopf) { knopf.setAttribute('aria-expanded', auf ? 'true' : 'false'); }
  }

  document.addEventListener('click', function (e) {
    var themaKnopf = e.target.closest('[data-thema]');
    if (themaKnopf) { themaUmschalten(); return; }

    var kopf = document.getElementById('kopfzeile');
    var burger = e.target.closest('[data-burger]');
    if (burger && kopf) { menueUmschalten(kopf, burger); return; }

    /* Ausserhalb geklickt: Menü zu. Sonst bleibt es auf dem Handy offen
       stehen, während man darunter weiterliest. */
    if (kopf && kopf.classList.contains('offen') && !kopf.contains(e.target)) {
      menueUmschalten(kopf, kopf.querySelector('[data-burger]'), false);
    }

    /* Sicherheitsabfrage vor unwiederbringlichen Aktionen. Als Attribut statt
       als onclick, damit der Text am Formular steht, wo er hingehört. */
    var frage = e.target.closest('[data-frage]');
    if (frage && !window.confirm(frage.getAttribute('data-frage'))) {
      e.preventDefault();
      e.stopPropagation();
    }
  });

  document.addEventListener('keydown', function (e) {
    var dialog = document.querySelector('[data-bild-dialog]:not([hidden])');
    if (dialog && (e.key === 'Escape' || e.key === 'ArrowLeft'
                   || e.key === 'ArrowRight')) {
      if (e.key === 'Escape') { bildDialogSchliessen(); }
      else { bildDialogZeige(e.key === 'ArrowRight' ? 1 : -1); }
      return;
    }
    if (e.key !== 'Escape') { return; }
    var kopf = document.getElementById('kopfzeile');
    if (kopf && kopf.classList.contains('offen')) {
      menueUmschalten(kopf, kopf.querySelector('[data-burger]'), false);
    }
  });

  /* --- Startseiten-Bilder als Slideshow --------------------------------- */
  var bildDialogBilder = [];
  var bildDialogIndex = 0;
  function bildDialogAktualisieren() {
    var dialog = document.querySelector('[data-bild-dialog]');
    var bild = dialog && dialog.querySelector('[data-bild-dialog-bild]');
    if (!bild || !bildDialogBilder.length) { return; }
    var eintrag = bildDialogBilder[bildDialogIndex];
    bild.src = eintrag.src;
    bild.alt = eintrag.alt;
    var mehrere = bildDialogBilder.length > 1;
    dialog.querySelector('[data-bild-zurueck]').hidden = !mehrere;
    dialog.querySelector('[data-bild-weiter]').hidden = !mehrere;
  }
  function bildDialogOeffnen(bilder, index) {
    bildDialogBilder = bilder;
    bildDialogIndex = index;
    var dialog = document.querySelector('[data-bild-dialog]');
    if (!dialog) { return; }
    dialog.hidden = false;
    bildDialogAktualisieren();
    document.body.style.overflow = 'hidden';
    dialog.querySelector('[data-bild-schliessen]').focus();
  }
  function bildDialogSchliessen() {
    var dialog = document.querySelector('[data-bild-dialog]');
    if (!dialog) { return; }
    dialog.hidden = true;
    document.body.style.overflow = '';
    bildDialogBilder = [];
  }
  function bildDialogZeige(richtung) {
    if (!bildDialogBilder.length) { return; }
    bildDialogIndex = (bildDialogIndex + richtung + bildDialogBilder.length)
      % bildDialogBilder.length;
    bildDialogAktualisieren();
  }
  document.addEventListener('click', function (e) {
    var knopf = e.target.closest('[data-galerie-bild]');
    var dialog = e.target.closest('[data-bild-dialog]');
    if (knopf) {
      var galerie = knopf.closest('.portfolio-galerie');
      var bilder = Array.prototype.map.call(
        galerie.querySelectorAll('[data-galerie-bild] img'),
        function (img) { return {src: img.src, alt: img.alt}; });
      bildDialogOeffnen(bilder, Array.prototype.indexOf.call(
        galerie.querySelectorAll('[data-galerie-bild]'), knopf));
      return;
    }
    if (dialog && e.target === dialog) { bildDialogSchliessen(); return; }
    if (e.target.closest('[data-bild-schliessen]')) { bildDialogSchliessen(); return; }
    if (e.target.closest('[data-bild-zurueck]')) { bildDialogZeige(-1); return; }
    if (e.target.closest('[data-bild-weiter]')) { bildDialogZeige(1); }
  });

  /* --- Aus einer Fehlermeldung heraus den Support erreichen ---------------
     Gemeldet: Wer sich bewirbt und dabei gegen einen Fehler läuft, versucht
     es zweimal und gibt auf. Dass es einen Kontakt gibt, steht auf der
     Startseite - also genau dort, wo er in diesem Moment nicht ist.

     Der Knopf in der Meldung (siehe vorlagen/teile/meldungen.html) bringt
     ihn deshalb zum Kontaktformular und schreibt schon hinein, was passiert
     ist. Ohne das steht in jeder zweiten Anfrage "geht nicht", und die
     Rückfrage kostet Tage - bei jemandem, der uns noch gar nicht kennt.

     Über sessionStorage und nicht über die Adresszeile: Ein Text aus der URL,
     der in ein Formular läuft, ist eine Einladung, die man jemandem als
     Verweis schicken kann. Der Speicher gilt nur für diesen Tab und diese
     Herkunft; geschrieben wird ausschliesslich in .value, nie in HTML. */
  var SUPPORT_SCHLUESSEL = 'wag-support-anlass';

  document.addEventListener('click', function (e) {
    var knopf = e.target.closest('[data-support-melden]');
    if (!knopf) { return; }
    try {
      sessionStorage.setItem(SUPPORT_SCHLUESSEL, JSON.stringify({
        text: knopf.dataset.supportText || '',
        betreff: knopf.dataset.supportBetreff || '',
        wo: window.location.pathname
      }));
    } catch (f) { /* Privatmodus - dann eben ohne vorbereiteten Text */ }
    window.location.href = '/#kontakt';
  });

  function supportAnlassEinsetzen() {
    var feld = document.querySelector('.kontakt-formular [name="nachricht"]');
    if (!feld) { return; }
    var roh = null;
    try {
      roh = sessionStorage.getItem(SUPPORT_SCHLUESSEL);
      sessionStorage.removeItem(SUPPORT_SCHLUESSEL);
    } catch (f) { return; }
    if (!roh) { return; }
    var anlass;
    try { anlass = JSON.parse(roh); } catch (f) { return; }
    if (!anlass || !anlass.text) { return; }

    feld.value = 'Auf der Seite ' + (anlass.wo || '/') + ' kam diese Meldung:\n\n'
      + anlass.text + '\n\nWas ich gemacht habe:\n';
    var abschnitt = feld.closest('#kontakt') || feld;
    abschnitt.scrollIntoView({behavior: 'smooth', block: 'start'});
    /* Hinter den vorbereiteten Text - dort geht es weiter, nicht am Anfang. */
    window.setTimeout(function () {
      feld.focus({preventScroll: true});
      feld.selectionStart = feld.selectionEnd = feld.value.length;
    }, 400);
  }

  if (document.readyState !== 'loading') { supportAnlassEinsetzen(); }
  else {
    document.addEventListener('DOMContentLoaded', supportAnlassEinsetzen);
  }

  /* --- In die Zwischenablage --------------------------------------------- */
  /* Für Kalenderadresse, ntfy-Thema, Startpasswort. Mit sichtbarer Rückmeldung:
     ohne sie weiss niemand, ob der Klick etwas bewirkt hat. */
  document.addEventListener('click', function (e) {
    var knopf = e.target.closest('[data-kopieren]');
    if (!knopf) { return; }
    e.preventDefault();
    var quelle = document.querySelector(knopf.getAttribute('data-kopieren'));
    var wert = quelle ? (quelle.value || quelle.textContent || '') : '';
    var fertig = function () {
      var alt = knopf.textContent;
      knopf.textContent = 'Kopiert';
      knopf.classList.add('btn-gut');
      setTimeout(function () {
        knopf.textContent = alt;
        knopf.classList.remove('btn-gut');
      }, 1600);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(wert).then(fertig, function () { });
    } else if (quelle && quelle.select) {
      /* Ohne HTTPS gibt es die Zwischenablage-Schnittstelle nicht. */
      quelle.select();
      try { document.execCommand('copy'); fertig(); } catch (err) { /* egal */ }
    }
  });

  /* --- Zeichenzähler ------------------------------------------------------ */
  document.addEventListener('input', function (e) {
    var feld = e.target;
    if (!feld.hasAttribute || !feld.hasAttribute('data-zaehler')) { return; }
    var anzeige = document.querySelector(feld.getAttribute('data-zaehler'));
    if (!anzeige) { return; }
    var max = parseInt(feld.getAttribute('maxlength') || '0', 10);
    var rest = max - feld.value.length;
    anzeige.textContent = max ? (rest + ' Zeichen frei') : (feld.value.length + ' Zeichen');
    anzeige.classList.toggle('zeichen-knapp', max > 0 && rest < 40);
  });

  /* --- Formular gegen Doppelklick sichern -------------------------------- */
  /* Ein zweiter Klick auf "Senden", weil die erste Antwort dauert, legte in V1
     regelmässig doppelte Aufgaben und doppelte Bewerbungen an. */
  document.addEventListener('submit', function (e) {
    var formular = e.target;
    if (formular.hasAttribute('data-mehrfach')) { return; }
    var knopf = formular.querySelector('button[type="submit"], button:not([type])');
    if (!knopf || knopf.disabled) { return; }
    setTimeout(function () {
      knopf.disabled = true;
      knopf.dataset.text = knopf.textContent;
      knopf.textContent = 'Einen Moment …';
      /* Falls der Server nicht antwortet, darf der Knopf nicht für immer
         gesperrt bleiben. */
      setTimeout(function () {
        knopf.disabled = false;
        if (knopf.dataset.text) { knopf.textContent = knopf.dataset.text; }
      }, 12000);
    }, 0);
  });

  /* --- In ein Passwortfeld hineinsehen -----------------------------------
     Gemeldet: "hat obwohl richtigem Passwort falsches Passwort gesagt". Der
     haeufigste Grund dafuer ist kein Fehler im Programm, sondern der
     Passwortspeicher des Browsers: Er fuellt das Feld "Bisheriges Passwort"
     mit einem alten gespeicherten Wert, und man sieht nur Punkte. Mit dem
     Auge daneben laesst sich das in einer Sekunde klaeren.

     Der Knopf wird an jedes Passwortfeld gehaengt, sobald es im Dokument
     steht - auch an die, die htmx spaeter nachlaedt. */
  function augeAnhaengen(wurzel) {
    (wurzel || document).querySelectorAll('input[type="password"]').forEach(
      function (feld) {
        if (feld.dataset.auge) { return; }
        feld.dataset.auge = '1';
        var knopf = document.createElement('button');
        knopf.type = 'button';
        knopf.className = 'auge';
        knopf.setAttribute('aria-label', 'Passwort anzeigen');
        knopf.textContent = 'anzeigen';
        knopf.addEventListener('click', function () {
          var zeigen = feld.type === 'password';
          feld.type = zeigen ? 'text' : 'password';
          knopf.textContent = zeigen ? 'verbergen' : 'anzeigen';
          knopf.setAttribute('aria-label',
            zeigen ? 'Passwort verbergen' : 'Passwort anzeigen');
          feld.focus();
        });
        var huelle = document.createElement('span');
        huelle.className = 'feld-mit-auge';
        feld.parentNode.insertBefore(huelle, feld);
        huelle.appendChild(feld);
        huelle.appendChild(knopf);
      });
  }

  window.augeAnhaengen = augeAnhaengen;
  if (document.readyState !== 'loading') { augeAnhaengen(); }
  else { document.addEventListener('DOMContentLoaded', function () {
    augeAnhaengen();
  }); }

  /* --- Verweise auf die andere Haelfte, wenn die App installiert ist -----
     Eine installierte Web-App gehoert zu GENAU EINEM Ursprung. Wer im
     installierten Dashboard auf "Website" tippt, verlaesst diesen Ursprung -
     und dann macht das Telefon aus der App wieder einen Browser mit
     Adresszeile, aus dem man nicht mehr herausfindet.

     Solange beide Haelften unter verschiedenen Namen laufen, laesst sich das
     nicht verhindern. Aber es laesst sich sauber machen: Solche Verweise
     oeffnen ein eigenes Fenster. Die App bleibt dann App, und die andere
     Seite ist ein Besuch, den man wieder schliesst.

     Nur im installierten Zustand - im normalen Browser waeren neue Fenster
     eine Zumutung. */
  /* Gesetzt wird das Merkmal schon im Seitenkopf (vorlagen/basis.html), noch
     vor dem ersten Zeichnen - dort wird es fuer den Abstand oben gebraucht.
     Hier nur nachgelesen: zwei getrennte Pruefungen koennen auseinander-
     laufen, und dann stimmt entweder der Abstand nicht oder die Meldung. */
  if (document.documentElement.hasAttribute('data-app')) {
    document.addEventListener('click', function (e) {
      var verweis = e.target.closest('a[href]');
      if (!verweis || verweis.target) { return; }
      var ziel;
      try { ziel = new URL(verweis.href, window.location.href); }
      catch (f) { return; }
      if (ziel.protocol !== 'http:' && ziel.protocol !== 'https:') { return; }
      if (ziel.origin === window.location.origin) { return; }
      verweis.target = '_blank';
      verweis.rel = 'noopener';
    }, true);

    /* Einmal je Sitzung dem Server sagen, dass diese Person das Dashboard
       wirklich als App benutzt. Nur so laesst sich der Hinweis "leg es auf
       den Startbildschirm" wieder abstellen - raten koennte man es nicht,
       und fragen waere eine Frage, deren Antwort der Browser schon kennt.
       Ein Fehlschlag bleibt still: Es ist eine Nebenbemerkung, kein
       Arbeitsschritt, und eine Meldung darueber waere nur im Weg. */
    if (window.location.pathname.indexOf('/dashboard') === 0
        && !sessionStorage.getItem('wag-als-app')) {
      var marke = document.getElementById('dash-csrf');
      if (marke && marke.value) {
        sessionStorage.setItem('wag-als-app', '1');
        var daten = new FormData();
        daten.append('csrf', marke.value);
        fetch('/dashboard/als-app', {method: 'POST', body: daten,
                                     credentials: 'same-origin'})
          .catch(function () { sessionStorage.removeItem('wag-als-app'); });
      }
    }
  }

  /* --- Hintergrundskript (PWA) ------------------------------------------- */
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () { /* nicht schlimm */ });
    });
  }
})();
