import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from mobile_image_delivery import (_profile_picture, load_findings,
                                   mobile_css_image_width)


class MobileImageDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / '_site'
        self.output.mkdir()
        (self.output / '.nojekyll').touch()
        self.assets = self.output / 'assets'
        self.assets.mkdir()

    def image(self, relative, size, image_format, quality=70):
        path = self.assets / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', size, '#817467').save(path, image_format, quality=quality)
        return path

    def test_checked_in_manifest_is_complete_and_fixed_to_the_baseline(self):
        manifest = load_findings()
        self.assertEqual(manifest['route_count'], 22)
        self.assertEqual(manifest['baseline_finding_count'], 39)
        self.assertEqual(manifest['finding_count'], 40)
        self.assertEqual(manifest['supplemental_audit']['additional_findings'], 1)
        self.assertEqual(manifest['supplemental_audit']['routes_checked'], 22)
        self.assertEqual(len({item['resource_path'] for items in manifest['routes'].values()
                              for item in items}), 34)

    def test_mobile_size_calculation_uses_the_measured_viewport(self):
        self.assertEqual(mobile_css_image_width(
            '(max-width: 700px) calc(100vw - 48px), (min-width: 1956px) 50vw'), 364)
        self.assertAlmostEqual(mobile_css_image_width(
            '(max-width: 700px) calc(115.72917vw - 55.55px), 50vw'), 421.255, places=2)
        self.assertAlmostEqual(mobile_css_image_width(
            '(max-width: 700px) max(calc(100vw - 48px), min(96vw, 973.33333px)), 91vw'),
            395.52, places=2)

    def test_downsizes_to_the_emulated_dpr_and_updates_the_preload(self):
        self.image('portfolio/test/photo-1440.webp', (1440, 960), 'WEBP')
        self.image('responsive/case-media/portfolio/test/photo-640.avif', (640, 427), 'AVIF')
        self.image('responsive/case-media/portfolio/test/photo-960.avif', (960, 640), 'AVIF')
        route = '/portfolio/test/'
        resource = '/assets/responsive/case-media/portfolio/test/photo-960.avif'
        sizes = '(max-width: 700px) calc(100vw - 48px), 50vw'
        srcset = ('/assets/responsive/case-media/portfolio/test/photo-640.avif 640w, '
                  '/assets/responsive/case-media/portfolio/test/photo-960.avif 960w')
        picture = ('<picture><source type="image/avif" media="(max-width: 700px)" '
                   'srcset="' + srcset + '" sizes="' + sizes + '"><img '
                   'src="/assets/portfolio/test/photo-1440.webp" '
                   'srcset="/assets/portfolio/test/photo-1440.webp 1440w" '
                   'width="1440" height="960"></picture>')
        preload = ('<link rel="preload" as="image" imagesrcset="' + srcset + '" '
                   'imagesizes="' + sizes + '">')
        html = '<head>' + preload + '</head>' + picture
        manifest = {'emulation': {'viewport_width_css_px': 412, 'device_scale_factor': 1.75}}

        amended, width, quality = _profile_picture(self.output, route, html, picture,
                                                  resource, manifest)

        self.assertEqual(width, 637)
        self.assertEqual(quality, 60)
        self.assertIn('photo-637-q60.avif 637w', amended)
        self.assertIn('imagesrcset="' + amended.split('srcset="', 1)[1].split('"', 1)[0] + '"', amended)
        candidate = self.assets / 'responsive/case-media/portfolio/test/photo-637-q60.avif'
        self.assertTrue(candidate.is_file())
        with Image.open(candidate) as image:
            self.assertEqual(image.size, (637, 425))

    def test_keeps_resolution_and_uses_recompression_when_selected_size_is_already_dpr_sized(self):
        self.image('portfolio/test/photo-1440.webp', (1440, 960), 'WEBP')
        self.image('responsive/case-media/portfolio/test/photo-640.avif', (640, 427), 'AVIF')
        resource = '/assets/responsive/case-media/portfolio/test/photo-640.avif'
        srcset = resource + ' 640w'
        picture = ('<picture><source type="image/avif" srcset="' + srcset + '" '
                   'sizes="(max-width: 700px) calc(100vw - 48px), 50vw"><img '
                   'src="/assets/portfolio/test/photo-1440.webp" '
                   'srcset="/assets/portfolio/test/photo-1440.webp 1440w"></picture>')
        manifest = {'emulation': {'viewport_width_css_px': 412, 'device_scale_factor': 1.75}}

        amended, width, quality = _profile_picture(self.output, '/portfolio/test/', picture,
                                                  picture, resource, manifest)

        self.assertEqual(width, 637)
        self.assertEqual(quality, 45)
        self.assertIn('photo-637-q45.avif 637w', amended)
        self.assertIn('photo-640.avif 640w', amended)

    def test_steps_down_quality_until_the_critical_psi_savings_threshold_is_met(self):
        self.image('portfolio/test/photo-1440.webp', (1440, 960), 'WEBP')
        self.image('responsive/case-media/portfolio/test/photo-640.avif', (640, 427), 'AVIF')
        resource = '/assets/responsive/case-media/portfolio/test/photo-640.avif'
        sizes = '(max-width: 700px) calc(100vw - 48px), 50vw'
        picture = ('<picture><source type="image/avif" srcset="' + resource + ' 640w" '
                   'sizes="' + sizes + '"><img src="/assets/portfolio/test/photo-1440.webp" '
                   'srcset="/assets/portfolio/test/photo-1440.webp 1440w"></picture>')
        manifest = {'emulation': {'viewport_width_css_px': 412, 'device_scale_factor': 1.75}}
        finding = {'reported_display_dimensions_px': [364, 243]}

        with patch('mobile_image_delivery._psi_image_delivery_savings', side_effect=[
                (0, 13_000, 12_288), (0, 10_000, 12_288)]) as savings:
            amended, width, quality = _profile_picture(
                self.output, '/portfolio/test/', picture, picture, resource, manifest, finding)

        self.assertEqual(savings.call_count, 2)
        self.assertEqual((width, quality), (637, 42))
        self.assertIn('photo-637-q42.avif 637w', amended)
        self.assertNotIn('photo-637-q45.avif', amended)


if __name__ == '__main__':
    unittest.main()
