const header = document.querySelector('.site-header');
const toggle = document.querySelector('.nav-toggle');
const nav = document.querySelector('.site-nav');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const syncHeader = () => header.classList.toggle('scrolled', window.scrollY > 24);
window.addEventListener('scroll', syncHeader, { passive: true });
syncHeader();

toggle?.addEventListener('click', () => {
  const open = nav.classList.toggle('open');
  toggle.setAttribute('aria-expanded', String(open));
});

nav?.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
  nav.classList.remove('open');
  toggle?.setAttribute('aria-expanded', 'false');
}));

const staggerGroups = ['.activity-path', '.team-roles'];
staggerGroups.forEach((selector) => {
  document.querySelectorAll(`${selector} > *`).forEach((element, index) => {
    element.classList.add('reveal');
    element.style.setProperty('--delay', `${Math.min(index * 110, 440)}ms`);
  });
});
document.querySelectorAll('.footer-main > *').forEach((element, index) => {
  element.classList.add('reveal');
  element.style.setProperty('--delay', `${index * 100}ms`);
});

const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) {
      entry.target.classList.add('is-visible');
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.08, rootMargin: '0px 0px -7% 0px' });

document.querySelectorAll('.reveal').forEach((element) => revealObserver.observe(element));

const revealPassed = () => {
  document.querySelectorAll('.reveal:not(.is-visible)').forEach((element) => {
    if (element.getBoundingClientRect().top < window.innerHeight * 0.94) {
      element.classList.add('is-visible');
      revealObserver.unobserve(element);
    }
  });
};
window.addEventListener('scroll', revealPassed, { passive: true });
revealPassed();

const carousel = document.querySelector('[data-carousel]');
const carouselViewport = carousel?.querySelector('.news-viewport');
const carouselTrack = carousel?.querySelector('.news-track');
const carouselSlides = [...(carousel?.querySelectorAll('.news-slide') || [])];
const carouselDots = [...(carousel?.querySelectorAll('.carousel-dot') || [])];
let activeSlide = 0;
let carouselTimer;

const startCarousel = () => {
  window.clearInterval(carouselTimer);
  if (!reducedMotion && carouselSlides.length > 1) {
    carouselTimer = window.setInterval(() => showSlide(activeSlide + 1, false), 6500);
  }
};

const showSlide = (index, restart = true) => {
  if (!carouselSlides.length) return;
  activeSlide = (index + carouselSlides.length) % carouselSlides.length;
  carouselSlides.forEach((slide, slideIndex) => {
    const distance = (slideIndex - activeSlide + carouselSlides.length) % carouselSlides.length;
    slide.classList.toggle('is-active', distance === 0);
    slide.classList.toggle('is-after', distance === 1);
    slide.classList.toggle('is-before', distance > 1);
    slide.setAttribute('aria-hidden', String(slideIndex !== activeSlide));
  });
  carouselDots.forEach((dot, dotIndex) => {
    const selected = dotIndex === activeSlide;
    dot.classList.toggle('is-active', selected);
    dot.setAttribute('aria-pressed', String(selected));
  });
  if (restart && !reducedMotion) {
    startCarousel();
  }
};

carouselDots.forEach((dot, index) => dot.addEventListener('click', () => showSlide(index)));
showSlide(0);
window.addEventListener('resize', () => showSlide(activeSlide, false), { passive: true });
carousel?.addEventListener('pointerenter', () => window.clearInterval(carouselTimer));
carousel?.addEventListener('pointerleave', startCarousel);
carousel?.addEventListener('focusin', () => window.clearInterval(carouselTimer));
carousel?.addEventListener('focusout', (event) => {
  if (!carousel.contains(event.relatedTarget)) startCarousel();
});

const activityLine = document.querySelector('.line-reveal');
const syncActivityLine = () => {
  if (!activityLine) return;
  if (reducedMotion) {
    activityLine.style.setProperty('--line-progress', '1');
    return;
  }
  const rect = activityLine.getBoundingClientRect();
  const start = window.innerHeight * .82;
  const distance = rect.height + window.innerHeight * .45;
  const progress = Math.max(0, Math.min(1, (start - rect.top) / distance));
  activityLine.style.setProperty('--line-progress', String(progress));
};
window.addEventListener('scroll', syncActivityLine, { passive: true });
window.addEventListener('resize', syncActivityLine, { passive: true });
syncActivityLine();

const words = ['VERSTEHEN.', 'ERLEBEN.', 'GESTALTEN.', 'BEWEGEN.'];
const dynamicWord = document.querySelector('.dynamic-word');
let wordIndex = 0;

if (dynamicWord && !reducedMotion) {
  window.setInterval(() => {
    dynamicWord.classList.remove('opening');
    dynamicWord.classList.add('closing');
    window.setTimeout(() => {
      wordIndex = (wordIndex + 1) % words.length;
      dynamicWord.textContent = words[wordIndex];
      dynamicWord.classList.remove('closing');
      void dynamicWord.offsetWidth;
      dynamicWord.classList.add('opening');
      window.setTimeout(() => dynamicWord.classList.remove('opening'), 560);
    }, 340);
  }, 2600);
}

const canvas = document.querySelector('#economy-globe');
const context = canvas?.getContext('2d');
let width = 0;
let height = 0;
let pixelRatio = 1;
let rotation = 0;

const resizeCanvas = () => {
  if (!canvas || !context) return;
  const rect = canvas.getBoundingClientRect();
  pixelRatio = Math.min(window.devicePixelRatio || 1, 1.8);
  width = rect.width;
  height = rect.height;
  canvas.width = Math.round(width * pixelRatio);
  canvas.height = Math.round(height * pixelRatio);
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
};

const projectPoint = (latitude, longitude, radius, cx, cy) => {
  const lat = latitude * Math.PI / 180;
  const lon = longitude * Math.PI / 180 + rotation;
  const x = Math.cos(lat) * Math.sin(lon);
  const y = Math.sin(lat);
  const z = Math.cos(lat) * Math.cos(lon);
  const perspective = 1.12 / (1.95 - z * .32);
  return { x: cx + x * radius * perspective, y: cy - y * radius * perspective, z };
};

const landmasses = [
  [[-168,72],[-135,74],[-112,60],[-83,48],[-60,52],[-82,24],[-105,18],[-128,36],[-154,55]],
  [[-82,13],[-64,9],[-48,-4],[-35,-23],[-50,-55],[-67,-48],[-78,-18]],
  [[-73,83],[-20,81],[-18,62],[-52,58],[-67,69]],
  [[-12,71],[28,72],[45,58],[34,42],[10,35],[-11,45]],
  [[-18,36],[18,38],[48,31],[51,8],[34,-34],[10,-36],[-8,-7]],
  [[28,72],[95,79],[170,63],[153,25],[123,5],[104,-8],[77,8],[47,28]],
  [[112,-11],[154,-9],[157,-39],[132,-45],[114,-33]]
];

const isInsidePolygon = (longitude, latitude, polygon) => {
  let inside = false;
  for (let current = 0, previous = polygon.length - 1; current < polygon.length; previous = current++) {
    const [xi, yi] = polygon[current];
    const [xj, yj] = polygon[previous];
    const intersects = ((yi > latitude) !== (yj > latitude)) && (longitude < (xj - xi) * (latitude - yi) / (yj - yi) + xi);
    if (intersects) inside = !inside;
  }
  return inside;
};

const isLand = (longitude, latitude) => landmasses.some((polygon) => isInsidePolygon(longitude, latitude, polygon));

const drawGlobe = () => {
  if (!context) return;
  context.clearRect(0, 0, width, height);
  const cx = width / 2;
  const cy = height * .52;
  const radius = Math.min(width * .39, height * .56, 470);

  context.beginPath();
  context.arc(cx, cy, radius * .72, 0, Math.PI * 2);
  const glow = context.createRadialGradient(cx, cy, 0, cx, cy, radius * .74);
  glow.addColorStop(0, 'rgba(215,165,71,.025)');
  glow.addColorStop(.72, 'rgba(215,165,71,.055)');
  glow.addColorStop(1, 'rgba(215,165,71,0)');
  context.fillStyle = glow;
  context.fill();

  for (let latitude = -78; latitude <= 78; latitude += 8) {
    for (let longitude = -180; longitude < 180; longitude += 8) {
      const point = projectPoint(latitude, longitude, radius, cx, cy);
      const front = Math.max(0, (point.z + .2) / 1.2);
      const alpha = .018 + front * .09;
      const size = .45 + front * .45;
      context.beginPath();
      context.arc(point.x, point.y, size, 0, Math.PI * 2);
      context.fillStyle = `rgba(224,216,194,${alpha})`;
      context.fill();
    }
  }

  for (let latitude = -76; latitude <= 82; latitude += 4) {
    for (let longitude = -176; longitude < 180; longitude += 4) {
      if (!isLand(longitude, latitude)) continue;
      const point = projectPoint(latitude, longitude, radius, cx, cy);
      if (point.z < -.08) continue;
      const front = Math.max(0, (point.z + .08) / 1.08);
      context.beginPath();
      context.arc(point.x, point.y, .9 + front * 1.05, 0, Math.PI * 2);
      context.fillStyle = `rgba(240,198,107,${.1 + front * .68})`;
      context.fill();
    }
  }

  for (let index = 0; index < 3; index += 1) {
    const hub = projectPoint(16 - index * 12, -60 + index * 74, radius, cx, cy);
    if (hub.z > 0) {
      const pulse = 6 + Math.sin(rotation * 4 + index) * 2;
      context.beginPath();
      context.arc(hub.x, hub.y, pulse, 0, Math.PI * 2);
      context.strokeStyle = 'rgba(215,165,71,.3)';
      context.stroke();
      context.beginPath();
      context.arc(hub.x, hub.y, 2, 0, Math.PI * 2);
      context.fillStyle = 'rgba(240,198,107,.9)';
      context.fill();
    }
  }

  rotation += reducedMotion ? 0 : .0022;
  if (!reducedMotion) window.requestAnimationFrame(drawGlobe);
};

if (canvas && context) {
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);
  drawGlobe();
}

const mailAddress = 'cto@tech.mvlg-wag.de';

const applicationEndpoint = (() => {
  const local = ['127.0.0.1', 'localhost'].includes(window.location.hostname);
  return local
    ? 'http://127.0.0.1:8001/api/bewerbungen'
    : 'https://mvlg-wag.de/__ausfall/bewerben';
})();

document.querySelectorAll('[data-application-form]').forEach((form) => {
  const status = form.querySelector('.form-status');
  const submit = form.querySelector('[type="submit"]');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!form.checkValidity()) {
      form.reportValidity();
      if (status) {
        status.textContent = 'Bitte prüfe die markierten Felder.';
        status.className = 'form-status is-error';
      }
      return;
    }
    const values = Object.fromEntries(new FormData(form).entries());
    if (submit) submit.disabled = true;
    if (status) {
      status.textContent = 'Bewerbung wird übermittelt …';
      status.className = 'form-status';
    }
    try {
      const response = await fetch(applicationEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.fehler || result.grund || 'Die Übermittlung hat nicht geklappt.');
      form.reset();
      if (status) {
        status.textContent = result.status === 'duplicate'
          ? 'Diese Bewerbung ist heute bereits bei uns eingegangen.'
          : 'Danke! Deine Bewerbung ist bei uns angekommen.';
        status.className = 'form-status is-success';
      }
    } catch (error) {
      if (status) {
        status.textContent = error instanceof TypeError
          ? 'Keine Verbindung zum Bewerbungsformular. Bitte prüfe deine Internetverbindung und versuche es erneut.'
          : error.message || 'Die Bewerbung konnte gerade nicht übermittelt werden. Bitte versuche es später erneut.';
        status.className = 'form-status is-error';
      }
    } finally {
      if (submit) submit.disabled = false;
    }
  });
});

document.querySelectorAll('[data-mail-form]').forEach((form) => {
  const status = form.querySelector('.form-status');
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!form.checkValidity()) {
      form.reportValidity();
      if (status) {
        status.textContent = 'Bitte prüfe die markierten Felder.';
        status.className = 'form-status is-error';
      }
      return;
    }

    const values = new FormData(form);
    const lines = [];
    for (const [key, value] of values.entries()) {
      if (key === 'website' || !String(value).trim()) continue;
      const field = form.querySelector(`[name="${key}"]`);
      const label = field?.closest('label')?.childNodes[0]?.textContent?.trim() || key;
      lines.push(`${label}: ${value}`);
    }
    const subject = form.dataset.mailSubject || 'Nachricht über die WAG-Website';
    const href = `mailto:${mailAddress}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(lines.join('\n\n'))}`;
    if (status) {
      status.textContent = 'E-Mail-Entwurf wird geöffnet. Bitte prüfe die Nachricht und sende sie dort ab.';
      status.className = 'form-status';
    }
    window.location.href = href;
  });
});

const quizRoot = document.querySelector('[data-quiz]');
if (quizRoot) {
  const questions = [
    { question: 'Was bedeutet Inflation?', options: ['Das allgemeine Preisniveau steigt, Geld verliert an Kaufkraft', 'Die Zinsen der Zentralbank steigen', 'Der Aktienmarkt bricht ein', 'Der Staat gibt neue Anleihen aus'], answer: 0, note: 'Inflation beschreibt einen breiten Preisanstieg. Mit derselben Geldmenge kann man dann weniger kaufen.' },
    { question: 'Was ist Diversifikation?', options: ['Geld auf verschiedene Anlagen verteilen', 'Nur die beste Aktie kaufen', 'Kredite möglichst lange laufen lassen', 'Gewinne sofort ausgeben'], answer: 0, note: 'Verschiedene Anlagen können verhindern, dass ein einzelner Ausfall das gesamte Portfolio trifft.' },
    { question: 'Was besitzt man mit einer Aktie?', options: ['Einen kleinen Anteil an einem Unternehmen', 'Einen Kredit an den Staat', 'Ein garantiertes Sparguthaben', 'Eine Währungseinheit'], answer: 0, note: 'Eine Aktie verbrieft einen Eigentumsanteil an einer Aktiengesellschaft.' },
    { question: 'Was beschreibt der Zins?', options: ['Den Preis für geliehenes Geld', 'Den Umsatz eines Unternehmens', 'Die Höhe der Mehrwertsteuer', 'Den Kurs einer Währung'], answer: 0, note: 'Zinsen sind vereinfacht gesagt der Preis, den Kreditnehmer für Kapital zahlen.' },
    { question: 'Worin unterscheiden sich Umsatz und Gewinn?', options: ['Gewinn bleibt nach Abzug der Kosten vom Umsatz', 'Umsatz ist immer kleiner als Gewinn', 'Beide Begriffe meinen dasselbe', 'Gewinn entsteht vor dem Verkauf'], answer: 0, note: 'Der Umsatz umfasst Verkaufserlöse; der Gewinn berücksichtigt zusätzlich die Kosten.' },
    { question: 'Was passiert meist bei höherer Nachfrage und gleichbleibendem Angebot?', options: ['Der Preis steigt', 'Der Preis fällt immer auf null', 'Das Angebot verschwindet sofort', 'Die Nachfrage wird gesetzlich begrenzt'], answer: 0, note: 'Wenn mehr Menschen dieselbe knappe Menge kaufen wollen, steigt typischerweise der Preis.' },
    { question: 'Was ist ein ETF?', options: ['Ein Fonds, der häufig einen Index abbildet', 'Eine einzelne Unternehmensaktie', 'Eine Steuer auf Kapitalerträge', 'Ein kurzfristiger Bankkredit'], answer: 0, note: 'Viele ETFs bündeln zahlreiche Wertpapiere und bilden regelbasiert einen Index nach.' },
    { question: 'Wozu dienen Steuern?', options: ['Sie finanzieren öffentliche Aufgaben', 'Sie garantieren Unternehmensgewinne', 'Sie verhindern jeden Preisanstieg', 'Sie ersetzen alle Versicherungen'], answer: 0, note: 'Mit Steuereinnahmen werden unter anderem Bildung, Infrastruktur und Verwaltung finanziert.' },
    { question: 'Was gehört zu einem Geschäftsmodell?', options: ['Welches Problem für wen und wie gelöst wird', 'Nur der Name des Unternehmens', 'Nur das Logo und die Farben', 'Ausschließlich die Rechtsform'], answer: 0, note: 'Ein Geschäftsmodell verbindet Zielgruppe, Nutzen, Leistung, Kosten und Erlöse.' },
    { question: 'Welche Aufgabe hat eine Zentralbank?', options: ['Unter anderem Preisstabilität sichern', 'Einzelne Aktien empfehlen', 'Unternehmen gründen', 'Private Kaufverträge prüfen'], answer: 0, note: 'Zentralbanken steuern die Geldpolitik; im Euroraum steht Preisstabilität im Mittelpunkt.' }
  ];
  let currentQuestion = 0;
  let score = 0;
  let answered = false;

  const counter = quizRoot.querySelector('[data-quiz-counter]');
  const scoreNode = quizRoot.querySelector('[data-quiz-score]');
  const progress = quizRoot.querySelector('[data-quiz-progress]');
  const questionNode = quizRoot.querySelector('[data-quiz-question]');
  const optionsNode = quizRoot.querySelector('[data-quiz-options]');
  const feedback = quizRoot.querySelector('[data-quiz-feedback]');
  const nextButton = quizRoot.querySelector('[data-quiz-next]');

  const renderQuestion = () => {
    answered = false;
    const item = questions[currentQuestion];
    counter.textContent = `Frage ${currentQuestion + 1} von ${questions.length}`;
    scoreNode.textContent = `${score} richtig`;
    progress.style.width = `${((currentQuestion + 1) / questions.length) * 100}%`;
    questionNode.textContent = item.question;
    feedback.textContent = 'Wähle eine Antwort.';
    nextButton.hidden = true;
    optionsNode.innerHTML = '';
    const choices = item.options.map((option, index) => ({ option, correct: index === item.answer }));
    for (let index = choices.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(Math.random() * (index + 1));
      [choices[index], choices[swapIndex]] = [choices[swapIndex], choices[index]];
    }
    choices.forEach(({ option, correct }) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'quiz-option';
      button.textContent = option;
      button.dataset.correct = String(correct);
      button.addEventListener('click', () => answerQuestion(button, correct));
      optionsNode.appendChild(button);
    });
  };

  const answerQuestion = (selectedButton, correctChoice) => {
    if (answered) return;
    answered = true;
    const item = questions[currentQuestion];
    const buttons = [...optionsNode.querySelectorAll('button')];
    buttons.forEach((button) => {
      button.disabled = true;
      if (button.dataset.correct === 'true') button.classList.add('is-correct');
    });
    if (correctChoice) {
      score += 1;
      feedback.innerHTML = `<strong>Richtig.</strong> ${item.note}`;
    } else {
      selectedButton.classList.add('is-wrong');
      feedback.innerHTML = `<strong>Noch nicht.</strong> ${item.note}`;
    }
    scoreNode.textContent = `${score} richtig`;
    nextButton.hidden = false;
    nextButton.textContent = currentQuestion === questions.length - 1 ? 'Ergebnis ansehen' : 'Nächste Frage';
    nextButton.focus();
  };

  nextButton.addEventListener('click', () => {
    if (currentQuestion < questions.length - 1) {
      currentQuestion += 1;
      renderQuestion();
      questionNode.focus();
      return;
    }
    quizRoot.innerHTML = `<div class="quiz-result"><span class="pill">Ergebnis</span><div class="quiz-score">${score}/10</div><h2>${score >= 8 ? 'Starker Start.' : score >= 5 ? 'Gute Basis.' : 'Neugierig bleiben.'}</h2><p>${score >= 8 ? 'Du kennst schon viele Grundlagen. In der WAG kannst du sie in Projekten und Gesprächen anwenden.' : 'Dein Ergebnis ist nur ein Anfang. In der WAG kannst du Fragen stellen, Zusammenhänge entdecken und Neues ausprobieren.'}</p><div class="button-row"><a class="button button-light" href="bewerben.html">Jetzt bewerben <span>↗</span></a><button class="button button-outline" type="button" data-quiz-restart>Noch einmal</button></div></div>`;
    quizRoot.querySelector('[data-quiz-restart]').addEventListener('click', () => window.location.reload());
  });

  renderQuestion();
}
