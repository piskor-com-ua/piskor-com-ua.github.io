import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import jsonschema

from agent_api import API_CATALOG_PATH, ORIGIN, generate_agent_api
from mcp_discovery import (CARD_MEDIA_TYPE, CARD_PATH, CONTRACT_PATH, GUIDE_PATH,
                           MCP_PUBLICATION_PATHS, generate_mcp_data)
import test_agent_api

REVISION = 'a' * 40
SCHEMAS = Path(__file__).resolve().parent / 'schemas'


class McpDiscoveryTests(unittest.TestCase):
    def fixture(self, site):
        catalog = test_agent_api.AgentApiTests().make_catalog(site)
        generate_agent_api(site)
        # Deliberately different from production: contact facts must come from the artifact.
        contact = ('<section id="contact"><a href="tel:+441234567890">+44 123 456 7890 ↗</a>'
                   '<a href="https://wa.me/441234567890"><span>WhatsApp</span> ↗</a>'
                   '<a href="viber://chat?number=%2B441234567890">Viber ↗</a></section>')
        (site / 'index.html').write_text('<a href="tel:+11111111111">Outside</a>' + contact)
        (site / 'en/index.html').write_text(contact)
        return catalog

    def snapshot(self, site):
        return {str(p.relative_to(site)): p.read_bytes() for p in site.rglob('*') if p.is_file()}

    def test_generated_data_is_deterministic_and_artifact_unchanged(self):
        with TemporaryDirectory() as directory:
            site = Path(directory)
            catalog = self.fixture(site)
            before = self.snapshot(site)
            data = generate_mcp_data(site, REVISION)
            self.assertEqual(data, generate_mcp_data(site, REVISION))
            self.assertEqual(self.snapshot(site), before)
            self.assertEqual(data['projects'], catalog['projects'])
            self.assertEqual(data['contract'], json.loads(CONTRACT_PATH.read_text()))
            self.assertEqual(set(data['publications']), set(MCP_PUBLICATION_PATHS))
            self.assertEqual(data['contacts'], [
                {'name': '+44 123 456 7890', 'url': 'tel:+441234567890'},
                {'name': 'WhatsApp', 'url': 'https://wa.me/441234567890'},
                {'name': 'Viber', 'url': 'viber://chat?number=%2B441234567890'}])
            self.assertNotIn('+380', json.dumps(data['contacts']))

    def test_current_primary_schema_and_real_transport_identity(self):
        schema_bytes = (SCHEMAS / 'mcp-server-card.schema.json').read_bytes()
        self.assertEqual(hashlib.sha256(schema_bytes).hexdigest(),
                         '2c772b51edb367f154771d84ddbae87ddba00a624422c8e46f218a9ac03bf042')
        schema = json.loads(schema_bytes)
        schema['$ref'] = '#/$defs/ServerCard'
        with TemporaryDirectory() as directory:
            site = Path(directory)
            self.fixture(site)
            data = generate_mcp_data(site, REVISION)
            publication = data['publications'][CARD_PATH]
            self.assertEqual(publication['contentType'], CARD_MEDIA_TYPE)
            card = json.loads(publication['body'])
            jsonschema.Draft202012Validator(schema).validate(card)
            self.assertEqual(card['name'], data['contract']['serverInfo']['name'])
            self.assertEqual(card['version'], data['contract']['serverInfo']['version'] + '+' + REVISION)
            self.assertEqual(card['remotes'], [{'type': 'streamable-http',
                                              'url': 'https://piskor.com.ua/mcp',
                                              'supportedProtocolVersions': ['2026-07-28', '2025-11-25']}])
            self.assertEqual(set(card), {'$schema', 'name', 'title', 'version', 'description',
                                         'websiteUrl', 'remotes'})
            changed = generate_mcp_data(site, 'b' * 40)
            self.assertNotEqual(publication, changed['publications'][CARD_PATH])

    def test_rfc9727_preserves_existing_catalog_and_adds_real_mcp(self):
        with TemporaryDirectory() as directory:
            site = Path(directory)
            self.fixture(site)
            original = json.loads((site / API_CATALOG_PATH).read_text())
            data = generate_mcp_data(site, REVISION)
            overlay = json.loads(data['publications']['/' + API_CATALOG_PATH]['body'])
            listing = copy.deepcopy(overlay['linkset'][0])
            self.assertEqual(listing['item'].pop(), {'href': ORIGIN + '/mcp', 'type': 'application/json'})
            self.assertEqual(listing, original['linkset'][0])
            self.assertEqual(overlay['linkset'][1:-1], original['linkset'][1:])
            self.assertEqual(overlay['linkset'][-1]['service-desc'],
                             [{'href': ORIGIN + CARD_PATH, 'type': CARD_MEDIA_TYPE}])

    def test_guide_uses_current_counts_schema_and_full_section_contract(self):
        with TemporaryDirectory() as directory:
            site = Path(directory)
            catalog = self.fixture(site)
            first = generate_mcp_data(site, REVISION)['publications'][GUIDE_PATH]['body']
            catalog['projects'].append(copy.deepcopy(catalog['projects'][0]))
            (site / 'project-catalog.json').write_text(json.dumps(catalog))
            guide = generate_mcp_data(site, REVISION)['publications'][GUIDE_PATH]['body']
            self.assertIn('2 language-specific project records', first)
            self.assertIn('3 language-specific project records', guide)
            self.assertIn('2 Ukrainian (`uk`) and 1 English (`en`)', guide)
            self.assertIn('default language is Ukrainian', guide)
            self.assertIn('full section text', guide)
            self.assertIn('16 KiB', guide)
            self.assertIn('no-store', guide)
            self.assertIn('server/discover', guide)
            self.assertIn('notifications/initialized', guide)
            for tool in json.loads(CONTRACT_PATH.read_text())['tools']:
                self.assertIn('### `' + tool['name'] + '`', guide)
                self.assertIn(json.dumps(tool['inputSchema'], ensure_ascii=False,
                                         sort_keys=True, indent=2), guide)

    def test_invalid_contacts_and_parity_fail_without_writing(self):
        invalid = ['javascript:alert(1)', 'https://wa.me.evil.test/441234567890',
                   'https://wa.me/441234567890?token=private', 'tel:+441234567890?x=1',
                   'viber://chat?number=%2B441234567890&token=private',
                   'viber://chat?number=%2B441234567890&number=%2B441234567891',
                   'https://piskor.com.ua/private', 'tel:123']
        for href in invalid:
            with self.subTest(href=href), TemporaryDirectory() as directory:
                site = Path(directory)
                self.fixture(site)
                (site / 'index.html').write_text('<section id="contact"><a href="' + href + '">Phone</a></section>')
                before = self.snapshot(site)
                with self.assertRaises(ValueError):
                    generate_mcp_data(site, REVISION)
                self.assertEqual(before, self.snapshot(site))
        for html in ['<section id="contact"></section>', '<a href="tel:+441234567890">Outside</a>',
                     '<section id="contact"><a href="tel:+441234567890">Phone</a>'
                     '<a href="tel:+441234567890">Duplicate</a></section>']:
            with self.subTest(html=html), TemporaryDirectory() as directory:
                site = Path(directory)
                self.fixture(site)
                (site / 'index.html').write_text(html)
                with self.assertRaises(ValueError):
                    generate_mcp_data(site, REVISION)
        with TemporaryDirectory() as directory:
            site = Path(directory)
            self.fixture(site)
            (site / 'en/index.html').write_text('<section id="contact"><a href="tel:+441234567899">Other</a></section>')
            with self.assertRaisesRegex(ValueError, 'UA/EN'):
                generate_mcp_data(site, REVISION)

    def test_sources_cannot_escape_final_artifact_through_symlinks(self):
        for relative in ('.nojekyll', 'project-catalog.json', 'index.html',
                         'en/index.html', API_CATALOG_PATH):
            with self.subTest(relative=relative), TemporaryDirectory() as directory:
                root = Path(directory)
                site = root / 'artifact'
                site.mkdir()
                self.fixture(site)
                source = site / relative
                outside = root / 'outside'
                outside.write_bytes(source.read_bytes())
                source.unlink()
                source.symlink_to(outside)
                before = self.snapshot(site)
                with self.assertRaisesRegex(ValueError, 'escapes the final artifact'):
                    generate_mcp_data(site, REVISION)
                self.assertEqual(before, self.snapshot(site))

    def test_missing_artifact_revision_or_source_schema_fail_closed(self):
        with TemporaryDirectory() as directory:
            site = Path(directory)
            with self.assertRaises(ValueError):
                generate_mcp_data(site, REVISION)
            self.fixture(site)
            for revision in ('', 'a' * 7, 'A' * 40, 'z' * 40, None):
                with self.subTest(revision=revision), self.assertRaises(ValueError):
                    generate_mcp_data(site, revision)
            catalog = json.loads((site / 'project-catalog.json').read_text())
            catalog['projects'][0]['private'] = 'must fail'
            (site / 'project-catalog.json').write_text(json.dumps(catalog))
            with self.assertRaises(ValueError):
                generate_mcp_data(site, REVISION)
            (site / 'project-catalog.json').unlink()
            with self.assertRaises(FileNotFoundError):
                generate_mcp_data(site, REVISION)


if __name__ == '__main__':
    unittest.main()
