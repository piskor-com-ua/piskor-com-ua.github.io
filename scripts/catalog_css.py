"""Conservatively omit impossible class selectors from catalog inline CSS."""
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import tinycss2


WORDS = re.compile(r'[\w-]+', re.UNICODE)
CLASS_MUTATION = re.compile(r'\.classList\.(add|remove|toggle|replace)\s*\(\s*')


def safe_class_mutations(script):
    """Literal names and literal hyphen prefixes are the bounded supported cases.

    An arbitrary expression cannot be inferred from script words. Retain the
    complete stylesheet rather than silently removing one of its runtime states.
    """
    for mutation in CLASS_MUTATION.finditer(script):
        argument = script[mutation.end():]
        if mutation[1] != 'toggle':
            # add/remove may take several class names; replace takes two. Do not
            # mistake a literal first argument for proof about later arguments.
            name = r'''(?:"[\w-]+"|'[\w-]+')'''
            if not re.match(name + r'(?:\s*,\s*' + name + r')*\s*\)', argument):
                return False
            continue
        literal = re.match(r'''(["'])([\w-]+)\1\s*([,+)])''', argument)
        if not literal or literal[3] == '+' and not literal[2].endswith('-'):
            return False
    return True


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
    Literal names and literal hyphen prefixes are supported. Arbitrary classList
    expressions retain full CSS; new controllers need the same review as styles.
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
            if re.search(r'\\(?:u|x)', script) or not safe_class_mutations(script):
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


def _possible(tokens, classes, prune_functional_ancestors=False):
    # Default output preserves every functional selector. The reviewed opt-in
    # may only rule out mandatory classes outside known logical functions.
    def uncertain(items):
        for token in items:
            if (token.type == 'error' or
                    token.type == 'literal' and token.value == '&'):
                return True
            if token.type == 'function':
                if (not prune_functional_ancestors or
                        token.lower_name not in {'is', 'where', 'not', 'has'} or
                        uncertain(token.arguments)):
                    return True
            elif hasattr(token, 'content') and uncertain(token.content):
                return True
        return False

    if (uncertain(tokens) if prune_functional_ancestors else
            any(token.type in {'function', 'error'} or
                (token.type == 'literal' and token.value == '&') for token in tokens)):
        return True
    # Classes directly in the selector remain mandatory even beside a logical
    # function. Never inspect its arguments: :not(.absent), for example, does
    # not require .absent to exist. Unknown functions and parse errors stay.
    required = {tokens[index + 1].value for index, token in enumerate(tokens[:-1])
                if token.type == 'literal' and token.value == '.'
                and tokens[index + 1].type == 'ident'}
    prefixes = {name for name in classes if name.endswith('-')}
    return all(name in classes or any(name.startswith(prefix) for prefix in prefixes)
               for name in required)


def prune_catalog_css(css, classes, *, prune_functional_ancestors=False):
    """Preserve source order/declarations; only remove impossible selector arms.

    This does not test current visibility or browser state. A class retained in
    any catalog or script keeps all of its hover/focus/pseudo-element rules.
    Optional functional-ancestor pruning tests only outer mandatory classes;
    function arguments never supply required classes.
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
                kept = [tokens for tokens in selectors
                        if _possible(tokens, classes, prune_functional_ancestors)]
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
