from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from deferred_mobile_media import critical_image_delivery_routes, lcp_target_routes
from mobile_lcp_cover_delivery import (MARKER, WIDTH, _insert_candidate, _prepare_page,
                                       CATALOG_MARKER, CATALOG_QUALITY, CATALOG_WIDTH,
                                       prepare_mobile_catalog_delivery_profiles,
                                       restore_mobile_lcp_cover, validate_mobile_catalog_delivery,
                                       validate_mobile_lcp_cover)

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

CATALOG_ROUTE = '/portfolio/2022/'
CATALOG_MASTER = '/assets/portfolio/zabava-restaurant-sambir/zabava-restaurant-sambir-01-1440.webp'
CATALOG_AVIF = ('/assets/responsive/case-cover/catalog/portfolio/zabava-restaurant-sambir/'
                'zabava-restaurant-sambir-01-640.avif 640w, '
                '/assets/responsive/case-cover/catalog/portfolio/zabava-restaurant-sambir/'
                'zabava-restaurant-sambir-01-768.avif 768w')
CATALOG_WEBP = ('/assets/responsive/portfolio/zabava-restaurant-sambir/'
                'zabava-restaurant-sambir-01-640.webp 640w, '
                '/assets/portfolio/zabava-restaurant-sambir/'
                'zabava-restaurant-sambir-01-1440.webp 1440w')
CATALOG_WIDE_ROUTE = '/en/portfolio/2021/'
CATALOG_WIDE_MASTER = '/assets/portfolio/vasha-terasa-showroom/vasha-terasa-hall-01-1440.webp'
CATALOG_WIDE_AVIF = ('/assets/responsive/case-cover/catalog/portfolio/vasha-terasa-showroom/'
                     'vasha-terasa-hall-01-640.avif 640w, '
                     '/assets/responsive/case-cover/catalog/portfolio/vasha-terasa-showroom/'
                     'vasha-terasa-hall-01-768.avif 768w')
CATALOG_WIDE_WEBP = ('/assets/responsive/portfolio/vasha-terasa-showroom/'
                     'vasha-terasa-hall-01-640.webp 640w, '
                     '/assets/portfolio/vasha-terasa-showroom/'
                     'vasha-terasa-hall-01-1440.webp 1422w')
CATALOG_HTML = ('<!doctype html><html><head><link rel="preload" as="image" type="image/avif" '
                'media="(max-width: 700px)" imagesrcset="' + CATALOG_AVIF + '" '
                'imagesizes="calc(100vw - 48px)" fetchpriority="high" '
                'data-catalog-cover-preload></head><body><a class="portfolio-card">'
                '<div class="portfolio-card-image"><picture><source type="image/avif" '
                'media="(max-width: 700px)" srcset="' + CATALOG_AVIF + '" '
                'sizes="calc(100vw - 48px)"><img class="portfolio-card-cover" src="' +
                CATALOG_MASTER + '" srcset="' + CATALOG_WEBP + '" '
                'sizes="calc(100vw - 48px)" width="1440" height="1080" '
                'alt="Zabava restaurant interior" loading="eager" fetchpriority="high" '
                'decoding="async"></picture></div></a></body></html>')
CATALOG_WIDE_HTML = ('<!doctype html><html><head><link rel="preload" as="image" type="image/avif" '
                     'media="(max-width: 700px)" imagesrcset="' + CATALOG_WIDE_AVIF + '" '
                     'imagesizes="calc(125.17606vw - 60.084507px)" fetchpriority="high" '
                     'data-catalog-cover-preload></head><body><a class="portfolio-card">'
                     '<div class="portfolio-card-image"><picture><source type="image/avif" '
                     'media="(max-width: 700px)" srcset="' + CATALOG_WIDE_AVIF + '" '
                     'sizes="calc(125.17606vw - 60.084507px)"><img class="portfolio-card-cover" src="' +
                     CATALOG_WIDE_MASTER + '" srcset="' + CATALOG_WIDE_WEBP + '" '
                     'sizes="calc(125.17606vw - 60.084507px)" width="1422" height="800" '
                     'alt="Vasha Terasa showroom" loading="eager" fetchpriority="high" '
                     'decoding="async"></picture></div></a></body></html>')


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

    def test_critical_catalog_delivery_profile_preserves_resolution_and_matches_preload(self):
        self.assertEqual(critical_image_delivery_routes(),
                         frozenset({'/portfolio/2022/', '/en/portfolio/2022/', CATALOG_WIDE_ROUTE}))
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / '.nojekyll').touch()
            master = output / CATALOG_MASTER.lstrip('/')
            master.parent.mkdir(parents=True)
            Image.new('RGB', (1440, 1080), '#8a7a63').save(master, 'WEBP', quality=86)
            default = output / 'assets/responsive/case-cover/catalog/portfolio/zabava-restaurant-sambir/zabava-restaurant-sambir-01-640.avif'
            default.parent.mkdir(parents=True)
            Image.new('RGB', (640, 480), '#8a7a63').save(default, 'AVIF', quality=50, speed=6)
            wide_master = output / CATALOG_WIDE_MASTER.lstrip('/')
            wide_master.parent.mkdir(parents=True)
            Image.new('RGB', (1422, 800), '#8a7a63').save(wide_master, 'WEBP', quality=86)
            wide_default = output / 'assets/responsive/case-cover/catalog/portfolio/vasha-terasa-showroom/vasha-terasa-hall-01-640.avif'
            wide_default.parent.mkdir(parents=True)
            Image.new('RGB', (640, 360), '#8a7a63').save(wide_default, 'AVIF', quality=50, speed=6)
            pages = []
            for route in sorted(critical_image_delivery_routes()):
                page = output / route.lstrip('/') / 'index.html'
                page.parent.mkdir(parents=True)
                page.write_text(CATALOG_WIDE_HTML if route == CATALOG_WIDE_ROUTE else CATALOG_HTML)
                pages.append(page)

            report = prepare_mobile_catalog_delivery_profiles(output)
            self.assertEqual(report['routes'], 3)
            self.assertEqual(report['unique_candidates'], 2)
            self.assertEqual(report['width'], CATALOG_WIDTH)
            self.assertEqual(report['quality'], CATALOG_QUALITY)
            for page in pages:
                amended = page.read_text()
                validate_mobile_catalog_delivery(output, page, amended)
                source = next(tag for tag in amended.split('<')
                              if tag.startswith('source') and CATALOG_MARKER in tag)
                candidate = next(entry.strip().split()[0]
                                 for entry in source.split('srcset="', 1)[1].split('"', 1)[0].split(',')
                                 if entry.strip().endswith(str(CATALOG_WIDTH) + 'w'))
                preload = next(tag for tag in amended.split('<')
                               if tag.startswith('link') and 'data-catalog-cover-preload' in tag)
                self.assertIn(candidate, preload)
                optimized = output / candidate.lstrip('/')
                with Image.open(optimized) as image:
                    self.assertEqual(image.format, 'AVIF')
                    self.assertEqual(image.width, CATALOG_WIDTH)
                    self.assertIn(image.height, (360, 480))
                baseline = wide_default if route == CATALOG_WIDE_ROUTE else default
                self.assertLess(optimized.stat().st_size, baseline.stat().st_size)
                self.assertLessEqual(optimized.stat().st_size, 18_000)


if __name__ == '__main__':
    unittest.main()
