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

cards = 0
for page in output.rglob('*.html'):
    root = Document(page.read_text()).root
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
        assert page_cards[0].attrs.get('loading') == 'eager'
        assert page_cards[0].attrs.get('fetchpriority') == 'high'
        assert all(c.attrs.get('loading') == 'lazy' for c in page_cards[1:])
        links = root.find(lambda n: n.tag == 'a' and n.has_class('portfolio-card'))
        for card in links:
            label = card.attrs['aria-labelledby']
            assert card.find(lambda n: n.tag == 'h3' and n.attrs.get('id') == label)
        sheets = root.find(lambda n: n.tag == 'link' and n.attrs.get('rel') == 'stylesheet')
        assert not sheets, str(page) + ': render-blocking catalog stylesheet'
        styles = root.find(lambda n: n.tag == 'style' and 'data-catalog-styles' in n.attrs)
        assert len(styles) == 1, str(page) + ': missing shared inline catalog styles'
    for node in root.find(lambda n: n.tag in {'img', 'script', 'link', 'button', 'video', 'source'}):
        for key in ['src', 'href', 'data-full', 'poster']:
            value = node.attrs.get(key, '')
            url = urlsplit(value)
            if not value.startswith('/') or url.scheme or url.netloc:
                continue
            target = output / url.path.lstrip('/')
            if target.is_file() and target.suffix in {'.webp', '.png', '.svg', '.ico', '.woff2', '.mp4', '.css', '.js'}:
                assert parse_qs(url.query).get('v') == [hashlib.sha256(target.read_bytes()).hexdigest()[:12]], value

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
assert sum(path.stat().st_size for path in subsets) <= 40000, 'Recheck the first-paint font budget before expanding character coverage'
print(f'Performance contracts: {len(pairs)} bilingual projects, {cards} responsive cards, actual image dimensions, resource versions and contact contrast verified')
