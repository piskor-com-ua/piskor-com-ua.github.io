"""Build the public concept artifact without internal notes or source PNG masters."""
from pathlib import Path
import re
import shutil

source = Path('concept')
out = Path('_site')
if out.exists():
    shutil.rmtree(out)
out.mkdir()
for path in source.rglob('*'):
    if not path.is_file():
        continue
    relative = path.relative_to(source)
    if path.suffix in {'.html', '.css', '.js', '.webp', '.ttf'} or path.name in {'piskor-logo.png', 'Roboto-LICENSE.txt'}:
        destination = out / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
(out / '.nojekyll').touch()
for path in out.glob('*'):
    if path.suffix not in {'.html', '.css', '.js'}:
        continue
    text = path.read_text()
    references = re.findall(r'''(?:src|href)=["']([^"']+)["']''', text) if path.suffix == '.html' else []
    references += re.findall(r'''["'(](assets/[^"')\s]+)["')]''', text)
    for reference in references:
        if reference.startswith(('http:', 'https:', '#', 'tel:', 'mailto:', 'viber:', 'data:')):
            continue
        assert not reference.startswith('/'), f'Root-relative URL breaks project Pages: {reference}'
        assert (out / reference.split('?')[0]).is_file(), f'Missing resource: {reference}'
assert 'noindex' in (out / 'index.html').read_text(), 'Preview must remain noindex'
assert not list(out.rglob('*.md'))
print(f'Validated {len(list(out.rglob("*")))} artifact entries')
