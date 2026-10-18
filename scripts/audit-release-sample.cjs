// Cold mobile lab checks; supplement with real navigation and five target runs.
const { spawn } = require('node:child_process');
const { readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const path = require('node:path');
const { parseArgs } = require('node:util');
const { values, positionals } = parseArgs({ allowPositionals: true, options: {
  output: { type: 'string', default: 'output/release-sample' }
} });
if (positionals.length !== 1) throw Error('Usage: node scripts/audit-release-sample.cjs BASE_URL [--output FOLDER]');
const origin = new URL(positionals[0]).origin;
const routes = JSON.parse(readFileSync(path.join(__dirname, 'release-sample.json')));
if (routes.length !== 10 || new Set(routes).size !== 10) throw Error('Keep ten distinct page paths in the release sample');
mkdirSync(values.output, { recursive: true });
(async () => {
  const rows = [];
  for (const [index, route] of routes.entries()) {
    const filename = path.resolve(values.output, 'mobile-' + (index + 1) + '.json');
    await new Promise((resolve, reject) => {
      const args = [origin + route, '--quiet',
        '--chrome-flags=--headless', '--output=json', '--output-path=' + filename,
        '--only-categories=performance,accessibility,best-practices,seo,agentic-browsing'];
      if (route === '/portfolio/') args.push('--save-assets');
      const child = spawn(path.resolve('node_modules/.bin/lighthouse'), args, { stdio: 'inherit' });
      child.on('error', reject);
      child.on('exit', code => code === 0 ? resolve() : reject(Error('Lighthouse exited ' + code)));
    });
    const report = JSON.parse(readFileSync(filename));
    if (report.runtimeError) throw Error(route + ': ' + report.runtimeError.message);
    const audit = key => report.audits[key];
    const agenticRefs = report.categories['agentic-browsing'].auditRefs;
    const agentic = agenticRefs.map(ref => audit(ref.id));
    const applicable = agenticRefs.filter(ref => ref.weight > 0).map(ref => audit(ref.id))
      .filter(a => !['informative', 'notApplicable', 'manual'].includes(a.scoreDisplayMode));
    const row = { route, captured: report.fetchTime, lighthouse: report.lighthouseVersion,
      performance: report.categories.performance.score * 100,
      accessibility: report.categories.accessibility.score * 100,
      bestPractices: report.categories['best-practices'].score * 100,
      fcp: audit('first-contentful-paint').numericValue, lcp: audit('largest-contentful-paint').numericValue,
      speedIndex: audit('speed-index').numericValue, cls: audit('cumulative-layout-shift').numericValue,
      tbt: audit('total-blocking-time').numericValue,
      agentic: { passed: applicable.filter(a => a.score === 1).length, applicable: applicable.length,
        notApplicable: agentic.filter(a => a.scoreDisplayMode === 'notApplicable').map(a => a.id) },
      failedAudits: Object.values(report.audits).filter(a => a.score === 0).map(a => a.id) };
    rows.push(row);
    writeFileSync(path.join(values.output, 'summary.json'), JSON.stringify(rows, null, 2));
    console.log(JSON.stringify(row));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
