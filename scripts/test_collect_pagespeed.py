"""Offline tests only; no Google requests, browser or Lighthouse invocation."""
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from collect_pagespeed import (agentic_coverage, api_request, build_matrix, collect, declared_redirects,
                               extract_public_reports, inventory, load_records,
                               public_report_id, runtime_route, save_report, summarize_lhr, write_matrix)


URL = 'https://piskor.com.ua/'


def lhr(strategy='mobile', run=0):
    return {'requestedUrl': URL, 'finalUrl': URL, 'mainDocumentUrl': URL,
            'fetchTime': f'2026-10-18T15:00:{run:02d}Z', 'lighthouseVersion': '13.5.0',
            'configSettings': {'formFactor': strategy, 'throttling': {'cpuSlowdownMultiplier': 1.2}},
            'audits': {'first-contentful-paint': {'numericValue': 900.123456},
                       'largest-contentful-paint': {'numericValue': 999.999999},
                       'speed-index': {'numericValue': 980.123456},
                       'network-requests': {'details': {'items': [{'resourceType': 'Document', 'url': URL, 'statusCode': 200}]}},
                       'weighted': {'score': 1, 'scoreDisplayMode': 'binary'},
                       'unweighted': {'score': 0, 'scoreDisplayMode': 'binary'},
                       'form': {'score': None, 'scoreDisplayMode': 'notApplicable'}},
            'categories': {'agentic-browsing': {'score': 1, 'auditRefs': [
                {'id': 'weighted', 'weight': 2}, {'id': 'unweighted', 'weight': 0}, {'id': 'form', 'weight': 0}]}}}


def embedded_html(mobile, desktop):
    data = [None] * 5
    data[4] = [None] * 5
    for position, report in [(4, mobile), (3, desktop)]:
        data[4][position] = [None] * 10
        data[4][position][9] = json.dumps(report)
    return "<script>AF_initDataCallback({key:'ds:1',hash:'x',data:" + json.dumps(data) + ",sideChannel:{}});</script>"


def route_lhr(url, strategy='mobile', run=0, final=None):
    report = lhr(strategy, run)
    final = final or url
    report.update(requestedUrl=url, finalUrl=final, mainDocumentUrl=final)
    report['audits']['network-requests']['details']['items'][0]['url'] = final
    return report


class PagespeedEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        (self.site / 'index.html').write_text('<html lang="uk"><h1>Public page</h1></html>')
        self.manifest = inventory(self.site, 'https://piskor.com.ua', 'current-revision', '2026-10-18T14:00:00Z')
        self.output = self.root / 'evidence'

    def save(self, report, identity, manifest=None):
        strategy = report['configSettings']['formFactor']
        return save_report(self.output, manifest or self.manifest, URL, strategy, report,
                           {'kind': 'google-psi-public-ui', 'report_url': 'https://pagespeed.web.dev/analysis/site/' + identity}, identity)

    def populate(self, manifest=None):
        for strategy in ('mobile', 'desktop'):
            for run in range(5):
                self.save(lhr(strategy, run), strategy + str(run), manifest)

    def alias_manifest(self):
        (self.site / 'old').mkdir()
        (self.site / 'z-new').mkdir()
        (self.site / 'old/index.html').write_text(
            '<html lang="uk"><link rel="canonical" href="' + URL + 'z-new/">'
            '<meta http-equiv="refresh" content="0;url=/z-new/">')
        (self.site / 'z-new/index.html').write_text('<html lang="uk"><h1>Canonical content</h1></html>')
        return inventory(self.site, URL.rstrip('/'), 'current-revision', '2026-10-18T14:00:00Z')

    def test_inventory_keeps_aliases_404_and_exact_nonindex_names(self):
        (self.site / '404.html').write_text('<h1>Not found</h1>')
        (self.site / 'homeindex.html').write_text('<h1>Not an index filename</h1>')
        (self.site / 'old').mkdir()
        (self.site / 'old/index.html').write_text('<html lang="uk"><link rel="canonical" href="' + URL + '">'
                                                 '<meta http-equiv="refresh" content="0;url=/">')
        manifest = inventory(self.site, 'https://piskor.com.ua', 'revision')
        self.assertEqual({page['route'] for page in manifest['pages']}, {'/', '/404.html', '/homeindex.html', '/old/'})
        self.assertTrue(next(page for page in manifest['pages'] if page['route'] == '/old/')['redirect_hint'])
        self.assertEqual(manifest, inventory(self.site, 'https://piskor.com.ua', 'revision'))
        (self.site / 'index.html').write_text('<html lang="uk">changed artifact</html>')
        self.assertNotEqual(manifest['artifact_hash'], inventory(self.site, 'https://piskor.com.ua', 'revision')['artifact_hash'])

    def test_declared_alias_requires_agreeing_local_canonical_and_nonalias_target(self):
        manifest = self.alias_manifest()
        self.assertEqual(declared_redirects(manifest), {URL + 'old/': URL + 'z-new/'})
        for change in [
            {'canonical': 'https://other.example/', 'redirect_hint': '0;url=https://other.example/'},
            {'canonical': URL + 'missing/', 'redirect_hint': '0;url=/missing/'},
            {'canonical': URL, 'redirect_hint': '0;url=/z-new/'},
            {'canonical': URL + 'old/', 'redirect_hint': '0;url=/old/'},
        ]:
            invalid = deepcopy(manifest)
            next(page for page in invalid['pages'] if page['route'] == '/old/').update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                declared_redirects(invalid)

    def test_declared_alias_rejects_cross_language_or_unknown_language_targets(self):
        manifest = self.alias_manifest()
        for alias_language, target_language in [('uk', 'en'), ('en', 'uk'), (None, 'uk'), ('uk', None)]:
            invalid = deepcopy(manifest)
            next(page for page in invalid['pages'] if page['route'] == '/old/')['language'] = alias_language
            next(page for page in invalid['pages'] if page['route'] == '/z-new/')['language'] = target_language
            with self.subTest(alias=alias_language, target=target_language), self.assertRaisesRegex(ValueError, 'known uk/en language'):
                declared_redirects(invalid)
        english = deepcopy(manifest)
        for page in english['pages']:
            if page['route'] in {'/old/', '/z-new/'}:
                page['language'] = 'en'
        self.assertEqual(declared_redirects(english), {URL + 'old/': URL + 'z-new/'})

    def test_expected_alias_missing_entry_timing_keeps_diagnostics_without_inheriting_canonical_acceptance(self):
        manifest = self.alias_manifest()
        for page in manifest['pages']:
            for strategy in ('mobile', 'desktop'):
                for run in range(5):
                    report = route_lhr(page['url'], strategy, run,
                                       URL + 'z-new/' if page['route'] == '/old/' else None)
                    save_report(self.output, manifest, page['url'], strategy, report,
                                {'kind': 'google-psi-public-ui'}, page['route'] + strategy + str(run))
        records = load_records(self.output)
        matrix = write_matrix(self.output, manifest)
        self.assertEqual((matrix['pages'], matrix['content_pages'], matrix['declared_aliases']), (3, 2, 1))
        self.assertEqual((matrix['content_rows'], matrix['alias_rows']), (4, 2))
        self.assertTrue(matrix['all_content_pages_pass'])
        self.assertFalse(matrix['all_pages_pass'])
        aliases = [row for row in matrix['rows'] if row['kind'] == 'declared-redirect']
        for row in aliases:
            self.assertEqual(row['status'], 'expected-routing-entry-timing-unverified')
            self.assertEqual(row['entry_timing_status'], 'unverified')
            self.assertEqual(row['canonical_cohort'], {'url': URL + 'z-new/', 'strategy': row['strategy']})
            self.assertEqual(row['settings_groups'][0]['metrics']['lcp']['max'], 999.999999)
            self.assertTrue(all(report['final_url'] == URL + 'z-new/' for report in row['settings_groups'][0]['reports']))
        # Reclassify only the old blanket redirect error, not other evidence faults.
        for record in records:
            if record['url'] == URL + 'old/':
                record['validation_errors'].append('redirected')
        self.assertEqual(build_matrix(manifest, records)['rows'][2]['status'], 'expected-routing-entry-timing-unverified')
        self.assertIn('entry timing remains unverified', (self.output / 'matrix.md').read_text())

    def test_wrong_alias_target_and_stale_reports_remain_invalid(self):
        manifest = self.alias_manifest()
        report = route_lhr(URL + 'old/', final=URL)
        wrong = save_report(self.output, manifest, URL + 'old/', 'mobile', report,
                            {'kind': 'google-psi-public-ui'}, 'wrong-target')
        self.assertIn('unexpected-redirect-target', wrong['validation_errors'])
        report = route_lhr(URL + 'old/', final=URL + 'z-new/')
        report['fetchTime'] = '2026-10-18T12:00:00Z'
        stale = save_report(self.output, manifest, URL + 'old/', 'mobile', report,
                            {'kind': 'google-psi-public-ui'}, 'stale-target')
        matrix = build_matrix(manifest, [wrong, stale], runs=1)
        row = next(row for row in matrix['rows'] if row['url'] == URL + 'old/' and row['strategy'] == 'mobile')
        self.assertEqual(row['status'], 'invalid-evidence')
        self.assertIn('report-predates-deployment', row['settings_groups'][0]['invalid_reports'][1]['errors'])
        self.assertFalse(matrix['all_pages_pass'])

    def test_collector_continues_after_expected_alias_to_later_content(self):
        manifest = self.alias_manifest()
        calls = []
        def response(url, strategy, key):
            calls.append((url, strategy))
            return route_lhr(url, strategy, len(calls), URL + 'z-new/' if url == URL + 'old/' else None), None
        with patch.dict(os.environ, {'PAGESPEED_API_KEY': 'secret'}), patch('collect_pagespeed.api_request', side_effect=response):
            matrix = collect(self.output, manifest, 1, 1000)
            self.assertEqual(calls, [(url, strategy) for url in [URL, URL + 'old/', URL + 'z-new/'] for strategy in ('mobile', 'desktop')])
            self.assertTrue(matrix['all_content_pages_pass'])
            self.assertFalse(matrix['all_pages_pass'])
            self.assertFalse((self.output / 'collection-stop.json').exists())
            # Completed diagnostic alias cohorts are not repeatedly recollected.
            collect(self.output, manifest, 1, 1000)
            self.assertEqual(len(calls), 6)

    def test_two_rounds_visit_all_urls_and_modes_before_repeating(self):
        manifest = self.alias_manifest()
        calls = []
        def response(url, strategy, key):
            calls.append((url, strategy))
            return route_lhr(url, strategy, len(calls), URL + 'z-new/' if url == URL + 'old/' else None), None
        with patch.dict(os.environ, {'PAGESPEED_API_KEY': 'secret'}), patch('collect_pagespeed.api_request', side_effect=response):
            matrix = collect(self.output, manifest, 2, 1000)
        one_round = [(url, strategy) for url in [URL, URL + 'old/', URL + 'z-new/'] for strategy in ('mobile', 'desktop')]
        self.assertEqual(calls, one_round * 2)
        self.assertEqual(len(load_records(self.output)), 12)
        self.assertTrue(matrix['all_content_pages_pass'])
        self.assertFalse(matrix['all_pages_pass'])

    def test_uneven_cache_resumes_only_missing_rounds_and_keeps_slow_reports(self):
        for run in range(2):
            report = lhr('mobile', run)
            if run == 0:
                report['audits']['largest-contentful-paint']['numericValue'] = 1200
            self.save(report, 'cached-mobile-' + str(run))
        calls = []
        def response(url, strategy, key):
            calls.append((url, strategy))
            return route_lhr(url, strategy, 10 + len(calls)), None
        with patch.dict(os.environ, {'PAGESPEED_API_KEY': 'secret'}), patch('collect_pagespeed.api_request', side_effect=response):
            matrix = collect(self.output, self.manifest, 3, 1000)
            self.assertEqual(calls, [(URL, 'desktop'), (URL, 'desktop'), (URL, 'mobile'), (URL, 'desktop')])
            mobile = next(row for row in matrix['rows'] if row['strategy'] == 'mobile')
            self.assertEqual(mobile['status'], 'failed-performance')
            self.assertEqual(mobile['settings_groups'][0]['valid_runs'], 3)
            self.assertEqual(mobile['settings_groups'][0]['metrics']['lcp']['max'], 1200)
            collect(self.output, self.manifest, 3, 1000)
            self.assertEqual(len(calls), 4)

    def test_round_robin_request_limit_resumes_without_repeating_completed_slots(self):
        manifest = self.alias_manifest()
        calls = []
        def response(url, strategy, key):
            calls.append((url, strategy))
            return route_lhr(url, strategy, len(calls), URL + 'z-new/' if url == URL + 'old/' else None), None
        one_round = [(url, strategy) for url in [URL, URL + 'old/', URL + 'z-new/'] for strategy in ('mobile', 'desktop')]
        with patch.dict(os.environ, {'PAGESPEED_API_KEY': 'secret'}), patch('collect_pagespeed.api_request', side_effect=response):
            first = collect(self.output, manifest, 2, 1000, max_requests=7)
            self.assertEqual(calls, (one_round * 2)[:7])
            self.assertFalse(first['all_content_pages_pass'])
            resumed = collect(self.output, manifest, 2, 1000)
            self.assertEqual(calls, one_round * 2)
            self.assertTrue(resumed['all_content_pages_pass'])
            collect(self.output, manifest, 2, 1000)
            self.assertEqual(len(calls), 12)

    def test_round_robin_duplicate_measurement_still_stops_without_retry(self):
        calls = []
        def response(url, strategy, key):
            calls.append((url, strategy))
            return route_lhr(url, strategy, 0), None
        with patch.dict(os.environ, {'PAGESPEED_API_KEY': 'secret'}), patch('collect_pagespeed.api_request', side_effect=response):
            matrix = collect(self.output, self.manifest, 2, 1000)
        self.assertEqual(calls, [(URL, 'mobile'), (URL, 'desktop'), (URL, 'mobile')])
        stop = json.loads((self.output / 'collection-stop.json').read_text())
        self.assertEqual(stop['reason'], 'duplicate-measurement-time')
        self.assertEqual(stop['network_requests'], 3)
        self.assertEqual(len(load_records(self.output)), 2)
        self.assertFalse(matrix['all_pages_pass'])

    def test_parser_decodes_json_without_evaluating_javascript(self):
        mobile, desktop = lhr(), lhr('desktop')
        html = "<script>throw new Error('must not evaluate');</script>" + embedded_html(mobile, desktop)
        self.assertEqual(extract_public_reports(html), {'mobile': mobile, 'desktop': desktop})
        self.assertEqual(public_report_id('https://pagespeed.web.dev/analysis/site/report-123?form_factor=mobile'), 'report-123')
        for invalid in ['https://other.example/analysis/site/id', 'https://pagespeed.web.dev/analysis/site']:
            with self.assertRaises(ValueError):
                public_report_id(invalid)
        with self.assertRaises(ValueError):
            extract_public_reports('<script>AF_initDataCallback({data:[1,2]});</script>')
        with self.assertRaises(ValueError):
            extract_public_reports(html + embedded_html(lhr(run=1), desktop))

    def test_parser_derives_modes_after_slots_move_and_reports_are_nested_json(self):
        mobile, desktop = lhr(), lhr('desktop')
        # The live October report moved mobile to [4][0] and desktop to [4][4].
        # Deeper serialization/dictionary wrappers must not change either mode.
        data = [None] * 5
        data[4] = [None] * 5
        data[4][0] = {'payload': json.dumps(json.dumps({'report': mobile}))}
        data[4][4] = [desktop]
        html = '<script>AF_initDataCallback({data:' + json.dumps(data) + '});</script>'
        reports = extract_public_reports(html)
        self.assertEqual(reports, {'mobile': mobile, 'desktop': desktop})
        self.assertEqual(summarize_lhr(reports['mobile'], URL, 'mobile')['validation_errors'], [])
        # Root JSON need not be an array, and repeated identical payloads are safe.
        for root in ({'reports': [mobile, json.dumps(desktop), mobile]},
                     json.dumps({'reports': [mobile, desktop]})):
            with self.subTest(root_type=type(root).__name__):
                html = '<script>AF_initDataCallback({data:' + json.dumps(root) + '});</script>'
                self.assertEqual(extract_public_reports(html), reports)

    def test_parser_rejects_unknown_modes_and_conflicting_duplicate_reports(self):
        for settings in ({}, None, {'formFactor': 'tablet'}, {'formFactor': None},
                         {'formFactor': 'mobile', 'emulatedFormFactor': 'desktop'}):
            report = lhr()
            report['configSettings'] = settings
            html = '<script>AF_initDataCallback({data:' + json.dumps({'report': report}) + '});</script>'
            with self.subTest(settings=settings), self.assertRaisesRegex(ValueError, 'form factor'):
                extract_public_reports(html)
        html = '<script>AF_initDataCallback({data:' + json.dumps([lhr(), {'nested': json.dumps(lhr(run=1))}]) + '});</script>'
        with self.assertRaisesRegex(ValueError, 'Ambiguous embedded mobile'):
            extract_public_reports(html)
        # Python considers True == 1, but an invalid boolean audit score is not
        # the same report as a valid numeric score, regardless of traversal order.
        boolean_score = lhr()
        boolean_score['audits']['weighted']['score'] = True
        for reports in ([lhr(), boolean_score], [boolean_score, lhr()]):
            html = '<script>AF_initDataCallback({data:' + json.dumps(reports) + '});</script>'
            with self.assertRaisesRegex(ValueError, 'Ambiguous embedded mobile'):
                extract_public_reports(html)

    def test_parser_keeps_partial_modes_and_legacy_form_factor_without_executing_code(self):
        desktop = lhr('desktop')
        desktop['configSettings']['emulatedFormFactor'] = desktop['configSettings'].pop('formFactor')
        html = '<script>AF_initDataCallback({data:' + json.dumps({'payload': desktop}) + '});</script>'
        self.assertEqual(extract_public_reports(html), {'desktop': desktop})
        expression = '(() => ' + json.dumps(lhr()) + ')()'
        with self.assertRaises(ValueError):
            extract_public_reports('<script>AF_initDataCallback({data:' + json.dumps(expression) + '});</script>')

    def test_runtime_404_english_variant_exists_before_generated_index_and_deduplicates_queries(self):
        (self.site / '404.html').write_text('<html lang="uk"><h1>Немає</h1></html>')
        (self.site / 'not-found.js').write_text(Path('concept/not-found.js').read_text())
        manifest = inventory(self.site, 'https://piskor.com.ua', 'revision')
        self.assertEqual(manifest['html_file_count'], 2)
        self.assertEqual(manifest['page_count'], 3)
        self.assertEqual({page['route'] for page in manifest['pages']}, {'/', '/404.html', '/404.html?lang=en'})
        english = next(page for page in manifest['pages'] if page['language'] == 'en')
        self.assertEqual(english['url'], 'https://piskor.com.ua/404.html?lang=en')
        self.assertEqual(english['file'], '404.html')
        routes = ['/404.html', '/404.html?lang=uk', '/404.html?lang=en',
                  '/404.html?lang=en&lang=uk', '/404.html?lang=uk&lang=en',
                  '/404.html?lang=en&lang=en', '/404.html?unused=1&lang=en']
        self.assertEqual({runtime_route(route) for route in routes}, {'/404.html', '/404.html?lang=en'})
        self.assertEqual(runtime_route('/portfolio/?year=2026'), '/portfolio/?year=2026')
        generated = self.site / 'agent-markdown/routes.json'
        generated.parent.mkdir()
        generated.write_text(json.dumps({'version': 1, 'pages': [
            {'url': route, 'markdown': '/agent-markdown/404.md', 'language': 'uk'} for route in routes]}))
        self.assertEqual(manifest, inventory(self.site, 'https://piskor.com.ua', 'revision'))
        self.assertFalse(any(page['route'] == '/404.html?lang=uk' for page in manifest['pages']))

    @unittest.skipUnless(Path('output/lcp-stable/production/psi-public-response.html').is_file(), 'Existing real PSI HTML fixture is local-only')
    def test_existing_real_public_psi_cache_without_copying_large_fixture(self):
        reports = extract_public_reports(Path('output/lcp-stable/production/psi-public-response.html').read_text())
        self.assertEqual(set(reports), {'mobile', 'desktop'})
        summary = summarize_lhr(reports['mobile'], 'https://piskor.com.ua/portfolio/', 'mobile')
        self.assertEqual(summary['validation_errors'], [])
        self.assertEqual(summary['metrics']['lcp'], 1201)
        self.assertEqual(summary['agentic']['weighted_total'], 5)
        self.assertEqual(summary['agentic']['weighted_passed'], 5)

    @unittest.skipUnless(Path('output/all-pages/design-preservation/public-ui-iab-087-baseline/public-report.html').is_file(),
                         'Existing moved-slot PSI HTML fixture is local-only')
    def test_current_real_public_psi_report_has_both_actual_modes(self):
        path = Path('output/all-pages/design-preservation/public-ui-iab-087-baseline/public-report.html')
        reports = extract_public_reports(path.read_text())
        self.assertEqual(set(reports), {'mobile', 'desktop'})
        for mode, expected in [('mobile', (932, 1201, 932)), ('desktop', (271, 284, 313.9799054894646))]:
            summary = summarize_lhr(reports[mode], 'https://piskor.com.ua/portfolio/', mode)
            self.assertEqual(summary['validation_errors'], [])
            self.assertEqual(tuple(summary['metrics'][key] for key in ('fcp', 'lcp', 'speed_index')), expected)
            self.assertEqual(summary['agentic']['weighted_passed'], 5)

    def test_five_distinct_current_reports_each_mode_are_required_without_rounding(self):
        self.populate()
        matrix = write_matrix(self.output, self.manifest)
        self.assertTrue(matrix['all_pages_pass'])
        self.assertEqual(matrix['passed_rows'], 2)
        self.assertEqual(matrix['rows'][0]['settings_groups'][0]['metrics']['lcp']['max'], 999.999999)
        failed = lhr(run=6)
        failed['audits']['largest-contentful-paint']['numericValue'] = 1000
        self.save(failed, 'slow-sixth-run')
        matrix = build_matrix(self.manifest, load_records(self.output))
        self.assertFalse(matrix['all_pages_pass'])
        self.assertEqual(matrix['rows'][0]['status'], 'failed-performance')
        self.assertEqual(matrix['rows'][0]['settings_groups'][0]['valid_runs'], 6)

    def test_missing_stale_duplicate_and_mixed_settings_never_pass(self):
        self.assertFalse(build_matrix(self.manifest, [])['all_pages_pass'])
        old = {**self.manifest, 'revision': 'previous-revision'}
        self.populate(old)
        matrix = build_matrix(self.manifest, load_records(self.output))
        self.assertEqual(matrix['rows'][0]['previous_artifact_reports_diagnostic_only'], 5)
        self.assertFalse(matrix['all_pages_pass'])
        for index in range(5):
            self.save(lhr(), 'same-cached-measurement-' + str(index))
        row = build_matrix(self.manifest, load_records(self.output))['rows'][0]
        self.assertEqual(row['settings_groups'][0]['valid_runs'], 1)
        self.assertEqual(row['status'], 'pending')
        different = lhr(run=2)
        different['configSettings']['throttling']['cpuSlowdownMultiplier'] = 4
        self.save(different, 'different-settings')
        self.assertEqual(build_matrix(self.manifest, load_records(self.output))['rows'][0]['status'], 'mixed-settings')

    def test_redirect_http_runtime_missing_metrics_and_old_times_are_not_passes(self):
        mutations = [lambda report: report.update(finalUrl=URL + 'other/'),
                     lambda report: report.update(runtimeError={'code': 'NO_FCP'}),
                     lambda report: report['audits'].pop('speed-index'),
                     lambda report: report['audits']['network-requests']['details']['items'][0].update(statusCode=404),
                     lambda report: report['audits'].pop('network-requests'),
                     lambda report: report.update(fetchTime='2026-10-18T12:00:00Z')]
        for index, mutate in enumerate(mutations):
            report = lhr(run=index)
            mutate(report)
            self.save(report, 'invalid-' + str(index))
        row = build_matrix(self.manifest, load_records(self.output))['rows'][0]
        self.assertEqual(row['status'], 'invalid-evidence')
        self.assertEqual(row['settings_groups'][0]['valid_runs'], 0)
        self.assertEqual(len(row['settings_groups'][0]['invalid_reports']), len(mutations))
        unverified = {**self.manifest, 'deployed_at': None}
        self.assertFalse(build_matrix(unverified, load_records(self.output))['all_pages_pass'])

    def test_agentic_uses_actual_weights_and_reports_unweighted_na_missing(self):
        report = lhr()
        coverage = agentic_coverage(report)
        self.assertEqual(coverage['status'], 'passed')
        self.assertEqual(coverage['weighted_total'], 2)
        self.assertEqual([audit['status'] for audit in coverage['audits']], ['passed', 'failed', 'not-applicable'])
        report['audits'].pop('weighted')
        self.assertEqual(agentic_coverage(report)['status'], 'missing')
        report['audits']['weighted'] = {'score': True}
        self.assertEqual(agentic_coverage(report)['status'], 'missing')
        self.assertEqual(agentic_coverage({})['status'], 'missing')

    def test_api_is_not_called_without_key_and_stops_on_quota_without_retry(self):
        with patch.dict(os.environ, {}, clear=True), patch('collect_pagespeed.api_request') as request:
            matrix = collect(self.output, self.manifest, 5, 1000)
            request.assert_not_called()
            self.assertFalse(matrix['all_pages_pass'])
        with patch.dict(os.environ, {'PAGESPEED_API_KEY': 'secret-do-not-log'}), patch('collect_pagespeed.api_request', return_value=(None, {'status': 429, 'reason': 'quota-exhausted'})) as request:
            collect(self.output, self.manifest, 5, 1000)
            self.assertEqual(request.call_count, 1)
            collect(self.output, self.manifest, 5, 1000)
            self.assertEqual(request.call_count, 1)
        self.assertNotIn('secret-do-not-log', (self.output / 'collection-stop.json').read_text())

    def test_collector_resumes_completed_cohort_without_network_or_slow_run_retries(self):
        self.populate()
        with patch.dict(os.environ, {'PAGESPEED_API_KEY': 'secret'}), patch('collect_pagespeed.api_request') as request:
            matrix = collect(self.output, self.manifest, 5, 1000)
            request.assert_not_called()
            self.assertTrue(matrix['all_pages_pass'])

    def test_api_sanitizes_http_and_network_errors(self):
        from urllib.error import HTTPError, URLError
        key = 'secret-do-not-log'
        with patch('collect_pagespeed.urlopen', side_effect=HTTPError('https://example/?key=' + key, 429, key, {}, None)):
            _, error = api_request(URL, 'mobile', key)
            self.assertEqual(error, {'status': 429, 'reason': 'quota-exhausted'})
        with patch('collect_pagespeed.urlopen', side_effect=URLError(key)):
            _, error = api_request(URL, 'mobile', key)
            self.assertNotIn(key, json.dumps(error))

    def test_api_requests_official_five_categories_and_checks_actual_agentic_response(self):
        # Offline snapshot of the official v5 Discovery revision 20261013,
        # checked 2026-10-18; no runPagespeed call is made by this fixture.
        discovery_categories = {'CATEGORY_UNSPECIFIED', 'ACCESSIBILITY', 'BEST_PRACTICES',
                                'PERFORMANCE', 'PWA', 'SEO', 'AGENTIC_BROWSING'}
        response = BytesIO(json.dumps({'lighthouseResult': lhr()}).encode())
        with patch('collect_pagespeed.urlopen', return_value=response) as request:
            report, error = api_request(URL, 'mobile', 'secret-do-not-log')
        query = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
        self.assertEqual(query['category'], ['PERFORMANCE', 'ACCESSIBILITY', 'BEST_PRACTICES', 'SEO', 'AGENTIC_BROWSING'])
        self.assertTrue(set(query['category']).issubset(discovery_categories))
        self.assertNotIn('PWA', query['category'])
        self.assertIsNone(error)
        self.assertEqual(agentic_coverage(report)['status'], 'passed')

        partial = lhr()
        partial['categories'].pop('agentic-browsing')
        with patch('collect_pagespeed.urlopen', return_value=BytesIO(json.dumps({'lighthouseResult': partial}).encode())):
            report, error = api_request(URL, 'mobile', 'secret-do-not-log')
        self.assertIsNone(error)
        record = self.save(report, 'partial-api-response')
        self.assertEqual(record['agentic']['status'], 'missing')
        row = build_matrix(self.manifest, [record], runs=1)['rows'][0]
        self.assertEqual(row['status'], 'failed-or-missing-agentic')


if __name__ == '__main__':
    unittest.main()
