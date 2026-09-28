"""Build with locked Jekyll, fingerprint resources and validate the public artifact."""
from pathlib import Path
import re
import subprocess
import hashlib
from optimize_assets import optimize_assets

source = Path('concept')
out = Path('_site')
subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', 'scripts',
                '-p', 'test_optimize_assets.py'], check=True)
subprocess.run(['bundle', 'exec', 'jekyll', 'build', '--trace'], check=True)
# Pages receives an already generated artifact; it must not build it a second time.
(out / '.nojekyll').touch()
optimization = optimize_assets(out)
print(f"Optimized media: {optimization['unused']} unused files, "
      f"{optimization['duplicates']} exact duplicates removed; "
      f"{optimization['saved_bytes']:,} bytes saved")
# A changed stylesheet or script must not reuse the previous browser cache entry.
for page in out.rglob('*.html'):
    def version_resource(match):
        prefix, reference, quote = match.groups()
        resource = out / reference.lstrip('/') if reference.startswith('/') else page.parent / reference
        if resource.suffix not in {'.css', '.js'} or not resource.is_file():
            return match.group(0)
        digest = hashlib.sha256(resource.read_bytes()).hexdigest()[:12]
        return f'{prefix}{reference}?v={digest}{quote}'
    page.write_text(re.sub(r'''((?:src|href)=["'])([^"'?]+)(["'])''', version_resource, page.read_text()))
for path in out.rglob('*'):
    if path.suffix not in {'.html', '.css', '.js'}:
        continue
    text = path.read_text()
    references = re.findall(r'''(?:src|href)=["']([^"']+)["']''', text) if path.suffix == '.html' else []
    references += re.findall(r'''["'(](/?assets/[^"')\s]+)["')]''', text)
    for reference in references:
        if reference.startswith(('http:', 'https:', '#', 'tel:', 'mailto:', 'viber:', 'data:')):
            continue
        clean = reference.split('#')[0].split('?')[0]
        resource = out / clean.lstrip('/') if clean.startswith('/') else path.parent / clean
        if resource.is_dir():
            resource = resource / 'index.html'
        assert resource.is_file(), f'Missing resource in {path}: {reference}'
assert 'noindex' in (out / 'index.html').read_text(), 'Preview must remain noindex'
assert not list(out.rglob('*.md'))
for path in out.rglob('*'):
    if path.is_file():
        assert path.suffix in {'.html', '.css', '.js', '.webp', '.ttf', '.mp4'} or path.name in {'piskor-logo.png', 'Roboto-LICENSE.txt', '.nojekyll', 'sitemap.xml', 'robots.txt', 'whatsapp.svg', 'viber.svg'}, f'Non-public file: {path}'
print(f'Validated {len(list(out.rglob("*")))} artifact entries')
print(f'Publication contains {sum(p.is_file() for p in out.rglob("*"))} files')
subprocess.run(['python3', 'scripts/check-seo.py'], check=True)
