"""Prepare responsive public images without modifying any source media."""
from functools import lru_cache
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
from PIL import Image, ImageOps

IMG = re.compile(r'<img\b[^>]*>', re.I)
CARD_SIZES = '(max-width: 700px) calc(100vw - 48px), (min-width: 1956px) calc((100vw - 204px) / 2), calc((91vw - 28px) / 2)'


class Tag(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.attrs = {}
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.attrs = dict(attrs)


def attribute(markup, name, value):
    pattern = re.compile(r'(?<![\w-])' + re.escape(name) + r'\s*=\s*(["\']).*?\1', re.S)
    replacement = name + '="' + escape(str(value), quote=True) + '"'
    if pattern.search(markup):
        return pattern.sub(lambda _: replacement, markup)
    return markup[:-1] + ' ' + replacement + '>'


def prepare_public_assets(output):
    output = Path(output).resolve()
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only a generated Pages artifact may be prepared')

    @lru_cache(maxsize=None)
    def dimensions(reference):
        clean = reference.split('?')[0].split('#')[0]
        target = output / clean.lstrip('/')
        if not target.resolve().is_relative_to(output) or target.is_symlink():
            raise ValueError('Unsafe image: ' + reference)
        with Image.open(target) as image:
            return ImageOps.exif_transpose(image).size

    @lru_cache(maxsize=None)
    def card_variants(reference):
        target = output / reference.lstrip('/')
        width, height = dimensions(reference)
        # The path stays stable; the resource fingerprint changes with its bytes.
        stem = re.sub(r'-\d+$', '', target.stem)
        relative = target.parent.relative_to(output / 'assets')
        folder = output / 'assets' / 'responsive' / relative
        folder.mkdir(parents=True, exist_ok=True)
        variants = []
        with Image.open(target) as opened:
            original = ImageOps.exif_transpose(opened).convert('RGB')
            for size in sorted({min(width, size) for size in (480, 640, 960, 1440)}):
                if size == width:
                    url = reference
                else:
                    path = folder / (stem + '-' + str(size) + '.webp')
                    original.resize((size, round(height * size / width)), Image.Resampling.LANCZOS).save(
                        path, 'WEBP', quality=86, method=6)
                    url = '/' + path.relative_to(output).as_posix()
                variants.append((url, size))
        return variants

    count = 0
    for page in output.rglob('*.html'):
        def image_markup(match):
            nonlocal count
            markup = match.group(0)
            attrs = Tag(markup).attrs
            source = attrs.get('src', '')
            if not source.startswith('/assets/'):
                return markup
            width, height = dimensions(source)
            markup = attribute(attribute(markup, 'width', width), 'height', height)
            if 'portfolio-card-cover' in attrs.get('class', '').split():
                variants = card_variants(source)
                markup = attribute(markup, 'srcset', ', '.join(url + ' ' + str(w) + 'w' for url, w in variants))
                markup = attribute(markup, 'sizes', CARD_SIZES)
                count += 1
            elif attrs.get('srcset'):
                entries = []
                for entry in attrs['srcset'].split(','):
                    url, descriptor = entry.strip().split()
                    if descriptor.endswith('w') and url.startswith('/assets/'):
                        descriptor = str(dimensions(url)[0]) + 'w'
                    if (url, descriptor) not in entries:
                        entries.append((url, descriptor))
                # Remove equal-width alternatives: browsers require unique descriptors.
                unique = {}
                for url, descriptor in entries:
                    unique.setdefault(descriptor, url)
                markup = attribute(markup, 'srcset', ', '.join(url + ' ' + d for d, url in unique.items()))
            return markup
        page.write_text(IMG.sub(image_markup, page.read_text()))
    return {'responsive_cards': count, 'unique_covers': card_variants.cache_info().currsize}


def bundle_catalog_styles(output):
    """Preserve source order and shared grid rules while removing three requests."""
    output = Path(output)
    names = ['analytics-consent.css', 'style.css', 'portfolio.css', 'catalog.css']
    (output / 'catalog-bundle.css').write_text('\n'.join((output / name).read_text() for name in names))
    pattern = re.compile(r'<link\s+rel="stylesheet"\s+href="/(?:' +
                         '|'.join(re.escape(name) for name in names) + r')"\s*>')
    for page in output.rglob('*.html'):
        text = page.read_text()
        if 'catalog-page' not in text:
            continue
        first = True
        def bundled(match):
            nonlocal first
            if first:
                first = False
                return '<link rel="stylesheet" href="/catalog-bundle.css">'
            return ''
        page.write_text(pattern.sub(bundled, text))
