async page => {
  const origin = 'http://127.0.0.1:4173';
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const results = [];
  for (const lang of ['uk', 'en']) {
    const prefix = lang === 'en' ? '/en' : '';
    await page.goto(origin + prefix + '/portfolio/');
    const cards = page.locator('.portfolio-card');
    if (await cards.count() !== 2) throw Error('Expected two project cards');
    if (!(await cards.first().getAttribute('href')).includes('briukhovychi-house')) throw Error('Year sorting failed');
    await cards.first().click();
    await page.evaluate(async () => {
      await Promise.all([...document.images].filter(i => i.getAttribute('src')).map(i => { i.loading = 'eager'; return i.decode(); }));
    });
    if (await page.locator('h1').count() !== 1) throw Error('H1 count');
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      const issues = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth,
        anchors: [...document.querySelectorAll('a[href^="#"]')].filter(a => !document.getElementById(a.hash.slice(1))).map(a => a.hash),
        duplicateIds: [...document.querySelectorAll('[id]')].map(e => e.id).filter((id, i, a) => a.indexOf(id) !== i)
      }));
      if (issues.overflow || issues.anchors.length || issues.duplicateIds.length) throw Error(JSON.stringify({ lang, width, issues }));
    }
    await page.locator('.case-navigation a').nth(2).click();
    if (!page.url().endsWith('#night-lighting')) throw Error('Anchor navigation');
    const first = page.locator('[data-gallery]').first();
    await first.click();
    if (!await page.locator('.project-lightbox').evaluate(d => d.open)) throw Error('Lightbox did not open');
    const previous = await page.locator('.project-lightbox img').getAttribute('src');
    await page.keyboard.press('ArrowRight');
    if (previous === await page.locator('.project-lightbox img').getAttribute('src')) throw Error('Gallery navigation');
    await page.keyboard.press('Escape');
    if (!await first.evaluate(e => e === document.activeElement)) throw Error('Focus not restored');
    if (await page.locator('.project-faq').count()) throw Error('Removed FAQ returned');
    if (/концепц|візуаліз|рендер|concept|visualization|rendering/i.test(await page.locator('main').innerText())) throw Error('Stale presentation copy');
    results.push(lang + ': catalog order, images, anchors, gallery, focus, completed-project copy, 1440/390/320px passed');
  }
  if (errors.length) throw Error(errors.join('\n'));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(origin + '/portfolio/briukhovychi-house/');
  await page.evaluate(async () => Promise.all([...document.images].filter(i => i.getAttribute('src')).map(i => { i.loading = 'eager'; return i.decode(); })));
  await page.evaluate(() => scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({ path: 'output/playwright/briukhovychi-desktop.png' });
  await page.locator('#shared-spaces').screenshot({ path: 'output/playwright/briukhovychi-chapter.png' });
  await page.setViewportSize({ width:390, height:844 });
  await page.evaluate(() => scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({ path: 'output/playwright/briukhovychi-mobile.png' });
  return results;
}
