#!/usr/bin/env python3
"""Verify real HTTP delivery against a saved Pages artifact (not PSI).

No credentials or mutations. Redirects are never implicit: the optional Markdown
307 allowance permits one same-origin hop to the exact advertised artifact path.
All observations, including failures, survive in a new output directory.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from email.utils import parsedate_to_datetime
import gzip
import hashlib
import http.client
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urljoin

UA = 'PISKOR-Release-Verifier/1.0 (+https://piskor.com.ua/)'
DISCOVERY = {
    ('/.well-known/ard.json', 'ard', 'application/ard+json'),
    ('/llms.txt', 'describedby', 'text/plain'),
    ('/.well-known/api-catalog', 'api-catalog', 'application/linkset+json'),
    ('/.well-known/agent-skills/index.json', 'agent-skills', 'application/json'),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def headers_map(pairs):
    result = {}
    for key, value in pairs:
        result.setdefault(key.lower(), []).append(value)
    return {key: ', '.join(values) for key, values in result.items()}


def links(value):
    result = set()
    for target, tail in re.findall(r'<([^>]+)>((?:[^<]|<(?![^>]+>))*)', value):
        params = {key.lower(): quoted or bare for key, quoted, bare in
                  re.findall(r';\s*([\w-]+)\s*=\s*(?:"([^"\n]*)"|([^;\s,]+))', tail)}
        for rel in params.get('rel', '').split():
            result.add((target, rel, params.get('type', '')))
    return result


def compare(body, expected, known=None, html=False):
    compared = body
    transformation = None
    if body != expected and html and known and body.count(known) == 1 and known not in expected:
        compared = body.replace(known, b'', 1)
        transformation = 'remove-one-exact-known-html-injection'
    return dict(raw_sha256=sha(body), compared_sha256=sha(compared),
                raw_byte_equal=body == expected, compared_byte_equal=compared == expected,
                transformation=transformation)


def policy(pairs, origin, vary=True):
    h = headers_map(pairs)
    issues = []
    signals = {}
    for part in h.get('content-signal', '').split(','):
        if '=' in part:
            key, value = part.strip().lower().split('=', 1)
            signals.setdefault(key.strip(), set()).add(value.strip())
    if any(signals.get(key) != {value} for key, value in
           [('ai-input', 'yes'), ('ai-train', 'no'), ('search', 'yes')]):
        issues.append('content-signal')
    if not {'noindex', 'nofollow'} <= {x.strip().lower() for x in h.get('x-robots-tag', '').split(',')}:
        issues.append('x-robots-tag')
    actual = {(urljoin(origin, target), rel, mime)
              for target, rel, mime in links(h.get('link', ''))}
    expected = {(origin + path, rel, mime) for path, rel, mime in DISCOVERY}
    if not expected <= actual:
        issues.append('four-discovery-links')
    if vary and not {'accept', '*'} & {x.strip().lower() for x in h.get('vary', '').split(',')}:
        issues.append('vary-accept')
    return issues


class MarkdownAlternates(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []
        self.noindex = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name', '').lower() == 'robots':
            self.noindex |= 'noindex' in {x.strip() for x in attrs.get('content', '').lower().split(',')}
        if tag == 'link' and 'alternate' in attrs.get('rel', '').split() and attrs.get('type') == 'text/markdown':
            self.targets.append(attrs.get('href'))


def html_alternates(body):
    parser = MarkdownAlternates()
    parser.feed(body.decode('utf-8'))
    return parser.targets


def request(url, method, accepts, timeout):
    parsed = urlsplit(url)
    connection = (http.client.HTTPSConnection if parsed.scheme == 'https' else
                  http.client.HTTPConnection)(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.putrequest(method, parsed.path + ('?' + parsed.query if parsed.query else ''),
                              skip_accept_encoding=True)
        connection.putheader('User-Agent', UA)
        connection.putheader('Accept-Encoding', 'gzip')
        for value in accepts:
            connection.putheader('Accept', value)
        connection.endheaders()
        response = connection.getresponse()
        body = response.read(20 * 1024 * 1024 + 1)
        if len(body) > 20 * 1024 * 1024:
            raise ValueError('Response exceeds 20MiB guard')
        pairs = response.getheaders()
        encoding = headers_map(pairs).get('content-encoding', '').lower()
        decoded = gzip.decompress(body) if body and encoding == 'gzip' else body
        if encoding not in ('', 'gzip', 'identity'):
            raise ValueError('Unsupported content encoding: ' + encoding)
        return dict(url=url, method=method, status=response.status, headers=pairs,
                    wire_sha256=sha(body), wire_bytes=len(body), body=decoded)
    finally:
        connection.close()


def verify(case, origin, expected, known=None, allow_redirects=False, timeout=20, fetch=request,
           expected_markdown_version=None):
    observations = []
    issues = []
    try:
        if expected_markdown_version is not None and (
                not isinstance(expected_markdown_version, str) or
                not re.fullmatch(r'[0-9a-f]{40}', expected_markdown_version)):
            raise ValueError('Expected Markdown version must be a complete Git SHA')
        initial_url = origin + case['route']
        response = fetch(initial_url, case['method'], case['accepts'], timeout)
        observations.append(response)
        if response['status'] == 307 and allow_redirects and (case['kind'] == 'negotiated' or
                (case['kind'] == 'true-404' and urlsplit(case['route']).path.endswith('/')
                 and not urlsplit(case['route']).query and '%' not in urlsplit(case['route']).path)):
            # A terminating307 can precede later response-header phases.
            # Preserve its headers, but apply policy only to the final resource.
            initial_headers = headers_map(response['headers'])
            cc = initial_headers.get('cache-control', '').lower()
            directives = [item.strip() for item in cc.split(',')]
            positive = any(int(match[1]) > 0 for item in directives
                           if (match := re.fullmatch(r'(?:s-maxage|max-age)\s*=\s*\"?(\d+)\"?', item)))
            expires = initial_headers.get('expires')
            if expires:
                try:
                    positive |= parsedate_to_datetime(expires) > datetime.now(timezone.utc)
                except (ValueError, TypeError):
                    issues.append('invalid-redirect-expires')
            if any(item in {'no-store', 'no-cache'} for item in directives):
                positive = False
            # An observed HIT remains evidence even if response directives forbid reuse.
            positive |= initial_headers.get('cf-cache-status', '').upper() == 'HIT'
            vary_accept = bool({'accept', '*'} & {x.strip().lower() for x in initial_headers.get('vary', '').split(',')})
            response['redirect_cache_evidence'] = dict(cache_control=cc, expires=expires,
                cf_cache_status=initial_headers.get('cf-cache-status'), cache_positive=positive, vary_accept=vary_accept)
            if positive and not vary_accept:
                issues.append('cacheable-format-redirect-without-vary-accept')
            locations = [v for k, v in response['headers'] if k.lower() == 'location']
            target = urljoin(initial_url, locations[0]) if len(locations) == 1 else ''
            query = urlsplit(initial_url).query
            markdown = case.get('markdown') or '/agent-markdown' + urlsplit(initial_url).path + 'index.md'
            advertised = origin + markdown + ('?' + query if query else '')
            if target != advertised:
                raise ValueError('307 target must be exact same-origin advertised Markdown path with original query preserved')
            response = fetch(target, case['method'], case['accepts'], timeout)
            observations.append(response)
        if response['status'] != case.get('status', 200):
            issues.append('status')
        h = headers_map(response['headers'])
        if h.get('location'):
            issues.append('unexpected-redirect-or-loop')
        types = [v for k, v in response['headers'] if k.lower() == 'content-type']
        if len(types) != 1 or ',' in types[0] or types[0].split(';')[0].strip().lower() != case['mime']:
            issues.append('content-type')
        if case.get('status', 200) == 200:
            issues += policy(response['headers'], origin)
            if case['mime'] == 'text/markdown' and expected_markdown_version:
                versions = [v for k, v in response['headers'] if k.lower() == 'x-piskor-markdown-version']
                if versions != [expected_markdown_version]:
                    issues.append('markdown-worker-version')
                if 'no-store' not in {x.strip().lower() for x in h.get('cache-control', '').split(',')}:
                    issues.append('markdown-worker-no-store')
                if h.get('cf-cache-status', '').upper() == 'HIT':
                    issues.append('markdown-worker-unexpected-hit')
        else:
            robots = MarkdownAlternates()
            robots.feed(expected.decode('utf-8'))
            if not robots.noindex:
                issues.append('404-artifact-meta-noindex')
        if case['method'] == 'HEAD' and any(item['body'] for item in observations):
            issues.append('head-body-not-empty')
        comparison = None
        if case['method'] == 'GET':
            comparison = compare(response['body'], expected, known, case['mime'] == 'text/html')
            if not comparison['compared_byte_equal']:
                issues.append('artifact-bytes')
            if case['mime'] == 'text/html':
                # Raw404 HTML remains UK even for ?lang=en; runtime locale is
                # browser evidence. Require its actual artifact alternate.
                expected_alternates = html_alternates(expected)
                actual_alternates = html_alternates(response['body'])
                if len(expected_alternates) != 1 or actual_alternates != expected_alternates:
                    issues.append('html-markdown-alternate')
        if case.get('cache_probe') and case['mime'] == 'text/markdown' and not expected_markdown_version:
            if h.get('cf-cache-status', '').upper() not in ('BYPASS', 'DYNAMIC'):
                issues.append('markdown-cloudflare-bypass-unverified')
        return dict(case=case, observations=observations, comparison=comparison,
                    issues=issues, pass_=not issues)
    except Exception as error:
        return dict(case=case, observations=observations, issues=issues + [str(error)], pass_=False)


def jobs(site):
    pages = json.loads((site / 'agent-markdown/routes.json').read_text())['pages']
    mapping = {row['url']: row['markdown'] for row in pages}
    if len(mapping) != len(pages):
        raise ValueError('Duplicate inventory URL')
    result = []
    def add(route, file, mime, accepts, kind, **extra):
        for method in ('GET', 'HEAD'):
            result.append(dict(route=route, file=file, mime=mime, accepts=accepts,
                               kind=kind, method=method, **extra))
    for row in pages:
        route, md = row['url'], row['markdown']
        if not route.startswith('/') or route.startswith('//') or not md.startswith('/agent-markdown/'):
            raise ValueError('Unsafe route/Markdown inventory URL')
        path = urlsplit(route).path
        html = (path + 'index.html' if path.endswith('/') else path).lstrip('/')
        add(route, html, 'text/html', ['text/html'], 'html')
        add(md, md.lstrip('/'), 'text/markdown', ['text/markdown'], 'direct')
        add(route, md.lstrip('/'), 'text/markdown', ['text/markdown'], 'negotiated', markdown=md)
    for route in ('/', '/en/', '/portfolio/', '/en/portfolio/'):
        path = route.lstrip('/') + 'index.html'
        for values in ([], ['*/*'], ['text/markdown;q=1'], ['text/markdown;q=0'], ['text/html,text/markdown'],
                       ['text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'],
                       ['text/markdown', 'text/markdown']):
            add(route, path, 'text/html', values, 'negative-accept')
        for query in ('utm_source=delivery-verifier', 'lang=en', 'lang=uk', 'lang=en&lang=uk', 'lang=uk&lang=en'):
            add(route + '?' + query, path, 'text/html', ['text/markdown'], 'negative-query')
    if '/404.html' in mapping:
        add('/404.html?lang=uk', '404.html', 'text/html', ['text/html'], 'html')
        add('/404.html?lang=uk', mapping['/404.html'].lstrip('/'), 'text/markdown',
            ['text/markdown'], 'negotiated', markdown=mapping['/404.html'])
        for query in ('lang=en&lang=uk', 'lang=uk&lang=en', '%6cang=en', 'lang=%65n'):
            add('/404.html?' + query, '404.html', 'text/html', ['text/markdown'], 'negative-query')
    for route in ('/piskor-delivery-verifier-missing/', '/en/piskor-delivery-verifier-missing/',
                  '/piskor-delivery-verifier-missing/?lang=en',
                  '/piskor-delivery-verifier-missing%20encoded/',
                  '/piskor-delivery-verifier-missing.html',
                  '/piskor-delivery-verifier-missing.html?lang=en'):
        add(route, '404.html', 'text/html', ['text/markdown'], 'true-404', status=404)
    sequences = []
    for route in ('/portfolio/', '/en/portfolio/'):
        for mime in ('text/markdown', 'text/html', 'text/markdown'):
            sequences.append(dict(route=route, file=mapping[route].lstrip('/') if mime == 'text/markdown'
                                  else route.lstrip('/') + 'index.html', mime=mime, accepts=[mime],
                                  method='GET', kind='negotiated' if mime == 'text/markdown' else 'html',
                                  markdown=mapping[route], cache_probe=True))
    for case in result + sequences:
        target = (site / case['file']).resolve()
        if not target.is_relative_to(site) or not target.is_file():
            raise ValueError('Missing/unsafe artifact: ' + case['file'])
    return result, sequences


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, type=Path)
    parser.add_argument('--origin', default='https://piskor.com.ua')
    parser.add_argument('--out', required=True, type=Path, help='New evidence directory; never overwritten')
    parser.add_argument('--known-html-injection', type=Path)
    parser.add_argument('--allow-markdown-redirects', type=int, choices=[307])
    parser.add_argument('--expected-markdown-version', help='Require this Worker revision and no-store on every Markdown response')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=4)
    parser.add_argument('--timeout', type=float, default=20)
    args = parser.parse_args()
    if args.expected_markdown_version is not None and not re.fullmatch(r'[0-9a-f]{40}', args.expected_markdown_version):
        parser.error('Expected Markdown version must be a complete Git SHA')
    origin = args.origin.rstrip('/')
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
        parser.error('Origin must be a plain HTTP(S) origin')
    site = args.site.resolve()
    cases, sequences = jobs(site)
    known = args.known_html_injection.read_bytes() if args.known_html_injection else None
    if known == b'':
        parser.error('Known injection must be nonempty exact bytes')
    args.out.mkdir(parents=True, exist_ok=False)
    def run(pair):
        index, case = pair
        row = verify(case, origin, (site / case['file']).read_bytes(), known,
                     bool(args.allow_markdown_redirects), args.timeout,
                     expected_markdown_version=args.expected_markdown_version)
        for hop, observation in enumerate(row['observations']):
            body = observation.pop('body')
            filename = f'{index:04d}-{hop}.body'
            (args.out / filename).write_bytes(body)
            observation.update(body_file=filename, decoded_bytes=len(body), decoded_sha256=sha(body))
        (args.out / f'{index:04d}.json').write_text(json.dumps(row, indent=2) + '\n')
        return row
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, enumerate(cases)))
    # These must stay sequential, after independent coverage, without cache busting.
    results += [run((len(cases) + i, case)) for i, case in enumerate(sequences)]
    report = dict(kind='production-HTTP-artifact-verification-not-PSI',
                  observed_at=datetime.now(timezone.utc).isoformat(), origin=origin, site=str(site),
                  inventory_sha256=sha((site / 'agent-markdown/routes.json').read_bytes()),
                  script_sha256=sha(Path(__file__).read_bytes()),
                  known_injection_sha256=sha(known) if known else None,
                  expected_markdown_version=args.expected_markdown_version,
                  route_states=len(json.loads((site / 'agent-markdown/routes.json').read_text())['pages']),
                  count=len(results), passed=sum(row['pass_'] for row in results),
                  cache_evidence_scope=('Worker revision, no-store and no observed CF HIT; separate control-plane proof required'
                                        if args.expected_markdown_version else
                                        'CF status only; Age hop attribution/control-plane rules require separate proof'),
                  results=results)
    (args.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('route_states', 'count', 'passed')}))
    return 0 if all(row['pass_'] for row in results) else 2


if __name__ == '__main__':
    raise SystemExit(main())
