import base64
import hashlib
from io import BytesIO
from pathlib import Path
import re
import shutil
import json
import subprocess
from tempfile import TemporaryDirectory
import unittest

from fontTools.ttLib import TTFont
from PIL import Image

from first_paint import subset_fonts, _critical_payload
from zabava_first_paint import (ROUTE, COVER, LOGO, FONT_PATHS,
                               _critical_characters, _unicode_range,
                               optimize_zabava_en, transform_critical_payload, _lazy_tools)

CONSENT = Path('concept/analytics-consent.js').read_text()
FACES = ''.join('@font-face{font-family:Roboto;src:url("/' + path + '") format("woff2");font-weight:' + str(weight) + ';font-display:swap}' for weight, path in FONT_PATHS.items())
SET = '/cover-640.avif 640w, /cover-768.avif 768w, /cover-960.avif 960w, /cover-1440.avif 1440w, /cover-2200.avif 2200w'
HTML = ('<html lang="en"><head><style>' + FACES + '.arrow:after{content:"\\2197"}</style>'
        '<link rel="preload" as="font" href="/assets/fonts/roboto-light-subset.woff2">'
        '<link rel="preload" as="font" href="/unrelated.woff2">'
        '<link rel="preload" as="image" type="image/avif" media="(max-width: 700px)" imagesizes="96vw" imagesrcset="' + SET + '" data-case-cover-preload>'
        '</head><body><header><picture><source type="image/webp" srcset="/assets/responsive/piskor-logo.webp?v=abc"><img src="/assets/piskor-logo.png"></picture></header>'
        '<h1>Zabava Restaurant</h1><p>A warm dining space. 2022 / 125 m² ©</p>'
        '<figure class="project-cover"><picture><source type="image/avif" media="(max-width: 700px)" sizes="96vw" srcset="' + SET + '"><img src="/unchanged.webp"></picture></figure>'
        '<script>const untouched = "private script text: Ω";</script>'
        '<footer><picture><source type="image/webp" srcset="/assets/responsive/piskor-logo.webp?v=abc"><img src="/assets/piskor-logo.png"></picture></footer></body></html>')


def snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def range_codes(text):
    result = set()
    for part in text.split(','):
        values = part.removeprefix('U+').split('-')
        start, end = int(values[0], 16), int(values[-1], 16)
        result.update(range(start, end + 1))
    return result


class ZabavaFirstPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp = TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_temp.cleanup)
        cls.fixture = Path(cls.fixture_temp.name)
        (cls.fixture / '.nojekyll').touch()
        (cls.fixture / 'assets').mkdir()
        for name in ('roboto-light', 'roboto-regular'):
            shutil.copyfile(Path('concept/assets') / (name + '.woff2'), cls.fixture / 'assets' / (name + '.woff2'))
        page = cls.fixture / ROUTE
        page.parent.mkdir(parents=True)
        page.write_text(HTML)
        (cls.fixture / 'analytics-consent.js').write_text(CONSENT)
        # Global coverage is intentionally broader than this route; those pages
        # and their font bytes must survive the scoped optimization unchanged.
        (cls.fixture / 'index.html').write_text('<html lang="uk">Київ Ґґ ©«°²·»×ç—‘’“”</html>')
        (cls.fixture / 'other.js').write_text('const neverInline = true;')
        subset_fonts(cls.fixture)
        (cls.fixture / COVER).parent.mkdir(parents=True)
        shutil.copyfile(Path('concept') / COVER, cls.fixture / COVER)
        (cls.fixture / LOGO).parent.mkdir(parents=True)
        Image.open('concept/assets/piskor-logo.png').save(cls.fixture / LOGO, 'WEBP', lossless=True, method=6, exact=True)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'artifact'
        shutil.copytree(self.fixture, self.root)

    def test_rejects_source_and_skips_absent_route(self):
        with self.assertRaises(ValueError):
            optimize_zabava_en(Path('concept'))
        (self.root / ROUTE).unlink()
        before = snapshot(self.root)
        self.assertIsNone(optimize_zabava_en(self.root))
        self.assertEqual(before, snapshot(self.root))

    def test_complete_profile_is_scoped_truthful_and_reproducible(self):
        before = snapshot(self.root)
        original = (self.root / ROUTE).read_text()
        report = optimize_zabava_en(self.root)
        result = (self.root / ROUTE).read_text()
        after = snapshot(self.root)
        self.assertEqual(set(before), set(after))
        self.assertEqual([path for path in before if before[path] != after[path]], [ROUTE])
        self.assertEqual(re.findall(r'<script\b[^>]*>(.*?)</script>', original, re.S),
                         re.findall(r'<script\b[^>]*>(.*?)</script>', result, re.S))
        self.assertIn('/unrelated.woff2', result)
        self.assertNotIn('href="/assets/fonts/roboto-light-subset.woff2"', result)
        font_uris = re.findall(r'data:font/woff2;base64,([A-Za-z0-9+/=]+)', result)
        self.assertEqual(len(font_uris), 2)
        self.assertEqual(font_uris[0], font_uris[1])
        font_uri = font_uris[0]
        inline_faces = [face for face in re.findall(r'@font-face\{[^}]*\}', result) if 'data:font/' in face]
        self.assertEqual([int(re.search(r'font-weight:(300|400);', face)[1]) for face in inline_faces], [300, 400])
        font = TTFont(BytesIO(base64.b64decode(font_uri)))
        critical = set(report['critical_codepoints'])
        remaining = set(report['fallback_codepoints'])
        global_codes = set(TTFont(self.root / FONT_PATHS[300]).getBestCmap())
        self.assertEqual(critical, set(font.getBestCmap()))
        self.assertEqual(global_codes, critical | remaining)
        self.assertFalse(critical & remaining)
        self.assertTrue(set(map(ord, 'ZabavaYourprivacychoices0123456789')).issubset(critical))
        self.assertNotIn(ord('Ω'), critical)
        self.assertIn(ord(':'), critical)  # Native video controls display 0:00.
        self.assertIn(ord('Ї'), remaining)
        self.assertTrue({'GSUB', 'GPOS', 'GDEF', 'gvar', 'HVAR'}.issubset(font.keys()))
        ranges = re.findall(r'unicode-range:([^}]+)', result)
        self.assertEqual([range_codes(value) for value in ranges], [critical, remaining, critical, remaining])
        candidates = re.findall(r'data:image/avif;base64,([A-Za-z0-9+/=]+) 704w', result)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0], candidates[1])
        self.assertEqual(Image.open(BytesIO(base64.b64decode(candidates[0]))).size, (704, 528))
        self.assertEqual(report['cover_recipe'], '704x528:AVIF:q28:speed0:threads1:LANCZOS')
        for width in (640, 768, 960, 1440, 2200):
            self.assertEqual(result.count(f'/cover-{width}.avif {width}w'), 2)
        self.assertEqual(result.count('media="(max-width: 700px)"'), 2)
        self.assertIn('imagesizes="96vw"', result)
        self.assertIn('sizes="96vw"', result)
        logos = re.findall(r'data:image/webp;base64,([A-Za-z0-9+/=]+)', result)
        self.assertEqual(len(logos), 2)
        self.assertTrue(all(base64.b64decode(data) == (self.root / LOGO).read_bytes() for data in logos))
        # Recreate the same clean artifact rather than reprocessing transformed HTML.
        twin = Path(self.temp.name) / 'twin'
        shutil.copytree(self.fixture, twin)
        self.assertEqual(report, optimize_zabava_en(twin))
        self.assertEqual((twin / ROUTE).read_bytes(), (self.root / ROUTE).read_bytes())

    def test_changed_visible_copy_and_consent_are_included_without_fixed_inventory(self):
        text = HTML.replace('Zabava Restaurant', 'Zabava Restaurant ç — “Private”')
        codes = _critical_characters(text, CONSENT)
        self.assertTrue(set(map(ord, 'ç—“”PRIVATE')).issubset(codes))
        self.assertTrue(set(map(ord, 'Your privacy choices')).issubset(codes))
        self.assertIn(0x2197, codes)
        self.assertIn(ord(':'), codes)
        self.assertNotIn(ord('Ω'), codes)
        self.assertEqual(_unicode_range({32, 33, 34, 40, 42, 43}), 'U+20-22,U+28,U+2a-2b')

    def test_lazy_tools_preserve_registration_execution_retry_and_catalog_cache(self):
        (self.root / 'agent-tools.js').write_text(Path('concept/agent-tools.js').read_text())
        (self.root / 'portfolio.js').write_text(Path('concept/portfolio.js').read_text())
        _, original = _critical_payload(self.root, ('agent-tools.js', 'portfolio.js'), 'data-inline-page-critical')
        transformed = transform_critical_payload(self.root, original)
        data = _lazy_tools(self.root)
        self.assertEqual(transformed.count('data-zabava-agent-tools'), 1)
        self.assertIn("document.addEventListener('DOMContentLoaded', () => {", transformed)
        self.assertEqual(transformed.count('}, { once: true });'), 2)
        _, untouched = _critical_payload(self.root, ('portfolio.js',), 'data-inline-page-critical')
        self.assertTrue(transformed.endswith(untouched))
        bodies = re.findall(r'<script[^>]*>(.*?)</script>', transformed, re.S)
        probe = Path(__file__).with_name('zabava-agent-tools.cjs')
        check = r"""
const assert = require('node:assert/strict'), vm = require('node:vm');
const data = JSON.parse(process.argv[1]), body = process.argv[2];
(async () => {
  const registered = [], requested = [], callbacks = [];
  let catalogFetches = 0;
  const document = { modelContext: { registerTool: tool => registered.push(tool) },
    documentElement: { lang: 'en' }, addEventListener: (event, callback, options) => {
      assert.equal(event, 'DOMContentLoaded'); assert.equal(options.once, true); callbacks.push(callback);
    }, querySelectorAll: () => [{ textContent: 'Phone ↗', getAttribute: () => 'tel:+380974781005' }] };
  const context = vm.createContext({ document, navigator: {}, fetch: async () => {
    catalogFetches++; return { ok: true, json: async () => ({ version: 1, projects: [
      { id: 'zabava-restaurant-sambir', language: 'en', year: 2022, name: 'Zabava', summary: 'Restaurant', label: '241 m²', url: '/en/portfolio/2022/zabava-restaurant-sambir/', facts: [], sections: [] }
    ] }) };
  } });
  const script = new vm.Script(body, { importModuleDynamically: async url => {
    requested.push(url);
    if (requested.length === 1) throw new Error('Temporary module fetch failure');
    const module = new vm.SourceTextModule(data.implementation, { context });
    await module.link(() => { throw new Error('Unexpected module dependency'); });
    await module.evaluate(); return module;
  } });
  script.runInContext(context);
  assert.equal(registered.length, 0); assert.equal(callbacks.length, 1);
  callbacks[0]();
  assert.equal(registered.length, 3); assert.equal(requested.length, 0);
  const metadata = registered.map(({ execute, ...tool }) => tool);
  assert.deepEqual(JSON.parse(JSON.stringify(metadata)), data.metadata);
  const contacts = registered.find(tool => tool.name === 'get_contact_options');
  await assert.rejects(contacts.execute({}), /Temporary module fetch failure/);
  assert.equal(JSON.parse(await contacts.execute({})).contacts.length, 1);
  assert.equal(requested.length, 2); assert.equal(requested[1], requested[0] + '?retry=1');
  assert.equal(catalogFetches, 0);
  const search = registered.find(tool => tool.name === 'search_projects');
  const details = registered.find(tool => tool.name === 'get_project_details');
  assert.equal(JSON.parse(await search.execute({ query: 'Zabava', language: 'en' })).total, 1);
  assert.equal(JSON.parse(await details.execute({ project_id: 'zabava-restaurant-sambir', language: 'en' })).id, 'zabava-restaurant-sambir');
  assert.equal(requested.length, 2); assert.equal(catalogFetches, 1);
  await assert.rejects(search.execute({ unknown: true }), /Unknown input field/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        subprocess.run(['node', '--experimental-vm-modules', '-e', check,
                        json.dumps(data), bodies[0]], check=True, capture_output=True, text=True)

    def test_lazy_tools_reject_stale_module_and_changed_shared_schema(self):
        source = Path('concept/agent-tools.js').read_text()
        (self.root / 'agent-tools.js').write_text(source)
        _, payload = _critical_payload(self.root, ('agent-tools.js',), 'data-inline-page-critical')
        data = _lazy_tools(self.root)
        module = self.root / data['filename']
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text('stale module bytes')
        with self.assertRaisesRegex(ValueError, 'Stale generated'):
            transform_critical_payload(self.root, payload)
        module.unlink()
        (self.root / 'agent-tools.js').write_text(source.replace('minimum: 1900', 'minimum: 1800'))
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            transform_critical_payload(self.root, payload)


    def test_unknown_consent_fails_before_any_output_write(self):
        (self.root / 'analytics-consent.js').write_text('const copy = chooseCopy();')
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, 'consent'):
            optimize_zabava_en(self.root)
        self.assertEqual(before, snapshot(self.root))

    def test_unexpected_cover_markup_fails_without_partial_rewrite(self):
        page = self.root / ROUTE
        page.write_text(page.read_text().replace('class="project-cover"', 'class="new-cover"'))
        before = snapshot(self.root)
        with self.assertRaisesRegex(ValueError, 'cover'):
            optimize_zabava_en(self.root)
        self.assertEqual(before, snapshot(self.root))


if __name__ == '__main__':
    unittest.main()
