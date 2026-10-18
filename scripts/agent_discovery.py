"""Publish a real browsing skill through current ARD and Lighthouse's legacy path."""
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re

from agent_catalog import Document


ORIGIN = 'https://piskor.com.ua'
SKILL_PATH = 'agent-skills/piskor-portfolio/SKILL.md'
ARD_PATHS = ('.well-known/ard.json', '.well-known/ai-catalog.json')
SKILLS_INDEX_PATH = '.well-known/agent-skills/index.json'
SKILL_INDEX_SCHEMA = 'https://schemas.agentskills.io/discovery/0.2.0/schema.json'
MANIFEST_PATHS = (*ARD_PATHS, SKILLS_INDEX_PATH)


def skill_metadata(content):
    """Read this publisher's single-line plain YAML metadata, failing closed.

    Complex YAML scalars are deliberately unsupported rather than publishing
    an index description that differs from what a skill client would read.
    """
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', content, re.S)
    if not match:
        raise ValueError('Skill requires YAML frontmatter')
    metadata = {}
    for key in ('name', 'description'):
        fields = re.findall(r'^' + key + r':[ \t]+([^\r\n]+)$', match[1], re.M)
        if len(fields) != 1:
            raise ValueError('Skill requires one plain single-line ' + key)
        value = fields[0].strip()
        if not value or value[0] in "'\"|>![{*&" or ' #' in value or ': ' in value:
            raise ValueError('Unsupported YAML scalar for skill ' + key)
        metadata[key] = value
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', metadata['name']) or len(metadata['name']) > 64:
        raise ValueError('Invalid Agent Skills name')
    if metadata['name'] != Path(SKILL_PATH).parent.name or len(metadata['description']) > 1024:
        raise ValueError('Skill metadata does not match its path or description limit')
    return metadata


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
    content = Path('agent-resources/piskor-portfolio/SKILL.md').read_bytes()
    metadata = skill_metadata(content.decode('utf-8'))
    skill.write_bytes(content)
    skill_index = {
        '$schema': SKILL_INDEX_SCHEMA,
        'skills': [{**metadata, 'type': 'skill-md', 'url': '/' + SKILL_PATH,
                    'digest': 'sha256:' + hashlib.sha256(content).hexdigest()}],
    }
    index = output / SKILLS_INDEX_PATH
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps(skill_index, ensure_ascii=False, separators=(',', ':')) + '\n')
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
    for relative in ARD_PATHS:
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
    print(f'Agent discovery: current/legacy ARD, draft Agent Skills 0.2.0 index, public browsing skill, {len(tokens)} configured Origin Trial token(s)')
