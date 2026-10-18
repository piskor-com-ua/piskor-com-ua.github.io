"""Serve two legacy entry URLs from their exact prepared canonical documents."""
from pathlib import Path
from urllib.parse import urlsplit
import hashlib

from agent_catalog import Document
from agent_content import markdown_path


ORIGIN = 'https://piskor.com.ua'
COMPATIBILITY_ROUTES = {
    '/portfolio/2026/bedroom-lighting-automation/': '/portfolio/2021/two-level-loft-lviv/',
    '/en/portfolio/2026/bedroom-lighting-automation/': '/en/portfolio/2021/two-level-loft-lviv/',
}


def _root(output):
    output = Path(output).resolve()
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only a generated Pages artifact may receive compatibility copies')
    return output


def _page(output, route):
    path = output / route.lstrip('/') / 'index.html'
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(output):
        raise ValueError('Missing or unsafe compatibility document: ' + route)
    return path


def _target(output, route):
    if route in COMPATIBILITY_ROUTES:
        raise ValueError('Compatibility copies must not form a chain')
    content = _page(output, route).read_bytes()
    root = Document(content.decode('utf-8')).root
    language = 'en' if route.startswith('/en/') else 'uk'
    html = root.find(lambda node: node.tag == 'html')
    canonical = root.find(lambda node: node.tag == 'link' and node.attrs.get('rel') == 'canonical')
    refresh = root.find(lambda node: node.tag == 'meta' and node.attrs.get('http-equiv', '').lower() == 'refresh')
    agents = root.find(lambda node: node.tag == 'script' and urlsplit(node.attrs.get('src', '')).path == '/agent-tools.js')
    compatibility = root.find(lambda node: node.tag == 'script' and urlsplit(node.attrs.get('src', '')).path == '/url-compat.js')
    controller = output / 'url-compat.js'
    if not controller.is_file():
        raise ValueError('Compatibility target needs its prepared shared controller: ' + route)
    controller_url = '/url-compat.js?v=' + hashlib.sha256(controller.read_bytes()).hexdigest()[:12]
    if (len(html) != 1 or html[0].attrs.get('lang') != language or len(canonical) != 1
            or canonical[0].attrs.get('href') != ORIGIN + route or refresh or len(agents) != 1 or len(compatibility) != 1
            or compatibility[0].attrs.get('src') != controller_url or 'defer' not in compatibility[0].attrs
            or not root.find(lambda node: node.tag == 'main' and node.attrs.get('id') == 'main')
            or not root.find(lambda node: node.attrs.get('id') == 'contact')):
        raise ValueError('Compatibility target must be the complete canonical page in its own language: ' + route)
    return content


def prepare_compatibility_pages(output):
    """Copy only after resource preparation and before per-route Markdown links."""
    output = _root(output)
    plans = []
    for alias, target in COMPATIBILITY_ROUTES.items():
        if alias.startswith('/en/') != target.startswith('/en/'):
            raise ValueError('Compatibility mapping must preserve language')
        path, content = _page(output, alias), _target(output, target)
        previous = path.read_bytes()
        if previous != content:
            # Do not replace an unrelated page if the declared legacy route changes.
            old = Document(previous.decode('utf-8')).root
            refresh = old.find(lambda node: node.tag == 'meta' and node.attrs.get('http-equiv', '').lower() == 'refresh')
            canonical = old.find(lambda node: node.tag == 'link' and node.attrs.get('rel') == 'canonical')
            if (len(refresh) != 1 or refresh[0].attrs.get('content') != '0;url=' + target
                    or len(canonical) != 1 or canonical[0].attrs.get('href') != ORIGIN + target):
                raise ValueError('Compatibility source must declare its exact existing target: ' + alias)
        plans.append((path, content))
    # Both source/target pairs must validate before replacing either document.
    for path, content in plans:
        path.write_bytes(content)
    return len(plans)


def validate_compatibility_pages(output, markdown_alternatives=False):
    """Allow only each document's own generated Markdown link to differ."""
    output = _root(output)
    for alias, target in COMPATIBILITY_ROUTES.items():
        actual, expected = _page(output, alias).read_bytes(), _target(output, target)
        if markdown_alternatives:
            normalized = []
            for route, content in ((alias, actual), (target, expected)):
                relative = Path(route.lstrip('/')) / 'index.html'
                link = ('<link rel="alternate" type="text/markdown" href="/'
                        + markdown_path(relative) + '">\n').encode()
                if content.count(link) != 1:
                    raise ValueError('Compatibility page needs its own single Markdown alternative: ' + route)
                normalized.append(content.replace(link, b''))
            actual, expected = normalized
        if actual != expected:
            raise ValueError('Compatibility HTML differs from its prepared canonical document: ' + alias)
    return len(COMPATIBILITY_ROUTES)
