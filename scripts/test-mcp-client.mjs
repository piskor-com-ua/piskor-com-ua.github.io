// Exercise the real published SDK over TCP; no fixture transport or mocked SDK.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { handleMcp } from '../cloudflare/mcp-server.mjs';

export async function exerciseSdk(endpoint, expected, fetchImpl = fetch, expectedRevision) {
  assert.match(expectedRevision, /^[0-9a-f]{40}$/);
  const client = new Client({ name: 'piskor-public-acceptance', version: '1.0.0' }, { capabilities: {} });
  const transport = new StreamableHTTPClientTransport(new URL(endpoint), { fetch: fetchImpl });
  try {
    await client.connect(transport);
    assert.equal(client.getServerVersion().name, expected.contract.serverInfo.name);
    assert.equal(client.getServerVersion().version, expected.contract.serverInfo.version + '+' + expectedRevision);
    const listed = await client.listTools();
    assert.deepEqual(listed.tools, expected.contract.tools);
    for (const language of ['uk', 'en']) {
      const available = expected.projects.filter(project => project.language === language);
      const found = await client.callTool({ name: 'search_projects', arguments: { language, limit: 20 } });
      assert.equal(found.isError, undefined);
      const result = JSON.parse(found.content[0].text);
      assert.equal(result.total, available.length);
      assert.deepEqual(result.projects.map(p => p.id), available.slice(0, 20).map(p => p.id));
      if (available.length) {
        const details = await client.callTool({ name: 'get_project_details', arguments: { project_id: available[0].id, language } });
        assert.deepEqual(JSON.parse(details.content[0].text), available[0]);
      }
    }
    const contacts = await client.callTool({ name: 'get_contact_options', arguments: {} });
    assert.deepEqual(JSON.parse(contacts.content[0].text), { contacts: expected.contacts });
    const missing = await client.callTool({ name: 'get_project_details', arguments: { project_id: 'no-such-published-project' } });
    assert.equal(missing.isError, true);
    return { sdk: '@modelcontextprotocol/sdk@1.32.1', protocolVersion: '2025-11-25', tools: listed.tools.map(t => t.name) };
  } finally { await client.close(); }
}

// Convert only the bridge URL to the production URL. Origin and all client headers
// remain untouched, so the handler's production-origin and rebinding checks still run.
export async function startBridge(data, fallback = () => new Response('Not found', { status: 404 }), env = {}) {
  const observations = [];
  const server = createServer(async (incoming, outgoing) => {
    try {
      const body = [];
      for await (const chunk of incoming) body.push(chunk);
      const bytes = Buffer.concat(body);
      const request = new Request(new URL(incoming.url, 'https://piskor.com.ua'), {
        method: incoming.method, headers: incoming.headers,
        body: ['GET', 'HEAD'].includes(incoming.method) ? undefined : bytes
      });
      const response = await handleMcp(request, data, env) ?? await fallback(request);
      observations.push({ method: incoming.method, path: incoming.url, body: bytes.toString(), status: response.status, headers: Object.fromEntries(response.headers) });
      outgoing.writeHead(response.status, Object.fromEntries(response.headers));
      outgoing.end(Buffer.from(await response.arrayBuffer()));
    } catch (error) { outgoing.writeHead(500); outgoing.end(String(error)); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  return { origin: `http://127.0.0.1:${server.address().port}`, observations, close: () => new Promise(resolve => server.close(resolve)) };
}

// Importable by the deployment checker without registering a node:test case there.
if (process.argv[1]?.endsWith('/test-mcp-client.mjs') || process.argv[1] === 'scripts/test-mcp-client.mjs') {
  test('official pinned SDK initializes, notifies, lists and calls all tools via loopback HTTP', async () => {
    const contract = JSON.parse(readFileSync('agent-resources/mcp-contract.json'));
    const projects = ['uk', 'en'].map(language => ({ id: 'house', language, year: 2026, name: language === 'uk' ? 'Будинок' : 'House', summary: '398', label: 'Project', url: `/${language}/house/`, facts: [], sections: [] }));
    const data = { revision: 'a'.repeat(40), mcp: { contract, projects, contacts: [{ name: 'Phone', url: 'tel:+380974781005' }], publications: {} } };
    const rateCalls = [];
    const env = { MCP_RATE_LIMITER: { limit: async value => { rateCalls.push(value); return { success: true }; } } };
    const bridge = await startBridge(data, undefined, env);
    try {
      await exerciseSdk(bridge.origin + '/mcp', data.mcp, fetch, data.revision);
      assert.equal(rateCalls.length, 6);
      assert.ok(rateCalls.every(value => value.key === 'piskor-mcp:tools-call:v1'));
      await assert.rejects(exerciseSdk(bridge.origin + '/mcp', data.mcp, fetch, 'b'.repeat(40)), { code: 'ERR_ASSERTION' });
      assert.ok(bridge.observations.some(row => JSON.parse(row.body || '{}').method === 'initialize'));
      assert.ok(bridge.observations.some(row => JSON.parse(row.body || '{}').method === 'notifications/initialized' && row.status === 202));
      assert.ok(bridge.observations.every(row => !row.headers['mcp-session-id'] && !row.headers['set-cookie']));
      const invalidOrigin = await fetch(bridge.origin + '/mcp', { method: 'POST', headers: { Origin: bridge.origin } });
      assert.equal(invalidOrigin.status, 403);
    } finally { await bridge.close(); }
  });
}
