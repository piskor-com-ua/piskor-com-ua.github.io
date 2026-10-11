(() => {
  const script = document.currentScript;
  const measurementId = script?.dataset.measurementId;
  if (!measurementId || !/^G-[A-Z0-9]+$/.test(measurementId)) return;

  const key = 'piskor-analytics-choice-v1';
  const isEnglish = document.documentElement.lang.toLowerCase().startsWith('en');
  const copy = isEnglish ? {
    title: 'Your privacy choices',
    description: 'We use Google Analytics to understand how visitors use this site. If you allow analytics, Google receives page views and interactions, along with browser, device and approximate location data. Analytics stays off until you choose.',
    accept: 'Allow analytics',
    reject: 'Reject analytics',
    settings: 'Analytics preferences',
    learn: 'Google Privacy Policy',
    label: 'Analytics privacy preferences'
  } : {
    title: 'Ваш вибір щодо аналітики',
    description: 'Ми використовуємо Google Analytics, щоб розуміти, як відвідувачі користуються сайтом. Якщо дозволити аналітику, Google отримуватиме дані про перегляди й взаємодії, а також браузер, пристрій і приблизне місце перебування. До вашого вибору аналітика вимкнена.',
    accept: 'Дозволити аналітику',
    reject: 'Відхилити аналітику',
    settings: 'Налаштування аналітики',
    learn: 'Політика конфіденційності Google',
    label: 'Налаштування приватності аналітики'
  };

  let choice = null;
  try {
    choice = localStorage.getItem(key);
  } catch {
    try { choice = sessionStorage.getItem(key); } catch { /* Keep the banner available. */ }
  }

  let loaded = false;
  function loadAnalytics() {
    if (loaded) return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function gtag() { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', measurementId, {
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
      cookie_expires: 30 * 24 * 60 * 60
    });
    const tag = document.createElement('script');
    tag.async = true;
    tag.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId)}`;
    document.head.append(tag);
  }

  const controls = document.createElement('section');
  controls.className = 'analytics-consent';
  controls.setAttribute('aria-label', copy.label);
  controls.hidden = true;
  controls.innerHTML = `
    <div class="analytics-consent__copy">
      <h2>${copy.title}</h2>
      <p>${copy.description}</p>
      <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">${copy.learn} ↗</a>
    </div>
    <div class="analytics-consent__actions">
      <button type="button" data-choice="accepted">${copy.accept}</button>
      <button type="button" data-choice="rejected">${copy.reject}</button>
    </div>`;
  const reopen = document.createElement('button');
  reopen.type = 'button';
  reopen.className = 'analytics-preferences';
  reopen.textContent = copy.settings;
  reopen.setAttribute('aria-label', copy.settings);
  document.body.append(controls, reopen);

  function saveChoice(value) {
    choice = value;
    try {
      localStorage.setItem(key, value);
    } catch {
      try { sessionStorage.setItem(key, value); } catch { /* Apply the choice for this page view. */ }
    }
    controls.hidden = true;
    reopen.hidden = false;
    if (value === 'accepted') {
      loadAnalytics();
    } else if (loaded) {
      clearAnalyticsCookies();
      window.location.reload();
    }
  }

  function clearAnalyticsCookies() {
    const names = document.cookie.split(';').map((part) => part.trim().split('=')[0]);
    for (const name of names.filter((item) => item === '_ga' || item.startsWith('_ga_'))) {
      document.cookie = `${name}=; Max-Age=0; path=/`;
      document.cookie = `${name}=; Max-Age=0; path=/; domain=${location.hostname}`;
      document.cookie = `${name}=; Max-Age=0; path=/; domain=.${location.hostname}`;
    }
  }

  controls.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-choice]');
    if (button) saveChoice(button.dataset.choice);
  });
  reopen.addEventListener('click', () => {
    controls.hidden = false;
    reopen.hidden = true;
    controls.querySelector('[data-choice="accepted"]').focus();
  });

  if (choice === 'accepted') {
    loadAnalytics();
    reopen.hidden = false;
  } else if (choice === 'rejected') {
    reopen.hidden = false;
  } else {
    controls.hidden = false;
    reopen.hidden = true;
  }
})();
