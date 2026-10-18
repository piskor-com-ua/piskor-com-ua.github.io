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
        const errors = [], storyRequests = [], controllerRequests = [], fontRequests = [];
        let initialStoryRequests = null, automationBiodynamic = null;
        page.on('request', request => {
          const pathname = new URL(request.url()).pathname;
          if (request.resourceType() === 'font') fontRequests.push(pathname);
          if (/^\/(?:story|automation|app)\.js$/.test(pathname)) controllerRequests.push(pathname);
          if (/^\/assets\/(?:v2\/|automation\/|(?:interior|house)-concept\.webp)/.test(pathname)) storyRequests.push(pathname);
        });
        page.on('pageerror', error => errors.push(error.message));
        page.on('response', response => { if (response.status() >= 400) errors.push(response.status() + ' ' + response.url()); });
        const route = locale === 'uk' ? '/' : '/en/';
        const opposite = locale === 'uk' ? 'en' : 'uk';
        const oppositePath = opposite === 'uk' ? '/' : '/en/';
        const label = (javascript ? 'enhanced' : 'native') + '-' + locale + '-' + width;
        try {
          const response = await page.goto(origin + route, { waitUntil: 'load' });
          assert.equal(response.status(), 200, label);
          const source = await response.text();
          assert.match(source, /<h1 id="hero-title">/, label + ': heading must be in delivered HTML');
          assert.ok(source.includes('data-home-render="' + locale + '"'));
          await page.locator('#hero-title').waitFor();
          if (javascript) {
            await page.evaluate(() => { window.__parsedHomeHeading = document.querySelector('#hero-title'); });
            assert.deepEqual(controllerRequests, [], label + ': inert controller scripts fetched before intent');
            assert.ok(await page.evaluate(() => window.__parsedHomeHeading === document.querySelector('#hero-title')), label + ': first enhancement replaced SSR content');
          }
          assert.equal(await page.locator('html').getAttribute('lang'), locale);
          assert.match(await page.locator('meta[name="robots"]').getAttribute('content'), /noindex/);
          assert.equal(await page.locator('[data-lang="' + locale + '"]').getAttribute('aria-current'), 'page');
          assert.equal(await page.locator('[data-lang="' + opposite + '"]').getAttribute('href'), oppositePath);
          const languageLayout = await page.evaluate(async () => {
            await document.fonts.ready;
            const glyph = element => {
              const range = document.createRange();
              range.selectNodeContents(element);
              return range.getBoundingClientRect().toJSON();
            };
            return [...document.querySelectorAll('#app .language [data-lang]')].map(link => {
              const box = link.getBoundingClientRect().toJSON();
              const text = glyph(link);
              const original = document.createElement('button');
              original.textContent = link.textContent;
              original.tabIndex = -1;
              original.setAttribute('aria-hidden', 'true');
              // Reconstruct the original button's font, padding, minimum box
              // and active underline. Native button text centering supplies
              // the reference missing from old snapshots of control boxes.
              original.style.cssText = 'position:fixed;visibility:hidden;pointer-events:none;'
                + 'left:' + box.x + 'px;top:' + box.y + 'px;margin:0;padding:12px 3px;'
                + 'min-width:' + (innerWidth <= 700 ? '32px' : '0') + ';'
                + 'min-height:' + (innerWidth <= 700 ? '44px' : '0') + ';'
                + 'border-bottom:' + getComputedStyle(link).borderBottom;
              link.parentElement.append(original);
              try {
                return { language: link.dataset.lang, box, text,
                  originalBox: original.getBoundingClientRect().toJSON(), originalText: glyph(original) };
              } finally {
                original.remove();
              }
            });
          });
          assert.equal(languageLayout.length, 2);
          for (const control of languageLayout) {
            assert.ok(Math.abs(control.box.width - control.originalBox.width) <= .5, label + ': language control width changed');
            assert.ok(Math.abs(control.box.height - control.originalBox.height) <= .5, label + ': language control height changed');
            for (const coordinate of ['x', 'y', 'width', 'height']) {
              assert.ok(Math.abs(control.text[coordinate] - control.originalText[coordinate]) <= 1,
                label + ': ' + control.language + ' text differs from original button ' + coordinate);
            }
            if (width === 390) {
              assert.equal(control.box.width, 32);
              assert.equal(control.box.height, 44);
            }
          }
          assert.ok(await page.locator('#hero-title').isVisible());
          assert.equal(await page.locator('.menu-button').getAttribute('aria-expanded'), null);
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
          if (width === 390) {
            const typography = await page.evaluate(() => ({
              heading: getComputedStyle(document.querySelector('#hero-title')).fontWeight,
              eyebrow: getComputedStyle(document.querySelector('.eyebrow')).fontWeight,
              family: getComputedStyle(document.body).fontFamily,
              headingSize: parseFloat(getComputedStyle(document.querySelector('#hero-title')).fontSize),
              hero: document.querySelector('.hero').getBoundingClientRect().toJSON(),
              picture: document.querySelector('.hero-picture').getBoundingClientRect().toJSON(),
              position: getComputedStyle(document.querySelector('.hero-picture img')).objectPosition,
              fit: getComputedStyle(document.querySelector('.hero-picture img')).objectFit,
            }));
            assert.equal(typography.heading, '300');
            assert.equal(typography.eyebrow, '400');
            assert.ok(typography.family.includes('Roboto'), label + ': original mobile font changed');
            assert.ok(Math.abs(typography.headingSize - 50.31) < .05, label + ': original mobile heading scale changed');
            assert.equal(typography.hero.height, 900, label + ': original full-height hero changed');
            assert.equal(typography.picture.width, 390);
            assert.equal(typography.picture.height, typography.hero.height);
            assert.equal(typography.position, '61% 50%');
            assert.equal(typography.fit, 'cover');
          }
          await page.screenshot({ path: path.join(output, 'home-' + label + '.jpg'), type: 'jpeg' });
          if (javascript) {
            initialStoryRequests = [...storyRequests];
            assert.deepEqual(initialStoryRequests, [], label + ': offscreen story images competed with first paint');
            assert.ok(await page.locator('[data-consent-inline]').count(), label + ': first-visit consent controller missing');
            const reject = page.getByRole('button', { name: locale === 'uk' ? 'Відхилити аналітику' : 'Reject analytics', exact: true });
            assert.ok(await reject.isVisible(), label + ': first-visit consent hidden');
            await reject.click();
            assert.deepEqual(controllerRequests, [], label + ': consent action loaded unrelated controllers');
            // The first relevant click must perform its action after enhancement.
            if (width === 390) {
              await page.locator('.menu-button').click();
              await page.locator('#mobile-menu').waitFor({ state: 'visible' });
              assert.equal(await page.locator('.menu-button').getAttribute('aria-expanded'), 'true');
              await page.locator('.menu-button').click();
              await page.locator('#mobile-menu').waitFor({ state: 'hidden' });
            } else {
              await page.locator('[data-lang="' + opposite + '"]').click();
              await page.waitForFunction(() => document.body.dataset.homeEnhanced === 'true');
              assert.equal(await page.locator('html').getAttribute('lang'), opposite, label + ': first language click was lost');
              assert.equal(new URL(page.url()).pathname, oppositePath);
              await page.locator('[data-lang="' + locale + '"]').click();
            }
            if (width === 390) assert.ok(await page.evaluate(() => window.__parsedHomeHeading === document.querySelector('#hero-title')), label + ': first enhancement replaced SSR content');
            assert.deepEqual(controllerRequests, ['/story.js', '/automation.js', '/app.js'], label + ': controllers must load once and in dependency order');
            await page.locator('[data-lang="' + opposite + '"]').click();
            assert.equal(new URL(page.url()).pathname, oppositePath);
            assert.equal(await page.locator('html').getAttribute('lang'), opposite);
            await hero.evaluate(image => image.decode());
            assert.equal(await hero.evaluate(image => image.currentSrc), media.src, label + ': locale switch changed prepared media');
            assert.ok((await hero.getAttribute('alt')).includes(opposite === 'uk' ? 'Концептуальний' : 'Concept house'));
            await page.locator('[data-lang="' + locale + '"]').click();
            // Reconcile restored scroll after intent against the real approach
            // margin; distant media must remain unfetched.
            const storyDistance = await page.locator('.story').evaluate(story => story.getBoundingClientRect().top - innerHeight);
            if (storyDistance >= 320) assert.deepEqual(storyRequests, [], label + ': distant story media loaded');
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
          results.push({ route, locale, width, javascript, media, languageLayout, initialStoryRequests, storyRequests, controllerRequests, fontRequests, automationBiodynamic, errors });
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
    const requests = [], controllers = [];
    page.on('request', request => {
      const pathname = new URL(request.url()).pathname;
      if (/^\/(?:story|automation|app)\.js$/.test(pathname)) controllers.push(pathname);
      if (/^\/assets\/(?:v2\/|automation\/|house-concept\.webp)/.test(pathname)) requests.push(pathname);
    });
    try {
      const route = (locale === 'uk' ? '/' : '/en/') + '#contact';
      await page.goto(origin + route);
      await page.locator('.hero-picture img').evaluate(image => image.decode());
      assert.deepEqual(requests, [], locale + ': skipping directly to contacts loaded hidden story media');
      assert.deepEqual(controllers, [], locale + ': contacts unnecessarily loaded story controllers');
      const initialControllers = [...controllers];
      await page.evaluate(() => {
        const bottom = scrollY + document.querySelector('.story').getBoundingClientRect().bottom;
        window.scrollTo({ top: bottom + 500, behavior: 'instant' });
      });
      await page.waitForFunction(() => document.body.dataset.homeEnhanced === 'true');
      assert.deepEqual(controllers, ['/story.js', '/automation.js', '/app.js'], locale + ': approaching from below must load controllers once');
      results.push({ route, locale, width: 390, javascript: true, hashEntry: 'contact', initialControllerRequests: initialControllers, controllerRequests: controllers });
    } finally {
      await context.close();
    }
  }
  for (const locale of ['uk', 'en']) {
    const context = await browser.newContext({ viewport: { width: 390, height: 900 } });
    const page = await context.newPage();
    let attempts = 0;
    await page.route(/\/app\.js(?:\?|$)/, async request => {
      attempts++;
      if (attempts === 1) await request.abort('failed');
      else await request.continue();
    });
    try {
      await page.goto(origin + (locale === 'uk' ? '/' : '/en/'));
      await page.locator('.menu-button').click();
      await page.locator('#home-interaction-status').waitFor({ state: 'visible' });
      await page.locator('#mobile-menu').waitFor({ state: 'visible' });
      assert.equal(new URL(page.url()).hash, '#mobile-menu');
      assert.equal(await page.locator('.menu-button').getAttribute('aria-expanded'), null);
      // The next public click retries the failed controller without reloading
      // successful classic scripts (whose const declarations cannot run twice).
      await page.locator('.menu-button').click();
      await page.waitForFunction(() => document.body.dataset.homeEnhanced === 'true');
      assert.equal(attempts, 2);
      assert.equal(await page.locator('#home-interaction-status').count(), 0);
      assert.equal(await page.locator('.menu-button').getAttribute('aria-expanded'), 'true');
      await page.locator('#mobile-menu').waitFor({ state: 'visible' });
      results.push({ locale, width: 390, javascript: true, failedControllerRetry: true, attempts });
    } finally {
      await context.close();
    }
  }
  for (const locale of ['uk', 'en']) {
    const context = await browser.newContext({ viewport: { width: 390, height: 900 } });
    const page = await context.newPage();
    let attempts = 0;
    const requests = [];
    await page.route(/\/automation\.css(?:\?|$)/, async request => {
      attempts++;
      if (attempts === 1) await request.abort('failed');
      else await request.continue();
    });
    page.on('request', request => {
      const pathname = new URL(request.url()).pathname;
      if (/^\/(?:automation\.css|story\.js|automation\.js|app\.js)$/.test(pathname)) requests.push(pathname);
    });
    try {
      await page.goto(origin + (locale === 'uk' ? '/' : '/en/'));
      assert.deepEqual(requests, [], locale + ': interaction stylesheet fetched before intent');
      await page.locator('.menu-button').click();
      await page.locator('#home-interaction-status').waitFor({ state: 'visible' });
      await page.locator('#mobile-menu').waitFor({ state: 'visible' });
      assert.equal(new URL(page.url()).hash, '#mobile-menu');
      assert.deepEqual(requests, ['/automation.css'], locale + ': controllers loaded without their stylesheet');
      await page.locator('.menu-button').click();
      await page.waitForFunction(() => document.body.dataset.homeEnhanced === 'true');
      assert.equal(attempts, 2);
      assert.deepEqual(requests, ['/automation.css', '/automation.css', '/story.js', '/automation.js', '/app.js']);
      assert.equal(await page.locator('#home-interaction-status').count(), 0);
      assert.equal(await page.locator('.menu-button').getAttribute('aria-expanded'), 'true');
      results.push({ locale, width: 390, javascript: true, failedStylesheetRetry: true, attempts, requests });
    } finally {
      await context.close();
    }
  }
  writeFileSync(path.join(output, 'home-rendering.json'), JSON.stringify(results, null, 2));
  return results;
};
