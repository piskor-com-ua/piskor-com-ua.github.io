// Independent black-box checks of the public handler: no handler helpers imported.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { handleMcp } from '../cloudflare/mcp-server.mjs';

const contract = JSON.parse(readFileSync('agent-resources/mcp-contract.json'));
const revision = 'a'.repeat(40);
const projects = [
  { id: 'house', language: 'uk', year: 2026, name: 'Будинок', url: '/portfolio/2026/house/', summary: '398 м²', label: 'Проєкт', facts: [{ value: 'Брюховичі' }], sections: [{ title: 'Світло', text: 'Підсвічування ніш та м’яке світло', url: '/portfolio/2026/house/#lighting' }] },
  { id: 'house', language: 'en', year: 2026, name: 'House', url: '/en/portfolio/2026/house/', summary: '398 m²', label: 'Project', facts: [{ value: 'Lviv' }], sections: [{ title: 'Lighting', text: 'Recessed accent illumination', url: '/en/portfolio/2026/house/#lighting' }] }
];
const contacts = [{ name: 'WhatsApp', url: 'https://wa.me/380974781005' }];
const publications = { '/.well-known/mcp/server-card.json': { body: '{"name":"piskor-portfolio"}', contentType: 'application/json' } };
const data = { revision, mcp: { contract, projects, contacts, publications } };
const allowEnv = { MCP_RATE_LIMITER: { limit: async () => ({ success: true }) } };
const serve = (request, snapshot = data, env = allowEnv) => handleMcp(request, snapshot, env);
const version = '2026-07-28';
const meta = () => ({ 'io.modelcontextprotocol/protocolVersion': version, 'io.modelcontextprotocol/clientInfo': { name: 'independent-qa', version: '1' }, 'io.modelcontextprotocol/clientCapabilities': {} });
function request(method = 'tools/list', params = {}, options = {}) {
  const body = options.body ?? { jsonrpc: '2.0', id: 42, method, params: { ...params, _meta: meta() } };
  const headers = new Headers({ Accept: 'application/json, text/event-stream', 'Content-Type': 'application/json', 'MCP-Protocol-Version': version, 'Mcp-Method': method });
  if (method === 'tools/call') headers.set('Mcp-Name', params.name);
  for (const [key, value] of Object.entries(options.headers ?? {})) value === null ? headers.delete(key) : headers.set(key, value);
  return new Request(options.url ?? 'https://piskor.com.ua/mcp', { method: options.method ?? 'POST', headers, body: ['GET', 'HEAD'].includes(options.method) ? undefined : (typeof body === 'string' ? body : JSON.stringify(body)) });
}
async function invoke(method, params = {}, options = {}) {
  const response = await serve(request(method, params, options), data);
  assert.ok(response instanceof Response);
  const raw = await response.text();
  return { response, raw, json: raw ? JSON.parse(raw) : null };
}
function securityHeaders(response, card = false) {
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(response.headers.get('X-Robots-Tag'), null);
  assert.equal(response.headers.get('Content-Signal'), 'ai-input=yes, ai-train=no, search=yes');
  assert.equal(response.headers.get('X-Piskor-MCP-Version'), revision);
  assert.equal(response.headers.get('Mcp-Session-Id'), null);
  assert.equal(response.headers.get('Set-Cookie'), null);
  if (!card) assert.notEqual(response.headers.get('Access-Control-Allow-Origin'), '*');
}
async function error(method, params, options, status, code) {
  const result = await invoke(method, params, options);
  assert.equal(result.response.status, status, result.raw);
  if (code !== undefined) assert.equal(result.json.error.code, code, result.raw);
  return result;
}
function output(result) {
  assert.equal(result.response.status, 200, result.raw);
  assert.equal(result.json.result.isError, undefined);
  assert.equal(result.json.result.resultType, 'complete');
  return JSON.parse(result.json.result.content[0].text);
}

test('modern discovery, list and result metadata advertise only the implemented read-only contract', async () => {
  const discovered = await invoke('server/discover');
  securityHeaders(discovered.response);
  assert.equal(discovered.json.id, 42);
  assert.equal(discovered.json.result.resultType, 'complete');
  assert.deepEqual(discovered.json.result.supportedVersions, contract.protocolVersions);
  assert.deepEqual(discovered.json.result.capabilities, { tools: {} });
  assert.equal(discovered.json.result._meta['io.modelcontextprotocol/serverInfo'].name, contract.serverInfo.name);
  const listed = await invoke('tools/list');
  assert.deepEqual(listed.json.result.tools, contract.tools);
  assert.equal(listed.json.result.resultType, 'complete');
  assert.ok(listed.json.result.tools.every(t => t.annotations.readOnlyHint && !t.annotations.destructiveHint));
});

test('actual browser WebMCP execution and HTTP results match in both languages, Unicode and section-only search', async () => {
  const tools = [];
  let fetches = 0;
  runInNewContext(readFileSync('concept/agent-tools.js', 'utf8'), {
    document: { modelContext: { registerTool: t => tools.push(t) }, documentElement: { lang: 'uk' }, querySelectorAll: () => contacts.map(c => ({ textContent: c.name + '↗', getAttribute: () => c.url })) },
    navigator: {}, fetch: async () => { fetches++; return { ok: true, json: async () => ({ version: 1, projects }) }; }
  });
  for (const args of [{}, { language: 'uk', query: 'Підсвічування ніш' }, { language: 'en', query: 'RECESSED illumination', year: 2026, limit: 1 }, { query: "м'яке" }, { query: 'no match' }, { year: 2025 }, { query: '😀'.repeat(101) }, { query: '😀'.repeat(200) }]) {
    assert.deepEqual(output(await invoke('tools/call', { name: 'search_projects', arguments: args })), JSON.parse(await tools[0].execute(args)));
  }
  for (const language of ['uk', 'en']) assert.deepEqual(output(await invoke('tools/call', { name: 'get_project_details', arguments: { project_id: 'house', language } })), JSON.parse(await tools[1].execute({ project_id: 'house', language })));
  assert.deepEqual(output(await invoke('tools/call', { name: 'get_contact_options', arguments: {} })), JSON.parse(await tools[2].execute({})));
  assert.equal(fetches, 1);
});

test('HTTP default is Ukrainian independently of Accept-Language and repeat calls need no session', async () => {
  const args = { name: 'search_projects', arguments: {} };
  const first = await invoke('tools/call', args, { headers: { 'Accept-Language': 'en' } });
  assert.equal(output(first).projects[0].name, 'Будинок');
  assert.deepEqual(output(await invoke('tools/call', args, { headers: { 'Mcp-Session-Id': 'untrusted' } })), output(first));
  securityHeaders(first.response);
});

test('malformed tool calls are protocol errors and known-tool schema failures are tool results', async () => {
  for (const args of [null, [], 1, 'bad']) await error('tools/call', { name: 'search_projects', arguments: args }, {}, 400, -32602);
  const invalidTool = async (name, args) => {
    const result = await invoke('tools/call', { name, arguments: args });
    assert.equal(result.response.status, 200, result.raw);
    assert.equal(result.json.result.isError, true);
    assert.equal(result.json.result.resultType, 'complete');
    assert.ok(result.json.result.content[0].text);
    assert.equal(result.json.error, undefined);
    securityHeaders(result.response);
  };
  for (const args of [{ extra: true }, { language: 'ru' }, { query: [] }, { query: 'x'.repeat(201) }, { query: '😀'.repeat(201) }, { year: '2026' }, { year: 1899 }, { year: 2101 }, { year: 2026.5 }, { limit: 0 }, { limit: 21 }, { limit: 1.5 }]) await invalidTool('search_projects', args);
  for (const args of [{}, { project_id: '../private' }, { project_id: 'x'.repeat(101) }, { project_id: 'house', language: 'xx' }, { project_id: 'missing' }]) await invalidTool('get_project_details', args);
  await invalidTool('get_contact_options', { send: true });
  const legacy = await invoke('tools/call', {}, { headers: { 'MCP-Protocol-Version': '2025-11-25', 'Mcp-Method': null }, body: { jsonrpc: '2.0', id: 51, method: 'tools/call', params: { name: 'search_projects', arguments: { limit: 21 } } } });
  assert.equal(legacy.response.status, 200);
  assert.equal(legacy.json.result.isError, true);
  assert.equal(legacy.json.result.resultType, undefined);
  await error('tools/call', { name: 'send_message', arguments: {} }, {}, 400, -32602);
});

test('modern required mirrored headers and metadata reject missing, mismatched and duplicate fields', async () => {
  for (const headers of [{ 'Mcp-Method': null }, { 'Mcp-Method': 'ping' }, { 'MCP-Protocol-Version': null }, { 'MCP-Protocol-Version': `${version}, ${version}` }]) await error('tools/list', {}, { headers }, 400, -32020);
  for (const value of [null, 'wrong', 'search_projects, search_projects']) await error('tools/call', { name: 'search_projects', arguments: {} }, { headers: { 'Mcp-Name': value } }, 400, -32020);
  const encoded = `=?base64?${Buffer.from('search_projects').toString('base64')}?=`;
  assert.equal((await invoke('tools/call', { name: 'search_projects', arguments: {} }, { headers: { 'Mcp-Name': encoded } })).response.status, 200);
  await error('tools/list', {}, { body: { jsonrpc: '2.0', id: 42, method: 'tools/list', params: {} } }, 400);
  const bad = { ...meta(), 'io.modelcontextprotocol/protocolVersion': '2099-01-01' };
  const unsupported = await error('tools/list', {}, { body: { jsonrpc: '2.0', id: 42, method: 'tools/list', params: { _meta: bad } }, headers: { 'MCP-Protocol-Version': '2099-01-01' } }, 400, -32022);
  assert.deepEqual(unsupported.json.error.data.supported, contract.protocolVersions);
});

test('JSON-RPC malformed inputs, unknown methods and client responses are protocol errors', async () => {
  await error('tools/list', {}, { body: '{' }, 400, -32700);
  for (const body of [[], null, 42, { jsonrpc: '1.0', id: 1, method: 'tools/list' }, { jsonrpc: '2.0', id: {}, method: 'tools/list' }, { jsonrpc: '2.0', id: 1, result: {} }]) await error('tools/list', {}, { body: JSON.stringify(body) }, 400, -32600);
  await error('unknown/method', {}, {}, 404, -32601);
  await error('resources/list', {}, {}, 404, -32601);
});

test('legacy initialize and initialized are stateless and notification responses have no body', async () => {
  const init = await invoke('initialize', {}, { headers: { 'MCP-Protocol-Version': null, 'Mcp-Method': null }, body: { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'qa', version: '1' } } } });
  assert.equal(init.response.status, 200, init.raw);
  assert.equal(init.json.result.protocolVersion, '2025-11-25');
  assert.equal(init.json.result.resultType, undefined);
  securityHeaders(init.response);
  const notified = await invoke('notifications/initialized', {}, { headers: { 'MCP-Protocol-Version': '2025-11-25', 'Mcp-Method': null }, body: { jsonrpc: '2.0', method: 'notifications/initialized' } });
  assert.equal(notified.response.status, 202);
  assert.equal(notified.raw, '');
  const listing = await invoke('tools/list', {}, { headers: { 'MCP-Protocol-Version': '2025-11-25', 'Mcp-Method': null }, body: { jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} } });
  assert.deepEqual(listing.json.result.tools, contract.tools);
  assert.equal(listing.json.result.resultType, undefined);
});

test('transport MIME, quality, Origin, query and verbs are constrained without wildcard CORS', async () => {
  for (const origin of ['null', 'https://evil.example', 'https://piskor.com.ua.evil.example', 'http://piskor.com.ua', 'https://piskor.com.ua/']) await error('tools/list', {}, { headers: { Origin: origin } }, 403);
  assert.equal((await invoke('tools/list', {}, { headers: { Origin: 'https://piskor.com.ua' } })).response.status, 200);
  for (const accept of ['text/html', 'application/json', 'text/event-stream', 'application/json;q=0, text/event-stream', 'application/json, text/event-stream;q=0', 'application/json;q=oops, text/event-stream', 'application/json;q=1.1, text/event-stream', 'application/json;q=0.1234, text/event-stream', 'application/json;q=1;q=0, text/event-stream']) await error('tools/list', {}, { headers: { Accept: accept } }, 406);
  assert.equal((await invoke('tools/list', {}, { headers: { Accept: 'application/json;q=0.5, text/event-stream;q=0.4' } })).response.status, 200);
  for (const mime of ['text/plain', 'application/json, application/json', 'application/jsonx']) await error('tools/list', {}, { headers: { 'Content-Type': mime } }, 415);
  await error('tools/list', {}, { url: 'https://piskor.com.ua/mcp?query=1' }, 400);
  await error('tools/list', {}, { url: 'https://piskor.com.ua/mcp?' }, 400);
  for (const method of ['GET', 'HEAD', 'DELETE', 'PUT']) {
    const response = await serve(new Request('https://piskor.com.ua/mcp', { method }), data);
    assert.equal(response.status, 405);
    if (method === 'HEAD') assert.equal(await response.text(), '');
  }
  assert.equal(await serve(new Request('https://piskor.com.ua/portfolio/'), data), null);
  assert.equal((await serve(new Request('https://elsewhere.example/mcp'), data)).status, 403);
});

test('bounded streaming body reader cancels over-limit input without trusting Content-Length', async () => {
  let pulls = 0, cancelled = false;
  const stream = new ReadableStream({ pull(controller) { pulls++; controller.enqueue(new Uint8Array(1024)); }, cancel() { cancelled = true; } }, { highWaterMark: 0 });
  const base = request();
  const response = await serve(new Request(base.url, { method: 'POST', headers: base.headers, body: stream, duplex: 'half' }), data);
  assert.equal(response.status, 413);
  assert.ok(pulls <= 17, `read ${pulls} KiB`);
  assert.equal(cancelled, true);
  await error('tools/list', {}, { body: 'x'.repeat(16385), headers: { 'Content-Length': '1' } }, 413);
});

test('runtime discovery is exact GET/HEAD, immutable supplied bytes with revision and security headers', async () => {
  const path = '/.well-known/mcp/server-card.json';
  for (const method of ['GET', 'HEAD']) {
    const response = await serve(new Request('https://piskor.com.ua' + path, { method }), data);
    assert.equal(response.status, 200); securityHeaders(response, true);
    assert.match(response.headers.get('Content-Type'), /^application\/json/);
    assert.equal(await response.text(), method === 'HEAD' ? '' : publications[path].body);
  }
  assert.equal(await serve(new Request('https://piskor.com.ua' + path + '?x=1'), data), null);
  const crossOrigin = await serve(new Request('https://piskor.com.ua' + path, { headers: { Origin: 'https://example.org' } }), data);
  assert.equal(crossOrigin.status, 200);
  assert.equal(crossOrigin.headers.get('Access-Control-Allow-Origin'), '*');
});

test('read-only runtime does not fetch, mutate embedded facts, log, or create credentials', async () => {
  const before = JSON.stringify(data), originalFetch = globalThis.fetch;
  const originals = Object.fromEntries(['log', 'warn', 'error', 'info', 'debug'].map(key => [key, console[key]]));
  for (const key of Object.keys(originals)) console[key] = () => { throw Error('Runtime logs forbidden'); };
  globalThis.fetch = () => { throw Error('Runtime network forbidden'); };
  try {
    for (const name of contract.tools.map(t => t.name)) {
      const result = await invoke('tools/call', { name, arguments: name === 'get_project_details' ? { project_id: 'house' } : {} });
      assert.equal(result.response.status, 200); securityHeaders(result.response);
    }
    assert.equal(JSON.stringify(data), before);
  } finally { globalThis.fetch = originalFetch; Object.assign(console, originals); }
});

test('exact 16 KiB request boundary is accepted and overlarge published results fail boundedly', async () => {
  const base = request();
  const body = await base.text();
  const bytes = Buffer.byteLength(body);
  const accepted = await serve(new Request(base.url, { method: 'POST', headers: base.headers, body: body + ' '.repeat(16384 - bytes) }), data);
  assert.equal(accepted.status, 200);
  const tooLarge = structuredClone(data);
  tooLarge.mcp.projects[0].sections[0].text = 'x'.repeat(256 * 1024);
  const response = await serve(request('tools/call', { name: 'get_project_details', arguments: { project_id: 'house' } }), tooLarge);
  assert.equal(response.status, 500);
  const raw = await response.text();
  assert.ok(Buffer.byteLength(raw) < 1024);
  assert.equal(JSON.parse(raw).error.code, -32603);
});

test('tools require a real limiter binding and fail closed on denial or outage before data execution', async () => {
  const noExecution = { ...data, mcp: { ...data.mcp } };
  Object.defineProperty(noExecution.mcp, 'projects', { get() { throw Error('Tool executed during denied/outage request'); } });
  const call = () => request('tools/call', { name: 'search_projects', arguments: {} });
  const cases = [
    [{}, 503],
    [{ MCP_RATE_LIMITER: {} }, 503],
    [{ MCP_RATE_LIMITER: { limit: async () => { throw Error('Binding unavailable'); } } }, 503],
    [{ MCP_RATE_LIMITER: { limit: async () => undefined } }, 503],
    [{ MCP_RATE_LIMITER: { limit: async () => ({}) } }, 503],
    [{ MCP_RATE_LIMITER: { limit: async () => ({ success: 'true' }) } }, 503],
    [{ MCP_RATE_LIMITER: { limit: async () => ({ success: false }) } }, 429]
  ];
  for (const [env, status] of cases) {
    const response = await handleMcp(call(), noExecution, env);
    assert.equal(response.status, status);
    securityHeaders(response);
    if (status === 429) assert.equal(response.headers.get('Retry-After'), '60');
    assert.ok((await response.json()).error);
  }
});

test('only tool execution consumes the same anonymous fixed rate-limit key', async () => {
  const calls = [];
  const env = { MCP_RATE_LIMITER: { limit: async options => { calls.push(options); return { success: true }; } } };
  for (const method of ['server/discover', 'tools/list']) {
    assert.equal((await handleMcp(request(method), data, env)).status, 200);
    assert.equal((await handleMcp(request(method), data, {})).status, 200);
  }
  const initialize = request('initialize', {}, { headers: { 'MCP-Protocol-Version': null, 'Mcp-Method': null }, body: { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'qa', version: '1' } } } });
  assert.equal((await handleMcp(initialize, data, env)).status, 200);
  assert.equal(await handleMcp(new Request('https://piskor.com.ua/portfolio/'), data, env), null);
  assert.equal((await handleMcp(new Request('https://piskor.com.ua/.well-known/mcp/server-card.json'), data, env)).status, 200);
  for (const params of [{ name: 'unknown_tool', arguments: {} }, { name: 'search_projects', arguments: null }, { name: 'search_projects', arguments: { limit: 21 } }]) {
    await handleMcp(request('tools/call', params), data, env);
  }
  const invalidOrigin = await handleMcp(request('tools/call', { name: 'search_projects', arguments: {} }, { headers: { Origin: 'https://invalid.example' } }), data, env);
  assert.equal(invalidOrigin.status, 403);
  assert.equal(calls.length, 0);
  for (const name of contract.tools.map(tool => tool.name)) {
    const response = await handleMcp(request('tools/call', { name, arguments: name === 'get_project_details' ? { project_id: 'house' } : {} }, { headers: { 'CF-Connecting-IP': '192.0.2.1', 'User-Agent': 'fixture' } }), data, env);
    assert.equal(response.status, 200);
  }
  assert.equal(calls.length, 3);
  assert.deepEqual(calls, Array.from({ length: 3 }, () => ({ key: 'piskor-mcp:tools-call:v1' })));
});
