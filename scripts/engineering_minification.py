"""Compile only the two approved service pages with the pinned HTML transform."""
import hashlib
from pathlib import Path
import re

from case_minification import minify_fragment

ROUTES = ('engineering-automation/index.html', 'en/engineering-automation/index.html')
CONSENT_SHA256 = 'b74abfc1372fd34499519c92486c471d98fee3627792e882a2f23a0d9b878feb'
CONSENT = re.compile(r'(<script\b[^>]*\bdata-consent-inline\b[^>]*>)([\s\S]*?)(</script>)', re.I)


def validate_engineering_consent(output, html):
    source = (Path(output) / 'analytics-consent.js').read_text()
    if hashlib.sha256(source.encode()).hexdigest() != CONSENT_SHA256:
        raise ValueError('Engineering compilation requires review of the changed consent controller')
    matches = list(CONSENT.finditer(html))
    if len(matches) != 1:
        raise ValueError('Engineering consent coverage differs')
    match = matches[0]
    original = match[1] + source + match[3]
    if match[0] not in (original, minify_fragment(original)):
        raise ValueError('Engineering consent differs from the exact pinned transform')
    return match[0] == minify_fragment(original)


def minify_engineering_pages(output):
    output = Path(output)
    if not (output / '.nojekyll').is_file():
        raise ValueError('Engineering compilation only accepts a generated artifact')
    plans = []
    for route in ROUTES:
        page = output / route
        if not page.is_file():
            continue
        html = page.read_text()
        if 'class="engineering-page"' not in html:
            raise ValueError('Engineering route has an unexpected body')
        compiled = validate_engineering_consent(output, html)
        main = re.search(r'<main\b[^>]*\bid="main"[^>]*>', html)
        if not main:
            raise ValueError('Engineering route has no expected main landmark')
        consent = CONSENT.search(html)
        if compiled and consent.start() < main.start():
            continue
        # The two service pages can paint while the longer demo markup is still
        # arriving. Start the unchanged consent controller before main so its
        # banner/font is ready for that first paint. It reads only body class,
        # document language and its own script attributes, all available here.
        # Other routes retain their existing complete-DOM bootstrap timing.
        original = consent[1] + (output / 'analytics-consent.js').read_text() + consent[3]
        html = html[:consent.start()] + html[consent.end():]
        main = re.search(r'<main\b[^>]*\bid="main"[^>]*>', html)
        html = html[:main.start()] + original + html[main.start():]
        compact = minify_fragment(html)
        validate_engineering_consent(output, compact)
        if compact != html:
            plans.append((page, compact))
    for page, compact in plans:
        page.write_text(compact)
    return len(plans)
