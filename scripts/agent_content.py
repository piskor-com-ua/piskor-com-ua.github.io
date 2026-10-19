"""Derive readable alternatives from the public HTML, never from private sources."""
import json
import re
from pathlib import Path
from html import escape
from urllib.parse import urljoin, urlsplit

from agent_catalog import Document, Node

ORIGIN = 'https://piskor.com.ua'
MARKDOWN_ROOT = 'agent-markdown'
POPPY_PATH = '.well-known/poppy.json'


def page_route(relative):
    value = relative.as_posix()
    return '/' + value[:-10] if value.endswith('index.html') else '/' + value


def markdown_path(relative):
    return MARKDOWN_ROOT + '/' + relative.with_suffix('.md').as_posix()


def inline(text):
    """Escape author text so punctuation cannot turn into Markdown instructions."""
    return re.sub(r'([\\`*_[\]<>])', r'\\\1', ' '.join(text.split()))


def render(node, base):
    if isinstance(node, str):
        # Keep author whitespace between adjacent inline tags; only escape syntax.
        return re.sub(r'([\\`*_[\]<>])', r'\\\1', node)
    attrs, tag = node.attrs, node.tag
    if tag in {'script', 'style', 'noscript', 'template', 'dialog', 'svg'} or 'hidden' in attrs or attrs.get('aria-hidden') == 'true':
        return ''
    body = ''.join(render(child, base) for child in node.children)
    if tag == 'a':
        href = attrs.get('href', '').strip()
        if not href or href.lower().startswith(('javascript:', 'data:')):
            return body
        label = ' '.join(body.split()) or inline(attrs.get('aria-label', ''))
        # Empty fragments mean the same document; normalize explicitly because
        # urllib's preservation of a trailing '#' differs between Python versions.
        target = urljoin(base, href)
        if not urlsplit(target).fragment:
            target = target.removesuffix('#')
        return '[' + label + '](' + target.replace(' ', '%20').replace('(', '%28').replace(')', '%29') + ')'
    if tag == 'img':
        alt = attrs.get('alt', '').strip()
        return '\n\n' + inline(alt) + '\n\n' if alt else ''
    if re.fullmatch(r'h[1-6]', tag):
        return '\n\n' + '#' * int(tag[1]) + ' ' + ' '.join(body.split()) + '\n\n'
    if tag == 'li':
        return '\n- ' + ' '.join(body.split())
    if tag == 'dt':
        return '\n\n' + body + ': '
    if tag in {'p', 'div', 'section', 'article', 'main', 'header', 'footer', 'nav', 'ul', 'ol', 'dl', 'figure', 'figcaption', 'blockquote', 'button'}:
        return '\n\n' + body.strip() + '\n\n'
    if tag == 'br':
        return '\n'
    return body


def generate_agent_content(output):
    output = Path(output)
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only a generated Pages artifact may receive content alternatives')
    pages = sorted(output.rglob('*.html'))
    routes = []
    for page in pages:
        relative = page.relative_to(output)
        route = page_route(relative)
        source = page.read_text()
        alternative = '<link rel="alternate" type="text/markdown" href="/' + escape(markdown_path(relative), quote=True) + '">'
        if alternative not in source:
            source = source.replace('</head>', alternative + '\n</head>', 1)
            page.write_text(source)
        root = Document(source).root
        html = root.find(lambda n: n.tag == 'html')
        titles = root.find(lambda n: n.tag == 'title')
        canonical = root.find(lambda n: n.tag == 'link' and n.attrs.get('rel') == 'canonical')
        robots = root.find(lambda n: n.tag == 'meta' and n.attrs.get('name') == 'robots')
        body = root.find(lambda n: n.tag == 'body')
        if not titles or not body:
            raise ValueError('Missing public document metadata: ' + route)
        metadata = {
            'title': titles[0].text(),
            'url': ORIGIN + route,
            'canonical': canonical[0].attrs['href'] if canonical else ORIGIN + route,
            'language': html[0].attrs.get('lang', 'uk') if html else 'uk',
            'robots': robots[0].attrs.get('content', 'noindex,nofollow') if robots else 'noindex,nofollow',
        }
        # JSON strings are valid YAML scalars. No author text becomes frontmatter syntax.
        frontmatter = '---\n' + ''.join(key + ': ' + json.dumps(value, ensure_ascii=False) + '\n' for key, value in metadata.items()) + '---\n\n'
        text = render(body[0], ORIGIN + route)
        text = re.sub(r'[ \t]+\n', '\n', text)
        text = re.sub(r'\n[ \t]+', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        target = output / markdown_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(frontmatter + text + '\n')
        routes.append({'url': route, 'markdown': '/' + markdown_path(relative), 'language': metadata['language']})
        if relative.as_posix() == '404.html' and (output / 'not-found.js').is_file():
            english = Document(source).root
            for node in english.find(lambda n: 'data-error-en' in n.attrs):
                node.children = [node.attrs['data-error-en']]
            for node in english.find(lambda n: 'data-error-en-label' in n.attrs):
                node.attrs['aria-label'] = node.attrs['data-error-en-label']
            for node in english.find(lambda n: 'data-error-path' in n.attrs):
                node.attrs['href'] = '/en' + node.attrs['data-error-path']
            # Derive the title from the same controller used by the public page.
            title = re.search(r"const title = '([^']*)';", (output / 'not-found.js').read_text())
            if not title:
                raise ValueError('Missing English error title in its public controller')
            en_route, en_path = '/404.html?lang=en', MARKDOWN_ROOT + '/404-en.md'
            en_meta = {**metadata, 'title': title[1], 'url': ORIGIN + en_route, 'language': 'en'}
            en_front = '---\n' + ''.join(key + ': ' + json.dumps(value, ensure_ascii=False) + '\n' for key, value in en_meta.items()) + '---\n\n'
            en_text = render(english.find(lambda n: n.tag == 'body')[0], ORIGIN + en_route)
            en_text = re.sub(r'\n{3,}', '\n\n', en_text).strip()
            (output / en_path).write_text(en_front + en_text + '\n')
            routes.append({'url': en_route, 'markdown': '/' + en_path, 'language': 'en'})
    (output / MARKDOWN_ROOT / 'routes.json').write_text(json.dumps({'version': 1, 'pages': routes}, ensure_ascii=False, separators=(',', ':')) + '\n')
    # Draft 0.1 explicitly permits web:{} with no auth: ordinary public browsing.
    # This advertises no agent server, API sessions, sign-in, or messaging service.
    (output / POPPY_PATH).parent.mkdir(exist_ok=True)
    (output / POPPY_PATH).write_text(json.dumps({
        'protocol_version': '0.1',
        'organization': {'name': 'PISKOR Architect', 'domain': 'piskor.com.ua'},
        'web': {},
    }, separators=(',', ':')) + '\n')
    return routes
