// Functional delivery only; this helper produces no performance/PSI evidence.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { mkdirSync, writeFileSync } = require('node:fs');
const path = require('node:path');

module.exports = async function checkCompatibilityPages(browser, origin, output = 'output/browser') {
  const mappings = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c',
    "import sys,json;sys.path.insert(0,'scripts');from compatibility_pages import COMPATIBILITY_ROUTES;print(json.dumps(COMPATIBILITY_ROUTES))",
  ], { encoding: 'utf8' }));
  const obsolete = ['lighting-baseline', 'dimming-and-reset', 'lighting-automation-scenarios'];
  const results = [];
  for (const [route, canonical] of Object.entries(mappings)) {
    const locale = route.startsWith('/en/') ? 'en' : 'uk';
    const opposite = locale === 'en' ? 'uk' : 'en';
    const oppositePath = locale === 'en' ? canonical.replace(/^\/en/, '') : '/en' + canonical;
    for (const width of [390, 1440]) for (const javascript of [true, false]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, javaScriptEnabled: javascript });
      const page = await context.newPage();
      const documents = [], errors = [];
      page.on('request', request => { if (request.resourceType() === 'document') documents.push(request.url()); });
      page.on('pageerror', error => errors.push(error.message));
      page.on('response', response => { if (response.status() >= 400) errors.push(response.status() + ' ' + response.url()); });
      try {
        const query = '?compatibility-check=1';
        const response = await page.goto(origin + route + query + '#' + obsolete[0]);
        assert.equal(response.status(), 200);
        await page.evaluate(() => document.fonts.ready);
        assert.equal(new URL(page.url()).pathname, route, 'Compatibility page navigated away');
        assert.equal(new URL(page.url()).search, query);
        assert.equal(documents.length, 1, 'Compatibility entry loaded another document');
        assert.equal(await page.locator('html').getAttribute('lang'), locale);
        assert.equal(await page.locator('link[rel="canonical"]').getAttribute('href'), 'https://piskor.com.ua' + canonical);
        assert.equal(await page.locator('meta[http-equiv="refresh"]').count(), 0);
        assert.match(await page.locator('meta[name="robots"]').getAttribute('content'), /noindex/);
        assert.equal(await page.locator('script[data-inline-page-critical="agent-tools.js"]').count(), 1);
        assert.equal(await page.locator('script[src^="/agent-tools.js?"]').count(), 0);
        assert.equal(await page.locator('script[src^="/url-compat.js?"]').count(), 1);
        assert.equal(await page.locator('link[rel="ard"]').count(), 1);
        assert.equal(await page.locator('#main h1').count(), 1);
        assert.ok(await page.locator('.case-chapter').count());
        await page.locator('.project-cover img').evaluate(image => image.decode());
        const languageLink = page.locator('.language a[lang="' + opposite + '"]');
        assert.equal(await languageLink.getAttribute('href'), oppositePath);
        const reject = page.getByRole('button', { name: locale === 'uk' ? 'Відхилити аналітику' : 'Reject analytics', exact: true });
        if (await reject.isVisible()) await reject.click();
        if (javascript) {
          for (const fragment of obsolete) {
            await page.evaluate(fragment => { location.hash = fragment; }, fragment);
            await page.waitForFunction(() => location.hash === '#accent-lighting-sequence');
            assert.equal(new URL(page.url()).pathname, route);
            assert.equal(new URL(page.url()).search, query);
          }
          await page.locator('[data-gallery]').first().click();
          assert.ok(await page.locator('dialog.project-lightbox').evaluate(dialog => dialog.open));
          await page.keyboard.press('Escape');
          assert.equal(await page.locator('dialog.project-lightbox').evaluate(dialog => dialog.open), false);
        }
        await page.locator('.project-nav a[href="#contact"]').click();
        assert.equal(new URL(page.url()).hash, '#contact');
        assert.ok(await page.locator('#contact a[href^="tel:"]').count());
        assert.ok(await page.locator('#contact a[href^="https://wa.me/"]').count());
        assert.ok(await page.locator('#contact a[href^="viber:"]').count());
        assert.equal(documents.length, 1, 'Fragment/gallery/contact interaction navigated');
        assert.deepEqual(errors, []);
        await languageLink.click();
        await page.waitForURL(url => url.pathname === oppositePath);
        assert.equal(await page.locator('html').getAttribute('lang'), opposite);
        results.push({ route, canonical, locale, width, javascript, initialDocumentRequests: 1,
          legacyFragments: javascript ? obsolete.length : 0, discoveryPreserved: true,
          nativeWebMCPExecution: 'not-tested-by-this-helper' });
      } finally {
        await context.close();
      }
    }
  }
  mkdirSync(output, { recursive: true });
  writeFileSync(path.join(output, 'compatibility-pages.json'), JSON.stringify(results, null, 2) + '\n');
  return results;
};
