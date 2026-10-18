import tempfile
import unittest
from pathlib import Path

from optimize_assets import optimize_assets


class OptimizeAssetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / '_site'
        self.output.mkdir()
        (self.output / '.nojekyll').touch()

    def write(self, name, content):
        path = self.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return path

    def test_unused_duplicates_and_all_reference_types(self):
        self.write('assets/photo-1440.webp', b'identical')
        self.write('assets/photo-2200.webp', b'identical')
        self.write('assets/photo-640.webp', b'small')
        self.write('assets/unused.webp', b'unused')
        self.write('assets/Roboto-LICENSE.txt', 'required license')
        self.write('assets/video.mp4', b'video')
        html = self.write('index.html', '<img src="/assets/photo-1440.webp" '
                          'srcset="/assets/photo-640.webp 640w, /assets/photo-2200.webp 2200w">'
                          '<button data-full="/assets/photo-2200.webp?version=1#image"></button>'
                          '<video poster="/assets/photo-2200.webp"><source src="/assets/video.mp4"></video>'
                          '<script type="application/ld+json">{"image":"https://example.com/assets/photo-2200.webp"}</script>')
        css = self.write('site.css', 'body{background:url("assets/photo-2200.webp")}')
        js = self.write('site.js', 'const image="/assets/photo-2200.webp";')
        result = optimize_assets(self.output)
        self.assertEqual(result, {'unused': 1, 'duplicates': 1, 'saved_bytes': 15})
        self.assertFalse((self.output / 'assets/unused.webp').exists())
        self.assertFalse((self.output / 'assets/photo-2200.webp').exists())
        for path in [html, css, js]:
            self.assertNotIn('photo-2200.webp', path.read_text())
        self.assertIn('?version=1#image', html.read_text())
        self.assertTrue((self.output / 'assets/Roboto-LICENSE.txt').exists())
        self.assertTrue((self.output / 'assets/video.mp4').exists())
        self.assertEqual(optimize_assets(self.output)['duplicates'], 0)

    def test_different_images_are_not_merged(self):
        self.write('assets/a.webp', b'a')
        self.write('assets/b.webp', b'b')
        self.write('site.js', 'const images=["/assets/a.webp","/assets/b.webp"];')
        self.assertEqual(optimize_assets(self.output)['duplicates'], 0)

    def test_missing_reference_fails_before_cleanup(self):
        unused = self.write('assets/unused.webp', b'unused')
        self.write('index.html', '<img srcset="/assets/missing.webp 640w">')
        with self.assertRaisesRegex(ValueError, 'Missing'):
            optimize_assets(self.output)
        self.assertTrue(unused.exists())

    def test_source_directory_is_rejected(self):
        (self.output / '.nojekyll').unlink()
        with self.assertRaises(ValueError):
            optimize_assets(self.output)

    def test_symlink_outside_artifact_is_rejected(self):
        external = Path(self.temp.name) / 'original.webp'
        external.write_bytes(b'original')
        (self.output / 'assets').mkdir()
        (self.output / 'assets/link.webp').symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            optimize_assets(self.output)
        self.assertEqual(external.read_bytes(), b'original')

    def test_distinct_formats_are_not_merged(self):
        self.write('assets/a.webp', b'identical')
        self.write('assets/b.png', b'identical')
        self.write('index.html', '<img src="/assets/a.webp"><img src="/assets/b.png">')
        self.assertEqual(optimize_assets(self.output)['duplicates'], 0)

    def test_new_derivatives_reuse_legacy_urls_for_cached_html(self):
        legacy = 'assets/responsive/portfolio/case/cover-640.avif'
        derivative = 'assets/responsive/case-media/portfolio/case/cover-640.avif'
        self.write(legacy, b'same published image')
        self.write(derivative, b'same published image')
        html = self.write('index.html', '<source srcset="/' + legacy + ' 640w"><source srcset="/' + derivative + ' 640w">')
        self.assertEqual(optimize_assets(self.output)['duplicates'], 1)
        self.assertTrue((self.output / legacy).is_file())
        self.assertFalse((self.output / derivative).exists())
        self.assertEqual(html.read_text().count('/' + legacy), 2)

    def test_new_cover_profile_never_displaces_existing_gallery_home_or_catalog_url(self):
        existing = [
            'assets/responsive/case-media/portfolio/case/photo-640.avif',
            'assets/responsive/home-media/home-960.avif',
            'assets/responsive/portfolio/catalog/cover-640.avif',
        ]
        new = []
        for index, old in enumerate(existing):
            fresh = 'assets/responsive/case-cover/profile-' + str(index) + '.avif'
            payload = ('identical pair ' + str(index)).encode()
            self.write(old, payload)
            self.write(fresh, payload)
            new.append(fresh)
        html = self.write('index.html', ''.join('<source srcset="/' + url + ' 640w">' for url in existing + new))
        self.assertEqual(optimize_assets(self.output)['duplicates'], 3)
        for old, fresh in zip(existing, new):
            self.assertTrue((self.output / old).is_file())
            self.assertFalse((self.output / fresh).exists())
            self.assertEqual(html.read_text().count('/' + old), 2)

    def test_compact_first_card_preserves_unreferenced_published_avif_bytes(self):
        old = self.write('assets/responsive/portfolio/rok/cover-480.avif', b'published q60')
        compact = self.write('assets/responsive/case-cover/compact-full/catalog/rok-448.avif', b'new q45')
        # The new HTML no longer references its formerly eager card source.
        html = self.write('index.html', '<source srcset="/' + compact.relative_to(self.output).as_posix() + ' 448w">')
        unused_new = self.write('assets/responsive/case-cover/unused.avif', b'unused new profile')
        optimize_assets(self.output)
        self.assertEqual(old.read_bytes(), b'published q60')
        self.assertEqual(compact.read_bytes(), b'new q45')
        self.assertNotIn('/' + old.relative_to(self.output).as_posix(), html.read_text())
        self.assertFalse(unused_new.exists())

    def test_legacy_retention_does_not_promote_unused_names_or_remove_old_aliases(self):
        unused = self.write('assets/responsive/aaa-unused.avif', b'same bytes')
        first = self.write('assets/responsive/portfolio/b-first.avif', b'same bytes')
        second = self.write('assets/responsive/portfolio/c-second.avif', b'same bytes')
        fresh = self.write('assets/responsive/case-cover/new.avif', b'same bytes')
        urls = [p.relative_to(self.output).as_posix() for p in (first, second, fresh)]
        html = self.write('index.html', ''.join('<source srcset="/' + url + ' 480w">' for url in urls))
        self.assertEqual(optimize_assets(self.output)['duplicates'], 1)
        self.assertNotIn('aaa-unused', html.read_text())
        self.assertEqual(html.read_text().count('/' + urls[0]), 3)
        for old in (unused, first, second):
            self.assertEqual(old.read_bytes(), b'same bytes')
        self.assertFalse(fresh.exists())
        self.assertEqual(optimize_assets(self.output)['duplicates'], 0)


if __name__ == '__main__':
    unittest.main()
