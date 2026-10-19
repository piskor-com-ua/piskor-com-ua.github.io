from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import re
import unittest

from case_minification import minify_fragment, minify_reviewed_cases
from first_paint import inline_consent, inline_page_critical_scripts, validate_page_inline_scripts


class CaseMinificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.nojekyll').touch()
        for name in ('agent-tools.js', 'portfolio.js', 'analytics-consent.js'):
            (self.root / name).write_bytes((Path('concept') / name).read_bytes())
        self.relative = 'en/portfolio/2022/zabava-restaurant-sambir/index.html'
        self.page = self.root / self.relative
        self.page.parent.mkdir(parents=True)
        self.schema = {'@context': 'https://schema.org', 'name': 'Zabava & café', 'description': 'Text with < and >.'}
        scripts = ''.join('<script src="/' + name + '?v=' + hashlib.sha256(
            (self.root / name).read_bytes()).hexdigest()[:12] + '" defer></script>'
            for name in ('agent-tools.js', 'portfolio.js'))
        self.page.write_text('<!doctype html><html lang="en"><head>' + scripts
                             + '<script type="application/ld+json">' + json.dumps(self.schema, indent=2)
                             + '</script><script src="/analytics-consent.js" data-measurement-id="G-ABC" defer></script>'
                             + '<style data-page-styles="source">p { color: red; }</style></head><body class="project-page"><a href="#contact">Contact</a>'
                             + '<main id="contact"><p>Natural visible text.</p></main></body></html>')
        inline_consent(self.root)
        inline_page_critical_scripts(self.root)

    def test_only_reviewed_case_is_compiled_and_sources_links_schema_are_preserved(self):
        other = self.root / 'portfolio/2022/zabava-restaurant-sambir/index.html'
        other.parent.mkdir(parents=True)
        other.write_bytes(self.page.read_bytes())
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p != self.page}
        self.assertEqual(minify_reviewed_cases(self.root), 1)
        html = self.page.read_text()
        validate_page_inline_scripts(self.root, self.page, html)
        self.assertIn('<a href="#contact">Contact</a>', html)
        self.assertIn('Natural visible text.', html)
        schema = re.search(r'<script type="application/ld\+json">(.*?)</script>', html).group(1)
        self.assertEqual(json.loads(schema), self.schema)
        style = re.search(r'<style data-page-styles="([a-f0-9]{12})">(.*?)</style>', html)
        self.assertEqual(style[1], hashlib.sha256(style[2].encode()).hexdigest()[:12])
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertEqual(minify_reviewed_cases(self.root), 0)
        self.assertEqual(self.page.read_text(), html)
        with self.assertRaises(ValueError):
            # A minified payload on a different route cannot relax its contract.
            validate_page_inline_scripts(self.root, other, html)

    def test_exact_compiled_contract_rejects_stale_sources_hashes_callbacks_or_extra_scripts(self):
        minify_reviewed_cases(self.root)
        html = self.page.read_text()
        for bad in (html.replace('data-source-sha256="', 'data-source-sha256="bad', 1),
                    html.replace('once:!0', 'once:!1', 1),
                    html.replace('</body>', '<script>window.changed=true</script></body>'),
                    html.replace('data-inline-page-critical="agent-tools.js"',
                                 'data-inline-page-critical="portfolio.js"', 1)):
            with self.subTest(tamper=bad[-100:]), self.assertRaises(ValueError):
                validate_page_inline_scripts(self.root, self.page, bad)
        (self.root / 'portfolio.js').write_text('window.changed = true;')
        with self.assertRaises(ValueError):
            validate_page_inline_scripts(self.root, self.page, html)

    def test_invalid_json_is_rejected_instead_of_silently_rewriting_structured_data(self):
        with self.assertRaises(Exception):
            minify_fragment('<script type="application/ld+json">{"broken":}</script>')
        with self.assertRaises(ValueError):
            minify_reviewed_cases('concept')


if __name__ == '__main__':
    unittest.main()
