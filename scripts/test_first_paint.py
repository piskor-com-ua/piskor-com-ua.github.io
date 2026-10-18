from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
from first_paint import inline_consent, subset_fonts, inline_catalog_styles


class FirstPaintTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.nojekyll').touch()

    def test_consent_runs_with_body_and_configuration_before_visible_content(self):
        (self.root / 'analytics-consent.js').write_text('document.body.dataset.test = document.currentScript.dataset.measurementId;')
        page = self.root / 'index.html'
        page.write_text('<html><head><script src="/analytics-consent.js" data-measurement-id="G-ABC" defer></script></head><body class="test"><header>Studio</header></body></html>')
        self.assertEqual(inline_consent(self.root), 1)
        result = page.read_text()
        self.assertNotIn('src="/analytics-consent.js"', result)
        self.assertIn('<body class="test"><script data-consent-inline data-measurement-id="G-ABC">', result)
        self.assertLess(result.index('document.body'), result.index('<header>'))
        self.assertEqual(inline_consent(self.root), 0)

    def test_inline_css_preserves_versioned_root_relative_resources(self):
        (self.root / 'catalog-bundle.css').write_text('@font-face{src:url("assets/fonts/light.woff2?v=abc")}a{mask:url(/assets/icon.svg?v=def)}')
        page = self.root / 'index.html'
        page.write_text('<head><link rel="stylesheet" href="/catalog-bundle.css?v=123"></head>')
        self.assertEqual(inline_catalog_styles(self.root), 1)
        result = page.read_text()
        self.assertIn('url("/assets/fonts/light.woff2?v=abc")', result)
        self.assertIn('url(/assets/icon.svg?v=def)', result)
        self.assertNotIn('<link', result)

    def test_font_subsets_cover_dynamic_and_escaped_text_and_keep_sources(self):
        assets = self.root / 'assets'
        assets.mkdir()
        for name in ('roboto-light', 'roboto-regular'):
            (assets / (name + '.woff2')).write_bytes((Path('concept/assets') / (name + '.woff2')).read_bytes())
        (self.root / 'index.html').write_text('<html lang="uk">Київ м² → &#x3A8;<link rel="preload" href="/assets/roboto-light.woff2"></html>')
        (self.root / 'app.js').write_text('const text = "Your privacy choices: \u0490"; const escaped = "\\u03A9";')
        (self.root / 'style.css').write_text('@font-face{src:url(assets/roboto-regular.woff2)}a:after{content:"\\2197"}')
        sizes = subset_fonts(self.root)
        for name in sizes:
            original = assets / (name + '.woff2')
            target = assets / 'fonts' / (name + '-subset.woff2')
            before = target.read_bytes()
            with TTFont(original) as source, TTFont(target) as font:
                for code in map(ord, 'КиївҐґм²→↗Your privacy choicesΩΨ'):
                    if code in source.getBestCmap():
                        self.assertIn(code, font.getBestCmap())
                        self.assertEqual(source['hmtx'][source.getBestCmap()[code]], font['hmtx'][font.getBestCmap()[code]])
                        original_pen = DecomposingRecordingPen(source.getGlyphSet())
                        subset_pen = DecomposingRecordingPen(font.getGlyphSet())
                        source.getGlyphSet()[source.getBestCmap()[code]].draw(original_pen)
                        font.getGlyphSet()[font.getBestCmap()[code]].draw(subset_pen)
                        self.assertEqual(original_pen.value, subset_pen.value)
                self.assertNotIn('fpgm', font)
                self.assertNotIn('prep', font)
                self.assertIn('GPOS', font)
            self.assertEqual(original.read_bytes(), (Path('concept/assets') / original.name).read_bytes())
            self.assertLess(len(before), original.stat().st_size)
        # Repeating a generated build step must not change font bytes.
        first = {p.name: p.read_bytes() for p in (assets / 'fonts').glob('*.woff2')}
        subset_fonts(self.root)
        self.assertEqual(first, {p.name: p.read_bytes() for p in (assets / 'fonts').glob('*.woff2')})

    def test_source_directories_cannot_be_rewritten(self):
        for function in (inline_consent, subset_fonts, inline_catalog_styles):
            with self.assertRaises(ValueError):
                function(Path('concept'))


if __name__ == '__main__':
    unittest.main()
