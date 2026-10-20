from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_catalog import Document
from agent_content import render
from deferred_mobile_media import (
    FALLBACK_MARKER, PICTURE_MARKER, SCRIPT_MARKER, STYLE_MARKER,
    CONTROLLER, followup_target_routes, high_si_target_routes, top10_target_routes,
    redirect_aliases, target_root_margin, target_routes,
    transform_page, validate_deferred_mobile_media,
)

SOURCE = ('<picture><source type="image/avif" media="(max-width: 700px)" '
          'srcset="/assets/room-640.avif 640w, /assets/room-1440.avif 1440w">'
          '<img src="/assets/room.webp" srcset="/assets/room-640.webp 640w, /assets/room.webp 1440w" '
          'sizes="100vw" alt="Warm dining room" width="1440" height="1080" '
          'loading="lazy" decoding="async"></picture>')
HTML = ('<!doctype html><html lang="en"><head><title>Portfolio</title></head><body>'
        '<main><div class="portfolio-card-image">'
        '<picture><source type="image/avif" srcset="/assets/cover-640.avif 640w">'
        '<img src="/assets/cover.webp" alt="First cover" width="1440" height="1080" '
        'loading="eager" fetchpriority="high"></picture>'
        '<picture><source type="image/avif" srcset="/assets/next-640.avif 640w">'
        '<img src="/assets/next.webp" alt="Next card" width="1440" height="1080" '
        'loading="lazy" decoding="async"></picture></div>'
        '<figure class="project-cover"><img src="/assets/hero.webp" alt="Hero"></figure>'
        '<section><div class="gallery-grid case-images"><figure><button data-gallery>'
        + SOURCE + '</button><figcaption>Room caption</figcaption></figure></div></section>'
        '</main><script data-inline-page-critical="agent-tools.js">agent();</script>'
        '<script data-inline-page-critical="portfolio.js">gallery();</script></body></html>')


class DeferredMobileMediaTests(unittest.TestCase):
    def test_fresh_psi_followup_is_separate_and_only_adds_speed_index_failures(self):
        followup = followup_target_routes()
        self.assertEqual(followup, frozenset({
            '/en/portfolio/2020/',
            '/en/portfolio/2020/family-house-solonka/',
            '/portfolio/2021/berloha-lounge-bar-lviv/',
            '/en/portfolio/2024/markosoli-store/',
            '/en/portfolio/2025/vesteros-house/',
        }))
        self.assertEqual(len(target_routes()), 54)
        self.assertTrue(followup.issubset(target_routes()))

    def test_high_speed_index_routes_are_exactly_scoped_and_use_zero_margin(self):
        routes = high_si_target_routes()
        self.assertEqual(len(routes), 10)
        self.assertEqual(target_root_margin('/portfolio/2024/rosa-store/'), '0px 0px')
        self.assertEqual(target_root_margin('/portfolio/2024/fitme-fitness-club/'), '250px 0px')
        self.assertTrue(routes.issubset(target_routes()))

    def test_current_top_ten_psi_cohort_is_ranked_and_included(self):
        top10 = top10_target_routes()
        self.assertEqual(len(top10), 10)
        self.assertEqual(top10, frozenset({
            '/', '/en/',
            '/en/portfolio/2020/family-house-solonka/',
            '/en/portfolio/2020/meduza-lounge-lviv/',
            '/en/portfolio/2020/bartativ-house-reconstruction/',
            '/portfolio/2020/sholts-restaurant-drohobych/',
            '/en/portfolio/2021/davydiv-house/',
            '/portfolio/2026/briukhovychi-house/',
            '/portfolio/2023/avalon-holiday-apartment/',
            '/portfolio/2025/zamartynivska-apartment/',
        }))
        self.assertTrue((top10 - {'/', '/en/'}).issubset(target_routes()))
        self.assertFalse({'/', '/en/'} & target_routes(), 'Homepages use their own PSI fix')

    def test_only_lazy_catalog_cards_and_case_gallery_pictures_are_deferred(self):
        amended, count = transform_page(HTML, CONTROLLER.read_text())
        self.assertEqual(count, 2)
        self.assertIn('<noscript ' + STYLE_MARKER, amended)
        self.assertIn('<noscript ' + FALLBACK_MARKER + '>' + SOURCE + '</noscript>', amended)
        self.assertIn('fetchpriority="high"', amended)
        self.assertIn('src="/assets/cover.webp"', amended)
        self.assertIn('src="/assets/hero.webp"', amended)
        self.assertIn('<picture><source type="image/avif" srcset="/assets/cover-640.avif 640w">'
                      '<img src="/assets/cover.webp"', amended)
        self.assertEqual(amended.count('data-piskor-src='), 2)
        self.assertEqual(amended.count('data-piskor-srcset='), 3)
        self.assertEqual(amended.count('<script ' + SCRIPT_MARKER), 1)
        self.assertLess(amended.index(SCRIPT_MARKER), amended.index('data-inline-page-critical="agent-tools.js"'))
        self.assertTrue(amended.endswith('</body></html>'))

    def test_deferred_and_native_markup_keep_identical_agent_visible_content(self):
        amended, _ = transform_page(HTML, CONTROLLER.read_text())
        before = render(Document(HTML).root, 'https://piskor.com.ua/')
        after = render(Document(amended).root, 'https://piskor.com.ua/')
        self.assertEqual(after, before)

    def test_high_si_route_profile_is_carried_by_verified_controller_markup(self):
        route = '/portfolio/2024/rosa-store/'
        amended, _ = transform_page(HTML, CONTROLLER.read_text(), route)
        self.assertIn('data-piskor-deferred-media-root-margin="0px 0px"', amended)
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / '.nojekyll').touch()
            page = output / route.lstrip('/') / 'index.html'
            page.parent.mkdir(parents=True)
            page.write_text(amended)
            validate_deferred_mobile_media(output, page, amended)

    def test_target_route_contract_rejects_loss_of_responsive_fallback_or_controller(self):
        amended, _ = transform_page(HTML, CONTROLLER.read_text())
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / '.nojekyll').touch()
            page = output / 'en' / 'portfolio' / '2026' / 'briukhovychi-house' / 'index.html'
            page.parent.mkdir(parents=True)
            page.write_text(amended)
            validate_deferred_mobile_media(output, page, amended)
            with self.assertRaises(ValueError):
                validate_deferred_mobile_media(output, page, amended.replace(
                    '<noscript ' + FALLBACK_MARKER, '<noscript'))
            with self.assertRaises(ValueError):
                validate_deferred_mobile_media(output, page, amended.replace(
                    '<script ' + SCRIPT_MARKER, '<script data-stale-controller'))

    def test_unknown_or_nonlazy_gallery_markup_fails_before_a_partial_transform(self):
        with self.assertRaises(ValueError):
            transform_page(HTML.replace('loading="lazy"', 'loading="eager"'),
                           CONTROLLER.read_text())

    def test_measured_legacy_redirects_are_validated_and_left_unchanged(self):
        route, destination = next(iter(redirect_aliases().items()))
        alias = ('<!doctype html><html><head><link rel="canonical" href="https://piskor.com.ua'
                 + destination + '"><meta http-equiv="refresh" content="0;url=' + destination
                 + '"></head><body><script>const destination = "' + destination + '";\n'
                 + 'location.replace(destination + location.search + fragment);</script></body></html>')
        amended, count = transform_page(alias, CONTROLLER.read_text(), route)
        self.assertEqual((amended, count), (alias, 0))
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / '.nojekyll').touch()
            page = output / route.lstrip('/') / 'index.html'
            page.parent.mkdir(parents=True)
            page.write_text(alias)
            validate_deferred_mobile_media(output, page, alias)
            with self.assertRaises(ValueError):
                transform_page(alias.replace('location.replace(', 'location.assign('),
                               CONTROLLER.read_text(), route)


if __name__ == '__main__':
    unittest.main()
