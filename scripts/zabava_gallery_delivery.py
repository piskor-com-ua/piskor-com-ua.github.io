"""Near-viewport gallery delivery for only the generated English Zabava page.

Keep responsive original pictures intact in noscript. The active images retain
their semantics and intrinsic dimensions; only fetch-triggering URLs are deferred.
Run after shared CSS inlining, before final page minification/Markdown generation.
"""
from html import escape
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re

from first_paint import generated_root

ROUTE = 'en/portfolio/2022/zabava-restaurant-sambir/index.html'
CONTROLLER = Path(__file__).with_name('zabava-gallery-controller.js')
MARKER = 'data-zabava-gallery-delivery'
FALLBACK = '<noscript><style>picture[data-zabava-gallery]{display:none!important}</style></noscript>'
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}


def defer_zabava_gallery(output):
    output = generated_root(output)
    page = output / ROUTE
    if not page.is_file():
        return None
    html = page.read_text()
    if MARKER in html:
        validate_zabava_gallery(output, page, html)
        return {'pictures': 0, 'already_prepared': True}
    controller = CONTROLLER.read_text()
    if '</script' in controller.lower():
        raise ValueError('Gallery controller contains an HTML script terminator')
    lines = [0]
    for match in re.finditer('\n', html):
        lines.append(match.end())

    class Pictures(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.spans = [], []
            self.start = None

        def source_offset(self):
            line, column = self.getpos()
            return lines[line - 1] + column

        def handle_starttag(self, tag, attrs):
            classes = set(dict(attrs).get('class', '').split())
            if tag == 'picture' and any(names & {'gallery-grid', 'case-images'} for _, names in self.stack):
                if self.start is not None:
                    raise ValueError('Nested gallery picture')
                self.start = self.source_offset()
            if tag not in VOID:
                self.stack.append((tag, classes))

        def handle_endtag(self, tag):
            if tag == 'picture' and self.start is not None:
                self.spans.append((self.start, html.index('>', self.source_offset()) + 1))
                self.start = None
            if tag not in VOID:
                if not self.stack or self.stack[-1][0] != tag:
                    raise ValueError('Malformed gallery document nesting')
                self.stack.pop()

    parser = Pictures()
    parser.feed(html)
    parser.close()
    if parser.start is not None or parser.stack:
        raise ValueError('Unclosed gallery document')
    if not parser.spans:
        raise ValueError('Expected Zabava gallery pictures')

    def prepare(original):
        images = re.findall(r'<img\b[^>]*>', original, re.I)
        if len(images) != 1:
            raise ValueError('Expected one image per gallery picture')
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', images[0]))
        if (attrs.get('loading') != 'lazy' or not attrs.get('alt') or
                not attrs.get('src', '').startswith('/assets/') or
                not all(re.fullmatch(r'[1-9]\d*', attrs.get(name, '')) for name in ('width', 'height'))):
            raise ValueError('Unrecognized gallery image contract')
        placeholder = ('data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20width=%22'
                       + attrs['width'] + '%22%20height=%22' + attrs['height'] + '%22%3E%3C/svg%3E')

        def defer_tag(match):
            tag = match[0]
            tag = re.sub(r'(?<![\w-])srcset=', 'data-zabava-srcset=', tag)
            if tag.startswith('<img'):
                tag = re.sub(r'(?<![\w-])src=', 'data-zabava-src=', tag)
                tag = tag.replace('<img', '<img src="' + escape(placeholder, quote=True) + '"', 1)
            return tag

        active = re.sub(r'<(?:img|source)\b[^>]*>', defer_tag, original)
        active = active.replace('<picture', '<picture data-zabava-gallery', 1)
        return active + '<noscript>' + original + '</noscript>'

    for start, end in reversed(parser.spans):
        html = html[:start] + prepare(html[start:end]) + html[end:]
    if html.count('</head>') != 1 or html.count('</body>') != 1:
        raise ValueError('Expected one document head/body')
    html = html.replace('</head>', FALLBACK + '</head>', 1)
    script = _controller_tag(controller)
    critical = re.search(r'<script\b[^>]*\bdata-inline-page-critical=["\']agent-tools\.js["\']', html)
    index = critical.start() if critical else html.index('</body>')
    html = html[:index] + script + html[index:]
    validate_zabava_gallery(output, page, html)
    page.write_text(html)
    return {'pictures': len(parser.spans), 'root_margin': '750px 0px'}


def _controller_tag(controller):
    return ('<script ' + MARKER + ' data-source-sha256="'
            + hashlib.sha256(controller.encode()).hexdigest() + '">' + controller + '</script>')


def validate_zabava_gallery(output, page, html):
    """Verify route, controller source/hash and native fallback picture parity."""
    output = generated_root(output)
    if Path(page).relative_to(output).as_posix() != ROUTE:
        if MARKER in html or 'data-zabava-gallery' in html:
            raise ValueError('Deferred gallery must remain on the exact English route')
        return
    from agent_catalog import Document
    from case_minification import minify_fragment
    controller = _controller_tag(CONTROLLER.read_text())
    if controller not in html and minify_fragment(controller) not in html:
        raise ValueError('Gallery controller source/hash differs from reviewed source')
    root = Document(html).root
    scripts = root.find(lambda n: n.tag == 'script' and MARKER in n.attrs)
    if len(scripts) != 1:
        raise ValueError('Expected one deferred gallery controller')
    styles = root.find(lambda n: n.tag == 'noscript' and
                       n.find(lambda child: child.tag == 'style'))
    if len(styles) != 1 or 'picture[data-zabava-gallery]{display:none!important}' not in html:
        raise ValueError('Missing native no-JS placeholder hiding rule')
    active = root.find(lambda n: n.tag == 'picture' and 'data-zabava-gallery' in n.attrs)
    fallback = [picture for node in root.find(lambda n: n.tag == 'noscript')
                for picture in node.find(lambda n: n.tag == 'picture')]
    if not active or len(active) != len(fallback):
        raise ValueError('Deferred/native picture coverage differs')

    def tokens(node, deferred):
        result = []
        for child in node.find(lambda n: n.tag in {'picture', 'source', 'img'}):
            attrs = dict(child.attrs)
            attrs.pop('data-zabava-gallery', None)
            if deferred:
                if child.tag == 'img':
                    if not attrs.pop('src', '').startswith('data:image/svg+xml,'):
                        raise ValueError('Deferred gallery placeholder performs an external request')
                    attrs['src'] = attrs.pop('data-zabava-src', None)
                if 'data-zabava-srcset' in attrs:
                    if 'srcset' in attrs:
                        raise ValueError('Deferred picture still has an active srcset')
                    attrs['srcset'] = attrs.pop('data-zabava-srcset')
            result.append((child.tag, attrs))
        return result

    if any(tokens(a, True) != tokens(b, False) for a, b in zip(active, fallback)):
        raise ValueError('Deferred picture differs from its native no-JS original')
