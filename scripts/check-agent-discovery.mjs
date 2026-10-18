import { readFileSync, existsSync } from 'node:fs';
import assert from 'node:assert/strict';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { ConformanceTester } from 'lighthouse/third-party/ard/ard.js';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';

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

const skillsIndexUrl = new URL('https://piskor.com.ua/.well-known/agent-skills/index.json');
const skillsIndex = JSON.parse(readFileSync('_site' + skillsIndexUrl.pathname, 'utf8'));
const skillsSchema = JSON.parse(readFileSync('scripts/schemas/agent-skills-discovery.schema.json', 'utf8'));
const validateSkills = ajv.compile(skillsSchema);
assert.ok(validateSkills(skillsIndex), JSON.stringify(validateSkills.errors));
assert.ok(skillsIndex.skills.length, 'Publish at least one real skill');
assert.equal(new Set(skillsIndex.skills.map(skill => skill.name)).size, skillsIndex.skills.length);
for (const entry of skillsIndex.skills) {
  assert.equal(entry.type, 'skill-md', 'This publisher has only single-file browsing skills');
  const url = new URL(entry.url, skillsIndexUrl);
  assert.equal(url.origin, skillsIndexUrl.origin);
  assert.equal(url.pathname, '/agent-skills/' + entry.name + '/SKILL.md');
  assert.equal(url.search + url.hash, '');
  const bytes = readFileSync('_site' + url.pathname);
  assert.equal(entry.digest, 'sha256:' + createHash('sha256').update(bytes).digest('hex'));
  assert.deepEqual(bytes, readFileSync('agent-resources/' + entry.name + '/SKILL.md'));
  const frontmatter = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(bytes.toString('utf8'));
  assert.ok(frontmatter, 'Skill requires YAML frontmatter');
  for (const key of ['name', 'description']) {
    const fields = [...frontmatter[1].matchAll(new RegExp('^' + key + ':[ \\t]+([^\\r\\n]+)$', 'gm'))];
    assert.equal(fields.length, 1);
    assert.equal(entry[key], fields[0][1].trim());
  }
}
// Exercise the local RFC-derived schema, rather than trusting a permissive stub.
for (const changed of [{ name: 'bad--name' }, { digest: 'sha256:invalid' }, { type: 'mcp' }, { url: null }]) {
  const invalid = structuredClone(skillsIndex);
  Object.assign(invalid.skills[0], changed);
  assert.equal(validateSkills(invalid), false, 'Invalid Agent Skills fixture passed: ' + JSON.stringify(changed));
}
const missingDigest = structuredClone(skillsIndex);
delete missingDigest.skills[0].digest;
assert.equal(validateSkills(missingDigest), false, 'Digest is required');
assert.ok(validateSkills({ ...skillsIndex, futureMetadata: true }), 'Unknown fields must be tolerated');

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
console.log(`Agent discovery: current ARD schema and Lighthouse ${require('lighthouse/package.json').version} conformance passed; draft Agent Skills 0.2.0 metadata/digests verified; ${tools.length} WebMCP input schemas compiled.`);
