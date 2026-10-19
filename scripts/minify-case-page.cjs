// A pinned, deterministic transform for the explicitly reviewed case only.
const fs = require('node:fs');
const {createHash} = require('node:crypto');
const {minify} = require('html-minifier-terser');
const OPTIONS = {
  collapseWhitespace: true,
  conservativeCollapse: true,
  removeComments: true,
  removeAttributeQuotes: false,
  removeEmptyAttributes: false,
  minifyCSS: true,
  minifyJS: {mangle: true, compress: {drop_console: false}, format: {comments: false}},
};

async function compact(html) {
  const json = html.replace(/<script([^>]*type="application\/ld\+json"[^>]*)>([\s\S]*?)<\/script>/g,
    (_, attrs, body) => '<script' + attrs + '>' + JSON.stringify(JSON.parse(body)) + '</script>');
  const result = await minify(json, OPTIONS);
  return result.replace(/<style([^>]*\bdata-page-styles=")[^"]*("[^>]*)>([\s\S]*?)<\/style>/g,
    (_, before, after, css) => '<style' + before + createHash('sha256').update(css).digest('hex').slice(0, 12)
      + after + '>' + css + '</style>');
}

if (require.main === module) {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  if (!Array.isArray(input) || input.some(value => typeof value !== 'string')) {
    throw new Error('Expected an array of HTML fragments');
  }
  Promise.all(input.map(compact)).then(result => process.stdout.write(JSON.stringify(result)))
    .catch(error => {process.stderr.write(error.message + '\n'); process.exitCode = 1;});
}
module.exports = {compact};
