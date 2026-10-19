// Build-only adapter. Tool schemas, descriptions, validation and executors remain
// sourced from the reviewed shared controller rather than a second implementation.
const vm = require('node:vm');
const crypto = require('node:crypto');

function lazyTools(source) {
  const registered = [];
  const context = { registerTool: tool => registered.push(tool) };
  vm.runInNewContext(source, { document: { modelContext: context }, navigator: {} }, { timeout: 1000 });
  const expected = ['search_projects', 'get_project_details', 'get_contact_options'];
  if (registered.length !== 3 || registered.some((tool, index) => tool.name !== expected[index] || typeof tool.execute !== 'function')) {
    throw Error('Unrecognized shared tool registration contract');
  }
  const start = source.indexOf('  let catalog;');
  const end = source.indexOf('  for (const tool of tools) {');
  if (start < 0 || end <= start || source.indexOf('  let catalog;', start + 1) !== -1 || source.indexOf('  for (const tool of tools) {', end + 1) !== -1) {
    throw Error('Unrecognized shared tool implementation boundaries');
  }
  const implementation = 'const tools = (() => {\n' + source.slice(start, end) + '\nreturn tools;\n})();\n' +
    'export function execute(name, input) {\n' +
    '  const tool = tools.find(tool => tool.name === name);\n' +
    '  if (!tool) throw new Error("Unknown PISKOR tool");\n' +
    '  return tool.execute(input);\n}\n';
  const hash = crypto.createHash('sha256').update(implementation).digest('hex');
  const filename = 'assets/zabava-agent-tools-' + hash.slice(0, 12) + '.js';
  const metadata = registered.map(({ execute, ...tool }) => tool);
  const script = `(() => {
  const context = document.modelContext || navigator.modelContext;
  if (!context || typeof context.registerTool !== 'function' || document.__piskorModelContext === context) return;
  document.__piskorModelContext = context;
  let implementation, attempts = 0;
  function execute(name, input) {
    if (!implementation) {
      if (attempts === 3) return Promise.reject(new Error('PISKOR tools could not load. Reload this page to retry.'));
      const retry = attempts++;
      implementation = import(${JSON.stringify('/' + filename)} + (retry ? '?retry=' + retry : '')).catch(error => {
        implementation = undefined;
        throw error;
      });
    }
    return implementation.then(module => module.execute(name, input));
  }
  for (const tool of ${JSON.stringify(metadata)}) {
    tool.execute = input => execute(tool.name, input);
    try { Promise.resolve(context.registerTool(tool)).catch(() => {}); } catch {}
  }
})();`;
  return { script, implementation, filename, implementation_sha256: hash, metadata };
}

module.exports = { lazyTools };
if (require.main === module) {
  let source = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', data => { source += data; });
  process.stdin.on('end', () => {
    try { process.stdout.write(JSON.stringify(lazyTools(source))); }
    catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 1; }
  });
}
