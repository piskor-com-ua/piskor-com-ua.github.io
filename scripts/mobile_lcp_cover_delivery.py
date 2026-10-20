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

from deferred_mobile_media import (TARGETS_FILE, critical_image_delivery_routes,
                                   lcp_target_routes)
from first_paint import generated_root

WIDTH = 832
QUALITY = 32
MARKER = 'data-piskor-mobile-lcp-cover'
PROFILE = (f'mobile-lcp-cover-v1:pillow-{PILLOW_VERSION}:width-{WIDTH}:'
           f'quality-{QUALITY}:speed-6:threads-2')
CATALOG_WIDTH = 640
CATALOG_QUALITY = 40
CATALOG_MAX_BYTES = 18_000
CATALOG_MARKER = 'data-piskor-mobile-critical-image'
CATALOG_PROFILE = (f'mobile-critical-catalog-image-v1:pillow-{PILLOW_VERSION}:'
                   f'width-{CATALOG_WIDTH}:quality-{CATALOG_QUALITY}:speed-6:threads-2')


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


def _replace_width_candidate(srcset, candidate, width):
    entries = [entry.strip() for entry in srcset.split(',') if entry.strip()]
    replaced = 0
    result = []
    for entry in entries:
        parts = entry.split()
        if len(parts) != 2 or not re.fullmatch(r'\d+w', parts[1]):
            raise ValueError('Unrecognized responsive image srcset')
        if parts[1] == str(width) + 'w':
            result.append(candidate + ' ' + str(width) + 'w')
            replaced += 1
        else:
            result.append(entry)
    if replaced != 1:
        raise ValueError(f'Expected one existing {width}w AVIF candidate')
    return ', '.join(result)


def _catalog_candidate_file(output, source, image_tag):
    image_attrs = _attributes(image_tag)
    source_entries = [entry.strip().split() for entry in image_attrs.get('srcset', '').split(',')
                      if entry.strip()]
    if not source_entries or any(len(entry) != 2 or not re.fullmatch(r'\d+w', entry[1])
                                 for entry in source_entries):
        raise ValueError('Critical catalog cover must retain responsive source images')
    source_reference = max(source_entries, key=lambda entry: int(entry[1][:-1]))[0]
    source_url = urlsplit(source_reference)
    if source_url.scheme or source_url.netloc or not source_url.path.startswith('/assets/'):
        raise ValueError('Critical catalog cover source must be a local image')
    source_path = output / source_url.path.lstrip('/')
    if not source_path.is_file():
        raise ValueError('Missing critical catalog cover source: ' + source_url.path)

    source_set = _attributes(source).get('srcset', '')
    avif_entries = [entry.strip().split() for entry in source_set.split(',') if entry.strip()]
    selected = [entry for entry in avif_entries
                if len(entry) == 2 and entry[1] == str(CATALOG_WIDTH) + 'w']
    if len(selected) != 1:
        raise ValueError('Critical catalog AVIF source needs one 640w candidate')
    existing_url = urlsplit(selected[0][0])
    prefix = '/assets/responsive/case-cover/catalog/'
    if existing_url.scheme or existing_url.netloc or not existing_url.path.startswith(prefix):
        raise ValueError('Critical catalog image escaped the reviewed cover directory')
    existing_path = output / existing_url.path.lstrip('/')
    if not existing_path.is_file():
        raise ValueError('Missing existing 640w catalog AVIF')
    with Image.open(existing_path) as existing:
        if existing.format != 'AVIF' or existing.width != CATALOG_WIDTH:
            raise ValueError('Existing 640w catalog candidate has unexpected dimensions')
        width, height = existing.size

    relative = Path(existing_url.path[len('/assets/'):])
    stem = re.sub(r'-\d+$', '', relative.stem)
    target = output / 'assets' / relative.parent / f'{stem}-{CATALOG_WIDTH}-q{CATALOG_QUALITY}.avif'
    cache = output.parent / 'output' / 'image-cache' / 'mobile-critical-catalog-image-v1'
    cache.mkdir(parents=True, exist_ok=True)
    original = source_path.read_bytes()
    digest = sha256(CATALOG_PROFILE.encode() + b'\0' + original).hexdigest()
    cached = cache / (digest + '.avif')
    valid = False
    if cached.is_file():
        try:
            with Image.open(cached) as image:
                valid = image.format == 'AVIF' and image.size == (width, height)
                image.verify()
            valid = valid and cached.stat().st_size <= CATALOG_MAX_BYTES
        except (OSError, ValueError):
            valid = False
    if not valid:
        with Image.open(BytesIO(original)) as opened:
            resized = ImageOps.exif_transpose(opened).convert('RGB')
            if abs(resized.width / resized.height - width / height) > 0.002:
                raise ValueError('Catalog image aspect ratio changed from its AVIF candidate')
            resized = resized.resize((width, height), Image.Resampling.LANCZOS)
            with tempfile.NamedTemporaryFile(dir=cache, suffix='.avif', delete=False) as temporary:
                temporary_path = Path(temporary.name)
            try:
                resized.save(temporary_path, 'AVIF', quality=CATALOG_QUALITY,
                             speed=6, max_threads=2)
                if temporary_path.stat().st_size > CATALOG_MAX_BYTES:
                    raise ValueError('Critical catalog AVIF exceeded its measured byte budget')
                temporary_path.replace(cached)
            finally:
                temporary_path.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, target)
    return target


def _catalog_cover_tags(html):
    picture, marker = _first_cover_picture(html)
    if marker != 'data-catalog-cover-preload':
        raise ValueError('Critical image delivery profile only supports catalog covers')
    source_match = re.search(r'<source\b[^>]*type="image/avif"[^>]*>', picture)
    image_match = re.search(r'<img\b[^>]*>', picture)
    preload_matches = re.findall(r'<link\b[^>]*\bdata-catalog-cover-preload\b[^>]*>', html)
    if not source_match or not image_match or len(preload_matches) != 1:
        raise ValueError('Critical catalog cover or matching preload is missing')
    source, image, preload = source_match[0], image_match[0], preload_matches[0]
    source_attrs, preload_attrs = _attributes(source), _attributes(preload)
    if (source_attrs.get('srcset') != preload_attrs.get('imagesrcset') or
            source_attrs.get('sizes') != preload_attrs.get('imagesizes') or
            preload_attrs.get('fetchpriority') != 'high'):
        raise ValueError('Critical catalog preload must exactly match the responsive cover')
    image_attrs = _attributes(image)
    if image_attrs.get('loading') != 'eager' or image_attrs.get('fetchpriority') != 'high':
        raise ValueError('Critical catalog cover must remain eager and high priority')
    return source, image, preload


def prepare_mobile_catalog_delivery_profiles(output):
    output = generated_root(output)
    routes = critical_image_delivery_routes()
    updates = []
    for route in sorted(routes):
        page = output / route.lstrip('/') / 'index.html'
        if not page.is_file():
            raise ValueError('Missing critical image delivery route: ' + route)
        html = page.read_text()
        if CATALOG_MARKER in html:
            validate_mobile_catalog_delivery(output, page, html)
            updates.append((page, html, 0))
            continue
        source, image, preload = _catalog_cover_tags(html)
        target = _catalog_candidate_file(output, source, image)
        candidate = '/' + target.relative_to(output).as_posix()
        srcset = _replace_width_candidate(_attributes(source)['srcset'], candidate, CATALOG_WIDTH)
        amended_source = _replace_attribute(source, 'srcset', srcset)
        amended_source = amended_source[:-1] + ' ' + CATALOG_MARKER + '>'
        amended_preload = _replace_attribute(preload, 'imagesrcset', srcset)
        if html.count(source) != 1 or html.count(preload) != 1:
            raise ValueError('Critical catalog cover and preload must be unique')
        amended = html.replace(source, amended_source, 1).replace(preload, amended_preload, 1)
        validate_mobile_catalog_delivery(output, page, amended)
        updates.append((page, amended, target.stat().st_size))
    for page, html, _ in updates:
        page.write_text(html)
    return {'routes': len(routes), 'unique_candidates': len({
        entry.split()[0]
        for _, html, _ in updates
        for entry in _attributes(re.search(r'<source\b[^>]*\b' + CATALOG_MARKER + r'[^>]*>', html)[0])['srcset'].split(',')
        if entry.strip().split()[-1] == str(CATALOG_WIDTH) + 'w'
    }), 'width': CATALOG_WIDTH, 'quality': CATALOG_QUALITY,
        'max_candidate_bytes': CATALOG_MAX_BYTES}


def validate_mobile_catalog_delivery(output, page, html):
    output = generated_root(output)
    route = '/' + Path(page).relative_to(output).as_posix()[:-len('index.html')]
    target = route in critical_image_delivery_routes()
    if not target:
        if CATALOG_MARKER in html:
            raise ValueError('Critical catalog delivery profile escaped its measured routes')
        return
    source, _, preload = _catalog_cover_tags(html)
    marked = re.findall(r'<source\b[^>]*\b' + CATALOG_MARKER + r'[^>]*>', html)
    if len(marked) != 1 or marked[0] != source:
        raise ValueError('Critical catalog source is missing its measured delivery profile')
    source_attrs, preload_attrs = _attributes(source), _attributes(preload)
    srcset = source_attrs.get('srcset', '')
    if not srcset or srcset != preload_attrs.get('imagesrcset'):
        raise ValueError('Critical catalog preload and source candidates do not match')
    candidates = [entry.strip().split()[0] for entry in srcset.split(',')
                  if entry.strip().split()[-1] == str(CATALOG_WIDTH) + 'w']
    if len(candidates) != 1:
        raise ValueError('Critical catalog cover needs one measured 640w candidate')
    path = urlsplit(candidates[0]).path
    if not path.startswith('/assets/responsive/case-cover/catalog/') or not path.endswith(
            f'-{CATALOG_WIDTH}-q{CATALOG_QUALITY}.avif'):
        raise ValueError('Critical catalog AVIF candidate has an unexpected path')
    image_path = output / path.lstrip('/')
    if not image_path.is_file() or image_path.stat().st_size > CATALOG_MAX_BYTES:
        raise ValueError('Critical catalog AVIF is missing or exceeds its measured byte budget')
    with Image.open(image_path) as image:
        if image.format != 'AVIF' or image.width != CATALOG_WIDTH:
            raise ValueError('Critical catalog AVIF has the wrong format or pixel width')
        image.verify()


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
