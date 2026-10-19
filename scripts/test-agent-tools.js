const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const source = readFileSync('concept/agent-tools.js', 'utf8');
const projects = [
  { id: 'house', language: 'uk', year: 2026, name: 'Будинок', url: '/portfolio/2026/house/', summary: '398 м²', label: 'Реалізований проєкт', facts: [{ value: 'Брюховичі' }], sections: [{ text: 'Автоматизація освітлення', url: '/portfolio/2026/house/#lighting' }] },
  { id: 'house', language: 'en', year: 2026, name: 'House', url: '/en/portfolio/2026/house/', summary: '398 m²', label: 'Completed project', facts: [], sections: [] }
];
function setup({ legacy = false, supported = true, failing = false } = {}) {
  const tools = [], requests = [];
  const context = { registerTool: tool => tools.push(tool) };
  const document = { documentElement: { lang: 'uk' }, querySelectorAll: () => [{ textContent: 'WhatsApp↗', getAttribute: () => 'https://wa.me/380974781005' }] };
  const navigator = {};
  if (supported) (legacy ? navigator : document).modelContext = context;
  const sandbox = { document, navigator, fetch: async (url, options) => {
    requests.push({ url, options });
    return { ok: !failing, json: async () => ({ version: 1, projects }) };
  } };
  const rerun = () => vm.runInNewContext(source, sandbox);
  rerun();
  return { tools, requests, document, navigator, context, rerun };
}
test('unsupported browsers make no requests and register nothing', () => {
  const { tools, requests } = setup({ supported: false });
  assert.equal(tools.length, 0); assert.equal(requests.length, 0);
});
test('current and earlier API surfaces register three read-only tools lazily', () => {
  for (const legacy of [false, true]) {
    const { tools, requests } = setup({ legacy });
    assert.deepEqual(tools.map(t => t.name), ['search_projects', 'get_project_details', 'get_contact_options']);
    assert.ok(tools.every(t => t.annotations.readOnlyHint));
    assert.equal(requests.length, 0);
    assert.ok(tools.every(t => t.inputSchema.additionalProperties === false));
  }
});
test('search, language, year and details use the same published records', async () => {
  const { tools, requests } = setup();
  const result = JSON.parse(await tools[0].execute({ query: 'брюховичі освітлення', year: 2026 }));
  assert.equal(result.total, 1);
  assert.equal(result.projects[0].label, 'Реалізований проєкт');
  assert.equal(JSON.parse(await tools[0].execute({ language: 'en' })).projects[0].name, 'House');
  assert.equal(JSON.parse(await tools[1].execute({ project_id: 'house' })).sections[0].url, '/portfolio/2026/house/#lighting');
  assert.equal(JSON.parse(await tools[0].execute({ query: 'missing' })).total, 0);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/project-catalog.json');
  assert.equal(requests[0].options.credentials, 'omit');
});
test('invalid and unknown inputs fail before reading data', async () => {
  const { tools, requests } = setup();
  for (const input of [null, [], { year: '2026' }, { year: 0 }, { language: 'ru' }, { limit: 0 }, { query: [] }, { query: 'x'.repeat(201) }, { extra: true }]) {
    await assert.rejects(tools[0].execute(input));
  }
  await assert.rejects(tools[1].execute({ project_id: '../private' }));
  await assert.rejects(tools[1].execute({}));
  await assert.rejects(tools[2].execute({ language: 'en' }));
  assert.equal(requests.length, 0);
});
test('default tool language follows a homepage language switch without registration or refetch', async () => {
  const { tools, requests, document } = setup();
  assert.equal(JSON.parse(await tools[0].execute()).projects[0].name, 'Будинок');
  document.documentElement.lang = 'en';
  assert.equal(JSON.parse(await tools[0].execute()).projects[0].name, 'House');
  assert.equal(JSON.parse(await tools[1].execute({ project_id: 'house' })).language, 'en');
  assert.equal(JSON.parse(await tools[0].execute({ language: 'uk' })).projects[0].name, 'Будинок');
  assert.equal(tools.length, 3);
  assert.equal(requests.length, 1);
});
test('contacts only read links and failed requests can retry', async () => {
  const { tools, requests } = setup({ failing: true });
  assert.equal(JSON.parse(await tools[2].execute()).contacts[0].url, 'https://wa.me/380974781005');
  assert.equal(requests.length, 0);
  await assert.rejects(tools[0].execute(), /temporarily unavailable/);
  await assert.rejects(tools[0].execute(), /temporarily unavailable/);
  assert.equal(requests.length, 2);
});

test('repeated script evaluation registers once per API context and retains lazy shared data', async () => {
  for (const legacy of [false, true]) {
    const { tools, requests, document, rerun } = setup({ legacy });
    rerun(); rerun();
    assert.equal(tools.length, 3);
    assert.equal(requests.length, 0);
    await tools[0].execute();
    document.documentElement.lang = 'en';
    rerun();
    assert.equal(JSON.parse(await tools[0].execute()).projects[0].name, 'House');
    assert.equal(JSON.parse(await tools[1].execute({ project_id: 'house' })).language, 'en');
    assert.equal(tools.length, 3);
    assert.equal(requests.length, 1);
  }
});
test('API appearing after initial unavailable evaluation can still register', () => {
  const { tools, document, context, rerun } = setup({ supported: false });
  document.modelContext = context;
  rerun(); rerun();
  assert.equal(tools.length, 3);
});
test('registration failure never breaks ordinary page execution', () => {
  const document = { modelContext: { registerTool() { throw Error('Experimental API unavailable'); } } };
  assert.doesNotThrow(() => vm.runInNewContext(source, { document, navigator: {} }));
});

test('query maxLength counts Unicode code points consistently with JSON Schema', async () => {
  const { tools } = setup();
  for (const query of ['😀'.repeat(101), '😀'.repeat(200), 'a'.repeat(200)]) {
    assert.equal(JSON.parse(await tools[0].execute({ query })).total, 0);
  }
  await assert.rejects(tools[0].execute({ query: '😀'.repeat(201) }), /at most 200/);
  await assert.rejects(tools[0].execute({ query: { toString: () => 'x' } }));
});
