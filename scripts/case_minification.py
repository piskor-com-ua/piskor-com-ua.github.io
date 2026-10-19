"""Minify one reviewed route after source validation and conservative CSS pruning."""
from functools import lru_cache
from pathlib import Path
import json
import subprocess


MINIFIED_CASES = frozenset({'en/portfolio/2022/zabava-restaurant-sambir/index.html'})


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
        if minify_fragment(payload) in html:
            continue
        compact = minify_fragment(html)
        validate_page_inline_scripts(output, page, compact)
        page.write_text(compact)
        count += 1
    return count
