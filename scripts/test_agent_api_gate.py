import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_api import API_CATALOG_PATH, OPENAPI_PATH, generate_agent_api
from agent_discovery import generate_agent_discovery, ARD_PATHS, SKILL_PATH
from check_agent_api import inspect_site, verify_live
import test_agent_api


class AgentApiGateTests(unittest.TestCase):
    def fixture(self, site):
        test_agent_api.AgentApiTests().make_catalog(site)
        generate_agent_api(site)
        (site / 'index.html').write_text('<html><head></head><body></body></html>')
        generate_agent_discovery(site)
        return site

    def test_current_html_is_the_source_and_counts_are_dynamic(self):
        with TemporaryDirectory() as directory:
            site = self.fixture(Path(directory))
            result = inspect_site(site)
            self.assertEqual((result['projects'], result['language_records']), (1, 2))
            self.assertEqual(result['section_links'], 2)
            catalog = site / 'project-catalog.json'
            data = json.loads(catalog.read_text())
            data['projects'][0]['label'] = 'Invented installed systems'
            catalog.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'current public'):
                inspect_site(site)

    def test_stale_schema_link_skill_and_legacy_manifest_fail(self):
        for target, mutation, expected in [
            (OPENAPI_PATH, lambda s: s.replace('"openapi":"3.1.0"', '"openapi":"3.1.0"').replace('"version":{"type":"integer","const":1}', '"version":{"type":"integer","const":2}'), 'schema drift'),
            (API_CATALOG_PATH, lambda s: s.replace('/agent-api/openapi.json', '/missing.json'), 'documentation link'),
            (SKILL_PATH, lambda s: s + '\nUnexpected changed bytes.\n', 'digest drift'),
            (ARD_PATHS[-1], lambda s: s + ' ', 'legacy bytes'),
        ]:
            with self.subTest(target=target), TemporaryDirectory() as directory:
                site = self.fixture(Path(directory))
                path = site / target
                before = path.read_text()
                changed = mutation(before)
                self.assertNotEqual(changed, before)
                path.write_text(changed)
                with self.assertRaisesRegex(ValueError, expected):
                    inspect_site(site)

    def test_origin_trial_renewal_warning_expiry_and_missing_tag(self):
        now = datetime(2026, 10, 19, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            site = self.fixture(Path(directory))
            def page(expiry):
                payload = json.dumps({'origin': 'https://piskor.com.ua:443', 'feature': 'WebMCP', 'expiry': int(expiry.timestamp())}).encode()
                token = base64.b64encode(bytes([3]) + bytes(64) + len(payload).to_bytes(4, 'big') + payload).decode()
                (site / 'index.html').write_text('<meta http-equiv="origin-trial" content="' + token + '"><script>registerTool</script>')
            page(now + timedelta(days=20))
            result = inspect_site(site, now)
            self.assertEqual(result['origin_trials'][0]['days_remaining'], 20)
            self.assertEqual(len(result['warnings']), 1)
            page(now)
            with self.assertRaisesRegex(ValueError, 'expired'):
                inspect_site(site, now)
            (site / 'index.html').write_text('<script>registerTool</script>')
            with self.assertRaisesRegex(ValueError, 'lacks'):
                inspect_site(site, now)

    def test_live_failure_is_archived_without_retry_or_redirect(self):
        with TemporaryDirectory() as directory:
            site = Path(directory) / 'site'
            site.mkdir()
            self.fixture(site)
            # Include Poppy among the normal generated resources in this fixture.
            (site / '.well-known/poppy.json').write_text('{"web":{}}\n')
            calls = []
            revision = 'a' * 40
            publication = {'/agent-api/mcp.md': {'body': 'Public MCP\n', 'contentType': 'text/markdown; charset=utf-8'}}
            def fetch(url, method, accepts, timeout):
                path = url.removeprefix('https://piskor.com.ua')
                calls.append((path, method))
                body = (publication[path]['body'].encode() if path in publication else (site / path.lstrip('/')).read_bytes()) if method == 'GET' else b''
                if path == '/project-catalog.json' and method == 'GET':
                    body = b'{"stale":true}'
                return {'status': 200, 'headers': [('Content-Type', accepts[0]), ('Content-Signal', 'ai-input=yes, ai-train=no, search=yes'), ('X-Piskor-MCP-Version', revision), ('Cache-Control', 'no-store')], 'body': body}
            out = Path(directory) / 'live'
            result = verify_live(site, revision, out, publication, fetch=fetch)
            self.assertEqual(result['passed'], result['total'] - 1)
            self.assertEqual(len(calls), len(set(calls)))
            failures = [x for x in result['rows'] if not x['passed']]
            self.assertEqual(failures[0]['issues'], ['artifact-byte-parity-or-head-body'])
            self.assertEqual((out / failures[0]['body_file']).read_bytes(), b'{"stale":true}')
            self.assertEqual(json.loads((out / 'summary.json').read_text())['passed'], result['passed'])


if __name__ == '__main__':
    unittest.main()
