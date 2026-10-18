// Initial rendering contract only; blocked media makes this no PSI evidence.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');

module.exports = async function checkNativeFonts(browser, origin) {
  const routes = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c',
    "import json,sys;sys.path.insert(0,'scripts');from collect_pagespeed import inventory;print(json.dumps([p['route'] for p in inventory('_site','https://piskor.com.ua','font-contract')['pages']]))",
  ], { encoding: 'utf8' }));
  const rows = [];
  for (const width of [390, 701]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    try {
      await context.route('**/*', route => ['image', 'media', 'font'].includes(route.request().resourceType())
        || new URL(route.request().url()).origin !== origin ? route.abort() : route.continue());
      const page = await context.newPage();
      let fonts = [];
      page.on('request', request => { if (request.resourceType() === 'font') fonts.push(new URL(request.url()).pathname); });
      for (const route of routes) {
        fonts = [];
        const response = await page.goto(origin + route, { waitUntil: 'load' });
        assert.equal(response.status(), 200, route);
        await page.evaluate(() => document.fonts.ready);
        const result = await page.evaluate(() => ({
          family: getComputedStyle(document.body).fontFamily,
          custom: [...document.body.querySelectorAll('*')].filter(node => getComputedStyle(node).fontFamily.includes('Roboto'))
            .slice(0, 5).map(node => ({ tag: node.tagName, id: node.id, class: node.getAttribute('class') })),
        }));
        if (width <= 700) {
          assert.deepEqual(fonts, [], route + ': mobile attempted a webfont request');
          assert.ok(result.family.includes('system-ui'), route + ': mobile body lost its native font stack');
          assert.deepEqual(result.custom, [], route + ': component reintroduced a custom font');
        } else {
          assert.ok(result.family.includes('Roboto'), route + ': desktop lost its original font family');
        }
        rows.push({ route, width, family: result.family, fontRequests: [...fonts] });
      }
    } finally {
      await context.close();
    }
  }
  return rows;
};
