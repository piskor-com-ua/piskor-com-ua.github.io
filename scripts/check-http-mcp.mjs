#!/usr/bin/env node
// Bounded production acceptance. Uses a final Pages artifact as data truth and
// archives every HTTP observation, including failed fetches and response reads.
// node scripts/check-http-mcp.mjs --site _site --expected-revision <40-char-SHA>
//   --out /new/evidence-directory [--origin https://piskor.com.ua]
// --origin may be a loopback HTTP bridge for local acceptance. The bridge must
// preserve request headers and map only its URL authority to the production host.
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { runInNewContext } from 'node:vm';
import { exerciseSdk } from './test-mcp-client.mjs';

export async function checkHttpMcp({ site, expectedRevision, out, origin = 'https://piskor.com.ua' }) {
  assert.match(expectedRevision, /^[0-9a-f]{40}$/);
  const endpointOrigin = new URL(origin);
  assert.equal(endpointOrigin.pathname + endpointOrigin.search + endpointOrigin.hash, '/');
  assert.equal(endpointOrigin.username + endpointOrigin.password, '', 'Credentials are not supported');
  origin = endpointOrigin.origin;
  assert.ok(origin === 'https://piskor.com.ua' || (endpointOrigin.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(endpointOrigin.hostname)), 'Only production HTTPS or loopback HTTP is allowed');
  out = resolve(out); site = resolve(site);
  mkdirSync(out); // Refuse to overwrite earlier evidence, including failed runs.
  const report = { startedAt: new Date().toISOString(), origin, expectedRevision, site, maximumRequests: 45, observations: [], checks: [], failures: [] };
  const persist = () => writeFileSync(out + '/report.json', JSON.stringify(report, null, 2) + '\n');
  persist();
  let serial = 0;
  const observedFetch = async (url, options = {}) => {
    assert.ok(report.observations.length < report.maximumRequests, 'Request budget exhausted');
    const target = new URL(String(url));
    assert.equal(target.origin, endpointOrigin.origin, 'Verifier cannot fetch foreign origins');
    const observation = { number: report.observations.length + 1, startedAt: new Date().toISOString(), url: target.href, method: options.method ?? 'GET', requestHeaders: Object.fromEntries(new Headers(options.headers)), requestBody: options.body == null ? null : String(options.body) };
    report.observations.push(observation); persist();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(new Error('HTTP fetch/body exceeded 15 seconds')), 15000);
    const chunks = [];
    try {
      const response = await fetch(target, { ...options, signal: controller.signal, credentials: 'omit', redirect: 'manual' });
      observation.status = response.status;
      observation.responseHeaders = Object.fromEntries(response.headers);
      let size = 0;
      const reader = response.body?.getReader();
      if (reader) {
        try {
          for (;;) {
            const { value, done } = await reader.read(); if (done) break;
            size += value.byteLength;
            if (size > 1024 * 1024) { await reader.cancel(); throw Error('Response exceeds 1 MiB evidence limit'); }
            chunks.push(value);
          }
        } finally { reader.releaseLock(); }
      }
      const bytes = Buffer.concat(chunks);
      observation.responseBytes = bytes.length;
      observation.responseBody = bytes.toString('utf8');
      observation.sha256 = createHash('sha256').update(bytes).digest('hex');
      return new Response(['HEAD'].includes(observation.method) || [204, 205, 304].includes(response.status) ? null : bytes, { status: response.status, statusText: response.statusText, headers: response.headers });
    } catch (error) {
      observation.error = String(error);
      if (chunks.length) { observation.responseBodyPartial = Buffer.concat(chunks).toString('utf8'); observation.partialBytes = Buffer.concat(chunks).length; }
      throw error;
    } finally { clearTimeout(timeout); observation.finishedAt = new Date().toISOString(); persist(); }
  };
  const check = async (name, run) => {
    try { await run(); report.checks.push({ name, passed: true }); }
    catch (error) { report.checks.push({ name, passed: false }); report.failures.push({ name, error: String(error), stack: error.stack }); }
    persist();
  };
  let expected;
  try {
    expected = JSON.parse(execFileSync('python3', ['-c', 'import json,sys; sys.path.insert(0,"scripts"); from mcp_discovery import generate_mcp_data; print(json.dumps(generate_mcp_data(sys.argv[1],sys.argv[2]),ensure_ascii=False))', site, expectedRevision], { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 }));
    const version = '2026-07-28';
    const meta = { 'io.modelcontextprotocol/protocolVersion': version, 'io.modelcontextprotocol/clientInfo': { name: 'piskor-release-check', version: '1' }, 'io.modelcontextprotocol/clientCapabilities': {} };
    const rpc = async (method, params = {}, override = {}) => {
      const headers = { Accept: 'application/json, text/event-stream', 'Content-Type': 'application/json', 'MCP-Protocol-Version': version, 'Mcp-Method': method, ...(method === 'tools/call' ? { 'Mcp-Name': params.name } : {}), ...override.headers };
      for (const key of Object.keys(headers)) if (headers[key] === null) delete headers[key];
      const response = await observedFetch(origin + '/mcp' + (override.query ?? ''), { method: override.method ?? 'POST', headers, body: override.body ?? JSON.stringify({ jsonrpc: '2.0', id: ++serial, method, params: { ...params, _meta: meta } }) });
      const text = await response.text();
      return { response, json: text ? JSON.parse(text) : null, text };
    };
    const headers = response => {
      assert.equal(response.headers.get('X-Piskor-MCP-Version'), expectedRevision);
      assert.equal(response.headers.get('Cache-Control'), 'no-store');
      assert.match(response.headers.get('X-Robots-Tag'), /noindex/);
      assert.equal(response.headers.get('Content-Signal'), 'ai-input=yes, ai-train=no, search=yes');
      assert.equal(response.headers.get('Set-Cookie'), null);
      assert.equal(response.headers.get('Mcp-Session-Id'), null);
    };
    const toolOutput = result => {
      assert.equal(result.response.status, 200, result.text); headers(result.response);
      assert.equal(result.json.result.resultType, 'complete');
      assert.equal(result.json.result.isError, undefined);
      const output = JSON.parse(result.json.result.content[0].text);
      assert.deepEqual(result.json.result.structuredContent, output);
      return output;
    };
    await check('published catalog bytes equal the matching final Pages artifact', async () => {
      const response = await observedFetch(origin + '/project-catalog.json');
      assert.equal(response.status, 200);
      assert.deepEqual(Buffer.from(await response.arrayBuffer()), readFileSync(site + '/project-catalog.json'));
    });
    await check('runtime card, guide and API catalog bytes exactly match the artifact-derived snapshot', async () => {
      for (const [path, publication] of Object.entries(expected.publications)) {
        const response = await observedFetch(origin + path);
        assert.equal(response.status, 200); headers(response);
        assert.equal(response.headers.get('Content-Type'), publication.contentType);
        assert.equal(await response.text(), publication.body);
      }
      const card = JSON.parse(expected.publications['/.well-known/mcp/server-card.json'].body);
      assert.deepEqual(card.remotes, [{ type: 'streamable-http', url: 'https://piskor.com.ua/mcp', supportedProtocolVersions: expected.contract.protocolVersions }]);
      assert.equal(card.version, expected.contract.serverInfo.version + '+' + expectedRevision);
    });
    await check('modern discovery and tools/list implement the same exact three-tool contract', async () => {
      const discovery = await rpc('server/discover');
      assert.equal(discovery.response.status, 200); headers(discovery.response);
      assert.equal(discovery.json.result.resultType, 'complete');
      assert.deepEqual(discovery.json.result.supportedVersions, expected.contract.protocolVersions);
      assert.deepEqual(discovery.json.result.capabilities, { tools: {} });
      assert.equal(discovery.json.result._meta['io.modelcontextprotocol/serverInfo'].version, expected.contract.serverInfo.version + '+' + expectedRevision);
      const listing = await rpc('tools/list');
      assert.equal(listing.response.status, 200); headers(listing.response);
      assert.deepEqual(listing.json.result.tools, expected.contract.tools);
    });
    const tools = [];
    const browserSource = readFileSync('concept/agent-tools.js', 'utf8');
    runInNewContext(browserSource, { document: { modelContext: { registerTool: tool => tools.push(tool) }, documentElement: { lang: 'uk' }, querySelectorAll: () => expected.contacts.map(c => ({ textContent: c.name, getAttribute: () => c.url })) }, navigator: {}, fetch: async () => ({ ok: true, json: async () => JSON.parse(readFileSync(site + '/project-catalog.json')) }) });
    await check('both languages and full section search equal actual browser WebMCP and artifact facts', async () => {
      for (const language of ['uk', 'en']) {
        const first = expected.projects.find(p => p.language === language);
        assert.ok(first);
        const section = first.sections.find(s => s.text.trim());
        assert.ok(section, 'Published project must have section text');
        const query = section.text.trim().split(/\s+/).slice(0, 3).join(' ').slice(0, 190);
        for (const args of [{ language, limit: 20 }, { language, query, year: first.year }]) {
          assert.deepEqual(toolOutput(await rpc('tools/call', { name: 'search_projects', arguments: args })), JSON.parse(await tools[0].execute(args)));
        }
        assert.deepEqual(toolOutput(await rpc('tools/call', { name: 'get_project_details', arguments: { project_id: first.id, language } })), first);
      }
      assert.deepEqual(toolOutput(await rpc('tools/call', { name: 'get_contact_options', arguments: {} })), { contacts: expected.contacts });
      const defaultResult = await rpc('tools/call', { name: 'search_projects', arguments: {} }, { headers: { 'Accept-Language': 'en' } });
      assert.deepEqual(toolOutput(defaultResult), JSON.parse(await tools[0].execute({})));
    });
    await check('transport rejects unknown methods, invalid input, Origin, media, metadata, query and oversized body', async () => {
      const fixtures = [
        ['unknown/method', {}, {}, 404, -32601],
        ['tools/call', { name: 'search_projects', arguments: null }, {}, 400, -32602],
        ['tools/list', {}, { headers: { Origin: 'https://invalid.example' } }, 403],
        ['tools/list', {}, { headers: { Accept: 'application/json;q=0, text/event-stream' } }, 406],
        ['tools/list', {}, { headers: { 'Content-Type': 'text/plain' } }, 415],
        ['tools/list', {}, { headers: { 'Mcp-Method': 'ping' } }, 400, -32020],
        ['tools/list', {}, { query: '?x=1' }, 400],
        ['tools/list', {}, { body: 'x'.repeat(16385) }, 413]
      ];
      for (const [method, params, options, status, code] of fixtures) {
        const result = await rpc(method, params, options);
        assert.equal(result.response.status, status, result.text); headers(result.response);
        if (code !== undefined) assert.equal(result.json.error.code, code);
      }
      for (const method of ['GET', 'HEAD', 'DELETE']) {
        const response = await observedFetch(origin + '/mcp', { method });
        assert.equal(response.status, 405); headers(response);
        if (method === 'HEAD') assert.equal(await response.text(), '');
      }
    });
    await check('recognized tool input validation returns a recoverable tool result', async () => {
      const result = await rpc('tools/call', { name: 'search_projects', arguments: { limit: 21 } });
      assert.equal(result.response.status, 200); headers(result.response);
      assert.equal(result.json.result.isError, true);
      assert.equal(result.json.result.resultType, 'complete');
      assert.ok(result.json.result.content[0].text);
    });
    await check('official SDK 1.32.1 legacy client works over real HTTP for all tools and both languages', async () => {
      report.sdk = await exerciseSdk(origin + '/mcp', expected, observedFetch, expectedRevision);
    });
  } catch (error) { report.failures.push({ name: 'verifier setup or execution', error: String(error), stack: error.stack }); }
  finally { report.finishedAt = new Date().toISOString(); report.passed = report.failures.length === 0; persist(); }
  return report;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), options = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = { '--site': 'site', '--expected-revision': 'expectedRevision', '--out': 'out', '--origin': 'origin' }[args[i]];
    assert.ok(key && args[i + 1] && !Object.hasOwn(options, key), 'Usage: node scripts/check-http-mcp.mjs --site <final-Pages-artifact> --expected-revision <SHA> --out <new-directory> [--origin https://piskor.com.ua]');
    options[key] = args[i + 1];
  }
  assert.ok(options.site && options.expectedRevision && options.out, '--site, --expected-revision and --out are required');
  const report = await checkHttpMcp(options);
  console.log(JSON.stringify({ passed: report.passed, requests: report.observations.length, failures: report.failures, report: resolve(options.out, 'report.json') }, null, 2));
  if (!report.passed) process.exitCode = 1;
}
