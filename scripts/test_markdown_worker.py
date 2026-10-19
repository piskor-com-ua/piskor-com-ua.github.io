import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import build_markdown_worker as worker

REVISION = '1' * 40


class MarkdownWorkerBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        (self.site / '.nojekyll').touch()
        (self.site / 'index.html').write_text('<html>Original unchanged</html>')
        (self.site / 'agent-markdown').mkdir()
        (self.site / 'agent-markdown/index.md').write_bytes('# Простір\n'.encode())
        self.rows = [{'url': '/', 'markdown': '/agent-markdown/index.md', 'language': 'uk'}]
        self.inventory()

    def tearDown(self):
        self.tmp.cleanup()

    def inventory(self):
        (self.site / 'agent-markdown/routes.json').write_text(json.dumps({'version': 1, 'pages': self.rows}))

    def test_deterministic_and_artifact_unchanged(self):
        before = {str(p): p.read_bytes() for p in self.site.rglob('*') if p.is_file()}
        a = worker.build(self.site, self.root / 'a', REVISION)
        b = worker.build(self.site, self.root / 'b', REVISION)
        self.assertEqual(a, b)
        for name in ('worker.mjs', 'manifest.json'):
            self.assertEqual((self.root / 'a' / name).read_bytes(), (self.root / 'b' / name).read_bytes())
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.site.rglob('*') if p.is_file()})
        self.assertEqual(a['markdown_files']['/agent-markdown/index.md']['bytes'], len('# Простір\n'.encode()))

    def test_outside_artifact_and_no_overwrite(self):
        with self.assertRaises(ValueError):
            worker.build(self.site, self.site / 'worker', REVISION)
        worker.build(self.site, self.root / 'out', REVISION)
        with self.assertRaises(ValueError):
            worker.build(self.site, self.root / 'out', REVISION)

    def test_duplicate_missing_and_uninventoried_html(self):
        self.rows *= 2
        self.inventory()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            worker.build(self.site, self.root / 'a', REVISION)
        self.rows = self.rows[:1]
        self.inventory()
        (self.site / 'extra.html').write_text('<html>')
        with self.assertRaisesRegex(ValueError, 'every generated HTML'):
            worker.build(self.site, self.root / 'b', REVISION)

    def test_escape_and_symlink_rejected(self):
        (self.root / 'outside.md').write_text('# Outside')
        (self.site / 'agent-markdown/index.md').unlink()
        (self.site / 'agent-markdown/index.md').symlink_to(self.root / 'outside.md')
        with self.assertRaisesRegex(ValueError, 'escaping'):
            worker.build(self.site, self.root / 'out', REVISION)

    def test_unknown_query_and_invalid_revision_rejected(self):
        self.rows[0]['url'] = '/?lang=en'
        self.inventory()
        with self.assertRaises(ValueError):
            worker.build(self.site, self.root / 'a', REVISION)
        with self.assertRaises(ValueError):
            worker.build(self.site, self.root / 'b', 'main')

    def test_404_en_and_uk_alias(self):
        (self.site / '404.html').write_text('<html>UK</html>')
        for name in ('404.md', '404-en.md'):
            (self.site / 'agent-markdown' / name).write_text('# ' + name)
        self.rows += [{'url': '/404.html', 'markdown': '/agent-markdown/404.md', 'language': 'uk'},
                      {'url': '/404.html?lang=en', 'markdown': '/agent-markdown/404-en.md', 'language': 'en'}]
        self.inventory()
        result = worker.build(self.site, self.root / 'out', REVISION)
        self.assertEqual(result['source_page_states'], 3)
        self.assertEqual(result['routing_keys_with_uk404_alias'], 4)

    def test_budget_fails_before_output(self):
        with patch.object(worker, 'MAX_BUNDLE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'budget'):
                worker.build(self.site, self.root / 'out', REVISION)
        self.assertFalse((self.root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
