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


if __name__ == '__main__':
    unittest.main()
