"""Defer non-initial images on the explicitly measured mobile SI cohort.

The first case cover and first catalog card remain eager and high priority.
Only below-fold gallery images and later catalog cards move behind an
IntersectionObserver; a native no-JavaScript copy remains in every page.
"""
from html import escape
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re

from first_paint import generated_root

TARGETS_FILE = Path(__file__).with_name('mobile-si-target-routes.json')
FOLLOWUP_TARGETS_FILE = Path(__file__).with_name('mobile-si-followup-routes.json')
TOP10_TARGETS_FILE = Path(__file__).with_name('mobile-si-top10-routes.json')
HIGH_SI_TARGETS_FILE = Path(__file__).with_name('mobile-si-high-routes.json')
CURRENT_SI_TARGETS_FILE = Path(__file__).with_name('mobile-si-2s-routes.json')
ENGINEERING_ROUTES = frozenset({'/engineering-automation/', '/en/engineering-automation/'})
CONTROLLER = Path(__file__).with_name('deferred-mobile-media-controller.js')
SCRIPT_MARKER = 'data-piskor-deferred-media-controller'
PICTURE_MARKER = 'data-piskor-deferred-media'
FALLBACK_MARKER = 'data-piskor-deferred-media-fallback'
STYLE_MARKER = 'data-piskor-deferred-media-style'
FALLBACK_STYLE = ('<noscript ' + STYLE_MARKER + '><style>'
                  'picture[' + PICTURE_MARKER + ']{display:none!important}'
                  '</style></noscript>')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}


def _base_target_routes():
    manifest = json.loads(TARGETS_FILE.read_text())
    routes = manifest.get('routes')
    lcp_routes = manifest.get('lcp_gte_1500_routes')
    lcp_media_routes = manifest.get('lcp_media_routes')
    critical_image_routes = manifest.get('critical_image_delivery_routes')
    redirect_aliases = manifest.get('redirect_aliases')
    if (manifest.get('count') != 39 or len(routes or []) != 39 or
            len(set(routes)) != 39 or
            manifest.get('lcp_gte_1500_count') != 10 or len(lcp_routes or []) != 10 or
            len(set(lcp_routes)) != 10 or not set(lcp_routes).issubset(routes) or
            manifest.get('lcp_media_count') != 10 or len(lcp_media_routes or []) != 10 or
            len(set(lcp_media_routes)) != 10 or not set(lcp_media_routes).issubset(lcp_routes) or
            manifest.get('critical_image_delivery_count') != 3 or
            len(critical_image_routes or []) != 3 or len(set(critical_image_routes)) != 3 or
            not set(critical_image_routes).issubset(routes) or
            set(lcp_media_routes) | set(redirect_aliases or {}) != set(lcp_routes) or
            not set(redirect_aliases or {}).issubset(routes) or
            manifest.get('baseline_revision') != '5e3652ef22931b994269493376f1d13fbebeeab7' or
            any(not re.fullmatch(r'/(?:en/)?portfolio(?:/\d{4})?/', route)
                and not re.fullmatch(r'/(?:en/)?portfolio/\d{4}/[a-z0-9-]+/', route)
                for route in routes + lcp_routes + lcp_media_routes + list(redirect_aliases or {}))):
        raise ValueError('Unexpected mobile Speed Index target manifest')
    return frozenset(routes)


def followup_target_routes():
    """Validate the fresh PSI follow-up cohort separately from its historical baseline."""
    manifest = json.loads(FOLLOWUP_TARGETS_FILE.read_text())
    entries = manifest.get('routes')
    routes = [entry.get('route') for entry in entries or []]
    if (manifest.get('baseline_revision') != '23fcc890439d1acd07a112b06199a5904bc6f6c5' or
            manifest.get('audit_date') != '2026-10-20' or
            manifest.get('form_factor') != 'mobile' or
            manifest.get('device') != 'Moto G Power' or
            manifest.get('throttling') != 'Slow 4G' or
            len(routes) != 5 or len(set(routes)) != 5 or
            not all(route and re.fullmatch(r'/(?:en/)?portfolio(?:/\d{4})?/', route)
                    or route and re.fullmatch(r'/(?:en/)?portfolio/\d{4}/[a-z0-9-]+/', route)
                    for route in routes) or
            any(not entry.get('psi_report', '').startswith('https://pagespeed.web.dev/analysis/') or
                any(type(entry.get(name)) is not int or entry[name] < 0
                    for name in ('fcp_ms', 'lcp_ms', 'speed_index_ms')) or
                entry['speed_index_ms'] <= 1500 or not entry.get('lcp_element') or
                not entry.get('review') for entry in entries) or
            set(routes) & _base_target_routes()):
        raise ValueError('Unexpected mobile Speed Index PSI follow-up manifest')
    return frozenset(routes)


def top10_target_routes():
    """Validate the current ten slowest production routes and their PSI evidence."""
    manifest = json.loads(TOP10_TARGETS_FILE.read_text())
    entries = manifest.get('routes')
    routes = [entry.get('route') for entry in entries or []]
    if (manifest.get('baseline_revision') != 'dc11e6a0839c6519f658bb0bebb3f6c8a08f9222' or
            manifest.get('audit_date') != '2026-10-20' or
            manifest.get('form_factor') != 'mobile' or
            manifest.get('device') != 'Moto G Power' or
            manifest.get('throttling') != 'Slow 4G' or
            len(routes) != 10 or len(set(routes)) != 10 or
            not all(route == '/' or route == '/en/' or
                    re.fullmatch(r'/(?:en/)?portfolio/\d{4}/[a-z0-9-]+/', route)
                    for route in routes) or
            any(not entry.get('psi_report', '').startswith('https://pagespeed.web.dev/analysis/') or
                any(type(entry.get(name)) is not int or entry[name] < 0
                    for name in ('fcp_ms', 'lcp_ms', 'speed_index_ms')) or
                entry['speed_index_ms'] <= 1500 or not entry.get('review')
                for entry in entries) or
            [entry['speed_index_ms'] for entry in entries] !=
            sorted((entry['speed_index_ms'] for entry in entries), reverse=True)):
        raise ValueError('Unexpected mobile Speed Index top-ten manifest')
    return frozenset(routes)


def high_si_target_routes():
    """Validate the latest PSI routes at or above the 2.5s SI threshold."""
    manifest = json.loads(HIGH_SI_TARGETS_FILE.read_text())
    entries = manifest.get('routes')
    routes = [entry.get('route') for entry in entries or []]
    if (manifest.get('baseline_revision') != 'def2cab67a1855041c2586ec04c4c0b872f61a72' or
            manifest.get('audit_date') != '2026-10-20' or
            manifest.get('form_factor') != 'mobile' or
            manifest.get('device') != 'Moto G Power' or
            manifest.get('throttling') != 'Slow 4G' or
            manifest.get('route_count') != 10 or len(routes) != 10 or
            len(set(routes)) != 10 or
            manifest.get('strategy') != 'defer non-initial media until entering the viewport' or
            any(not re.fullmatch(r'/(?:en/)?portfolio(?:/\d{4})?/', route)
                and not re.fullmatch(r'/(?:en/)?portfolio/\d{4}/[a-z0-9-]+/', route)
                for route in routes) or
            any(not entry.get('psi_report', '').startswith('https://pagespeed.web.dev/analysis/') or
                any(not re.fullmatch(r'\d+\.\d', entry.get(name, ''))
                    for name in ('fcp_s', 'lcp_s', 'speed_index_s')) or
                float(entry['speed_index_s']) < 2.5 or not entry.get('findings')
                for entry in entries)):
        raise ValueError('Unexpected high-Speed-Index route manifest')
    return frozenset(routes)


def current_si_target_routes():
    """Return routes currently measured at or above the 2-second mobile SI threshold."""
    manifest = json.loads(CURRENT_SI_TARGETS_FILE.read_text())
    entries = manifest.get('routes')
    routes = [entry.get('route') for entry in entries or []]
    if (manifest.get('audit_date') != '2026-10-21' or
            manifest.get('form_factor') != 'mobile' or
            manifest.get('device') != 'Moto G Power' or
            manifest.get('throttling') != 'Slow 4G' or
            manifest.get('threshold_si_ms') != 2000 or
            manifest.get('route_count') != 4 or len(routes) != 4 or
            len(set(routes)) != 4 or
            any(route not in {'/en/', '/portfolio/2023/zamartynivska-40-apartment/',
                              '/portfolio/2023/avalon-holiday-apartment/',
                              '/portfolio/2024/domazhyr-house/'} for route in routes) or
            any(not entry.get('psi_report', '').startswith('https://pagespeed.web.dev/analysis/') or
                any(type(entry.get(name)) is not int or entry[name] < 0
                    for name in ('fcp_ms', 'lcp_ms', 'speed_index_ms')) or
                entry['speed_index_ms'] < 2000 or entry.get('agentic') != '5/5'
                for entry in entries)):
        raise ValueError('Unexpected current mobile SI >= 2s manifest')
    return frozenset(routes)


def target_root_margin(route):
    """Wait until deferred media enters view throughout the approved 39-route cohort."""
    return '0px 0px' if route in (_base_target_routes() | high_si_target_routes() |
                                  current_si_target_routes()) else '250px 0px'


def target_routes():
    """Return the evidenced historical, follow-up, and current top-ten cohorts."""
    # The two home pages are in the performance cohort but have no eligible
    # gallery/catalog pictures; their PSI finding is fixed in home-bootstrap.js.
    media_top10 = top10_target_routes() - {'/', '/en/'}
    current_media = current_si_target_routes() - {'/', '/en/'}
    return (_base_target_routes() | followup_target_routes() | media_top10 |
            high_si_target_routes() | current_media | ENGINEERING_ROUTES)


def lcp_target_routes():
    target_routes()
    manifest = json.loads(TARGETS_FILE.read_text())
    return frozenset(manifest['lcp_media_routes'])


def critical_image_delivery_routes():
    target_routes()
    return frozenset(json.loads(TARGETS_FILE.read_text())['critical_image_delivery_routes'])


def redirect_aliases():
    target_routes()
    return json.loads(TARGETS_FILE.read_text())['redirect_aliases']


def _route_for_page(output, page):
    relative = Path(page).relative_to(output).as_posix()
    if relative == 'index.html':
        return '/'
    if relative.endswith('/index.html'):
        return '/' + relative[:-len('index.html')]
    return '/' + relative


class _Pictures(HTMLParser):
    def __init__(self, html, engineering=False):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.lines = [0]
        for match in re.finditer('\n', html):
            self.lines.append(match.end())
        self.stack = []
        self.current = None
        self.spans = []
        self.engineering = engineering

    def _offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get('class', '').split())
        if tag == 'picture':
            gallery = any(names & {'gallery-grid', 'case-images'} for _, names in self.stack)
            catalog = any('portfolio-card-image' in names for _, names in self.stack)
            if gallery or catalog or self.engineering:
                if self.current is not None:
                    raise ValueError('Nested image pictures are unsupported')
                kind = 'gallery' if gallery else 'catalog' if catalog else 'candidate'
                self.current = {'start': self._offset(), 'kind': kind}
        if (tag == 'img' and self.engineering and self.current is not None
                and 'data-engineering-photo' in attrs):
            self.current['kind'] = 'engineering'
        if tag not in VOID:
            self.stack.append((tag, classes))

    def handle_endtag(self, tag):
        if tag == 'picture' and self.current is not None:
            end = self.html.index('>', self._offset()) + 1
            if self.current['kind'] != 'candidate':
                self.spans.append((self.current['start'], end, self.current['kind']))
            self.current = None
        if tag not in VOID:
            if not self.stack or self.stack[-1][0] != tag:
                raise ValueError('Malformed image document nesting')
            self.stack.pop()


def _picture_spans(html, engineering=False):
    parser = _Pictures(html, engineering)
    parser.feed(html)
    parser.close()
    if parser.current is not None or parser.stack:
        raise ValueError('Unclosed image document')
    return parser.spans


def _picture_img(original, require_lazy=True):
    images = re.findall(r'<img\b[^>]*>', original, re.I)
    if len(images) != 1:
        raise ValueError('Deferred picture must contain exactly one image')
    attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', images[0]))
    if ((require_lazy and attrs.get('loading') != 'lazy') or not attrs.get('alt') or
            not attrs.get('src', '').startswith('/assets/') or
            not all(re.fullmatch(r'[1-9]\d*', attrs.get(name, ''))
                    for name in ('width', 'height'))):
        raise ValueError('Unrecognized deferred image contract')
    return images[0], attrs


def _prepare_picture(original, kind):
    image, attrs = _picture_img(original)
    if kind == 'catalog' and attrs.get('fetchpriority') == 'high':
        raise ValueError('The eager catalog cover must not be deferred')
    sources = re.findall(r'<source\b[^>]*>', original, re.I)
    if not sources or not any('srcset="' in source for source in sources):
        raise ValueError('Deferred picture must retain responsive source candidates')
    placeholder = ('data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20width=%22'
                  + attrs['width'] + '%22%20height=%22' + attrs['height'] + '%22%3E%3C/svg%3E')

    def defer_tag(match):
        tag = match[0]
        tag = re.sub(r'(?<![\w-])srcset=', 'data-piskor-srcset=', tag)
        if tag.lower().startswith('<img'):
            tag = re.sub(r'(?<![\w-])src=', 'data-piskor-src=', tag)
            tag = tag.replace('<img', '<img src="' + escape(placeholder, quote=True) + '"', 1)
        return tag

    active = re.sub(r'<(?:img|source)\b[^>]*>', defer_tag, original, flags=re.I)
    if PICTURE_MARKER in active:
        raise ValueError('Picture was already transformed')
    active = active.replace('<picture', '<picture ' + PICTURE_MARKER, 1)
    return active + '<noscript ' + FALLBACK_MARKER + '>' + original + '</noscript>'


def _controller_tag(controller, root_margin='250px 0px'):
    return ('<script ' + SCRIPT_MARKER + ' data-source-sha256="'
            + hashlib.sha256(controller.encode()).hexdigest() + '"'
            + ' data-piskor-deferred-media-root-margin="' + escape(root_margin, quote=True) + '">'
            + controller + '</script>')


def restore_deferred_mobile_media(html):
    """Restore original pictures for exact compatibility-content comparison."""
    if PICTURE_MARKER not in html and SCRIPT_MARKER not in html and FALLBACK_MARKER not in html:
        return html
    pattern = re.compile(
        r'(<picture\b[^>]*\b' + PICTURE_MARKER + r'[^>]*>.*?</picture>)'
        r'<noscript\b[^>]*\b' + FALLBACK_MARKER + r'[^>]*>(.*?)</noscript>', re.S)
    matches = list(pattern.finditer(html))
    if not matches or len(matches) != html.count(FALLBACK_MARKER):
        raise ValueError('Cannot normalize deferred pictures for compatibility validation')
    html = pattern.sub(lambda match: match[2], html)
    html = re.sub(r'<noscript\b[^>]*\b' + STYLE_MARKER + r'[^>]*>.*?</noscript>', '', html, flags=re.S)
    tag = re.search(r'<script\b[^>]*\b' + SCRIPT_MARKER + r'[^>]*>', html)
    attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', tag[0])) if tag else {}
    script = _controller_tag(CONTROLLER.read_text(),
                             attrs.get('data-piskor-deferred-media-root-margin', '250px 0px'))
    if html.count(script) != 1:
        raise ValueError('Cannot normalize changed deferred-media controller')
    return html.replace(script, '', 1)


def _validate_redirect_alias(html, route):
    destination = redirect_aliases().get(route)
    if not destination:
        return False
    canonical = re.search(r'<link\b[^>]*rel="canonical"[^>]*href="https://piskor\.com\.ua([^"#?]*)"', html)
    refresh = re.search(r'<meta\b[^>]*http-equiv="refresh"[^>]*content="0;url=([^"]+)"', html, re.I)
    expected_script = 'const destination = "' + destination + '";'
    if (not canonical or canonical[1] != destination or not refresh or
            refresh[1] != destination or expected_script not in html or
            'location.replace(destination + location.search + fragment)' not in html):
        raise ValueError('Measured alias no longer matches its reviewed redirect contract')
    return True


def transform_page(html, controller, route=None):
    if SCRIPT_MARKER in html or PICTURE_MARKER in html:
        raise ValueError('Page already contains deferred-media markers')
    spans = _picture_spans(html, engineering=route in ENGINEERING_ROUTES)
    selected = []
    for start, end, kind in spans:
        original = html[start:end]
        image, attrs = _picture_img(original, require_lazy=(kind != 'catalog'))
        # The first catalog cover is eager; all other lazy cards can wait until
        # they approach the viewport. Every story-gallery image is lazy.
        if kind in {'gallery', 'engineering'} or attrs.get('loading') == 'lazy':
            selected.append((start, end, original, kind))
    if not selected and route and _validate_redirect_alias(html, route):
        return html, 0
    if not selected:
        raise ValueError('Target route has no eligible offscreen images')

    for start, end, original, kind in reversed(selected):
        html = html[:start] + _prepare_picture(original, kind) + html[end:]
    if html.count('</head>') != 1 or html.count('</body>') != 1:
        raise ValueError('Expected one document head/body')
    html = html.replace('</head>', FALLBACK_STYLE + '</head>', 1)
    script = _controller_tag(controller, target_root_margin(route) if route else '250px 0px')
    # Keep each route's contiguous DOM-ready payload in its original order.
    # Engineering runs its scene controller before registering agent tools.
    critical = re.search(r'<script\b[^>]*\bdata-inline-page-critical=["\'](?:engineering-automation|agent-tools)\.js["\']', html)
    index = critical.start() if critical else html.index('</body>')
    return html[:index] + script + html[index:], len(selected)


def defer_mobile_media(output):
    output = generated_root(output)
    routes = target_routes()
    controller = CONTROLLER.read_text()
    if '</script' in controller.lower():
        raise ValueError('Deferred-media controller contains an HTML script terminator')
    updates = []
    for route in sorted(routes):
        page = output / route.lstrip('/') / 'index.html'
        if not page.is_file():
            raise ValueError('Missing measured mobile route: ' + route)
        html = page.read_text()
        if SCRIPT_MARKER in html or PICTURE_MARKER in html:
            validate_deferred_mobile_media(output, page, html)
            continue
        amended, count = transform_page(html, controller, route)
        validate_deferred_mobile_media(output, page, amended)
        updates.append((page, amended, count))
    for page, amended, _ in updates:
        page.write_text(amended)
    return {'pages': len(routes), 'pictures': sum(count for _, _, count in updates),
            'compatibility_alias_routes': len(redirect_aliases()),
            'already_prepared': len(routes) - len(updates),
            'root_margin': '0px for the approved 39-route cohort; 250px elsewhere'}


def _normalized_picture_tokens(picture, deferred):
    nodes = ([picture] if picture.tag in {'picture', 'source', 'img'} else [])
    nodes += picture.find(lambda node: node.tag in {'source', 'img'})
    result = []
    for node in nodes:
        attrs = dict(node.attrs)
        attrs.pop(PICTURE_MARKER, None)
        if deferred:
            if node.tag == 'img':
                placeholder = attrs.pop('src', '')
                if not placeholder.startswith('data:image/svg+xml,'):
                    raise ValueError('Deferred image placeholder performs no network request')
                attrs['src'] = attrs.pop('data-piskor-src', None)
            if 'data-piskor-srcset' in attrs:
                if 'srcset' in attrs:
                    raise ValueError('Deferred picture still has an active srcset')
                attrs['srcset'] = attrs.pop('data-piskor-srcset')
        result.append((node.tag, attrs))
    return result


def validate_deferred_mobile_media(output, page, html):
    output = generated_root(output)
    route = _route_for_page(output, page)
    target = route in target_routes()
    if route in redirect_aliases() and SCRIPT_MARKER not in html and PICTURE_MARKER not in html:
        _validate_redirect_alias(html, route)
        return
    if not target:
        if SCRIPT_MARKER in html or PICTURE_MARKER in html or FALLBACK_MARKER in html:
            raise ValueError('Deferred media was added outside the measured route cohort')
        return

    from agent_catalog import Document
    from case_minification import minify_fragment
    script = _controller_tag(CONTROLLER.read_text(), target_root_margin(route))
    if script not in html and minify_fragment(script) not in html:
        raise ValueError('Deferred-media controller source/hash differs from reviewed source')
    root = Document(html).root
    scripts = root.find(lambda node: node.tag == 'script' and SCRIPT_MARKER in node.attrs)
    active = root.find(lambda node: node.tag == 'picture' and PICTURE_MARKER in node.attrs)
    fallbacks = root.find(lambda node: node.tag == 'noscript' and FALLBACK_MARKER in node.attrs)
    styles = root.find(lambda node: node.tag == 'noscript' and STYLE_MARKER in node.attrs)
    if len(scripts) != 1 or not active or len(active) != len(fallbacks):
        raise ValueError('Deferred image/controller coverage differs')
    if len(styles) != 1 or 'picture[' + PICTURE_MARKER + ']{display:none!important}' not in html:
        raise ValueError('Missing native no-JavaScript image fallback styling')
    fallback_pictures = []
    for fallback in fallbacks:
        pictures = fallback.find(lambda node: node.tag == 'picture')
        if len(pictures) != 1:
            raise ValueError('Native fallback must contain exactly one original picture')
        fallback_pictures.append(pictures[0])
    if any(_normalized_picture_tokens(on, True) != _normalized_picture_tokens(off, False)
           for on, off in zip(active, fallback_pictures)):
        raise ValueError('Deferred active picture differs from its no-JavaScript original')
