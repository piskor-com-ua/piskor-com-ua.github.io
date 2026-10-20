import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('./deferred-mobile-media-controller.js', import.meta.url), 'utf8');

function fixture(mode = 'observer') {
  const writes = [], observed = [], removed = [], handlers = {};
  class Node {
    constructor(name, attributes) {this.name = name; this.attributes = new Map(Object.entries(attributes));}
    getAttribute(name) {return this.attributes.get(name);}
    hasAttribute(name) {return this.attributes.has(name);}
    setAttribute(name, value) {this.attributes.set(name, value); writes.push([this.name, name, value]);}
    removeAttribute(name) {this.attributes.delete(name);}
  }
  const image = new Node('image', {'src': 'data:image/svg+xml,placeholder', 'data-piskor-src': '/original.webp',
    'data-piskor-srcset': '/small.webp 640w, /large.webp 1440w', alt: 'Dining room'});
  const responsive = new Node('source', {'data-piskor-srcset': '/small.avif 640w, /large.avif 1440w'});
  const picture = new Node('picture', {'data-piskor-deferred-media': ''});
  const button = {addEventListener(name, callback, options) {handlers[name] = {callback, options};}};
  picture.querySelector = () => image;
  picture.querySelectorAll = () => [responsive, image].filter(node => node.hasAttribute('data-piskor-srcset'));
  picture.closest = selector => selector === '[data-gallery]' ? button : selector === 'a' ? null : null;
  image.closest = () => picture;
  let notify, config, ready;
  const window = {};
  if (mode !== 'missing') window.IntersectionObserver = class {
    constructor(callback, options) {if (mode === 'throws') throw Error('Unavailable observer'); notify = callback; config = options;}
    observe(node) {observed.push(node);}
    unobserve(node) {removed.push(node);}
    disconnect() {}
  };
  const document = {readyState: 'complete', querySelectorAll() {return [picture];},
    addEventListener(event, callback, options) {assert.equal(event, 'DOMContentLoaded'); assert.equal(options.once, true); ready = callback;}};
  vm.runInNewContext(source, {window, document, IntersectionObserver: window.IntersectionObserver});
  return {writes, image, picture, handlers, observed, removed, get config() {return config;},
    notify(value) {notify([{target: image, isIntersecting: value}]);}, ready() {ready();}};
}

test('offscreen image URLs remain inert until the 500px near-viewport boundary', () => {
  const page = fixture();
  assert.equal(page.writes.length, 0);
  assert.equal(page.config.rootMargin, '500px 0px');
  assert.equal(page.config.threshold, 0);
  page.notify(false);
  assert.equal(page.writes.length, 0);
  page.notify(true);
  assert.deepEqual(page.writes.map(row => row.slice(0, 2)),
    [['source', 'srcset'], ['image', 'srcset'], ['image', 'src']]);
  assert.equal(page.image.getAttribute('alt'), 'Dining room');
  assert.equal(page.removed[0], page.image);
  page.notify(true);
  assert.equal(page.writes.length, 3);
});

test('focus and capture-phase click restore sources before gallery or navigation handlers', () => {
  for (const event of ['focusin', 'click']) {
    const page = fixture();
    assert.equal(page.handlers.click.options.capture, true);
    page.handlers[event].callback();
    assert.equal(page.image.getAttribute('src'), '/original.webp');
    assert.equal(page.writes[0][0], 'source');
  }
});

test('missing or failed IntersectionObserver eagerly restores every source', () => {
  for (const mode of ['missing', 'throws']) {
    const page = fixture(mode);
    assert.equal(page.image.getAttribute('src'), '/original.webp');
    assert.equal(page.picture.hasAttribute('data-piskor-deferred-media'), false);
    assert.equal(page.writes.length, 3);
  }
});
