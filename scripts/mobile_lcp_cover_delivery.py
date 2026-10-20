"""Add one visually reviewed mobile cover candidate for the LCP-failing subset."""
from hashlib import sha256
from html import escape
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from PIL import Image, ImageOps, __version__ as PILLOW_VERSION

from deferred_mobile_media import TARGETS_FILE, lcp_target_routes
from first_paint import generated_root

WIDTH = 832
QUALITY = 32
MARKER = 'data-piskor-mobile-lcp-cover'
PROFILE = (f'mobile-lcp-cover-v1:pillow-{PILLOW_VERSION}:width-{WIDTH}:'
           f'quality-{QUALITY}:speed-6:threads-2')


def _attributes(tag):
    return dict(re.findall(r'([\w-]+)="([^"]*)"', tag))


def _insert_candidate(srcset, candidate):
    entries = [entry.strip() for entry in srcset.split(',') if entry.strip()]
    parsed = []
    for entry in entries:
        parts = entry.split()
        if len(parts) != 2 or not re.fullmatch(r'\d+w', parts[1]):
            raise ValueError('Unrecognized responsive cover srcset')
        parsed.append((int(parts[1][:-1]), entry))
    if any(width == WIDTH for width, _ in parsed):
        raise ValueError('Mobile LCP width already exists in source candidates')
    position = next((index for index, (width, _) in enumerate(parsed) if width > WIDTH), len(parsed))
    parsed.insert(position, (WIDTH, candidate + ' ' + str(WIDTH) + 'w'))
    return ', '.join(entry for _, entry in parsed)


def _first_cover_picture(html):
    if 'data-case-cover-preload' in html:
        figure = re.search(r'<figure\b[^>]*class="[^"]*\bproject-cover\b[^"]*"[^>]*>.*?</figure>',
                           html, re.S)
        if not figure:
            raise ValueError('LCP route has no case cover figure')
        pictures = re.findall(r'<picture\b[^>]*>.*?</picture>', figure[0], re.S)
        if len(pictures) != 1:
            raise ValueError('Case cover must contain one picture')
        return pictures[0], 'data-case-cover-preload'
    if 'data-catalog-cover-preload' in html:
        pictures = re.findall(r'<picture\b[^>]*>.*?</picture>', html, re.S)
        for picture in pictures:
            image = re.search(r'<img\b[^>]*>', picture)
            if image and 'portfolio-card-cover' in _attributes(image[0]).get('class', '').split():
                return picture, 'data-catalog-cover-preload'
        raise ValueError('LCP catalog route has no first cover card')
    raise ValueError('LCP route has no reviewed image preload')


def _cover_tags(html):
    picture, preload_marker = _first_cover_picture(html)
    source_match = re.search(r'<source\b[^>]*type="image/avif"[^>]*>', picture)
    image_match = re.search(r'<img\b[^>]*>', picture)
    if not source_match or not image_match:
        raise ValueError('LCP cover must use an AVIF source and an image fallback')
    preload_matches = re.findall(r'<link\b[^>]*\b' + preload_marker + r'\b[^>]*>', html)
    if len(preload_matches) != 1:
        raise ValueError('LCP cover needs exactly one matching preload')
    source = source_match[0]
    preload = preload_matches[0]
    source_attrs = _attributes(source)
    preload_attrs = _attributes(preload)
    if (source_attrs.get('srcset') != preload_attrs.get('imagesrcset') or
            source_attrs.get('sizes') != preload_attrs.get('imagesizes') or
            preload_attrs.get('fetchpriority') != 'high'):
        raise ValueError('LCP preload must match the selected mobile image candidates')
    return picture, source, image_match[0], preload, preload_marker


def _candidate_file(output, source, image_tag):
    attrs = _attributes(image_tag)
    source_entries = [entry.strip().split() for entry in attrs.get('srcset', '').split(',')
                      if entry.strip()]
    if source_entries:
        if any(len(entry) != 2 or not re.fullmatch(r'\d+w', entry[1]) for entry in source_entries):
            raise ValueError('Unrecognized full-resolution source srcset')
        image_reference = max(source_entries, key=lambda entry: int(entry[1][:-1]))[0]
    else:
        image_reference = attrs.get('src', '')
    image_url = urlsplit(image_reference)
    if image_url.scheme or image_url.netloc or not image_url.path.startswith('/assets/'):
        raise ValueError('LCP source image must be a local source asset')
    image_path = output / image_url.path.lstrip('/')
    if not image_path.is_file():
        raise ValueError('Missing LCP source image: ' + image_url.path)
    first_candidate = _attributes(source).get('srcset', '').split(',')[0].strip().split()
    if len(first_candidate) != 2:
        raise ValueError('LCP AVIF srcset has no first candidate')
    avif_path = urlsplit(first_candidate[0]).path
    prefix = '/assets/responsive/case-cover/'
    if not avif_path.startswith(prefix):
        raise ValueError('Unexpected LCP responsive-image namespace')
    relative_avif = Path(avif_path[len('/assets/'):])
    namespace = relative_avif.parts[2] if len(relative_avif.parts) > 3 else ''
    if namespace not in {'portfolio', 'catalog'}:
        raise ValueError('Unexpected LCP cover namespace')
    folder = output / 'assets' / 'responsive' / 'case-cover' / namespace
    folder = folder.joinpath(*relative_avif.parts[3:-1])
    stem = re.sub(r'-(?:480|640|768|960|1080|1280|1440|2000|2100|2200|2970)$',
                  '', relative_avif.stem)
    target = folder / (stem + '-' + str(WIDTH) + '.avif')

    cache = output.parent / 'output' / 'image-cache' / 'mobile-lcp-cover-v1'
    cache.mkdir(parents=True, exist_ok=True)
    original = image_path.read_bytes()
    digest = sha256(PROFILE.encode() + b'\0' + original).hexdigest()
    cached = cache / (digest + '.avif')
    valid = False
    if cached.is_file():
        try:
            with Image.open(cached) as image:
                valid = image.format == 'AVIF' and image.width == WIDTH
                image.verify()
        except (OSError, ValueError):
            valid = False
    if not valid:
        with Image.open(BytesIO(original)) as opened:
            resized = ImageOps.exif_transpose(opened).convert('RGB')
            if resized.width <= WIDTH:
                raise ValueError('LCP source is too small for the mobile candidate')
            height = round(resized.height * WIDTH / resized.width)
            resized = resized.resize((WIDTH, height), Image.Resampling.LANCZOS)
            with tempfile.NamedTemporaryFile(dir=cache, suffix='.avif', delete=False) as temporary:
                temporary_path = Path(temporary.name)
            try:
                resized.save(temporary_path, 'AVIF', quality=QUALITY, speed=6, max_threads=2)
                temporary_path.replace(cached)
            finally:
                temporary_path.unlink(missing_ok=True)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, target)
    return target


def _replace_attribute(tag, name, value):
    pattern = r'(\b' + re.escape(name) + r'=")[^"]*(")'
    amended, count = re.subn(pattern, lambda match: match[1] + escape(value, quote=True) + match[2], tag, count=1)
    if count != 1:
        raise ValueError('Missing ' + name + ' on responsive LCP cover')
    return amended


def _prepare_page(output, route):
    page = output / route.lstrip('/') / 'index.html'
    if not page.is_file():
        raise ValueError('Missing measured LCP route: ' + route)
    html = page.read_text()
    if MARKER in html:
        validate_mobile_lcp_cover(output, page, html)
        return page, html, 0
    picture, source, image, preload, _ = _cover_tags(html)
    target = _candidate_file(output, source, image)
    candidate = '/' + target.relative_to(output).as_posix()
    amended_srcset = _insert_candidate(_attributes(source)['srcset'], candidate)
    amended_source = _replace_attribute(source, 'srcset', amended_srcset)
    amended_source = amended_source[:-1] + ' ' + MARKER + '>'
    amended_preload = _replace_attribute(preload, 'imagesrcset', amended_srcset)
    if html.count(source) != 1 or html.count(preload) != 1:
        raise ValueError('LCP cover source/preload tags must be unique')
    html = html.replace(source, amended_source, 1).replace(preload, amended_preload, 1)
    validate_mobile_lcp_cover(output, page, html)
    return page, html, target.stat().st_size


def restore_mobile_lcp_cover(html):
    """Remove only this route-scoped candidate before copy-parity comparison."""
    marked = re.findall(r'<source\b[^>]*\b' + MARKER + r'\b[^>]*>', html)
    if not marked:
        return html
    if len(marked) != 1:
        raise ValueError('Cannot normalize multiple mobile LCP profiles')
    source = marked[0]
    picture, expected_source, _, preload, _ = _cover_tags(html)
    if source != expected_source:
        raise ValueError('Cannot normalize a mobile LCP profile on a non-primary image')

    def remove_candidate(srcset):
        entries = [entry.strip() for entry in srcset.split(',') if entry.strip()]
        retained = []
        removed = 0
        for entry in entries:
            parts = entry.split()
            if len(parts) == 2 and parts[1] == str(WIDTH) + 'w' and urlsplit(parts[0]).path.endswith(
                    '-' + str(WIDTH) + '.avif'):
                removed += 1
            else:
                retained.append(entry)
        if removed != 1:
            raise ValueError('Cannot find the exact generated mobile candidate to normalize')
        return ', '.join(retained)

    source_attrs = _attributes(source)
    preload_attrs = _attributes(preload)
    clean_source = _replace_attribute(source, 'srcset', remove_candidate(source_attrs['srcset']))
    clean_source = re.sub(r'\s+' + MARKER + r'(?=\s|>)', '', clean_source)
    clean_preload = _replace_attribute(preload, 'imagesrcset',
                                       remove_candidate(preload_attrs['imagesrcset']))
    if clean_source == source or clean_preload == preload:
        raise ValueError('Mobile candidate normalization did not change both source and preload')
    return html.replace(source, clean_source, 1).replace(preload, clean_preload, 1)


def prepare_mobile_lcp_covers(output):
    output = generated_root(output)
    updates = [_prepare_page(output, route) for route in sorted(lcp_target_routes())]
    for page, html, _ in updates:
        page.write_text(html)
    return {'routes': len(updates), 'unique_candidates': len({
        _attributes(re.search(r'<source\b[^>]*' + MARKER + r'[^>]*>', html)[0])['srcset']
        for _, html, _ in updates}), 'width': WIDTH, 'quality': QUALITY}


def validate_mobile_lcp_cover(output, page, html):
    output = generated_root(output)
    route = '/' + Path(page).relative_to(output).as_posix()[:-len('index.html')]
    target = route in lcp_target_routes()
    if not target:
        if MARKER in html:
            raise ValueError('Mobile LCP cover profile was added outside its measured routes')
        return
    picture, source, _, preload, _ = _cover_tags(html)
    marked = re.findall(r'<source\b[^>]*\b' + MARKER + r'\b[^>]*>', html)
    if len(marked) != 1 or marked[0] != source:
        raise ValueError('LCP AVIF source is missing its exact reviewed profile')
    srcset = _attributes(source).get('srcset', '')
    preload_set = _attributes(preload).get('imagesrcset', '')
    if not srcset or srcset != preload_set:
        raise ValueError('Mobile LCP preload and picture candidates do not match')
    candidates = []
    for entry in srcset.split(','):
        parts = entry.strip().split()
        if len(parts) != 2:
            raise ValueError('Unrecognized mobile cover candidate')
        if parts[1] == str(WIDTH) + 'w':
            candidates.append(parts[0])
    if len(candidates) != 1:
        raise ValueError('Expected one 832w mobile LCP candidate')
    path = urlsplit(candidates[0]).path
    if not path.startswith('/assets/responsive/case-cover/'):
        raise ValueError('Mobile LCP candidate escaped the responsive image directory')
    image_path = output / path.lstrip('/')
    if not image_path.is_file():
        raise ValueError('Missing generated mobile LCP candidate')
    with Image.open(image_path) as opened:
        if opened.format != 'AVIF' or opened.width != WIDTH:
            raise ValueError('Mobile LCP candidate has the wrong format or dimensions')
        opened.verify()
    if 'fetchpriority="high"' not in picture and 'class="portfolio-card-cover"' not in picture:
        raise ValueError('Mobile LCP candidate must remain attached to the eager cover')
