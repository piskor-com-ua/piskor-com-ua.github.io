"""Check the generated bilingual page metadata and clean URL contract."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import json
import re
import xml.etree.ElementTree as ET
from urllib.robotparser import RobotFileParser
from compatibility_pages import COMPATIBILITY_ROUTES, validate_compatibility_pages

validate_compatibility_pages('_site', markdown_alternatives=True)

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

routes = {}
for index in Path('_site').rglob('index.html'):
    relative = index.parent.relative_to('_site').as_posix()
    route = '/' if relative == '.' else f'/{relative}/'
    routes[route] = 'en' if route == '/en/' or route.startswith('/en/') else 'uk'
titles = set()
for route, lang in routes.items():
    page = Page((Path('_site') / route.lstrip('/') / 'index.html').read_text())
    assert len(page.titles) == 1
    title = page.titles[0]
    assert not any(word in title.lower() for word in ['concept', 'концепт'])
    if route not in COMPATIBILITY_ROUTES:
        assert title not in titles
        titles.add(title)
    assert next(a['lang'] for t, a in page.tags if t == 'html') == lang
    meta = {a.get('name', a.get('property')): a.get('content') for t, a in page.tags if t == 'meta'}
    assert meta['description'] and meta['og:title'] == title and meta['twitter:title'] == title
    expected_robots = 'noindex,nofollow' if route in COMPATIBILITY_ROUTES else 'index,follow,max-image-preview:large'
    assert meta['robots'] == expected_robots, f'Unexpected indexing directive for {route}'
    links = [a for t, a in page.tags if t == 'link']
    canonical = [a['href'] for a in links if a.get('rel') == 'canonical']
    refresh = [a['content'] for t, a in page.tags if t == 'meta' and a.get('http-equiv') == 'refresh']
    canonical_route = COMPATIBILITY_ROUTES.get(route, route)
    if refresh:
        assert len(refresh) == 1 and refresh[0].startswith('0;url=/'), route
        canonical_route = refresh[0].removeprefix('0;url=')
        assert canonical_route in routes and canonical_route != route, route
        assert routes[canonical_route] == lang, route
        target = Page((Path('_site') / canonical_route.lstrip('/') / 'index.html').read_text())
        assert not any(t == 'meta' and a.get('http-equiv') == 'refresh' for t, a in target.tags), 'Redirect chain'
    assert canonical == ['https://piskor.com.ua' + canonical_route]
    alternates = {a['hreflang']: a['href'] for a in links if 'hreflang' in a}
    suffix = canonical_route.removeprefix('/en/').lstrip('/')
    assert alternates == {'uk': 'https://piskor.com.ua/' + suffix, 'en': 'https://piskor.com.ua/en/' + suffix, 'x-default': 'https://piskor.com.ua/' + suffix}
    for tag, attrs in page.tags:
        if tag == 'a' and attrs.get('href', '').startswith('/'):
            assert not urlsplit(attrs['href']).path.endswith('.html'), attrs['href']
for old in ['lviv-apartment.html', 'lviv-apartment-en.html']:
    assert not (Path('_site') / old).exists(), old
for path in Path('_site').rglob('*.html'):
    text = path.read_text()
    parsed = Page(text)
    robots = [a['content'] for t, a in parsed.tags if t == 'meta' and a.get('name') == 'robots']
    alias_files = {Path('_site') / route.lstrip('/') / 'index.html' for route in COMPATIBILITY_ROUTES}
    expected_robots = 'noindex,nofollow' if path == Path('_site/404.html') or path in alias_files else 'index,follow,max-image-preview:large'
    assert len(robots) == 1 and robots[0] == expected_robots, f'Indexability policy: {path}'
    graphs = [json.loads(value) for value in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)]
    assert len(graphs) == 1 and graphs[0]['@context'] == 'https://schema.org', path
    types = {node['@type'] for node in graphs[0]['@graph']}
    assert {'Organization', 'WebSite'} <= types, path
    for video in (node for node in graphs[0]['@graph'] if node.get('@type') == 'VideoObject'):
        assert all(video.get(key) for key in ('name', 'description', 'thumbnailUrl', 'uploadDate', 'contentUrl')), path
    if path.parent.name == 'engineering-automation':
        assert {'Service', 'BreadcrumbList'} <= types, path
        assert 'id="automation-areas"' in text and 'id="contact"' in text, path
    if 'CollectionPage' in types:
        assert {'CollectionPage', 'BreadcrumbList'} <= types, path
    elif 'portfolio' in path.parts:
        assert {'CreativeWork', 'BreadcrumbList'} <= types, path
robots_text = Path('_site/robots.txt').read_text()
robots = RobotFileParser()
robots.parse(robots_text.splitlines())
for agent in ['Googlebot', 'bingbot', 'OAI-SearchBot', 'Claude-SearchBot']:
    assert all(robots.can_fetch(agent, route) for route in routes), f'{agent} cannot crawl a public route'
assert robots.site_maps() == ['https://piskor.com.ua/sitemap.xml'], 'Advertise the public sitemap'
tree = ET.parse('_site/sitemap.xml')
assert tree.getroot().tag == '{http://www.sitemaps.org/schemas/sitemap/0.9}urlset'
video_ns = '{http://www.google.com/schemas/sitemap-video/1.1}'
locations = [item.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc').text for item in tree.getroot()]
expected_locations = {'https://piskor.com.ua' + route for route in routes if route not in COMPATIBILITY_ROUTES}
assert set(locations) == expected_locations, 'Sitemap must contain canonical routes only'
assert all(url.startswith('https://piskor.com.ua/') for url in locations)
assert not any(url.endswith('/404.html') for url in locations)
video_page_count = 0
for item in tree.getroot():
    page_url = item.find('{http://www.sitemaps.org/schemas/sitemap/0.9}loc').text
    route = urlsplit(page_url).path
    page_file = Path('_site') / route.lstrip('/') / 'index.html' if route.endswith('/') else Path('_site') / route.lstrip('/')
    page_text = page_file.read_text()
    parsed_page = Page(page_text)
    video_tags = [attrs for tag, attrs in parsed_page.tags if tag == 'video']
    video_entries = item.findall(f'{video_ns}video')
    assert len(video_entries) == len(video_tags), f'Every public HTML video needs exactly one sitemap entry: {page_url}'
    video_page_count += bool(video_entries)
    for video in video_entries:
        title = video.findtext(f'{video_ns}title')
        description = video.findtext(f'{video_ns}description')
        thumbnail = video.findtext(f'{video_ns}thumbnail_loc')
        content = video.findtext(f'{video_ns}content_loc')
        assert title and len(title) <= 100, f'Invalid video title: {page_url}'
        assert description and len(description) <= 2048, f'Invalid video description: {page_url}'
        assert thumbnail and urlsplit(thumbnail).path in page_text, f'Video poster missing from page: {page_url}'
        assert content and urlsplit(content).path in page_text, f'Video file missing from page: {page_url}'
assert video_page_count > 0, 'Expected video entries in the video sitemap'
error_page = Page(Path('_site/404.html').read_text())
error_robots = [attrs['content'] for tag, attrs in error_page.tags if tag == 'meta' and attrs.get('name') == 'robots']
assert error_robots == ['noindex,nofollow'], 'Not-found page must stay out of the index'
print(f'SEO metadata, language pairs and clean routes verified for all {len(routes)} pages')
