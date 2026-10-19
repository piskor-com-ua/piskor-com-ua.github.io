"""Reviewed, generated-artifact delivery profile for the English Zabava case.

Only this route embeds its original logo, an endpoint-exact Roboto variable
subset, and a real 704px AVIF candidate. q35 is an explicit image-compression
tradeoff; it is not a claim of lossless or unchanged image quality. All existing
font/image resources and all other pages remain untouched.
"""
import ast
import base64
import hashlib
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re

from fontTools import subset, varLib
from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageOps

from first_paint import generated_root

ROUTE = 'en/portfolio/2022/zabava-restaurant-sambir/index.html'
COVER = 'assets/portfolio/zabava-restaurant-sambir/zabava-restaurant-sambir-01-2200.webp'
LOGO = 'assets/responsive/piskor-logo.webp'
FONT_PATHS = {300: 'assets/fonts/roboto-light-subset.woff2',
              400: 'assets/fonts/roboto-regular-subset.woff2'}


class _VisibleText(HTMLParser):
    """Exclude inert/document metadata; retain inline CSS for generated content."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.text, self.css = [], []

    def handle_starttag(self, tag, attrs):
        if tag in {'head', 'script', 'style', 'template'}:
            self.hidden.append(tag)

    def handle_endtag(self, tag):
        if tag in {'head', 'script', 'style', 'template'}:
            if not self.hidden or self.hidden.pop() != tag:
                raise ValueError('Malformed Zabava text container')

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
        if self.hidden and self.hidden[-1] == 'style':
            self.css.append(data)


def _critical_characters(html, controller):
    """Unknown consent syntax fails before writes; other glyphs keep global coverage.

    The reviewed gallery controller constructs only numeric positions, slash,
    middle dot and existing captions. Native video controls also render a
    numeric timer with a colon. Include those plus all uppercase text as
    a conservative bound for CSS text-transform. Inert templates and unvisited
    dynamic text can still use the complementary original global font faces.
    """
    parser = _VisibleText()
    parser.feed(html)
    parser.close()
    if parser.hidden:
        raise ValueError('Unclosed Zabava text container')
    match = re.search(r'const copy = isEnglish \? \{(.*?)\} : \{', controller, re.S)
    if not match:
        raise ValueError('Unrecognized English consent copy')
    fields = re.findall(r"(\w+)\s*:\s*('(?:\\.|[^'\\])*')\s*(?:,|$)", match[1].strip())
    expected = {'title', 'description', 'accept', 'reject', 'settings', 'learn', 'label'}
    if len(fields) != len(expected) or {key for key, _ in fields} != expected:
        raise ValueError('Unrecognized English consent fields')
    # Reject expressions, comments and unparsed object members rather than
    # accidentally producing a subset from a partial JavaScript object.
    residue = re.sub(r"\w+\s*:\s*'(?:\\.|[^'\\])*'\s*,?", '', match[1]).strip()
    if residue:
        raise ValueError('Unparsed English consent expression')
    try:
        consent = ' '.join(ast.literal_eval(value) for _, value in fields)
    except (ValueError, SyntaxError) as error:
        raise ValueError('Unrecognized consent string escape') from error
    content = re.findall(r'''content\s*:\s*['"]([^'"]*)['"]''', '\n'.join(parser.css))
    css_text = ''.join(re.sub(r'\\([0-9a-fA-F]{1,6})\s?',
                              lambda value: chr(int(value[1], 16)), value)
                       for value in content)
    text = ' '.join(parser.text) + ' ' + consent + ' ' + css_text + ' 0123456789 / · :'
    return set(map(ord, text + text.upper()))


def _unicode_range(codes):
    runs = []
    for value in sorted(codes):
        if runs and value == runs[-1][1] + 1:
            runs[-1][1] = value
        else:
            runs.append([value, value])
    return ','.join(f'U+{a:x}' + (f'-{b:x}' if a != b else '') for a, b in runs)


def _outline(font, name, location=None):
    glyphs = font.getGlyphSet(location=location)
    pen = DecomposingRecordingPen(glyphs)
    glyphs[name].draw(pen)
    return pen.value, glyphs[name].width


def _variable_font(output, characters):
    """Rebuild from this build's static masters; never consume an opaque cache."""
    masters = {weight: TTFont(output / path, recalcTimestamp=False)
               for weight, path in FONT_PATHS.items()}
    light = masters[300]
    if any(font.getBestCmap() != light.getBestCmap() or
           font.getGlyphOrder() != light.getGlyphOrder() for font in masters.values()):
        raise ValueError('Roboto masters have different coverage or glyph order')
    designspace = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.name, axis.tag = 'Weight', 'wght'
    axis.minimum = axis.default = 300
    axis.maximum = 400
    designspace.addAxis(axis)
    for weight, master in masters.items():
        source = SourceDescriptor()
        source.name, source.location, source.font = f'Roboto-{weight}', {'Weight': weight}, master
        designspace.addSource(source)
    # IUP optimization can alter unrounded endpoints by fractional font units.
    font, _, _ = varLib.build(designspace, optimize=False)
    font.recalcTimestamp = False
    font['head'].created, font['head'].modified = light['head'].created, light['head'].modified
    for weight, master in masters.items():
        if any(_outline(master, glyph) != _outline(font, glyph, {'wght': weight})
               for glyph in master.getGlyphOrder()):
            raise ValueError('Variable Roboto changed endpoint outlines or advances')
        instance = instantiateVariableFont(font, {'wght': weight}, inplace=False, optimize=False)
        if instance['hmtx'].metrics != master['hmtx'].metrics:
            raise ValueError('Variable Roboto changed endpoint hmtx')
        for table, fields in [('hhea', ('ascent', 'descent', 'lineGap')),
                              ('OS/2', ('sTypoAscender', 'sTypoDescender', 'sTypoLineGap',
                                        'usWinAscent', 'usWinDescent'))]:
            if any(getattr(instance[table], field) != getattr(master[table], field) for field in fields):
                raise ValueError('Variable Roboto changed vertical metrics')
    available = set(light.getBestCmap())
    critical = characters & available
    if not critical:
        raise ValueError('Empty Zabava critical font coverage')
    options = subset.Options()
    options.flavor = 'woff2'
    # Global masters are already unhinted; never introduce a second hinting policy.
    options.hinting = False
    options.layout_features = ['*']
    worker = subset.Subsetter(options=options)
    worker.populate(unicodes=critical)
    worker.subset(font)
    if set(font.getBestCmap()) != critical or not all(tag in font for tag in ('GSUB', 'GPOS', 'GDEF')):
        raise ValueError('Critical Roboto lost coverage or layout tables')
    font.flavor = 'woff2'
    data = BytesIO()
    font.save(data)
    return data.getvalue(), critical, available - critical


def _data_uri(kind, data):
    return 'data:' + kind + ';base64,' + base64.b64encode(data).decode('ascii')


def _insert_candidate(tag, attribute, candidate):
    match = re.search(r'\b' + attribute + r'="([^"]+)"', tag)
    if not match or len(re.findall(r'\s640w(?:,|$)', match[1])) != 1 or re.search(r'\s704w(?:,|$)', match[1]):
        raise ValueError('Unrecognized Zabava cover candidates')
    value = re.sub(r'(\s640w),', lambda item: item[1] + ', ' + candidate + ',', match[1], count=1)
    if value == match[1]:
        raise ValueError('Missing cover candidate insertion point')
    return tag[:match.start(1)] + value + tag[match.end(1):]


def optimize_zabava_en(output):
    output = generated_root(output)
    page = output / ROUTE
    if not page.is_file():
        return None
    html = page.read_text()
    critical_text = _critical_characters(html, (output / 'analytics-consent.js').read_text())
    font, critical, remaining = _variable_font(output, critical_text)
    if not remaining:
        raise ValueError('Expected complementary global Roboto coverage')
    faces = [face for face in re.findall(r'@font-face\{[^{}]*\}', html)
             if re.search(r'font-family:\s*[\'"]?Roboto(?:[\'"]?\s*;)', face)]
    if len(faces) != 2:
        raise ValueError('Expected two original Roboto faces')
    # Fixed-weight declarations must match each complementary static face.
    # A 300–400 range can suppress same-family Cyrillic fallback in Chromium;
    # both declarations intentionally reuse one identical variable payload.
    inline = ('@font-face{font-family:Roboto;src:url("' + _data_uri('font/woff2', font) +
              '") format("woff2");font-weight:{weight};font-display:swap;unicode-range:' +
              _unicode_range(critical) + '}')
    weights = set()
    for face in faces:
        weight_match = re.search(r'font-weight:\s*(300|400)\s*;', face)
        if not weight_match or 'unicode-range' in face:
            raise ValueError('Unrecognized original Roboto face')
        weight = int(weight_match[1])
        if FONT_PATHS[weight] not in face:
            raise ValueError('Unexpected original Roboto source')
        weights.add(weight)
        fallback = face[:-1].rstrip(';') + ';unicode-range:' + _unicode_range(remaining) + '}'
        html = html.replace(face, inline.replace('{weight}', str(weight)) + fallback, 1)
    if weights != {300, 400}:
        raise ValueError('Missing Roboto weight')
    # Remove only these fonts' preloads. The complementary faces remain demand-loaded.
    html = re.sub(r'<link\b[^>]*>', lambda match: '' if
                  re.search(r'\brel="preload"', match[0]) and
                  re.search(r'\bas="font"', match[0]) and
                  any(path in match[0] for path in FONT_PATHS.values()) else match[0], html)
    original_cover = (output / COVER).read_bytes()
    with Image.open(BytesIO(original_cover)) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGB')
        if image.size != (2200, 1650):
            raise ValueError('Unexpected original Zabava cover dimensions')
        image = image.resize((704, 528), Image.Resampling.LANCZOS)
        encoded = BytesIO()
        image.save(encoded, 'AVIF', quality=35, speed=0, max_threads=1)
    cover = encoded.getvalue()
    candidate = _data_uri('image/avif', cover) + ' 704w'
    cover_match = re.search(r'(<figure\b[^>]*class="project-cover"[^>]*>\s*<picture>\s*)(<source\b[^>]*>)', html)
    if not cover_match or 'type="image/avif"' not in cover_match[2]:
        raise ValueError('Missing mobile Zabava cover source')
    amended = _insert_candidate(cover_match[2], 'srcset', candidate)
    html = html[:cover_match.start(2)] + amended + html[cover_match.end(2):]
    preloads = list(re.finditer(r'<link\b[^>]*data-case-cover-preload[^>]*>', html))
    if len(preloads) != 1 or 'type="image/avif"' not in preloads[0][0]:
        raise ValueError('Expected one mobile AVIF cover preload')
    preload = preloads[0]
    html = html[:preload.start()] + _insert_candidate(preload[0], 'imagesrcset', candidate) + html[preload.end():]
    logo = (output / LOGO).read_bytes()
    count = 0
    def inline_logo(match):
        nonlocal count
        tag = match[0]
        if re.search(r'\bsrcset="/' + re.escape(LOGO) + r'(?:\?[^" ]*)?"', tag):
            count += 1
            return re.sub(r'(\bsrcset=")[^"]+("\s*)', lambda value: value[1] + _data_uri('image/webp', logo) + value[2], tag, count=1)
        return tag
    html = re.sub(r'<source\b[^>]*>', inline_logo, html)
    if count != 2:
        raise ValueError('Expected header and footer logo sources')
    page.write_text(html)
    digest = lambda data: hashlib.sha256(data).hexdigest()
    return {'page': ROUTE, 'html_bytes': len(html.encode()),
            'font_bytes': len(font), 'font_sha256': digest(font),
            'critical_codepoints': sorted(critical), 'fallback_codepoints': sorted(remaining),
            'font_masters': {str(weight): digest((output / path).read_bytes()) for weight, path in FONT_PATHS.items()},
            'cover_bytes': len(cover), 'cover_sha256': digest(cover),
            'cover_source_sha256': digest(original_cover), 'cover_recipe': '704x528:AVIF:q35:speed0:threads1:LANCZOS',
            'logo_bytes': len(logo), 'logo_sha256': digest(logo)}
