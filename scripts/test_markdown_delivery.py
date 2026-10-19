import unittest

from prepare_markdown_delivery import prepare_diagnostic


class BoundedDiagnosticTests(unittest.TestCase):
    def test_expiry_is_literal_and_no_request_value_is_interpolated_into_filter(self):
        prepared = prepare_diagnostic(1800000000, 120)
        expression = prepared['rule']['expression']
        self.assertIn('http.request.timestamp.sec ge 1800000000', expression)
        self.assertIn('http.request.timestamp.sec lt 1800000120', expression)
        self.assertNotIn('START_SECOND', expression)
        self.assertNotIn('END_SECOND', expression)
        self.assertEqual(prepared['status'], 'prepared_not_applied')
        self.assertEqual(prepared['duration_seconds'], 120)
        self.assertIn('raw.http.request.uri.path in {"" "/"}', expression)
        self.assertIn('raw.http.request.uri.query eq ""', expression)
        mime = prepared['rule']['action_parameters']['headers']['content-type']['expression']
        self.assertIn('md1-1800000000', mime)
        self.assertNotIn('START_SECOND', mime)
        self.assertTrue(mime.startswith('concat("text/html; charset=utf-8;'))
        self.assertIn('piskor-raw-accept', mime)
        self.assertIn('join(raw.http.request.headers["accept"], "|")', mime)

    def test_refuses_unbounded_or_invalid_window(self):
        for start, duration in [(0, 180), (-1, 180), (True, 180), (1800000000, 0),
                                (1800000000, 181), (1800000000, -1), (1800000000, True)]:
            with self.subTest(start=start, duration=duration), self.assertRaises(ValueError):
                prepare_diagnostic(start, duration)

    def test_rendering_does_not_mutate_template_or_reuse_previous_window(self):
        first = prepare_diagnostic(1800000000)
        second = prepare_diagnostic(1800001000, 1)
        self.assertIn('lt 1800000180', first['rule']['expression'])
        self.assertIn('lt 1800001001', second['rule']['expression'])

    def test_root_trial_never_reconstructs_accept_or_expands_the_path(self):
        trial = prepare_diagnostic(1800000000, 120, 'root_trial')
        rule = trial['rule']
        for guard in ['raw.http.request.uri.path eq "/"', 'raw.http.request.uri.query eq ""',
                      'http.request.uri.path eq "/"', 'http.request.uri.query eq ""',
                      'len(http.request.headers["accept"]) eq 1',
                      'http.request.headers["accept"][0] eq "text/markdown"',
                      'http.request.timestamp.sec ge 1800000000',
                      'http.request.timestamp.sec lt 1800000120']:
            self.assertIn(guard, rule['expression'])
        self.assertNotIn('http.user_agent', rule['expression'])
        parameters = rule['action_parameters']['from_value']
        self.assertEqual(parameters['status_code'], 307)
        self.assertEqual(parameters['target_url']['value'], 'https://piskor.com.ua/agent-markdown/index.md')
        self.assertTrue(parameters['preserve_query_string'])
        with self.assertRaises(ValueError):
            prepare_diagnostic(1800000000, kind='full_rollout')


if __name__ == '__main__':
    unittest.main()
