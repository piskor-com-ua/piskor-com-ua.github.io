"""Build with locked Jekyll, fingerprint resources and validate the public artifact."""
from pathlib import Path
import re
import subprocess
import sys
from prepare_public_assets import prepare_public_assets, bundle_catalog_styles
from fingerprint_resources import fingerprint_resources
from agent_catalog import generate_agent_catalog
from agent_discovery import generate_agent_discovery, SKILL_PATH, MANIFEST_PATHS
from optimize_assets import optimize_assets
from first_paint import inline_consent, subset_fonts, inline_catalog_styles, inline_page_styles, inline_home_critical_scripts
from agent_content import generate_agent_content, MARKDOWN_ROOT, POPPY_PATH
from agent_api import generate_agent_api, API_PATHS, API_CATALOG_PATH, API_DOC_PATH
from compatibility_pages import prepare_compatibility_pages

source = Path('concept')
out = Path('_site')
subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts',
                '-p', 'test_*.py'], check=True)
subprocess.run(['bundle', 'exec', 'jekyll', 'build', '--trace'], check=True)
subprocess.run(['node', 'scripts/prerender-home.cjs', str(out)], check=True)
# Pages receives an already generated artifact; it must not build it a second time.
(out / '.nojekyll').touch()
print(f'Early consent: {inline_consent(out)} pages')
print(f'Font subsets: {subset_fonts(out)}')
print(f'Prepared images: {prepare_public_assets(out)}')
bundle_catalog_styles(out)
generate_agent_catalog(out)
generate_agent_discovery(out)
generate_agent_api(out)
optimization = optimize_assets(out)
print(f"Optimized media: {optimization['unused']} unused files, "
      f"{optimization['duplicates']} exact duplicates removed; "
      f"{optimization['saved_bytes']:,} bytes saved")
print(f'Versioned {fingerprint_resources(out)} media/font resources')
print(f'Inline home critical scripts: {inline_home_critical_scripts(out)} pages')
print(f'Inline catalog styles: {inline_catalog_styles(out)} pages')
print(f'Inline page styles: {inline_page_styles(out)} stylesheets')
print(f'Canonical compatibility copies: {prepare_compatibility_pages(out)} pages')
agent_pages = generate_agent_content(out)
print(f'Agent content: {len(agent_pages)} HTML-derived Markdown pages and website-only Poppy discovery')
for path in out.rglob('*'):
    if path.suffix not in {'.html', '.css', '.js', '.json'}:
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
expected_markdown = {SKILL_PATH, API_DOC_PATH, *(item['markdown'].lstrip('/') for item in agent_pages)}
assert {p.relative_to(out).as_posix() for p in out.rglob('*.md')} == expected_markdown
hidden_files = {p.relative_to(out).as_posix() for p in out.rglob('*')
                if p.is_file() and any(part.startswith('.') for part in p.relative_to(out).parts)}
from agent_discovery import SKILLS_INDEX_PATH
assert hidden_files == {'.nojekyll', *MANIFEST_PATHS, SKILLS_INDEX_PATH, POPPY_PATH, API_CATALOG_PATH}, f'Unexpected hidden public files: {hidden_files}'
for path in out.rglob('*'):
    if path.is_file():
        assert path.relative_to(out).as_posix() in {*MANIFEST_PATHS, *API_PATHS, SKILLS_INDEX_PATH, POPPY_PATH, *expected_markdown, MARKDOWN_ROOT + '/routes.json'} or path.suffix in {'.html', '.css', '.js', '.webp', '.avif', '.ttf', '.woff2', '.mp4'} or path.name in {'piskor-logo.png', 'favicon.ico', 'favicon-32.png', 'apple-touch-icon.png', 'Roboto-LICENSE.txt', '.nojekyll', 'sitemap.xml', 'robots.txt', 'llms.txt', 'project-catalog.json', 'whatsapp.svg', 'viber.svg'}, f'Non-public file: {path}'
print(f'Validated {len(list(out.rglob("*")))} artifact entries')
print(f'Publication contains {sum(p.is_file() for p in out.rglob("*"))} files')
subprocess.run([sys.executable, 'scripts/check-seo.py'], check=True)

subprocess.run([sys.executable, 'scripts/check-performance.py'], check=True)
