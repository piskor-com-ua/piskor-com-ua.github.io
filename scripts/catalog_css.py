"""Conservatively omit impossible class selectors from catalog inline CSS."""
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import tinycss2


WORDS = re.compile(r'[\w-]+', re.UNICODE)


class CatalogTokens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.classes = set()
        self.sources = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.classes.update((attrs.get('class') or '').split())
        if tag == 'script':
            self.in_script = True
            if attrs.get('src'):
                self.sources.append(attrs['src'])

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            # A superset, rather than just classList calls: consent constructs HTML.
            self.classes.update(WORDS.findall(data))


def catalog_classes(output, pages):
    """Union every catalog and its loaded scripts, including inline consent.

    Keep all script words as possible dynamic classes. Escaped script words
    cannot be proven absent, so fall back to the full stylesheet for those.
    Controllers must keep dynamic class names literal rather than assembling
    them from fragments; new controllers need the same review as new styles.
    """
    output = Path(output).resolve()
    classes = set()
    for page in pages:
        parser = CatalogTokens()
        html = page.read_text()
        parser.feed(html)
        classes.update(parser.classes)
        scripts = re.findall(r'<script\b[^>]*>(.*?)</script\s*>', html, re.I | re.S)
        for src in parser.sources:
            url = urlsplit(src)
            if url.scheme or url.netloc:
                return None  # An unknown external controller may create classes.
            path = (output / unquote(url.path).lstrip('/') if url.path.startswith('/')
                    else page.parent / unquote(url.path)).resolve()
            if not path.is_relative_to(output) or not path.is_file():
                return None
            scripts.append(path.read_text())
        for script in scripts:
            if re.search(r'\\(?:u|x)', script):
                return None
            classes.update(WORDS.findall(script))
    return classes


def _selectors(tokens):
    selectors, current = [], []
    for token in tokens:
        if token.type == 'literal' and token.value == ',':
            selectors.append(current)
            current = []
        else:
            current.append(token)
    selectors.append(current)
    return selectors


def _possible(tokens, classes):
    # :not(.missing), :is(.missing, a), :has() and nesting need logical analysis.
    # Preserve every functional selector, including unfamiliar future functions.
    if any(token.type in {'function', 'error'} or
           (token.type == 'literal' and token.value == '&') for token in tokens):
        return True
    required = {tokens[index + 1].value for index, token in enumerate(tokens[:-1])
                if token.type == 'literal' and token.value == '.'
                and tokens[index + 1].type == 'ident'}
    return required.issubset(classes)


def prune_catalog_css(css, classes):
    """Preserve source order/declarations; only remove impossible selector arms.

    This does not test current visibility or browser state. A class retained in
    any catalog or script keeps all of its hover/focus/pseudo-element rules.
    """
    if classes is None:
        return css

    def prune(rules):
        result = []
        for rule in rules:
            if rule.type == 'qualified-rule':
                # Preserve nested CSS, whose selectors may depend on a parent.
                if any(token.type == '{} block' for token in rule.content):
                    result.append(tinycss2.serialize([rule]))
                    continue
                selectors = _selectors(rule.prelude)
                kept = [tokens for tokens in selectors if _possible(tokens, classes)]
                if len(kept) == len(selectors):
                    result.append(tinycss2.serialize([rule]))
                elif kept:
                    result.append(','.join(tinycss2.serialize(tokens) for tokens in kept)
                                  + '{' + tinycss2.serialize(rule.content) + '}')
            elif (rule.type == 'at-rule' and rule.lower_at_keyword in
                  {'media', 'supports', 'layer', 'container'} and rule.content is not None):
                content = prune(tinycss2.parse_rule_list(rule.content))
                # Keep even empty layers: their declaration affects cascade order.
                result.append('@' + rule.at_keyword + tinycss2.serialize(rule.prelude)
                              + '{' + content + '}')
            else:
                result.append(tinycss2.serialize([rule]))
        return ''.join(result)

    rules = tinycss2.parse_stylesheet(css)
    if any(rule.type == 'error' for rule in rules):
        return css
    try:
        return prune(rules)
    except (TypeError, ValueError):
        # Nested parse errors must retain the source instead of dropping rules.
        return css
