"""Prune generated media and share byte-identical images, never source assets."""
from pathlib import Path
import hashlib
import re

TEXT_SUFFIXES = {'.html', '.css', '.js'}
MEDIA_SUFFIXES = {'.webp', '.png', '.svg', '.ttf', '.mp4'}
# Includes srcset, data-full, posters, JSON-LD and literal JS/CSS asset URLs.
ASSET_URL = re.compile(
    r'(?P<prefix>(?:\.\./)*|\./|/)?'
    r'(?P<asset>assets/[\w./%-]+\.(?:webp|png|svg|ttf|mp4))'
    r'(?=$|[\s\"\'<>(),?#`\\])'
)


def optimize_assets(output):
    output = Path(output).resolve()
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only an already generated Pages artifact may be optimized')
    assets = output / 'assets'
    texts = {p: p.read_text() for p in output.rglob('*')
             if p.is_file() and p.suffix in TEXT_SUFFIXES}
    referenced = {m['asset'] for text in texts.values()
                  for m in ASSET_URL.finditer(text)}
    candidates = sorted(p for p in assets.rglob('*')
                        if p.is_file() and p.suffix in MEDIA_SUFFIXES)
    # Fail before removing anything if the artifact already has broken media URLs.
    for reference in referenced:
        target = output / reference
        if not target.is_file() or not target.resolve().is_relative_to(assets):
            raise ValueError(f'Missing or unsafe generated asset: {reference}')
    for path in candidates:
        if path.is_symlink() or not path.resolve().is_relative_to(assets):
            raise ValueError(f'Unsafe generated asset: {path}')

    unused = [p for p in candidates if p.relative_to(output).as_posix() not in referenced]
    aliases, fingerprints = {}, {}
    for path in candidates:
        reference = path.relative_to(output).as_posix()
        if reference not in referenced or path.suffix not in {'.webp', '.png'}:
            continue
        digest = (path.suffix, hashlib.sha256(path.read_bytes()).digest())
        if digest in fingerprints:
            aliases[reference] = fingerprints[digest]
        else:
            fingerprints[digest] = reference

    for path, text in texts.items():
        rewritten = ASSET_URL.sub(
            lambda m: (m['prefix'] or '') + aliases.get(m['asset'], m['asset']), text)
        if rewritten != text:
            path.write_text(rewritten)

    removed = unused + [output / reference for reference in aliases]
    saved_bytes = sum(p.stat().st_size for p in removed)
    for path in removed:
        path.unlink()
    # Check every static media reference again, including gallery and srcset URLs.
    for path in texts:
        for match in ASSET_URL.finditer(path.read_text()):
            if not (output / match['asset']).is_file():
                raise ValueError(f'Broken optimized media URL in {path}: {match[0]}')
    return {'unused': len(unused), 'duplicates': len(aliases), 'saved_bytes': saved_bytes}
