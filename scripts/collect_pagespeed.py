"""Collect real Google PSI evidence; inventory/import/matrix modes are offline.

Official API: https://developers.google.com/speed/docs/insights/v5/reference/pagespeedapi/runpagespeed
No Lighthouse CLI results are accepted. A deployment timestamp is required for
acceptance; cached reports from another revision remain diagnostic evidence.

Offline workflow:
  python3 scripts/collect_pagespeed.py inventory --revision COMMIT --deployed-at ISO_TIME --out output/psi/inventory.json
  python3 scripts/collect_pagespeed.py import-html --inventory output/psi/inventory.json --output output/psi --url EXACT_SITE_URL --html SAVED_PSI_HTML
  python3 scripts/collect_pagespeed.py matrix --inventory output/psi/inventory.json --output output/psi

Optional network collection uses PAGESPEED_API_KEY from the environment:
  python3 scripts/collect_pagespeed.py collect --inventory output/psi/inventory.json --output output/psi --max-requests 1
Omit max-requests to collect all missing runs sequentially. HTTP/API errors stop
the invocation immediately; a saved quota stop requires explicit operator retry.
Exit 2 means acceptance is pending/failed, never a successful all-pages result.

The official PSI v5 Discovery document (revision 20261013, checked 2026-10-18)
includes AGENTIC_BROWSING. Request all five current categories, excluding the
deprecated PWA category. Parameter validity does not prove a successful API run:
old/partial responses without actual Agentic coverage remain missing, even with
five fast reports. Distinct settings families are not merged.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


API = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed'
STRATEGIES = ('mobile', 'desktop')
# Primary metadata: https://pagespeedonline.googleapis.com/$discovery/rest?version=v5
CATEGORIES = ('PERFORMANCE', 'ACCESSIBILITY', 'BEST_PRACTICES', 'SEO', 'AGENTIC_BROWSING')
METRICS = {'fcp': 'first-contentful-paint', 'lcp': 'largest-contentful-paint',
           'speed_index': 'speed-index', 'tbt': 'total-blocking-time', 'cls': 'cumulative-layout-shift'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return parsed


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode() + b'\n')
    temporary.replace(path)


class PageMetadata(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.canonical = None
        self.redirect = None
        self.language = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html':
            self.language = attrs.get('lang')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh':
            self.redirect = attrs.get('content')


def runtime_route(route):
    """Normalize only the known 404 language variant, preserving English.

    URLSearchParams.get('lang') in public not-found.js uses the first value.
    At /404.html, uk/unknown/missing values all render the default Ukrainian.
    Other page queries are left intact; they may have different semantics.
    """
    parsed = urlsplit(route)
    if parsed.path != '/404.html' or parsed.scheme or parsed.netloc:
        return route
    requested = next((value for name, value in parse_qsl(parsed.query, keep_blank_values=True)
                      if name == 'lang'), None)
    return '/404.html?lang=en' if requested == 'en' else '/404.html'


def inventory(site, origin, revision, deployed_at=None):
    """Include every generated HTML, including redirect aliases and 404.html."""
    if not revision.strip():
        raise ValueError('An explicit artifact revision is required')
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('Origin must be an HTTPS origin without path/query/fragment')
    if deployed_at:
        timestamp(deployed_at)
    site = Path(site)
    pages = []
    signatures = []
    for path in sorted(site.rglob('*.html')):
        relative = path.relative_to(site).as_posix()
        content = path.read_bytes()
        signatures.append([relative, hashlib.sha256(content).hexdigest()])
        route = '/' + (relative[:-10] if path.name == 'index.html' else relative)
        metadata = PageMetadata(content.decode('utf-8'))
        pages.append({'route': route, 'url': origin.rstrip('/') + quote(route, safe='/'),
                      'file': relative, 'canonical': metadata.canonical,
                      'redirect_hint': metadata.redirect, 'language': metadata.language})
    if not pages:
        raise ValueError('No generated HTML pages found')
    html_count = len(pages)
    error_page = next((page for page in pages if page['route'] == '/404.html'), None)
    controller = site / 'not-found.js'
    if error_page and controller.is_file():
        # Explicit public runtime route: the one HTML has a separate EN state.
        # This works before the optional Markdown route index is generated.
        signatures.append(['not-found.js', hashlib.sha256(controller.read_bytes()).hexdigest()])
        candidates = ['/404.html?lang=en']
        routes_file = site / 'agent-markdown/routes.json'
        if routes_file.is_file():
            routes = json.loads(routes_file.read_text())
            if routes.get('version') != 1 or not isinstance(routes.get('pages'), list):
                raise ValueError('Unsupported generated Markdown route inventory')
            candidates += [item['url'] for item in routes['pages']
                           if urlsplit(item['url']).path == '/404.html']
        seen = {page['route'] for page in pages}
        for candidate in candidates:
            route = runtime_route(candidate)
            if route in seen:
                continue
            if route != '/404.html?lang=en':
                raise ValueError('Unsupported runtime route in Markdown inventory')
            pages.append({**error_page, 'route': route, 'url': origin.rstrip('/') + route,
                          'language': 'en', 'runtime_variant': True})
            seen.add(route)
    manifest = {'schema_version': 1, 'revision': revision, 'artifact_hash': digest(signatures),
                'origin': origin.rstrip('/'), 'deployed_at': deployed_at,
                'html_file_count': html_count, 'page_count': len(pages), 'pages': pages}
    declared_redirects(manifest)
    return manifest


def declared_redirects(manifest):
    """Recognize only declared aliases with an agreeing, real content target."""
    pages = {page['url']: page for page in manifest['pages']}
    origin = urlsplit(manifest['origin'])
    targets = {}
    for page in pages.values():
        if not page.get('redirect_hint'):
            continue
        hint = re.fullmatch(r'0;url=(\S+)', page['redirect_hint'], re.I)
        target = urljoin(page['url'], hint[1]) if hint else None
        parsed = urlsplit(target or '')
        canonical = urljoin(page['url'], page.get('canonical') or '')
        if (not target or (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc)
                or canonical != target or target not in pages
                or pages[target].get('redirect_hint')):
            raise ValueError('Declared redirect needs an agreeing same-origin canonical content target: ' + page['url'])
        if page.get('language') not in {'uk', 'en'} or pages[target].get('language') != page['language']:
            raise ValueError('Declared redirect must preserve its known uk/en language: ' + page['url'])
        targets[page['url']] = target
    return targets


def public_report_id(report_url):
    url = urlsplit(report_url)
    if url.scheme != 'https' or url.netloc != 'pagespeed.web.dev':
        raise ValueError('Public report URL must be on https://pagespeed.web.dev')
    match = re.fullmatch(r'/analysis/[^/]+/([A-Za-z0-9_-]+)/?', url.path)
    if not match:
        raise ValueError('Public PSI report URL must contain its report ID')
    return match[1]


def extract_public_reports(html):
    """Walk embedded JSON and derive modes from reports, never JS or slot indexes."""
    starts = list(re.finditer(r'AF_initDataCallback\s*\(\s*\{', html))
    reports = {}
    decoder = json.JSONDecoder()
    for index, start in enumerate(starts):
        stop = starts[index + 1].start() if index + 1 < len(starts) else len(html)
        data_match = re.search(r'\bdata\s*:\s*', html[start.end():stop])
        if not data_match:
            continue
        offset = start.end() + data_match.end()
        try:
            data, _ = decoder.raw_decode(html, offset)
        except json.JSONDecodeError:
            continue
        pending = [data]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if 'audits' not in value or 'requestedUrl' not in value:
                    pending.extend(value.values())
                    continue
                settings = value.get('configSettings')
                if not isinstance(settings, dict):
                    raise ValueError('Embedded Lighthouse report has unknown form factor')
                strategy = settings.get('formFactor', settings.get('emulatedFormFactor'))
                if strategy not in STRATEGIES:
                    raise ValueError('Embedded Lighthouse report has unknown form factor')
                if ('emulatedFormFactor' in settings and settings['emulatedFormFactor'] != strategy):
                    raise ValueError('Embedded Lighthouse report has conflicting form factors')
                if strategy in reports and canonical(reports[strategy]) != canonical(value):
                    raise ValueError('Ambiguous embedded ' + strategy + ' reports')
                reports[strategy] = value
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str) and value.lstrip().startswith(('{', '[', '"')):
                # PSI can nest serialized JSON inside other JSON strings. Parse
                # only complete JSON values; script expressions remain inert.
                try:
                    pending.append(json.loads(value))
                except json.JSONDecodeError:
                    continue
    if not reports:
        raise ValueError('No embedded public PSI Lighthouse reports found')
    return reports


def finite_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def agentic_coverage(lhr):
    category = lhr.get('categories', {}).get('agentic-browsing')
    if not isinstance(category, dict) or not category.get('auditRefs'):
        return {'status': 'missing', 'weighted_total': 0, 'weighted_passed': 0, 'audits': []}
    audits, total, passed, unknown = [], 0, 0, False
    for ref in category['auditRefs']:
        audit = lhr.get('audits', {}).get(ref['id'], {})
        weight = ref.get('weight', 0)
        mode, score = audit.get('scoreDisplayMode'), audit.get('score')
        not_applicable = mode in ('notApplicable', 'not_applicable')
        state = 'not-applicable' if not_applicable else ('passed' if finite_number(score) and score == 1 else 'failed' if finite_number(score) else 'missing')
        audits.append({'id': ref['id'], 'weight': weight, 'score': score, 'mode': mode, 'status': state})
        if not finite_number(weight):
            unknown = True
        if finite_number(weight) and weight > 0 and not not_applicable:
            total += weight
            if state == 'passed':
                passed += weight
            elif state == 'missing':
                unknown = True
    status = 'missing' if not total or unknown else 'passed' if passed == total and finite_number(category.get('score')) and category.get('score') == 1 else 'failed'
    return {'status': status, 'category_score': category.get('score'), 'weighted_total': total,
            'weighted_passed': passed, 'audits': audits}


def summarize_lhr(lhr, exact_url, strategy, expected_redirect=None):
    errors = []
    if lhr.get('runtimeError'):
        errors.append('runtime-error')
    requested, final = lhr.get('requestedUrl'), lhr.get('finalUrl')
    if requested != exact_url:
        errors.append('requested-url-mismatch')
    if final != (expected_redirect or exact_url):
        errors.append(('unexpected-redirect-target' if expected_redirect else 'redirected') if final else 'missing-final-url')
    settings = lhr.get('configSettings', {})
    if settings.get('formFactor', settings.get('emulatedFormFactor')) != strategy:
        errors.append('strategy-mismatch')
    if not lhr.get('lighthouseVersion'):
        errors.append('missing-lighthouse-version')
    try:
        timestamp(lhr.get('fetchTime', ''))
    except (ValueError, AttributeError, TypeError):
        errors.append('missing-or-invalid-fetch-time')
    audits = lhr.get('audits', {})
    metrics = {name: audits.get(audit, {}).get('numericValue') for name, audit in METRICS.items()}
    for name in ('fcp', 'lcp', 'speed_index'):
        if not finite_number(metrics[name]):
            errors.append('missing-or-invalid-' + name)
    main_url = lhr.get('mainDocumentUrl') or final
    documents = [item for item in audits.get('network-requests', {}).get('details', {}).get('items', [])
                 if item.get('resourceType') == 'Document' and item.get('url') == main_url]
    statuses = [item.get('statusCode') for item in documents]
    if not statuses or any(not isinstance(code, int) or not 200 <= code < 300 for code in statuses):
        errors.append('missing-or-unsuccessful-document-http-status')
    http_audit = audits.get('http-status-code', {})
    if http_audit.get('score') == 0:
        errors.append('http-status-audit-failed')
    return {'requested_url': requested, 'final_url': final, 'main_document_url': main_url,
            'document_http_statuses': statuses, 'fetch_time': lhr.get('fetchTime'),
            'lighthouse_version': lhr.get('lighthouseVersion'), 'metrics': metrics,
            'settings': settings, 'settings_hash': digest({'version': lhr.get('lighthouseVersion'), 'config': settings}),
            'agentic': agentic_coverage(lhr), 'validation_errors': errors,
            'runtime_error': lhr.get('runtimeError'), 'run_warnings': lhr.get('runWarnings', [])}


def save_report(output, manifest, exact_url, strategy, lhr, source, report_id):
    if exact_url not in {page['url'] for page in manifest['pages']}:
        raise ValueError('Exact requested URL is not in this inventory')
    summary = summarize_lhr(lhr, exact_url, strategy, declared_redirects(manifest).get(exact_url))
    identity = {'revision': manifest['revision'], 'artifact_hash': manifest['artifact_hash'],
                'url': exact_url, 'strategy': strategy, 'settings_hash': summary['settings_hash'],
                'source': source['kind'], 'report_id': report_id}
    key = digest(identity)
    raw_hash = digest(lhr)
    output = Path(output)
    raw_path = output / 'reports' / (raw_hash + '.json.gz')
    if not raw_path.exists():
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(gzip.compress(canonical(lhr), mtime=0))
    record = {**identity, 'cache_key': key, 'report_sha256': raw_hash,
              'report_file': raw_path.relative_to(output).as_posix(), 'source_details': source,
              'imported_at': now(), **summary}
    target = output / 'records' / (key + '.json')
    if target.exists():
        old = json.loads(target.read_text())
        if old['report_sha256'] != raw_hash:
            raise ValueError('A cached report identity changed; retain both source files for investigation')
        return old
    write_json(target, record)
    return record


def load_records(output):
    return [json.loads(path.read_text()) for path in sorted((Path(output) / 'records').glob('*.json'))]


def freshness_errors(record, manifest):
    errors = list(record['validation_errors'])
    expected = declared_redirects(manifest).get(record['url'])
    if expected:
        if record.get('final_url') == expected:
            # Older cached records treated every redirect as invalid. Reclassify
            # only that error using the current declaration, retaining all others.
            errors = [error for error in errors if error != 'redirected']
        else:
            errors.append('unexpected-redirect-target' if record.get('final_url') else 'missing-final-url')
    if not manifest.get('deployed_at'):
        errors.append('deployment-time-unverified')
    else:
        try:
            if timestamp(record.get('fetch_time', '')) < timestamp(manifest['deployed_at']):
                errors.append('report-predates-deployment')
        except (ValueError, TypeError, AttributeError):
            errors.append('missing-or-invalid-fetch-time')
    return sorted(set(errors))


def build_matrix(manifest, records, runs=5, threshold=1000):
    rows = []
    redirects = declared_redirects(manifest)
    for page in manifest['pages']:
        expected = redirects.get(page['url'])
        for strategy in STRATEGIES:
            matching = [record for record in records if record['url'] == page['url'] and record['strategy'] == strategy]
            current = [record for record in matching if record['revision'] == manifest['revision'] and record['artifact_hash'] == manifest['artifact_hash']]
            groups = {}
            for record in current:
                groups.setdefault(record['settings_hash'], {})[record['report_sha256']] = record
            group_results = []
            for settings_hash, unique in sorted(groups.items()):
                evidence = list(unique.values())
                valid = [record for record in evidence if not freshness_errors(record, manifest)]
                invalid = [{'report_id': record['report_id'], 'errors': freshness_errors(record, manifest)}
                           for record in evidence if freshness_errors(record, manifest)]
                metric_ranges = {}
                for name in METRICS:
                    values = [record['metrics'][name] for record in valid if finite_number(record['metrics'][name])]
                    metric_ranges[name] = {'min': min(values), 'max': max(values), 'median': statistics.median(values)} if values else None
                distinct_runs = len({record['fetch_time'] for record in valid})
                performance_pass = distinct_runs >= runs and all(record['metrics'][name] < threshold for record in valid for name in ('fcp', 'lcp', 'speed_index'))
                agentic_pass = distinct_runs >= runs and all(record['agentic']['status'] == 'passed' for record in valid)
                group_results.append({'settings_hash': settings_hash, 'valid_runs': distinct_runs, 'distinct_report_bodies': len(valid), 'invalid_reports': invalid,
                                      'metrics': metric_ranges, 'performance_pass': performance_pass,
                                      'agentic_pass': agentic_pass,
                                      'reports': [{'report_id': record['report_id'], 'source': record['source_details'],
                                                   'fetch_time': record['fetch_time'], 'metrics': record['metrics'],
                                                   'agentic': record['agentic'], 'final_url': record['final_url'],
                                                   'http_statuses': record['document_http_statuses']} for record in evidence]})
            if not group_results:
                status = 'pending'
            elif len(group_results) > 1:
                status = 'mixed-settings'
            elif group_results[0]['invalid_reports']:
                status = 'invalid-evidence'
            elif group_results[0]['valid_runs'] < runs:
                status = 'pending'
            elif expected:
                # These metrics describe the final document. Neither its speed
                # nor finalUrl establishes the alias's total entry timing/chain.
                status = 'expected-routing-entry-timing-unverified'
            elif not group_results[0]['performance_pass']:
                status = 'failed-performance'
            elif not group_results[0]['agentic_pass']:
                status = 'failed-or-missing-agentic'
            else:
                status = 'passed'
            rows.append({'route': page['route'], 'url': page['url'], 'strategy': strategy, 'status': status,
                         'kind': 'declared-redirect' if expected else 'content',
                         **({'expected_redirect': expected, 'entry_timing_status': 'unverified',
                             'canonical_cohort': {'url': expected, 'strategy': strategy}} if expected else {}),
                         'canonical': page.get('canonical'), 'redirect_hint': page.get('redirect_hint'),
                         'previous_artifact_reports_diagnostic_only': len(matching) - len(current),
                         'previous_artifact_reports': [
                             {key: record[key] for key in ('revision', 'artifact_hash', 'report_id', 'fetch_time',
                                                           'settings_hash', 'metrics', 'agentic', 'source_details')}
                             for record in matching if record not in current],
                         'settings_groups': group_results})
    content_rows = [row for row in rows if row['kind'] == 'content']
    return {'revision': manifest['revision'], 'artifact_hash': manifest['artifact_hash'],
            'deployed_at': manifest.get('deployed_at'), 'required_runs_per_strategy': runs,
            'threshold_ms_exclusive': threshold, 'pages': len(manifest['pages']),
            'html_files': manifest.get('html_file_count'), 'rows': rows,
            'content_pages': len(manifest['pages']) - len(redirects), 'declared_aliases': len(redirects),
            'content_rows': len(content_rows), 'alias_rows': len(rows) - len(content_rows),
            'all_content_pages_pass': bool(content_rows) and all(row['status'] == 'passed' for row in content_rows),
            'passed_rows': sum(row['status'] == 'passed' for row in rows),
            'all_pages_pass': bool(rows) and all(row['status'] == 'passed' for row in rows)}


def write_matrix(output, manifest, runs=5, threshold=1000):
    matrix = build_matrix(manifest, load_records(output), runs, threshold)
    write_json(Path(output) / 'matrix.json', matrix)
    lines = ['# Public Google PSI acceptance matrix', '',
             f"Revision: `{manifest['revision']}`; artifact: `{manifest['artifact_hash']}`.", '',
             f"Requested URLs: {len(manifest['pages'])}; generated HTML files: {manifest.get('html_file_count', 'unknown')}. Runtime language variants remain separate URLs.", '',
             f'Required: {runs} distinct reports per strategy, each FCP/LCP/SI < {threshold} ms, valid direct-page HTTP evidence, and applicable weighted Agentic audits passed.',
             'Missing, unexpected redirects, failed, stale, or mixed-settings evidence is not a pass. Earlier artifact reports remain diagnostic only.', '',
             f"Content states: {matrix['content_pages']} ({matrix['content_rows']} mode rows); declared aliases: {matrix['declared_aliases']} ({matrix['alias_rows']} mode rows). All URL states remain listed.",
             'Declared-alias metrics are final-document diagnostics, not proof of entry timing or redirect-chain correctness. Their canonical cohort is measured separately; alias entry timing remains unverified and prevents universal acceptance.', '',
             '| Route | Strategy | Status | Valid runs | FCP min–max, ms | LCP min–max, ms | SI min–max, ms |',
             '|---|---|---|---:|---|---|---|']
    for row in matrix['rows']:
        group = row['settings_groups'][0] if len(row['settings_groups']) == 1 else None
        def span(name):
            value = group['metrics'][name] if group else None
            return str(value['min']) + '–' + str(value['max']) if value else 'pending'
        lines.append(f"| {row['route']} | {row['strategy']} | {row['status']} | {group['valid_runs'] if group else 0}/{runs} | {span('fcp')} | {span('lcp')} | {span('speed_index')} |")
    lines += ['', f"Passed rows: {matrix['passed_rows']}/{len(matrix['rows'])}. All content pages pass: {matrix['all_content_pages_pass']}. All pages pass: {matrix['all_pages_pass']}.",
              'Full precision, settings families, actual weighted/unweighted/N/A Agentic audits, URLs, HTTP statuses and exclusions are in matrix.json.', '']
    target = Path(output) / 'matrix.md'
    target.write_text('\n'.join(lines))
    return matrix


def api_request(exact_url, strategy, key):
    # Never return/log the key-bearing URL or exception string.
    parameters = [('url', exact_url), ('strategy', strategy), ('locale', 'en-US')]
    parameters += [('category', category) for category in CATEGORIES]
    parameters.append(('key', key))
    request = Request(API + '?' + urlencode(parameters), headers={'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=180) as response:
            result = json.load(response)
    except HTTPError as error:
        error.close()
        return None, {'status': error.code, 'reason': 'quota-exhausted' if error.code == 429 else 'api-http-error'}
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None, {'status': None, 'reason': 'api-network-or-json-error'}
    if not isinstance(result, dict) or 'error' in result:
        status = result.get('error', {}).get('code') if isinstance(result, dict) else None
        return None, {'status': status, 'reason': 'quota-exhausted' if status == 429 else 'api-error'}
    if result.get('captchaResult') in ('CAPTCHA_BLOCKING', 'CAPTCHA_NEEDED', 'CAPTCHA_UNMATCHED'):
        return None, {'status': None, 'reason': 'captcha-required'}
    if not isinstance(result.get('lighthouseResult'), dict):
        return None, {'status': None, 'reason': 'missing-lighthouse-result'}
    return result['lighthouseResult'], None


def collect(output, manifest, runs, threshold, urls=None, max_requests=None, retry_after_quota=False):
    key = os.environ.get('PAGESPEED_API_KEY')
    output = Path(output)
    stop = output / 'collection-stop.json'
    if not key:
        if stop.exists() and json.loads(stop.read_text()).get('reason') == 'quota-exhausted':
            return write_matrix(output, manifest, runs, threshold)
        write_json(stop, {'reason': 'PAGESPEED_API_KEY-not-set', 'network_requests': 0,
                          'note': 'Unkeyed quota-zero probe is already known; it is not retried.'})
        return write_matrix(output, manifest, runs, threshold)
    if stop.exists() and json.loads(stop.read_text()).get('reason') == 'quota-exhausted' and not retry_after_quota:
        return write_matrix(output, manifest, runs, threshold)
    if not manifest.get('deployed_at'):
        write_json(stop, {'reason': 'deployment-time-unverified', 'network_requests': 0})
        return write_matrix(output, manifest, runs, threshold)
    records = load_records(output)
    requested = set(urls or [page['url'] for page in manifest['pages']])
    known = {page['url'] for page in manifest['pages']}
    if not requested.issubset(known):
        raise ValueError('Requested URL is not in the exact inventory')
    requests = 0
    # Spread repeated URL/mode keys across the inventory without concurrency,
    # cache-busting or extra calls. Freshness is still checked on every result.
    for round_index in range(runs):
        for page in manifest['pages']:
            if page['url'] not in requested:
                continue
            for strategy in STRATEGIES:
                existing = [record for record in records if record['revision'] == manifest['revision']
                            and record['artifact_hash'] == manifest['artifact_hash'] and record['url'] == page['url']
                            and record['strategy'] == strategy and not freshness_errors(record, manifest)]
                # Cached and unfavorable completed cohorts keep their places:
                # do not retry a slow result to manufacture passing reports.
                count = len({record['fetch_time'] for record in existing})
                if count > round_index:
                    continue
                if max_requests is not None and requests >= max_requests:
                    return write_matrix(output, manifest, runs, threshold)
                lhr, error = api_request(page['url'], strategy, key)
                requests += 1
                if error:
                    write_json(stop, {**error, 'at': now(), 'url': page['url'], 'strategy': strategy, 'network_requests': requests})
                    return write_matrix(output, manifest, runs, threshold)
                record = save_report(output, manifest, page['url'], strategy, lhr,
                                     {'kind': 'google-psi-v5', 'endpoint': API}, 'api:' + digest(lhr))
                if any(previous['url'] == record['url'] and previous['strategy'] == strategy
                       and previous['fetch_time'] == record['fetch_time']
                       and previous['revision'] == record['revision']
                       and previous['artifact_hash'] == record['artifact_hash'] for previous in records):
                    write_json(stop, {'reason': 'duplicate-measurement-time', 'at': now(), 'url': page['url'],
                                      'strategy': strategy, 'network_requests': requests})
                    return write_matrix(output, manifest, runs, threshold)
                records.append(record)
                if freshness_errors(record, manifest):
                    write_json(stop, {'reason': 'invalid-report', 'at': now(), 'url': page['url'], 'strategy': strategy,
                                      'errors': freshness_errors(record, manifest), 'network_requests': requests})
                    return write_matrix(output, manifest, runs, threshold)
    if stop.exists():
        stop.unlink()
    return write_matrix(output, manifest, runs, threshold)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inv = commands.add_parser('inventory', help='Offline inventory of every generated HTML')
    inv.add_argument('--site', default='_site')
    inv.add_argument('--origin', default='https://piskor.com.ua')
    inv.add_argument('--revision', required=True)
    inv.add_argument('--deployed-at', help='Verified deployment timestamp, ISO 8601 with timezone')
    inv.add_argument('--out', required=True)
    for name in ('import-html', 'matrix', 'collect'):
        command = commands.add_parser(name)
        command.add_argument('--inventory', required=True)
        command.add_argument('--output', required=True)
        command.add_argument('--runs', type=int, default=5)
        command.add_argument('--threshold', type=float, default=1000)
        if name == 'import-html':
            command.add_argument('--html', required=True)
            command.add_argument('--report-url', help='Public PSI URL; otherwise use the saved HTML canonical')
            command.add_argument('--url', required=True, help='Exact audited site URL from inventory')
        if name == 'collect':
            command.add_argument('--url', action='append', help='Limit to exact URL(s); default all inventory')
            command.add_argument('--max-requests', type=int)
            command.add_argument('--retry-after-quota', action='store_true', help='Explicit operator retry after quota recovery; never automatic')
    args = parser.parse_args(argv)
    if args.command == 'inventory':
        manifest = inventory(args.site, args.origin, args.revision, args.deployed_at)
        write_json(args.out, manifest)
        print(json.dumps({'pages': manifest['page_count'], 'revision': manifest['revision'], 'artifact_hash': manifest['artifact_hash']}))
        return 0
    if args.runs < 1 or not finite_number(args.threshold) or args.threshold <= 0 or (getattr(args, 'max_requests', None) is not None and args.max_requests < 1):
        parser.error('runs/threshold/max-requests must be positive')
    manifest = json.loads(Path(args.inventory).read_text())
    if args.command == 'import-html':
        html = Path(args.html).read_text()
        report_url = args.report_url or PageMetadata(html).canonical
        report_id = public_report_id(report_url or '')
        for strategy, lhr in extract_public_reports(html).items():
            save_report(args.output, manifest, args.url, strategy, lhr,
                        {'kind': 'google-psi-public-ui', 'report_url': report_url,
                         'html_sha256': hashlib.sha256(html.encode()).hexdigest()}, report_id)
        result = write_matrix(args.output, manifest, args.runs, args.threshold)
    elif args.command == 'collect':
        result = collect(args.output, manifest, args.runs, args.threshold, args.url, args.max_requests, args.retry_after_quota)
    else:
        result = write_matrix(args.output, manifest, args.runs, args.threshold)
    print(json.dumps({'pages': result['pages'], 'passed_rows': result['passed_rows'],
                      'required_rows': len(result['rows']), 'all_pages_pass': result['all_pages_pass']}))
    return 0 if result['all_pages_pass'] else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as error:
        # These are local/parser errors only; network exceptions are sanitized above.
        print('PSI evidence error: ' + str(error), file=sys.stderr)
        sys.exit(1)
