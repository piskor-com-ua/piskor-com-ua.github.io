from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from deferred_mobile_media import lcp_target_routes
from mobile_lcp_cover_delivery import (MARKER, WIDTH, _insert_candidate, _prepare_page,
                                       restore_mobile_lcp_cover, validate_mobile_lcp_cover)

ROUTE = '/en/portfolio/2020/sholts-restaurant-drohobych/'
IMAGE = '/assets/portfolio/sholts-restaurant-drohobych/vaults-01-1440.webp'
AVIF = ('/assets/responsive/case-cover/portfolio/sholts-restaurant-drohobych/'
        'vaults-01-640.avif 640w, /assets/responsive/case-cover/portfolio/'
        'sholts-restaurant-drohobych/vaults-01-960.avif 960w')
SIZES = '(max-width: 700px) 100vw, 50vw'
HTML = ('<!doctype html><html><head><link rel="preload" as="image" type="image/avif" '
        'media="(max-width: 700px)" imagesrcset="' + AVIF + '" imagesizes="' + SIZES +
        '" fetchpriority="high" data-case-cover-preload></head><body>'
        '<figure class="project-cover"><picture><source type="image/avif" '
        'media="(max-width: 700px)" srcset="' + AVIF + '" sizes="' + SIZES + '">'
        '<img src="' + IMAGE + '" width="1440" height="936" alt="Restaurant interior" '
        'fetchpriority="high"></picture></figure></body></html>')


class MobileLcpCoverDeliveryTests(unittest.TestCase):
    def test_profile_adds_the_same_responsive_candidate_to_image_and_preload(self):
        self.assertIn(ROUTE, lcp_target_routes())
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / '.nojekyll').touch()
            source = output / IMAGE.lstrip('/')
            source.parent.mkdir(parents=True)
            Image.new('RGB', (1440, 936), '#8a7a63').save(source, 'WEBP', quality=86)
            page = output / ROUTE.lstrip('/') / 'index.html'
            page.parent.mkdir(parents=True)
            page.write_text(HTML)
            page, amended, _ = _prepare_page(output, ROUTE)
            page.write_text(amended)
            validate_mobile_lcp_cover(output, page, amended)
            source_tag = next(tag for tag in amended.split('<') if MARKER in tag)
            self.assertIn('832w', source_tag)
            self.assertIn('832w', amended.split('data-case-cover-preload')[0])
            self.assertEqual(amended.count(MARKER), 1)
            image_path = output / 'assets/responsive/case-cover/portfolio/sholts-restaurant-drohobych/vaults-01-832.avif'
            with Image.open(image_path) as image:
                self.assertEqual(image.format, 'AVIF')
                self.assertEqual(image.width, WIDTH)

    def test_profile_validator_allows_unprofiled_routes_without_markers(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / '.nojekyll').touch()
            page = output / 'portfolio' / 'index.html'
            page.parent.mkdir(parents=True)
            validate_mobile_lcp_cover(output, page, '<html></html>')

    def test_delivery_normalizer_removes_only_the_matching_832w_pair(self):
        candidate = '/assets/responsive/case-cover/portfolio/sholts-restaurant-drohobych/vaults-01-832.avif'
        source_tag = '<source type="image/avif" media="(max-width: 700px)" srcset="' + AVIF + '" sizes="' + SIZES + '">'
        preload_tag = ('<link rel="preload" as="image" type="image/avif" media="(max-width: 700px)" '
                       'imagesrcset="' + AVIF + '" imagesizes="' + SIZES
                       + '" fetchpriority="high" data-case-cover-preload>')
        profiled_source = source_tag.replace('srcset="' + AVIF + '"',
            'srcset="' + _insert_candidate(AVIF, candidate) + '"')[:-1] + ' ' + MARKER + '>'
        profiled_preload = preload_tag.replace('imagesrcset="' + AVIF + '"',
            'imagesrcset="' + _insert_candidate(AVIF, candidate) + '"')
        amended = HTML.replace(source_tag, profiled_source).replace(preload_tag, profiled_preload)
        self.assertEqual(restore_mobile_lcp_cover(amended), HTML)


if __name__ == '__main__':
    unittest.main()
