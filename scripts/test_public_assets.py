import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from prepare_public_assets import (prepare_public_assets, bundle_catalog_styles, COVER_SIZES, CARD_SIZES,
                                   CaseImageContexts, image_style_rules, case_image_style,
                                   crop_aware_sizes, home_hero_crops, UnsupportedImageStyle)
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

    def test_case_sources_match_layout_and_preserve_full_gallery_and_desktop(self):
        originals = {}
        for name, width in [('photo-640', 640), ('photo-1440', 1440), ('photo-2200', 2000)]:
            path = self.output / ('assets/' + name + '.webp')
            Image.new('RGB', (width, width * 3 // 4), '#258878').save(path)
            originals[path] = path.read_bytes()
        img = ('<img src="/assets/photo-1440.webp" '
               'srcset="/assets/photo-640.webp 640w, /assets/photo-1440.webp 1440w, /assets/photo-2200.webp 2200w" '
               'sizes="100vw" alt="Той самий простір">')
        html = ('<head><meta name="viewport" content="width=device-width, initial-scale=1">'
                '<link rel="preload" as="font" href="/font.woff2"></head>\n'
                '<body class="project-page pdf-project-page"><figure class="project-cover">' + img + '</figure>'
                '<section class="case-chapter"><div class="gallery-grid case-images"><figure>'
                '<button data-gallery data-full="/assets/photo-2200.webp" aria-label="Збільшити простір">' +
                img.replace('/assets/photo-1440.webp 1440w, ', '').replace('sizes="100vw"', 'sizes="(max-width: 700px) 100vw, 50vw" loading="lazy" decoding="async"') +
                '</button><figcaption>Збережений підпис</figcaption></figure></div></section></body>')
        for name in ('uk.html', 'en.html'):
            (self.output / name).write_text(html)
        result = prepare_public_assets(self.output)
        self.assertEqual(result['responsive_case_images'], 4)
        self.assertEqual(result['unique_case_images'], 1)
        fingerprint_resources(self.output)
        for name in ('uk.html', 'en.html'):
            text = (self.output / name).read_text()
            root = Document(text).root
            pictures = root.find(lambda n: n.tag == 'picture')
            self.assertEqual(len(pictures), 2)
            for index, picture in enumerate(pictures):
                source = picture.find(lambda n: n.tag == 'source')[0].attrs
                fallback = picture.find(lambda n: n.tag == 'img')[0].attrs
                self.assertEqual(source['sizes'], COVER_SIZES if index == 0 else CARD_SIZES)
                self.assertEqual(source['sizes'], fallback['sizes'])
                self.assertEqual(source['media'], '(max-width: 700px)')
                self.assertEqual(fallback['src'].split('?')[0], '/assets/photo-1440.webp')
                self.assertIn('photo-2200.webp?v=', fallback['srcset'])
                self.assertIn('photo-1440.webp?v=', fallback['srcset'])
                self.assertIn('2000w', fallback['srcset'])
                self.assertNotIn('2200w', fallback['srcset'])
                widths = []
                for entry in source['srcset'].split(','):
                    url, descriptor = entry.strip().split()
                    with Image.open(self.output / url.split('?')[0].lstrip('/')) as image:
                        self.assertEqual(image.format, 'AVIF')
                        self.assertEqual(image.width, int(descriptor[:-1]))
                        self.assertEqual(image.width / image.height, 4 / 3)
                        widths.append(image.width)
                self.assertEqual(widths, [640, 768, 960, 1440, 2000] if index == 0 else [640, 960, 1440, 2000])
                self.assertEqual(fallback['alt'], 'Той самий простір')
            gallery = pictures[1].find(lambda n: n.tag == 'img')[0]
            self.assertEqual((gallery.attrs['loading'], gallery.attrs['decoding']), ('lazy', 'async'))
            button = root.find(lambda n: n.tag == 'button')[0]
            self.assertTrue(button.attrs['data-full'].startswith('/assets/photo-2200.webp?v='))
            self.assertEqual(button.attrs['aria-label'], 'Збільшити простір')
            self.assertIn('Збережений підпис', root.text())
            preload = root.find(lambda n: n.tag == 'link' and n.attrs.get('as') == 'image')[0].attrs
            cover = pictures[0].find(lambda n: n.tag == 'source')[0].attrs
            self.assertEqual((preload['imagesrcset'], preload['imagesizes']), (cover['srcset'], cover['sizes']))
            self.assertEqual(preload['fetchpriority'], 'high')
            self.assertNotIn('href', preload)
            self.assertLess(text.index('data-case-cover-preload'), text.index('as="font"'))
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_cover_768_context_isolated_from_prior_gallery_and_catalog_without_upscaling(self):
        for name, width in (('shared', 1200), ('small', 600)):
            Image.new('RGB', (width, width * 3 // 4), '#258878').save(self.output / ('assets/' + name + '.webp'))
        head = '<head><meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        image = '<img src="/assets/shared.webp" alt="Same source">'
        case = self.output / 'case.html'
        case.write_text(head + '<body class="project-page"><div class="gallery-grid">' + image
                        + '</div><figure class="project-cover">' + image + '</figure></body>')
        catalog = self.output / 'catalog.html'
        catalog.write_text(head + '<img class="portfolio-card-cover" src="/assets/shared.webp">')
        small = self.output / 'small.html'
        small.write_text(head + '<body class="project-page"><figure class="project-cover">'
                         '<img src="/assets/small.webp"></figure></body>')
        prepare_public_assets(self.output)
        root = Document(case.read_text()).root
        gallery = root.find(lambda n:'gallery-grid' in n.attrs.get('class', '').split())[0]
        cover = root.find(lambda n:'project-cover' in n.attrs.get('class', '').split())[0]
        cover_source = cover.find(lambda n:n.tag == 'source')[0].attrs
        gallery_source = gallery.find(lambda n:n.tag == 'source')[0].attrs
        self.assertIn('768w', cover_source['srcset'])
        self.assertIn('960w', cover_source['srcset'])
        self.assertNotIn('768w', gallery_source['srcset'])
        self.assertNotIn('768w', Document(catalog.read_text()).root.find(lambda n:n.tag == 'source')[0].attrs['srcset'])
        preload = root.find(lambda n:n.tag == 'link' and n.attrs.get('as') == 'image')[0].attrs
        self.assertEqual((preload['imagesrcset'], preload['imagesizes']), (cover_source['srcset'], cover_source['sizes']))
        small_source = Document(small.read_text()).root.find(lambda n:n.tag == 'source')[0].attrs
        self.assertEqual([entry.strip().split()[1] for entry in small_source['srcset'].split(',')], ['600w'])
        self.assertFalse(any(self.output.glob('assets/responsive/case-media/small-768.avif')))

    def test_case_encoding_cache_reuses_bytes_and_invalidates_changed_source(self):
        path = self.output / 'assets/photo.webp'
        Image.new('RGB', (64, 48), '#258878').save(path)
        page = self.output / 'index.html'
        html = ('<head><meta name="viewport" content="width=device-width, initial-scale=1"></head>'
                '<body class="project-page"><figure class="project-cover"><img src="/assets/photo.webp"></figure></body>')
        original_save = Image.Image.save
        encodes = []
        def save(image, filename, format=None, **kwargs):
            if format == 'AVIF':
                encodes.append(str(filename))
                self.assertEqual(kwargs['quality'], 60)
            return original_save(image, filename, format, **kwargs)
        with patch.object(Image.Image, 'save', save):
            page.write_text(html)
            prepare_public_assets(self.output)
            self.assertEqual(len(encodes), 1)
            first = (self.output / 'assets/responsive/case-media/photo-64.avif').read_bytes()
            page.write_text(html)
            prepare_public_assets(self.output)
            self.assertEqual(len(encodes), 1)
            self.assertEqual((self.output / 'assets/responsive/case-media/photo-64.avif').read_bytes(), first)
            Image.new('RGB', (64, 48), '#754832').save(path)
            page.write_text(html)
            prepare_public_assets(self.output)
            self.assertEqual(len(encodes), 2)
            self.assertNotEqual((self.output / 'assets/responsive/case-media/photo-64.avif').read_bytes(), first)
        self.assertTrue((self.output.parent / 'output/image-cache/responsive-avif-v1').is_dir())
        self.assertFalse(any(p.name.startswith('.') and p.name != '.nojekyll' for p in self.output.rglob('*')))

    def test_only_real_case_images_are_transformed(self):
        Image.new('RGB', (64, 48), '#258878').save(self.output / 'assets/photo.webp')
        page = self.output / 'index.html'
        script = '<script>const example = \'<img src="/assets/not-an-asset.webp">\';</script>'
        page.write_text(script + '<body class="project-page"><header><img src="/assets/photo.webp"></header>'
                        '<div class="project-lightbox"><img src="/assets/photo.webp"></div></body>')
        result = prepare_public_assets(self.output)
        self.assertEqual(result['responsive_case_images'], 0)
        self.assertIn(script, page.read_text())
        self.assertNotIn('<picture>', page.read_text())

    def hero_styles(self):
        names = ('analytics-consent.css', 'style.css', 'story.css', 'mobile.css', 'automation.css', 'portfolio.css')
        for name in names:
            (self.output / name).write_text(re.sub(r'url\([^)]*\)', 'url(data:,)', (Path('concept') / name).read_text()))
        return ''.join('<link rel="stylesheet" href="/' + name + '">' for name in names)

    def test_ssr_home_hero_uses_exact_mobile_crops_and_matching_exclusive_preloads(self):
        source = self.output / 'assets/house-concept.webp'
        Image.new('RGB', (1536, 1024), '#258878').save(source)
        original = source.read_bytes()
        page = self.output / 'index.html'
        html = ('<head><meta name="viewport" content="width=device-width, initial-scale=1">'
                        '<link rel="preload" as="font" href="/font.woff2">'
                        '<link rel="preload" href="/assets/house-concept.webp" as="image">' + self.hero_styles() + '</head>'
                        '<body><main><section class="hero"><div class="hero-picture">'
                        '<img src="/assets/house-concept.webp" width="1536" height="1024" '
                        'alt="Concept house" fetchpriority="high"></div><h1>Space</h1></section></main></body>')
        page.write_text(html)
        en = self.output / 'en/index.html'
        en.parent.mkdir()
        en.write_text(html)
        original_save = Image.Image.save
        original_resize = Image.Image.resize
        encodes = []
        def count_avif(image, filename, format=None, **kwargs):
            if format == 'AVIF':
                encodes.append((image.size, kwargs['quality']))
            return original_save(image, filename, format, **kwargs)
        def resize(image, size, *args, **kwargs):
            self.assertNotIn(image.size, {(636, 1024), (736, 1024), (1036, 1024)}, 'Native mobile crops must not be resampled')
            return original_resize(image, size, *args, **kwargs)
        with patch.object(Image.Image, 'save', count_avif), patch.object(Image.Image, 'resize', resize):
            result = prepare_public_assets(self.output)
        self.assertCountEqual(encodes, [((960, 640), 60), ((1280, 853), 60), ((1440, 960), 60), ((1536, 1024), 60),
                                      ((636, 1024), 45), ((736, 1024), 45), ((1036, 1024), 45)])
        self.assertEqual(result['responsive_home_heroes'], 2)
        self.assertEqual(result['responsive_case_images'], 0)
        fingerprint_resources(self.output)
        text = page.read_text()
        root = Document(text).root
        image = root.find(lambda n: n.tag == 'img')[0].attrs
        sources = [node.attrs for node in root.find(lambda n: n.tag == 'source')]
        picture_source = sources[-1]
        preload = root.find(lambda n: n.tag == 'link' and n.attrs.get('as') == 'image')
        self.assertEqual(len(preload), 4)
        self.assertEqual(len(sources), 4)
        for link, prepared, media in zip(preload, sources, ('(width <= 450px)', '(450px < width <= 480px)', '(480px < width <= 700px)', '(700px < width)')):
            self.assertEqual(link.attrs['imagesrcset'], prepared['srcset'])
            self.assertEqual(link.attrs['imagesizes'], prepared['sizes'])
            self.assertEqual(link.attrs['media'], media)
            self.assertNotIn('href', link.attrs)
        # These intervals form an exclusive partition, including fractional
        # widths that would fall into gaps in min-width:451px-style queries.
        for viewport_width, expected_branch in ((450, 0), (450.5, 1), (480, 1), (480.5, 2), (700, 2), (700.5, 3)):
            active = [viewport_width <= 450, 450 < viewport_width <= 480,
                      480 < viewport_width <= 700, 700 < viewport_width]
            self.assertEqual([index for index, matches in enumerate(active) if matches], [expected_branch])
        for prepared, dimensions in zip(sources[:3], ((636, 1024), (736, 1024), (1036, 1024))):
            self.assertEqual(len(prepared['srcset'].split(',')), 1)
            url, descriptor = prepared['srcset'].split()
            with Image.open(self.output / url.split('?')[0].lstrip('/')) as encoded:
                self.assertEqual(encoded.size, dimensions)
                self.assertEqual(descriptor, str(encoded.width) + 'w')
        self.assertNotIn('media', picture_source)
        self.assertIn('clamp(1110px, 150svh, 1500px)', picture_source['sizes'])
        self.assertIn('clamp(1140px, 150svh, 1800px)', picture_source['sizes'])
        self.assertEqual(image['sizes'], picture_source['sizes'])
        self.assertEqual((image['width'], image['height']), ('1536', '1024'))
        self.assertEqual(image['alt'], 'Concept house')
        self.assertTrue(image['src'].startswith('/assets/house-concept.webp?v='))
        self.assertIn('1536w', picture_source['srcset'])
        self.assertNotIn('2200w', picture_source['srcset'])
        self.assertLess(text.index('data-home-hero-preload'), text.index('as="font"'))
        self.assertEqual(source.read_bytes(), original)
        en_sources = [node.attrs for node in Document(en.read_text()).root.find(lambda n: n.tag == 'source')]
        self.assertEqual(sources, en_sources)

    def test_mobile_hero_crop_preserves_exact_source_coordinates_and_native_density(self):
        html = '<head>' + self.hero_styles() + '</head><body><main><section class="hero"><div class="hero-picture"><img></div></section></main></body>'
        context = CaseImageContexts(html)
        path = next(iter(context.paths.values()))
        crops = home_hero_crops(self.output, html, path, 1536, 1024)
        self.assertEqual(crops, [(450, (549, 0, 1185, 1024)), (480, (488, 0, 1224, 1024)), (700, (305, 0, 1341, 1024))])
        for viewport_width in (320, 390, 450, Fraction(901, 2), 480, Fraction(961, 2), 600, 700):
            crop = next(crop for maximum, crop in crops if viewport_width <= maximum)
            crop_width = crop[2] - crop[0]
            for viewport_height in (320, 740, 823, 844, 1000, 1400):
                hero_height = min(1000, max(740, viewport_height))
                visible_native_width = Fraction(viewport_width * 1024, hero_height)
                self.assertGreaterEqual(crop_width, visible_native_width)
                original_left = Fraction(61, 100) * (1536 - visible_native_width)
                cropped_left = crop[0] + Fraction(61, 100) * (crop_width - visible_native_width)
                self.assertEqual(original_left, cropped_left)
                self.assertEqual((crop[1], crop[3]), (0, 1024))
                # Both images scale from the same complete 1,024 source rows:
                # source density and every final visible coordinate are equal.
                self.assertEqual(Fraction(hero_height, crop[3] - crop[1]), Fraction(hero_height, 1024))

    def test_mobile_hero_crop_rejects_unproven_geometry_before_encoding(self):
        Image.new('RGB', (1536, 1024), '#258878').save(self.output / 'assets/house-concept.webp')
        head = '<head><meta name="viewport" content="width=device-width, initial-scale=1">' + self.hero_styles()
        body = '</head><body><main><section class="hero"><div class="hero-picture"><img src="/assets/house-concept.webp"></div></section></main></body>'
        page = self.output / 'index.html'
        for css in ('.hero{height:600px}', '.hero-picture img{object-position:50% 50%}',
                    '@media(orientation:landscape){.hero{height:50vh}}', '.hero:has(.x){height:100px}',
                    'img{width:80%}', '.hero{animation:move 1s}', '@starting-style{.hero{height:10px}}', '@import url(/unknown.css);'):
            with self.subTest(css=css):
                html = head + '<style>' + css + '</style>' + body
                page.write_text(html)
                with self.assertRaisesRegex(ValueError, 'Home hero crop'), patch.object(Image.Image, 'save', side_effect=AssertionError('must not encode')):
                    prepare_public_assets(self.output)
                self.assertEqual(page.read_text(), html)

    def test_crop_aware_cascade_follows_section_override_and_nth_child_specificity(self):
        html = ('<body class="project-page pdf-project-page"><main><section id="narrow">'
                '<div class="gallery-grid case-images"><figure><button><img src="/photo.webp"></button></figure>'
                '<figure><button><img src="/other.webp"></button></figure>'
                '<figure><button><img src="/third.webp"></button></figure></div></section></main></body>')
        contexts = CaseImageContexts(html)
        rules = image_style_rules('''
          .gallery-grid img{height:auto;aspect-ratio:3/4;object-fit:cover}
          .gallery-grid figure:nth-child(3) img{aspect-ratio:2970/2100}
          .pdf-project-page:not(.other-page) .case-images img{aspect-ratio:4/3}
          .pdf-project-page :is(#narrow,#other) .case-images img{aspect-ratio:3/5}
          body.project-page > main > section#narrow .case-images > figure:nth-child(2) img[src*="other"]{aspect-ratio:1/2}
        ''')
        styles = [case_image_style(rules, path) for path in contexts.paths.values()]
        self.assertEqual([style['aspect-ratio'] for style in styles], ['3/5', '1/2', '3/5'])
        # Source 4:3 in a 3:5 box needs 2.222... times the box's pixel width.
        sizes = crop_aware_sizes('gallery', 4 / 3, styles[0])
        self.assertIn('calc(222.22222vw - 106.66667px)', sizes)
        # A narrow portrait in a wider box is cropped vertically: no width penalty.
        self.assertEqual(crop_aware_sizes('gallery', 1213 / 2930, styles[1]), CARD_SIZES)
        # Without the ID rule, the more specific PDF rule beats nth-child.
        self.assertEqual(case_image_style(rules[:3], list(contexts.paths.values())[2])['aspect-ratio'], '4/3')

        # Inline declarations outrank ID selectors at the same importance;
        # an important stylesheet declaration still wins over ordinary inline.
        inline_path = list(contexts.paths.values())[0]
        inline_path[-1]['attrs']['style'] = 'aspect-ratio:2/1;object-fit:contain'
        inline_rules = image_style_rules('#narrow img{aspect-ratio:3/5;object-fit:cover!important}')
        self.assertEqual(case_image_style(inline_rules, inline_path)['aspect-ratio'], '2/1')
        self.assertEqual(case_image_style(inline_rules, inline_path)['object-fit'], 'cover')

    def test_cover_and_fixed_height_gallery_account_for_native_source_ratio(self):
        sizes = crop_aware_sizes('cover', 4 / 3, {'height': 'min(72vw,730px)', 'object-fit': 'cover'})
        self.assertIn('max(calc(100vw - 48px), min(96vw, 973.33333px))', sizes)
        # A cover's explicit aspect ratio plus height:auto takes precedence over
        # the shared min(72vw,730px) once the CSS cascade has selected it.
        self.assertEqual(crop_aware_sizes('cover', 4 / 3,
                                         {'height': 'auto', 'aspect-ratio': '16/9', 'object-fit': 'cover'}), COVER_SIZES)
        fixed = crop_aware_sizes('gallery', 2, {'height': 'clamp(260px,34vw,520px)', 'aspect-ratio': 'auto', 'object-fit': 'cover'})
        self.assertIn('clamp(520px, 68vw, 1040px)', fixed)
        with self.assertRaises(UnsupportedImageStyle):
            crop_aware_sizes('gallery', 2, {'height': 'var(--height)', 'object-fit': 'cover'})

    def test_unknown_conditional_image_layout_retains_legacy_and_full_native(self):
        for name, width in [('photo-640', 640), ('photo-1440', 1440), ('photo-2200', 2000)]:
            Image.new('RGB', (width, width * 3 // 4), '#258878').save(self.output / ('assets/' + name + '.webp'))
        page = self.output / 'index.html'
        page.write_text('<head><meta name="viewport" content="width=device-width, initial-scale=1">'
                        '<style>.gallery-grid img{height:auto;aspect-ratio:4/3;object-fit:cover}'
                        '@media(max-width:800px){.gallery-grid img{aspect-ratio:1/2}}</style></head>'
                        '<body class="project-page"><div class="gallery-grid"><figure><img '
                        'src="/assets/photo-1440.webp" srcset="/assets/photo-640.webp 640w, /assets/photo-2200.webp 2200w" '
                        'sizes="(max-width: 700px) 100vw, 50vw"></figure></div></body>')
        prepare_public_assets(self.output)
        root = Document(page.read_text()).root
        source = root.find(lambda n: n.tag == 'source')[0].attrs
        fallback = root.find(lambda n: n.tag == 'img')[0].attrs
        self.assertEqual(source['sizes'], '(max-width: 700px) 100vw, 50vw')
        self.assertEqual(len(source['srcset'].split(',')), 1)
        self.assertTrue(source['srcset'].endswith('2000w'))
        self.assertNotIn('photo-1440.webp', fallback['srcset'])

    def test_unsafe_picture_css_fails_before_encoding_or_rewriting(self):
        Image.new('RGB', (800, 600), '#258878').save(self.output / 'assets/photo.webp')
        page = self.output / 'index.html'
        styles = [
            ('button > img{width:100%}', 'structural CSS selector'),
            ('button > picture > img{height:80px}', 'structural CSS selector'),
            ('img:first-child{object-position:left}', 'structural CSS selector'),
            ('img:nth-child(2){width:70%}', 'structural CSS selector'),
            ('img:not(button > img){height:80px}', 'structural CSS selector'),
            ('button:hover > img{width:70%}', 'structural CSS selector'),
            ('.gallery-grid button > span + img{width:70%}', 'structural CSS selector'),
            ('.gallery-grid img:hover{height:80px}button > img{width:70%}', 'structural CSS selector'),
            ('@media(max-width:800px){.gallery-grid img{height:80px}}button > img{width:70%}', 'structural CSS selector'),
            ('img:last-child{object-position:left}', 'structural CSS selector'),
            ('img:nth-of-type(2){width:70%}', 'structural CSS selector'),
            ('.gallery-photo:last-child{object-position:left}', 'structural CSS selector'),
            ('@import url("/extra.css");', 'resolution of @import CSS'),
            ('@scope (.gallery-grid){img{aspect-ratio:1/2}}', 'resolution of @scope CSS'),
            ('.gallery-grid{& img{aspect-ratio:1/2}}', 'nested CSS selectors'),
        ]
        for css, message in styles:
            with self.subTest(css=css):
                html = ('<head><meta name="viewport" content="width=device-width, initial-scale=1">'
                        '<style>' + css + '</style></head><body class="project-page">'
                        '<div class="gallery-grid"><button><img class="gallery-photo" src="/assets/photo.webp"></button></div></body>')
                page.write_text(html)
                with self.assertRaisesRegex(ValueError, message), patch.object(Image.Image, 'save', side_effect=AssertionError('must not encode')):
                    prepare_public_assets(self.output)
                self.assertEqual(page.read_text(), html)

        # Unknown structural pseudos on a disjoint tag/class cannot style this
        # image; they must not block otherwise supported current stylesheets.
        context = CaseImageContexts('<body class="project-page"><div class="gallery-grid"><img src="/assets/photo.webp"></div></body>')
        rules = image_style_rules('.service-row:last-child{border:0}a:nth-of-type(2){width:30%}')
        self.assertEqual(case_image_style(rules, next(iter(context.paths.values()))), {})

    def test_unresolved_stylesheets_fail_closed_before_picture_fallback(self):
        Image.new('RGB', (800, 600), '#258878').save(self.output / 'assets/photo.webp')
        page = self.output / 'index.html'
        for href in ('https://example.test/remote.css', '//example.test/remote.css', '/missing.css'):
            with self.subTest(href=href):
                html = ('<head><meta name="viewport" content="width=device-width, initial-scale=1">'
                        '<link rel="stylesheet" href="' + href + '">'
                        '<style>button > img{width:70%}</style></head><body class="project-page">'
                        '<div class="gallery-grid"><button><img src="/assets/photo.webp"></button></div></body>')
                page.write_text(html)
                with self.assertRaisesRegex(ValueError, 'Case picture wrapper requires'), patch.object(Image.Image, 'save', side_effect=AssertionError('must not encode')):
                    prepare_public_assets(self.output)
                self.assertEqual(page.read_text(), html)

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
