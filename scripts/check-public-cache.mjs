#!/usr/bin/env node
// Production proof for monthly edge caching. No configuration changes, browser
// state, cache-busting queries or private credentials. Keep every failed probe.
import assert from 'node:assert/strict';
import {mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';

const options = {};
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  assert.ok(['--site', '--revision', '--out', '--known-html-injection'].includes(key) && process.argv[index + 1] && !options[key]);
  options[key] = process.argv[index + 1];
}
const site = resolve(options['--site'] || '_site'), revision = options['--revision'];
assert.match(revision || '', /^[a-f0-9]{40}$/);
assert.ok(options['--out'], 'Supply a new evidence directory');
const out = resolve(options['--out']);
mkdirSync(out); mkdirSync(out + '/bodies');
const origin = 'https://piskor.com.ua';
const sha = body => createHash('sha256').update(body).digest('hex');
const policy = JSON.parse(readFileSync('cloudflare/cache-policy.json'));
const beacon = options['--known-html-injection'] ? readFileSync(options['--known-html-injection'], 'utf8') : null;
const inventory = JSON.parse(execFileSync('python3', ['-c', 'import json,sys; sys.path.insert(0,"scripts"); from cache_policy import inventory; print(json.dumps(inventory(sys.argv[1],sys.argv[2])))', site, revision], {encoding: 'utf8', maxBuffer: 16 * 1024 * 1024}));
const mcp = JSON.parse(execFileSync('python3', ['-c', 'import json,sys; sys.path.insert(0,"scripts"); from mcp_discovery import generate_mcp_data; print(json.dumps(generate_mcp_data(sys.argv[1],sys.argv[2])))', site, revision], {encoding: 'utf8', maxBuffer: 8 * 1024 * 1024}));
const report = {startedAt: new Date().toISOString(), revision, policySha256: sha(readFileSync('cloudflare/cache-policy.json')),
  edgeMinimum: policy.edge_min_ttl, artifactFiles: Object.keys(inventory.files).length,
  validatedVersionedUrls: Object.keys(inventory.versioned_urls).length,
  scope: 'Every public stable document plus representative versioned assets; TTL also requires saved control-plane proof.',
  observations: [], failures: []};
const save = () => writeFileSync(out + '/report.json', JSON.stringify(report, null, 2) + '\n');
let serial = 0;
async function probe(item, attempt) {
  const number = serial++;
  const row = {number, path: item.path, kind: item.kind, attempt, at: new Date().toISOString(), method: item.video && attempt === 1 ? 'HEAD' : 'GET'};
  report.observations.push(row);
  try {
    const response = await fetch(origin + item.path, {method: row.method, redirect: 'manual', credentials: 'omit',
      signal: AbortSignal.timeout(15000), headers: {Accept: item.kind === 'html' ? 'text/html' : '*/*',
        ...(item.video && attempt === 2 ? {Range: 'bytes=0-4095'} : {})}});
    row.status = response.status;
    row.headers = Object.fromEntries([...response.headers].filter(([name]) => name !== 'set-cookie'));
    row.setCookiePresent = response.headers.has('set-cookie');
    const chunks = []; let received = 0;
    const reader = response.body?.getReader();
    if (reader) try {
      for (;;) {
        const {done, value} = await reader.read(); if (done) break;
        received += value.byteLength;
        if (received > 1024 * 1024) {await reader.cancel(); throw Error('Probe exceeded the public-body bound');}
        chunks.push(value);
      }
    } finally {reader.releaseLock();}
    const body = Buffer.concat(chunks);
    row.bytes = body.length; row.sha256 = sha(body);
    writeFileSync(out + '/bodies/' + String(number).padStart(4, '0') + '.body', body);
    assert.equal(response.status, item.video && attempt === 2 ? 206 : 200);
    let compared = body;
    if (item.kind === 'html' && beacon && body.toString('utf8').split(beacon).length === 2 && !item.expected.toString('utf8').includes(beacon)) {
      compared = Buffer.from(body.toString('utf8').replace(beacon, ''));
      row.knownHtmlInjection = true;
    }
    if (item.video && attempt === 1) {
      assert.equal(body.length, 0);
      assert.equal(Number(response.headers.get('Content-Length')), item.expected.length);
    } else {
      const expected = item.video ? item.expected.subarray(0, 4096) : item.expected;
      row.expectedSha256 = sha(expected); row.byteEqual = compared.equals(expected);
      assert.ok(row.byteEqual, 'Published bytes differ from the matching artifact');
    }
    if (item.kind === 'worker-document') {
      assert.ok(['MISS', 'HIT'].includes(response.headers.get('X-Piskor-Edge-Cache')), 'Document cache unavailable, errored or repaired');
      assert.equal(response.headers.get('X-Piskor-Edge-TTL'), String(policy.edge_min_ttl));
      assert.equal(response.headers.get('X-Piskor-Edge-Key'), item.path + '?v=' + sha(item.expected));
      assert.equal(response.headers.get('X-Piskor-Edge-Purge-Prefix'), 'piskor.com.ua' + item.path);
      assert.equal(response.headers.get(item.publication ? 'X-Piskor-MCP-Version' : 'X-Piskor-Markdown-Version'), revision);
      assert.equal(response.headers.get('Cache-Control'), 'no-store', 'Browser must not retain an obsolete protocol revision');
      if (attempt === 2) assert.equal(response.headers.get('X-Piskor-Edge-Cache'), 'HIT');
    } else {
      if (attempt === 2) assert.equal(response.headers.get('CF-Cache-Status'), 'HIT');
      if (item.kind === 'versioned-asset') {
        const maxAge = /(?:^|[,\s])max-age=(\d+)/.exec(response.headers.get('Cache-Control') || '');
        assert.ok(maxAge && Number(maxAge[1]) >= policy.versioned_browser_ttl, 'Versioned browser TTL below one month');
      } else {
        assert.match(response.headers.get('Cache-Control') || '', /no-store|no-cache|max-age=0(?:[,\s]|$)/,
          'Mutable browser document must revalidate after CDN purge');
      }
    }
  } catch (error) {
    row.error = String(error); report.failures.push({path: item.path, attempt, error: String(error)});
  } finally {save();}
}

const items = [];
for (const relative of inventory.stable_documents) {
  const path = inventory.files[relative].urls[0];
  if (Object.hasOwn(mcp.publications, path)) continue;
  items.push({path, kind: relative.endsWith('.md') && relative.startsWith('agent-markdown/') ? 'worker-document' : relative.endsWith('.html') ? 'html' : 'stable-document',
    expected: readFileSync(site + '/' + relative)});
}
for (const [path, publication] of Object.entries(mcp.publications)) {
  items.push({path, kind: 'worker-document', publication: true, expected: Buffer.from(publication.body)});
}
const selectedExtensions = new Set();
for (const [path, relative] of Object.entries(inventory.versioned_urls)) {
  const extension = relative.split('.').pop();
  if (selectedExtensions.has(extension)) continue;
  selectedExtensions.add(extension);
  items.push({path, kind: 'versioned-asset', video: extension === 'mp4', expected: readFileSync(site + '/' + relative)});
}
let next = 0;
await Promise.all(Array.from({length: 6}, async () => {
  while (next < items.length) {
    const item = items[next++];
    await probe(item, 1); await probe(item, 2);
  }
}));
report.finishedAt = new Date().toISOString();
report.passed = report.failures.length === 0;
save();
console.log(JSON.stringify({passed: report.passed, requests: report.observations.length, failures: report.failures.length, report: out + '/report.json'}));
if (!report.passed) process.exitCode = 1;
