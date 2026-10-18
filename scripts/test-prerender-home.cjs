'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { createRenderer, prerenderHomepages } = require('./prerender-home.cjs');
const source = path.join(__dirname, '../concept');

// The browser uses this same function; evaluating it without document/window
// also guards against accidentally moving browser effects into the build renderer.
test('shared template renders useful, localized HTML without a browser', () => {
  const render = createRenderer(source);
  for (const [locale, headline, portfolio] of [
    ['uk', 'Продуманий', '/portfolio/'],
    ['en', 'Considered', '/en/portfolio/'],
  ]) {
    const html = render(locale);
    assert.ok(html.includes(headline));
    assert.ok(html.includes('href="' + portfolio + '"'));
    assert.match(html, /class="hero-picture"><img[^>]+fetchpriority="high"/);
    assert.match(html, /class="visual-image current"[^>]+data-story-src="\/assets\/v2\/model.webp"[^>]+loading="lazy"/);
    assert.doesNotMatch(html.split('<noscript>')[0], /class="visual-image current"[^>]+(?<![\w-])src=/);
    assert.match(html, /<noscript><img class="visual-image current"[^>]+src="\/assets\/v2\/model.webp"/);
    assert.match(html, /class="privacy-image"[^>]+loading="lazy"/);
    assert.match(html, /<h2>(?:Починаємо з контексту\.|Start with the context\.)<\/h2>/);
    assert.match(html, /data-lang="uk" href="\/" lang="uk" hreflang="uk"/);
    assert.match(html, /data-lang="en" href="\/en\/" lang="en" hreflang="en"/);
    assert.match(html, new RegExp('data-lang="' + locale + '"[^>]+aria-current="page"'));
    assert.match(html, /class="menu-button" href="#mobile-menu"/);
    assert.doesNotMatch(html, /class="menu-button"[^>]+aria-expanded=/);
    assert.match(html, /<main id="main">/);
    assert.match(html, /id="our-approach"/);
    assert.match(html, /id="architecture-services"/);
    assert.match(html, /id="contact"/);
    assert.match(html, /href="tel:\+380974781005"/);
    assert.doesNotMatch(html, /undefined|\bNaN\b/);
  }
  assert.throws(() => render('ru'), /Unsupported/);
});

test('language change retains prepared picture URLs and translates only alt text', () => {
  const render = createRenderer(source);
  const picture = '<picture><source type="image/avif" srcset="/assets/responsive/hero.avif?v=123 1536w" sizes="100vw"><img src="/assets/house-concept.webp?v=456" width="1536" height="1024" alt="UA alt" fetchpriority="high"></picture>';
  const app = fs.readFileSync(path.join(source, 'app.js'), 'utf8');
  const logoPicture = '<picture><source type="image/webp" srcset="/assets/responsive/piskor-logo.webp?v=789"><img src="/assets/piskor-logo.png?v=abc" alt="PISKOR Architect"></picture>';
  const context = vm.createContext({ picture, logoPicture });
  vm.runInContext(fs.readFileSync(path.join(source, 'story.js'), 'utf8'), context);
  vm.runInContext(app.split('// Browser-only homepage enhancement.')[0], context);
  const html = vm.runInContext('renderHomeMarkup("en",picture,logoPicture)', context);
  assert.match(html, /srcset="\/assets\/responsive\/hero\.avif\?v=123 1536w"/);
  assert.match(html, /src="\/assets\/house-concept\.webp\?v=456"/);
  assert.match(html, /alt="Concept house in dark stone and glass among pine trees"/);
  assert.doesNotMatch(html, /UA alt/);
  assert.equal((html.match(/srcset="\/assets\/responsive\/piskor-logo\.webp\?v=789"/g) || []).length, 2);
});

test('build inserts both home pages and preserves metadata and consent hooks', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'piskor-home-'));
  try {
    for (const filename of ['app.js', 'story.js']) fs.copyFileSync(path.join(source, filename), path.join(directory, filename));
    fs.mkdirSync(path.join(directory, 'en'));
    for (const [relative, locale] of [['index.html', 'uk'], ['en/index.html', 'en']]) {
      fs.writeFileSync(path.join(directory, relative), '<html lang="' + locale + '"><head><meta name="robots" content="noindex,nofollow"></head><body><div id="app" data-home-render=""></div><script src="/analytics-consent.js"></script></body></html>');
    }
    assert.equal(prerenderHomepages(directory), 2);
    for (const [relative, locale] of [['index.html', 'uk'], ['en/index.html', 'en']]) {
      const html = fs.readFileSync(path.join(directory, relative), 'utf8');
      assert.ok(html.includes('data-home-render="' + locale + '"'));
      assert.match(html, /<h1 id="hero-title">/);
      assert.match(html, /content="noindex,nofollow"/);
      assert.match(html, /src="\/analytics-consent.js"/);
      assert.equal((html.match(/<main /g) || []).length, 1);
    }
    assert.throws(() => prerenderHomepages(directory), /unrendered app placeholder/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('enhancement keeps the initial prerendered DOM and renders only on locale change', () => {
  const appSource = fs.readFileSync(path.join(source, 'app.js'), 'utf8');
  // Run the actual render function with the smallest DOM surface it needs. A
  // replacement of SSR markup would throw, detecting lost media / focus state.
  const start = appSource.indexOf('function render(');
  const end = appSource.indexOf('\n\nfunction technicalArt', start);
  let replacements = 0, controls = 0, stories = 0;
  const app = {
    dataset: { homeRender: 'uk' },
    querySelector: () => ({}),
    set innerHTML(value) { replacements++; assert.equal(value, 'en markup'); },
  };
  const context = vm.createContext({
    locale: 'uk',
    homeSEO: {
      uk: { title: 'UA', description: 'UA description', path: '/', locale: 'uk_UA' },
      en: { title: 'EN', description: 'EN description', path: '/en/', locale: 'en_GB' },
    },
    document: {
      documentElement: { lang: 'uk' },
      body: { classList: { toggle() {} } },
      querySelector: selector => selector === '#app' ? app : { href: 'https://piskor.com.ua/' },
    },
    reduced: { matches: false },
    logo: '<img src="/logo.png">',
    URL,
    renderHomeMarkup: locale => locale + ' markup',
    bindControls: () => controls++,
    initStory: () => stories++,
  });
  vm.runInContext(appSource.slice(start, end), context);
  vm.runInContext('render()', context);
  assert.equal(replacements, 0);
  assert.equal(controls, 1);
  assert.equal(stories, 1);
  vm.runInContext('locale="en";render()', context);
  assert.equal(replacements, 1);
  assert.equal(app.dataset.homeRender, 'en');
  assert.equal(controls, 2);
  assert.equal(stories, 2);
});

test('story media waits for approach, flushes latest frame, and resets stale locale work', () => {
  const app = fs.readFileSync(path.join(source, 'app.js'), 'utf8');
  const start = app.indexOf('const decodedImages=new Map();');
  const end = app.indexOf('let sceneLayoutTimer', start);
  const observers = [], shown = [], prepared = [];
  const box = { top: 2000, bottom: 12000 };
  const context = vm.createContext({
    document: { querySelector: () => ({ getBoundingClientRect: () => box }) },
    innerHeight: 900, imageTicket: 0, activeFrame: 1, activeChapter: 0,
    frames: [{ asset: 'model' }, { asset: 'kitchen' }, { asset: 'materials' }],
    showImage: (key, animate) => shown.push([key, animate]),
    prepareImage: key => prepared.push(key),
    IntersectionObserver: class {
      constructor(callback, options) { this.callback = callback; this.options = options; this.disconnected = false; observers.push(this); }
      observe() {}
      disconnect() { this.disconnected = true; }
    },
  });
  vm.runInContext(app.slice(start, end), context);
  vm.runInContext('resetStoryMedia();pendingStoryImage={key:"model"};activateStoryMedia();prepareStoryNeighbors()', context);
  assert.deepEqual(shown, []);
  assert.deepEqual(prepared, []);
  assert.equal(observers[0].options.rootMargin, '320px 0px');
  vm.runInContext('pendingStoryImage={key:"kitchen"}', context);
  box.top = 1200;
  observers[0].callback([{ isIntersecting: true }]);
  assert.deepEqual(shown, [['kitchen', false]]);
  assert.deepEqual(prepared, ['materials', 'model']);
  assert.ok(observers[0].disconnected);
  box.top = 2000;
  vm.runInContext('resetStoryMedia();pendingStoryImage={key:"night"};resetStoryMedia()', context);
  box.top = 1200;
  observers.at(-1).callback([{ isIntersecting: true }]);
  assert.deepEqual(shown, [['kitchen', false]], 'A discarded locale must not flush its pending frame');
  box.top = 2000;
  vm.runInContext('resetStoryMedia();pendingStoryImage={key:"house"};activateStoryMedia(true)', context);
  assert.deepEqual(shown.at(-1), ['house', false], 'Explicit navigation must load immediately');
  vm.runInContext('resetStoryMedia();storyMediaInitializing=true;pendingStoryImage={key:"model"};activateStoryMedia(true);pendingStoryImage={key:"night"};storyMediaInitializing=false;activateStoryMedia(true)', context);
  assert.deepEqual(shown.at(-1), ['night', false], 'Initial scroll / locale reconciliation must flush only its final frame');
  assert.equal(shown.filter(([key]) => key === 'model').length, 0);
});
