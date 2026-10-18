import base64
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_discovery import (generate_agent_discovery, validate_trial_token, skill_metadata,
                             SKILL_PATH, SKILLS_INDEX_PATH, SKILL_INDEX_SCHEMA, MANIFEST_PATHS)


class AgentDiscoveryTest(unittest.TestCase):
    def token(self, **overrides):
        payload = {'origin': 'https://piskor.com.ua:443', 'feature': 'WebMCP', 'expiry': 1900000000}
        payload.update(overrides)
        content = json.dumps(payload).encode()
        # Synthetic metadata fixture, not a signed Chrome token.
        return base64.b64encode(bytes([3]) + bytes(64) + len(content).to_bytes(4, 'big') + content).decode()

    def test_token_scope_and_expiry(self):
        now = datetime(2026, 10, 18, tzinfo=timezone.utc)
        self.assertEqual(validate_trial_token(self.token(), now)['feature'], 'WebMCP')
        for changes in ({'origin': 'https://example.com:443'}, {'feature': 'Other'},
                        {'expiry': 1}, {'isThirdParty': True}, {'isSubdomain': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_trial_token(self.token(**changes), now)
        with self.assertRaises(ValueError):
            validate_trial_token('not-a-token', now)

    def test_manifest_references_real_resource_and_rejects_expired_html_token(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            (output / 'index.html').write_text('<html><head></head></html>')
            generate_agent_discovery(output)
            self.assertEqual((output / '.well-known/ard.json').read_bytes(),
                             (output / '.well-known/ai-catalog.json').read_bytes())
            self.assertTrue((output / SKILL_PATH).is_file())
            self.assertFalse((output / 'project-catalog.json').exists())  # No invented data.
            (output / 'index.html').write_text('<meta http-equiv="origin-trial" content="' + self.token(expiry=1) + '">')
            with self.assertRaisesRegex(ValueError, 'expired'):
                generate_agent_discovery(output)

    def test_skill_index_hashes_published_bytes_and_retains_legacy_deterministically(self):
        source = Path('agent-resources/piskor-portfolio/SKILL.md')
        before = source.read_bytes()
        with TemporaryDirectory() as directory:
            output = Path(directory)
            generate_agent_discovery(output)
            index = json.loads((output / SKILLS_INDEX_PATH).read_text())
            self.assertEqual(index['$schema'], SKILL_INDEX_SCHEMA)
            self.assertEqual(len(index['skills']), 1)
            entry = index['skills'][0]
            self.assertEqual(entry['type'], 'skill-md')
            self.assertEqual(entry['url'], '/' + SKILL_PATH)
            published = (output / SKILL_PATH).read_bytes()
            self.assertEqual(published, before)
            self.assertEqual(entry['digest'], 'sha256:' + hashlib.sha256(published).hexdigest())
            metadata = skill_metadata(published.decode())
            self.assertEqual({key: entry[key] for key in metadata}, metadata)
            snapshots = {path: (output / path).read_bytes() for path in (*MANIFEST_PATHS, SKILL_PATH)}
            generate_agent_discovery(output)
            self.assertEqual(snapshots, {path: (output / path).read_bytes() for path in snapshots})
            self.assertFalse((output / '.well-known/skills/index.json').exists())
            self.assertFalse((output / 'auth.md').exists())
            self.assertEqual(source.read_bytes(), before)

    def test_skill_metadata_rejects_unsupported_or_invalid_frontmatter(self):
        content = Path('agent-resources/piskor-portfolio/SKILL.md').read_text()
        for invalid in [content.replace('name: piskor-portfolio', 'name: other'),
                        content.replace('name: piskor-portfolio', 'name: piskor--portfolio'),
                        content.replace('name: piskor-portfolio', 'name: Piskor'),
                        content.replace('name: piskor-portfolio', 'name: piskor-portfolio\nname: duplicate'),
                        content.replace('description: Find', 'description: "Find'),
                        content.replace('description: Find', 'description: |\n  Find'),
                        'no frontmatter']:
            with self.subTest(invalid=invalid[:80]), self.assertRaises(ValueError):
                skill_metadata(invalid)


if __name__ == '__main__':
    unittest.main()
