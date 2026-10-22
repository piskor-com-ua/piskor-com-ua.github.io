"""Build a self-contained Worker from the exact generated Pages Markdown artifact.

No source HTML modifications, network, credentials, logs, tokens or deployment.
"""
import argparse
import base64
import brotli
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from mcp_discovery import generate_mcp_data, CONTRACT_PATH

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / 'cloudflare/markdown-worker.mjs'
MCP_HANDLER = ROOT / 'cloudflare/mcp-server.mjs'
MCP_DISCOVERY = ROOT / 'scripts/mcp_discovery.py'
MCP_IMPORT = b"import {handleMcp} from './mcp-server.mjs';\n"
MAX_BUNDLE_BYTES = 2 * 1024 * 1024  # Conservative local budget, not Cloudflare's64MiB limit.
HTML_ROUTE = '/en/portfolio/2022/zabava-restaurant-sambir/'
# Local guard for the measured Zabava payload/model; not a production timing
# guarantee. Raising it requires renewed performance verification.
MAX_HTML_BROTLI_BYTES = 43_200


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def html_representation(site, pages, revision):
    """Freeze final canonical bytes with a 43,200-byte Brotli local guard.

    The guard bounds this page's measured delivery model, not production timing.
    """
    from html.parser import HTMLParser

    if HTML_ROUTE not in pages:
        return {}
    relative = HTML_ROUTE.lstrip('/') + 'index.html'
    path = (site / relative).resolve()
    if not path.is_relative_to(site) or not path.is_file():
        raise ValueError('Missing/escaping precompressed HTML artifact')
    body = path.read_bytes()

    class Metadata(HTMLParser):
        def __init__(self):
            super().__init__()
            self.languages, self.canonicals, self.robots = [], [], []
            self.redirect = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'html':
                self.languages.append(attrs.get('lang'))
            if tag == 'link' and attrs.get('rel') == 'canonical':
                self.canonicals.append(attrs.get('href'))
            if tag == 'meta' and attrs.get('name', '').lower() == 'robots':
                self.robots.append({part.strip().lower() for part in attrs.get('content', '').split(',')})
            if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh':
                self.redirect = True

    metadata = Metadata()
    metadata.feed(body.decode('utf-8'))
    if (metadata.languages != ['en'] or metadata.canonicals != ['https://piskor.com.ua' + HTML_ROUTE]
            or metadata.robots != [{'index', 'follow', 'max-image-preview:large'}] or metadata.redirect):
        raise ValueError('Precompressed HTML must be the indexable canonical English page')
    encoded = brotli.compress(body, quality=11, mode=brotli.MODE_TEXT)
    if len(encoded) > MAX_HTML_BROTLI_BYTES:
        raise ValueError('Precompressed Zabava HTML exceeds the 43,200-byte local Brotli budget; '
                         'renew performance verification before changing this guard')
    if brotli.decompress(encoded) != body:
        raise ValueError('Precompressed HTML bytes must round-trip exactly')
    return {HTML_ROUTE: {'bodyBase64': base64.b64encode(encoded).decode('ascii'),
                        'encoding': 'br', 'quality': 11, 'language': 'en',
                        'bytes': len(body), 'sha256': sha(body),
                        'encodedBytes': len(encoded), 'encodedSha256': sha(encoded),
                        'sourcePath': relative, 'revision': revision}}


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
        if route == HTML_ROUTE and language != 'en':
            raise ValueError('Precompressed route must use the English inventory entry')
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
    mcp = generate_mcp_data(site, revision)
    html = html_representation(site, pages, revision)
    data = {'revision': revision, 'pages': pages, 'documents': documents, 'mcp': mcp, 'html': html}
    handler, mcp_handler = HANDLER.read_bytes(), MCP_HANDLER.read_bytes()
    # Exact, checked composition keeps the deployed module self-contained without a
    # bundler or runtime dependency. Fail closed if either module gains an import.
    if handler.count(MCP_IMPORT) != 1:
        raise ValueError('Expected exactly one MCP handler import')
    composed_handler = handler.replace(MCP_IMPORT, b'', 1)
    for source in (composed_handler, mcp_handler):
        if re.search(rb'^\s*import\b|\bimport\s*\(', source, re.MULTILINE):
            raise ValueError('Worker modules must not introduce runtime imports')
    bundle = b'const PUBLIC_PAGE_DATA=' + canonical(data) + b';\n' + mcp_handler + b'\n' + composed_handler
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise ValueError('Worker exceeds conservative2MiB local budget; review required')
    source_paths = {'markdown_handler': HANDLER, 'mcp_handler': MCP_HANDLER,
                    'mcp_discovery': MCP_DISCOVERY, 'mcp_contract': CONTRACT_PATH,
                    'worker_builder': Path(__file__).resolve(),
                    'mcp_design_contract': ROOT / 'docs/public-http-mcp.md',
                    'wrangler_config': ROOT / 'cloudflare/wrangler.jsonc'}
    source_hashes = {name: sha(path.read_bytes()) for name, path in source_paths.items()}
    artifact_hashes = {name: sha((site / name).read_bytes()) for name in
                       ('project-catalog.json', 'index.html', '.well-known/api-catalog')}
    if (site / 'en/index.html').is_file():
        artifact_hashes['en/index.html'] = sha((site / 'en/index.html').read_bytes())
    for representation in html.values():
        artifact_hashes[representation['sourcePath']] = representation['sha256']
    manifest = {'version': 1, 'revision': revision, 'routes_sha256': sha(route_file.read_bytes()),
                'source_sha256': source_hashes, 'artifact_source_sha256': artifact_hashes,
                'mcp_data_sha256': sha(canonical(mcp)),
                'mcp_server_version': mcp['contract']['serverInfo']['version'] + '+' + revision,
                'mcp_protocol_versions': mcp['contract']['protocolVersions'],
                'mcp_project_records': len(mcp['projects']),
                'mcp_publications': {path: {'sha256': sha(item['body'].encode('utf-8')),
                                          'bytes': len(item['body'].encode('utf-8')),
                                          'content_type': item['contentType']}
                                     for path, item in mcp['publications'].items()},
                'handler_sha256': sha(handler), 'mcp_handler_sha256': sha(mcp_handler), 'bundle_sha256': sha(bundle),
                'bundle_bytes': len(bundle), 'bundle_gzip9_bytes': len(gzip.compress(bundle, mtime=0)),
                'source_page_states': len(inventory['pages']), 'routing_keys_with_uk404_alias': len(pages),
                'markdown_files': files, 'markdown_total_bytes': sum(x['bytes'] for x in files.values()),
                'html_representations': {route: {key: value for key, value in item.items() if key != 'bodyBase64'}
                                         for route, item in html.items()},
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
