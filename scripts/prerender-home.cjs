/** Render both home pages from the exact browser template before asset preparation. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const BROWSER_BOUNDARY = '// Browser-only homepage enhancement.';
const PLACEHOLDER = '<div id="app" data-home-render=""></div>';
const HOME_PAGES = [['index.html', 'uk'], ['en/index.html', 'en']];

function createRenderer(directory) {
  const app = fs.readFileSync(path.join(directory, 'app.js'), 'utf8');
  const parts = app.split(BROWSER_BOUNDARY);
  assert.equal(parts.length, 2, 'Homepage source must have one browser boundary');
  // Only committed, trusted project JavaScript is evaluated. No website HTML or
  // external content is executed, and the renderer receives no browser or IO APIs.
  const context = vm.createContext(Object.create(null), {
    codeGeneration: { strings: false, wasm: false },
  });
  vm.runInContext(fs.readFileSync(path.join(directory, 'story.js'), 'utf8'), context, { timeout: 1000 });
  vm.runInContext(parts[0], context, { timeout: 1000 });
  return locale => {
    assert.ok(['uk', 'en'].includes(locale), 'Unsupported homepage locale');
    return vm.runInContext('renderHomeMarkup(' + JSON.stringify(locale) + ')', context, { timeout: 1000 });
  };
}

function prerenderHomepages(directory) {
  const render = createRenderer(directory);
  for (const [relative, locale] of HOME_PAGES) {
    const filename = path.join(directory, relative);
    const html = fs.readFileSync(filename, 'utf8');
    assert.match(html, new RegExp('<html lang="' + locale + '"'), 'Homepage language must match its route');
    assert.equal(html.split(PLACEHOLDER).length, 2, 'Homepage must contain one unrendered app placeholder: ' + relative);
    const markup = render(locale);
    assert.ok(markup.includes('id="hero-title"') && markup.includes('id="contact"'), 'Homepage content is incomplete');
    // Use a callback: literal dollar sequences in future copy are not replacement tokens.
    fs.writeFileSync(filename, html.replace(PLACEHOLDER, () => '<div id="app" data-home-render="' + locale + '">' + markup + '</div>'));
  }
  return HOME_PAGES.length;
}

if (require.main === module) {
  const output = path.resolve(process.argv[2] || '_site');
  console.log('Prerendered home pages: ' + prerenderHomepages(output));
}

module.exports = { createRenderer, prerenderHomepages };
