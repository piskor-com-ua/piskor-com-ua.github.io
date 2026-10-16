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
    const context = await browser.newContext();
    const errors = [];
    page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => { if (response.status() >= 400) errors.push(response.status() + ' ' + response.url()); });
    const checkGrid = vm.runInThisContext('(' + readFileSync('scripts/check-portfolio-grid.js', 'utf8') + ')');
    const matrix = await checkGrid(page, origin);
    mkdirSync('output/browser', { recursive: true });
    for (const language of ['uk', 'en']) {
      const prefix = language === 'en' ? '/en' : '';
      await page.goto(origin + prefix + '/portfolio/');
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
    writeFileSync('output/browser/matrix.json', JSON.stringify({ matrix, errors }, null, 2));
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
