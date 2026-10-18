"""Enforce media, discovery and accessibility contracts on the whole public artifact."""
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import hashlib
import json
import re
from PIL import Image
from agent_catalog import Document

output = Path('_site')
catalog = json.loads((output / 'project-catalog.json').read_text())
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
    root = Document(page.read_text()).root
    agents = root.find(lambda n: n.tag == 'script' and urlsplit(n.attrs.get('src', '')).path == '/agent-tools.js')
    for rel, href in [('ard', '/.well-known/ard.json'), ('ai-catalog', '/.well-known/ai-catalog.json')]:
        discovery = root.find(lambda n: n.tag == 'link' and n.attrs.get('rel') == rel)
        assert len(discovery) == (1 if agents else 0), str(page) + ': discovery coverage'
        if discovery:
            assert discovery[0].attrs.get('href') == href
    early = root.find(lambda n: n.tag == 'script' and 'data-consent-inline' in n.attrs)
    assert len(early) == 1, str(page) + ': missing early consent controller'
    assert not root.find(lambda n: n.tag == 'script' and urlsplit(n.attrs.get('src', '')).path == '/analytics-consent.js')
    images = root.find(lambda n: n.tag == 'img' and n.attrs.get('src', '').startswith('/assets/'))
    for image in images:
        attrs = image.attrs
        path = output / urlsplit(attrs['src']).path.lstrip('/')
        with Image.open(path) as opened:
            assert (int(attrs['width']), int(attrs['height'])) == opened.size, str(page) + ': intrinsic dimensions'
        if 'srcset' in attrs:
            descriptors = set()
            for entry in attrs['srcset'].split(','):
                reference, descriptor = entry.strip().split()
                assert descriptor not in descriptors, str(page) + ': repeated srcset width'
                descriptors.add(descriptor)
                with Image.open(output / urlsplit(reference).path.lstrip('/')) as opened:
                    assert descriptor == str(opened.width) + 'w', str(page) + ': false srcset descriptor'
        if image.has_class('portfolio-card-cover'):
            assert attrs.get('srcset') and attrs.get('sizes')
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
            assert len(heading) == 1 and card.attrs.get('aria-label') == heading[0].text(), str(page) + ': card accessible name'
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
            alternatives = sources[0].attrs['srcset'].split(',')
            assert len(alternatives) == len(fallback.attrs['srcset'].split(','))
            for entry, webp in zip(alternatives, fallback.attrs['srcset'].split(',')):
                reference, descriptor = entry.strip().split()
                assert descriptor == webp.strip().split()[1]
                target = output / urlsplit(reference).path.lstrip('/')
                webp_path = output / urlsplit(webp.strip().split()[0]).path.lstrip('/')
                with Image.open(target) as opened, Image.open(webp_path) as original:
                    assert opened.format == 'AVIF' and descriptor == str(opened.width) + 'w'
                    assert opened.size == original.size, str(page) + ': format geometry differs'
                assert parse_qs(urlsplit(reference).query).get('v') == [hashlib.sha256(target.read_bytes()).hexdigest()[:12]]
    for node in root.find(lambda n: n.tag in {'img', 'script', 'link', 'button', 'video', 'source'}):
        for key in ['src', 'href', 'data-full', 'poster']:
            value = node.attrs.get(key, '')
            url = urlsplit(value)
            if not value.startswith('/') or url.scheme or url.netloc:
                continue
            target = output / url.path.lstrip('/')
            if target.is_file() and target.suffix in {'.webp', '.avif', '.png', '.svg', '.ico', '.woff2', '.mp4', '.css', '.js'}:
                assert parse_qs(url.query).get('v') == [hashlib.sha256(target.read_bytes()).hexdigest()[:12]], value

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
