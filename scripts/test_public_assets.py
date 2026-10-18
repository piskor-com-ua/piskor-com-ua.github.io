import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from prepare_public_assets import prepare_public_assets, bundle_catalog_styles
from fingerprint_resources import fingerprint_resources
from optimize_assets import optimize_assets
from agent_catalog import Document


class PublicAssetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / '_site'
        self.output.mkdir()
        (self.output / '.nojekyll').touch()
        (self.output / 'assets').mkdir()

    def test_actual_sizes_responsive_candidates_and_source_preservation(self):
        image = self.output / 'assets/cover-1440.webp'
        Image.new('RGB', (1080, 810), '#258878').save(image)
        original = image.read_bytes()
        page = self.output / 'index.html'
        page.write_text('<head><meta name="viewport" content="width=device-width, initial-scale=1"></head><img class="portfolio-card-cover" src="/assets/cover-1440.webp" width="2970" height="2100" loading="eager">')
        result = prepare_public_assets(self.output)
        text = page.read_text()
        self.assertEqual(result['unique_covers'], 1)
        self.assertIn('width="1080" height="810"', text)
        self.assertIn('960w', text)
        self.assertIn('1080w', text)
        self.assertNotIn('1440w', text)
        self.assertEqual(image.read_bytes(), original)
        with Image.open(self.output / 'assets/responsive/cover-960.webp') as prepared:
            self.assertEqual(prepared.size, (960, 720))
        picture = Document(text).root.find(lambda n: n.tag == 'picture')[0]
        source = picture.find(lambda n: n.tag == 'source')[0]
        fallback = picture.find(lambda n: n.tag == 'img')[0]
        self.assertEqual(source.attrs['type'], 'image/avif')
        self.assertEqual(source.attrs['media'], '(max-width: 700px)')
        self.assertEqual(source.attrs['sizes'], fallback.attrs['sizes'])
        for entry in source.attrs['srcset'].split(','):
            url, descriptor = entry.strip().split()
            with Image.open(self.output / url.lstrip('/')) as prepared:
                self.assertEqual(prepared.format, 'AVIF')
                self.assertEqual(prepared.width, int(descriptor[:-1]))
                self.assertEqual(prepared.width / prepared.height, 4 / 3)

    def test_preload_follows_first_card_per_page_and_survives_fingerprinting(self):
        for name in ('first', 'year'):
            Image.new('RGB', (480, 360), name == 'first' and '#258878' or '#754832').save(self.output / ('assets/' + name + '.webp'))
        head = '<head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="preload" as="font" href="/font.woff2"></head>'
        card = lambda name: '<img class="portfolio-card-cover" src="/assets/' + name + '.webp">'
        pages = {'index.html': head + card('first') + card('year'),
                 'year.html': head + card('year'), 'case.html': head + '<img src="/assets/first.webp">'}
        for name, html in pages.items():
            (self.output / name).write_text(html)
        prepare_public_assets(self.output)
        fingerprint_resources(self.output)
        for name in ('index.html', 'year.html'):
            html = (self.output / name).read_text()
            root = Document(html).root
            links = root.find(lambda n: n.tag == 'link' and n.attrs.get('as') == 'image')
            self.assertEqual(len(links), 1)
            link = links[0].attrs
            source = root.find(lambda n: n.tag == 'source')[0].attrs
            self.assertEqual(link['imagesrcset'], source['srcset'])
            self.assertIn('.avif?v=', link['imagesrcset'])
            self.assertEqual(link['imagesizes'], source['sizes'])
            self.assertEqual((link['type'], link['media']), (source['type'], source['media']))
            self.assertEqual(link['fetchpriority'], 'high')
            self.assertNotIn('href', link)
            self.assertLess(html.index('data-catalog-cover-preload'), html.index('as="font"'))
        self.assertNotIn('as="image"', (self.output / 'case.html').read_text())
        self.assertIn('/year-480.avif', (self.output / 'year.html').read_text())

    def test_nested_fingerprints_follow_bytes_and_keep_paths(self):
        image = self.output / 'assets/cover.webp'
        image.write_bytes(b'picture')
        (self.output / 'assets/cover.avif').write_bytes(b'avif picture')
        font = self.output / 'assets/font.woff2'
        font.write_bytes(b'font')
        style = self.output / 'site.css'
        style.write_text('a{background:url(assets/cover.webp)}')
        script = self.output / 'site.js'
        script.write_text('const font="/assets/font.woff2";')
        page = self.output / 'index.html'
        page.write_text('<link href="/site.css"><script src="/site.js"></script><picture><source type="image/avif" srcset="/assets/cover.avif 640w"><img srcset="/assets/cover.webp 640w"></picture>')
        (self.output / 'project-catalog.json').write_text(json.dumps({'image': '/assets/cover.webp'}))
        fingerprint_resources(self.output)
        self.assertIn('cover.webp?v=' + hashlib.sha256(b'picture').hexdigest()[:12], style.read_text())
        self.assertIn('/site.css?v=' + hashlib.sha256(style.read_bytes()).hexdigest()[:12], page.read_text())
        self.assertIn('font.woff2?v=', script.read_text())
        self.assertIn('cover.webp?v=', (self.output / 'project-catalog.json').read_text())
        self.assertIn('cover.avif?v=' + hashlib.sha256(b'avif picture').hexdigest()[:12], page.read_text())
        self.assertTrue(image.exists())
        self.assertTrue(font.exists())
        # Optimizer understands versioned references and preserves WOFF2.
        optimize_assets(self.output)
        self.assertTrue(font.exists())
        self.assertTrue((self.output / 'assets/cover.avif').exists())

    def test_logo_preserves_transparency_original_and_intrinsic_ratio(self):
        logo = self.output / 'assets/piskor-logo.png'
        artwork = Image.new('RGBA', (924, 234), (150, 200, 180, 128))
        artwork.putpixel((0, 0), (50, 60, 70, 0))
        artwork.save(logo)
        original = logo.read_bytes()
        page = self.output / 'index.html'
        page.write_text('<img src="/assets/piskor-logo.png" alt="PISKOR">')
        prepare_public_assets(self.output)
        attrs = Document(page.read_text()).root.find(lambda n: n.tag == 'img')[0].attrs
        self.assertEqual((attrs['width'], attrs['height']), ('924', '234'))
        self.assertEqual(attrs['src'], '/assets/piskor-logo.png')
        self.assertEqual(logo.read_bytes(), original)
        source = Document(page.read_text()).root.find(lambda n: n.tag == 'source')[0].attrs
        self.assertEqual(source['type'], 'image/webp')
        with Image.open(self.output / source['srcset'].lstrip('/')) as image, Image.open(logo) as before:
            self.assertEqual(image.size, before.size)
            self.assertEqual(image.convert('RGBA').tobytes(), before.convert('RGBA').tobytes())

    def test_queries_and_fragments_survive_versioning(self):
        (self.output / 'assets/cover.webp').write_bytes(b'picture')
        page = self.output / 'index.html'
        page.write_text('<img src="/assets/cover.webp?width=640&amp;mode=crop#view">')
        fingerprint_resources(self.output)
        self.assertIn('?width=640&amp;mode=crop&amp;v=', page.read_text())
        self.assertIn('#view', page.read_text())
        once = page.read_text()
        fingerprint_resources(self.output)
        self.assertEqual(page.read_text(), once)

    def test_bundle_keeps_source_order_and_only_changes_catalog(self):
        for name in ['analytics-consent.css', 'style.css', 'portfolio.css', 'catalog.css']:
            (self.output / name).write_text('/* ' + name + ' */')
        links = ''.join('<link rel="stylesheet" href="/' + name + '">' for name in ['analytics-consent.css', 'style.css', 'portfolio.css', 'catalog.css'])
        (self.output / 'index.html').write_text(links + '<body class="catalog-page">')
        (self.output / 'case.html').write_text(links + '<body class="project-page">')
        bundle_catalog_styles(self.output)
        self.assertEqual((self.output / 'index.html').read_text().count('rel="stylesheet"'), 1)
        self.assertEqual((self.output / 'case.html').read_text().count('rel="stylesheet"'), 4)
        self.assertLess((self.output / 'catalog-bundle.css').read_text().index('style.css'), (self.output / 'catalog-bundle.css').read_text().index('portfolio.css'))


if __name__ == '__main__':
    unittest.main()
