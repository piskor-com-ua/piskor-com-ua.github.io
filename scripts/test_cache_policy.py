import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cache_policy import inventory, purge_plan, public_urls, write_report, POLICY


class CachePolicyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name) / 'site'
        self.site.mkdir()
        (self.site / '.nojekyll').touch()
        (self.site / 'assets').mkdir()
        (self.site / 'assets/photo.webp').write_bytes(b'public-image-fixture')
        self.media_hash = hashlib.sha256(b'public-image-fixture').hexdigest()[:12]
        (self.site / 'app.js').write_text('/* public script */')
        self.code_hash = hashlib.sha256((self.site / 'app.js').read_bytes()).hexdigest()[:12]
        self.html = (f'<html><head><script src="/app.js?v={self.code_hash}"></script></head>'
                     f'<body><img src="/assets/photo.webp?v={self.media_hash}"></body></html>')
        (self.site / 'index.html').write_text(self.html)

    def test_versions_cover_media_and_code_without_modifying_the_artifact(self):
        original = {p.relative_to(self.site).as_posix(): p.read_bytes() for p in self.site.rglob('*') if p.is_file()}
        report = inventory(self.site)
        self.assertEqual(len(report['versioned_urls']), 2)
        self.assertEqual(report['files']['index.html']['dependencies'], ['app.js', 'assets/photo.webp'])
        self.assertEqual(original, {p.relative_to(self.site).as_posix(): p.read_bytes() for p in self.site.rglob('*') if p.is_file()})

    def test_missing_or_stale_content_versions_fail_before_a_release_plan(self):
        for reference in ['/assets/photo.webp', '/assets/photo.webp?v=old', '/assets/photo.webp?v=' + self.media_hash + '&v=duplicate']:
            (self.site / 'index.html').write_text('<img src="' + reference + '">')
            with self.assertRaisesRegex(ValueError, 'incorrect-content-version'):
                inventory(self.site)
        (self.site / 'index.html').write_text('<img src="/assets/missing.webp?v=000000000000">')
        with self.assertRaisesRegex(ValueError, 'missing-resource'):
            inventory(self.site)

    def test_new_changed_deleted_resources_and_render_consumers_are_targeted(self):
        before = inventory(self.site, 'before')
        (self.site / 'assets/photo.webp').write_bytes(b'new-image')
        media_hash = hashlib.sha256(b'new-image').hexdigest()[:12]
        (self.site / 'index.html').write_text(self.html.replace(self.media_hash, media_hash))
        (self.site / 'new.html').write_text('<h1>New page</h1>')
        after = inventory(self.site, 'after')
        plan = purge_plan(after, before)
        urls = {url for batch in plan['url_batches'] for url in batch}
        self.assertIn('https://piskor.com.ua/', urls)
        self.assertIn('https://piskor.com.ua/index.html', urls)
        self.assertIn('https://piskor.com.ua/assets/photo.webp', urls)
        self.assertIn('https://piskor.com.ua/new.html', urls)
        self.assertNotIn('app.js', plan['affected_files'])
        (self.site / 'new.html').unlink()
        deleted = purge_plan(inventory(self.site), after)
        self.assertIn('https://piskor.com.ua/new.html', {url for batch in deleted['url_batches'] for url in batch})

    def test_navigation_is_not_a_render_dependency_and_unchanged_releases_need_no_purge(self):
        (self.site / 'other.html').write_text('<a href="/">Home</a>')
        before = inventory(self.site)
        (self.site / 'index.html').write_text(self.html + '<p>Changed copy</p>')
        after = inventory(self.site)
        self.assertNotIn('other.html', purge_plan(after, before)['affected_files'])
        self.assertEqual(purge_plan(after, after)['url_batches'], [])

    def test_bootstrap_is_explicit_and_keeps_unchanged_image_families_warm(self):
        current = inventory(self.site)
        plan = purge_plan(current)
        self.assertEqual(plan['mode'], 'bootstrap-stable-documents')
        self.assertNotIn('assets/photo.webp', plan['affected_files'])
        self.assertFalse(plan['purge_everything'])
        for batch in plan['url_batches']:
            self.assertLessEqual(len(batch), 30)
        self.assertEqual(public_urls('en/portfolio/index.html'), ['/en/portfolio/', '/en/portfolio/index.html'])

    def test_markdown_custom_cache_keys_require_prefix_purge(self):
        (self.site / 'agent-markdown').mkdir()
        path = self.site / 'agent-markdown/index.md'
        path.write_text('# Original\n')
        before = inventory(self.site)
        path.write_text('# Changed\n')
        plan = purge_plan(inventory(self.site), before)
        self.assertIn('piskor.com.ua/agent-markdown/index.md', plan['markdown_prefixes'])
        self.assertIn('piskor.com.ua/agent-api/mcp.md', plan['markdown_prefixes'])

    def test_policy_change_invalidates_stable_documents_even_when_bytes_are_unchanged(self):
        current = inventory(self.site)
        previous = {**current, 'policy_sha256': 'previous-policy'}
        plan = purge_plan(current, previous)
        self.assertEqual(plan['mode'], 'policy-change-stable-documents')
        self.assertEqual(plan['changed_files'], [])
        self.assertIn('index.html', plan['affected_files'])
        self.assertNotIn('assets/photo.webp', plan['affected_files'])

    def test_revision_changes_refresh_runtime_publications_and_render_dependencies_are_transitive(self):
        (self.site / 'app.js').write_text(f'const image="/assets/photo.webp?v={self.media_hash}";')
        script_hash = hashlib.sha256((self.site / 'app.js').read_bytes()).hexdigest()[:12]
        (self.site / 'index.html').write_text(self.html.replace(self.code_hash, script_hash))
        before = inventory(self.site, 'before')
        revision_only = purge_plan(inventory(self.site, 'after'), before)
        self.assertEqual(revision_only['url_batches'], [])
        self.assertIn('piskor.com.ua/.well-known/mcp/server-card.json', revision_only['markdown_prefixes'])
        self.assertEqual(before['files']['app.js']['dependencies'], ['assets/photo.webp'])
        # The graph must also cover an unchanged direct consumer when a lower
        # dependency changes. Version validation belongs to inventory(), not purge.
        after = json.loads(json.dumps(before))
        after['files']['assets/photo.webp']['sha256'] = 'new-bytes'
        self.assertEqual(purge_plan(after, before)['affected_files'], ['app.js', 'assets/photo.webp', 'index.html'])

    def test_policy_minimum_and_rpc_exclusion_cannot_drift(self):
        policy = json.loads(POLICY.read_text())
        self.assertGreaterEqual(policy['edge_min_ttl'], 2678400)
        self.assertTrue(policy['public_markdown_edge_cache'])
        self.assertFalse(policy['mcp_post_cache'])
        params = policy['public_rule']['patch_action_parameters']
        self.assertEqual(params['edge_ttl']['default'], policy['edge_min_ttl'])
        self.assertEqual(params['browser_ttl']['mode'], 'bypass')
        self.assertIn('{"GET" "HEAD" "PURGE"}', policy['public_rule']['expression'])
        self.assertNotIn('"POST"', policy['public_rule']['expression'])
        worker = (POLICY.parent / 'markdown-worker.mjs').read_text()
        self.assertIn('PUBLIC_EDGE_TTL = ' + str(policy['edge_min_ttl']), worker)

    def test_report_does_not_leak_into_the_public_artifact_and_rejects_wrong_previous_origin(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            write_report(self.site, self.site / 'report')
        current = inventory(self.site)
        with self.assertRaisesRegex(ValueError, 'same origin'):
            purge_plan(current, {**current, 'origin': 'https://other.test'})
        result = write_report(self.site, Path(self.temp.name) / 'report')
        self.assertEqual(result['files'], 4)


if __name__ == '__main__':
    unittest.main()
