import json
import base64
import brotli
import hashlib
import random
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
        (self.site / 'index.html').write_text('<html><section id="contact"><a href="tel:+380123456789">Phone</a></section></html>')
        (self.site / 'project-catalog.json').write_text(json.dumps({'version': 1, 'projects': []}))
        (self.site / '.well-known').mkdir()
        (self.site / '.well-known/api-catalog').write_text(json.dumps({'linkset': [
            {'anchor': 'https://piskor.com.ua/.well-known/api-catalog',
             'item': [{'href': 'https://piskor.com.ua/project-catalog.json', 'type': 'application/json'}]}]}))
        (self.site / 'agent-markdown').mkdir()
        (self.site / 'agent-markdown/index.md').write_bytes('# Простір\n'.encode())
        self.rows = [{'url': '/', 'markdown': '/agent-markdown/index.md', 'language': 'uk'}]
        self.inventory()

    def tearDown(self):
        self.tmp.cleanup()

    def inventory(self):
        (self.site / 'agent-markdown/routes.json').write_text(json.dumps({'version': 1, 'pages': self.rows}))

    def html_fixture(self):
        relative = worker.HTML_ROUTE.lstrip('/') + 'index.html'
        page = self.site / relative
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_bytes(('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                          '<meta name="robots" content="noindex,nofollow">'
                          '<link rel="canonical" href="https://piskor.com.ua' + worker.HTML_ROUTE
                          + '"></head><body>Space · Простір 🥁</body></html>\n').encode())
        markdown = '/agent-markdown/' + relative.replace('.html', '.md')
        document = self.site / markdown.lstrip('/')
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text('# Space\n')
        self.rows.append({'url': worker.HTML_ROUTE, 'markdown': markdown, 'language': 'en'})
        self.inventory()
        return page

    def test_precompressed_html_is_exact_deterministic_final_artifact_with_provenance(self):
        page = self.html_fixture()
        expected = page.read_bytes()
        a = worker.build(self.site, self.root / 'a', REVISION)
        b = worker.build(self.site, self.root / 'b', REVISION)
        self.assertEqual(a, b)
        payload = (self.root / 'a/worker.mjs').read_text().split('const PUBLIC_PAGE_DATA=', 1)[1].split(';\n', 1)[0]
        data = json.loads(payload)
        item = data['html'][worker.HTML_ROUTE]
        encoded = base64.b64decode(item['bodyBase64'], validate=True)
        self.assertEqual(brotli.decompress(encoded), expected)
        self.assertEqual(item['sha256'], hashlib.sha256(expected).hexdigest())
        self.assertEqual(item['encodedSha256'], hashlib.sha256(encoded).hexdigest())
        self.assertEqual(item['bytes'], len(expected))
        self.assertEqual(item['encodedBytes'], len(encoded))
        self.assertEqual(item['revision'], REVISION)
        self.assertEqual(item['quality'], 11)
        self.assertEqual(a['artifact_source_sha256'][item['sourcePath']], item['sha256'])
        self.assertEqual(a['html_representations'][worker.HTML_ROUTE],
                         {key: value for key, value in item.items() if key != 'bodyBase64'})
        self.assertEqual(page.read_bytes(), expected)
        page.write_bytes(expected.replace(b'Space', b'Updated space'))
        changed = worker.build(self.site, self.root / 'c', '2' * 40)
        self.assertNotEqual(a['html_representations'], changed['html_representations'])
        self.assertEqual(changed['html_representations'][worker.HTML_ROUTE]['revision'], '2' * 40)

    def test_precompressed_route_rejects_missing_and_wrong_canonical_language_or_robots(self):
        page = self.html_fixture()
        original = page.read_bytes()
        for before, after in ((b'lang="en"', b'lang="uk"'),
                              (b'noindex,nofollow', b'index,follow'),
                              (b'href="https://piskor.com.ua/en/', b'href="https://wrong.test/en/'),
                              (b'<meta charset=', b'<meta http-equiv="refresh" content="0;url=/"><meta charset=')):
            with self.subTest(after=after):
                page.write_bytes(original.replace(before, after))
                with self.assertRaisesRegex(ValueError, 'canonical English'):
                    worker.build(self.site, self.root / 'bad', REVISION)
        page.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing/escaping'):
            worker.build(self.site, self.root / 'missing', REVISION)

    def test_incompressible_html_exceeding_brotli_guard_requires_performance_revalidation(self):
        page = self.html_fixture()
        # Deterministic high-entropy, valid UTF8 HTML content, rather than a
        # repeated filler string that Brotli could shrink below the real guard.
        noise = base64.b64encode(random.Random(731).randbytes(90_000))
        original = page.read_bytes()
        page.write_bytes(original.replace(b'</body>', noise + b'</body>'))
        self.assertGreater(len(brotli.compress(page.read_bytes(), quality=11, mode=brotli.MODE_TEXT)),
                           worker.MAX_HTML_BROTLI_BYTES)
        with self.assertRaisesRegex(ValueError, 'renew performance verification'):
            worker.build(self.site, self.root / 'over-budget', REVISION)
        self.assertFalse((self.root / 'over-budget').exists())

    def test_deterministic_and_artifact_unchanged(self):
        before = {str(p): p.read_bytes() for p in self.site.rglob('*') if p.is_file()}
        a = worker.build(self.site, self.root / 'a', REVISION)
        b = worker.build(self.site, self.root / 'b', REVISION)
        self.assertEqual(a, b)
        for name in ('worker.mjs', 'manifest.json'):
            self.assertEqual((self.root / 'a' / name).read_bytes(), (self.root / 'b' / name).read_bytes())
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.site.rglob('*') if p.is_file()})
        self.assertEqual(a['mcp_protocol_versions'], ['2026-07-28', '2025-11-25'])
        self.assertEqual(a['mcp_server_version'], '1.0.0+' + REVISION)
        self.assertEqual(set(a['mcp_publications']), {'/.well-known/mcp/server-card.json',
                                                    '/.well-known/api-catalog', '/agent-api/mcp.md'})
        self.assertIn('mcp_discovery', a['source_sha256'])
        self.assertIn('wrangler_config', a['source_sha256'])
        self.assertIn('project-catalog.json', a['artifact_source_sha256'])
        self.assertNotIn(b"from './mcp-server.mjs'", (self.root / 'a/worker.mjs').read_bytes())
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

    def test_module_composition_rejects_changed_or_extra_imports(self):
        changed = self.root / 'changed-handler.mjs'
        changed.write_bytes(worker.HANDLER.read_bytes().replace(worker.MCP_IMPORT, b''))
        with patch.object(worker, 'HANDLER', changed):
            with self.assertRaisesRegex(ValueError, 'exactly one MCP'):
                worker.build(self.site, self.root / 'out', REVISION)
        changed.write_bytes(worker.HANDLER.read_bytes() + b"\nimport 'unreviewed-module';\n")
        with patch.object(worker, 'HANDLER', changed):
            with self.assertRaisesRegex(ValueError, 'runtime imports'):
                worker.build(self.site, self.root / 'out', REVISION)
        changed.write_bytes(worker.MCP_HANDLER.read_bytes() + b"\nimport('runtime-module');\n")
        with patch.object(worker, 'MCP_HANDLER', changed):
            with self.assertRaisesRegex(ValueError, 'runtime imports'):
                worker.build(self.site, self.root / 'out', REVISION)
        self.assertFalse((self.root / 'out').exists())

    def test_budget_fails_before_output(self):
        with patch.object(worker, 'MAX_BUNDLE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'budget'):
                worker.build(self.site, self.root / 'out', REVISION)
        self.assertFalse((self.root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
