"""Minify one reviewed route after source validation and conservative CSS pruning."""
from functools import lru_cache
from pathlib import Path
import json
import re
import subprocess


TARGET_COHORT = json.loads((Path(__file__).with_name('mobile-si-target-routes.json')).read_text())
MINIFIED_CASES = frozenset(
    str(Path(route.lstrip('/')) / 'index.html')
    for route in TARGET_COHORT['routes']
    if route not in TARGET_COHORT.get('redirect_aliases', {})
    and re.fullmatch(r'/(?:en/)?portfolio/\d{4}/[^/]+/', route)
) | frozenset({'en/portfolio/2022/zabava-restaurant-sambir/index.html'})


@lru_cache(maxsize=8)
def minify_fragment(html):
    result = subprocess.run(['node', str(Path(__file__).with_name('minify-case-page.cjs'))],
                            input=json.dumps([html]), text=True, capture_output=True,
                            check=True)
    values = json.loads(result.stdout)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
        raise ValueError('Unexpected pinned minifier result')
    return values[0]


def minify_reviewed_cases(output):
    from first_paint import (generated_root, validate_page_inline_scripts,
                             _critical_payload, PAGE_CRITICAL_PROFILES, PAGE_INLINE_MARKER)
    output = generated_root(output)
    count = 0
    for relative in sorted(MINIFIED_CASES):
        page = output / relative
        if not page.is_file():
            continue
        html = page.read_text()
        validate_page_inline_scripts(output, page, html)
        _, payload = _critical_payload(output, PAGE_CRITICAL_PROFILES['case'], PAGE_INLINE_MARKER)
        if 'data-zabava-agent-tools' in html:
            from zabava_first_paint import transform_critical_payload
            payload = transform_critical_payload(output, payload)
        if minify_fragment(payload) in html:
            continue
        compact = minify_fragment(html)
        validate_page_inline_scripts(output, page, compact)
        page.write_text(compact)
        count += 1
    return count
