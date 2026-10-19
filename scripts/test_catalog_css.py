from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from catalog_css import catalog_classes, prune_catalog_css
from first_paint import inline_catalog_styles


class CatalogCssTests(unittest.TestCase):
    def test_only_impossible_selector_arms_are_removed_without_cascade_changes(self):
        css = ('/* shared */@font-face{font-family:Roboto;src:url(font.woff2)}'
               ':root{--gap:28px}*{box-sizing:border-box}'
               '.home,.card:hover,.card:focus-visible{color:red}'
               '@media(max-width:700px){.home{display:none}.card::before{content:"↗"}}'
               '.card{color:blue}@supports(display:grid){.card{gap:var(--gap)}}'
               '@layer earlier{.home{color:red}}@layer later;')
        result = prune_catalog_css(css, {'card'})
        self.assertNotIn('.home', result)
        self.assertIn('.card:hover,.card:focus-visible{color:red}', result)
        self.assertIn('@media(max-width:700px){.card::before{content:"↗"}}', result)
        self.assertIn('@layer earlier{}@layer later;', result)
        self.assertLess(result.index('color:red'), result.index('color:blue'))
        for untouched in ['/* shared */', '@font-face{font-family:Roboto;src:url(font.woff2)}',
                          ':root{--gap:28px}', '*{box-sizing:border-box}',
                          '@supports(display:grid){.card{gap:var(--gap)}}']:
            self.assertIn(untouched, result)
        self.assertEqual(result, prune_catalog_css(css, {'card'}))
        self.assertEqual(result, prune_catalog_css(result, {'card'}))

    def test_functional_selectors_unknown_rules_nesting_and_escaped_classes_are_safe(self):
        css = (':not(.missing){color:red}:is(.missing,a){color:blue}'
               'body:has(.missing){color:green}:where(.missing,a){color:pink}'
               '.card:nth-child(2){display:block}'
               '@unknown x{.missing{display:none}}'
               '.parent{& .child{color:red}}.\\63 ard:hover{color:yellow}'
               '[class~="other"]{color:purple}')
        self.assertEqual(css.replace('.\\63 ard', '.card'), prune_catalog_css(css, {'card'}))

    def test_opt_in_prunes_only_mandatory_outer_classes_beside_logical_functions(self):
        css = ('.other-house :is(.gallery, figure) .images{height:100px}'
               '.case :is(.missing,figure){color:red}'
               '.case:not(.absent){color:blue}.case:has(.absent){color:green}'
               '.case :where(.missing,a){display:block}'
               '.case:has(:is(.absent,a)){gap:4px}'
               '.other-house:not(.case),.case:not(.absent){padding:8px}'
               '@media print{.other-house:has(img){display:none}.case:not(.absent){color:black}}')
        classes = {'case', 'images', 'gallery'}
        self.assertEqual(prune_catalog_css(css, classes), css)
        result = prune_catalog_css(css, classes, prune_functional_ancestors=True)
        self.assertNotIn('.other-house', result)
        for rule in ('.case :is(.missing,figure){color:red}',
                     '.case:not(.absent){color:blue}', '.case:has(.absent){color:green}',
                     '.case :where(.missing,a){display:block}',
                     '.case:has(:is(.absent,a)){gap:4px}',
                     '.case:not(.absent){padding:8px}',
                     '@media print{.case:not(.absent){color:black}}'):
            self.assertIn(rule, result)

    def test_opt_in_keeps_unknown_functions_errors_nesting_and_dynamic_prefixes(self):
        css = ('.absent:future(.case){color:red}'
               '.absent:is(:future(.case)){color:blue}'
               '.absent:is(.case]){color:green}'
               '.absent:is(& .case){color:pink}'
               '.absent{& .child{color:black}}'
               '.state-open:not(.absent){display:block}'
               '.case:not(.absent)::before{content:"yes"}')
        self.assertEqual(prune_catalog_css(css, {'case', 'state-'},
                                          prune_functional_ancestors=True), css)
        self.assertEqual(prune_catalog_css(css, None, prune_functional_ancestors=True), css)

    def test_union_covers_other_languages_inline_consent_and_versioned_scripts(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'agent.js').write_text('node.classList.add("expanded");')
            ua = root / 'ua.html'
            ua.write_text('<article class="картка"></article><script>const html = '
                          '\'<div class="analytics-consent__copy">Київ</div>\';</script>')
            en = root / 'en.html'
            en.write_text('<article class="card en-only"></article><script src="/agent.js?v=abc" defer></script>')
            classes = catalog_classes(root, [ua, en])
            self.assertTrue({'картка', 'card', 'en-only', 'analytics-consent__copy', 'expanded'}.issubset(classes))
            css = '.картка,.en-only,.analytics-consent__copy,.expanded:focus{color:red}'
            self.assertEqual(css, prune_catalog_css(css, classes))
            (root / 'agent.js').write_text('node.className="\\u0063ard";')
            self.assertIsNone(catalog_classes(root, [ua, en]))
            self.assertEqual(css, prune_catalog_css(css, None))

    def test_inline_only_generated_catalogs_preserves_bundle_sources_and_resources(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.nojekyll').touch()
            css = '.home{color:red}.card{color:blue}@font-face{src:url(assets/font.woff2?v=abc)}'
            bundle = root / 'catalog-bundle.css'
            bundle.write_text(css)
            shared = root / 'style.css'
            shared.write_text(css)
            head = '<link rel="stylesheet" href="/catalog-bundle.css?v=xyz">'
            page = root / 'index.html'
            page.write_text(head + '<article class="card">Київ</article>')
            other = root / 'other.html'
            other.write_text('<link rel="stylesheet" href="/style.css"><div class="home"></div>')
            untouched = other.read_bytes()
            self.assertEqual(inline_catalog_styles(root), 1)
            first = page.read_bytes()
            self.assertNotIn(b'.home', first)
            self.assertIn(b'.card{color:blue}', first)
            self.assertIn(b'url(/assets/font.woff2?v=abc)', first)
            self.assertEqual(inline_catalog_styles(root), 0)
            self.assertEqual(first, page.read_bytes())
            self.assertEqual(untouched, other.read_bytes())
            self.assertEqual(css, bundle.read_text())
            self.assertEqual(css, shared.read_text())
            (root / '.nojekyll').unlink()
            with self.assertRaises(ValueError):
                inline_catalog_styles(root)

    def test_unknown_script_is_full_css_fallback(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            page = root / 'index.html'
            for src in ['https://example.com/controller.js', '/missing.js', '/../outside.js']:
                page.write_text('<script src="' + src + '"></script>')
                self.assertIsNone(catalog_classes(root, [page]))

    def test_runtime_prefix_states_survive_and_unknown_expressions_keep_full_css(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'automation.js'
            page = root / 'index.html'
            page.write_text('<div class="story-sticky visual-image"></div><script src="/automation.js"></script>')
            script.write_text("stage.classList.toggle('device-'+key,on); panel.classList.toggle('system-' + kind,on);")
            css = '.story-sticky.device-biodynamic .visual-image{filter:sepia(.22)}.system-air{opacity:1}.absent{color:red}'
            pruned = prune_catalog_css(css, catalog_classes(root, [page]))
            self.assertIn('.device-biodynamic', pruned)
            self.assertIn('.system-air', pruned)
            self.assertNotIn('.absent', pruned)
            for expression in ['name', "'device'+suffix", 'getClass()', '`device-${key}`']:
                script.write_text('stage.classList.toggle(' + expression + ',on);')
                classes = catalog_classes(root, [page])
                self.assertIsNone(classes)
                self.assertEqual(css, prune_catalog_css(css, classes))
            script.write_text("stage.classList.add('known', dynamicName);")
            self.assertIsNone(catalog_classes(root, [page]))

    def test_malformed_css_is_retained_instead_of_partially_pruned(self):
        for css in ['.missing{color:red}}', '@media all{.missing{color:red}}}']:
            self.assertEqual(css, prune_catalog_css(css, set()))


if __name__ == '__main__':
    unittest.main()
