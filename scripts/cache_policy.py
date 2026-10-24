"""Audit final resource versions and prepare release-scoped CDN invalidation.

No network, credentials, Cloudflare writes or modifications of the Pages artifact.
"""
import argparse
from collections import defaultdict
import hashlib
from html import unescape
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

from agent_catalog import Document
from fingerprint_resources import VERSION
from optimize_assets import TEXT_SUFFIXES

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'cloudflare/cache-policy.json'
STABLE_DOCUMENT_SUFFIXES = {'.html', '.css', '.js', '.json', '.md', '.txt', '.xml'}


def digest(body):
    return hashlib.sha256(body).hexdigest()


def public_urls(relative):
    direct = '/' + relative
    return [direct[:-10], direct] if relative.endswith('/index.html') else ['/', '/index.html'] if relative == 'index.html' else [direct]


def inventory(site, revision='local'):
    site = Path(site).resolve()
    if not (site / '.nojekyll').is_file():
        raise ValueError('Use a final generated Pages artifact')
    policy = json.loads(POLICY.read_text())
    if policy['edge_min_ttl'] < 2678400 or not policy['public_markdown_edge_cache'] or policy['mcp_post_cache']:
        raise ValueError('Monthly public edge cache and uncached MCP POST are mandatory')
    origin = policy['origin']
    files, texts, versions, issues = {}, {}, {}, []
    for path in sorted(site.rglob('*')):
        if not path.is_file():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(site):
            raise ValueError('Unsafe artifact resource')
        relative = path.relative_to(site).as_posix()
        body = path.read_bytes()
        files[relative] = {'sha256': digest(body), 'bytes': len(body), 'urls': public_urls(relative), 'dependencies': []}
        if path.suffix in TEXT_SUFFIXES | {'.md'}:
            texts[relative] = body.decode('utf-8')

    def reference(owner, value, require_version=True):
        value = unescape(value)
        url = urlsplit(urljoin(origin + '/' + owner, value))
        if (url.scheme + '://' + url.netloc) != origin:
            return
        target = unquote(url.path).lstrip('/')
        if target not in files:
            issues.append({'owner': owner, 'url': value, 'issue': 'missing-resource'})
            return
        files[owner]['dependencies'].append(target)
        if require_version:
            values = [v for key, v in parse_qsl(url.query, keep_blank_values=True) if key == 'v']
            expected = files[target]['sha256'][:12]
            if values != [expected]:
                issues.append({'owner': owner, 'url': value, 'issue': 'incorrect-content-version', 'expected': expected})
            versions[url.path + ('?' + url.query if url.query else '')] = target

    for relative, text in texts.items():
        for match in VERSION.finditer(text):
            # Media references can be relative in CSS/JS. Their asset component
            # is rooted in the generated artifact by the existing build contract.
            reference(relative, '/' + match['asset'] + (match['query'] or ''))
        if relative.endswith('.html'):
            root = Document(text).root
            for node in root.find(lambda n: n.tag in {'script', 'link'}):
                value = node.attrs.get('src') if node.tag == 'script' else node.attrs.get('href')
                if value and Path(urlsplit(unescape(value)).path).suffix in {'.css', '.js'}:
                    reference(relative, value)
    for record in files.values():
        record['dependencies'] = sorted(set(record['dependencies']))
    if issues:
        raise ValueError('Unsafe long-cache references: ' + json.dumps(issues[:12], ensure_ascii=False))
    stable = sorted(relative for relative in files
                    if Path(relative).suffix in STABLE_DOCUMENT_SUFFIXES or relative == '.well-known/api-catalog')
    return {'version': 1, 'revision': revision, 'origin': origin,
            'policy_sha256': digest(POLICY.read_bytes()), 'edge_min_ttl': policy['edge_min_ttl'],
            'files': files, 'versioned_urls': dict(sorted(versions.items())), 'stable_documents': stable}


def purge_plan(current, previous=None):
    if previous and (previous.get('version') != 1 or previous.get('origin') != current['origin']):
        raise ValueError('Previous inventory must use the same origin and schema')
    now, old = current['files'], previous['files'] if previous else {}
    changed = {name for name in set(now) | set(old)
               if now.get(name, {}).get('sha256') != old.get(name, {}).get('sha256')}
    # Navigation links are not render dependencies. Changed document bytes are
    # already detected; don't invalidate the whole site's link graph for one case.
    reverse = defaultdict(set)
    for records in (now, old):
        for owner, record in records.items():
            for target in record['dependencies']:
                reverse[target].add(owner)
    affected = set(changed)
    pending = list(changed)
    while pending:
        for owner in reverse[pending.pop()]:
            if owner not in affected:
                affected.add(owner)
                pending.append(owner)
    policy_changed = bool(previous and previous.get('policy_sha256') != current['policy_sha256'])
    if not previous or policy_changed:
        # Initial policy rollout: explicit stable documents, not Purge Everything
        # and not thousands of unchanged, already version-cached image variants.
        affected = set(current['stable_documents'])
    urls = set()
    prefixes = set()
    for name in affected:
        for records in (now, old):
            if name in records:
                urls.update(current['origin'] + url for url in records[name]['urls'])
        if name.startswith('agent-markdown/') and name.endswith('.md'):
            prefixes.add(urlsplit(current['origin']).netloc + '/' + name)
    # These Worker-generated public documents don't equal the origin files.
    # Their bodies depend on the release revision, catalog and protocol contract.
    if changed or not previous or current['revision'] != previous.get('revision'):
        prefixes.update(urlsplit(current['origin']).netloc + path for path in
                        ('/.well-known/mcp/server-card.json', '/agent-api/mcp.md', '/.well-known/api-catalog'))
    policy = json.loads(POLICY.read_text())
    size = policy['purge_batch_size']
    ordered = sorted(urls)
    return {'mode': 'policy-change-stable-documents' if policy_changed else 'changed-and-dependent' if previous else 'bootstrap-stable-documents',
            'revision': current['revision'], 'previous_revision': previous and previous.get('revision'),
            'changed_files': sorted(changed), 'affected_files': sorted(affected),
            'url_batches': [ordered[i:i + size] for i in range(0, len(ordered), size)],
            'markdown_prefixes': sorted(prefixes), 'purge_everything': False,
            'note': 'Cache API custom keys require global prefix purge; single-URL purge is not proof of their invalidation.'}


def write_report(site, out, revision='local', previous=None):
    site, out = Path(site).resolve(), Path(out).resolve()
    if out == site or out.is_relative_to(site):
        raise ValueError('Cache reports must stay outside the public artifact')
    current = inventory(site, revision)
    plan = purge_plan(current, previous)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n')
    (out / 'purge-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    # Keep batches in one report so a later shorter plan cannot leave stale files.
    return {'files': len(current['files']), 'versioned_urls': len(current['versioned_urls']),
            'url_purge_batches': len(plan['url_batches']), 'mode': plan['mode'], 'out': str(out)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', default='_site')
    parser.add_argument('--out', default='output/cache-policy')
    parser.add_argument('--revision', default=os.environ.get('GITHUB_SHA', 'local'))
    parser.add_argument('--previous', help='Manifest from the previous actually published Pages artifact')
    args = parser.parse_args()
    previous = json.loads(Path(args.previous).read_text()) if args.previous else None
    print(json.dumps(write_report(args.site, args.out, args.revision, previous), ensure_ascii=False))


if __name__ == '__main__':
    main()
