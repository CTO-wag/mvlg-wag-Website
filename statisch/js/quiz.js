/* Ablaufsteuerung des Quiz.

   Ohne Bibliothek und ohne Serverkontakt: Fragen und Lösungen stehen bereits
   im Markup, das Skript blendet nur die aktuelle Frage ein, wertet den Klick
   aus und stellt am Ende die Bilanz zusammen. Es geht nichts an den Server,
   also wird auch nichts gespeichert - genau das steht über dem Quiz. */
(function () {
  'use strict';
  var wurzel = document.getElementById('quiz');
  if (!wurzel) { return; }

  var fragen = Array.prototype.slice.call(wurzel.querySelectorAll('.quiz-frage'));
  var gesamt = fragen.length;
  if (!gesamt) { return; }

  var zaehler = document.getElementById('quiz-zaehler');
  var stand = document.getElementById('quiz-stand');
  var balken = document.getElementById('quiz-balken');
  var fuellung = document.getElementById('quiz-fuellung');
  var ergebnis = document.getElementById('quiz-ergebnis');
  var trefferFeld = document.getElementById('quiz-treffer');
  var urteil = document.getElementById('quiz-urteil');
  var bilanz = document.getElementById('quiz-bilanz');

  var aktuell = 0, treffer = 0, beantwortet = 0;

  function loesung(frage) {
    return frage.querySelectorAll('.quiz-option-text')[+frage.dataset.richtig].textContent;
  }

  function fortschritt() {
    fuellung.style.width = (beantwortet / gesamt * 100) + '%';
    balken.setAttribute('aria-valuenow', beantwortet);
    stand.textContent = treffer + ' richtig';
  }

  function zeige(nr, fokus) {
    aktuell = nr;
    fragen.forEach(function (f, i) { f.hidden = i !== nr; });
    ergebnis.hidden = true;
    zaehler.textContent = 'Frage ' + (nr + 1) + ' von ' + gesamt;
    if (fokus) { fragen[nr].querySelector('.quiz-frage-text').focus(); }
  }

  function auswerten(frage, knopf) {
    if (frage.dataset.beantwortet) { return; }
    frage.dataset.beantwortet = '1';
    var richtig = +frage.dataset.richtig;
    var korrekt = +knopf.dataset.nr === richtig;
    frage.querySelectorAll('.quiz-option').forEach(function (o, i) {
      o.disabled = true;
      if (i === richtig) { o.classList.add('richtig'); }
    });
    if (korrekt) { treffer++; } else { knopf.classList.add('falsch'); }
    frage.dataset.korrekt = korrekt ? '1' : '0';
    beantwortet++;
    fortschritt();

    var meldung = frage.querySelector('.quiz-rueckmeldung');
    meldung.className = 'quiz-rueckmeldung meldung ' + (korrekt ? 'meldung-gut' : 'meldung-fehler');
    meldung.textContent = '';
    var kasten = document.createElement('div');
    var kopf = document.createElement('strong');
    kopf.textContent = korrekt ? 'Richtig.' : 'Nicht ganz.';
    kasten.appendChild(kopf);
    if (!korrekt) {
      kasten.appendChild(document.createTextNode(' Richtig ist: ' + loesung(frage)));
    }
    meldung.appendChild(kasten);
    meldung.hidden = false;

    var weiter = frage.querySelector('.quiz-weiter');
    weiter.hidden = false;
    weiter.focus();
  }

  function zeigeErgebnis() {
    fragen.forEach(function (f) { f.hidden = true; });
    zaehler.textContent = 'Auswertung';
    trefferFeld.textContent = treffer;
    var quote = treffer / gesamt;
    urteil.textContent =
      quote === 1 ? 'Alles richtig – besser geht es nicht.' :
      quote >= 0.8 ? 'Starkes Ergebnis, die Grundlagen sitzen.' :
      quote >= 0.5 ? 'Solide Basis – ein paar Begriffe fehlen noch.' :
                     'Da ist noch Luft nach oben. Genau dafür gibt es die AG.';

    bilanz.textContent = '';
    fragen.forEach(function (frage) {
      var korrekt = frage.dataset.korrekt === '1';
      var eintrag = document.createElement('li');
      eintrag.className = korrekt ? 'gut' : 'schlecht';

      var zeichen = document.createElement('span');
      zeichen.className = 'quiz-bilanz-zeichen';
      zeichen.setAttribute('aria-hidden', 'true');
      zeichen.textContent = korrekt ? 'Richtig' : 'Falsch';
      eintrag.appendChild(zeichen);

      var block = document.createElement('div');
      var hilfe = document.createElement('span');
      hilfe.className = 'nur-lesehilfe';
      hilfe.textContent = korrekt ? 'Richtig beantwortet: ' : 'Falsch beantwortet: ';
      block.appendChild(hilfe);
      var titel = document.createElement('strong');
      titel.textContent = frage.querySelector('.quiz-frage-text').textContent;
      block.appendChild(titel);
      if (!korrekt) {
        var loes = document.createElement('span');
        loes.className = 'quiz-bilanz-loesung';
        loes.textContent = 'Richtig wäre gewesen: ' + loesung(frage);
        block.appendChild(loes);
      }
      eintrag.appendChild(block);
      bilanz.appendChild(eintrag);
    });
    ergebnis.hidden = false;
    ergebnis.focus();
  }

  function neustart() {
    treffer = 0; beantwortet = 0;
    fragen.forEach(function (frage) {
      delete frage.dataset.beantwortet;
      delete frage.dataset.korrekt;
      frage.querySelectorAll('.quiz-option').forEach(function (o) {
        o.disabled = false;
        o.classList.remove('richtig', 'falsch');
      });
      var m = frage.querySelector('.quiz-rueckmeldung');
      m.hidden = true; m.textContent = '';
      frage.querySelector('.quiz-weiter').hidden = true;
    });
    fortschritt();
    zeige(0, true);
  }

  wurzel.addEventListener('click', function (e) {
    var option = e.target.closest('.quiz-option');
    if (option) { auswerten(option.closest('.quiz-frage'), option); return; }
    if (e.target.closest('.quiz-weiter')) {
      if (aktuell + 1 < gesamt) { zeige(aktuell + 1, true); } else { zeigeErgebnis(); }
      return;
    }
    if (e.target.closest('#quiz-neu')) { neustart(); }
  });

  fortschritt();
  zeige(0, false);
})();
