"""Publish a real browsing skill through current ARD and Lighthouse's legacy path."""
import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from agent_catalog import Document


ORIGIN = 'https://piskor.com.ua'
SKILL_PATH = 'agent-skills/piskor-portfolio/SKILL.md'
MANIFEST_PATHS = ('.well-known/ard.json', '.well-known/ai-catalog.json')


def validate_trial_token(token, now=None):
    """Check public token metadata; Chrome alone verifies Google's signature."""
    try:
        raw = base64.b64decode(token, validate=True)
        # Version byte, 64-byte signature, 4-byte payload length, JSON payload.
        if len(raw) < 70 or raw[0] not in (2, 3):
            raise ValueError('Unsupported token format')
        size = int.from_bytes(raw[65:69], 'big')
        if len(raw[69:]) != size:
            raise ValueError('Invalid token length')
        data = json.loads(raw[69:])
        if (data.get('origin') != ORIGIN + ':443' or data.get('feature') != 'WebMCP'
                or data.get('isThirdParty', False) or data.get('isSubdomain', False)):
            raise ValueError('Use a first-party WebMCP token for https://piskor.com.ua:443 only')
        current = (now or datetime.now(timezone.utc)).timestamp()
        if not isinstance(data.get('expiry'), int) or data['expiry'] <= current:
            raise ValueError('WebMCP token expired; renew it or remove it from config')
        return data
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError('Invalid WebMCP Origin Trial token: ' + str(error)) from error


def generate_agent_discovery(output):
    output = Path(output)
    skill = output / SKILL_PATH
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(Path('agent-resources/piskor-portfolio/SKILL.md').read_text())
    # specVersion is retained for Lighthouse 13.5; current ARD ignores transport fields.
    manifest = {
        'specVersion': '1.0',
        'entries': [{
            'identifier': 'urn:air:piskor.com.ua:skills:piskor-portfolio',
            'displayName': 'PISKOR portfolio browsing',
            'type': 'text/markdown; profile="urn:air:agent-skills"',
            'url': ORIGIN + '/' + SKILL_PATH,
            'description': 'Read-only guidance for finding bilingual PISKOR cases, checking published project facts and section links, and retrieving public studio contacts.',
            'capabilities': ['search_projects', 'get_project_details', 'get_contact_options'],
            'representativeQueries': [
                'Знайди проєкти PISKOR за роком і покажи підтверджені рішення.',
                'Find PISKOR interior projects and read their published scope in English.',
                'Where can I find public contact links for PISKOR Architect?'
            ]
        }]
    }
    content = json.dumps(manifest, ensure_ascii=False, separators=(',', ':')) + '\n'
    for relative in MANIFEST_PATHS:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    tokens = set()
    for page in output.rglob('*.html'):
        root = Document(page.read_text()).root
        for meta in root.find(lambda n: n.tag == 'meta' and n.attrs.get('http-equiv', '').lower() == 'origin-trial'):
            tokens.add(meta.attrs['content'])
    for token in tokens:
        validate_trial_token(token)
    print(f'Agent discovery: current/legacy manifests, public browsing skill, {len(tokens)} configured Origin Trial token(s)')
