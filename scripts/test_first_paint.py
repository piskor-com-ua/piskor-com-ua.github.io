from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import unittest
from unittest.mock import patch

from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
from first_paint import (inline_consent, subset_fonts, inline_catalog_styles,
                         inline_page_styles, inline_page_critical_scripts,
                         PAGE_STYLE_SCOPES)


class FirstPaintTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.nojekyll').touch()

    def test_consent_runs_after_page_content_and_before_deferred_scripts_finish(self):
        (self.root / 'analytics-consent.js').write_text('document.body.dataset.test = document.currentScript.dataset.measurementId;')
        page = self.root / 'index.html'
        page.write_text('<html><head><script src="/analytics-consent.js" data-measurement-id="G-ABC" defer></script></head><body class="test"><header>Studio</header></body></html>')
        self.assertEqual(inline_consent(self.root), 1)
        result = page.read_text()
        self.assertNotIn('src="/analytics-consent.js"', result)
        self.assertIn('<header>Studio</header><script data-consent-inline data-measurement-id="G-ABC">', result)
        self.assertLess(result.index('<header>'), result.index('document.body'))
        self.assertLess(result.index('document.body'), result.index('</body>'))
        self.assertEqual(inline_consent(self.root), 0)

    def test_consent_inlining_fails_closed_when_page_has_no_body_end(self):
        (self.root / 'analytics-consent.js').write_text('document.body.dataset.test = true;')
        page = self.root / 'index.html'
        page.write_text('<html><head><script src="/analytics-consent.js" data-measurement-id="G-ABC"></script></head><body>Content')
        with self.assertRaisesRegex(ValueError, 'Missing consent configuration or body'):
            inline_consent(self.root)

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
        for function in (inline_consent, subset_fonts, inline_catalog_styles, inline_page_styles):
            with self.assertRaises(ValueError):
                function(Path('concept'))

    def test_page_styles_keep_cascade_dynamic_states_and_relative_resources(self):
        (self.root / 'styles').mkdir()
        (self.root / 'styles/first.css').write_text('.used{background:url(../assets/bg.webp?v=abc)}.future:focus-visible{color:red}.absent{color:blue}')
        (self.root / 'second.css').write_text('.used{color:green}@media print{.future{display:block}}')
        (self.root / 'controller.js').write_text('element.classList.add("future");')
        page = self.root / 'index.html'
        page.write_text('<head><link rel="stylesheet" href="/styles/first.css?v=a"><style>.used{color:red}</style><link rel="stylesheet" href="/second.css?v=b" media="screen"><script src="/controller.js"></script></head><body class="used">Actual content</body>')
        self.assertEqual(inline_page_styles(self.root), 2)
        html = page.read_text()
        self.assertIn('/assets/bg.webp?v=abc', html)
        self.assertIn('.future:focus-visible', html)
        self.assertNotIn('.absent', html)
        self.assertLess(html.index('background:'), html.index('.used{color:red}'))
        self.assertLess(html.index('.used{color:red}'), html.index('.used{color:green}'))
        self.assertIn('media="screen"', html)
        self.assertIn('Actual content', html)
        self.assertEqual(inline_page_styles(self.root), 0)

    def test_page_families_keep_both_languages_all_cases_and_their_dynamic_states(self):
        (self.root / 'shared.css').write_text(
            '@font-face{font-family:Brand;src:url(/font.woff2)}body{color:black}'
            '.home-uk{color:red}.home-en{color:blue}.home-open:focus-visible{outline:0}'
            '.case-one{color:red}.case-two{color:blue}.gallery-open:hover{color:green}'
            '.not-found-page{color:red}.error-open{color:blue}.unused{display:none}'
            ':is(.future-state,a){color:inherit}')
        (self.root / 'home.js').write_text('element.classList.add("home-open");')
        (self.root / 'case.js').write_text('element.classList.add("gallery-open");')
        (self.root / 'error.js').write_text('element.classList.add("error-open");')
        fixtures = {
            'index.html': ('home-uk', 'home'),
            'en/index.html': ('home-en', None),
            'portfolio/2026/first/index.html': ('project-page case-one', 'case'),
            'en/portfolio/2025/second/index.html': ('project-page case-two', None),
            '404.html': ('not-found-page', 'error'),
            'old-alias/index.html': ('alias', None),
        }
        for relative, (classes, controller) in fixtures.items():
            page = self.root / relative
            page.parent.mkdir(parents=True, exist_ok=True)
            script = '<script src="/' + controller + '.js"></script>' if controller else ''
            page.write_text('<head><link rel="stylesheet" href="/shared.css">' + script
                            + '</head><body class="' + classes + '">Content</body>')
        self.assertEqual(inline_page_styles(self.root), len(fixtures))
        for relative in ('index.html', 'en/index.html'):
            html = (self.root / relative).read_text()
            for selector in ('.home-uk', '.home-en', '.home-open:focus-visible'):
                self.assertIn(selector, html)
            for selector in ('.case-one', '.gallery-open', '.not-found-page', '.error-open'):
                self.assertNotIn(selector, html)
        for relative in ('portfolio/2026/first/index.html', 'en/portfolio/2025/second/index.html'):
            html = (self.root / relative).read_text()
            for selector in ('.case-one', '.case-two', '.gallery-open:hover'):
                self.assertIn(selector, html)
            for selector in ('.home-uk', '.home-open', '.not-found-page', '.error-open'):
                self.assertNotIn(selector, html)
        error = (self.root / '404.html').read_text()
        self.assertIn('.not-found-page', error)
        self.assertIn('.error-open', error)
        self.assertNotIn('.home-uk', error)
        self.assertNotIn('.case-one', error)
        unknown = (self.root / 'old-alias/index.html').read_text()
        for selector in ('.home-uk', '.home-en', '.home-open', '.case-one', '.case-two', '.gallery-open', '.not-found-page', '.error-open'):
            self.assertIn(selector, unknown)
        for relative in fixtures:
            html = (self.root / relative).read_text()
            self.assertIn('@font-face', html)
            self.assertIn('body{color:black}', html)
            self.assertIn(':is(.future-state,a)', html)
            self.assertNotIn('.unused', html)

    def test_unknown_controller_disables_pruning_only_for_its_family_and_unknown_pages(self):
        css = '.home-state{color:red}.case-state{color:blue}.unknown-state{color:green}'
        (self.root / 'shared.css').write_text(css)
        for relative, classes, script in (
            ('index.html', 'home-state', '<script src="https://example.test/controller.js"></script>'),
            ('portfolio/2026/first/index.html', 'project-page case-state', ''),
            ('alias/index.html', 'alias', ''),
        ):
            page = self.root / relative
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text('<link rel="stylesheet" href="/shared.css">' + script
                            + '<body class="' + classes + '">Content</body>')
        self.assertEqual(inline_page_styles(self.root), 3)
        self.assertIn(css, (self.root / 'index.html').read_text())
        self.assertIn(css, (self.root / 'alias/index.html').read_text())
        case = (self.root / 'portfolio/2026/first/index.html').read_text()
        self.assertIn('.case-state', case)
        self.assertNotIn('.home-state', case)
        self.assertNotIn('.unknown-state', case)

    def scoped_case(self, script='', route='en/portfolio/2022/zabava-restaurant-sambir/index.html'):
        page = self.root / route
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text('<html lang="en"><head><link rel="stylesheet" href="/shared.css">'
                        + script + '</head><body class="project-page zabava-restaurant-sambir-page">'
                        '<dialog class="project-lightbox"><div class="lightbox-caption"></div>'
                        '<div class="lightbox-controls"></div></dialog></body></html>')
        return page

    def test_explicit_case_scope_leaves_every_other_output_byte_identical(self):
        css = ('.zabava-restaurant-sambir-page{color:red}.other-case{color:blue}'
               '.home-only{color:green}.ua-only{color:purple}.alias-only{color:gray}'
               '.other-case :is(a,button){color:blue}.ua-only:not(.unavailable){color:purple}')
        (self.root / 'shared.css').write_text(css)
        target = self.scoped_case()
        for route in sorted(PAGE_STYLE_SCOPES - {target.relative_to(self.root).as_posix()}):
            self.scoped_case(route=route)
        fixtures = {
            'index.html': 'home-only', 'en/index.html': 'home-only',
            'portfolio/2022/zabava-restaurant-sambir/index.html': 'project-page ua-only',
            'en/portfolio/2021/other/index.html': 'project-page other-case',
            '404.html': 'not-found-page', 'alias/index.html': 'alias-only',
        }
        for relative, classes in fixtures.items():
            page = self.root / relative
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text('<link rel="stylesheet" href="/shared.css"><body class="'
                            + classes + '">Unchanged content</body>')
        originals = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('first_paint.PAGE_STYLE_SCOPES', frozenset()):
            inline_page_styles(self.root)
        baseline = {p: p.read_bytes() for p in originals}
        for page, data in originals.items():
            page.write_bytes(data)
        inline_page_styles(self.root)
        changed = sorted(p.relative_to(self.root).as_posix() for p in originals
                         if p.read_bytes() != baseline[p])
        self.assertEqual(changed, sorted(PAGE_STYLE_SCOPES))
        self.assertIn('.zabava-restaurant-sambir-page{color:red}', target.read_text())
        self.assertNotIn('.other-case', target.read_text())
        self.assertNotIn('.ua-only', target.read_text())

    def test_current_slow_production_case_uses_route_scoped_css(self):
        self.assertIn('portfolio/2024/domazhyr-house/index.html', PAGE_STYLE_SCOPES)

    def test_case_scope_preserves_shared_controllers_consent_and_native_dialog_states(self):
        for name in ('analytics-consent.js', 'portfolio.js', 'agent-tools.js', 'url-compat.js'):
            (self.root / name).write_bytes((Path('concept') / name).read_bytes())
        selectors = ('.analytics-consent', '.analytics-consent__copy', '.analytics-preferences',
                     '.project-lightbox[open]', '.project-lightbox::backdrop',
                     '.lightbox-caption', '.lightbox-controls button:focus-visible')
        css = ''.join(selector + '{color:red}' for selector in selectors)
        css += '@media(max-width:700px){.lightbox-controls{gap:12px}}'
        css += '.other-case{color:blue}:is(.future,a){color:inherit}'
        (self.root / 'shared.css').write_text(css)
        scripts = '<script src="/analytics-consent.js" data-measurement-id="G-ABC" defer></script>'
        for name in ('agent-tools.js', 'portfolio.js', 'url-compat.js'):
            digest = hashlib.sha256((self.root / name).read_bytes()).hexdigest()[:12]
            scripts += '<script src="/' + name + '?v=' + digest + '" defer></script>'
        page = self.scoped_case(scripts)
        # Exercise the real build order, including source-hashed inline payloads.
        inline_consent(self.root)
        inline_page_critical_scripts(self.root)
        inline_page_styles(self.root)
        result = page.read_text()
        for selector in selectors:
            self.assertIn(selector + '{color:red}', result)
        self.assertIn('@media(max-width:700px){.lightbox-controls{gap:12px}}', result)
        self.assertIn(':is(.future,a){color:inherit}', result)
        self.assertNotIn('.other-case', result)

    def test_case_scope_unknown_controller_keeps_complete_stylesheet(self):
        css = '.zabava-restaurant-sambir-page{color:red}.future-state{color:blue}'
        (self.root / 'shared.css').write_text(css)
        for script in ('<script src="https://example.test/unknown.js"></script>',
                       '<script src="/missing.js"></script>',
                       '<script src="/new-controller.js"></script>',
                       '<script>element.className = computedName;</script>',
                       '<script>element.classList.add(computedName);</script>',
                       '<script>element.classList.toggle("\\u0066uture-state");</script>'):
            with self.subTest(script=script):
                (self.root / 'new-controller.js').write_text('element.className = computedName;')
                page = self.scoped_case(script)
                inline_page_styles(self.root)
                self.assertIn(css, page.read_text())

    def test_changed_reviewed_controller_keeps_full_css_for_uninferable_future_classes(self):
        css = '.zabava-restaurant-sambir-page{color:red}.future-state{color:blue}'
        (self.root / 'shared.css').write_text(css)
        (self.root / 'portfolio.js').write_text('element.className = computedName;')
        page = self.scoped_case('<script src="/portfolio.js"></script>')
        inline_page_styles(self.root)
        self.assertIn(css, page.read_text())

    def test_case_scope_stale_inline_controller_keeps_complete_stylesheet(self):
        css = '.zabava-restaurant-sambir-page{color:red}.future-state{color:blue}'
        (self.root / 'shared.css').write_text(css)
        for name in ('agent-tools.js', 'portfolio.js'):
            (self.root / name).write_bytes((Path('concept') / name).read_bytes())
        scripts = ''.join('<script src="/' + name + '?v='
                          + hashlib.sha256((self.root / name).read_bytes()).hexdigest()[:12]
                          + '" defer></script>' for name in ('agent-tools.js', 'portfolio.js'))
        page = self.scoped_case(scripts)
        inline_page_critical_scripts(self.root)
        page.write_text(page.read_text().replace("dialog.showModal();", "dialog.showModal(); unknown();"))
        inline_page_styles(self.root)
        self.assertIn(css, page.read_text())

    def test_deferred_home_styles_keep_versioned_template_and_native_fallback_links(self):
        (self.root / 'base.css').write_text('body{color:black}')
        automation = '.device-biodynamic .visual-image{filter:sepia(.22)}'
        (self.root / 'automation.css').write_text(automation)
        link = '<link rel="stylesheet" href="/automation.css?v=actualhash" data-home-deferred-style="automation">'
        page = self.root / 'index.html'
        page.write_text('<head><link rel="stylesheet" href="/base.css">'
                        '<noscript>' + link + '</noscript>'
                        '<template id="home-controllers">' + link
                        + '<script src="/app.js?v=actualjs"></script></template></head><body>Home</body>')
        self.assertEqual(inline_page_styles(self.root), 1)
        html = page.read_text()
        self.assertIn('<noscript>' + link + '</noscript>', html)
        self.assertIn('<template id="home-controllers">' + link, html)
        self.assertNotIn(automation, html)
        self.assertEqual((self.root / 'automation.css').read_text(), automation)
        self.assertEqual(inline_page_styles(self.root), 0)
        for wrong in [link.replace('automation"', 'other"'), link.replace('/automation.css', '/base.css')]:
            page.write_text('<template>' + wrong + '</template>')
            with self.assertRaises(ValueError):
                inline_page_styles(self.root)
        page.write_text('<body>Home</body>')
        case = self.root / 'portfolio/2026/case/index.html'
        case.parent.mkdir(parents=True)
        case.write_text('<body class="project-page">' + link + '</body>')
        with self.assertRaises(ValueError):
            inline_page_styles(self.root)


if __name__ == '__main__':
    unittest.main()
