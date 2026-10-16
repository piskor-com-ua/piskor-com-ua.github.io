const { spawn } = require('node:child_process');
const { readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const path = require('node:path');
const { parseArgs } = require('node:util');
const { values, positionals } = parseArgs({ allowPositionals: true, options: {
  runs: { type: 'string', default: '3' }, modes: { type: 'string', default: 'mobile,desktop' },
  output: { type: 'string', default: 'output/lighthouse' }
} });
const baseline = positionals[0] || 'http://127.0.0.1:4184/portfolio/';
const candidate = positionals[1] || 'http://127.0.0.1:4183/portfolio/';
const folder = values.output;
const runs = Number(values.runs);
const modes = values.modes.split(',');
if (!Number.isInteger(runs) || runs < 1 || runs > 10 || !modes.length || modes.some(mode => !['mobile', 'desktop'].includes(mode))) {
  throw Error('Use --runs 1..10 and --modes mobile,desktop');
}
mkdirSync(folder, { recursive: true });
const rows = [];
(async () => {
  for (const mode of modes) {
    for (let run = 1; run <= runs; run++) {
      for (const [name, url] of [['baseline', baseline], ['candidate', candidate]]) {
        const filename = path.resolve(folder, name + '-' + mode + '-' + run + '.json');
        const args = [url, '--quiet', '--chrome-flags=--headless', '--output=json', '--output-path=' + filename,
          '--only-categories=performance,accessibility,best-practices,seo,agentic-browsing'];
        if (mode === 'desktop') args.push('--preset=desktop');
        await new Promise((resolve, reject) => {
          const child = spawn(path.resolve('node_modules/.bin/lighthouse'), args, { stdio: 'inherit' });
          child.on('error', reject);
          child.on('exit', code => code === 0 ? resolve() : reject(Error('Lighthouse exited ' + code)));
        });
        const report = JSON.parse(readFileSync(filename));
        if (report.runtimeError) throw Error(report.runtimeError.message);
        const audit = key => report.audits[key].numericValue;
        const row = { name, mode, run, lighthouse: report.lighthouseVersion,
          performance: report.categories.performance.score * 100,
          accessibility: report.categories.accessibility.score * 100,
          fcp: audit('first-contentful-paint'), lcp: audit('largest-contentful-paint'),
          speedIndex: audit('speed-index'), cls: audit('cumulative-layout-shift'),
          tbt: audit('total-blocking-time'), bytes: audit('total-byte-weight') };
        rows.push(row);
        console.log(JSON.stringify(row));
        writeFileSync(folder + '/summary.json', JSON.stringify(rows, null, 2));
      }
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
