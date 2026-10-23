from pathlib import Path
import tempfile
import unittest

from engineering_minification import minify_engineering_pages, validate_engineering_consent, ROUTES


class EngineeringMinificationTest(unittest.TestCase):
    def test_exact_consent_transform_scoped_pages_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.nojekyll').touch()
            source = Path('concept/analytics-consent.js').read_text()
            (root / 'analytics-consent.js').write_text(source)
            html = ('<!doctype html><html lang="uk"><head><title>Service</title></head>'
                    '<body class="engineering-page"><main id="main"><p>Lighting and comfort</p></main>'
                    '<script data-consent-inline data-measurement-id="G-TEST123">' + source + '</script></body></html>')
            pages = []
            for route in ROUTES:
                page = root / route
                page.parent.mkdir(parents=True)
                page.write_text(html)
                pages.append(page)
            unrelated = root / 'index.html'
            unrelated.write_text(html)
            self.assertEqual(minify_engineering_pages(root), 2)
            self.assertEqual(unrelated.read_text(), html)
            for page in pages:
                self.assertLess(len(page.read_text()), len(html))
                validate_engineering_consent(root, page.read_text())
                self.assertLess(page.read_text().index('data-consent-inline'), page.read_text().index('<main'))
            self.assertEqual(minify_engineering_pages(root), 0)
            pages[0].write_text(html)
            pages[1].write_text(html.replace('window.dataLayer', 'window.changedDataLayer'))
            with self.assertRaisesRegex(ValueError, 'exact pinned transform'):
                minify_engineering_pages(root)
            self.assertEqual(pages[0].read_text(), html)
