/** Actual bilingual home navigation with and without JavaScript. */
'use strict';

const assert = require('node:assert/strict');
const { mkdirSync, writeFileSync } = require('node:fs');
const path = require('node:path');

module.exports = async function checkHomeRendering(browser, origin, output = 'output/browser') {
  mkdirSync(output, { recursive: true });
  const results = [];
  for (const javascript of [false, true]) {
    for (const locale of ['uk', 'en']) {
      for (const width of [390, 1440]) {
        const context = await browser.newContext({
          javaScriptEnabled: javascript,
          viewport: { width, height: 900 },
          deviceScaleFactor: 1,
        });
        const page = await context.newPage();
        const errors = [], storyRequests = [];
        let initialStoryRequests = null, automationBiodynamic = null;
        page.on('request', request => {
          const pathname = new URL(request.url()).pathname;
          if (/^\/assets\/(?:v2\/|automation\/|(?:interior|house)-concept\.webp)/.test(pathname)) storyRequests.push(pathname);
        });
        page.on('pageerror', error => errors.push(error.message));
        page.on('response', response => { if (response.status() >= 400) errors.push(response.status() + ' ' + response.url()); });
        const route = locale === 'uk' ? '/' : '/en/';
        const opposite = locale === 'uk' ? 'en' : 'uk';
        const oppositePath = opposite === 'uk' ? '/' : '/en/';
        const label = (javascript ? 'enhanced' : 'native') + '-' + locale + '-' + width;
        try {
          // Pause only the enhancement script in this test, then identify the
          // parsed heading. Its identity must survive normal script startup.
          let releaseEnhancement;
          if (javascript) {
            const gate = new Promise(resolve => { releaseEnhancement = resolve; });
            await page.route(/\/app\.js(?:\?|$)/, async request => {
              await gate;
              await request.continue();
            });
          }
          const response = await page.goto(origin + route, { waitUntil: javascript ? 'commit' : 'load' });
          assert.equal(response.status(), 200, label);
          const source = await response.text();
          assert.match(source, /<h1 id="hero-title">/, label + ': heading must be in delivered HTML');
          assert.ok(source.includes('data-home-render="' + locale + '"'));
          await page.locator('#hero-title').waitFor();
          if (javascript) {
            await page.evaluate(() => { window.__parsedHomeHeading = document.querySelector('#hero-title'); });
            releaseEnhancement();
            await page.waitForLoadState('load');
            assert.ok(await page.evaluate(() => window.__parsedHomeHeading === document.querySelector('#hero-title')), label + ': first enhancement replaced SSR content');
          }
          assert.equal(await page.locator('html').getAttribute('lang'), locale);
          assert.match(await page.locator('meta[name="robots"]').getAttribute('content'), /noindex/);
          assert.equal(await page.locator('[data-lang="' + locale + '"]').getAttribute('aria-current'), 'page');
          assert.equal(await page.locator('[data-lang="' + opposite + '"]').getAttribute('href'), oppositePath);
          assert.ok(await page.locator('#hero-title').isVisible());
          assert.equal(await page.locator('.menu-button').getAttribute('aria-expanded'), javascript ? 'false' : null);
          assert.ok(await page.locator('#architecture-services h2').textContent());
          assert.ok(await page.locator('#contact a[href="tel:+380974781005"]').isVisible());
          assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), label + ': horizontal overflow');
          const hero = page.locator('.hero-picture img');
          await hero.evaluate(image => image.decode());
          const media = await hero.evaluate(image => ({
            src: image.currentSrc,
            width: image.naturalWidth,
            height: image.naturalHeight,
            priority: image.fetchPriority,
            loading: image.loading,
            picture: image.parentElement.tagName === 'PICTURE',
          }));
          assert.ok(media.width > 0 && media.height > 0, label + ': missing hero');
          assert.equal(media.priority, 'high');
          assert.notEqual(media.loading, 'lazy');
          assert.ok(media.picture, label + ': responsive hero picture missing');
          await page.screenshot({ path: path.join(output, 'home-' + label + '.jpg'), type: 'jpeg' });
          if (javascript) {
            initialStoryRequests = [...storyRequests];
            assert.deepEqual(initialStoryRequests, [], label + ': offscreen story images competed with first paint');
            assert.ok(await page.locator('[data-consent-inline]').count(), label + ': first-visit consent controller missing');
            const reject = page.getByRole('button', { name: locale === 'uk' ? 'Відхилити аналітику' : 'Reject analytics', exact: true });
            assert.ok(await reject.isVisible(), label + ': first-visit consent hidden');
            await reject.click();
            await page.locator('[data-lang="' + opposite + '"]').click();
            assert.equal(new URL(page.url()).pathname, oppositePath);
            assert.equal(await page.locator('html').getAttribute('lang'), opposite);
            await hero.evaluate(image => image.decode());
            assert.equal(await hero.evaluate(image => image.currentSrc), media.src, label + ': locale switch changed prepared media');
            assert.ok((await hero.getAttribute('alt')).includes(opposite === 'uk' ? 'Концептуальний' : 'Concept house'));
            await page.locator('[data-lang="' + locale + '"]').click();
            assert.deepEqual(storyRequests, [], label + ': locale switch loaded offscreen story media');
            // A real scroll begins loading before the story enters the viewport.
            await page.evaluate(() => {
              const top = scrollY + document.querySelector('.story').getBoundingClientRect().top;
              window.scrollTo({ top: top - innerHeight - 300, behavior: 'instant' });
            });
            await page.waitForFunction(() => document.querySelector('.stage-visual .current').getAttribute('src')?.includes('/model.webp'));
            assert.ok(await page.locator('.story').evaluate(story => story.getBoundingClientRect().top > innerHeight), label + ': photo should start before the story is visible');
            await page.locator('.stage-visual .current').evaluate(image => image.decode());
          }
          if (width === 390) {
            await page.locator('.menu-button').click();
            await page.locator('#mobile-menu').waitFor({ state: 'visible' });
            if (javascript) {
              assert.equal(await page.locator('.menu-button').getAttribute('aria-expanded'), 'true');
              assert.equal(await page.locator('#mobile-menu').evaluate(menu => menu.inert), false);
            } else {
              assert.equal(await page.locator('.menu-button').getAttribute('aria-expanded'), null, label + ': native menu must not expose a false collapsed state');
            }
            await page.locator('#mobile-menu a[href="#our-approach"]').click();
            assert.equal(new URL(page.url()).hash, '#our-approach');
            await page.locator('#mobile-menu').waitFor({ state: 'hidden' });
          }
          if (javascript) {
            await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
            await page.locator('.hero-bottom a[href="#design-process"]').click();
            assert.equal((await page.locator('.chapter-copy h2').textContent()).trim(), locale === 'uk' ? 'Починаємо з контексту.' : 'Start with the context.');
            await page.locator('.stage-visual .current').evaluate(image => image.decode());
            assert.ok(storyRequests.some(url => url.endsWith('/model.webp')), label + ': entering story did not load its image');
            await page.locator('.next-beat').click();
            assert.equal((await page.locator('.chapter-copy h2').textContent()).trim(), locale === 'uk' ? 'Простір починається з вас.' : 'Space begins with you.');
            await page.locator('.stage-details').click();
            assert.ok(await page.locator('dialog.detail[open]').count());
            await page.keyboard.press('Escape');
            assert.equal(await page.locator('dialog.detail[open]').count(), 0);
            assert.ok(await page.locator('.stage-details').evaluate(button => button === document.activeElement));
            await page.locator('[data-chapter="2"]').click();
            await page.waitForFunction(() => document.querySelector('.stage-visual .current').getAttribute('src')?.includes('interior-concept.webp'));
            await page.locator('.stage-visual .current').evaluate(image => image.decode());
            assert.ok(storyRequests.some(url => url.endsWith('/interior-concept.webp')), label + ': chapter navigation did not update media');
            await page.locator('[data-chapter="4"]').click();
            if (width === 390) {
              await page.locator('.mobile-automation-trigger').click();
              await page.locator('.mobile-control-sheet[open]').waitFor({ state: 'visible' });
            }
            const biodynamic = page.locator('[data-system="biodynamic"]');
            const currentPhoto = page.locator('.stage-visual .visual-image.current');
            assert.equal(await biodynamic.getAttribute('aria-pressed'), 'false');
            const beforeFilter = await currentPhoto.evaluate(image => getComputedStyle(image).filter);
            await biodynamic.click();
            assert.equal(await biodynamic.getAttribute('aria-pressed'), 'true');
            assert.ok(await page.locator('.story-sticky').evaluate(stage => stage.classList.contains('device-biodynamic')), label + ': lighting class missing');
            // Check the real computed photo treatment after its CSS transition,
            // rather than accepting an ARIA change or class without working CSS.
            await page.waitForFunction(() => getComputedStyle(document.querySelector('.stage-visual .visual-image.current')).filter.includes('sepia(0.22)'));
            const onFilter = await currentPhoto.evaluate(image => getComputedStyle(image).filter);
            await biodynamic.click();
            assert.equal(await biodynamic.getAttribute('aria-pressed'), 'false');
            assert.ok(!(await page.locator('.story-sticky').evaluate(stage => stage.classList.contains('device-biodynamic'))), label + ': lighting class remained active');
            await page.waitForFunction(() => !getComputedStyle(document.querySelector('.stage-visual .visual-image.current')).filter.includes('sepia('));
            const offFilter = await currentPhoto.evaluate(image => getComputedStyle(image).filter);
            automationBiodynamic = { beforeFilter, onFilter, offFilter };
            if (width === 390) {
              await page.locator('.mobile-control-sheet .sheet-close').click();
              await page.locator('.mobile-control-sheet[open]').waitFor({ state: 'hidden' });
            }
          } else {
            const storyHeight = await page.locator('.story').evaluate(story => story.getBoundingClientRect().height);
            assert.ok(storyHeight <= 1800, label + ': frozen interactive scroll area without JavaScript');
            await page.locator('[data-lang="' + opposite + '"]').click();
            assert.equal(new URL(page.url()).pathname, oppositePath);
            assert.equal(await page.locator('html').getAttribute('lang'), opposite);
            assert.ok(await page.locator('#hero-title').isVisible());
          }
          assert.deepEqual(errors, [], label);
          results.push({ route, locale, width, javascript, media, initialStoryRequests, storyRequests, automationBiodynamic, errors });
        } catch (error) {
          await page.screenshot({ path: path.join(output, 'home-failure-' + label + '.jpg'), type: 'jpeg' });
          const diagnostics = await page.evaluate(() => {
            const menu = document.querySelector('#mobile-menu');
            const trigger = document.querySelector('.menu-button');
            if (!menu) return { hash: location.hash, menu: null };
            const style = getComputedStyle(menu);
            return {
              hash: location.hash, target: menu.matches(':target'), inert: menu.inert,
              triggerHref: trigger?.getAttribute('href'), expanded: trigger?.getAttribute('aria-expanded'),
              classes: menu.className,
              style: { display: style.display, visibility: style.visibility, opacity: style.opacity },
              box: menu.getBoundingClientRect().toJSON(),
              hero: document.querySelector('.hero-picture img')?.currentSrc,
            };
          }).catch(() => null);
          writeFileSync(path.join(output, 'home-failure-' + label + '.json'), JSON.stringify({ route, locale, width, javascript, url: page.url(), errors, error: error.message, diagnostics }, null, 2));
          throw error;
        } finally {
          await context.close();
        }
      }
    }
  }
  for (const locale of ['uk', 'en']) {
    for (const reducedMotion of ['reduce', 'no-preference']) {
      const context = await browser.newContext({ viewport: { width: 390, height: 900 }, reducedMotion });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const route = (locale === 'uk' ? '/' : '/en/') + '#design-process';
      try {
        await page.goto(origin + route);
        await page.waitForFunction(() => document.querySelector('.stage-visual .current').getAttribute('src')?.includes('/model.webp'));
        await page.locator('.stage-visual .current').evaluate(image => image.decode());
        const reject = page.getByRole('button', { name: locale === 'uk' ? 'Відхилити аналітику' : 'Reject analytics', exact: true });
        if (await reject.isVisible()) await reject.click();
        await page.locator('[data-chapter="2"]').click();
        await page.waitForFunction(() => document.querySelector('.stage-visual .current').getAttribute('src')?.includes('interior-concept.webp'));
        await page.locator('.stage-visual .current').evaluate(image => image.decode());
        const opposite = locale === 'uk' ? 'en' : 'uk';
        await page.locator('[data-lang="' + opposite + '"]').click();
        assert.equal(await page.locator('html').getAttribute('lang'), opposite);
        await page.locator('.hero-bottom a[href="#design-process"]').click();
        await page.waitForFunction(() => document.querySelector('.stage-visual .current').getAttribute('src')?.includes('/model.webp'));
        await page.locator('.stage-visual .current').evaluate(image => image.decode());
        assert.ok((await page.locator('.chapter-copy h2').textContent()).includes(opposite === 'uk' ? 'контексту' : 'context'));
        assert.deepEqual(errors, []);
        results.push({ route, locale, width: 390, javascript: true, reducedMotion, hashEntry: true, errors });
      } finally {
        await context.close();
      }
    }
  }
  for (const locale of ['uk', 'en']) {
    const context = await browser.newContext({ viewport: { width: 390, height: 900 } });
    const page = await context.newPage();
    const requests = [];
    page.on('request', request => {
      const pathname = new URL(request.url()).pathname;
      if (/^\/assets\/(?:v2\/|automation\/|house-concept\.webp)/.test(pathname)) requests.push(pathname);
    });
    try {
      const route = (locale === 'uk' ? '/' : '/en/') + '#contact';
      await page.goto(origin + route);
      await page.locator('.hero-picture img').evaluate(image => image.decode());
      assert.deepEqual(requests, [], locale + ': skipping directly to contacts loaded hidden story media');
      results.push({ route, locale, width: 390, javascript: true, hashEntry: 'contact', storyRequests: requests });
    } finally {
      await context.close();
    }
  }
  writeFileSync(path.join(output, 'home-rendering.json'), JSON.stringify(results, null, 2));
  return results;
};
