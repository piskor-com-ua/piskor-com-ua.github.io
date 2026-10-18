"""Offline tests only; no Google requests, browser or Lighthouse invocation."""
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from collect_pagespeed import (agentic_coverage, api_request, build_matrix, collect,
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


class PagespeedEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        (self.site / 'index.html').write_text('<h1>Public page</h1>')
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

    def test_inventory_keeps_aliases_404_and_exact_nonindex_names(self):
        (self.site / '404.html').write_text('<h1>Not found</h1>')
        (self.site / 'homeindex.html').write_text('<h1>Not an index filename</h1>')
        (self.site / 'old').mkdir()
        (self.site / 'old/index.html').write_text('<meta http-equiv="refresh" content="0;url=/new/">')
        manifest = inventory(self.site, 'https://piskor.com.ua', 'revision')
        self.assertEqual({page['route'] for page in manifest['pages']}, {'/', '/404.html', '/homeindex.html', '/old/'})
        self.assertTrue(next(page for page in manifest['pages'] if page['route'] == '/old/')['redirect_hint'])
        self.assertEqual(manifest, inventory(self.site, 'https://piskor.com.ua', 'revision'))
        (self.site / 'index.html').write_text('changed artifact')
        self.assertNotEqual(manifest['artifact_hash'], inventory(self.site, 'https://piskor.com.ua', 'revision')['artifact_hash'])

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


if __name__ == '__main__':
    unittest.main()
