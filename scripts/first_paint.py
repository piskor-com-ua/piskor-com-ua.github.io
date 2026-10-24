"""Prepare early rendering from shared sources in the generated artifact only."""
from html import escape, unescape
from pathlib import Path
import json
from urllib.parse import urlsplit, urljoin
import hashlib
import re

from fontTools import subset
from fontTools.ttLib import TTFont
from catalog_css import catalog_classes, prune_catalog_css


FONT_NAMES = ('roboto-light', 'roboto-regular')
ENGINEERING_INLINE_PAGES = frozenset({
    'engineering-automation/index.html', 'en/engineering-automation/index.html',
})
CONSENT_SCRIPT = re.compile(r'<script\b(?=[^>]*\bsrc=["\']/analytics-consent\.js["\'])[^>]*>\s*</script>', re.I)
CATALOG_SHEET = re.compile(r'<link\b[^>]*\bhref=["\']/catalog-bundle\.css(?:\?[^"\']*)?["\'][^>]*>', re.I)
BODY = re.compile(r'<body\b[^>]*>', re.I)
BODY_END = re.compile(r'</body\s*>', re.I)
# The performance-maintenance contract approves the 39-route mobile target
# cohort as a bounded optimization scope. Catalogs and legacy redirect aliases
# are deliberately excluded; all other pages retain the family CSS union.
TARGET_COHORT = json.loads((Path(__file__).with_name('mobile-si-target-routes.json')).read_text())
TARGET_CASE_SCOPES = frozenset(
    str(Path(route.lstrip('/')) / 'index.html')
    for route in TARGET_COHORT['routes']
    if route not in TARGET_COHORT.get('redirect_aliases', {})
    and len(route.strip('/').split('/')) == 3 + (route.startswith('/en/'))
)
# Preserve the earlier reviewed follow-up routes and extend the same fail-closed
# controller checks to canonical case pages in the approved target cohort.
PAGE_STYLE_SCOPES = frozenset({
    'en/portfolio/2020/family-house-solonka/index.html',
    'portfolio/2021/berloha-lounge-bar-lviv/index.html',
    'en/portfolio/2022/zabava-restaurant-sambir/index.html',
    'en/portfolio/2024/markosoli-store/index.html',
    'en/portfolio/2025/vesteros-house/index.html',
    # Current production PSI still measures this approved case outside the
    # historical 39-route cohort. Keep its CSS inventory route-scoped too.
    'portfolio/2024/domazhyr-house/index.html',
    'engineering-automation/index.html',
    'en/engineering-automation/index.html',
}) | TARGET_CASE_SCOPES
SCOPED_STYLE_CONTROLLERS = frozenset({
    'analytics-consent.js', 'agent-tools.js', 'portfolio.js', 'url-compat.js',
})
# Changing a reviewed controller requires rechecking its dynamic class states.
# Unknown revisions safely retain complete CSS, including computed assignments.
SCOPED_CONTROLLER_SHA256 = {
    'analytics-consent.js': 'b74abfc1372fd34499519c92486c471d98fee3627792e882a2f23a0d9b878feb',
    'agent-tools.js': 'df7313413ea89c038d733102cb2b0d09e2547c51294d1a98d18170ec3de11d72',
    'portfolio.js': '82ceee047af3508289a0dba2b353d13691210f7e538b66bc75f022e1ce699290',
    'url-compat.js': '9c74c56d65c26cc6499daa6d12a1714a1307cce2b94743a7469a91171623efa0',
    'engineering-automation.js': '3f422e22c43867c8b81069f5fed725ed48052cde9cbbc1867bca6fa270195079',
}


def _reviewed_style_controller(output, name):
    path = output / name
    if not path.is_file():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == SCOPED_CONTROLLER_SHA256.get(name)


def _scoped_style_classes(output, page):
    """Only reviewed shared controllers may narrow this route's CSS inventory.

    Check inline sources against the same generated controllers; an unfamiliar
    script, marker or stale payload keeps full CSS. JSON script data is inert.
    """
    from html.parser import HTMLParser

    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.scripts = []
            self.current = None

        def handle_starttag(self, tag, attrs):
            if tag == 'script':
                self.current = (dict(attrs), [])

        def handle_data(self, data):
            if self.current is not None:
                self.current[1].append(data)

        def handle_endtag(self, tag):
            if tag == 'script' and self.current is not None:
                self.scripts.append(self.current)
                self.current = None

    parser = Scripts()
    parser.feed(page.read_text())
    if parser.current is not None:
        return None
    allowed_controllers = set(SCOPED_STYLE_CONTROLLERS)
    engineering = page.relative_to(output).as_posix() in ENGINEERING_INLINE_PAGES
    if engineering:
        allowed_controllers.add('engineering-automation.js')
    for attrs, parts in parser.scripts:
        body = ''.join(parts)
        if 'src' in attrs:
            url = urlsplit(attrs['src'])
            if (url.scheme or url.netloc or url.path not in
                    {'/' + name for name in allowed_controllers}):
                return None
            if not _reviewed_style_controller(output, url.path.lstrip('/')):
                return None
            continue
        if attrs.get('type', '').lower() in {'application/json', 'application/ld+json'}:
            continue
        if 'data-consent-inline' in attrs:
            name = 'analytics-consent.js'
            expected = (output / name).read_text() if (output / name).is_file() else None
        else:
            name = attrs.get('data-inline-page-critical')
            inline_names = {'agent-tools.js', 'portfolio.js'}
            if engineering:
                inline_names.add('engineering-automation.js')
            if name not in inline_names or not (output / name).is_file():
                return None
            source = (output / name).read_text()
            if attrs.get('data-source-sha256') != hashlib.sha256(source.encode()).hexdigest():
                return None
            expected = ("document.addEventListener('DOMContentLoaded', () => {\n"
                        + source + '\n}, { once: true });')
        if not _reviewed_style_controller(output, name):
            return None
        if expected is None or body.strip() != expected.strip():
            return None
    return catalog_classes(output, [page])


def generated_root(output):
    output = Path(output)
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only a generated Pages artifact may be prepared')
    return output


def inline_consent(output):
    """Run consent setup after page content has been parsed, before deferred scripts."""
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
        if not measurement or not BODY.search(html) or not BODY_END.search(html):
            raise ValueError(f'Missing consent configuration or body: {page}')
        script = '<script data-consent-inline data-measurement-id="' + escape(measurement[1], quote=True) + '">' + controller + '</script>'
        html = html[:match.start()] + html[match.end():]
        html = BODY_END.sub(lambda body: script + body[0], html, count=1)
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
    if relative in {'engineering-automation/index.html', 'en/engineering-automation/index.html'}:
        return 'engineering'
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
    Explicit case opt-ins additionally use their own HTML and loaded/inline
    controller inventory. Unknown controllers retain the complete stylesheet.
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
    scoped_classes = {page: _scoped_style_classes(output, page) for page in pages
                      if families[page] in {'case', 'engineering'}
                      and page.relative_to(output).as_posix() in PAGE_STYLE_SCOPES}
    pattern = re.compile(r'<link\b(?=[^>]*\brel=["\']stylesheet["\'])[^>]*>', re.I)
    count = 0
    cache = {}
    for page in pages:
        family = families[page]
        scope = page if page in scoped_classes else family
        classes = scoped_classes[page] if page in scoped_classes else family_classes[family]
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
            deferred = re.search(r'\bdata-home-deferred-style=["\']([^"\']*)["\']', match[0], re.I)
            if deferred:
                # These links intentionally remain links inside the inert
                # controller template and its no-JS fallback. Converting the
                # template link to a style would leave enhancement unstyled.
                if family != 'home' or deferred[1] != 'automation' or parsed.path != '/automation.css':
                    raise ValueError('Unsupported deferred homepage stylesheet: ' + href[1])
                return match[0]
            if re.search(r'\bdata-engineering-deferred-style\b', match[0], re.I):
                if family != 'engineering' or parsed.path != '/engineering-story.css':
                    raise ValueError('Unsupported deferred engineering stylesheet: ' + href[1])
                # Keep the native stylesheet fallback when JavaScript is off.
                return match[0]
            key = (scope, target)
            if key not in cache:
                css = prune_catalog_css(target.read_text(), classes,
                                        prune_functional_ancestors=page in scoped_classes)
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


def _critical_payload(output, names, marker):
    """Exact shared sources, without defer/currentScript timing assumptions."""
    sources, payload = {}, []
    for name in names:
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
        payload.append('<script ' + marker + '="' + name
                       + '" data-source-sha256="' + digest + '">\n'
                       + "document.addEventListener('DOMContentLoaded', () => {\n"
                       + source + '\n}, { once: true });\n</script>\n')
    return sources, ''.join(payload)


def _home_critical_payload(output):
    return _critical_payload(output, HOME_CRITICAL_SCRIPTS, HOME_INLINE_MARKER)


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


def _plan_home_critical_scripts(output):
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
    return plans


def inline_home_critical_scripts(output):
    """Keep the existing home-only API and exact home output contract."""
    plans = _plan_home_critical_scripts(output)
    for page, updated in plans:
        page.write_bytes(updated.encode('utf-8'))
    return len(plans)


PAGE_INLINE_MARKER = 'data-inline-page-critical'
PAGE_CRITICAL_PROFILES = {
    'case': ('agent-tools.js', 'portfolio.js'),
    'catalog': ('agent-tools.js',),
    'not-found': ('agent-tools.js',),
    'engineering': ('engineering-automation.js', 'agent-tools.js'),
}


def _page_script_attributes_reviewed(profile, name, attributes):
    """The service controller alone has the reviewed low-priority hint."""
    attrs = dict(attributes)
    expected = {'src', 'defer'}
    if profile == 'engineering' and name == 'engineering-automation.js':
        expected.add('fetchpriority')
        if attrs.get('fetchpriority') != 'low':
            return False
    return set(attrs) == expected and len(attributes) == len(expected)


def _page_script_tags(html):
    """Retain script ancestry: regex offsets cannot prove an active head."""
    from html.parser import HTMLParser

    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.scripts = [], []

        def handle_starttag(self, tag, attrs):
            if tag == 'script':
                self.scripts.append((attrs, tuple(name for name, _ in self.stack),
                                     any(inert for _, inert in self.stack)))
            if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                           'link', 'meta', 'param', 'source', 'track', 'wbr'}:
                self.stack.append((tag, 'inert' in dict(attrs)))

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    break

    parser = Scripts()
    parser.feed(html)
    return parser.scripts


def _validate_page_external_scripts(output, html, profile, before_inline=False):
    """Review every external dependency, including retained defer controllers.

    Moving code to DOM-ready would reverse its execution order relative to any
    unreviewed external defer/module/classic script. Only these explicit source
    inventories are safe, in their original order and directly in active head.
    """
    critical = PAGE_CRITICAL_PROFILES[profile] if before_inline else ()
    if profile == 'case':
        allowed = (critical, critical + ('url-compat.js',))
    elif profile == 'not-found':
        allowed = (('not-found.js',) + critical,)
    else:
        allowed = (critical,)
    ordered = []
    for attributes, ancestry, inert in _page_script_tags(html):
        attrs = dict(attributes)
        if 'src' not in attrs:
            continue
        reference = urlsplit(unescape(attrs['src']))
        name = reference.path.lstrip('/')
        if (name not in {name for inventory in allowed for name in inventory}
                or reference.scheme or reference.netloc or reference.path != '/' + name
                or not _page_script_attributes_reviewed(profile, name, attributes)
                or ancestry != ('html', 'head') or inert):
            raise ValueError('Unsupported page external dependency/context: ' + attrs['src'])
        source = output / name
        if not source.is_file():
            raise ValueError('Missing retained page controller: ' + name)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        if reference.query != 'v=' + digest or reference.fragment:
            raise ValueError('Page external controller URL does not match its source hash: ' + name)
        ordered.append(name)
    if tuple(ordered) not in allowed:
        raise ValueError('Page external dependency coverage/order differs')


def page_critical_profile(output, page, html):
    """Recognize only explicit route/body combinations; aliases stay external."""
    from html.parser import HTMLParser

    class Body(HTMLParser):
        classes = set()
        redirect = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'body':
                self.classes = set(attrs.get('class', '').split())
            if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh':
                self.redirect = True

    parser = Body()
    parser.feed(html)
    if parser.redirect:
        return None
    relative = Path(page).relative_to(output).as_posix()
    if relative in ENGINEERING_INLINE_PAGES and parser.classes == {'engineering-page'}:
        return 'engineering'
    if relative == '404.html' and 'not-found-page' in parser.classes:
        return 'not-found'
    if ('catalog-page' in parser.classes and 'project-page' in parser.classes
            and re.fullmatch(r'(?:en/)?portfolio/(?:\d{4}/)?index\.html', relative)):
        return 'catalog'
    if ('project-page' in parser.classes and 'catalog-page' not in parser.classes
            and re.fullmatch(r'(?:en/)?portfolio/\d{4}/[^/]+/index\.html', relative)):
        return 'case'
    return None


def validate_page_inline_scripts(output, page, html):
    """Validate exact sources, hash, order, once wrapper and complete-DOM timing."""
    output = generated_root(output)
    profile = page_critical_profile(output, page, html)
    if profile is None:
        raise ValueError('Unknown page family cannot inline controllers: ' + str(page))
    names = PAGE_CRITICAL_PROFILES[profile]
    _, payload = _critical_payload(output, names, PAGE_INLINE_MARKER)
    if 'data-zabava-agent-tools' in html:
        from zabava_first_paint import ROUTE, transform_critical_payload
        if Path(page).relative_to(output).as_posix() != ROUTE or profile != 'case':
            raise ValueError('Zabava tools delivery is restricted to its reviewed route')
        payload = transform_critical_payload(output, payload)
    actual = re.findall(r'<script\b[^>]*\b' + PAGE_INLINE_MARKER + r'=["\']([^"\']+)["\']', html, re.I)
    if tuple(actual) != names or HOME_INLINE_MARKER in html:
        raise ValueError('Page inline controller coverage/order differs')
    closing = list(re.finditer(r'</body\s*>', html, re.I))
    expected = payload
    if len(closing) == 1 and not html[:closing[0].start()].endswith(expected):
        from case_minification import MINIFIED_CASES, minify_fragment
        if Path(page).relative_to(output).as_posix() in MINIFIED_CASES | ENGINEERING_INLINE_PAGES:
            # The source hashes and once/DOM-ready wrapper remain part of the
            # exact canonical transform; never accept a caller-supplied digest.
            expected = minify_fragment(payload)
    if len(closing) != 1 or not html[:closing[0].start()].endswith(expected):
        raise ValueError('Page inline source/hash/DOM-ready wrapper/body position differs')
    for attrs, ancestry, inert in _page_script_tags(html):
        if PAGE_INLINE_MARKER in dict(attrs) and (ancestry != ('html', 'body') or inert):
            raise ValueError('Page inline controller is not in active body context')
    _validate_page_external_scripts(output, html, profile)


def _plan_page_critical_scripts(output):
    from html.parser import HTMLParser

    class ScriptAttributes(HTMLParser):
        def handle_starttag(self, tag, attrs):
            self.attributes = attrs

    output = generated_root(output)
    plans, cache = [], {}
    for page in sorted(output.rglob('*.html')):
        html = page.read_bytes().decode('utf-8')
        profile = page_critical_profile(output, page, html)
        if profile is None:
            if PAGE_INLINE_MARKER in html:
                raise ValueError('Unknown page family has inline controllers: ' + str(page))
            continue
        if PAGE_INLINE_MARKER in html or HOME_INLINE_MARKER in html:
            raise ValueError('Page controllers already inlined or use the wrong family')
        _validate_page_external_scripts(output, html, profile, before_inline=True)
        names = PAGE_CRITICAL_PROFILES[profile]
        if profile not in cache:
            cache[profile] = _critical_payload(output, names, PAGE_INLINE_MARKER)
        sources, payload = cache[profile]
        body = re.search(r'<body\b', html, re.I)
        ordered = []

        def remove(match):
            parser = ScriptAttributes()
            parser.feed(match[0])
            attrs = dict(parser.attributes)
            reference = urlsplit(unescape(attrs.get('src', '')))
            name = reference.path.lstrip('/')
            if name not in names:
                return match[0]
            if (reference.scheme or reference.netloc or reference.path != '/' + name
                    or not _page_script_attributes_reviewed(profile, name, parser.attributes)
                    or body is None or match.start() >= body.start()):
                raise ValueError('Unsupported page script attributes/location: ' + name)
            if reference.query != 'v=' + sources[name][1][:12] or reference.fragment:
                raise ValueError('Page controller URL does not match its source hash: ' + name)
            ordered.append(name)
            return ''

        updated = HOME_EXTERNAL_SCRIPT.sub(remove, html)
        if tuple(ordered) != names:
            raise ValueError('Expected each deferred page controller once in source order: ' + str(page))
        closing = list(re.finditer(r'</body\s*>', updated, re.I))
        if len(closing) != 1:
            raise ValueError('Expected one page body end: ' + str(page))
        index = closing[0].start()
        updated = updated[:index] + payload + updated[index:]
        validate_page_inline_scripts(output, page, updated)
        plans.append((page, updated))
    return plans


def inline_page_critical_scripts(output):
    """Inline approved profiles; unknown pages and external assets remain."""
    plans = _plan_page_critical_scripts(output)
    for page, updated in plans:
        page.write_bytes(updated.encode('utf-8'))
    return len(plans)


def inline_critical_scripts(output):
    """Validate all home and page plans before changing any generated HTML."""
    homes = _plan_home_critical_scripts(output)
    pages = _plan_page_critical_scripts(output)
    for page, updated in homes + pages:
        page.write_bytes(updated.encode('utf-8'))
    return {'home': len(homes), 'page': len(pages)}
