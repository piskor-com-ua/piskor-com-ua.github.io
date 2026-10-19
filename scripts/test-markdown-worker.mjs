import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {handle, diagnosticParameters} from '../cloudflare/markdown-worker.mjs';

const origin = 'https://piskor.com.ua';
const data = {revision: '1'.repeat(40), pages: {'/': {markdown: '/agent-markdown/index.md'}, '/404.html?lang=en': {markdown: '/agent-markdown/404-en.md'}, '/404.html?lang=uk': {markdown: '/agent-markdown/404.md'}}, documents: {}};
for (const [url, body, language] of [['/agent-markdown/index.md', '# Простір\n', 'uk'], ['/agent-markdown/404.md', '# UK\n', 'uk'], ['/agent-markdown/404-en.md', '# English\n', 'en']]) {
  data.documents[url] = {body, bytes: Buffer.byteLength(body), language};
}

async function passthrough(route, options = {}, env = {}, response = new Response('<html>same</html>', {headers: {'Content-Type': 'text/html; charset=utf-8'}}), nowSeconds = 1800000001) {
  const request = new Request(origin + route, options);
  let calls = 0;
  const actual = await handle(request, env, {passThroughOnException() {}}, data, {nowSeconds, fetch: async seen => {assert.equal(seen, request); calls++; return response;}});
  assert.equal(calls, 1);
  return {actual, response};
}

test('strict negotiation and direct alternatives preserve exact UTF8/HEAD contract', async () => {
  for (const method of ['GET', 'HEAD']) for (const route of ['/', '/agent-markdown/index.md']) {
    const request = new Request(origin + route, {method, headers: route === '/' ? {Accept: 'text/markdown'} : {Accept: '*/*'}});
    const response = await handle(request, {}, {}, data, {fetch: () => {throw Error('Unexpected origin request');}});
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Content-Type'), 'text/markdown; charset=utf-8');
    assert.equal(response.headers.get('Content-Length'), String(Buffer.byteLength('# Простір\n')));
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    assert.equal(response.headers.get('Vary'), 'Accept');
    assert.equal(response.headers.get('X-Robots-Tag'), 'noindex, nofollow');
    assert.equal(response.headers.get('Content-Signal'), 'ai-input=yes, ai-train=no, search=yes');
    assert.equal((response.headers.get('Link').match(/rel=/g) || []).length, 4);
    assert.equal(response.headers.get('X-Piskor-Markdown-Version'), data.revision);
    assert.equal(response.headers.has('x-markdown-tokens'), false);
    assert.equal(await response.text(), method === 'HEAD' ? '' : '# Простір\n');
  }
});

test('only the exact old404 rewrite query aliases serve direct Markdown', async () => {
  for (const [route, expected] of [['/agent-markdown/404-en.md?lang=en', '# English\n'], ['/agent-markdown/404.md?lang=uk', '# UK\n']]) {
    for (const method of ['GET', 'HEAD']) {
      const response = await handle(new Request(origin + route, {method}), {}, {}, data, {fetch: () => {throw Error('Unexpected origin request');}});
      assert.equal(response.headers.get('X-Piskor-Markdown-Version'), data.revision);
      assert.equal(await response.text(), method === 'HEAD' ? '' : expected);
    }
  }
  for (const route of ['/agent-markdown/404.md?lang=en', '/agent-markdown/404-en.md?lang=uk', '/agent-markdown/404-en.md?lang=en&lang=en', '/agent-markdown/404.md?lang=uk&lang=en', '/agent-markdown/404-en.md?%6cang=en', '/agent-markdown/404-en.md?lang=%65n']) {
    for (const method of ['GET', 'HEAD']) {
      const result = await passthrough(route, {method, headers: {Accept: 'text/markdown'}});
      assert.equal(result.actual, result.response);
    }
  }
});

test('negative Accept, duplicate combined values, query and unknown routes preserve response identity', async () => {
  for (const accept of [undefined, '*/*', 'text/markdown;q=0', 'text/markdown;q=1', 'text/html,text/markdown', 'text/markdown, text/markdown']) {
    const result = await passthrough('/', {headers: accept === undefined ? {} : {Accept: accept}});
    assert.equal(result.actual, result.response);
  }
  const duplicate = new Headers(); duplicate.append('Accept', 'text/markdown'); duplicate.append('Accept', 'text/markdown');
  const result = await passthrough('/', {headers: duplicate}); assert.equal(result.actual, result.response);
  for (const route of ['/?utm_source=test', '/?lang=en', '/404.html?lang=en&lang=uk', '/404.html?%6cang=en', '/404.html?lang=%65n', '/unknown/', '/agent-markdown/missing.md', '/agent-markdown/index.md?x=1', '/%65n/']) {
    const result = await passthrough(route, {headers: {Accept: 'text/markdown'}}, {}, new Response('actual404', {status: 404}));
    assert.equal(result.actual, result.response); assert.equal(result.actual.status, 404);
  }
});

test('other methods/hosts and origin exceptions are not swallowed or rewritten', async () => {
  for (const method of ['POST', 'PUT', 'OPTIONS']) {
    const result = await passthrough('/', {method, headers: {Accept: 'text/markdown'}});
    assert.equal(result.actual, result.response);
  }
  let enabled = false;
  const request = new Request(origin + '/', {headers: {Accept: 'text/html'}});
  await assert.rejects(handle(request, {}, {passThroughOnException() {enabled = true;}}, data, {fetch: () => {throw Error('origin failure');}}), /origin failure/);
  assert.equal(enabled, true);
  const foreign = new Request('https://other.test/', {headers: {Accept: 'text/markdown'}});
  const expected = new Response('foreign'); assert.equal(await handle(foreign, {}, {}, data, {fetch: seen => {assert.equal(seen, foreign); return expected;}}), expected);
});

test('bounded root HTML diagnostic adds only fixed Content-Type parameters, no arbitrary data', async () => {
  const env = {MD_DIAGNOSTIC_START: '1800000000'};
  for (const now of [1799999999, 1800000180]) {
    const result = await passthrough('/?secret=not-reflected', {headers: {Accept: 'text/html;secret=not-reflected'}}, env, undefined, now);
    assert.equal(result.actual, result.response);
  }
  const result = await passthrough('/?secret=not-reflected', {headers: {Accept: 'text/html;secret=not-reflected'}}, env);
  assert.equal(await result.actual.text(), '<html>same</html>');
  const ct = result.actual.headers.get('Content-Type');
  assert.match(ct, /query-present=yes; method=GET; accept-class=html; accept-length=\d+$/);
  assert.equal(ct.includes('secret'), false);
  assert.equal(diagnosticParameters(new Request(origin + '/portfolio/'), env, data.revision, 1800000001), null);
  assert.equal(diagnosticParameters(new Request(origin + '/'), {MD_DIAGNOSTIC_START: 'invalid'}, data.revision, 1800000001), null);
});

const bundle = process.env.PISKOR_WORKER_BUNDLE || 'output/markdown-worker/worker.mjs';
const site = process.env.PISKOR_WORKER_SITE || '_site';
test('actual generated artifact: every114 route/mode and direct MD matches exact saved bytes', {skip: !fs.existsSync(bundle) && !fs.existsSync(site)}, async () => {
  assert.ok(fs.existsSync(bundle), 'Generate Worker first');
  assert.ok(fs.existsSync(site), 'Actual Pages artifact required');
  const module = await import(pathToFileURL(path.resolve(bundle)));
  const manifest = JSON.parse(fs.readFileSync(path.join(path.dirname(bundle), 'manifest.json')));
  assert.equal(crypto.createHash('sha256').update(fs.readFileSync(bundle)).digest('hex'), manifest.bundle_sha256);
  const rows = JSON.parse(fs.readFileSync(path.join(site, 'agent-markdown/routes.json'))).pages;
  assert.equal(rows.length, 114);
  for (const row of rows) for (const method of ['GET', 'HEAD']) for (const direct of [false, true]) {
    const request = new Request(origin + (direct ? row.markdown : row.url), {method, headers: {Accept: direct ? '*/*' : 'text/markdown'}});
    const response = await module.default.fetch(request, {}, {});
    const expected = fs.readFileSync(path.join(site, row.markdown));
    assert.equal(response.headers.get('Content-Length'), String(expected.length));
    assert.equal(response.headers.get('Content-Language'), row.language);
    assert.equal(response.headers.get('X-Piskor-Markdown-Version'), manifest.revision);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), method === 'HEAD' ? Buffer.alloc(0) : expected);
  }
  const uk = await module.default.fetch(new Request(origin + '/404.html?lang=uk', {headers: {Accept: 'text/markdown'}}), {}, {});
  assert.deepEqual(Buffer.from(await uk.arrayBuffer()), fs.readFileSync(path.join(site, 'agent-markdown/404.md')));
});
