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


def target_routes():
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
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.lines = [0]
        for match in re.finditer('\n', html):
            self.lines.append(match.end())
        self.stack = []
        self.current = None
        self.spans = []

    def _offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get('class', '').split())
        if tag == 'picture':
            gallery = any(names & {'gallery-grid', 'case-images'} for _, names in self.stack)
            catalog = any('portfolio-card-image' in names for _, names in self.stack)
            if gallery or catalog:
                if self.current is not None:
                    raise ValueError('Nested image pictures are unsupported')
                self.current = {'start': self._offset(), 'kind': 'gallery' if gallery else 'catalog'}
        if tag not in VOID:
            self.stack.append((tag, classes))

    def handle_endtag(self, tag):
        if tag == 'picture' and self.current is not None:
            end = self.html.index('>', self._offset()) + 1
            self.spans.append((self.current['start'], end, self.current['kind']))
            self.current = None
        if tag not in VOID:
            if not self.stack or self.stack[-1][0] != tag:
                raise ValueError('Malformed image document nesting')
            self.stack.pop()


def _picture_spans(html):
    parser = _Pictures(html)
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


def _controller_tag(controller):
    return ('<script ' + SCRIPT_MARKER + ' data-source-sha256="'
            + hashlib.sha256(controller.encode()).hexdigest() + '">'
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
    script = _controller_tag(CONTROLLER.read_text())
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
    spans = _picture_spans(html)
    selected = []
    for start, end, kind in spans:
        original = html[start:end]
        image, attrs = _picture_img(original, require_lazy=(kind == 'gallery'))
        # The first catalog cover is eager; all other lazy cards can wait until
        # they approach the viewport. Every story-gallery image is lazy.
        if kind == 'gallery' or attrs.get('loading') == 'lazy':
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
    script = _controller_tag(controller)
    critical = re.search(r'<script\b[^>]*\bdata-inline-page-critical=["\']agent-tools\.js["\']', html)
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
            'already_prepared': len(routes) - len(updates), 'root_margin': '250px 0px'}


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
    script = _controller_tag(CONTROLLER.read_text())
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
