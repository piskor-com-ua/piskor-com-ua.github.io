"""Offline transport-contract tests: no public requests."""
import importlib.util
from pathlib import Path
import tempfile
import json
import unittest

spec = importlib.util.spec_from_file_location('delivery', Path(__file__).with_name('check-agent-delivery.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ORIGIN = 'https://piskor.com.ua'
LINK = ', '.join(f'<{path}>; rel="{rel}"; type="{mime}"' for path, rel, mime in sorted(m.DISCOVERY))


def headers(mime='text/markdown'):
    return [('Content-Type', mime + '; charset=utf-8'), ('Vary', 'Accept'),
            ('Content-Signal', 'ai-input=yes, ai-train=no, search=yes'),
            ('X-Robots-Tag', 'noindex, nofollow'), ('Link', LINK)]


class Delivery(unittest.TestCase):
    def setUp(self):
        self.case = dict(route='/en/', file='agent-markdown/en/index.md', mime='text/markdown',
                         accepts=['text/markdown'], method='GET', kind='negotiated',
                         markdown='/agent-markdown/en/index.md')
        self.calls = []

    def run_responses(self, responses, **kwargs):
        def fetch(url, method, accepts, timeout):
            self.calls.append((url, method, accepts))
            status, pairs, body = responses[len(self.calls) - 1]
            return dict(url=url, method=method, status=status, headers=pairs, body=body)
        return m.verify(self.case, ORIGIN, b'# English\n', fetch=fetch, **kwargs)

    def test_exact_direct_negotiation(self):
        row = self.run_responses([(200, headers(), b'# English\n')])
        self.assertTrue(row['pass_'])
        self.assertEqual(len(self.calls), 1)

    def test_worker_acceptance_requires_exact_version_and_no_store(self):
        revision = 'a' * 40
        for extra, expected_issues in [
            ([], {'markdown-worker-version', 'markdown-worker-no-store'}),
            ([('X-Piskor-Markdown-Version', 'b' * 40), ('Cache-Control', 'no-store')], {'markdown-worker-version'}),
            ([('X-Piskor-Markdown-Version', revision)] * 2 + [('Cache-Control', 'no-store')], {'markdown-worker-version'}),
            ([('X-Piskor-Markdown-Version', revision), ('Cache-Control', 'max-age=600')], {'markdown-worker-no-store'}),
            ([('X-Piskor-Markdown-Version', revision), ('Cache-Control', 'no-store'), ('CF-Cache-Status', 'HIT')], {'markdown-worker-unexpected-hit'}),
        ]:
            with self.subTest(extra=extra):
                self.calls = []
                result = self.run_responses([(200, headers() + extra, b'# English\n')], expected_markdown_version=revision)
                self.assertEqual(set(result['issues']), expected_issues)
                self.assertFalse(result['pass_'])

    def test_generated_worker_response_need_not_have_origin_cache_status(self):
        self.case['cache_probe'] = True
        revision = 'a' * 40
        result = self.run_responses([(200, headers() + [('X-Piskor-Markdown-Version', revision),
                                   ('Cache-Control', 'no-store')], b'# English\n')], expected_markdown_version=revision)
        self.assertTrue(result['pass_'], result['issues'])

    def test_empty_or_invalid_worker_version_cannot_disable_ownership_checks(self):
        for revision in ('', 'a' * 39, 'A' * 40, 123):
            with self.subTest(revision=revision):
                result = self.run_responses([], expected_markdown_version=revision)
                self.assertFalse(result['pass_'])
                self.assertEqual(self.calls, [])
                self.assertIn('Expected Markdown version must be a complete Git SHA', result['issues'])

    def test_single_exact_307_preserves_head(self):
        self.case['method'] = 'HEAD'
        row = self.run_responses([(307, [('Location', self.case['markdown'])], b''),
                                  (200, headers(), b'')], allow_redirects=True)
        self.assertTrue(row['pass_'])
        self.assertEqual([x[1] for x in self.calls], ['HEAD', 'HEAD'])
        self.assertIsNone(row['comparison'])

    def test_off_origin_or_wrong_locale_never_followed(self):
        for target in ['https://evil.test/agent-markdown/en/index.md', '/agent-markdown/index.md',
                       '/agent-markdown/en/index.md?extra=1']:
            with self.subTest(target=target):
                self.calls = []
                row = self.run_responses([(307, headers() + [('Location', target)], b'')], allow_redirects=True)
                self.assertFalse(row['pass_'])
                self.assertEqual(len(self.calls), 1)


    def test_307_query_is_preserved_exactly(self):
        self.case['route'] = '/404.html?lang=en'
        self.case['markdown'] = '/agent-markdown/404-en.md'
        target = self.case['markdown'] + '?lang=en'
        row = self.run_responses([(307, [('Location', target)], b''),
                                  (200, headers(), b'# English\n')], allow_redirects=True)
        self.assertTrue(row['pass_'])
        self.assertEqual(self.calls[1][0], ORIGIN + target)
        for wrong in [self.case['markdown'], target + '&other=1', self.case['markdown'] + '?lang=uk']:
            self.calls = []
            self.assertFalse(self.run_responses([(307, [('Location', wrong)], b'')], allow_redirects=True)['pass_'])
            self.assertEqual(len(self.calls), 1)

    def test_html_alternate_is_required_from_actual_artifact(self):
        body = b'<link rel="alternate" type="text/markdown" href="/agent-markdown/404.md">'
        case = dict(self.case, mime='text/html', kind='html')
        def fetch(url, method, accepts, timeout):
            return dict(url=url, method=method, status=200, headers=headers('text/html'), body=body)
        self.assertTrue(m.verify(case, ORIGIN, body, fetch=fetch)['pass_'])
        missing = b'<html></html>'
        def no_alternate(url, method, accepts, timeout):
            return dict(url=url, method=method, status=200, headers=headers('text/html'), body=missing)
        self.assertIn('html-markdown-alternate', m.verify(case, ORIGIN, missing, fetch=no_alternate)['issues'])


    def test_true404_policy_not200_and_exact_optional_directory_redirect(self):
        body = b'<meta name="robots" content="noindex, nofollow"><link rel="alternate" type="text/markdown" href="/agent-markdown/404.md">'
        case = dict(self.case, route='/missing/', kind='true-404', mime='text/html', status=404)
        case.pop('markdown')
        seen = []
        def fetch(url, method, accepts, timeout):
            seen.append(url)
            if len(seen) == 1:
                return dict(status=307, headers=[('Location', '/agent-markdown/missing/index.md')], body=b'')
            return dict(status=404, headers=[('Content-Type', 'text/html')], body=body)
        row = m.verify(case, ORIGIN, body, allow_redirects=True, fetch=fetch)
        self.assertTrue(row['pass_'], row['issues'])
        self.assertEqual(len(seen), 2)
        # The directory fallback contract excludes query and percent-encoded paths.
        for route in ['/missing/?lang=en', '/missing%20encoded/']:
            queried = dict(case, route=route)
            def excluded_redirect(url, method, accepts, timeout):
                return dict(status=307, headers=[('Location', '/agent-markdown/missing/index.md')], body=b'')
            self.assertFalse(m.verify(queried, ORIGIN, body, allow_redirects=True, fetch=excluded_redirect)['pass_'])
        def wrong_target(url, method, accepts, timeout):
            return dict(status=307, headers=[('Location', '/agent-markdown/404.md?lang=en')], body=b'')
        self.assertFalse(m.verify(case, ORIGIN, body, allow_redirects=True, fetch=wrong_target)['pass_'])
        head_case = dict(case, method='HEAD')
        def head404(url, method, accepts, timeout):
            return dict(status=404, headers=[('Content-Type', 'text/html')], body=b'')
        self.assertTrue(m.verify(head_case, ORIGIN, body, fetch=head404)['pass_'])
        def soft404(url, method, accepts, timeout):
            return dict(status=200, headers=[('Content-Type', 'text/html')], body=body)
        self.assertFalse(m.verify(case, ORIGIN, body, fetch=soft404)['pass_'])

    def test_head_body_rejected(self):
        self.case['method'] = 'HEAD'
        self.assertIn('head-body-not-empty', self.run_responses([(200, headers(), b'illegal')])['issues'])

    def test_cache_positive_redirect_needs_vary_accept(self):
        for cc, vary, passing in [('public,max-age=60', None, False),
                                  ('public,max-age=60', 'Accept', True),
                                  ('max-age="600"', None, False),
                                  ('s-maxage="600"', None, False),
                                  ('x-max-age=600', None, True),
                                  ('max-age=600,no-cache="X-Optional"', None, False),
                                  ('max-age=600,no-cache', None, True),
                                  ('no-store', None, True)]:
            self.calls = []
            pairs = [('Location', self.case['markdown']), ('Cache-Control', cc)]
            if vary:
                pairs.append(('Vary', vary))
            row = self.run_responses([(307, pairs, b''), (200, headers(), b'# English\n')], allow_redirects=True)
            self.assertEqual(row['pass_'], passing, row['issues'])
        self.calls = []
        row = self.run_responses([(307, [('Location', self.case['markdown']), ('Cache-Control', 'no-store'),
                                        ('CF-Cache-Status', 'HIT')], b''),
                                  (200, headers(), b'# English\n')], allow_redirects=True)
        self.assertFalse(row['pass_'])

    def test_loop_stops_after_one_hop(self):
        row = self.run_responses([(307, headers() + [('Location', self.case['markdown'])], b''),
                                  (307, headers() + [('Location', '/en/')], b'')], allow_redirects=True)
        self.assertFalse(row['pass_'])
        self.assertEqual(len(self.calls), 2)

    def test_redirect_disallowed_by_default(self):
        row = self.run_responses([(307, headers() + [('Location', self.case['markdown'])], b'')])
        self.assertFalse(row['pass_'])
        self.assertEqual(len(self.calls), 1)

    def test_final_bytes_and_mime_are_required(self):
        for pairs, body in [(headers(), b'# Wrong\n'), (headers('text/html'), b'# English\n')]:
            self.calls = []
            row = self.run_responses([(307, headers() + [('Location', self.case['markdown'])], b''),
                                      (200, pairs, body)], allow_redirects=True)
            self.assertFalse(row['pass_'])

    def test_only_one_exact_html_injection_allowed(self):
        for raw, html, equal in [(b'pageBLOB', True, True), (b'pageBLOBBLOB', True, False),
                                  (b'pageOTHER', True, False), (b'pageBLOB', False, False),
                                  (b'page', True, True)]:
            self.assertEqual(m.compare(raw, b'page', b'BLOB', html)['compared_byte_equal'], equal)
        self.assertIsNone(m.compare(b'page', b'page', b'BLOB', True)['transformation'])

    def test_policy_ambiguity_and_missing_link_fail(self):
        for changed in [headers() + [('Content-Signal', 'ai-train=yes')],
                        [(k, v) for k, v in headers() if k != 'Link'],
                        [(k, v) for k, v in headers() if k != 'Vary']]:
            self.assertTrue(m.policy(changed, ORIGIN))
        self.calls = []
        self.assertFalse(self.run_responses([(200, headers() + [('Content-Type', 'text/html')], b'# English\n')])['pass_'])

    def test_duplicate_accept_is_preserved_and_cache_hit_fails(self):
        self.case['accepts'] = ['text/markdown', 'text/markdown']
        self.case['cache_probe'] = True
        row = self.run_responses([(200, headers() + [('CF-Cache-Status', 'HIT')], b'# English\n')])
        self.assertEqual(self.calls[0][2], ['text/markdown', 'text/markdown'])
        self.assertFalse(row['pass_'])

    def test_real_inventory_jobs_preserve_404_en_query_and_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            routes = ['/', '/en/', '/portfolio/', '/en/portfolio/', '/404.html', '/404.html?lang=en']
            rows = []
            for index, route in enumerate(routes):
                md = f'/agent-markdown/{index}.md'
                target = site / md.lstrip('/')
                target.parent.mkdir(exist_ok=True)
                target.write_text('# Text')
                path = route.split('?')[0].lstrip('/')
                html = site / (path + 'index.html' if route.endswith('/') else path)
                html.parent.mkdir(parents=True, exist_ok=True)
                html.write_text('<html>')
                rows.append(dict(url=route, markdown=md))
            (site / 'agent-markdown/routes.json').write_text(json.dumps(dict(pages=rows)))
            cases, sequence = m.jobs(site.resolve())
            en = [x for x in cases if x['route'] == '/404.html?lang=en' and x['kind'] == 'negotiated']
            self.assertEqual({x['method'] for x in en}, {'GET', 'HEAD'})
            self.assertTrue(all(x['file'] == 'agent-markdown/5.md' for x in en))
            self.assertEqual([x['mime'] for x in sequence[:3]], ['text/markdown', 'text/html', 'text/markdown'])


if __name__ == '__main__':
    unittest.main()
