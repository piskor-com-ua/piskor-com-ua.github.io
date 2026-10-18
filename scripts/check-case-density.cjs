// Geometry/selection verification only. Images use empty SVG stubs with the
// real file-header dimensions; media/font downloads are blocked. This preserves
// decoded intrinsic sizing without pixel decoding or missing-image alt text.
// This helper does not produce performance, visual-quality or HTTP evidence.
const { chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const { readFileSync, writeFileSync, mkdirSync } = require('node:fs');
const path = require('node:path');
const { parseArgs } = require('node:util');

const { values, positionals } = parseArgs({ allowPositionals: true, options: {
  site: { type: 'string', default: '_site' },
  output: { type: 'string', default: 'output/browser/case-density.json' },
  python: { type: 'string', default: process.env.PYTHON || 'python3' },
  widths: { type: 'string', default: '390,700,701,1440,1956' },
  routes: { type: 'string' },
} });
if (positionals.length !== 1) throw Error('Usage: node scripts/check-case-density.cjs BASE_URL [--site _site] [--python PYTHON] [--routes /path/,/en/path/]');
const origin = new URL(positionals[0]).origin;
const site = path.resolve(values.site);
const widths = values.widths.split(',').map(Number);
if (widths.some(width => !Number.isInteger(width) || width < 300)) throw Error('Invalid viewport widths');
const projects = JSON.parse(readFileSync(path.join(site, 'project-catalog.json'))).projects;
const caseRoutes = [...new Set(projects.map(project => project.url))];
const catalogRoutes = ['', 'en/'].flatMap(prefix => [
  '/' + prefix + 'portfolio/',
  ...[...new Set(projects.map(project => project.year))].map(year => '/' + prefix + 'portfolio/' + year + '/'),
]);
const routes = values.routes ? values.routes.split(',') : [...caseRoutes, ...catalogRoutes];
if (!routes.length || routes.some(route => !/^\/(?:en\/)?portfolio\/(?:\d{4}\/(?:[\w-]+\/)?)?$/.test(route))) throw Error('Use generated case or catalog routes');

// Read image headers only, without decoding pixels or requesting remote assets.
const dimensions = JSON.parse(execFileSync(values.python, ['-c', String.raw`
import json, sys
from pathlib import Path
from PIL import Image
root = Path(sys.argv[1])
result = {}
for extension in ('*.avif', '*.webp'):
    for image in root.rglob(extension):
        with Image.open(image) as opened:
            result['/' + image.relative_to(root).as_posix()] = list(opened.size)
print(json.dumps(result))
`, site], { maxBuffer: 16 * 1024 * 1024 }).toString());

(async () => {
  const browser = await chromium.launch({ headless: true });
  const rows = [];
  try {
    for (const width of widths) {
      const dpr = width <= 700 ? 1.75 : 1;
      const context = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: dpr });
      await context.route('**/*', route => {
        const request = route.request();
        if (new URL(request.url()).origin !== origin || ['media', 'font'].includes(request.resourceType())) return route.abort();
        if (request.resourceType() === 'image') {
          const size = dimensions[decodeURI(new URL(request.url()).pathname)];
          if (!size) return route.abort();
          return route.fulfill({ contentType: 'image/svg+xml', body:
            '<svg xmlns="http://www.w3.org/2000/svg" width="' + size[0] + '" height="' + size[1] + '"></svg>' });
        }
        return route.continue();
      });
      const page = await context.newPage();
      for (const route of routes) {
        await page.goto(origin + route, { waitUntil: 'domcontentloaded' });
        await page.evaluate(async () => {
          // Offscreen cards deliberately skip layout in normal browsing. This
          // geometry-only probe must inspect their real image boxes as well.
          for (const card of document.querySelectorAll('.portfolio-card')) card.style.contentVisibility = 'visible';
          const images = [...document.querySelectorAll('.project-cover img,.gallery-grid img,.portfolio-card-cover')];
          for (const image of images) image.loading = 'eager';
          await Promise.all(images.map(image => image.decode()));
          await document.fonts.ready;
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        });
        const images = await page.evaluate(({ dimensions, dpr }) => {
          const probe = document.createElement('div');
          probe.style.cssText = 'position:fixed;visibility:hidden;pointer-events:none;height:0;box-sizing:content-box;margin:0;padding:0;border:0;max-width:none;min-width:0;';
          document.body.append(probe);
          const measured = new Map();
          function splitList(value) {
            let depth = 0, start = 0;
            const parts = [];
            for (let index = 0; index < value.length; index++) {
              if (value[index] === '(') depth++;
              if (value[index] === ')') depth--;
              if (value[index] === ',' && depth === 0) { parts.push(value.slice(start, index).trim()); start = index + 1; }
            }
            parts.push(value.slice(start).trim());
            return parts;
          }
          function declaredWidth(sizes) {
            for (let part of splitList(sizes || '100vw')) {
              if (part.startsWith('(')) {
                let depth = 0, end = -1;
                for (let index = 0; index < part.length; index++) {
                  if (part[index] === '(') depth++;
                  if (part[index] === ')' && --depth === 0) { end = index + 1; break; }
                }
                if (end < 0 || !matchMedia(part.slice(0, end)).matches) continue;
                part = part.slice(end).trim();
              }
              if (!CSS.supports('width', part)) throw Error('Invalid sizes expression: ' + part);
              if (!measured.has(part)) {
                probe.style.setProperty('width', part, 'important');
                measured.set(part, probe.getBoundingClientRect().width);
              }
              return measured.get(part);
            }
            throw Error('No sizes branch applies');
          }
          const filePath = url => decodeURI(new URL(url, location.href).pathname);
          const output = [];
          for (const image of document.querySelectorAll('.project-cover img,.gallery-grid img,.portfolio-card-cover')) {
            const errors = [];
            try {
              const source = [...(image.closest('picture')?.querySelectorAll('source') || [])].find(source =>
                (!source.media || matchMedia(source.media).matches) && ['image/avif', 'image/webp'].includes(source.type));
              const srcset = source?.srcset || image.srcset;
              const candidates = srcset ? srcset.split(',').map(entry => {
                const [url, descriptor] = entry.trim().split(/\s+/);
                if (!/^\d+w$/.test(descriptor)) throw Error('Expected width descriptor');
                const size = dimensions[filePath(url)];
                if (!size || size[0] !== Number(descriptor.slice(0, -1))) throw Error('Descriptor does not match file: ' + url);
                return { url, width: size[0], height: size[1] };
              }) : [{ url: image.src, width: dimensions[filePath(image.src)]?.[0], height: dimensions[filePath(image.src)]?.[1] }];
              if (candidates.some(candidate => !candidate.width || !candidate.height)) throw Error('Missing image dimensions');
              const native = [...candidates].sort((a, b) => b.width - a.width)[0];
              const style = getComputedStyle(image);
              const rect = image.getBoundingClientRect();
              const boxWidth = rect.width - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth) - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
              const boxHeight = rect.height - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth) - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
              if (boxWidth <= 0 || boxHeight <= 0) throw Error('Image geometry is unavailable without scrolling');
              const sourceHeightWidth = boxHeight * native.width / native.height;
              const referenceWidth = style.objectFit === 'cover' ? Math.max(boxWidth, sourceHeightWidth)
                : style.objectFit === 'contain' ? Math.min(boxWidth, sourceHeightWidth) : boxWidth;
              const declared = declaredWidth(source?.sizes || image.sizes);
              const fullNative = candidates.length === 1 && !!source;
              if (!fullNative && declared + 1 < referenceWidth) errors.push('sizes understates cropped source width');
              const requiredPixels = Math.min(native.width, referenceWidth * dpr);
              const selected = image.currentSrc ? dimensions[filePath(image.currentSrc)] : null;
              if (selected && selected[0] + 2 < requiredPixels) errors.push('Selected candidate undersamples cropped source');
              const predicted = [...candidates].sort((a, b) => a.width - b.width).find(candidate => candidate.width >= declared * dpr) || native;
              if (predicted.width + 2 < requiredPixels) errors.push('Declared candidates would undersample cropped source');
              output.push({ source: image.getAttribute('src'), section: image.closest('[id]')?.id || null,
                objectFit: style.objectFit, aspectRatio: style.aspectRatio, boxWidth, boxHeight,
                sourceNative: [native.width, native.height], referenceWidth, declaredWidth: declared,
                requiredPixels, predictedWidth: predicted.width, currentSrc: image.currentSrc || null,
                selectedWidth: selected?.[0] || null, fullNativeFallback: fullNative, errors });
            } catch (error) {
              output.push({ source: image.getAttribute('src'), errors: [String(error.message || error)] });
            }
          }
          probe.remove();
          return output;
        }, { dimensions, dpr });
        if (!images.length) throw Error('No generated case/catalog images at ' + route);
        rows.push({ route, width, dpr, images });
      }
      await context.close();
    }
  } finally {
    await browser.close();
  }
  mkdirSync(path.dirname(values.output), { recursive: true });
  const failures = rows.flatMap(row => row.images.filter(image => image.errors.length).map(image => ({ route: row.route, width: row.width, dpr: row.dpr, ...image })));
  const summary = { kind: 'geometry-only-header-sized-image-stubs-media-fonts-blocked', pages: routes.length,
    cases: routes.filter(route => caseRoutes.includes(route)).length,
    catalogs: routes.filter(route => catalogRoutes.includes(route)).length, viewports: widths,
    checkedImages: rows.reduce((total, row) => total + row.images.length, 0), failures: failures.length };
  writeFileSync(values.output, JSON.stringify({ summary, failures, rows }, null, 2) + '\n');
  console.log(JSON.stringify(summary));
  if (failures.length) { console.error(JSON.stringify(failures.slice(0, 10), null, 2)); process.exitCode = 1; }
})().catch(error => { console.error(error); process.exitCode = 1; });
