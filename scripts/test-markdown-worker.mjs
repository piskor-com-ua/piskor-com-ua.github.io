import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {brotliCompressSync, brotliDecompressSync, constants} from 'node:zlib';
import {pathToFileURL} from 'node:url';
import {handle, diagnosticParameters} from '../cloudflare/markdown-worker.mjs';

const origin = 'https://piskor.com.ua';
const data = {revision: '1'.repeat(40), pages: {'/': {markdown: '/agent-markdown/index.md'}, '/en/': {markdown: '/agent-markdown/en/index.md'}, '/404.html?lang=en': {markdown: '/agent-markdown/404-en.md'}, '/404.html?lang=uk': {markdown: '/agent-markdown/404.md'}}, documents: {}};
for (const [url, body, language] of [['/agent-markdown/index.md', '# Простір\n', 'uk'], ['/agent-markdown/en/index.md', '# Space\n', 'en'], ['/agent-markdown/404.md', '# UK\n', 'uk'], ['/agent-markdown/404-en.md', '# English\n', 'en']]) {
  data.documents[url] = {body, bytes: Buffer.byteLength(body), language};
}
const htmlRoute = '/en/portfolio/2022/zabava-restaurant-sambir/';
const sourceHtml = Buffer.from('<!doctype html><html lang="en"><meta charset="utf-8"><body>Простір · Space 🥁</body></html>\n');
const compressedHtml = brotliCompressSync(sourceHtml, {params: {[constants.BROTLI_PARAM_QUALITY]: 11}});
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const htmlItem = {bodyBase64: compressedHtml.toString('base64'), encoding: 'br', language: 'en',
  revision: data.revision, sha256: digest(sourceHtml), encodedSha256: digest(compressedHtml),
  bytes: sourceHtml.length, encodedBytes: compressedHtml.length};
const htmlData = {...data, pages: {...data.pages, [htmlRoute]: {markdown: '/agent-markdown/en/index.md'}}, html: {[htmlRoute]: htmlItem}};

test('explicit Brotli HTML is exact source bytes; HEAD and conditional responses preserve representation headers', async () => {
  let etag;
  for (const method of ['GET', 'HEAD']) {
    const response = await handle(new Request(origin + htmlRoute, {method, headers: {'Accept-Encoding': 'BR;Q=0.500', Accept: 'text/html'}}), {}, {}, htmlData,
      {fetch() {throw Error('Unexpected origin request');}});
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Content-Type'), 'text/html; charset=utf-8');
    assert.equal(response.headers.get('Content-Language'), 'en');
    assert.equal(response.headers.get('Content-Encoding'), 'br');
    assert.equal(response.headers.get('Vary'), 'Accept, Accept-Encoding');
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), '*');
    assert.equal(response.headers.get('Cache-Control'), 'public, max-age=600, no-transform');
    assert.equal(response.headers.get('X-Robots-Tag'), null);
    assert.equal(response.headers.get('Content-Signal'), 'ai-input=yes, ai-train=no, search=yes');
    assert.equal((response.headers.get('Link').match(/rel=/g) || []).length, 4);
    assert.equal(response.headers.get('X-Piskor-HTML-Version'), data.revision);
    assert.equal(response.headers.get('X-Piskor-HTML-SHA256'), digest(sourceHtml));
    assert.equal(response.headers.has('Content-Length'), false);
    etag = response.headers.get('ETag');
    assert.equal(etag, `"sha256-${digest(compressedHtml)}-br"`);
    const bytes = Buffer.from(await response.arrayBuffer());
    if (method === 'GET') assert.deepEqual(brotliDecompressSync(bytes), sourceHtml);
    else assert.equal(bytes.length, 0);
  }
  for (const method of ['GET', 'HEAD']) for (const condition of [etag, `W/${etag}`, `"other", W/${etag}`, '*']) {
    const response = await handle(new Request(origin + htmlRoute, {method, headers: {'Accept-Encoding': 'br', 'If-None-Match': condition}}), {}, {}, htmlData);
    assert.equal(response.status, 304);
    assert.equal(response.headers.get('ETag'), etag);
    assert.equal(response.headers.get('Vary'), 'Accept, Accept-Encoding');
    assert.equal(await response.text(), '');
  }
  for (const encoding of ['br', 'gzip, br;q=1', '*;q=0, br;q=0.1']) {
    const response = await handle(new Request(origin + htmlRoute, {headers: {'Accept-Encoding': encoding, 'If-None-Match': '"different"'}}), {}, {}, htmlData);
    assert.equal(response.status, 200);
  }
});

test('manual encoded response constructor is explicit; native Node does not emulate Cloudflare transport', async () => {
  const OriginalResponse = globalThis.Response;
  let options;
  globalThis.Response = class extends OriginalResponse {constructor(body, init) {super(body, init); options = init;}};
  try {
    await handle(new Request(origin + htmlRoute, {headers: {'Accept-Encoding': 'br'}}), {}, {}, htmlData);
    assert.equal(options.encodeBody, 'manual');
  } finally {globalThis.Response = OriginalResponse;}
});

test('Cloudflare original client encoding controls delivery despite its normalized header', async () => {
  for (const cf of [{clientAcceptEncoding: 'gzip'}, {clientAcceptEncoding: 'br;q=0, gzip'},
    {clientAcceptEncoding: ''}, {clientAcceptEncoding: null}, {}, null]) {
    const request = new Request(origin + htmlRoute, {headers: {'Accept-Encoding': 'br, gzip'}});
    Object.defineProperty(request, 'cf', {value: cf});
    const expected = new Response('original origin');
    assert.equal(await handle(request, {}, {}, htmlData, {fetch: seen => {assert.equal(seen, request); return expected;}}), expected);
  }
  for (const original of ['br', 'gzip, BR;q=0.500']) {
    const request = new Request(origin + htmlRoute, {headers: {'Accept-Encoding': 'br, gzip'}});
    Object.defineProperty(request, 'cf', {value: {clientAcceptEncoding: original}});
    const response = await handle(request, {}, {}, htmlData, {fetch() {throw Error('Unexpected origin request');}});
    assert.deepEqual(brotliDecompressSync(Buffer.from(await response.arrayBuffer())), sourceHtml);
  }
});

test('HTML kill switch preserves origin identity including HEAD and conditional requests, without disabling Markdown', async () => {
  const env = {HTML_PRECOMPRESSED_DISABLED: 'true'};
  for (const method of ['GET', 'HEAD']) {
    const request = new Request(origin + htmlRoute, {method, headers: {'Accept-Encoding': 'br', 'If-None-Match': '*'}});
    const expected = new Response(method === 'HEAD' ? null : 'current origin');
    assert.equal(await handle(request, env, {}, htmlData, {fetch: seen => {assert.equal(seen, request); return expected;}}), expected);
  }
  const markdown = await handle(new Request(origin + htmlRoute, {headers: {Accept: 'text/markdown', 'Accept-Encoding': 'br'}}), env, {}, htmlData);
  assert.equal(await markdown.text(), '# Space\n');
  const response = await handle(new Request(origin + htmlRoute, {headers: {'Accept-Encoding': 'br'}}), {HTML_PRECOMPRESSED_DISABLED: 'false'}, {}, htmlData);
  assert.equal(response.headers.get('Content-Encoding'), 'br');
});

test('unsupported encodings, queries, methods, foreign hosts and stale/missing representations pass through identically', async () => {
  const cases = [undefined, '', '*', '*;q=1', '*;q=0', 'gzip', 'br;q=0', 'br;q=0.000', 'br;q=.5',
    'br;q=1.1', 'br;q=0.1234', 'br;q=wat', 'br;q=1;unknown=yes', 'br, br;q=0', 'bravo'];
  for (const encoding of cases) {
    const request = new Request(origin + htmlRoute, {headers: encoding === undefined ? {} : {'Accept-Encoding': encoding}});
    const expected = new Response('origin unchanged');
    assert.equal(await handle(request, {}, {}, htmlData, {fetch: seen => {assert.equal(seen, request); return expected;}}), expected);
  }
  for (const [route, method] of [[htmlRoute + '?x=1', 'GET'], [htmlRoute + 'index.html', 'GET'],
    [htmlRoute, 'POST'], [htmlRoute, 'OPTIONS'], ['https://other.test' + htmlRoute, 'GET'], ['/404.html', 'GET']]) {
    const request = new Request(route.startsWith('https:') ? route : origin + route, {method, headers: {'Accept-Encoding': 'br'}});
    const expected = new Response('origin unchanged');
    assert.equal(await handle(request, {}, {}, htmlData, {fetch: seen => {assert.equal(seen, request); return expected;}}), expected);
  }
  for (const html of [{}, {[htmlRoute]: {...htmlItem, revision: '2'.repeat(40)}},
    {[htmlRoute]: {...htmlItem, sha256: 'bad'}}, {[htmlRoute]: {...htmlItem, bodyBase64: '!!!'}},
    {[htmlRoute]: {...htmlItem, encodedBytes: compressedHtml.length + 1}}]) {
    const expected = new Response('original');
    assert.equal(await handle(new Request(origin + htmlRoute, {headers: {'Accept-Encoding': 'br'}}), {}, {}, {...htmlData, html}, {fetch: () => expected}), expected);
  }
});

test('exact Markdown negotiation preempts selective HTML while HTML remains the default', async () => {
  for (const method of ['GET', 'HEAD']) {
    const response = await handle(new Request(origin + htmlRoute, {method, headers: {Accept: 'text/markdown', 'Accept-Encoding': 'br'}}), {}, {}, htmlData);
    assert.equal(response.headers.get('Content-Type'), 'text/markdown; charset=utf-8');
    assert.equal(response.headers.has('Content-Encoding'), false);
    assert.equal(await response.text(), method === 'HEAD' ? '' : '# Space\n');
  }
});

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
    assert.equal(response.headers.get('X-Robots-Tag'), null);
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
  for (const route of ['/?lang=en', '/404.html?lang=en&lang=uk', '/404.html?%6cang=en', '/404.html?lang=%65n', '/unknown/', '/agent-markdown/missing.md', '/agent-markdown/index.md?x=1', '/%65n/']) {
    const result = await passthrough(route, {headers: {Accept: 'text/markdown'}}, {}, new Response('actual404', {status: 404}));
    assert.equal(result.actual, result.response); assert.equal(result.actual.status, 404);
  }
});

test('home query negotiation uses canonical content except decoded lang in any position', async () => {
  for (const root of ['/', '/en/']) for (const method of ['GET', 'HEAD']) {
    const expected = root === '/' ? '# Простір\n' : '# Space\n';
    for (const query of ['?utm_source=test', '?cache=123&other=yes', '?arbitrary=a%20b', '?q=lang%3Den']) {
      const response = await handle(new Request(origin + root + query, {method, headers: {Accept: 'text/markdown', 'Accept-Language': 'en-US'}}), {}, {}, data, {fetch: () => {throw Error('Unexpected origin request');}});
      assert.equal(response.headers.get('Content-Type'), 'text/markdown; charset=utf-8');
      assert.equal(response.headers.get('Content-Length'), String(Buffer.byteLength(expected)));
      assert.equal(response.headers.get('Content-Language'), root === '/' ? 'uk' : 'en');
      assert.equal(response.headers.get('X-Piskor-Markdown-Version'), data.revision);
      assert.equal(await response.text(), method === 'HEAD' ? '' : expected);
    }
    for (const query of ['?lang=en', '?lang=uk', '?lang=', '?%6cang=en', '?l%61ng=uk', '?lang=en&lang=uk', '?other=1&lang=uk&lang=en']) {
      const result = await passthrough(root + query, {method, headers: {Accept: 'text/markdown'}});
      assert.equal(result.actual, result.response);
    }
    for (const accept of [undefined, 'text/html', '*/*', 'text/markdown;q=0', 'text/markdown;q=1', 'text/html,text/markdown', 'text/markdown, text/markdown']) {
      const result = await passthrough(root + '?utm_source=test', {method, headers: accept === undefined ? {} : {Accept: accept}});
      assert.equal(result.actual, result.response);
    }
  }
  for (const route of ['/portfolio/?cache=1', '/en/portfolio/?cache=1', '/agent-markdown/en/index.md?cache=1', '/unknown/?cache=1']) {
    const result = await passthrough(route, {headers: {Accept: 'text/markdown'}});
    assert.equal(result.actual, result.response);
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
test('actual generated artifact: every generated route/mode and direct MD matches exact saved bytes', {skip: !fs.existsSync(bundle) && !fs.existsSync(site)}, async () => {
  assert.ok(fs.existsSync(bundle), 'Generate Worker first');
  assert.ok(fs.existsSync(site), 'Actual Pages artifact required');
  const module = await import(pathToFileURL(path.resolve(bundle)));
  const manifest = JSON.parse(fs.readFileSync(path.join(path.dirname(bundle), 'manifest.json')));
  assert.equal(crypto.createHash('sha256').update(fs.readFileSync(bundle)).digest('hex'), manifest.bundle_sha256);
  const rows = JSON.parse(fs.readFileSync(path.join(site, 'agent-markdown/routes.json'))).pages;
  assert.equal(rows.length, manifest.source_page_states);
  for (const row of rows) for (const method of ['GET', 'HEAD']) for (const direct of [false, true]) {
    const request = new Request(origin + (direct ? row.markdown : row.url), {method, headers: {Accept: direct ? '*/*' : 'text/markdown'}});
    const response = await module.default.fetch(request, {}, {});
    const expected = fs.readFileSync(path.join(site, row.markdown));
    assert.equal(response.headers.get('Content-Length'), String(expected.length));
    assert.equal(response.headers.get('Content-Language'), row.language);
    assert.equal(response.headers.get('X-Piskor-Markdown-Version'), manifest.revision);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), method === 'HEAD' ? Buffer.alloc(0) : expected);
  }
  for (const root of ['/', '/en/']) for (const method of ['GET', 'HEAD']) {
    const request = new Request(origin + root + '?arbitrary=opaque&another=1', {method, headers: {Accept: 'text/markdown'}});
    const response = await module.default.fetch(request, {}, {});
    const row = rows.find(row => row.url === root);
    const expected = fs.readFileSync(path.join(site, row.markdown));
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), method === 'HEAD' ? Buffer.alloc(0) : expected);
  }
  const uk = await module.default.fetch(new Request(origin + '/404.html?lang=uk', {headers: {Accept: 'text/markdown'}}), {}, {});
  assert.deepEqual(Buffer.from(await uk.arrayBuffer()), fs.readFileSync(path.join(site, 'agent-markdown/404.md')));
  const expectedHtml = fs.readFileSync(path.join(site, htmlRoute, 'index.html'));
  const metadata = manifest.html_representations[htmlRoute];
  assert.equal(metadata.sha256, digest(expectedHtml));
  assert.equal(metadata.bytes, expectedHtml.length);
  assert.equal(metadata.revision, manifest.revision);
  for (const method of ['GET', 'HEAD']) {
    const response = await module.default.fetch(new Request(origin + htmlRoute, {method, headers: {'Accept-Encoding': 'br'}}), {}, {});
    assert.equal(response.headers.get('X-Piskor-HTML-Version'), manifest.revision);
    assert.equal(response.headers.get('X-Piskor-HTML-SHA256'), metadata.sha256);
    const encoded = Buffer.from(await response.arrayBuffer());
    if (method === 'GET') {
      assert.deepEqual(brotliDecompressSync(encoded), expectedHtml);
      assert.equal(digest(encoded), metadata.encodedSha256);
      assert.equal(encoded.length, metadata.encodedBytes);
    } else assert.equal(encoded.length, 0);
  }
});
