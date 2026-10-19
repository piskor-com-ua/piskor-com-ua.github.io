import hashlib
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from agent_catalog import Document
from agent_content import render
from case_minification import minify_fragment
from zabava_gallery_delivery import ROUTE, defer_zabava_gallery, validate_zabava_gallery

PICTURE = ('<picture><source type="image/avif" media="(max-width: 700px)" '
           'srcset="/assets/a-640.avif?v=a 640w, /assets/a-1440.avif?v=b 1440w" sizes="90vw">'
           '<img src="/assets/a.webp?v=c" srcset="/assets/a-640.webp?v=d 640w, /assets/a.webp?v=c 1440w" '
           'sizes="90vw" alt="Warm dining room" width="1440" height="1080" loading="lazy" decoding="async"></picture>')
HTML = ('<html lang="en"><head><title>Zabava</title></head><body>'
        '<figure class="project-cover"><img src="/assets/cover.webp" alt="Cover"></figure>'
        '<section id="dining"><h2>Dining</h2><div class="gallery-grid case-images">'
        '<figure><button data-gallery data-full="/assets/a-full.webp" aria-label="Enlarge room">'
        + PICTURE + '</button><figcaption>Room caption</figcaption></figure>'
        '<figure>' + PICTURE.replace('Warm dining room', 'Guest room')
        + '<figcaption>Guest room caption</figcaption></figure></div></section>'
        '<dialog class="project-lightbox"><img alt=""></dialog></body></html>')


class GalleryDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.nojekyll').touch()
        self.page = self.root / ROUTE
        self.page.parent.mkdir(parents=True)
        self.page.write_text(HTML)

    def test_only_exact_route_changes_and_repeated_preparation_is_stable(self):
        for name in ('index.html', 'portfolio/2022/zabava-restaurant-sambir/index.html', 'assets/a.webp'):
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(HTML)
        snapshot = lambda: {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in self.root.rglob('*') if p.is_file()}
        before = snapshot()
        self.assertEqual(defer_zabava_gallery(self.root)['pictures'], 2)
        after = snapshot()
        self.assertEqual([name for name in before if before[name] != after[name]], [ROUTE])
        self.assertEqual(defer_zabava_gallery(self.root), {'pictures': 0, 'already_prepared': True})
        self.assertEqual(snapshot(), after)

    def test_original_noscript_responsive_pictures_and_semantic_content_remain_exact(self):
        before = render(Document(HTML).root, 'https://piskor.com.ua/')
        defer_zabava_gallery(self.root)
        html = self.page.read_text()
        self.assertIn('<noscript>' + PICTURE + '</noscript>', html)
        self.assertIn('<noscript>' + PICTURE.replace('Warm dining room', 'Guest room') + '</noscript>', html)
        self.assertIn('<noscript><style>picture[data-zabava-gallery]{display:none!important}</style></noscript>', html)
        self.assertEqual(render(Document(html).root, 'https://piskor.com.ua/'), before)
        self.assertIn('<figure class="project-cover"><img src="/assets/cover.webp" alt="Cover"></figure>', html)
        active = Document(html).root.find(lambda node: node.tag == 'picture' and 'data-zabava-gallery' in node.attrs)
        self.assertEqual(len(active), 2)
        for picture in active:
            image = picture.find(lambda node: node.tag == 'img')[0]
            self.assertTrue(image.attrs['src'].startswith('data:image/svg+xml,'))
            self.assertEqual(image.attrs['width'], '1440')
            self.assertEqual(image.attrs['height'], '1080')
            self.assertIn(image.attrs['alt'], {'Warm dining room', 'Guest room'})
            self.assertEqual(image.attrs['sizes'], '90vw')
            self.assertEqual(image.attrs['data-zabava-src'], '/assets/a.webp?v=c')
            self.assertNotIn('srcset', image.attrs)
            self.assertIn('data-zabava-srcset', image.attrs)
            source = picture.find(lambda node: node.tag == 'source')[0]
            self.assertEqual(source.attrs['type'], 'image/avif')
            self.assertEqual(source.attrs['media'], '(max-width: 700px)')
            self.assertNotIn('srcset', source.attrs)
        self.assertIn('data-full="/assets/a-full.webp"', html)
        self.assertIn('aria-label="Enlarge room"', html)

    def test_pinned_minifier_retains_working_noscript_fallback_and_original_semantics(self):
        defer_zabava_gallery(self.root)
        original = self.page.read_text()
        compact = minify_fragment(original)
        self.assertEqual(render(Document(compact).root, 'https://piskor.com.ua/'),
                         render(Document(original).root, 'https://piskor.com.ua/'))
        fallback = Document(compact).root.find(lambda node: node.tag == 'noscript')
        self.assertEqual(len(fallback), 3)
        self.assertEqual(len([node for item in fallback for node in item.find(lambda n: n.tag == 'img')]), 2)
        self.assertIn('picture[data-zabava-gallery]', compact)

    def test_missing_route_is_skipped_and_unknown_markup_fails_before_write(self):
        with self.assertRaises(ValueError):
            defer_zabava_gallery(Path('concept'))
        for malformed in (HTML.replace('loading="lazy"', 'loading="eager"'),
                          HTML.replace('</picture>', ''), HTML.replace('width="1440"', 'width="unknown"')):
            self.page.write_text(malformed)
            with self.assertRaises(ValueError):
                defer_zabava_gallery(self.root)
            self.assertEqual(self.page.read_text(), malformed)
        self.page.unlink()
        self.assertIsNone(defer_zabava_gallery(self.root))

    def test_gallery_controller_precedes_existing_critical_pair_and_keeps_its_body_end(self):
        pair = ('<script data-inline-page-critical="agent-tools.js">agent();</script>'
                '<script data-inline-page-critical="portfolio.js">gallery();</script>')
        self.page.write_text(HTML.replace('</body>', pair + '</body>'))
        defer_zabava_gallery(self.root)
        html = self.page.read_text()
        self.assertTrue(html.endswith(pair + '</body></html>'))
        self.assertLess(html.index('data-zabava-gallery-delivery'), html.index('data-inline-page-critical'))

    def test_validator_rejects_stale_source_missing_fallback_and_changed_alt(self):
        defer_zabava_gallery(self.root)
        html = self.page.read_text()
        for changed in (html.replace("rootMargin: '750px 0px'", "rootMargin: '1px'"),
                        html.replace('<noscript>' + PICTURE + '</noscript>', ''),
                        html.replace('alt="Warm dining room"', 'alt="Wrong room"', 1)):
            with self.subTest(changed=changed[:40]):
                with self.assertRaises(ValueError):
                    validate_zabava_gallery(self.root, self.page, changed)
        with self.assertRaises(ValueError):
            validate_zabava_gallery(self.root, self.root / 'index.html', html)


if __name__ == '__main__':
    unittest.main()
