async page => {
  const results = [];
  for (const language of ['', '/en']) {
    for (const project of ['lviv-apartment', 'briukhovychi-house']) {
      await page.goto('http://127.0.0.1:4173' + language + '/portfolio/' + project + '/?preview=shared-grid');
      for (const width of [1440, 768, 390]) {
        await page.setViewportSize({width, height:900});
        const errors = await page.evaluate(() => {
          const errors = [];
          for (const chapter of document.querySelectorAll('.case-chapter')) {
            const grids = [...chapter.querySelectorAll('.case-chapter-heading,.case-story-copy,.case-images,.scenario-note')];
            const baseline = grids[0].children[1].getBoundingClientRect();
            for (const grid of grids) {
              const right = grid.children[1].getBoundingClientRect();
              if (Math.abs(right.x-baseline.x)>1 || Math.abs(right.width-baseline.width)>1) errors.push(chapter.id + ': ' + grid.className);
            }
          }
          if (document.documentElement.scrollWidth > innerWidth) errors.push('Overflow');
          return errors;
        });
        if (errors.length) throw Error(project + ' ' + language + ' ' + width + ': ' + errors.join(', '));
        results.push(project + ' ' + (language || 'uk') + ' ' + width + ': aligned');
      }
    }
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:4173/portfolio/briukhovychi-house/?preview=shared-grid');
  await page.locator('.case-chapter').first().locator('img').evaluateAll(async imgs=>Promise.all(imgs.map(i=>i.decode())));
  await page.locator('.case-chapter').first().screenshot({path:'output/playwright/shared-portfolio-grid.png'});
  return results;
}
