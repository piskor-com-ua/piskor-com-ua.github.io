"""Prepare responsive public images without modifying any source media."""
from functools import lru_cache
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import math
import re
import shutil
import tempfile
from PIL import Image, ImageOps, __version__ as PILLOW_VERSION
import tinycss2

IMG = re.compile(r'<img\b[^>]*>', re.I)
VIEWPORT = re.compile(r'<meta\b(?=[^>]*\bname=["\']viewport["\'])[^>]*>', re.I)
IMAGE_PRELOAD = re.compile(r'<link\b(?=[^>]*\brel=["\']preload["\'])(?=[^>]*\bas=["\']image["\'])[^>]*>', re.I)
CARD_SIZES = '(max-width: 700px) calc(100vw - 48px), (min-width: 1956px) calc((100vw - 204px) / 2), calc((91vw - 28px) / 2)'
COVER_SIZES = '(max-width: 700px) calc(100vw - 48px), (min-width: 1956px) calc(100vw - 176px), 91vw'
CATALOG_FRAME_RATIO = 1.42
VOID_ELEMENTS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class CaseImageContexts(HTMLParser):
    """Locate actual case images; never rewrite image-like strings in scripts."""
    def __init__(self, html):
        super().__init__()
        self.offsets = [0]
        self.offsets.extend(match.end() for match in re.finditer('\n', html))
        self.stack = []
        self.elements = []
        self.child_counts = [0]
        self.images = set()
        self.contexts = {}
        self.paths = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get('class', '').split())
        self.child_counts[-1] += 1
        element = {'tag': tag, 'attrs': attrs, 'index': self.child_counts[-1]}
        if tag == 'img':
            line, column = self.getpos()
            offset = self.offsets[line - 1] + column
            self.images.add(offset)
            self.paths[offset] = (*self.elements, element)
            case_page = any('project-page' in names and 'catalog-page' not in names
                            for _, names in self.stack)
            if any('hero-picture' in names for _, names in self.stack):
                self.contexts[offset] = 'home-hero'
            elif case_page:
                context = ('cover' if any('project-cover' in names for _, names in self.stack)
                           else 'gallery' if any('gallery-grid' in names for _, names in self.stack)
                           else None)
                if context:
                    if any(name == 'picture' for name, _ in self.stack):
                        raise ValueError('Case media already has a picture source; update its delivery explicitly')
                    self.contexts[offset] = context
        if tag not in VOID_ELEMENTS:
            self.stack.append((tag, classes))
            self.elements.append(element)
            self.child_counts.append(0)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                del self.elements[index:]
                del self.child_counts[index + 1:]
                break


class UnsupportedImageStyle(ValueError):
    pass


def split_css_list(value, separator=','):
    """Split only outside functional selectors, attributes and quoted strings."""
    result, start, depth, quote = [], 0, 0, None
    for index, character in enumerate(value):
        if quote:
            if character == quote and (index == 0 or value[index - 1] != '\\'):
                quote = None
        elif character in '\"\'':
            quote = character
        elif character in '([':
            depth += 1
        elif character in ')]':
            depth -= 1
        elif depth == 0 and character == separator:
            result.append(value[start:index].strip())
            start = index + 1
    result.append(value[start:].strip())
    return result


def selector_steps(selector):
    """The deliberately bounded subset used by the shared image CSS."""
    result, start, depth, quote, relation = [], 0, 0, None, None
    for index, character in enumerate(selector + ' '):
        if quote:
            if character == quote and (index == 0 or selector[index - 1] != '\\'):
                quote = None
            continue
        if character in '\"\'':
            quote = character
        elif character in '([':
            depth += 1
        elif character in ')]':
            depth -= 1
        elif depth == 0 and (character.isspace() or character in '>+~'):
            if character in '+~':
                raise UnsupportedImageStyle('Sibling image selector')
            compound = selector[start:index].strip()
            if compound:
                result.append((compound, relation))
                relation = ' '
            if character == '>':
                relation = '>'
            start = index + 1
    return result


def compound_match(compound, path):
    node = path[-1]
    attrs = node['attrs']
    matched, specificity, position = True, [0, 0, 0], 0
    tag = re.match(r'^(?:[a-zA-Z][\w-]*|\*)', compound)
    if tag:
        matched = tag[0] == '*' or node['tag'] == tag[0]
        specificity[2] += tag[0] != '*'
        position = tag.end()
    while position < len(compound):
        token = re.match(r'([.#])([\w-]+)', compound[position:])
        if token:
            kind, name = token.groups()
            matched &= attrs.get('id') == name if kind == '#' else name in attrs.get('class', '').split()
            specificity[0 if kind == '#' else 1] += 1
            position += token.end()
            continue
        attribute_match = re.match(r'\[([\w-]+)(?:([*^$~|]?=)[\"\']([^\"\']*)[\"\'])?\]', compound[position:])
        if attribute_match:
            name, operator, value = attribute_match.groups()
            actual = attrs.get(name)
            tests = {None: lambda: actual is not None, '=': lambda: actual == value,
                     '*=': lambda: actual is not None and value in actual,
                     '^=': lambda: actual is not None and actual.startswith(value),
                     '$=': lambda: actual is not None and actual.endswith(value),
                     '~=': lambda: actual is not None and value in actual.split(),
                     '|=': lambda: actual == value or actual is not None and actual.startswith(value + '-')}
            matched &= tests[operator]()
            specificity[1] += 1
            position += attribute_match.end()
            continue
        pseudo = re.match(r':([\w-]+)', compound[position:])
        if not pseudo:
            raise UnsupportedImageStyle('Unknown image selector')
        name = pseudo[1]
        position += pseudo.end()
        argument = None
        if position < len(compound) and compound[position] == '(':
            start, depth = position + 1, 1
            position += 1
            while position < len(compound) and depth:
                depth += (compound[position] == '(') - (compound[position] == ')')
                position += 1
            if depth:
                raise UnsupportedImageStyle('Unclosed image selector')
            argument = compound[start:position - 1]
        if name in {'is', 'not', 'where'} and argument is not None:
            choices = [selector_match(item, path) for item in split_css_list(argument)]
            any_match = any(choice[0] for choice in choices)
            matched &= not any_match if name == 'not' else any_match
            if name != 'where':
                extra = max(choice[1] for choice in choices)
                specificity = [a + b for a, b in zip(specificity, extra)]
        elif name == 'nth-child' and argument is not None:
            if argument.isdigit():
                matched &= node['index'] == int(argument)
            elif argument in {'odd', 'even'}:
                matched &= node['index'] % 2 == (1 if argument == 'odd' else 0)
            else:
                raise UnsupportedImageStyle('Unsupported nth-child image selector')
            specificity[1] += 1
        elif name == 'first-child' and argument is None:
            matched &= node['index'] == 1
            specificity[1] += 1
        elif name == 'root' and argument is None:
            matched &= node['tag'] == 'html'
            specificity[1] += 1
        else:
            raise UnsupportedImageStyle('Unsupported image pseudo-class')
    return matched, tuple(specificity)


def selector_match(selector, path):
    if re.search(r':{1,2}(?:before|after|backdrop|marker|first-letter|first-line)\b', selector):
        return False, (0, 0, 0)  # A pseudo-element is not the actual image box.
    steps = selector_steps(selector)
    # Compute specificity independently of which ancestor matches.
    specificity = tuple(sum(values) for values in zip(*(compound_match(compound, path)[1] for compound, _ in steps)))
    def matches(index, path_index):
        if path_index < 0 or not compound_match(steps[index][0], path[:path_index + 1])[0]:
            return False
        if index == 0:
            return True
        candidates = [path_index - 1] if steps[index][1] == '>' else range(path_index - 1, -1, -1)
        return any(matches(index - 1, candidate) for candidate in candidates)
    return matches(len(steps) - 1, len(path) - 1), specificity


IMAGE_PROPERTIES = {'height', 'min-height', 'max-height', 'aspect-ratio', 'object-fit'}
STRUCTURAL_IMAGE_SELECTOR = re.compile(r'>|:(?:first-child|last-child|nth-child|only-child|nth-last-child|first-of-type|last-of-type|nth-of-type|only-of-type|nth-last-of-type)\b')


@lru_cache(maxsize=None)
def image_style_rules(css):
    rules = []
    def visit(items, conditional=False):
        for rule in items:
            if rule.type == 'at-rule' and rule.lower_at_keyword in {'import', 'scope'}:
                raise ValueError('Case picture delivery requires explicit resolution of @' + rule.lower_at_keyword + ' CSS')
            if rule.type == 'at-rule' and rule.content is not None:
                # Responsive image-layout changes need an explicit sizes branch.
                # Unknown conditional layout must not become false precision.
                if rule.lower_at_keyword in {'media', 'supports', 'container', 'layer'}:
                    visit(tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True), True)
            elif rule.type == 'qualified-rule':
                if any(token.type == '{} block' for token in rule.content):
                    raise ValueError('Case picture delivery requires explicit resolution of nested CSS selectors')
                declarations = [(item.lower_name, tinycss2.serialize(item.value).strip(), item.important)
                                for item in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
                                if item.type == 'declaration' and item.lower_name in IMAGE_PROPERTIES]
                for selector in split_css_list(tinycss2.serialize(rule.prelude)):
                    # Keep structural selectors even when their declarations
                    # are not crop properties: adding <picture> must not stop
                    # an existing direct-child image rule from applying.
                    if declarations or STRUCTURAL_IMAGE_SELECTOR.search(selector):
                        rules.append((selector, declarations, conditional))
    visit(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True))
    return rules


def case_image_style(rules, path):
    picture_path = (*path[:-1], {'tag': 'picture', 'attrs': {}, 'index': path[-1]['index']},
                    {**path[-1], 'index': 2})  # <source> precedes the original <img>.
    # Complete wrapper safety before any unsupported crop rule can select the
    # native-only fallback. That fallback still inserts a <picture> element.
    for selector, _, _ in rules:
        if STRUCTURAL_IMAGE_SELECTOR.search(selector):
            try:
                before = selector_match(selector, path)[0]
                after = selector_match(selector, picture_path)[0]
            except UnsupportedImageStyle:
                # A known non-image target cannot style the wrapped <img>.
                # For potential image targets, an unknown structural selector
                # needs an explicit resolution rather than a broken fallback.
                try:
                    target = selector_steps(selector)[-1][0]
                except UnsupportedImageStyle:
                    target = ''  # An unknown combinator cannot prove its target.
                prefix = re.match(r'^(?:[a-zA-Z][\w-]*|\*)?(?:[.#][\w-]+)*', target)[0]
                if not prefix or compound_match(prefix, path)[0]:
                    raise ValueError('Case picture wrapper requires resolution of structural CSS selector: ' + selector)
            else:
                if before != after:
                    raise ValueError('Case picture wrapper changes a structural CSS selector: ' + selector)
    winners = {}
    for order, (selector, declarations, conditional) in enumerate(rules):
        if not declarations:
            continue
        matched, specificity = selector_match(selector, path)
        if not matched:
            continue
        if conditional:
            raise UnsupportedImageStyle('Conditional image layout needs an explicit branch')
        for name, value, important in declarations:
            priority = (important, 0, specificity, order)
            if name not in winners or priority >= winners[name][0]:
                winners[name] = (priority, value)
    for item in tinycss2.parse_declaration_list(path[-1]['attrs'].get('style', ''), skip_comments=True, skip_whitespace=True):
        if item.type == 'declaration' and item.lower_name in IMAGE_PROPERTIES:
            priority = (item.important, 1, (0, 0, 0), len(rules))
            if item.lower_name not in winners or priority >= winners[item.lower_name][0]:
                winners[item.lower_name] = (priority, tinycss2.serialize(item.value).strip())
    return {name: value for name, (_, value) in winners.items()}


def page_image_rules(output, html):
    output = Path(output).resolve()
    rules = []
    # Preserve the original stylesheet order, including any inline additions.
    for match in re.finditer(r'<link\b[^>]*>|<style\b[^>]*>(.*?)</style\s*>', html, re.I | re.S):
        if match[1] is not None:
            rules.extend(image_style_rules(match[1]))
            continue
        attrs = Tag(match[0]).attrs
        if attrs.get('rel') != 'stylesheet':
            continue
        url = attrs.get('href', '').split('?')[0].split('#')[0]
        if not url.startswith('/') or url.startswith('//'):
            raise ValueError('Case picture wrapper requires a resolved local stylesheet: ' + url)
        path = (output / url.lstrip('/')).resolve()
        if not path.is_relative_to(output) or not path.is_file():
            raise ValueError('Case picture wrapper requires an available local stylesheet: ' + url)
        extra = image_style_rules(path.read_text())
        if attrs.get('media', 'all') not in {'all', 'screen'}:
            extra = [(selector, declarations, True) for selector, declarations, _ in extra]
        rules.extend(extra)
    return rules


def crop_aware_sizes(kind, source_ratio, style):
    """Describe source-pixel width, including unchanged object-fit cropping."""
    if any(style.get(name, 'none') not in {'none', '0', '0px'} for name in ('min-height', 'max-height')):
        raise UnsupportedImageStyle('Constrained image height')
    height = re.sub(r'\s+', '', style.get('height', 'auto'))
    ratio = re.sub(r'\s+', '', style.get('aspect-ratio', 'auto'))
    factor, fitted_height = 1, None
    if style.get('object-fit', 'fill') == 'cover':
        if height == 'auto':
            if ratio != 'auto':
                match = re.fullmatch(r'(\d+(?:\.\d+)?)(?:/(\d+(?:\.\d+)?))?', ratio)
                if not match:
                    raise UnsupportedImageStyle('Unknown image aspect ratio')
                box_ratio = float(match[1]) / float(match[2] or 1)
                if box_ratio <= 0:
                    raise UnsupportedImageStyle('Invalid image aspect ratio')
                factor = max(1, source_ratio / box_ratio)
        else:
            match = re.fullmatch(r'(min|clamp)\(([^()]+)\)', height)
            if not match:
                raise UnsupportedImageStyle('Unknown fixed image height')
            terms = []
            for term in match[2].split(','):
                length = re.fullmatch(r'(\d+(?:\.\d+)?)(px|vw)', term)
                if not length:
                    raise UnsupportedImageStyle('Unknown image height unit')
                terms.append(f'{float(length[1]) * source_ratio:.8g}{length[2]}')
            fitted_height = match[1] + '(' + ', '.join(terms) + ')'
    mobile = f'calc({100 * factor:.8g}vw - {48 * factor:.8g}px)'
    if kind == 'cover':
        large = f'calc({100 * factor:.8g}vw - {176 * factor:.8g}px)'
        desktop = f'{91 * factor:.8g}vw'
    else:
        large = f'calc(({100 * factor:.8g}vw - {204 * factor:.8g}px) / 2)'
        desktop = f'calc(({91 * factor:.8g}vw - {28 * factor:.8g}px) / 2)'
    if fitted_height:
        mobile, large, desktop = [f'max({slot}, {fitted_height})' for slot in (mobile, large, desktop)]
    return f'(max-width: 700px) {mobile}, (min-width: 1956px) {large}, {desktop}'


def catalog_image_sizes(source_ratio):
    """Match the original full-width 1.42 cover frame in both layouts."""
    if not math.isfinite(source_ratio) or source_ratio <= 0:
        raise ValueError('Catalog cover requires a positive native aspect ratio')
    return crop_aware_sizes('gallery', source_ratio, {
        'height': 'auto', 'aspect-ratio': str(CATALOG_FRAME_RATIO), 'object-fit': 'cover',
    })


def home_hero_crops(output, html, image_path, width, height):
    """Prove the existing hero geometry before removing never-visible pixels.

    This is an explicit contract for the shared hero, not another CSS cascade
    implementation. A new matching geometry rule requires revisiting the proof.
    """
    expected = {
        ('', '*'): {'box-sizing': 'border-box'},
        ('', 'body'): {'margin': '0'},
        ('', 'img'): {'max-width': '100%', 'display': 'block'},
        ('', '.hero'): {'height': 'max(760px,100svh)', 'max-height': '1200px', 'position': 'relative', 'overflow': 'hidden', 'display': 'flex'},
        ('', '.hero-picture'): {'position': 'absolute', 'inset': '0'},
        ('', '.hero-picture img'): {'height': '100%', 'width': '100%', 'object-fit': 'cover', 'object-position': '58%56%'},
        ('media:(min-width:1800px)', '.hero'): {'max-height': 'none'},
        ('media:(max-width:700px)', '.hero'): {'height': '100svh', 'min-height': '740px', 'max-height': '1000px'},
        ('media:(max-width:700px)', '.hero-picture img'): {'object-position': '61%50%'},
        ('media:(prefers-reduced-motion:reduce)', '*'): {'transition': 'none!important', 'animation': 'none!important'},
    }
    found = {}
    geometry = {'height', 'min-height', 'max-height', 'width', 'min-width', 'max-width', 'object-fit', 'object-position',
                'aspect-ratio', 'transform', 'translate', 'scale', 'rotate', 'inset', 'left', 'right', 'top', 'bottom',
                'position', 'box-sizing', 'display', 'overflow', 'all', 'zoom', 'contain', 'content-visibility', 'flex',
                'block-size', 'inline-size', 'min-block-size', 'max-block-size', 'min-inline-size', 'max-inline-size', 'writing-mode'}
    # The generated picture is part of the final geometry contract as well as
    # the original image path. Its new selectors deliberately style this wrapper.
    wrapped_path = (*image_path[:-1], {'tag': 'picture', 'attrs': {}, 'index': image_path[-1]['index']},
                    {**image_path[-1], 'index': 5})  # Three mobile sources and the full desktop source.
    paths = [path[:index] for path in (image_path, wrapped_path) for index in range(1, len(path) + 1)]
    # These fixed components live outside the hero image ancestry. An absent
    # arbitrary state class (for example .expanded) is never such a proof.
    nonhero_classes = {'logo', 'scene-images', 'material-chip', 'approach-image', 'approach-steps',
                       'device-effects', 'system-map', 'scene-preview', 'system-summary',
                       'portfolio-card-image', 'portfolio-card', 'project-cover', 'gallery-grid',
                       'project-lightbox', 'project-page', 'catalog-page', 'case-chapter-heading',
                       'case-story-copy', 'scenario-note', 'skip', 'language', 'service-row', 'contact-top',
                       'header', 'mobile-menu'}
    path_classes = {name for path in paths for name in path[-1]['attrs'].get('class', '').split()}
    def nonhero_scope(selector):
        try:
            compounds = [compound for compound, _ in selector_steps(selector)]
        except UnsupportedImageStyle:
            return False  # Sibling relationships cannot prove ancestry.
        for compound in compounds:
            tokens = tinycss2.parse_component_value_list(compound)
            for first, second in zip(tokens, tokens[1:]):
                # Only positive, top-level classes count; :not(.scope) does not.
                if (first.type == 'literal' and first.value == '.' and second.type == 'ident'
                        and second.value in nonhero_classes - path_classes):
                    return True
        return False
    def visit(items, condition=''):
        for rule in items:
            if rule.type == 'error':
                raise ValueError('Home hero crop requires valid CSS')
            if rule.type == 'at-rule':
                if rule.lower_at_keyword in {'import', 'scope'}:
                    raise ValueError('Home hero crop requires resolved CSS: @' + rule.lower_at_keyword)
                if rule.content is not None and rule.lower_at_keyword in {'media', 'supports', 'container', 'layer'}:
                    context = rule.lower_at_keyword + ':' + re.sub(r'\s+', '', tinycss2.serialize(rule.prelude))
                    visit(tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True),
                          condition + ('/' if condition else '') + context)
                elif rule.content is not None and rule.lower_at_keyword not in {'font-face', 'keyframes', '-webkit-keyframes', 'font-feature-values', 'property', 'counter-style', 'page'}:
                    raise ValueError('Home hero crop requires review of CSS @' + rule.lower_at_keyword)
                continue
            if rule.type != 'qualified-rule':
                continue
            if any(token.type == '{} block' for token in rule.content):
                raise ValueError('Home hero crop requires explicit resolution of nested CSS')
            declarations = {}
            for item in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
                if item.type == 'declaration' and (item.lower_name in geometry or item.lower_name.startswith(('margin', 'padding', 'border', 'inset-', 'flex-', 'animation', 'transition'))):
                    value = re.sub(r'\s+', '', tinycss2.serialize(item.value))
                    declarations[item.lower_name] = value + ('!important' if item.important else '')
            if not declarations:
                continue
            for selector in split_css_list(tinycss2.serialize(rule.prelude)):
                try:
                    applies = any(selector_match(selector, path)[0] for path in paths)
                except UnsupportedImageStyle:
                    if nonhero_scope(selector):
                        continue
                    try:
                        target = selector_steps(selector)[-1][0]
                    except UnsupportedImageStyle:
                        target = ''
                    tag = re.match(r'^[a-zA-Z][\w-]*', target)
                    if tag and all(path[-1]['tag'] != tag[0].lower() for path in paths):
                        continue
                    raise ValueError('Home hero crop cannot prove CSS selector: ' + selector)
                if applies:
                    key = (condition, selector)
                    if key in found and set(found[key]) & set(declarations):
                        raise ValueError('Home hero crop requires review of repeated geometry selector: ' + selector)
                    found.setdefault(key, {}).update(declarations)
                elif not re.search(r':{1,2}(?:before|after)\b', selector):
                    # Existing dialog/menu scroll lock changes no dimensions
                    # of the explicit mobile picture frame. Do not generalize
                    # this exception to other body states or declarations.
                    if condition == '' and selector == 'body.locked' and declarations == {'overflow': 'hidden'}:
                        continue
                    if nonhero_scope(selector):
                        continue
                    # A descendant such as .hero .text-link cannot change an
                    # ancestor/image box. Still reject unrendered hero states
                    # on a known target, regardless of conditional class order.
                    compounds = [compound for compound, _ in selector_steps(selector)]
                    def known_compound(compound):
                        tag = re.match(r'^(?:[a-zA-Z][\w-]*|\*)', compound)
                        anchors = ([tag[0]] if tag else []) + re.findall(r'[.#][\w-]+', compound)
                        return any(compound_match(anchor, path)[0] for anchor in anchors for path in paths)
                    known_target = known_compound(compounds[-1])
                    conditional_selector = any(re.search(r'[.#\[:]', compound) for compound in compounds)
                    hero_selector = re.search(r'\.hero(?:-picture)?(?![\w-])', selector)
                    if known_target and (conditional_selector or hero_selector):
                        raise ValueError('Home hero crop requires review of conditional geometry selector: ' + selector)
    output = Path(output).resolve()
    for match in re.finditer(r'<link\b[^>]*>|<style\b[^>]*>(.*?)</style\s*>', html, re.I | re.S):
        css = match[1]
        if css is None:
            attrs = Tag(match[0]).attrs
            if attrs.get('rel') != 'stylesheet':
                continue
            url = attrs.get('href', '').split('?')[0].split('#')[0]
            target = (output / url.lstrip('/')).resolve()
            if (not url.startswith('/') or url.startswith('//') or not target.is_relative_to(output)
                    or not target.is_file() or attrs.get('media', 'all') not in {'all', 'screen'}):
                raise ValueError('Home hero crop requires resolved unconditional local stylesheets')
            css = target.read_text()
        visit(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True))
    if found != expected:
        raise ValueError('Home hero crop geometry contract changed; review height, width and object-position before cropping')
    if any(node['attrs'].get('style') for node in image_path):
        raise ValueError('Home hero crop requires review of inline ancestor/image styles')
    if (width, height) != (1536, 1024):
        raise ValueError('Home hero crop requires review of changed native image dimensions')
    # Preserve every visible coordinate of the original tall mobile hero.
    # Keeping all source rows means only unseen horizontal pixels are removed:
    # left + .61*(cropWidth-visibleWidth) == .61*(1536-visibleWidth).
    crops = []
    for maximum in (450, 480, 700):
        minimum = math.ceil(height * maximum / 740)
        removed = ((width - minimum) // 100) * 100
        crop_width = width - removed
        left = removed * 61 // 100
        crops.append((maximum, (left, 0, left + crop_width, height)))
    return crops


class Tag(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.attrs = {}
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.attrs = dict(attrs)


def attribute(markup, name, value):
    pattern = re.compile(r'(?<![\w-])' + re.escape(name) + r'\s*=\s*(["\']).*?\1', re.S)
    replacement = name + '="' + escape(str(value), quote=True) + '"'
    if pattern.search(markup):
        return pattern.sub(lambda _: replacement, markup)
    return markup[:-1] + ' ' + replacement + '>'


def prepare_public_assets(output):
    output = Path(output).resolve()
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only a generated Pages artifact may be prepared')

    @lru_cache(maxsize=None)
    def dimensions(reference):
        clean = reference.split('?')[0].split('#')[0]
        target = output / clean.lstrip('/')
        if not target.resolve().is_relative_to(output) or target.is_symlink():
            raise ValueError('Unsafe image: ' + reference)
        with Image.open(target) as image:
            return ImageOps.exif_transpose(image).size

    @lru_cache(maxsize=None)
    def lossless_logo(reference):
        target = output / reference.lstrip('/')
        folder = output / 'assets' / 'responsive'
        folder.mkdir(parents=True, exist_ok=True)
        with Image.open(target) as original:
            # Resampling this flat transparent artwork creates more colours and
            # larger files. The full-resolution lossless encoding is smaller.
            path = folder / 'piskor-logo.webp'
            original.save(path, 'WEBP', lossless=True, method=6, exact=True)
        return '/' + path.relative_to(output).as_posix()

    @lru_cache(maxsize=None)
    def card_variants(reference):
        target = output / reference.lstrip('/')
        width, height = dimensions(reference)
        # The path stays stable; the resource fingerprint changes with its bytes.
        stem = re.sub(r'-\d+$', '', target.stem)
        relative = target.parent.relative_to(output / 'assets')
        folder = output / 'assets' / 'responsive' / relative
        folder.mkdir(parents=True, exist_ok=True)
        variants, mobile_variants = [], []
        with Image.open(target) as opened:
            original = ImageOps.exif_transpose(opened).convert('RGB')
            for size in sorted({min(width, size) for size in (480, 640, 960, 1440)}):
                resized = original.resize((size, round(height * size / width)), Image.Resampling.LANCZOS)
                if size == width:
                    url = reference
                else:
                    path = folder / (stem + '-' + str(size) + '.webp')
                    resized.save(path, 'WEBP', quality=86, method=6)
                    url = '/' + path.relative_to(output).as_posix()
                variants.append((url, size))
                mobile = folder / (stem + '-' + str(size) + '.avif')
                resized.save(mobile, 'AVIF', quality=60, speed=6, max_threads=2)
                mobile_variants.append(('/' + mobile.relative_to(output).as_posix(), size))
        return variants, mobile_variants

    @lru_cache(maxsize=None)
    def avif_variants(reference, namespace='case-media', crop=None):
        """Use the largest existing source, preserving every original/full URL.

        Keep a separate namespace from catalog covers, whose input can be a
        smaller WebP. Cache encoded bytes outside the public artifact so a new
        Jekyll build and the second language do not repeat this expensive work.
        """
        width, height = dimensions(reference)
        target = output / reference.split('?')[0].split('#')[0].lstrip('/')
        cover = namespace in {'case-cover', 'case-cover/catalog'}
        quality = 50 if cover else 45 if namespace == 'home-media' and crop else 60
        recipe = f'responsive-avif-v1:pillow-{PILLOW_VERSION}:quality-{quality}:speed-6:threads-2'
        if crop:
            if not (0 <= crop[0] < crop[2] <= width and 0 <= crop[1] < crop[3] <= height):
                raise ValueError('Invalid source-pixel crop')
            width, height = crop[2] - crop[0], crop[3] - crop[1]
            recipe += ':crop-' + '-'.join(map(str, crop))
        digest = hashlib.sha256(recipe.encode() + b'\0' + target.read_bytes()).hexdigest()
        cache_folder = output.parent / 'output' / 'image-cache' / 'responsive-avif-v1'
        cache_folder.mkdir(parents=True, exist_ok=True)
        folder = output / 'assets' / 'responsive' / namespace / target.parent.relative_to(output / 'assets')
        folder.mkdir(parents=True, exist_ok=True)
        # Strip known rendition suffixes only: photo-01 and photo-02 are
        # distinct images, not alternative resolutions of a single photo.
        stem = re.sub(r'-(?:480|640|960|1080|1440|2000|2200|2970)$', '', target.stem)
        if crop:
            stem += '-crop-' + '-'.join(map(str, crop))
        variants = []
        original = None
        # Retain a full-native candidate for high-DPR phones; never upscale.
        widths = ((width,) if crop else (960, 1280, 1440, width)) if namespace == 'home-media' else (640, 960, 1440, 2200, width)
        if cover:
            widths += (768,)
        for size in sorted({min(width, size) for size in widths}):
            wanted = (size, round(height * size / width))
            cached = cache_folder / (digest + '-' + str(size) + '.avif')
            valid = False
            if cached.is_file():
                try:
                    with Image.open(cached) as image:
                        valid = image.format == 'AVIF' and image.size == wanted
                        image.verify()
                except (OSError, ValueError):
                    valid = False
            if not valid:
                if original is None:
                    with Image.open(target) as opened:
                        original = ImageOps.exif_transpose(opened).convert('RGB')
                        if crop:
                            original = original.crop(crop)
                resized = original.copy() if original.size == wanted else original.resize(wanted, Image.Resampling.LANCZOS)
                with tempfile.NamedTemporaryFile(dir=cache_folder, suffix='.avif', delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                try:
                    resized.save(temporary_path, 'AVIF', quality=quality, speed=6, max_threads=2)
                    temporary_path.replace(cached)
                finally:
                    temporary_path.unlink(missing_ok=True)
            path = folder / (stem + '-' + str(size) + '.avif')
            shutil.copyfile(cached, path)
            variants.append(('/' + path.relative_to(output).as_posix(), size))
        return variants

    count = case_count = hero_count = 0
    case_sources = set()
    for page in output.rglob('*.html'):
        cover_preload = None
        hero_preload_source = None
        page_html = page.read_text()
        image_contexts = CaseImageContexts(page_html)
        case_contexts = image_contexts.contexts
        try:
            case_rules = page_image_rules(output, page_html) if any(kind in {'cover', 'gallery'} for kind in case_contexts.values()) else []
        except UnsupportedImageStyle:
            case_rules = None
        def image_markup(match):
            nonlocal count, case_count, hero_count, cover_preload, hero_preload_source
            markup = match.group(0)
            if match.start() not in image_contexts.images:
                return markup
            attrs = Tag(markup).attrs
            source = attrs.get('src', '')
            if not source.startswith('/assets/'):
                return markup
            width, height = dimensions(source)
            markup = attribute(attribute(markup, 'width', width), 'height', height)
            if source == '/assets/piskor-logo.png':
                return ('<picture><source type="image/webp" srcset="' + escape(lossless_logo(source), quote=True) + '">' + markup + '</picture>')
            if 'portfolio-card-cover' in attrs.get('class', '').split():
                variants, mobile_variants = card_variants(source)
                markup = attribute(markup, 'srcset', ', '.join(url + ' ' + str(w) + 'w' for url, w in variants))
                sizes = catalog_image_sizes(width / height)
                markup = attribute(markup, 'sizes', sizes)
                if cover_preload is None:
                    # Only the first rendered catalog card needs the smaller
                    # cover profile. Later cards retain their published q60 URLs.
                    mobile_variants = avif_variants(source, 'case-cover/catalog')
                mobile_srcset = escape(', '.join(url + ' ' + str(w) + 'w' for url, w in mobile_variants), quote=True)
                if cover_preload is None:
                    # Derive from the rendered first card, including year/locale order.
                    # No href: older browsers must not fetch an unselected fallback.
                    cover_preload = ('<link rel="preload" as="image" type="image/avif" '
                                     'media="(max-width: 700px)" imagesrcset="' + mobile_srcset +
                                     '" imagesizes="' + escape(sizes, quote=True) +
                                     '" fetchpriority="high" data-catalog-cover-preload>')
                markup = ('<picture><source type="image/avif" media="(max-width: 700px)" '
                          'srcset="' + mobile_srcset + '" sizes="' + escape(sizes, quote=True) + '">' + markup + '</picture>')
                count += 1
            elif attrs.get('srcset'):
                entries = []
                for entry in attrs['srcset'].split(','):
                    url, descriptor = entry.strip().split()
                    if descriptor.endswith('w') and url.startswith('/assets/'):
                        descriptor = str(dimensions(url)[0]) + 'w'
                    if (url, descriptor) not in entries:
                        entries.append((url, descriptor))
                if case_contexts.get(match.start()) in {'cover', 'gallery'}:
                    # Several galleries list only 640/full even though their
                    # existing src is a useful middle rendition. Reuse it so
                    # desktop browsers do not jump straight to a 2200px file.
                    entries.append((source, str(width) + 'w'))
                # Remove equal-width alternatives: browsers require unique descriptors.
                unique = {}
                for url, descriptor in entries:
                    unique.setdefault(descriptor, url)
                markup = attribute(markup, 'srcset', ', '.join(url + ' ' + d for d, url in unique.items()))
            context = case_contexts.get(match.start())
            if context:
                references = [source]
                for entry in attrs.get('srcset', '').split(','):
                    parts = entry.strip().split()
                    if len(parts) == 2 and parts[0].startswith('/assets/') and parts[1].endswith('w'):
                        references.append(parts[0])
                largest = max(references, key=lambda url: dimensions(url)[0])
                native_width, native_height = dimensions(largest)
                native_only = False
                if context == 'home-hero':
                    # object-fit:cover scales this landscape source to the tall
                    # hero height. 100vw would pick a blurry undersized image on
                    # a portrait screen. Match the unchanged shared CSS heights.
                    ratio = width / height
                    sizes = (f'(max-width: 700px) max(100vw, clamp({740 * ratio:g}px, {100 * ratio:g}svh, {1000 * ratio:g}px)), '
                             f'(min-width: 1800px) max(100vw, max({760 * ratio:g}px, {100 * ratio:g}svh)), '
                             f'max(100vw, clamp({760 * ratio:g}px, {100 * ratio:g}svh, {1200 * ratio:g}px))')
                    hero_crops = home_hero_crops(output, page_html, image_contexts.paths[match.start()], native_width, native_height)
                else:
                    try:
                        if case_rules is None:
                            raise UnsupportedImageStyle('Unresolved stylesheet')
                        style = case_image_style(case_rules, image_contexts.paths[match.start()])
                        sizes = crop_aware_sizes(context, native_width / native_height, style)
                    except UnsupportedImageStyle:
                        # Preserve the old WebP selection, and never undersample
                        # AVIF when an unfamiliar layout cannot be proven.
                        sizes = attrs.get('sizes', '100vw')
                        native_only = True
                        if attrs.get('srcset'):
                            legacy = {}
                            for entry in attrs['srcset'].split(','):
                                url, descriptor = entry.strip().split()
                                if descriptor.endswith('w') and url.startswith('/assets/'):
                                    descriptor = str(dimensions(url)[0]) + 'w'
                                legacy.setdefault(descriptor, url)
                            markup = attribute(markup, 'srcset', ', '.join(url + ' ' + descriptor
                                                                         for descriptor, url in legacy.items()))
                markup = attribute(markup, 'sizes', sizes)
                namespace = 'home-media' if context == 'home-hero' else 'case-cover' if context == 'cover' else 'case-media'
                variants = avif_variants(largest, namespace)
                if native_only:
                    variants = variants[-1:]
                mobile_srcset = escape(', '.join(url + ' ' + str(w) + 'w'
                                                for url, w in variants), quote=True)
                sources = [(None if context == 'home-hero' else '(max-width: 700px)', mobile_srcset, sizes)]
                if context == 'home-hero':
                    sources = []
                    for maximum, crop in hero_crops:
                        crop_ratio = (crop[2] - crop[0]) / native_height
                        crop_sizes = f'max(100vw, clamp({740 * crop_ratio:g}px, {100 * crop_ratio:g}svh, {1000 * crop_ratio:g}px))'
                        crop_variants = avif_variants(largest, namespace, crop)
                        crop_srcset = escape(', '.join(url + ' ' + str(w) + 'w' for url, w in crop_variants), quote=True)
                        crop_media = {450: '(width <= 450px)', 480: '(450px < width <= 480px)',
                                      700: '(480px < width <= 700px)'}[maximum]
                        sources.append((crop_media, crop_srcset, crop_sizes))
                    sources.append((None, mobile_srcset, sizes))
                markup = ('<picture>' + ''.join('<source type="image/avif"' + (' media="' + query + '"' if query else '')
                                               + ' srcset="' + srcset + '" sizes="' + escape(source_sizes, quote=True) + '">'
                                               for query, srcset, source_sizes in sources) + markup + '</picture>')
                if context in {'cover', 'home-hero'} and cover_preload is None:
                    marker = 'data-home-hero-preload' if context == 'home-hero' else 'data-case-cover-preload'
                    cover_preload = ''.join('<link rel="preload" as="image" type="image/avif" '
                                            + ('media="' + (query or '(700px < width)') + '" ' if context == 'home-hero' or query else '')
                                            + 'imagesrcset="' + srcset + '" imagesizes="' + escape(source_sizes, quote=True)
                                            + '" fetchpriority="high" ' + marker + '>'
                                            for query, srcset, source_sizes in sources)
                if context == 'home-hero':
                    hero_preload_source = source
                    hero_count += 1
                else:
                    case_sources.add(largest)
                    case_count += 1
            return markup
        html = IMG.sub(image_markup, page_html)
        if hero_preload_source:
            # Replace, rather than duplicate, the previous WebP hero preload.
            html = IMAGE_PRELOAD.sub(lambda match: '' if Tag(match[0]).attrs.get('href') == hero_preload_source else match[0], html)
        if cover_preload:
            viewport = VIEWPORT.search(html)
            if not viewport:
                raise ValueError('Responsive cover preload requires an early viewport: ' + str(page))
            html = html[:viewport.end()] + cover_preload + html[viewport.end():]
        page.write_text(html)
    return {'responsive_cards': count, 'unique_covers': card_variants.cache_info().currsize,
            'responsive_case_images': case_count, 'unique_case_images': len(case_sources),
            'responsive_home_heroes': hero_count}


def bundle_catalog_styles(output):
    """Preserve source order and shared grid rules while removing three requests."""
    output = Path(output)
    names = ['analytics-consent.css', 'style.css', 'portfolio.css', 'catalog.css']
    (output / 'catalog-bundle.css').write_text('\n'.join((output / name).read_text() for name in names))
    pattern = re.compile(r'<link\s+rel="stylesheet"\s+href="/(?:' +
                         '|'.join(re.escape(name) for name in names) + r')"\s*>')
    for page in output.rglob('*.html'):
        text = page.read_text()
        if 'catalog-page' not in text:
            continue
        first = True
        def bundled(match):
            nonlocal first
            if first:
                first = False
                return '<link rel="stylesheet" href="/catalog-bundle.css">'
            return ''
        page.write_text(pattern.sub(bundled, text))
