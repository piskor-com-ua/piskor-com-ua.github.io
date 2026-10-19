// Geometry/selection verification only. Network images use empty SVG stubs
// with real file-header dimensions; inline data images decode their real pixels
// natively because data URLs are not network-interceptable. Media/fonts are
// blocked. This preserves intrinsic sizing without missing-image alt text.
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
import base64, io, json, re, sys
from html.parser import HTMLParser
from pathlib import Path
from PIL import Image
root = Path(sys.argv[1])
result = {}
for extension in ('*.avif', '*.webp'):
    for image in root.rglob(extension):
        with Image.open(image) as opened:
            result['/' + image.relative_to(root).as_posix()] = list(opened.size)
class InlineImages(HTMLParser):
    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name not in {'src', 'srcset', 'imagesrcset', 'href'} or not value:
                continue
            for found in re.finditer(r'data:image/(avif|webp);base64,[A-Za-z0-9+/]+={0,2}', value):
                raw = found.group(0)
                if raw in result:
                    continue
                if len(raw) > 1024 * 1024:
                    raise ValueError('Inline image exceeds geometry inventory bound')
                body = base64.b64decode(raw.split(',', 1)[1], validate=True)
                with Image.open(io.BytesIO(body)) as opened:
                    if opened.format.lower() != found.group(1):
                        raise ValueError('Inline image format does not match MIME type')
                    result[raw] = list(opened.size)
for page in root.rglob('*.html'):
    InlineImages().feed(page.read_text(encoding='utf-8'))
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
          function parseGeneratedSrcset(value) {
            if (!value || value.length > 1024 * 1024) throw Error('Invalid generated srcset length');
            // Generated width candidates only. The single comma inside a base64
            // image URL belongs to that URL; separators follow the descriptor.
            const candidate = /\s*((?:data:image\/(?:avif|webp);base64,[A-Za-z0-9+/]+={0,2})|(?:(?!data:)[^\s,]+))\s+([1-9]\d*)w\s*(,|$)/gy;
            const entries = [], widths = new Set();
            let position = 0;
            while (position < value.length) {
              candidate.lastIndex = position;
              const match = candidate.exec(value);
              if (!match || entries.length >= 64) throw Error('Invalid generated width srcset');
              const width = Number(match[2]);
              if (!Number.isSafeInteger(width) || widths.has(width)) throw Error('Invalid or duplicate srcset width');
              widths.add(width);
              entries.push({ url: match[1], width });
              position = candidate.lastIndex;
              if (match[3] === ',' && !value.slice(position).trim()) throw Error('Trailing srcset separator');
            }
            return entries;
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
          const filePath = url => url.startsWith('data:') ? url : decodeURI(new URL(url, location.href).pathname);
          const output = [];
          for (const image of document.querySelectorAll('.project-cover img,.gallery-grid img,.portfolio-card-cover')) {
            const errors = [];
            try {
              const source = [...(image.closest('picture')?.querySelectorAll('source') || [])].find(source =>
                (!source.media || matchMedia(source.media).matches) && ['image/avif', 'image/webp'].includes(source.type));
              const srcset = source?.srcset || image.srcset;
              const candidates = srcset ? parseGeneratedSrcset(srcset).map(({ url, width }) => {
                const size = dimensions[filePath(url)];
                if (!size || size[0] !== width) throw Error('Descriptor does not match image header');
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
              if (!selected) errors.push('Selected candidate dimensions unavailable');
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
  const summary = { kind: 'geometry-only-network-image-stubs-native-inline-images-media-fonts-blocked', pages: routes.length,
    cases: routes.filter(route => caseRoutes.includes(route)).length,
    catalogs: routes.filter(route => catalogRoutes.includes(route)).length, viewports: widths,
    checkedImages: rows.reduce((total, row) => total + row.images.length, 0), failures: failures.length };
  writeFileSync(values.output, JSON.stringify({ summary, failures, rows }, null, 2) + '\n');
  console.log(JSON.stringify(summary));
  if (failures.length) { console.error(JSON.stringify(failures.slice(0, 10), null, 2)); process.exitCode = 1; }
})().catch(error => { console.error(error); process.exitCode = 1; });
