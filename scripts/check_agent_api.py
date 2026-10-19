"""Artifact and optional production release gate for the real public agent API.

No credentials, redirects, retries or mutations. Live observations, including
failures, are saved in a new directory; this is not a PSI measurement.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from agent_api import (API_CATALOG_PATH, API_DOC_PATH, OPENAPI_PATH, ORIGIN,
                       catalog_schemas, _validate_shape)
from agent_catalog import Document, read_agent_projects
from agent_content import POPPY_PATH
from agent_discovery import (ARD_PATHS, SKILL_PATH, SKILLS_INDEX_PATH,
                             skill_metadata, validate_trial_token)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def inspect_site(site, now=None):
    site = Path(site).resolve()
    if not (site / '.nojekyll').is_file():
        raise ValueError('Use a generated Pages artifact')
    catalog = json.loads((site / 'project-catalog.json').read_bytes())
    specification = json.loads((site / OPENAPI_PATH).read_bytes())
    schemas = catalog_schemas()
    _validate_shape(catalog, schemas['ProjectCatalog'], schemas)
    if specification['components']['schemas'] != schemas:
        raise ValueError('OpenAPI schema drift')
    if specification['servers'] != [{'url': ORIGIN}] or specification['security'] != []:
        raise ValueError('Unexpected API origin or authorization claim')
    if set(specification['paths']) != {'/project-catalog.json'} or set(specification['paths']['/project-catalog.json']) != {'get'}:
        raise ValueError('Document only the implemented catalog GET')
    projects = catalog['projects']
    if not projects or projects != read_agent_projects(site):
        raise ValueError('Catalog does not match current public cards and case facts')
    identities = [(p['id'], p['language']) for p in projects]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate project/language identity')
    ids = {p['id'] for p in projects}
    if set(identities) != {(id_, lang) for id_ in ids for lang in ('uk', 'en')}:
        raise ValueError('Every project requires both published languages')
    for project in projects:
        page = site / project['url'].lstrip('/') / 'index.html'
        root = Document(page.read_text()).root
        anchors = {n.attrs['id'] for n in root.find(lambda n: 'id' in n.attrs)}
        for section in project['sections']:
            parsed = urlsplit(section['url'])
            if parsed.path != project['url'] or parsed.fragment not in anchors:
                raise ValueError('Broken case section URL: ' + section['url'])
    listing = json.loads((site / API_CATALOG_PATH).read_bytes())['linkset']
    by_anchor = {item['anchor']: item for item in listing}
    endpoint = ORIGIN + '/project-catalog.json'
    if by_anchor[ORIGIN + '/' + API_CATALOG_PATH]['item'] != [{'href': endpoint, 'type': 'application/json'}]:
        raise ValueError('API catalog listing drift')
    item = by_anchor[endpoint]
    for relation, path, mime in [('service-desc', OPENAPI_PATH, 'application/json'),
                                  ('service-doc', API_DOC_PATH, 'text/markdown')]:
        if item[relation] != [{'href': ORIGIN + '/' + path, 'type': mime}]:
            raise ValueError('API documentation link drift')
    skills = json.loads((site / SKILLS_INDEX_PATH).read_bytes())['skills']
    for entry in skills:
        if entry['url'] != '/' + SKILL_PATH or entry['type'] != 'skill-md':
            raise ValueError('Unexpected browsing skill resource')
        body = (site / SKILL_PATH).read_bytes()
        if entry['digest'] != 'sha256:' + sha(body):
            raise ValueError('Skill digest drift')
        if any(entry[key] != value for key, value in skill_metadata(body.decode()).items()):
            raise ValueError('Skill frontmatter drift')
    if not skills or len(skills) != len({x['name'] for x in skills}):
        raise ValueError('Missing or duplicate skills')
    manifests = [(site / path).read_bytes() for path in ARD_PATHS]
    if len(set(manifests)) != 1:
        raise ValueError('ARD current/legacy bytes differ')
    for entry in json.loads(manifests[0])['entries']:
        if entry['url'] != ORIGIN + '/' + SKILL_PATH:
            raise ValueError('ARD references a different skill')
        if set(entry['capabilities']) != {'search_projects', 'get_project_details', 'get_contact_options'}:
            raise ValueError('ARD capabilities drift')
    current = now or datetime.now(timezone.utc)
    tokens = set()
    for page in site.rglob('*.html'):
        text = page.read_text()
        root = Document(text).root
        metas = root.find(lambda n: n.tag == 'meta' and n.attrs.get('http-equiv', '').lower() == 'origin-trial')
        if ('registerTool' in text or 'agent-tools' in text) and not metas:
            raise ValueError('WebMCP page lacks the configured Origin Trial: ' + str(page))
        tokens.update(n.attrs['content'] for n in metas)
    trials = []
    for token in tokens:
        metadata = validate_trial_token(token, current)
        trials.append({'expiry': datetime.fromtimestamp(metadata['expiry'], timezone.utc).isoformat(),
                       'days_remaining': (metadata['expiry'] - current.timestamp()) / 86400,
                       'verification': 'metadata only; native browser checks signature and activation'})
    return {'projects': len(ids), 'language_records': len(projects), 'languages': ['uk', 'en'],
            'section_links': sum(len(p['sections']) for p in projects), 'skills': len(skills),
            'origin_trials': trials, 'warnings': ['Renew WebMCP Origin Trial within 30 days']
            if any(t['days_remaining'] <= 30 for t in trials) else []}


def verify_live(site, revision, out, publications, fetch=None, origin=ORIGIN):
    if origin != ORIGIN or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Live gate requires the production origin and exact commit SHA')
    spec = importlib.util.spec_from_file_location('agent_delivery', Path(__file__).with_name('check-agent-delivery.py'))
    delivery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(delivery)
    fetch = fetch or delivery.request
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    resources = {'/project-catalog.json': 'application/json', '/' + OPENAPI_PATH: 'application/json',
                 '/' + API_DOC_PATH: 'text/markdown', '/' + SKILLS_INDEX_PATH: 'application/json',
                 '/' + SKILL_PATH: 'text/markdown', '/' + POPPY_PATH: 'application/json',
                 **{'/' + p: 'application/ard+json' for p in ARD_PATHS}}
    expected = {path: (Path(site) / path.lstrip('/')).read_bytes() for path in resources}
    for path, document in publications.items():
        resources[path] = document['contentType'].split(';')[0]
        expected[path] = document['body'].encode()
    rows = []
    for path, mime in resources.items():
        for method in ('GET', 'HEAD'):
            row = {'path': path, 'method': method, 'issues': []}
            try:
                response = fetch(origin + path, method, [mime], 25)
                body = response.pop('body')
                headers = delivery.headers_map(response['headers'])
                row['response'] = response
                row['body_sha256'] = sha(body)
                row['expected_sha256'] = sha(expected[path])
                body_file = f'{len(rows):02d}.body'
                (out / body_file).write_bytes(body)
                row['body_file'] = body_file
                if response['status'] != 200:
                    row['issues'].append('status')
                types = [v for k, v in response['headers'] if k.lower() == 'content-type']
                if len(types) != 1 or types[0].split(';')[0].lower().strip() != mime:
                    row['issues'].append('content-type')
                if body != (expected[path] if method == 'GET' else b''):
                    row['issues'].append('artifact-byte-parity-or-head-body')
                if not {'noindex', 'nofollow'} <= {x.strip() for x in headers.get('x-robots-tag', '').split(',')}:
                    row['issues'].append('robots-policy')
                signals = {part.strip().lower() for part in headers.get('content-signal', '').split(',')}
                if not {'ai-input=yes', 'ai-train=no', 'search=yes'} <= signals:
                    row['issues'].append('content-signals-policy')
                if path in publications:
                    if headers.get('x-piskor-mcp-version') != revision:
                        row['issues'].append('mcp-revision')
                    if 'no-store' not in headers.get('cache-control', '').lower() or headers.get('cf-cache-status', '').upper() == 'HIT':
                        row['issues'].append('runtime-publication-cache')
            except Exception as error:
                row['issues'].append(str(error))
            row['passed'] = not row['issues']
            rows.append(row)
    result = {'at': datetime.now(timezone.utc).isoformat(), 'revision': revision,
              'passed': sum(r['passed'] for r in rows), 'total': len(rows), 'rows': rows}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, type=Path)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--live', action='store_true', help='GET/HEAD exact production resources once; no retries')
    args = parser.parse_args()
    summary = inspect_site(args.site)
    from mcp_discovery import generate_mcp_data
    mcp = generate_mcp_data(args.site, args.revision)
    if args.live:
        result = verify_live(args.site, args.revision, args.out, mcp['publications'])
        print(json.dumps({'passed': result['passed'], 'total': result['total'], 'site': summary}))
        if result['passed'] != result['total']:
            raise SystemExit(1)
    else:
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary))
    for warning in summary['warnings']:
        print('::warning title=Origin Trial renewal::' + warning)


if __name__ == '__main__':
    main()
