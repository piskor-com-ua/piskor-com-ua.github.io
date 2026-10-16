"""Prepare early rendering from shared sources in the generated artifact only."""
from html import escape, unescape
from pathlib import Path
import hashlib
import re

from fontTools import subset
from fontTools.ttLib import TTFont


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
    css = (output / 'catalog-bundle.css').read_text()
    css = re.sub(r'url\(\s*(["\']?)(assets/)', r'url(\1/\2', css)
    if '</style' in css.lower():
        raise ValueError('Catalog stylesheet contains an HTML style terminator')
    digest = hashlib.sha256(css.encode()).hexdigest()[:12]
    style = '<style data-catalog-styles="' + digest + '">' + css + '</style>'
    count = 0
    for page in output.rglob('*.html'):
        html, replaced = CATALOG_SHEET.subn(lambda _: style, page.read_text())
        if replaced:
            page.write_text(html)
            count += 1
    return count
