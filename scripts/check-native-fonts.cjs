// Original Roboto rendering contract; blocked media makes this no PSI evidence.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');

module.exports = async function checkNativeFonts(browser, origin) {
  const routes = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c',
    "import json,sys;sys.path.insert(0,'scripts');from collect_pagespeed import inventory;print(json.dumps([p['route'] for p in inventory('_site','https://piskor.com.ua','font-contract')['pages']]))",
  ], { encoding: 'utf8' }));
  const reviewed = '/en/portfolio/2022/zabava-restaurant-sambir/';
  const originalCoverage = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c',
    "import json;from fontTools.ttLib import TTFont;print(json.dumps(sorted(TTFont('_site/assets/fonts/roboto-light-subset.woff2').getBestCmap())))",
  ], {encoding: 'utf8'}));
  const expand = range => [...range.matchAll(/U\+([0-9A-F]+)(?:-([0-9A-F]+))?/gi)]
    .flatMap(([, first, last]) => {
      const start = parseInt(first, 16), end = parseInt(last || first, 16);
      return Array.from({length: end - start + 1}, (_, index) => start + index);
    }).sort((a, b) => a - b);
  const rows = [];
  for (const width of [390, 701]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    try {
      let currentRoute;
      await context.route('**/*', route => ['image', 'media'].includes(route.request().resourceType())
        || (route.request().resourceType() === 'font' && currentRoute !== reviewed)
        || new URL(route.request().url()).origin !== origin ? route.abort() : route.continue());
      const page = await context.newPage();
      let fonts = [];
      page.on('request', request => { if (request.resourceType() === 'font') fonts.push(new URL(request.url()).pathname); });
      for (const route of routes) {
        currentRoute = route;
        fonts = [];
        const response = await page.goto(origin + route, { waitUntil: 'load' });
        assert.equal(response.status(), 200, route);
        await page.evaluate(() => document.fonts.ready);
        const result = await page.evaluate(() => ({
          family: getComputedStyle(document.body).fontFamily,
          faces: [...document.styleSheets].flatMap(sheet => [...sheet.cssRules])
            .filter(rule => rule.type === CSSRule.FONT_FACE_RULE)
            .map(rule => ({family: rule.style.fontFamily, weight: rule.style.fontWeight,
              display: rule.style.fontDisplay, range: rule.style.unicodeRange,
              inline: rule.style.src.includes('data:font/woff2;base64,')})),
          preloads: [...document.querySelectorAll('link[rel="preload"][as="font"]')]
            .map(link => ({ href: link.getAttribute('href'), media: link.media })),
        }));
        assert.ok(result.family.includes('Roboto'), route + ': original font family changed');
        if (route === reviewed) {
          assert.deepEqual(result.preloads, [], route + ': inline font must not retain an unused preload');
          const faces = result.faces.filter(face => face.family.replace(/["']/g, '') === 'Roboto');
          assert.equal(faces.length, 4, route + ': original complementary faces missing');
          const critical = faces.filter(face => face.inline);
          assert.equal(critical.length, 2);
          assert.deepEqual(critical.map(face => face.weight).sort(), ['300', '400']);
          assert.ok(faces.every(face => face.display === 'swap'));
          for (const weight of ['300', '400']) {
            const fallback = faces.filter(face => face.weight === weight && !face.inline);
            assert.equal(fallback.length, 1);
            const inline = critical.find(face => face.weight === weight);
            const a = expand(inline.range), b = expand(fallback[0].range);
            assert.equal(a.filter(code => b.includes(code)).length, 0, 'Font ranges overlap');
            assert.deepEqual([...a, ...b].sort((x, y) => x - y), originalCoverage,
              route + ': original full character coverage changed');
          }
          // Actual complementary font requests are allowed for this profile.
          // This remains a font contract probe, never a performance measurement.
          await page.evaluate(async () => {
            await Promise.all(['300', '400'].map(weight => document.fonts.load(weight + ' 20px Roboto', 'ҐґЄєІіЇїЙйКиїв м² !?')));
            if (!['300', '400'].every(weight => document.fonts.check(weight + ' 20px Roboto', 'ҐґЄєІіЇїЙйКиїв м² !?'))) {
              throw Error('Original complementary Roboto could not load');
            }
          });
          assert.ok(fonts.some(url => url.includes('roboto-light-subset.woff2')));
          assert.ok(fonts.some(url => url.includes('roboto-regular-subset.woff2')));
        } else {
          assert.ok(result.preloads.some(link => link.href.includes('roboto-light')), route + ': original light-font preload missing');
        }
        assert.ok(result.preloads.every(link => link.media === ''), route + ': original font preload restricted by viewport');
        rows.push({ route, width, family: result.family, fontRequests: [...fonts],
          kind: route === reviewed ? 'actual-inline-and-complementary-fonts-media-blocked' : 'font-network-blocked' });
      }
    } finally {
      await context.close();
    }
  }
  return rows;
};
