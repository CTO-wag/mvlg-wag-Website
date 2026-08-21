/* ===========================================================================
   Dieses Gerät für Web Push anmelden.

   Wird einmal im Rahmen geladen und arbeitet mit Ereignissen am document -
   der Knopf steckt im Bereich „Nachrichten“, den htmx erst später nachlädt.
   (Ein <script> im nachgeladenen Bereich wäre unter der Nonce-Richtlinie
   blockiert worden, siehe dashboard.js.)

   Der Ablauf hat mehrere Stellen, an denen es scheitern kann, und jede davon
   hat einen anderen Grund. In V1 stand überall dieselbe Meldung ("Push konnte
   nicht eingerichtet werden") - damit war niemandem geholfen, besonders nicht
   auf dem iPhone, wo die Seite erst auf dem Startbildschirm liegen muss.
   ========================================================================= */
(function () {
  'use strict';

  function knopf() { return document.getElementById('push-anmelden'); }
  function hinweisfeld() { return document.getElementById('push-hinweis'); }

  /* Wohin die Anmeldung geht, steht am Knopf. Dieselbe Datei bedient beide
     Seiten: das Dashboard meldet sich unter /dashboard/nachrichten/… an, die
     Website unter /push-… - jede bei sich selbst, weil eine Push-Anmeldung
     immer nur fuer ihren eigenen Ursprung gilt. */
  function adresse(art) {
    var k = knopf();
    var eigen = k && k.getAttribute('data-' + art);
    if (eigen) { return eigen; }
    return art === 'schluessel'
      ? '/dashboard/nachrichten/push-schluessel'
      : '/dashboard/nachrichten/push-anmelden';
  }

  function sagen(text, art) {
    var feld = hinweisfeld();
    if (!feld) { return; }
    feld.textContent = text;
    feld.className = 'meta';
    if (art) { feld.classList.add(art); }
  }

  function csrf() {
    var feld = document.getElementById('dash-csrf')
      || document.getElementById('push-csrf');
    return feld ? feld.value : '';
  }

  /* Der Schlüssel kommt als Base64 vom Server, der Browser will Bytes. */
  function zuBytes(base64) {
    var voll = (base64 + '='.repeat((4 - base64.length % 4) % 4))
      .replace(/-/g, '+').replace(/_/g, '/');
    var roh = window.atob(voll);
    var bytes = new Uint8Array(roh.length);
    for (var i = 0; i < roh.length; i++) { bytes[i] = roh.charCodeAt(i); }
    return bytes;
  }

  function istAufStartbildschirm() {
    return window.matchMedia('(display-mode: standalone)').matches
      || window.navigator.standalone === true;
  }

  function istIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent)
      || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  }

  /* Wo man eine einmal erteilte Absage wieder aufhebt - je nach Geraet an
     einer ganz anderen Stelle. Ein blosses "in den Einstellungen des
     Browsers" laesst genau die Leute stehen, die es brauchen. */
  function erlaubnisWiederholen() {
    var anfang = 'Für diese Seite sind Benachrichtigungen im Browser '
      + 'gesperrt – deshalb fragt er gar nicht mehr. ';
    if (istIOS()) {
      return anfang + 'Auf dem iPhone: Einstellungen öffnen, nach unten zu '
        + 'dieser App scrollen, „Mitteilungen“ antippen und erlauben. '
        + 'Danach hier noch einmal tippen.';
    }
    if (/Android/.test(navigator.userAgent)) {
      return anfang + 'Auf Android: in der Adresszeile auf das Schloss '
        + 'tippen, „Berechtigungen“, dann „Benachrichtigungen“ zurücksetzen.';
    }
    return anfang + 'Am Rechner: links in der Adresszeile auf das Schloss '
      + 'klicken und die Benachrichtigungen für diese Seite wieder erlauben. '
      + 'Danach die Seite neu laden.';
  }

  function anmelden() {
    var k = knopf();
    if (!k) { return; }

    /* Auf dem iPhone hat Apple eine harte Regel: Web Push gibt es NUR, wenn
       die Seite ueber "Zum Home-Bildschirm" abgelegt und von dort geoeffnet
       wurde. In Safari selbst antwortet der Browser je nach Fassung mal mit
       einem fehlenden PushManager, mal mit einem sofortigen "denied" - und
       dann stand hier "Du hast abgelehnt", obwohl niemand irgendetwas
       abgelehnt hatte. Deshalb wird diese Bedingung zuerst geprueft und
       nicht erst, wenn schon etwas schiefgegangen ist. */
    if (istIOS() && !istAufStartbildschirm()) {
      sagen('Auf dem iPhone und iPad geht das erst, wenn diese Seite auf dem '
        + 'Home-Bildschirm liegt – das ist eine Vorgabe von Apple, nicht von '
        + 'uns. Teilen-Symbol antippen, „Zum Home-Bildschirm“ wählen, die App '
        + 'von dort öffnen und hier noch einmal tippen. Ohne das klappt nur '
        + 'ntfy – das Thema steht oben.', 'warnung');
      return;
    }

    if (!('serviceWorker' in navigator) || !('PushManager' in window)
        || !('Notification' in window)) {
      sagen('Dieser Browser kann kein Web Push. Über ntfy klappt es '
        + 'trotzdem – das Thema steht oben.', 'warnung');
      return;
    }

    /* Schon einmal abgelehnt? Dann fragt der Browser gar nicht mehr, sondern
       antwortet sofort mit "denied". Das ist etwas anderes als "gerade eben
       abgelehnt", und es braucht eine andere Anleitung - naemlich wo man die
       Sperre wieder aufhebt. Vorher stand in beiden Faellen derselbe Satz. */
    if (Notification.permission === 'denied') {
      sagen(erlaubnisWiederholen(), 'warnung');
      return;
    }
    if (!window.isSecureContext) {
      /* Nicht nur "braucht https" sagen, sondern den haeufigsten Fall
         benennen: Wer die Seite vom Handy aus ueber die Netzwerkadresse des
         Rechners aufruft (http://192.168.…), bekommt von jedem Browser eine
         Absage - dort ist Push schlicht gesperrt. */
      sagen('Push geht nur über eine verschlüsselte Verbindung. Diese Seite '
        + 'läuft gerade über ' + window.location.protocol + '//'
        + window.location.hostname + ' – das lässt der Browser nicht zu. '
        + 'Über die richtige Adresse (https) klappt es.', 'warnung');
      return;
    }

    k.disabled = true;
    sagen('Einen Moment …');

    /* Die Frage nach der Erlaubnis steht GANZ VORN und nicht hinter der
       Registrierung des Hintergrundskripts. Grund: Safari auf dem iPhone
       erlaubt requestPermission() nur direkt aus einer Berührung heraus.
       Vorher lagen zwei Zwischenschritte davor - bis die Frage kam, war die
       Berührung "verbraucht", und Safari lehnte kommentarlos ab. Auf dem
       iPhone ging die Anmeldung deshalb nie, und die Meldung behauptete
       obendrein, der Nutzer habe abgelehnt. */
    var erlaubnisFrage;
    try {
      erlaubnisFrage = Notification.requestPermission();
      /* Sehr alte Browser kennen nur die Rueckruf-Fassung. */
      if (!erlaubnisFrage || typeof erlaubnisFrage.then !== 'function') {
        erlaubnisFrage = new Promise(function (fertig) {
          Notification.requestPermission(fertig);
        });
      }
    } catch (f) {
      erlaubnisFrage = Promise.reject(new Error('unbekannt'));
    }

    erlaubnisFrage
      .then(function (erlaubnis) {
        if (erlaubnis !== 'granted') {
          throw new Error(erlaubnis === 'denied' ? 'abgelehnt' : 'offen');
        }
        return navigator.serviceWorker.register('/sw.js');
      })
      .then(function () { return navigator.serviceWorker.ready; })
      .then(function (registrierung) {
        return fetch(adresse('schluessel'))
          .then(function (a) { return a.text(); })
          .then(function (schluessel) {
            return registrierung.pushManager.subscribe({
              userVisibleOnly: true,
              applicationServerKey: zuBytes(schluessel.trim())
            });
          });
      })
      .then(function (abo) {
        var daten = abo.toJSON();
        return fetch(adresse('anmelden'), {
          method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded'},
          body: new URLSearchParams({
            csrf: csrf(),
            endpoint: abo.endpoint,
            p256dh: daten.keys.p256dh,
            auth: daten.keys.auth
          }).toString()
        });
      })
      .then(function (antwort) {
        if (!antwort.ok) { throw new Error('server'); }
        sagen('Geschafft. Dieses Gerät bekommt jetzt Meldungen. Probier es '
          + 'gleich mit „Probemeldung schicken“ aus.', 'gut');
        var kn = knopf();
        if (kn) { kn.textContent = 'Angemeldet'; }
      })
      .catch(function (fehler) {
        var kn = knopf();
        if (kn) { kn.disabled = false; }
        var grund = fehler && fehler.message;
        if (grund === 'abgelehnt') {
          sagen(erlaubnisWiederholen(), 'warnung');
        } else if (grund === 'offen') {
          sagen('Die Abfrage wurde weggeklickt. Tipp einfach noch einmal auf '
            + 'den Knopf.', 'warnung');
        } else if (grund === 'server') {
          sagen('Der Server hat die Anmeldung nicht angenommen. Bitte die '
            + 'Seite neu laden und noch einmal versuchen.', 'fehler');
        } else {
          sagen('Das hat nicht geklappt (' + (grund || 'unbekannt') + '). Über '
            + 'ntfy funktionieren Meldungen trotzdem.', 'fehler');
        }
      });
  }

  document.addEventListener('click', function (e) {
    if (e.target.closest('#push-anmelden')) { anmelden(); }
  });

  /* Ist dieses Gerät schon angemeldet, gleich sagen - sonst tippt jemand
     jedes Mal aufs Neue. Läuft nach jedem Bereichswechsel erneut, weil der
     Knopf dann neu im Dokument steht. */
  function zustandZeigen() {
    if (!knopf() || !('serviceWorker' in navigator) || !window.isSecureContext) {
      return;
    }
    navigator.serviceWorker.getRegistration().then(function (r) {
      if (!r) { return; }
      r.pushManager.getSubscription().then(function (abo) {
        var k = knopf();
        if (abo && k) {
          k.textContent = 'Angemeldet';
          sagen('Dieses Gerät ist bereits angemeldet.');
        }
      });
    }).catch(function () { });
  }

  document.body.addEventListener('htmx:afterSwap', zustandZeigen);
  if (document.readyState !== 'loading') { zustandZeigen(); }
  else { document.addEventListener('DOMContentLoaded', zustandZeigen); }
})();
