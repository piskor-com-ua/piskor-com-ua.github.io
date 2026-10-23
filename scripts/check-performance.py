"""Enforce media, discovery and accessibility contracts on the whole public artifact."""
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import hashlib
import json
import re
from PIL import Image
from agent_catalog import Document
from first_paint import (HOME_INLINE_PAGES, HOME_INLINE_MARKER, PAGE_INLINE_MARKER,
                         page_critical_profile, validate_home_inline_scripts, validate_page_inline_scripts)
from zabava_gallery_delivery import validate_zabava_gallery
from deferred_mobile_media import validate_deferred_mobile_media
from mobile_lcp_cover_delivery import validate_mobile_lcp_cover


def card_label_text(node):
    """Keep real text-node boundaries; Node.text() invents spaces between tags."""
    if isinstance(node, str):
        return node
    if node.tag in {'script', 'style'} or 'hidden' in node.attrs or node.attrs.get('aria-hidden') == 'true':
        return ''
    return ''.join(card_label_text(child) for child in node.children)


output = Path('_site')
catalog = json.loads((output / 'project-catalog.json').read_text())
top10_font_preload_routes = {
    route['route'].lstrip('/') + 'index.html' if route['route'].endswith('/')
    else route['route'].lstrip('/')
    for route in json.loads(Path('scripts/mobile-si-top10-routes.json').read_text())['routes']
}
assert catalog['version'] == 1 and catalog['projects']
pairs = {}
assert len({(p['id'], p['language']) for p in catalog['projects']}) == len(catalog['projects'])
for project in catalog['projects']:
    pairs.setdefault(project['id'], set()).add(project['language'])
    target = output / project['url'].lstrip('/') / 'index.html'
    document = Document(target.read_text()).root
    for section in project['sections']:
        fragment = urlsplit(section['url']).fragment
        assert document.find(lambda n: n.attrs.get('id') == fragment), section['url']
    assert project['name'] and project['summary'] and project['sections'], project['url']
assert all(languages == {'uk', 'en'} for languages in pairs.values())
assert (output / 'llms.txt').read_text().startswith('# PISKOR Architect\n')
assert all('https://piskor.com.ua' + p['url'] in (output / 'llms.txt').read_text() for p in catalog['projects'])

expected_catalog_orders = {}
for language, prefix in [('uk', ''), ('en', 'en/')]:
    localized = [project for project in catalog['projects'] if project['language'] == language]
    # Sort a composite unique key; never depend on a second sort preserving ties.
    ordered = sorted(localized, key=lambda project: (project['year'], project['id']), reverse=True)
    expected_catalog_orders[prefix + 'portfolio/index.html'] = [project['id'] for project in ordered]
    for year in {project['year'] for project in ordered}:
        expected_catalog_orders[prefix + 'portfolio/' + str(year) + '/index.html'] = [
            project['id'] for project in ordered if project['year'] == year]
checked_catalog_orders = set()

cards = 0
for page in output.rglob('*.html'):
    html = page.read_text()
    validate_zabava_gallery(output, page, html)
    validate_deferred_mobile_media(output, page, html)
    validate_mobile_lcp_cover(output, page, html)
    semantic_html = re.sub(
        r'<noscript data-piskor-deferred-media-fallback>.*?</noscript>',
        '', html, flags=re.S)
    root = Document(semantic_html).root
    external_agents = root.find(lambda n: n.tag == 'script' and urlsplit(n.attrs.get('src', '')).path == '/agent-tools.js')
    inline_controllers = root.find(lambda n: n.tag == 'script' and (HOME_INLINE_MARKER in n.attrs or PAGE_INLINE_MARKER in n.attrs))
    inline_agents = [node for node in inline_controllers if node.attrs.get(HOME_INLINE_MARKER, node.attrs.get(PAGE_INLINE_MARKER)) == 'agent-tools.js']
    if page.relative_to(output).as_posix() in HOME_INLINE_PAGES:
        validate_home_inline_scripts(output, page.read_text())
        assert all(HOME_INLINE_MARKER in node.attrs for node in inline_controllers), str(page) + ': wrong home inline marker'
        assert not external_agents and len(inline_agents) == 1, str(page) + ': home agent execution coverage'
    elif page_critical_profile(output, page, page.read_text()):
        validate_page_inline_scripts(output, page, page.read_text())
        assert all(PAGE_INLINE_MARKER in node.attrs for node in inline_controllers), str(page) + ': wrong page inline marker'
        assert not external_agents and len(inline_agents) == 1, str(page) + ': page agent execution coverage'
    else:
        assert not inline_controllers, str(page) + ': unmeasured page must retain external controllers'
        assert len(external_agents) <= 1, str(page) + ': duplicate external agent controller'
    agents = external_agents + inline_agents
    for rel, href in [('ard', '/.well-known/ard.json'), ('ai-catalog', '/.well-known/ai-catalog.json')]:
        discovery = root.find(lambda n: n.tag == 'link' and n.attrs.get('rel') == rel)
        assert len(discovery) == (1 if agents else 0), str(page) + ': discovery coverage'
        if discovery:
            assert discovery[0].attrs.get('href') == href
    early = root.find(lambda n: n.tag == 'script' and 'data-consent-inline' in n.attrs)
    assert len(early) == 1, str(page) + ': missing early consent controller'
    assert not root.find(lambda n: n.tag == 'script' and urlsplit(n.attrs.get('src', '')).path == '/analytics-consent.js')
    font_preloads = root.find(lambda n: n.tag == 'link' and n.attrs.get('rel') == 'preload' and n.attrs.get('as') == 'font')
    assert all(not n.attrs.get('media') for n in font_preloads), str(page) + ': original Roboto must remain available in both viewport modes'
    relative_page = page.relative_to(output).as_posix()
    if relative_page in {'engineering-automation/index.html', 'en/engineering-automation/index.html'}:
        from engineering_minification import validate_engineering_consent
        validate_engineering_consent(output, html)
    if relative_page in top10_font_preload_routes:
        regular_font = [node for node in font_preloads
                        if urlsplit(node.attrs.get('href', '')).path == '/assets/fonts/roboto-regular-subset.woff2']
        assert len(regular_font) == 1 and 'crossorigin' in regular_font[0].attrs, (
            str(page) + ': PSI critical request chain font must be preloaded once with CORS')
    if relative_page in {'engineering-automation/index.html', 'en/engineering-automation/index.html'}:
        critical_light = [node for node in font_preloads
                          if urlsplit(node.attrs.get('href', '')).path == '/assets/fonts/roboto-light-subset.woff2']
        regular_font = [node for node in font_preloads
                        if urlsplit(node.attrs.get('href', '')).path == '/assets/fonts/roboto-regular-subset.woff2']
        assert len(critical_light) == 1 and critical_light[0].attrs.get('fetchpriority') == 'high', (
            str(page) + ': LCP heading font must receive the only high-priority font preload')
        assert len(regular_font) == 1 and regular_font[0].attrs.get('fetchpriority') == 'low', (
            str(page) + ': first-visit consent font must be discovered early without sharing the LCP font priority')
    images = root.find(lambda n: n.tag == 'img' and
                       (n.attrs.get('src', '').startswith('/assets/') or
                        n.attrs.get('data-piskor-src', '').startswith('/assets/')))
    for image in images:
        attrs = image.attrs
        source = attrs.get('data-piskor-src', attrs.get('src', ''))
        path = output / urlsplit(source).path.lstrip('/')
        with Image.open(path) as opened:
            assert (int(attrs['width']), int(attrs['height'])) == opened.size, str(page) + ': intrinsic dimensions'
        srcset = attrs.get('data-piskor-srcset', attrs.get('srcset'))
        if srcset:
            descriptors = set()
            for entry in srcset.split(','):
                reference, descriptor = entry.strip().split()
                assert descriptor not in descriptors, str(page) + ': repeated srcset width'
                descriptors.add(descriptor)
                with Image.open(output / urlsplit(reference).path.lstrip('/')) as opened:
                    assert descriptor == str(opened.width) + 'w', str(page) + ': false srcset descriptor'
        if image.has_class('portfolio-card-cover'):
            assert attrs.get('data-piskor-srcset', attrs.get('srcset')) and attrs.get('sizes')
            cards += 1
        if attrs.get('fetchpriority') == 'high':
            assert attrs.get('loading') != 'lazy', str(page) + ': lazy LCP image'
    page_cards = root.find(lambda n: n.has_class('portfolio-card-cover'))
    if page_cards:
        relative = page.relative_to(output).as_posix()
        assert relative in expected_catalog_orders, str(page) + ': unexpected catalog route'
        ordered_links = root.find(lambda n: n.tag == 'a' and n.has_class('portfolio-card'))
        assert [card.attrs.get('data-project-id') for card in ordered_links] == expected_catalog_orders[relative], str(page) + ': catalog must sort year DESC, project_id DESC'
        checked_catalog_orders.add(relative)
        assert page_cards[0].attrs.get('loading') == 'eager'
        assert page_cards[0].attrs.get('fetchpriority') == 'high'
        assert all(c.attrs.get('loading') == 'lazy' for c in page_cards[1:])
        links = root.find(lambda n: n.tag == 'a' and n.has_class('portfolio-card'))
        for card in links:
            heading = card.find(lambda n: n.tag == 'h3')
            label = ' '.join(card_label_text(card).split())
            assert len(heading) == 1 and card.attrs.get('aria-label') == label, str(page) + ': card accessible name must match its real text-node boundaries'
        sheets = root.find(lambda n: n.tag == 'link' and n.attrs.get('rel') == 'stylesheet')
        assert not sheets, str(page) + ': render-blocking catalog stylesheet'
        styles = root.find(lambda n: n.tag == 'style' and 'data-catalog-styles' in n.attrs)
        assert len(styles) == 1, str(page) + ': missing shared inline catalog styles'
        fonts = root.find(lambda n: n.tag == 'link' and n.attrs.get('rel') == 'preload' and n.attrs.get('as') == 'font')
        assert {urlsplit(n.attrs['href']).path for n in fonts} == {
            '/assets/fonts/roboto-light-subset.woff2', '/assets/fonts/roboto-regular-subset.woff2'}
        pictures = root.find(lambda n: n.tag == 'picture' and n.find(lambda child: child.has_class('portfolio-card-cover')))
        assert len(pictures) == len(page_cards), str(page) + ': missing responsive format fallback'
        preloads = root.find(lambda n: n.tag == 'link' and n.attrs.get('rel') == 'preload' and n.attrs.get('as') == 'image')
        assert len(preloads) == 1, str(page) + ': preload only the first mobile cover'
        preload = preloads[0].attrs
        first_source = pictures[0].find(lambda n: n.tag == 'source')[0].attrs
        for link_key, source_key in [('imagesrcset', 'srcset'), ('imagesizes', 'sizes'), ('type', 'type'), ('media', 'media')]:
            assert preload.get(link_key) == first_source[source_key], str(page) + ': preload does not match selected cover'
        assert preload.get('fetchpriority') == 'high' and 'href' not in preload
        html = page.read_text()
        assert html.index('name="viewport"') < html.index('data-catalog-cover-preload') < html.index('as="font"')
        for picture in pictures:
            sources = picture.find(lambda n: n.tag == 'source')
            fallback = picture.find(lambda n: n.tag == 'img')[0]
            assert len(sources) == 1 and sources[0].attrs.get('type') == 'image/avif'
            assert sources[0].attrs.get('media') == '(max-width: 700px)'
            assert sources[0].attrs.get('sizes') == fallback.attrs['sizes']
            alternatives = sources[0].attrs.get(
                'data-piskor-srcset', sources[0].attrs.get('srcset', '')).split(',')
            webp_candidates = []
            webp_srcset = fallback.attrs.get(
                'data-piskor-srcset', fallback.attrs.get('srcset', ''))
            for webp in webp_srcset.split(','):
                with Image.open(output / urlsplit(webp.strip().split()[0]).path.lstrip('/')) as original:
                    webp_candidates.append(original.size)
            native_width, native_height = max(webp_candidates)
            descriptors = set()
            for entry in alternatives:
                reference, descriptor = entry.strip().split()
                assert descriptor not in descriptors, str(page) + ': repeated AVIF candidate'
                descriptors.add(descriptor)
                target = output / urlsplit(reference).path.lstrip('/')
                with Image.open(target) as opened:
                    assert opened.format == 'AVIF' and descriptor == str(opened.width) + 'w'
                    assert opened.width <= native_width, str(page) + ': upscaled overview'
                    assert abs(opened.height - round(native_height * opened.width / native_width)) <= 1, str(page) + ': overview must retain its full source frame'
                assert parse_qs(urlsplit(reference).query).get('v') == [hashlib.sha256(target.read_bytes()).hexdigest()[:12]]
    for node in root.find(lambda n: n.tag in {'img', 'script', 'link', 'button', 'video', 'source'}):
        for key in ['src', 'href', 'data-full', 'poster', 'data-piskor-src']:
            value = node.attrs.get(key, '')
            url = urlsplit(value)
            if not value.startswith('/') or url.scheme or url.netloc:
                continue
            target = output / url.path.lstrip('/')
            if target.is_file() and target.suffix in {'.webp', '.avif', '.png', '.svg', '.ico', '.woff2', '.mp4', '.css', '.js'}:
                assert parse_qs(url.query).get('v') == [hashlib.sha256(target.read_bytes()).hexdigest()[:12]], value
        for key in ['srcset', 'data-piskor-srcset']:
            for candidate in node.attrs.get(key, '').split(','):
                reference = candidate.strip().split()[0] if candidate.strip() else ''
                url = urlsplit(reference)
                if not reference.startswith('/') or url.scheme or url.netloc:
                    continue
                target = output / url.path.lstrip('/')
                if target.is_file() and target.suffix in {'.webp', '.avif', '.png'}:
                    assert parse_qs(url.query).get('v') == [
                        hashlib.sha256(target.read_bytes()).hexdigest()[:12]], reference

assert checked_catalog_orders == set(expected_catalog_orders), 'Missing UA/EN full or year catalog order verification'

css = (output / 'style.css').read_text()
background = re.search(r'\.contact\{background:(#[a-f0-9]{6});', css)[1]
def luminance(color):
    values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(v * weight for v, weight in zip(values, [.2126, .7152, .0722]))
for selector in [r'\.contact-top \.eyebrow', r'\.contact-main p']:
    foreground = re.search(selector + r'\{[^}]*color:(#[a-f0-9]{6})', css)[1]
    low, high = sorted([luminance(foreground), luminance(background)])
    assert (high + .05) / (low + .05) >= 4.5
assert '.ttf' not in css and 'font-display:swap' in css
subsets = [output / 'assets/fonts' / (name + '-subset.woff2') for name in ('roboto-light', 'roboto-regular')]
assert sum(path.stat().st_size for path in subsets) <= 26000, 'Recheck the first-paint font budget before expanding character coverage'
print(f'Performance contracts: {len(pairs)} bilingual projects, {cards} responsive cards, actual image dimensions, resource versions and contact contrast verified')
