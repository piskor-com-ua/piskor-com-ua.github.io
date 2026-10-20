"""Add DPR-sized AVIF candidates for the remaining measured PSI image findings."""
from hashlib import sha256
from html import escape, unescape
from pathlib import Path
import json
import math
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from PIL import Image, ImageOps, __version__ as PILLOW_VERSION

FINDINGS_FILE = Path(__file__).with_name('mobile-image-delivery-findings.json')
BASELINE_REVISION = '5e3652ef22931b994269493376f1d13fbebeeab7'
VIEWPORT_WIDTH = 412
DEVICE_SCALE_FACTOR = 1.75
QUALITY = 45
MINIMUM_QUALITY = 28
QUALITY_FALLBACKS = (55, 50, 45, 42, 40, 38, 36, 34, 32, 30, 28)
# Lighthouse 13.5 ImageDelivery thresholds: 1/6 byte per pixel for AVIF,
# 4 KiB for format savings, and 12 KiB for responsive images with breakpoints.
AVIF_TARGET_BYTES_PER_PIXEL = 1 / 6
FORMAT_SAVINGS_THRESHOLD = 4096
RESPONSIVE_SAVINGS_THRESHOLD = 12 * 1024
SCRIPT_PROFILE = (f'mobile-image-delivery-v1:pillow-{PILLOW_VERSION}:quality-{QUALITY}:'
                 'speed-6:threads-2')
PICTURE = re.compile(r'<picture\b[^>]*>.*?</picture>', re.S)
SOURCE = re.compile(r'<source\b[^>]*>', re.S)
IMAGE = re.compile(r'<img\b[^>]*>', re.S)
LINK = re.compile(r'<link\b[^>]*>', re.S)
LEGACY_GALLERY_PREFIX = '/assets/responsive/portfolio/'
GALLERY_PREFIX = '/assets/responsive/case-media/portfolio/'
COVER_PREFIX = '/assets/responsive/case-cover/portfolio/'
GALLERY_SELECTORS = {
    'figure > button > picture > img',
    'div.gallery-grid > figure > picture > img',
}
COVER_SELECTOR = 'main#main > figure.project-cover > picture > img'
CATALOG_SELECTOR = 'a.portfolio-card > div.portfolio-card-image > picture > img.portfolio-card-cover'


def _attributes(tag):
    return {key: unescape(value) for key, value in re.findall(r'([\w-]+)="([^"]*)"', tag)}


def _replace_attribute(tag, name, value):
    replacement = name + '="' + escape(str(value), quote=True) + '"'
    pattern = re.compile(r'(?<![\w-])' + re.escape(name) + r'\s*=\s*(["\']).*?\1', re.S)
    if pattern.search(tag):
        return pattern.sub(lambda _: replacement, tag, count=1)
    return tag[:-1] + ' ' + replacement + '>'


def load_findings(path=FINDINGS_FILE):
    manifest = json.loads(Path(path).read_text())
    routes = manifest.get('routes')
    findings = [item for items in (routes or {}).values() for item in items]
    resources = [item.get('resource_path') for item in findings]
    if (manifest.get('baseline_revision') != BASELINE_REVISION or
            manifest.get('lighthouse_version') != '13.5.0' or
            manifest.get('emulation') != {'viewport_width_css_px': VIEWPORT_WIDTH,
                                          'device_scale_factor': DEVICE_SCALE_FACTOR} or
            manifest.get('route_count') != 22 or len(routes or {}) != 22 or
            manifest.get('baseline_finding_count') != 39 or
            manifest.get('finding_count') != 40 or len(findings) != 40 or
            manifest.get('unique_resource_count') != 34 or len(set(resources)) != 34 or
            manifest.get('supplemental_audit', {}).get('additional_findings') != 1 or
            manifest.get('supplemental_audit', {}).get('routes_checked') != 22 or
            any(not route.startswith(('/portfolio/', '/en/portfolio/')) or not route.endswith('/')
                for route in (routes or {})) or
            any(not isinstance(item.get('estimated_savings_bytes'), int) or
                item['estimated_savings_bytes'] <= 0 or
                not item.get('resource_path', '').startswith('/assets/responsive/') or
                not item['resource_path'].endswith('.avif') or
                not item.get('current_resource_path', '').startswith('/assets/responsive/') or
                not item['current_resource_path'].endswith('.avif') or
                item.get('node_selector') not in GALLERY_SELECTORS | {COVER_SELECTOR, CATALOG_SELECTOR} or
                not item.get('node_label') or
                '?' in item['resource_path'] or '#' in item['resource_path']
                for item in findings)):
        raise ValueError('Unexpected mobile image-delivery findings manifest')
    for route, items in routes.items():
        paths = [item['resource_path'] for item in items]
        if len(paths) != len(set(paths)):
            raise ValueError('Duplicate measured image resource on ' + route)
        current_paths = [item['current_resource_path'] for item in items]
        if len(current_paths) != len(set(current_paths)):
            raise ValueError('Duplicate mapped image resource on ' + route)
        for item in items:
            expected = item['resource_path']
            selector = item['node_selector']
            if expected.startswith(LEGACY_GALLERY_PREFIX):
                if selector in GALLERY_SELECTORS:
                    expected = expected.replace(LEGACY_GALLERY_PREFIX, GALLERY_PREFIX, 1)
                elif selector == COVER_SELECTOR:
                    expected = expected.replace(LEGACY_GALLERY_PREFIX, COVER_PREFIX, 1)
                elif selector != CATALOG_SELECTOR:
                    raise ValueError('Legacy image has an unsupported PSI element: ' + selector)
            if item['current_resource_path'] != expected:
                raise ValueError('PSI image mapping does not match its element role on ' + route)
    return manifest


def _current_resource_path(finding):
    """Return the current-main URL for a baseline PSI node, preserving its role."""
    return finding['current_resource_path']


def _first_sizes_expression(sizes):
    depth = 0
    end = len(sizes)
    for index, char in enumerate(sizes):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif char == ',' and depth == 0:
            end = index
            break
    first = sizes[:end].strip()
    media = re.match(r'^\([^)]*\)\s*(.+)$', first, re.S)
    if not media:
        raise ValueError('Measured image sizes has no mobile media condition')
    return media.group(1).strip()


def _evaluate_calc(expression, viewport_width):
    value = expression.strip()
    if value == '100vw':
        return float(viewport_width)
    calc = re.fullmatch(r'calc\(\s*([\d.]+)vw\s*(?:-\s*([\d.]+)px)?\s*\)', value)
    if not calc:
        raise ValueError('Unrecognized mobile image calc size: ' + expression)
    result = float(calc.group(1)) * viewport_width / 100
    return result - float(calc.group(2) or 0)


def mobile_css_image_width(sizes, viewport_width=VIEWPORT_WIDTH):
    expression = _first_sizes_expression(sizes)
    if expression.startswith('max('):
        calc = re.search(r'calc\([^)]*\)', expression)
        minimum = re.search(r'min\(\s*([\d.]+)vw\s*,\s*([\d.]+)px\s*\)', expression)
        if not calc or not minimum:
            raise ValueError('Unrecognized measured max/min image size: ' + expression)
        calc_width = _evaluate_calc(calc.group(0), viewport_width)
        min_width = min(float(minimum.group(1)) * viewport_width / 100,
                        float(minimum.group(2)))
        return max(calc_width, min_width)
    return _evaluate_calc(expression, viewport_width)


def _local_asset(output, reference):
    output = Path(output).resolve()
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/assets/'):
        raise ValueError('Mobile delivery source must be a local asset: ' + reference)
    target = output / parsed.path.lstrip('/')
    if (not target.is_file() or target.is_symlink() or
            not target.resolve().is_relative_to((output / 'assets').resolve())):
        raise ValueError('Missing or unsafe mobile delivery asset: ' + reference)
    return target


def _srcset_entries(srcset):
    entries = []
    for entry in srcset.split(','):
        parts = entry.strip().split()
        if len(parts) != 2 or not re.fullmatch(r'\d+w', parts[1]):
            raise ValueError('Unrecognized mobile AVIF srcset')
        entries.append((parts[0], int(parts[1][:-1])))
    return entries


def _original_image(output, image_tag):
    attrs = _attributes(image_tag)
    entries = []
    for entry in attrs.get('srcset', '').split(','):
        parts = entry.strip().split()
        if len(parts) == 2 and re.fullmatch(r'\d+w', parts[1]):
            entries.append((parts[0], int(parts[1][:-1])))
    reference = max(entries, key=lambda item: item[1])[0] if entries else attrs.get('src', '')
    return _local_asset(output, reference)


def _candidate_file(output, resource_path, original_path, width, quality):
    source_bytes = original_path.read_bytes()
    profile = f'{SCRIPT_PROFILE}:width-{width}:quality-{quality}'
    digest = sha256(profile.encode() + b'\0' + source_bytes).hexdigest()
    cache = output.parent / 'output' / 'image-cache' / 'mobile-image-delivery-v1'
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / (digest + '.avif')
    with Image.open(original_path) as opened:
        original = ImageOps.exif_transpose(opened).convert('RGB')
    actual_width = min(width, original.width)
    target_size = (actual_width, max(1, round(original.height * actual_width / original.width)))
    valid = False
    if cached.is_file():
        try:
            with Image.open(cached) as image:
                valid = image.format == 'AVIF' and image.size == target_size
                image.verify()
        except (OSError, ValueError):
            valid = False
    if not valid:
        resized = original if original.size == target_size else original.resize(
            target_size, Image.Resampling.LANCZOS)
        with tempfile.NamedTemporaryFile(dir=cache, suffix='.avif', delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            resized.save(temporary_path, 'AVIF', quality=quality, speed=6, max_threads=2)
            temporary_path.replace(cached)
        finally:
            temporary_path.unlink(missing_ok=True)
    requested = Path(resource_path)
    match = re.search(r'-(\d+)\.avif$', requested.name)
    if not match:
        raise ValueError('Measured AVIF URL has no width suffix: ' + resource_path)
    stem = requested.name[:match.start()]
    target = output / requested.parent.as_posix().lstrip('/') / f'{stem}-{actual_width}-q{quality}.avif'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, target)
    with Image.open(target) as image:
        if image.format != 'AVIF' or image.size != target_size:
            raise ValueError('Generated mobile image candidate has an unexpected raster size')
        image.verify()
    return target, actual_width


def _psi_image_delivery_savings(image_path, display_dimensions, has_responsive_breakpoints):
    with Image.open(image_path) as image:
        image_pixels = image.width * image.height
    image_bytes = image_path.stat().st_size
    format_savings = max(0, round(image_bytes - AVIF_TARGET_BYTES_PER_PIXEL * image_pixels))
    display_pixels = display_dimensions[0] * display_dimensions[1]
    responsive_savings = round(max(0, 1 - display_pixels / image_pixels) * image_bytes)
    responsive_threshold = (RESPONSIVE_SAVINGS_THRESHOLD if has_responsive_breakpoints
                           else FORMAT_SAVINGS_THRESHOLD)
    return format_savings, responsive_savings, responsive_threshold


def _profile_picture(output, route, html, picture, resource_path, manifest, finding=None):
    avif_sources = []
    for tag in SOURCE.findall(picture):
        attrs = _attributes(tag)
        if attrs.get('type') != 'image/avif':
            continue
        entries = _srcset_entries(attrs.get('srcset', ''))
        if any(urlsplit(url).path == resource_path for url, _ in entries):
            avif_sources.append((tag, attrs, entries))
    if len(avif_sources) != 1:
        raise ValueError(f'{route}: expected exactly one AVIF picture source for {resource_path}')
    source_tag, source_attrs, entries = avif_sources[0]
    image_match = IMAGE.search(picture)
    if not image_match:
        raise ValueError(route + ': measured picture has no image fallback')
    source_path = _local_asset(output, resource_path)
    with Image.open(source_path) as selected:
        selected_width = selected.width
    css_width = mobile_css_image_width(source_attrs.get('sizes', ''))
    desired_width = math.ceil(css_width * manifest['emulation']['device_scale_factor'])
    original_path = _original_image(output, image_match[0])
    with Image.open(original_path) as original:
        candidate_width = min(desired_width, selected_width, original.width)
    namespace = resource_path.split('/')[3]
    source_quality = 50 if namespace == 'case-cover' else 60
    preferred_quality = 45 if candidate_width >= selected_width * 0.8 else source_quality
    with Image.open(original_path) as original:
        display_width = math.ceil(css_width)
        display_height = round(display_width * original.height / original.width)
    display_dimensions = ((finding or {}).get('reported_display_dimensions_px') or
                          [display_width, display_height])
    quality_levels = [preferred_quality]
    quality_levels.extend(value for value in QUALITY_FALLBACKS
                          if MINIMUM_QUALITY <= value < preferred_quality)
    # All measured nodes came from <picture>; Lighthouse applies its larger
    # responsive-breakpoint savings threshold to these candidates.
    has_breakpoints = True
    selected_candidate = None
    for quality in dict.fromkeys(quality_levels):
        target, actual_width = _candidate_file(output, resource_path, original_path,
                                               candidate_width, quality)
        format_savings, responsive_savings, responsive_threshold = _psi_image_delivery_savings(
            target, display_dimensions, has_breakpoints)
        if (format_savings <= FORMAT_SAVINGS_THRESHOLD and
                responsive_savings <= responsive_threshold):
            selected_candidate = (target, actual_width, quality)
            break
    if selected_candidate is None:
        raise ValueError(f'{route}: image {resource_path} cannot meet PSI delivery thresholds '
                         'without going below the reviewed AVIF quality floor')
    target, actual_width, quality = selected_candidate
    candidate = '/' + target.relative_to(output).as_posix()
    updated = [(url, width) for url, width in entries if width != actual_width]
    updated.append((candidate, actual_width))
    updated.sort(key=lambda item: item[1])
    srcset = ', '.join(url + ' ' + str(width) + 'w' for url, width in updated)
    if any(widths == actual_width and url != candidate for url, widths in entries):
        raise ValueError(route + ': conflicting candidate width ' + str(actual_width))
    new_source = _replace_attribute(source_tag, 'srcset', srcset)
    if source_tag == new_source and candidate not in source_tag:
        raise ValueError(route + ': mobile image candidate was not added')
    amended = html.replace(source_tag, new_source, 1)
    # Keep any eager cover preload byte-for-byte aligned with its source set.
    for link_tag in LINK.findall(amended):
        attrs = _attributes(link_tag)
        if attrs.get('imagesrcset') == source_attrs.get('srcset'):
            amended = amended.replace(link_tag, _replace_attribute(link_tag, 'imagesrcset', srcset), 1)
    return amended, actual_width, quality


def _route_page(output, route):
    return output / route.lstrip('/') / 'index.html'


def prepare_mobile_image_delivery(output, manifest_path=FINDINGS_FILE):
    output = Path(output).resolve()
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only a generated Pages artifact may be optimized')
    manifest = load_findings(manifest_path)
    candidates = set()
    qualities = set()
    changed_pages = 0
    for route, findings in manifest['routes'].items():
        page = _route_page(output, route)
        if not page.is_file():
            raise ValueError('Missing measured mobile image-delivery route: ' + route)
        original_html = page.read_text()
        html = original_html
        for finding in findings:
            resource_path = _current_resource_path(finding)
            matching = [picture for picture in PICTURE.findall(html)
                        if any(urlsplit(url).path == resource_path
                               for source in SOURCE.findall(picture)
                               if _attributes(source).get('type') == 'image/avif'
                               for url, _ in _srcset_entries(_attributes(source).get('srcset', '')))]
            if len(matching) != 1:
                raise ValueError(f'{route}: expected exactly one picture for {resource_path}')
            html, width, quality = _profile_picture(output, route, html, matching[0],
                                                    resource_path, manifest, finding)
            candidates.add((resource_path, width, quality))
            qualities.add(quality)
        if html != original_html:
            page.write_text(html)
            changed_pages += 1
    validate_mobile_image_delivery(output, manifest)
    return {'routes': len(manifest['routes']), 'findings': manifest['finding_count'],
            'unique_resources': len({item['resource_path'] for values in manifest['routes'].values()
                                     for item in values}),
            'candidate_profiles': len(candidates), 'qualities': sorted(qualities),
            'changed_pages': changed_pages}


def validate_mobile_image_delivery(output, manifest=None):
    output = Path(output).resolve()
    manifest = manifest or load_findings()
    for route, findings in manifest['routes'].items():
        page = _route_page(output, route)
        if not page.is_file():
            raise ValueError('Missing measured mobile image-delivery route: ' + route)
        html = page.read_text()
        for finding in findings:
            resource_path = _current_resource_path(finding)
            matches = []
            for picture in PICTURE.findall(html):
                for source in SOURCE.findall(picture):
                    attrs = _attributes(source)
                    if attrs.get('type') != 'image/avif':
                        continue
                    entries = _srcset_entries(attrs.get('srcset', ''))
                    if any(urlsplit(url).path == resource_path for url, _ in entries):
                        matches.append((attrs, entries))
            if len(matches) != 1:
                raise ValueError(f'{route}: measured source disappeared or is duplicated: {resource_path}')
            attrs, entries = matches[0]
            css_width = mobile_css_image_width(attrs.get('sizes', ''))
            desired = math.ceil(css_width * manifest['emulation']['device_scale_factor'])
            image = _local_asset(output, resource_path)
            with Image.open(image) as opened:
                selected_width = opened.width
            picture = next(picture for picture in PICTURE.findall(html)
                           if any(urlsplit(url).path == resource_path
                                  for source in SOURCE.findall(picture)
                                  if _attributes(source).get('type') == 'image/avif'
                                  for url, _ in _srcset_entries(_attributes(source).get('srcset', ''))))
            image_match = IMAGE.search(picture)
            if not image_match:
                raise ValueError(route + ': measured picture has no image fallback')
            original_path = _original_image(output, image_match[0])
            with Image.open(original_path) as original:
                target_width = min(desired, selected_width, original.width)
            generated = [(url, width) for url, width in entries
                         if width <= target_width and re.search(
                             r'-' + str(width) + r'-q\d+\.avif$', urlsplit(url).path)]
            if len(generated) != 1 or generated[0][1] != target_width:
                raise ValueError(f'{route}: no exact DPR candidate for {resource_path}')
            candidate_path = _local_asset(output, generated[0][0])
            with Image.open(candidate_path) as candidate:
                if candidate.width != target_width:
                    raise ValueError(f'{route}: candidate width differs from the srcset descriptor')
                candidate.verify()
            format_savings, responsive_savings, _ = _psi_image_delivery_savings(
                candidate_path, finding['reported_display_dimensions_px'],
                has_responsive_breakpoints=True)
            if format_savings > FORMAT_SAVINGS_THRESHOLD:
                raise ValueError(f'{route}: AVIF compression still exceeds the PSI image budget '
                                 f'({format_savings} bytes): {resource_path}')
            if responsive_savings > RESPONSIVE_SAVINGS_THRESHOLD:
                raise ValueError(f'{route}: responsive image still exceeds the PSI image budget '
                                 f'({responsive_savings} bytes): {resource_path}')
            source_set = attrs['srcset']
            referencing_preloads = []
            for link in LINK.findall(html):
                imagesrcset = _attributes(link).get('imagesrcset', '')
                if imagesrcset and any(urlsplit(url).path == resource_path
                                       for url, _ in _srcset_entries(imagesrcset)):
                    referencing_preloads.append(link)
            if referencing_preloads and any(_attributes(link).get('imagesrcset') != source_set
                                            for link in referencing_preloads):
                raise ValueError(f'{route}: measured preload does not match its AVIF source')
    return True
