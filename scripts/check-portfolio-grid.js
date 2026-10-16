async (page, origin = 'http://127.0.0.1:4173') => {
  const results = [];
  const routes = [];
  for (const prefix of ['', '/en']) {
    await page.goto(origin + prefix + '/portfolio/');
    routes.push(...await page.locator('a.portfolio-card').evaluateAll(cards => cards.map(card => card.getAttribute('href'))));
  }
  for (const route of [...new Set(routes)]) {
    await page.goto(origin + route);
    await page.evaluate(() => document.fonts.ready);
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate(async () => {
        await document.fonts.ready;
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      });
      const errors = await page.evaluate(() => {
        const errors = [];
        for (const chapter of document.querySelectorAll('.case-chapter')) {
          const grids = [...chapter.querySelectorAll('.case-chapter-heading,.case-story-copy,.case-images,.scenario-note')];
          for (const grid of grids) {
            // A few existing galleries contain one frame: verify its occupied column.
            for (let index = 0; index < Math.min(grid.children.length, 2); index++) {
              const baseline = grids[0].children[index].getBoundingClientRect();
              const actual = grid.children[index].getBoundingClientRect();
              if (Math.abs(actual.x - baseline.x) > 1 || Math.abs(actual.width - baseline.width) > 1) errors.push(chapter.id + ': ' + grid.className);
            }
          }
        }
        if (document.documentElement.scrollWidth > innerWidth) errors.push('Overflow');
        for (const link of document.querySelectorAll('a[href^="#"]')) {
          if (link.hash && !document.getElementById(link.hash.slice(1))) errors.push('Missing anchor ' + link.hash);
        }
        return errors;
      });
      if (errors.length) throw Error(route + ' ' + width + ': ' + errors.join(', '));
      results.push(route + ' ' + width + ': aligned');
    }
  }
  return results;
}
