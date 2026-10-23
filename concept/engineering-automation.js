(() => {
  'use strict';
  const demo = document.querySelector('[data-engineering-demo]');
  if (!demo || demo.dataset.ready) return;
  const frames = new Map([...demo.querySelectorAll('[data-demo-frame]')].map(frame => [frame.dataset.demoFrame, frame]));
  const stage = demo.querySelector('.engineering-demo-stage');
  const loading = demo.querySelector('.engineering-demo-loading');
  const loadingLabel = loading.textContent;
  const temperature = demo.querySelector('#heating-target');
  const thermostat = demo.querySelector('[data-thermostat]');
  const temperatureValue = demo.querySelector('[data-temperature-value]');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let active = frames.get('living-day');
  let request = 0;

  function selected() {
    const system = demo.querySelector('input[name="engineering-system"]:checked')?.value;
    const choice = demo.querySelector('input[name="state-' + system + '"]:checked');
    return { system, choice, frame: frames.get(choice?.dataset.frame || (system === 'heating' ? 'heating-detail' : 'living-day')) };
  }

  function setTemperature(value) {
    const target = Math.max(16, Math.min(26, Number(value)));
    temperature.value = String(target);
    temperatureValue.value = target + '°C';
    thermostat.value = target + '°';
    demo.classList.toggle('is-eco', target < 21);
  }

  async function show() {
    const { frame, choice } = selected();
    if (!frame) return;
    const currentRequest = ++request;
    if (choice?.dataset.temperature) setTemperature(choice.dataset.temperature);
    if (frame === active) { loading.hidden = true; stage.removeAttribute('aria-busy'); return; }
    const image = frame.querySelector('img');
    image.loading = 'eager';
    loading.textContent = loadingLabel;
    loading.hidden = false;
    stage.setAttribute('aria-busy', 'true');
    try {
      await image.decode();
      if (currentRequest !== request) return;
      frame.classList.add('is-preparing');
      // Commit the decoded, transparent frame before starting its crossfade.
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      if (currentRequest !== request) { frame.classList.remove('is-preparing'); return; }
      const previous = active;
      previous.classList.remove('is-active');
      previous.classList.add('is-retiring');
      previous.setAttribute('aria-hidden', 'true');
      frame.classList.remove('is-preparing', 'is-retiring');
      frame.classList.add('is-active');
      frame.removeAttribute('aria-hidden');
      active = frame;
      demo.dataset.currentFrame = frame.dataset.demoFrame;
      const retire = () => { if (previous !== active) previous.classList.remove('is-retiring'); };
      if (reduced.matches) retire(); else setTimeout(retire, 450);
    } catch {
      if (currentRequest !== request) return;
      // If a requested image cannot load, retain the previous complete scene.
      loading.textContent = demo.dataset.errorLabel;
    } finally {
      if (currentRequest === request) { stage.removeAttribute('aria-busy'); if (active === frame) loading.hidden = true; }
    }
  }

  demo.querySelectorAll('input[type="radio"]').forEach(input => input.addEventListener('change', show));
  temperature.addEventListener('input', () => {
    demo.querySelectorAll('input[name="state-heating"]').forEach(input => { input.checked = Number(input.dataset.temperature) === Number(temperature.value); });
    setTemperature(temperature.value);
  });
  demo.querySelectorAll('.engineering-state-picker label,.engineering-system-picker label').forEach(label => {
    label.addEventListener('pointerenter', () => {
      const input = document.getElementById(label.htmlFor);
      const target = input.dataset.frame || demo.querySelector('input[name="state-' + input.value + '"]:checked')?.dataset.frame;
      const image = frames.get(target)?.querySelector('img');
      if (image) image.loading = 'eager';
    });
  });
  const initial = selected().frame;
  if (!initial) return;
  frames.forEach(frame => { frame.classList.remove('is-active'); if (frame !== initial) frame.setAttribute('aria-hidden', 'true'); });
  initial.classList.add('is-active');
  active = initial;
  demo.dataset.currentFrame = initial.dataset.demoFrame;
  setTemperature(selected().choice?.dataset.temperature || 22);
  demo.querySelector('.engineering-temperature-adjust').hidden = false;
  demo.classList.add('is-enhanced');
  demo.dataset.ready = 'true';
})();
