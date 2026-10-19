"""Build a self-contained Worker from the exact generated Pages Markdown artifact.

No source HTML modifications, network, credentials, logs, tokens or deployment.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

HANDLER = Path(__file__).resolve().parents[1] / 'cloudflare/markdown-worker.mjs'
MAX_BUNDLE_BYTES = 2 * 1024 * 1024  # Conservative local budget, not Cloudflare's64MiB limit.


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def build(site, out, revision):
    site, out = Path(site).resolve(), Path(out).resolve()
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Revision must be the exact40-character Git commit SHA')
    if not (site / '.nojekyll').is_file() or not (site / 'agent-markdown/routes.json').is_file():
        raise ValueError('Only a generated Pages artifact may supply Worker content')
    if out == site or out.is_relative_to(site):
        raise ValueError('Worker output must remain outside the public Pages artifact')
    if out.exists():
        raise ValueError('New output directory required; never overwrite a release bundle')
    route_file = site / 'agent-markdown/routes.json'
    if not route_file.resolve().is_relative_to(site) or (site / '.nojekyll').is_symlink():
        raise ValueError('Artifact marker/inventory must remain inside artifact')
    inventory = json.loads(route_file.read_text())
    if inventory.get('version') != 1 or not isinstance(inventory.get('pages'), list):
        raise ValueError('Unsupported generated route inventory')
    pages, documents, files = {}, {}, {}
    expected_html_routes = {'/' + p.relative_to(site).as_posix()[:-10] if p.name == 'index.html'
                            else '/' + p.relative_to(site).as_posix() for p in site.rglob('*.html')}
    for row in inventory['pages']:
        route, markdown, language = row['url'], row['markdown'], row['language']
        parsed = urlsplit(route)
        if (parsed.scheme or parsed.netloc or parsed.fragment or '%' in route or
                not route.startswith('/') or route.startswith('//') or
                (parsed.query and route != '/404.html?lang=en')):
            raise ValueError('Unsupported authored route: ' + route)
        if route in pages or language not in ('uk', 'en'):
            raise ValueError('Duplicate route or unsupported language')
        html = parsed.path.lstrip('/') + ('index.html' if parsed.path.endswith('/') else '')
        expected_md = '/agent-markdown/' + str(Path(html).with_suffix('.md'))
        if route == '/404.html?lang=en':
            expected_md = '/agent-markdown/404-en.md'
        if markdown != expected_md:
            raise ValueError('Markdown path does not match authored route')
        html_path = (site / html).resolve()
        path = (site / markdown.lstrip('/')).resolve()
        if not html_path.is_relative_to(site) or not html_path.is_file() or not path.is_relative_to(site) or not path.is_file():
            raise ValueError('Missing/escaping artifact resource')
        if markdown in documents:
            raise ValueError('Duplicate Markdown resource')
        body = path.read_bytes()
        text = body.decode('utf-8')
        if text.encode('utf-8') != body:
            raise ValueError('Markdown UTF8 bytes must round-trip exactly')
        pages[route] = {'markdown': markdown}
        documents[markdown] = {'body': text, 'bytes': len(body), 'sha256': sha(body), 'language': language}
        files[markdown] = {'bytes': len(body), 'sha256': sha(body)}
    if not pages or set(pages) - {'/404.html?lang=en'} != expected_html_routes:
        raise ValueError('Inventory must cover every generated HTML document exactly')
    if '/404.html' in pages:
        pages['/404.html?lang=uk'] = pages['/404.html'].copy()
    data = {'revision': revision, 'pages': pages, 'documents': documents}
    handler = HANDLER.read_bytes()
    bundle = b'const PUBLIC_PAGE_DATA=' + canonical(data) + b';\n' + handler
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise ValueError('Worker exceeds conservative2MiB local budget; review required')
    manifest = {'version': 1, 'revision': revision, 'routes_sha256': sha(route_file.read_bytes()),
                'handler_sha256': sha(handler), 'bundle_sha256': sha(bundle),
                'bundle_bytes': len(bundle), 'bundle_gzip9_bytes': len(gzip.compress(bundle, mtime=0)),
                'source_page_states': len(inventory['pages']), 'routing_keys_with_uk404_alias': len(pages),
                'markdown_files': files, 'markdown_total_bytes': sum(x['bytes'] for x in files.values()),
                'local_budget_bytes': MAX_BUNDLE_BYTES, 'token_headers': 'omitted-no-model-independent-token-count',
                'deployment': 'Not deployed; Pages artifact unchanged; no logging configuration is enabled by this module'}
    out.mkdir(parents=True)
    (out / 'worker.mjs').write_bytes(bundle)
    (out / 'manifest.json').write_bytes(canonical(manifest) + b'\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.site, args.out, args.revision), ensure_ascii=False))


if __name__ == '__main__':
    main()
