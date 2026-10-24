// Local visual-service regression checks. No analytics traffic leaves this test.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { mkdirSync, writeFileSync } = require('node:fs');

async function checkEngineeringRendering(browser, origin, output = 'output/playwright/engineering-photorealistic') {
  mkdirSync(output, { recursive: true });
  const results = [];
  const assertPhotoDensity = async image => {
    await image.scrollIntoViewIfNeeded();
    await image.page().waitForFunction(element => !element.hasAttribute('data-piskor-src'), await image.elementHandle());
    const density = await image.evaluate(async element => {
      // Restoring srcset is synchronous, but native candidate selection is not.
      // Wait for the real image rather than decoding an empty/stale currentSrc.
      await element.decode();
      const bitmap = new Image();
      bitmap.src = element.currentSrc;
      await bitmap.decode();
      const box = element.getBoundingClientRect();
      const ratio = Number(element.getAttribute('width')) / Number(element.getAttribute('height'));
      const native = Math.max(...element.srcset.split(',').map(entry => Number(entry.trim().split(/\s+/).pop().replace(/w$/, ''))));
      return { source: element.currentSrc, selected: bitmap.naturalWidth,
        required: Math.min(native, Math.max(box.width, box.height * ratio) * devicePixelRatio) };
    });
    assert.ok(density.selected + 1 >= density.required, JSON.stringify(density));
    return density;
  };
  for (const language of ['uk', 'en']) {
    const route = (language === 'en' ? '/en' : '') + '/engineering-automation/';
    // Late story CSS used to expose the video's intrinsic 848px width. Mobile
    // Chrome expanded its layout viewport before the stylesheet arrived, then
    // repainted the hero and consent banner. Check the first paint, not just
    // the settled layout after all styles have loaded.
    const coldContext = await browser.newContext({ viewport: { width: 412, height: 823 }, isMobile: true, deviceScaleFactor: 1.75 });
    try {
      const cold = await coldContext.newPage();
      const lateStyles = [];
      const prematurePhotos = [];
      const externalControllers = [];
      cold.on('request', request => {
        if (/\/assets\/(?:responsive\/case-media\/)?portfolio\//.test(request.url())) prematurePhotos.push(request.url());
        if (/\/(?:engineering-automation|agent-tools)\.js(?:\?|$)/.test(request.url())) externalControllers.push(request.url());
      });
      await coldContext.route('**/engineering-story.css*', async request => {
        lateStyles.push(request.request().url());
        await request.abort();
      });
      await cold.addInitScript(() => {
        window.__engineeringFirstPaint = [];
        new PerformanceObserver(list => {
          for (const entry of list.getEntries()) window.__engineeringFirstPaint.push({
            name: entry.name, width: innerWidth, scroll: document.documentElement.scrollWidth
          });
        }).observe({ type: 'paint', buffered: true });
      });
      await cold.goto(origin + route);
      await cold.waitForFunction(() => window.__engineeringFirstPaint.length > 0);
      const firstPaint = await cold.evaluate(() => window.__engineeringFirstPaint);
      assert.deepEqual(lateStyles, [], 'All story geometry must be available in the initial HTML');
      assert.equal(await cold.locator('link[href*="engineering-story.css"]').count(), 0);
      assert.ok(firstPaint.every(entry => entry.width === 412 && entry.scroll <= 412), JSON.stringify(firstPaint));
      assert.ok(await cold.locator('picture[data-piskor-deferred-media] img[data-engineering-photo]').count() > 0);
      assert.deepEqual(prematurePhotos, [], 'Below-fold project photos must not compete with the initial frame');
      assert.deepEqual(externalControllers, [], 'Approved DOM-ready controllers must not add initial requests');
      results.push({ language, firstPaint, noDeferredStoryGeometry: true, prematurePhotos, externalControllers });
    } finally { await coldContext.close(); }
    for (const width of [390, 700, 701, 1440]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 2 });
      const page = await context.newPage();
      const errors = [], analytics = [], photoDensity = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('response', response => { if (response.status() >= 400) errors.push(response.status() + ' ' + response.url()); });
      await context.route(/https:\/\/(?:www\.)?(?:googletagmanager\.com|google-analytics\.com)/, async request => {
        analytics.push(request.request().url());
        await request.fulfill({ contentType: 'application/javascript', body: '' });
      });
      try {
        assert.equal((await page.goto(origin + route)).status(), 200);
        assert.equal(await page.locator('html').getAttribute('lang'), language);
        assert.equal(await page.locator('main h1').count(), 1);
        const banner = page.locator('.analytics-consent');
        assert.ok(await banner.isVisible());
        assert.deepEqual(analytics, []);
        await page.getByRole('button', { name: language === 'en' ? 'Reject analytics' : 'Відхилити аналітику', exact: true }).click();
        await page.waitForFunction(() => document.querySelector('[data-engineering-demo]').dataset.ready === 'true');
        const hero = page.locator('[data-demo-frame="living-day"] img');
        await hero.evaluate(image => image.decode());
        assert.equal(await hero.getAttribute('fetchpriority'), 'high');
        assert.equal(await hero.getAttribute('loading'), 'eager');
        const source = await hero.evaluate(image => ({ source: image.currentSrc, width: image.clientWidth, height: image.clientHeight }));
        const demo = page.locator('[data-engineering-demo]');
        assert.equal(await demo.locator('.engineering-demo-note').count(), 0);
        const systemMedia = [];
        const waitFrame = async frame => {
          await page.waitForFunction(id => {
            const demo = document.querySelector('[data-engineering-demo]');
            return demo.dataset.currentFrame === id && !demo.querySelector('.is-retiring,.is-preparing');
          }, frame);
          assert.equal(await demo.locator('.engineering-demo-frame:visible').count(), 1);
          const image = demo.locator('[data-demo-frame="' + frame + '"] img');
          await image.evaluate(image => image.decode());
          assert.ok((await image.getAttribute('src')).includes('/' + frame + '-'));
          assert.equal(await image.evaluate(image => getComputedStyle(image).objectFit), 'contain');
          assert.equal(await demo.locator('.engineering-mode-controls:visible').count(), 1);
          assert.equal(await demo.locator('.engineering-demo-loading').isVisible(), false);
          return image;
        };
        assert.equal(await demo.locator('svg,.engineering-room-signal,.engineering-room-dim,.engineering-room-glow,.engineering-demo-curtains').count(), 0);
        for (const [system, states] of [
          ['lighting', [['evening', 'living-evening'], ['day', 'living-day']]],
          ['shading', [['closed', 'living-curtains-closed'], ['open', 'living-day']]],
          ['heating', [['eco', 'heating-detail'], ['comfort', 'heating-detail']]],
          ['doors', [['open', 'living-door-open'], ['closed', 'living-day']]],
          ['gates', [['open', 'gate-open'], ['closed', 'gate-closed']]]
        ]) {
          await page.locator('label[for="system-' + system + '"]').click();
          for (const [state, frame] of states) {
            await page.locator('label[for="state-' + system + '-' + state + '"]').click();
            const image = await waitFrame(frame);
            if (system === 'heating') {
              const target = state === 'eco' ? '18' : '22';
              assert.equal(await demo.locator('[data-thermostat]').textContent(), target + '°');
              assert.equal(await demo.locator('[data-temperature-value]').textContent(), target + '°C');
            }
            systemMedia.push({ system, state, frame, source: await image.evaluate(image => image.currentSrc), alt: await image.getAttribute('alt') });
            if ([390, 1440].includes(width)) await demo.screenshot({ path: `${output}/${language}-${width}-${system}-${state}.png` });
          }
          if (system === 'heating') {
            await demo.locator('#heating-target').focus();
            await demo.locator('#heating-target').press('ArrowRight');
            assert.equal(await demo.locator('[data-thermostat]').textContent(), '23°');
            assert.equal(await demo.locator('[data-temperature-value]').textContent(), '23°C');
            const geometry = await demo.evaluate(element => {
              const stage = element.querySelector('.engineering-demo-stage').getBoundingClientRect();
              const screen = element.querySelector('.engineering-thermostat-screen').getBoundingClientRect();
              return { x: (screen.x - stage.x) / stage.width, y: (screen.y - stage.y) / stage.height, width: screen.width / stage.width, height: screen.height / stage.height };
            });
            assert.ok(Math.abs(geometry.x - .586) < .001 && Math.abs(geometry.y - .272) < .001);
            assert.ok(Math.abs(geometry.width - .279) < .001 && Math.abs(geometry.height - .411) < .001);
            if ([390, 1440].includes(width)) await demo.screenshot({ path: `${output}/${language}-${width}-thermostat-live.png` });
          }
        }
        await page.locator('#system-gates').press('ArrowLeft');
        assert.ok(await page.locator('#system-doors').isChecked());
        await waitFrame('living-day');
        await page.locator('label[for="system-lighting"]').click();
        await waitFrame('living-day');
        assert.equal(await page.locator('.engineering-scene-panel:visible').count(), 1);
        for (const mode of ['morning', 'evening', 'away']) {
          await page.locator('label[for="mode-' + mode + '"]').click();
          assert.ok(await page.locator('#mode-' + mode).isChecked());
          assert.equal(await page.locator('.engineering-scene-panel:visible').count(), 1);
          assert.ok(await page.locator('#scene-' + mode).isVisible());
          photoDensity.push(await assertPhotoDensity(page.locator('#scene-' + mode + ' img')));
        }
        await page.locator('#mode-away').press('ArrowLeft');
        assert.ok(await page.locator('#mode-evening').isChecked());
        for (const image of await page.locator('main img:visible').all()) {
          await image.scrollIntoViewIfNeeded();
          assert.ok(await image.getAttribute('alt'));
          if (await image.getAttribute('data-engineering-photo') !== null) photoDensity.push(await assertPhotoDensity(image));
          else await image.evaluate(image => image.decode());
        }
        const areaMedia = [];
        for (const area of await page.locator('.engineering-area').all()) {
          if (!(await area.evaluate(element => element.open))) await area.locator('summary').click();
          assert.equal(await page.locator('.engineering-area[open]').count(), 1);
          const image = area.locator('img');
          photoDensity.push(await assertPhotoDensity(image));
          areaMedia.push({ title: await area.locator('summary').textContent(), source: await image.getAttribute('src'), alt: await image.getAttribute('alt') });
        }
        assert.ok(areaMedia[4].source.includes('/garden-'));
        assert.ok(areaMedia.every(item => !item.source.includes('/terrace-') && item.alt));
        await page.locator('.engineering-area').first().locator('summary').click();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert.equal(await page.locator('.engineering-area').count(), 6);
        const video = page.locator('video');
        await video.scrollIntoViewIfNeeded();
        await video.evaluate(async element => { element.load(); await element.play(); });
        await page.waitForFunction(() => document.querySelector('video').currentTime > 0.1);
        const videoState = await video.evaluate(element => { element.pause(); element.currentTime = 5; return { duration: element.duration, controls: element.controls, autoplay: element.autoplay }; });
        assert.ok(videoState.duration > 5);
        assert.ok(videoState.controls && !videoState.autoplay);
        await page.waitForFunction(() => {
          const video = document.querySelector('video');
          return !video.seeking && Math.abs(video.currentTime - 5) < 0.1;
        });
        if ([390, 1440].includes(width)) {
          await page.locator('#automation-areas').screenshot({ path: `${output}/${language}-${width}-areas.png` });
          await page.locator('#lighting-in-motion').screenshot({ path: `${output}/${language}-${width}-video.png` });
        }
        const links = await page.locator('.engineering-project-link').evaluateAll(elements => elements.map(element => element.getAttribute('href')));
        assert.ok(links.every(link => language === 'en' ? link.startsWith('/en/portfolio/') : link.startsWith('/portfolio/')));
        for (const href of await page.locator('main a[href^="#"]').evaluateAll(elements => elements.map(element => element.getAttribute('href')))) {
          assert.equal(await page.locator(href).count(), 1);
        }
        await page.locator('#daily-scenarios').scrollIntoViewIfNeeded();
        if ([390, 1440].includes(width)) await page.screenshot({ path: `${output}/${language}-${width}-scenarios.png` });
        await page.evaluate(() => scrollTo(0, 0));
        if ([390, 1440].includes(width)) await page.screenshot({ path: `${output}/${language}-${width}-hero.png` });
        assert.deepEqual(errors, []);
        assert.deepEqual(analytics, []);
        if (width === 390) {
          const settings = language === 'en' ? 'Analytics preferences' : 'Налаштування аналітики';
          const allow = language === 'en' ? 'Allow analytics' : 'Дозволити аналітику';
          const reject = language === 'en' ? 'Reject analytics' : 'Відхилити аналітику';
          await page.reload();
          assert.deepEqual(analytics, [], 'Saved denial must survive a warm visit');
          await page.getByRole('button', { name: settings, exact: true }).click();
          await Promise.all([
            page.waitForRequest(request => request.url().includes('googletagmanager.com/gtag/js')),
            page.getByRole('button', { name: allow, exact: true }).click()
          ]);
          await page.reload();
          await page.waitForFunction(() => document.querySelector('script[src*="googletagmanager"]'));
          await page.getByRole('button', { name: settings, exact: true }).click();
          await Promise.all([page.waitForEvent('load'), page.getByRole('button', { name: reject, exact: true }).click()]);
          assert.equal(await page.locator('script[src*="googletagmanager"]').count(), 0);
        }
        results.push({ language, width, source, systemMedia, areaMedia, photoDensity, interactiveControls: true, video: videoState, errors });
      } finally { await context.close(); }
    }
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    try {
      await page.goto(origin + route);
      const demo = page.locator('[data-engineering-demo]');
      assert.equal(await page.locator('.engineering-system-picker').getAttribute('disabled'), null);
      for (const [system, state, frame] of [
        ['lighting', 'evening', 'living-evening'], ['shading', 'closed', 'living-curtains-closed'],
        ['heating', 'eco', 'heating-detail'], ['doors', 'open', 'living-door-open'], ['gates', 'open', 'gate-open']
      ]) {
        await page.locator('label[for="system-' + system + '"]').click();
        await page.locator('label[for="state-' + system + '-' + state + '"]').click();
        assert.equal(await demo.locator('.engineering-demo-frame:visible').count(), 1);
        assert.ok(await demo.locator('[data-demo-frame="' + frame + '"]').isVisible());
        assert.equal(await demo.locator('.engineering-mode-controls:visible').count(), 1);
        if (system === 'heating') {
          assert.ok(await demo.locator('.thermostat-eco').isVisible());
          assert.equal(await demo.locator('.thermostat-comfort').isVisible(), false);
          assert.equal(await demo.locator('#heating-target').isVisible(), false);
        }
      }
      await page.locator('label[for="mode-evening"]').click();
      assert.ok(await page.locator('#scene-evening').isVisible());
      assert.equal(await page.locator('.engineering-scene-panel:visible').count(), 1);
      assert.ok(await page.locator('video[controls]').isVisible());
      const nativePhotos = await page.locator('img[data-engineering-photo]:visible').all();
      assert.ok(nativePhotos.length > 0);
      for (const image of nativePhotos) {
        await image.scrollIntoViewIfNeeded();
        await image.evaluate(image => image.decode());
        assert.equal(await image.getAttribute('data-piskor-src'), null);
        assert.ok((await image.evaluate(image => image.currentSrc)).startsWith(origin + '/assets/'));
      }
      results.push({ language, noJavaScript: true, nativeSceneSwitching: true, nativePhotos: nativePhotos.length });
    } finally { await context.close(); }
    const reducedContext = await browser.newContext({ reducedMotion: 'reduce' });
    try {
      const reduced = await reducedContext.newPage();
      await reduced.goto(origin + route);
      await reduced.getByRole('button', { name: language === 'en' ? 'Reject analytics' : 'Відхилити аналітику', exact: true }).click();
      await reduced.locator('label[for="state-lighting-evening"]').click();
      await reduced.waitForFunction(() => document.querySelector('[data-engineering-demo]').dataset.currentFrame === 'living-evening');
      assert.equal(await reduced.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior), 'auto');
      assert.equal(await reduced.locator('.engineering-demo-frame.is-active').evaluate(element => getComputedStyle(element).transitionDuration), '0s');
      assert.ok(await reduced.locator('[data-demo-frame="living-evening"]').isVisible());
      results.push({ language, reducedMotion: true, workingControls: true });
    } finally { await reducedContext.close(); }
    const delayedContext = await browser.newContext({ viewport: { width: 390, height: 900 } });
    let releaseImage;
    const imageGate = new Promise(resolve => { releaseImage = resolve; });
    const eveningResource = /\/engineering-scene\/(?:engineering-demo\/)?living-evening-/;
    await delayedContext.route(eveningResource, async request => {
      await imageGate;
      await request.continue();
    });
    try {
      const delayed = await delayedContext.newPage();
      await delayed.goto(origin + route);
      await delayed.getByRole('button', { name: language === 'en' ? 'Reject analytics' : 'Відхилити аналітику', exact: true }).click();
      const imageRequest = delayed.waitForRequest(eveningResource);
      await delayed.locator('label[for="state-lighting-evening"]').click();
      await delayed.waitForFunction(() => document.querySelector('.engineering-demo-stage').getAttribute('aria-busy') === 'true');
      await imageRequest;
      assert.equal(await delayed.locator('[data-engineering-demo]').getAttribute('data-current-frame'), 'living-day');
      assert.ok(await delayed.locator('[data-demo-frame="living-day"]').isVisible());
      // A late response must not overwrite the user's more recent choice.
      await delayed.locator('label[for="state-lighting-day"]').click();
      releaseImage();
      await delayed.waitForLoadState('networkidle');
      assert.equal(await delayed.locator('[data-engineering-demo]').getAttribute('data-current-frame'), 'living-day');
      assert.equal(await delayed.locator('.engineering-demo-loading').isVisible(), false);
      results.push({ language, delayedImageKeepsCurrentFrame: true, latestChoiceWins: true });
    } finally { releaseImage(); await delayedContext.close(); }
    const failedContext = await browser.newContext();
    await failedContext.route(eveningResource, request => request.abort());
    try {
      const failed = await failedContext.newPage();
      await failed.goto(origin + route);
      await failed.getByRole('button', { name: language === 'en' ? 'Reject analytics' : 'Відхилити аналітику', exact: true }).click();
      await failed.locator('label[for="state-lighting-evening"]').click();
      await failed.waitForFunction(() => {
        const demo = document.querySelector('[data-engineering-demo]');
        return demo.querySelector('.engineering-demo-loading').textContent === demo.dataset.errorLabel;
      });
      assert.equal(await failed.locator('[data-engineering-demo]').getAttribute('data-current-frame'), 'living-day');
      assert.ok(await failed.locator('[data-demo-frame="living-day"]').isVisible());
      await failed.locator('label[for="state-lighting-day"]').click();
      assert.equal(await failed.locator('.engineering-demo-loading').isVisible(), false);
      results.push({ language, failedImageKeepsCurrentFrame: true, errorAnnounced: true });
    } finally { await failedContext.close(); }
  }
  writeFileSync(output + '/checks.json', JSON.stringify(results, null, 2));
  return results;
}
module.exports = checkEngineeringRendering;
if (require.main === module) (async () => {
  const browser = await chromium.launch({ headless: true });
  try { console.log(JSON.stringify(await checkEngineeringRendering(browser, process.argv[2] || 'http://127.0.0.1:4195', process.argv[3]), null, 2)); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
