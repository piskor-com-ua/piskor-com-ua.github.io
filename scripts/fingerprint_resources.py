"""Version public assets and their references; keep stable paths valid for old HTML."""
import hashlib
from html import unescape
from urllib.parse import parse_qsl, urlencode
from pathlib import Path
import re
from optimize_assets import ASSET_URL, TEXT_SUFFIXES

VERSION = re.compile(ASSET_URL.pattern + r"(?P<query>\?[^\s\"'<>(),#\x60\\]*)?")


def fingerprint_resources(output):
    output = Path(output)
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only a generated Pages artifact may be fingerprinted')
    versions = {}
    for path in (output / 'assets').rglob('*'):
        if path.is_file() and path.suffix in {'.webp', '.avif', '.png', '.svg', '.woff2', '.ttf', '.mp4', '.ico'}:
            versions[path.relative_to(output).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    for path in output.rglob('*'):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            def version_asset(match):
                asset = match['asset']
                query = match['query'] or ''
                params = [(key, value) for key, value in parse_qsl(unescape(query.lstrip('?')), keep_blank_values=True) if key != 'v']
                params.append(('v', versions[asset]))
                serialized = urlencode(params)
                if '&amp;' in query:
                    serialized = serialized.replace('&', '&amp;')
                return (match['prefix'] or '') + asset + '?' + serialized
            path.write_text(VERSION.sub(version_asset, path.read_text()))
    # Hash CSS/JS after their nested image/font references have changed.
    for page in output.rglob('*.html'):
        def version_code(match):
            prefix, reference, quote = match.groups()
            resource = output / reference.lstrip('/') if reference.startswith('/') else page.parent / reference
            if resource.suffix not in {'.css', '.js'} or not resource.is_file():
                return match.group(0)
            digest = hashlib.sha256(resource.read_bytes()).hexdigest()[:12]
            return prefix + reference + '?v=' + digest + quote
        page.write_text(re.sub(r'''((?:src|href)=["'])([^"'?]+)(["'])''', version_code, page.read_text()))
    return len(versions)
