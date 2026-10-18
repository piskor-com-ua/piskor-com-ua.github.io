const assert = require('node:assert/strict');
const { mkdirSync } = require('node:fs');

async function assertNamedCardLinks(page, label) {
  // DOM text/backend IDs do not measure or reveal offscreen descendants.
  const titles = await page.locator('.catalog-projects a.portfolio-card h3').allTextContents();
  const labels = await page.locator('.catalog-projects a.portfolio-card').evaluateAll(cards => cards.map(card => card.getAttribute('aria-label')));
  const cdp = await page.context().newCDPSession(page);
  try {
    const { root } = await cdp.send('DOM.getDocument', { depth: 0 });
    const { nodeIds } = await cdp.send('DOM.querySelectorAll', { nodeId: root.nodeId, selector: '.catalog-projects a.portfolio-card' });
    const descriptions = await Promise.all(nodeIds.map(nodeId => cdp.send('DOM.describeNode', { nodeId })));
    const { nodes } = await cdp.send('Accessibility.getFullAXTree');
    const accessible = new Map(nodes.filter(node => !node.ignored).map(node => [node.backendDOMNodeId, node]));
    assert.equal(descriptions.length, titles.length, label + ': card headings missing');
    const normalize = text => text.replace(/\s+/g, ' ').trim();
    for (let index = 0; index < descriptions.length; index++) {
      const node = accessible.get(descriptions[index].node.backendNodeId);
      assert.equal(node?.role?.value, 'link', label + ': card absent from native AX: ' + titles[index]);
      assert.ok(normalize(labels[index] || '').includes(normalize(titles[index])), label + ': card label omits heading');
      assert.equal(normalize(node?.name?.value || ''), normalize(labels[index] || ''), label + ': native AX card name differs from complete visible label');
    }
    return descriptions.length;
  } finally {
    await cdp.detach();
  }
}

// Inspect each card only after revealing its article. Measuring every descendant
// up front would materialize skipped content and conceal content-visibility bugs.
module.exports = async function checkCatalogRendering(browser, origin, output = 'output/browser') {
  mkdirSync(output, { recursive: true });
  const results = [];
  for (const prefix of ['', '/en']) {
    for (const width of [390, 768, 1440]) {
      const route = prefix + '/portfolio/';
      const label = (prefix ? 'en' : 'uk') + '-' + width;
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('response', response => { if (response.status() >= 400) errors.push(response.status() + ' ' + response.url()); });
      const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const noOverflow = async () => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), label + ': horizontal overflow');
      const reveal = async article => {
        await article.evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
        await settle();
        await article.locator('.portfolio-card-cover').evaluate(async image => {
          await image.decode();
          if (!image.complete || !image.naturalWidth || !image.naturalHeight) throw Error('Empty catalog cover');
        });
        const geometry = await article.evaluate(element => {
          const card = element.querySelector('a.portfolio-card');
          const image = card.querySelector('.portfolio-card-cover');
          const heading = card.querySelector('h3');
          const box = card.getBoundingClientRect(), cover = image.getBoundingClientRect(), title = heading.getBoundingClientRect();
          const imageContainer = image.closest('.portfolio-card-image');
          const frame = imageContainer.getBoundingClientRect(), frameStyle = getComputedStyle(imageContainer);
          // The existing hover treatment scales the bitmap inside an overflow
          // clip. Test its painted bounds, not the intentionally larger bitmap.
          const clipX = ['hidden', 'clip'].includes(frameStyle.overflowX);
          const paintedLeft = clipX ? Math.max(cover.left, frame.left) : cover.left;
          const paintedRight = clipX ? Math.min(cover.right, frame.right) : cover.right;
          return { visible: image.checkVisibility({ contentVisibilityAuto: true }) && heading.checkVisibility({ contentVisibilityAuto: true }),
            intersects: box.bottom > 0 && box.top < innerHeight,
            cover: cover.width > 0 && cover.height > 0, title: title.width > 0 && title.height > 0,
            horizontal: box.left >= -.5 && box.right <= innerWidth + .5,
            containsImage: paintedLeft >= box.left - 1 && paintedRight <= box.right + 1,
            fillsImageFrame: cover.left <= frame.left + 1 && cover.right >= frame.right - 1 && cover.top <= frame.top + 1 && cover.bottom >= frame.bottom - 1,
            containsTitle: title.left >= box.left - 1 && title.right <= box.right + 1,
            details: { card: box.toJSON(), image: cover.toJSON(), title: title.toJSON(),
              imageContainer: frame.toJSON(), overflowX: frameStyle.overflowX,
              transform: getComputedStyle(image).transform, hover: card.matches(':hover'),
              project: card.dataset.projectId } };
        });
        for (const [key, value] of Object.entries(geometry)) if (key !== 'details') assert.ok(value, label + ': revealed card ' + key + ' ' + JSON.stringify(geometry.details));
        await noOverflow();
      };
      const focusVisible = async card => {
        const state = await card.evaluate(element => {
          let clippingElement = element;
          while (clippingElement && getComputedStyle(clippingElement).contentVisibility !== 'auto') clippingElement = clippingElement.parentElement;
          const box = element.getBoundingClientRect(), parent = (clippingElement || element).getBoundingClientRect();
          const style = getComputedStyle(element), container = getComputedStyle(clippingElement || element);
          const outline = parseFloat(style.outlineWidth) + Math.max(0, parseFloat(style.outlineOffset) || 0);
          const margin = parseFloat(container.overflowClipMargin) || 0;
          return { active: document.activeElement === element,
            onscreen: box.bottom > 0 && box.top < innerHeight,
            outline: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0,
            unclipped: container.contentVisibility !== 'auto' ||
              (box.left - outline >= parent.left - margin - 1 && box.right + outline <= parent.right + margin + 1 &&
               box.top - outline >= parent.top - margin - 1 && box.bottom + outline <= parent.bottom + margin + 1) };
        });
        for (const [key, value] of Object.entries(state)) assert.ok(value, label + ': keyboard focus ' + key);
      };
      try {
        const response = await page.goto(origin + route);
        assert.equal(response.status(), 200);
        await page.evaluate(() => document.fonts.ready);
        await settle();
        const articles = page.locator('.catalog-projects article');
        const cards = articles.locator('a.portfolio-card');
        const count = await cards.count();
        assert.ok(count > 2, label + ': catalog cards missing');
        const accessibleCards = await assertNamedCardLinks(page, label);
        assert.equal(accessibleCards, count, label + ': native AX card count');
        await page.locator('.portfolio-card-cover').first().evaluate(image => image.decode());
        for (const selector of ['h1', '.header .logo', '.catalog-years', '.analytics-consent']) {
          const element = page.locator(selector).first();
          assert.ok(await element.isVisible(), label + ': first visit ' + selector);
        }
        const bannerFits = await page.locator('.analytics-consent').evaluate(element => {
          const box = element.getBoundingClientRect();
          return box.left >= 0 && box.right <= innerWidth + 1 && box.top >= 0 && box.bottom <= innerHeight + 1;
        });
        assert.ok(bannerFits, label + ': first visit consent clipped');
        assert.equal(await page.locator('script[src*="googletagmanager"]').count(), 0);
        await noOverflow();
        await page.screenshot({ path: output + '/catalog-first-visit-' + label + '.jpg', type: 'jpeg' });
        await page.getByRole('button', { name: prefix ? 'Reject analytics' : 'Відхилити аналітику', exact: true }).click();

        // Exercise never-rendered content before anchors or the sequential walk
        // populate remembered intrinsic sizes. checkVisibility does not query
        // descendant rectangles or force skipped contents to lay out.
        assert.equal(await cards.last().locator('.portfolio-card-cover').evaluate(image =>
          image.checkVisibility({ contentVisibilityAuto: true })), false, label + ': last card must start skipped');
        await cards.first().focus();
        await page.keyboard.press('Tab');
        await page.keyboard.press('Shift+Tab');
        await settle();
        await focusVisible(cards.first());
        // Keyboard modality is already established. Direct focus must reveal
        // and scroll the untouched last card without first visiting its neighbor.
        await cards.last().focus();
        await settle();
        await focusVisible(cards.last());
        await page.keyboard.press('Tab');
        await page.keyboard.press('Shift+Tab');
        await settle();
        await focusVisible(cards.last());
        if (width === 390) await page.screenshot({ path: output + '/catalog-last-focus-' + label + '.jpg', type: 'jpeg' });
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
        await settle();

        const anchors = await page.locator('.catalog-years a[href^="#"]').evaluateAll(links => links.map(link => link.getAttribute('href')));
        for (const hash of anchors) {
          await page.locator('.catalog-years a[href="' + hash + '"]').click();
          await settle();
          assert.equal(new URL(page.url()).hash, hash);
          const target = page.locator(hash);
          assert.equal(await target.count(), 1, label + ': missing year target ' + hash);
          const nearViewport = await target.evaluate(element => {
            const box = element.getBoundingClientRect();
            return box.top >= -1 && box.top < innerHeight;
          });
          assert.ok(nearViewport, label + ': year anchor did not scroll to ' + hash);
          const first = target.locator('article').first();
          assert.ok(await first.count(), label + ': empty year ' + hash);
          await reveal(first);
        }

        // DOM order/count alone does not force rendering of skipped descendants.
        for (let index = 0; index < count; index++) await reveal(articles.nth(index));

        await page.emulateMedia({ media: 'print' });
        const printVisibility = await cards.evaluateAll(elements => elements.map(element => getComputedStyle(element).contentVisibility));
        assert.ok(printVisibility.every(value => value === 'visible'), label + ': print skips catalog content');
        assert.deepEqual(errors, [], label + ': browser errors');
        results.push({ route, width, cards: count, accessibleCards, yearAnchors: anchors.length, firstVisitConsent: true, keyboardFocus: true, print: true });
      } catch (error) {
        await page.screenshot({ path: output + '/catalog-failure-' + label + '.jpg', type: 'jpeg' }).catch(() => {});
        throw new Error(label + ': ' + error.message, { cause: error });
      } finally {
        await context.close();
      }
    }
    const noJsContext = await browser.newContext({ viewport: { width: 390, height: 900 }, javaScriptEnabled: false });
    try {
      const noJsPage = await noJsContext.newPage();
      const response = await noJsPage.goto(origin + prefix + '/portfolio/');
      assert.equal(response.status(), 200);
      const count = await noJsPage.locator('.catalog-projects a.portfolio-card').count();
      assert.ok(count > 2);
      assert.equal(await assertNamedCardLinks(noJsPage, (prefix ? 'en' : 'uk') + '-no-js'), count);
      results.push({ route: prefix + '/portfolio/', width: 390, javaScript: false, cards: count, accessibleCards: count });
    } finally {
      await noJsContext.close();
    }
  }
  return results;
};
