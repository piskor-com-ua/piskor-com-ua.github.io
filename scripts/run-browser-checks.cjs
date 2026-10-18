const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const { readFileSync, mkdirSync, writeFileSync } = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

(async () => {
  const origin = 'http://127.0.0.1:4176';
  const server = spawn('python3', ['-m', 'http.server', '4176', '--bind', '127.0.0.1', '--directory', '_site'], { stdio: 'ignore' });
  let browser, page;
  mkdirSync('output/browser', { recursive: true });
  try {
    for (let attempt = 0; attempt < 30; attempt++) {
      try { await fetch(origin); break; } catch {
        if (attempt === 29) throw Error('Preview server did not start.');
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    }
    browser = await chromium.launch({ headless: true });
    const preloadChecks = [];
    for (const [route, width, deviceScaleFactor] of [
      ['/portfolio/', 390, 1], ['/portfolio/', 412, 1.75], ['/en/portfolio/', 390, 2],
      ['/portfolio/2025/', 700, 2], ['/en/portfolio/2026/', 701, 1], ['/portfolio/', 1440, 2]
    ]) {
      const probeContext = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor });
      const probe = await probeContext.newPage();
      const requests = [];
      probe.on('request', request => requests.push(request.url()));
      await probe.goto(origin + route);
      await probe.locator('.portfolio-card-cover').first().evaluate(image => image.decode());
      const result = await probe.locator('.portfolio-card-cover').first().evaluate(image => ({
        src: image.currentSrc,
        entries: performance.getEntriesByName(image.currentSrc).map(entry => entry.initiatorType)
      }));
      assert.equal(requests.filter(url => url === result.src).length, 1, 'Cover fetched more than once: ' + route);
      assert.deepEqual(result.entries, [width <= 700 ? 'link' : 'img'], 'Preload must match picture selection');
      assert.ok(new URL(result.src).pathname.endsWith(width <= 700 ? '.avif' : '.webp'));
      preloadChecks.push({ route, width, deviceScaleFactor, ...result });
      await probeContext.close();
    }
    const context = await browser.newContext();
    const errors = [];
    page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => { if (response.status() >= 400) errors.push(response.status() + ' ' + response.url()); });
    const checkGrid = vm.runInThisContext('(' + readFileSync('scripts/check-portfolio-grid.js', 'utf8') + ')');
    const matrix = await checkGrid(page, origin);
    const sampleRoutes = JSON.parse(readFileSync('scripts/release-sample.json'));
    assert.equal(new Set(sampleRoutes).size, 10);
    for (const required of ['/', '/en/', '/portfolio/', '/en/portfolio/']) assert.ok(sampleRoutes.includes(required));
    const releaseSample = [];
    for (const route of sampleRoutes) {
      for (const width of [390, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        const response = await page.goto(origin + route);
        assert.equal(response.status(), 200, route);
        await page.locator('h1').waitFor();
        await page.evaluate(() => document.fonts.ready);
        assert.equal(await page.locator('html').getAttribute('lang'), route.startsWith('/en/') ? 'en' : 'uk');
        assert.match(await page.locator('meta[name="robots"]').getAttribute('content'), /noindex/);
        assert.ok(await page.locator('link[rel="canonical"]').getAttribute('href'));
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), route + ': overflow');
        const image = page.locator('.hero-picture img,.portfolio-card-cover,.project-cover img').first();
        if (await image.count()) await image.evaluate(image => image.decode());
        await page.screenshot({ path: 'output/browser/sample-' + sampleRoutes.indexOf(route) + '-' + width + '.jpg', type: 'jpeg' });
        releaseSample.push({ route, width, status: response.status() });
      }
    }
    mkdirSync('output/browser', { recursive: true });
    for (const language of ['uk', 'en']) {
      const prefix = language === 'en' ? '/en' : '';
      await page.goto(origin + prefix + '/portfolio/');
      for (const width of [390, 1440]) {
        await page.setViewportSize({ width, height: 844 });
        await page.waitForFunction(extension => {
          const image = document.querySelector('.portfolio-card-cover');
          return image.complete && image.naturalWidth > 0 && new URL(image.currentSrc).pathname.endsWith(extension);
        }, width === 390 ? '.avif' : '.webp');
        const image = page.locator('.portfolio-card-cover').first();
        await image.evaluate(image => image.decode());
        assert.ok((await image.evaluate(image => image.currentSrc)).includes(width === 390 ? '.avif?' : '.webp?'));
      }
      await page.setViewportSize({ width: 390, height: 844 });
      const scripts = [];
      page.on('request', request => scripts.push(request.url()));
      const reject = page.getByRole('button', { name: language === 'en' ? 'Reject analytics' : 'Відхилити аналітику', exact: true });
      if (await reject.isVisible()) await reject.click();
      assert.ok(!(await page.locator('script[src*="googletagmanager"]').count()));
      assert.ok(!scripts.some(url => url.includes('/project-catalog.json')));
      await page.locator('.catalog-years a[href="#year-2025"]').click();
      const card = page.locator('a.portfolio-card[data-project-id="zamartynivska-apartment"]');
      const cardName = await card.getByRole('heading').innerText();
      await page.getByRole('link', { name: cardName, exact: true }).click();
      const trigger = page.locator('[data-gallery]').first();
      await trigger.click();
      assert.ok(await page.locator('dialog[open]').count());
      await page.keyboard.press('ArrowRight');
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('dialog[open]').count(), 0);
      assert.ok(await trigger.evaluate(element => element === document.activeElement));
      await page.locator('.project-nav a[href="#contact"]').click();
      assert.ok(page.url().endsWith('#contact'));
      assert.equal(await page.locator('#contact a[href^="tel:"]').count(), 1);
      await page.waitForFunction(() => { const box = document.querySelector('#contact').getBoundingClientRect(); return box.top >= 0 && box.bottom <= innerHeight; });
      await page.screenshot({ path: 'output/browser/contact-' + language + '.jpg', type: 'jpeg' });
      await page.locator('.language a').filter({ hasText: language === 'en' ? 'UA' : 'EN' }).click();
      assert.equal(await page.locator('html').getAttribute('lang'), language === 'en' ? 'uk' : 'en');
    }
    const consentContext = await browser.newContext();
    const consentPage = await consentContext.newPage();
    let tagRequests = 0;
    await consentPage.route('https://www.googletagmanager.com/gtag/js?**', route => {
      tagRequests++;
      return route.fulfill({ contentType: 'application/javascript', body: '/* analytics transport stub */' });
    });
    await consentPage.goto(origin + '/portfolio/');
    assert.equal(await consentPage.locator('script[src*="googletagmanager"]').count(), 0);
    await consentPage.getByRole('button', { name: 'Відхилити аналітику', exact: true }).click();
    await consentPage.reload();
    assert.equal(tagRequests, 0);
    await consentPage.getByRole('button', { name: 'Налаштування аналітики', exact: true }).click();
    await Promise.all([
      consentPage.waitForRequest(request => request.url().startsWith('https://www.googletagmanager.com/gtag/js')),
      consentPage.getByRole('button', { name: 'Дозволити аналітику', exact: true }).click()
    ]);
    assert.equal(await consentPage.locator('script[src*="googletagmanager"]').count(), 1);
    await consentPage.reload();
    await consentPage.waitForFunction(() => document.querySelector('script[src*="googletagmanager"]'));
    await consentPage.getByRole('button', { name: 'Налаштування аналітики', exact: true }).click();
    await Promise.all([
      consentPage.waitForEvent('load'),
      consentPage.getByRole('button', { name: 'Відхилити аналітику', exact: true }).click()
    ]);
    assert.equal(await consentPage.locator('script[src*="googletagmanager"]').count(), 0);
    await consentContext.close();
    assert.deepEqual(errors, []);
    mkdirSync('output/browser', { recursive: true });
    writeFileSync('output/browser/matrix.json', JSON.stringify({ matrix, preloadChecks, releaseSample, errors }, null, 2));
    console.log('Browser validation: ' + matrix.length + ' project/viewport checks; bilingual gallery, focus, language, consent and contacts passed.');
  } catch (error) {
    if (page) {
      await page.screenshot({ path: 'output/browser/failure.jpg', type: 'jpeg' });
      const diagnostics = await page.evaluate(() => ({
        url: location.href, viewport: innerWidth, client: document.documentElement.clientWidth,
        scroll: document.documentElement.scrollWidth,
        elements: [...document.querySelectorAll('body *')].map(element => {
          const box = element.getBoundingClientRect();
          return { tag: element.tagName, id: element.id, className: element.className,
            left: box.left, right: box.right, width: box.width, text: element.textContent.slice(0, 80) };
        }).filter(box => box.width > 0 && (box.right > innerWidth + .5 || box.left < -.5)).slice(0, 25)
      }));
      writeFileSync('output/browser/failure.json', JSON.stringify(diagnostics, null, 2));
      console.error(JSON.stringify(diagnostics, null, 2));
    }
    throw error;
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
