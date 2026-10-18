"""Prepare early rendering from shared sources in the generated artifact only."""
from html import escape, unescape
from pathlib import Path
from urllib.parse import urlsplit, urljoin
import hashlib
import re

from fontTools import subset
from fontTools.ttLib import TTFont
from catalog_css import catalog_classes, prune_catalog_css


FONT_NAMES = ('roboto-light', 'roboto-regular')
CONSENT_SCRIPT = re.compile(r'<script\b(?=[^>]*\bsrc=["\']/analytics-consent\.js["\'])[^>]*>\s*</script>', re.I)
CATALOG_SHEET = re.compile(r'<link\b[^>]*\bhref=["\']/catalog-bundle\.css(?:\?[^"\']*)?["\'][^>]*>', re.I)
BODY = re.compile(r'<body\b[^>]*>', re.I)


def generated_root(output):
    output = Path(output)
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only a generated Pages artifact may be prepared')
    return output


def inline_consent(output):
    """Run the existing consent controller at body start, before the first paint."""
    output = generated_root(output)
    controller = (output / 'analytics-consent.js').read_text()
    if '</script' in controller.lower():
        raise ValueError('Consent controller contains an HTML script terminator')
    count = 0
    for page in output.rglob('*.html'):
        html = page.read_text()
        match = CONSENT_SCRIPT.search(html)
        if not match:
            continue
        measurement = re.search(r'data-measurement-id=["\']([^"\']*)["\']', match[0])
        if not measurement or not BODY.search(html):
            raise ValueError(f'Missing consent configuration or body: {page}')
        script = '<script data-consent-inline data-measurement-id="' + escape(measurement[1], quote=True) + '">' + controller + '</script>'
        html = html[:match.start()] + html[match.end():]
        html = BODY.sub(lambda body: body[0] + script, html, count=1)
        page.write_text(html)
        count += 1
    return count


def subset_fonts(output):
    """Include rendered and dynamic text, CSS escapes and complete UA/ASCII input."""
    output = generated_root(output)
    characters = set(range(32, 127))
    characters.update(map(ord, 'АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯабвгґдеєжзиіїйклмнопрстуфхцчшщьюя²↗←→↓'))
    texts = [path for path in output.rglob('*') if path.suffix in {'.html', '.js', '.css'}]
    for path in texts:
        text = path.read_text()
        characters.update(map(ord, text))
        if path.suffix == '.html':
            characters.update(map(ord, unescape(text)))
        for code in re.findall(r'\\u(?:\{([a-fA-F0-9]{1,6})\}|([a-fA-F0-9]{4}))', text):
            characters.add(int(code[0] or code[1], 16))
        if path.suffix == '.css':
            characters.update(int(code, 16) for code in re.findall(r'\\([a-fA-F0-9]{1,6})(?:\s|(?=[^a-fA-F0-9]))', text))
    folder = output / 'assets' / 'fonts'
    folder.mkdir(exist_ok=True)
    sizes = {}
    replacements = {}
    for name in FONT_NAMES:
        source = output / 'assets' / (name + '.woff2')
        target = folder / (name + '-subset.woff2')
        with TTFont(source, recalcTimestamp=False) as font:
            required = characters.intersection(font.getBestCmap())
            options = subset.Options()
            options.flavor = 'woff2'
            # Keep outlines, shaping and metrics; omit legacy grid-fitting bytecode.
            options.hinting = False
            worker = subset.Subsetter(options=options)
            worker.populate(unicodes=sorted(required))
            worker.subset(font)
            font.save(target)
        with TTFont(target) as font:
            if not required.issubset(font.getBestCmap()):
                raise ValueError('Font subset lost required characters: ' + name)
        sizes[name] = {'original': source.stat().st_size, 'subset': target.stat().st_size}
        replacements['assets/' + name + '.woff2'] = 'assets/fonts/' + name + '-subset.woff2'
    for path in texts:
        text = path.read_text()
        for original, replacement in replacements.items():
            text = text.replace(original, replacement)
        path.write_text(text)
    return sizes


def inline_catalog_styles(output):
    """Inline the small shared bundle, preserving order and absolute asset URLs."""
    output = generated_root(output)
    pages = sorted(path for path in output.rglob('*.html')
                   if CATALOG_SHEET.search(path.read_text()))
    css = (output / 'catalog-bundle.css').read_text()
    css = prune_catalog_css(css, catalog_classes(output, pages))
    css = re.sub(r'url\(\s*(["\']?)(assets/)', r'url(\1/\2', css)
    if '</style' in css.lower():
        raise ValueError('Catalog stylesheet contains an HTML style terminator')
    digest = hashlib.sha256(css.encode()).hexdigest()[:12]
    style = '<style data-catalog-styles="' + digest + '">' + css + '</style>'
    count = 0
    for page in pages:
        html, replaced = CATALOG_SHEET.subn(lambda _: style, page.read_text())
        if replaced:
            page.write_text(html)
            count += 1
    return count


def _page_style_family(output, page, html):
    """Only known page families may use a narrower class inventory."""
    relative = page.relative_to(output).as_posix()
    if relative in {'index.html', 'en/index.html'}:
        return 'home'
    if relative == '404.html':
        return 'not-found'
    body = BODY.search(html)
    classes = re.search(r'(?<![\w-])class\s*=\s*["\']([^"\']*)["\']', body[0], re.I) if body else None
    names = set(unescape(classes[1]).split()) if classes else set()
    if ('project-page' in names and 'catalog-page' not in names
            and re.fullmatch(r'(?:en/)?portfolio/\d{4}/[^/]+/index\.html', relative)):
        return 'case'
    return 'all'


def inline_page_styles(output):
    """Remove stylesheet round trips while retaining every possible page state.

    Pruning uses all HTML and local controllers within a known page family:
    both home languages, every case together, or the 404 page. Unknown pages
    retain the union of all non-catalog pages. Each replacement stays at its
    original cascade position; unknown external styles are left untouched.
    """
    output = generated_root(output)
    pages = sorted(path for path in output.rglob('*.html')
                   if 'data-catalog-styles=' not in path.read_text())
    families = {}
    family_pages = {}
    for page in pages:
        family = _page_style_family(output, page, page.read_text())
        families[page] = family
        family_pages.setdefault(family, []).append(page)
    family_classes = {family: catalog_classes(output, pages if family == 'all' else members)
                      for family, members in family_pages.items()}
    pattern = re.compile(r'<link\b(?=[^>]*\brel=["\']stylesheet["\'])[^>]*>', re.I)
    count = 0
    cache = {}
    for page in pages:
        family = families[page]
        def replace(match):
            nonlocal count
            href = re.search(r'\bhref=["\']([^"\']+)["\']', match[0], re.I)
            if not href:
                return match[0]
            parsed = urlsplit(unescape(href[1]))
            if parsed.scheme or parsed.netloc or not parsed.path.startswith('/'):
                return match[0]
            target = (output / parsed.path.lstrip('/')).resolve()
            if not target.is_relative_to(output.resolve()) or not target.is_file():
                raise ValueError('Missing local stylesheet: ' + href[1])
            key = (family, target)
            if key not in cache:
                css = prune_catalog_css(target.read_text(), family_classes[family])
                def absolute_url(found):
                    quote, resource = found[1], found[2]
                    return 'url(' + quote + urljoin(parsed.path, resource) + quote + ')'
                css = re.sub(r'''url\(\s*(["']?)([^"')\s]+)\1\s*\)''', absolute_url, css)
                if '</style' in css.lower():
                    raise ValueError('Stylesheet contains an HTML style terminator')
                cache[key] = css
            media = re.search(r'\bmedia=["\']([^"\']*)["\']', match[0], re.I)
            css = cache[key]
            digest = hashlib.sha256(css.encode()).hexdigest()[:12]
            count += 1
            return '<style data-page-styles="' + digest + '"' + (' media="' + escape(media[1], quote=True) + '"' if media else '') + '>' + css + '</style>'
        page.write_text(pattern.sub(replace, page.read_text()))
    return count


HOME_CRITICAL_SCRIPTS = ('agent-tools.js', 'home-bootstrap.js', 'url-compat.js')
HOME_INLINE_PAGES = {'index.html': 'uk', 'en/index.html': 'en'}
HOME_INLINE_MARKER = 'data-inline-home-critical'
HOME_EXTERNAL_SCRIPT = re.compile(r'<script\b(?P<attrs>[^>]*)>\s*</script\s*>', re.I)


def _home_critical_payload(output):
    """Exact shared sources, without defer/currentScript timing assumptions."""
    sources, payload = {}, []
    for name in HOME_CRITICAL_SCRIPTS:
        source = (output / name).read_bytes().decode('utf-8')
        if re.search(r'</script\b', source, re.I):
            raise ValueError('Home controller contains an HTML script terminator: ' + name)
        if re.search(r'document\s*\.\s*currentScript|\bDOMContentLoaded\b', source):
            raise ValueError('Home controller needs an explicit timing review: ' + name)
        digest = hashlib.sha256(source.encode()).hexdigest()
        sources[name] = (source, digest)
        # Inline classic scripts ignore defer. DOM-ready callbacks preserve the
        # original source order, an interactive complete DOM, and before-load
        # registration of native tools and compatibility/hash listeners.
        payload.append('<script ' + HOME_INLINE_MARKER + '="' + name
                       + '" data-source-sha256="' + digest + '">\n'
                       + "document.addEventListener('DOMContentLoaded', () => {\n"
                       + source + '\n}, { once: true });\n</script>\n')
    return sources, ''.join(payload)


def validate_home_inline_scripts(output, html):
    """Fail on stale source/hash, duplicate execution, order or timing changes."""
    output = generated_root(output)
    _, expected = _home_critical_payload(output)
    names = re.findall(r'<script\b[^>]*\b' + HOME_INLINE_MARKER
                       + r'=["\']([^"\']+)["\']', html, re.I)
    if tuple(names) != HOME_CRITICAL_SCRIPTS:
        raise ValueError('Home inline controller coverage/order differs from the shared contract')
    bodies = list(re.finditer(r'</body\s*>', html, re.I))
    if len(bodies) != 1 or not html[:bodies[0].start()].endswith(expected):
        raise ValueError('Home inline source/hash/DOM-ready wrapper/body position differs')
    from html.parser import HTMLParser

    class ExternalScripts(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == 'script':
                reference = urlsplit(dict(attrs).get('src', ''))
                if reference.path in {'/' + name for name in HOME_CRITICAL_SCRIPTS}:
                    raise ValueError('Home controller is both inline and external')

    ExternalScripts().feed(html)


def inline_home_critical_scripts(output):
    """Inline only the two measured home routes, keeping all other pages intact."""
    output = generated_root(output)
    sources, payload = _home_critical_payload(output)
    from html.parser import HTMLParser

    class ScriptAttributes(HTMLParser):
        def handle_starttag(self, tag, attrs):
            self.attributes = attrs

    plans = []
    for relative, language in HOME_INLINE_PAGES.items():
        page = output / relative
        html = page.read_bytes().decode('utf-8')
        if ('<html lang="' + language + '"' not in html
                or 'data-home-render="' + language + '"' not in html):
            raise ValueError('Expected the prerendered localized homepage: ' + relative)
        if HOME_INLINE_MARKER in html:
            raise ValueError('Home critical controllers are already inlined')
        body = re.search(r'<body\b', html, re.I)
        if not body:
            raise ValueError('Missing home body: ' + relative)
        ordered = []

        def remove(match):
            parser = ScriptAttributes()
            parser.feed(match[0])
            attrs = dict(parser.attributes)
            reference = urlsplit(unescape(attrs.get('src', '')))
            name = reference.path.lstrip('/')
            if name not in HOME_CRITICAL_SCRIPTS:
                return match[0]
            if (reference.scheme or reference.netloc or reference.path != '/' + name
                    or set(attrs) != {'src', 'defer'} or len(parser.attributes) != 2
                    or match.start() >= body.start()):
                raise ValueError('Unsupported home script attributes/location: ' + name)
            if reference.query != 'v=' + sources[name][1][:12] or reference.fragment:
                raise ValueError('Home controller URL does not match its source hash: ' + name)
            ordered.append(name)
            return ''

        updated = HOME_EXTERNAL_SCRIPT.sub(remove, html)
        if tuple(ordered) != HOME_CRITICAL_SCRIPTS:
            raise ValueError('Expected each deferred home controller once in source order')
        closing = list(re.finditer(r'</body\s*>', updated, re.I))
        if len(closing) != 1:
            raise ValueError('Expected one home body end: ' + relative)
        index = closing[0].start()
        updated = updated[:index] + payload + updated[index:]
        validate_home_inline_scripts(output, updated)
        plans.append((page, updated))
    # Validate both routes before changing either one.
    for page, updated in plans:
        page.write_bytes(updated.encode('utf-8'))
    return len(plans)
