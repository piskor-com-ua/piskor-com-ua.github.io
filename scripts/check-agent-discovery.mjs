import { readFileSync, existsSync } from 'node:fs';
import assert from 'node:assert/strict';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { ConformanceTester } from 'lighthouse/third-party/ard/ard.js';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const source = readFileSync('_site/.well-known/ard.json', 'utf8');
assert.equal(source, readFileSync('_site/.well-known/ai-catalog.json', 'utf8'));
const catalog = JSON.parse(source);
const schema = JSON.parse(readFileSync('scripts/schemas/ard-entry.schema.json', 'utf8'));
const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema(schema);
const validate = ajv.compile({ $ref: schema.$id + '#/$defs/ArdManifest' });
assert.ok(validate(catalog), JSON.stringify(validate.errors));
const legacy = new ConformanceTester();
legacy.validate_manifest(source, 'ai-catalog.json');
assert.deepEqual(legacy.errors, []);
assert.deepEqual(legacy.warnings, []);
assert.ok(catalog.entries.length);

// Validate actual registered tool schemas, without a browser or network request.
const { runInNewContext } = await import('node:vm');
const tools = [];
runInNewContext(readFileSync('concept/agent-tools.js', 'utf8'), {
  document: { modelContext: { registerTool: tool => tools.push(tool) }, documentElement: { lang: 'uk' } },
  navigator: {}, fetch: () => { throw Error('Registration must not fetch a catalog'); }
});
for (const tool of tools) assert.ok(ajv.compile(JSON.parse(JSON.stringify(tool.inputSchema))));
for (const entry of catalog.entries) {
  assert.ok(entry.identifier.startsWith('urn:air:piskor.com.ua:'));
  assert.ok(entry.representativeQueries.length >= 2 && entry.representativeQueries.length <= 5);
  assert.deepEqual(entry.capabilities, tools.map(tool => tool.name));
  const url = new URL(entry.url);
  assert.equal(url.origin, 'https://piskor.com.ua');
  assert.ok(existsSync('_site' + url.pathname));
  const skill = readFileSync('_site' + url.pathname, 'utf8');
  for (const tool of tools) assert.ok(skill.includes('`' + tool.name + '`'));
}
console.log(`Agent discovery: current ARD schema and Lighthouse ${require('lighthouse/package.json').version} conformance passed; ${tools.length} WebMCP input schemas compiled.`);
