"""Check the generated bilingual page metadata and clean URL contract."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import json
import re
import xml.etree.ElementTree as ET
from urllib.robotparser import RobotFileParser

class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.titles = []
        self.in_title = False
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == 'title':
            self.in_title = True
            self.titles.append('')
    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
    def handle_data(self, value):
        if self.in_title:
            self.titles[-1] += value

routes = {'/': 'uk', '/en/': 'en', '/portfolio/': 'uk', '/en/portfolio/': 'en', '/portfolio/lviv-apartment/': 'uk', '/en/portfolio/lviv-apartment/': 'en'}
titles = set()
for route, lang in routes.items():
    page = Page((Path('_site') / route.lstrip('/') / 'index.html').read_text())
    assert len(page.titles) == 1
    title = page.titles[0]
    assert title not in titles and not any(word in title.lower() for word in ['concept', 'концепт'])
    titles.add(title)
    assert next(a['lang'] for t, a in page.tags if t == 'html') == lang
    meta = {a.get('name', a.get('property')): a.get('content') for t, a in page.tags if t == 'meta'}
    assert meta['description'] and meta['og:title'] == title and meta['twitter:title'] == title
    assert 'noindex' in meta['robots'], 'Indexing requires separate approval'
    links = [a for t, a in page.tags if t == 'link']
    canonical = [a['href'] for a in links if a.get('rel') == 'canonical']
    assert canonical == ['https://piskor-com-ua.github.io' + route]
    alternates = {a['hreflang']: a['href'] for a in links if 'hreflang' in a}
    suffix = route.removeprefix('/en/').lstrip('/')
    assert alternates == {'uk': 'https://piskor-com-ua.github.io/' + suffix, 'en': 'https://piskor-com-ua.github.io/en/' + suffix, 'x-default': 'https://piskor-com-ua.github.io/' + suffix}
    for tag, attrs in page.tags:
        if tag == 'a' and attrs.get('href', '').startswith('/'):
            assert not urlsplit(attrs['href']).path.endswith('.html'), attrs['href']
for old in ['lviv-apartment.html', 'lviv-apartment-en.html']:
    assert not (Path('_site') / old).exists(), old
for path in Path('_site').rglob('*.html'):
    text = path.read_text()
    parsed = Page(text)
    robots = [a['content'] for t, a in parsed.tags if t == 'meta' and a.get('name') == 'robots']
    assert len(robots) == 1 and 'noindex' in robots[0], f'Indexing guard: {path}'
    graphs = [json.loads(value) for value in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)]
    assert len(graphs) == 1 and graphs[0]['@context'] == 'https://schema.org', path
    types = {node['@type'] for node in graphs[0]['@graph']}
    assert {'Organization', 'WebSite'} <= types, path
    if path.parent.name == 'portfolio':
        assert {'CollectionPage', 'BreadcrumbList'} <= types, path
    elif 'portfolio' in path.parts:
        assert {'CreativeWork', 'BreadcrumbList'} <= types, path
robots_text = Path('_site/robots.txt').read_text()
robots = RobotFileParser()
robots.parse(robots_text.splitlines())
for agent in ['Googlebot', 'bingbot', 'OAI-SearchBot', 'Claude-SearchBot']:
    assert all(robots.can_fetch(agent, route) for route in routes), 'Crawler cannot see noindex'
assert not robots.site_maps(), 'Do not advertise an indexing sitemap while indexing is disabled'
tree = ET.parse('_site/sitemap.xml')
assert tree.getroot().tag == '{http://www.sitemaps.org/schemas/sitemap/0.9}urlset'
assert not list(tree.getroot()), 'No noindex pages in the indexing sitemap'
print(f'SEO metadata, language pairs and clean routes verified for all {len(routes)} pages')
