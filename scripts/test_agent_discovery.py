import base64
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_discovery import generate_agent_discovery, validate_trial_token, SKILL_PATH


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


if __name__ == '__main__':
    unittest.main()
