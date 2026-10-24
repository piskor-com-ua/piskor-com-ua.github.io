"""Offline compatibility-copy and fragment behavior; no browser or encoding."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import hashlib
import subprocess
import unittest

from agent_content import generate_agent_content, markdown_path
from compatibility_pages import (COMPATIBILITY_ROUTES, ORIGIN, prepare_compatibility_pages,
                                 validate_compatibility_pages)
from deferred_mobile_media import CONTROLLER, transform_page
from first_paint import inline_page_critical_scripts


class CompatibilityPagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.nojekyll').touch()
        controller = Path('concept/url-compat.js').read_bytes()
        (self.root / 'url-compat.js').write_bytes(controller)
        controller_hash = hashlib.sha256(controller).hexdigest()[:12]
        self.originals = {}
        for alias, target in COMPATIBILITY_ROUTES.items():
            language = 'en' if target.startswith('/en/') else 'uk'
            counterpart = target.removeprefix('/en') if language == 'en' else '/en' + target
            uk, en = (counterpart, target) if language == 'en' else (target, counterpart)
            content = ('<!doctype html><html lang="' + language + '"><head>'
                       '<title>Canonical loft ' + language + '</title>'
                       '<meta name="robots" content="index,follow,max-image-preview:large">'
                       '<link rel="canonical" href="' + ORIGIN + target + '">'
                       '<link rel="alternate" hreflang="uk" href="' + ORIGIN + uk + '">'
                       '<link rel="alternate" hreflang="en" href="' + ORIGIN + en + '">'
                       '<link rel="alternate" hreflang="x-default" href="' + ORIGIN + uk + '">'
                       '<meta http-equiv="origin-trial" content="existing-token">'
                       '<script src="/agent-tools.js?v=prepared" defer></script>'
                       '<script src="/url-compat.js?v=' + controller_hash + '" defer></script>'
                       '<script type="application/ld+json">{"url":"' + ORIGIN + target + '"}</script>'
                       '<style data-page-styles="prepared">.project-page{color:red}</style></head>'
                       '<body class="project-page"><script data-consent-inline>/* exact consent */</script>'
                       '<main id="main"><h1>Canonical loft ' + language + '</h1>'
                       '<section id="accent-lighting-sequence"><p>Published 2021 content.</p>'
                       '<button data-gallery data-full="/assets/full.webp?v=original">Gallery</button>'
                       '<div class="gallery-grid"><figure><button data-gallery>'
                       '<picture><source srcset="/assets/cover.avif?v=prepared 768w">'
                       '<img src="/assets/cover.webp?v=prepared" alt="Same room" width="1440" height="1080" '
                       'loading="lazy"></picture></button></figure></div></section>'
                       '<section id="contact"><a href="tel:+380974781005">Public phone</a></section>'
                       '<a lang="' + ('uk' if language == 'en' else 'en') + '" href="' + counterpart + '">Language</a>'
                       '</main></body></html>').encode()
            self.path(target).parent.mkdir(parents=True)
            self.path(target).write_bytes(content)
            self.originals[target] = content
            self.path(alias).parent.mkdir(parents=True)
            self.path(alias).write_text('<html lang="' + language + '"><head>'
                '<link rel="canonical" href="' + ORIGIN + target + '">'
                '<meta http-equiv="refresh" content="0;url=' + target + '"></head><body>Legacy entry</body></html>')
        (self.root / 'project-catalog.json').write_text('{"version":1,"projects":["canonical-uk","canonical-en"]}\n')

    def path(self, route):
        return self.root / route.lstrip('/') / 'index.html'

    def test_exact_prepared_copies_keep_metadata_media_tools_contacts_and_catalog(self):
        catalog = (self.root / 'project-catalog.json').read_bytes()
        files = {path.relative_to(self.root) for path in self.root.rglob('*.html')}
        self.assertEqual(prepare_compatibility_pages(self.root), 2)
        self.assertEqual(validate_compatibility_pages(self.root), 2)
        for alias, target in COMPATIBILITY_ROUTES.items():
            expected_alias = self.originals[target].replace(
                b'name="robots" content="index,follow,max-image-preview:large"',
                b'name="robots" content="noindex,nofollow"', 1)
            self.assertEqual(self.path(alias).read_bytes(), expected_alias)
            self.assertIn(b'name="robots" content="noindex,nofollow"', self.path(alias).read_bytes())
            self.assertEqual(self.path(target).read_bytes(), self.originals[target])
            self.assertNotIn(b'http-equiv="refresh"', self.path(alias).read_bytes())
        self.assertEqual((self.root / 'project-catalog.json').read_bytes(), catalog)
        self.assertEqual({path.relative_to(self.root) for path in self.root.rglob('*.html')}, files)
        self.assertEqual(prepare_compatibility_pages(self.root), 2)  # Same prepared bytes are idempotent.

    def test_exact_inline_controllers_are_preserved_and_tampering_aborts_all_copies(self):
        for name in ('agent-tools.js', 'portfolio.js'):
            (self.root / name).write_bytes((Path('concept') / name).read_bytes())
        for route in self.originals:
            html = self.path(route).read_text()
            digest = hashlib.sha256((self.root / 'agent-tools.js').read_bytes()).hexdigest()[:12]
            portfolio_digest = hashlib.sha256((self.root / 'portfolio.js').read_bytes()).hexdigest()[:12]
            html = html.replace('/agent-tools.js?v=prepared', '/agent-tools.js?v=' + digest)
            html = html.replace('<script src="/url-compat.js',
                                '<script src="/portfolio.js?v=' + portfolio_digest + '" defer></script><script src="/url-compat.js')
            self.path(route).write_text(html)
        self.assertEqual(inline_page_critical_scripts(self.root), 2)
        aliases = {route: self.path(route).read_bytes() for route in COMPATIBILITY_ROUTES}
        english = next(route for route in self.originals if route.startswith('/en/'))
        original = self.path(english).read_text()
        self.path(english).write_text(original.replace('data-source-sha256="', 'data-source-sha256="wrong', 1))
        with self.assertRaises(ValueError):
            prepare_compatibility_pages(self.root)
        self.assertEqual({route: self.path(route).read_bytes() for route in aliases}, aliases)
        self.path(english).write_text(original)
        self.assertEqual(prepare_compatibility_pages(self.root), 2)
        self.assertEqual(validate_compatibility_pages(self.root), 2)
        for alias, target in COMPATIBILITY_ROUTES.items():
            expected_alias = self.path(target).read_bytes().replace(
                b'name="robots" content="index,follow,max-image-preview:large"',
                b'name="robots" content="noindex,nofollow"', 1)
            self.assertEqual(self.path(alias).read_bytes(), expected_alias)
            self.assertIn('data-inline-page-critical="agent-tools.js"', self.path(alias).read_text())

    def test_per_route_markdown_is_the_only_allowed_final_html_difference(self):
        prepare_compatibility_pages(self.root)
        routes = generate_agent_content(self.root)
        self.assertEqual(len(routes), 4)
        self.assertEqual(validate_compatibility_pages(self.root, markdown_alternatives=True), 2)
        for alias, target in COMPATIBILITY_ROUTES.items():
            relative = Path(alias.lstrip('/')) / 'index.html'
            html = self.path(alias).read_text()
            self.assertIn('href="/' + markdown_path(relative) + '"', html)
            markdown = (self.root / markdown_path(relative)).read_text()
            self.assertIn('url: ' + json.dumps(ORIGIN + alias), markdown)
            self.assertIn('canonical: ' + json.dumps(ORIGIN + target), markdown)
            self.assertIn('Published 2021 content.', markdown)
            original = self.path(alias).read_bytes()
            self.path(alias).write_bytes(original.replace(b'Published 2021 content.', b'Changed content.'))
            with self.assertRaisesRegex(ValueError, 'differs from its prepared canonical'):
                validate_compatibility_pages(self.root, markdown_alternatives=True)
            self.path(alias).write_bytes(original.replace(markdown_path(relative).encode(), b'agent-markdown/wrong.md'))
            with self.assertRaisesRegex(ValueError, 'own single Markdown alternative'):
                validate_compatibility_pages(self.root, markdown_alternatives=True)
            self.path(alias).write_bytes(original)

    def test_alias_delivery_deferral_keeps_exact_canonical_content(self):
        prepare_compatibility_pages(self.root)
        alias = next(iter(COMPATIBILITY_ROUTES))
        original = self.path(alias).read_text()
        amended, count = transform_page(original, CONTROLLER.read_text(), alias)
        self.assertEqual(count, 1)
        self.path(alias).write_text(amended)
        self.assertEqual(validate_compatibility_pages(self.root), 2)

    def test_invalid_target_or_changed_alias_aborts_before_replacing_either_page(self):
        aliases = {alias: self.path(alias).read_bytes() for alias in COMPATIBILITY_ROUTES}
        english_target = next(target for target in self.originals if target.startswith('/en/'))
        original = self.originals[english_target]
        variants = [original.replace(b'lang="en"', b'lang="uk"', 1),
                    original.replace((ORIGIN + english_target).encode(), b'https://other.example/', 1),
                    original.replace(b'</head>', b'<meta http-equiv="refresh" content="0;url=/"></head>'),
                    original.replace(b'/agent-tools.js?v=prepared', b'/wrong.js'),
                    original.replace(b'/url-compat.js?v=', b'/wrong-compat.js?v='),
                    original.replace(b'/url-compat.js?v=', b'/url-compat.js?v=wrong'),
                    original.replace(b'</head>', b'<script src="/url-compat.js" defer></script></head>'),
                    original.replace(b'id="contact"', b'id="missing-contact"')]
        for content in variants:
            with self.subTest(content=content[:90]):
                self.path(english_target).write_bytes(content)
                with self.assertRaisesRegex(ValueError, 'complete canonical page'):
                    prepare_compatibility_pages(self.root)
                self.assertEqual({alias: self.path(alias).read_bytes() for alias in aliases}, aliases)
        self.path(english_target).write_bytes(original)
        english_alias = next(alias for alias in aliases if alias.startswith('/en/'))
        self.path(english_alias).write_bytes(aliases[english_alias].replace(b'0;url=/en/', b'0;url=/wrong/'))
        with self.assertRaisesRegex(ValueError, 'exact existing target'):
            prepare_compatibility_pages(self.root)
        uk_alias = next(alias for alias in aliases if not alias.startswith('/en/'))
        self.assertEqual(self.path(uk_alias).read_bytes(), aliases[uk_alias])

    def test_source_directory_and_missing_target_cannot_be_rewritten(self):
        with self.assertRaises(ValueError):
            prepare_compatibility_pages('concept')
        aliases = {alias: self.path(alias).read_bytes() for alias in COMPATIBILITY_ROUTES}
        self.path(next(target for target in self.originals if target.startswith('/en/'))).unlink()
        with self.assertRaisesRegex(ValueError, 'Missing or unsafe'):
            prepare_compatibility_pages(self.root)
        self.assertEqual({alias: self.path(alias).read_bytes() for alias in aliases}, aliases)

    def test_legacy_fragments_preserve_current_path_query_and_unknown_hashes(self):
        script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('concept/url-compat.js','utf8');
const obsolete=['lighting-baseline','dimming-and-reset','lighting-automation-scenarios'];
const legacy={story:'design-process',services:'architecture-services',approach:'our-approach',gallery:'project-story',
 ...Object.fromEntries(obsolete.map(hash=>[hash,'accent-lighting-sequence']))};
for(const pathname of JSON.parse(process.argv[1]))for(const hash of [...Object.keys(legacy),'accent-lighting-sequence','custom-section']){
 const location={pathname,search:'?campaign=old&lang=en',hash:'#'+hash},listeners={},replacements=[],scrolls=[];
 const targetId=legacy[hash]||hash;
 const context=vm.createContext({location,
  document:{getElementById(id){return id===targetId?{scrollIntoView(options){scrolls.push(options.behavior);}}:null;}},
  history:{replaceState(state,title,url){replacements.push(url);const parsed=new URL(url,'https://piskor.com.ua');Object.assign(location,{pathname:parsed.pathname,search:parsed.search,hash:parsed.hash});}},
  addEventListener(name,callback){listeners[name]=callback;}});
 vm.runInContext(source,context);assert.deepEqual(Object.keys(listeners),['load','hashchange']);listeners.load();
 assert.equal(location.pathname,pathname);assert.equal(location.search,'?campaign=old&lang=en');
 assert.equal(location.hash,'#'+targetId);assert.deepEqual(scrolls,['instant']);
 assert.equal(replacements.length,hash in legacy?1:0);listeners.hashchange();
 assert.equal(replacements.length,hash in legacy?1:0);
}
const location={pathname:'/',search:'?keep=1',hash:'#lighting-baseline'},listeners={};
vm.runInNewContext(source,{location,document:{getElementById(){return null;}},
 history:{replaceState(){throw Error('Missing anchor must not rewrite URL');}},addEventListener(name,callback){listeners[name]=callback;}});
listeners.load();assert.equal(location.hash,'#lighting-baseline');
console.log('Legacy fragments preserve path/query and require a real target');
'''
        routes = [*COMPATIBILITY_ROUTES, *COMPATIBILITY_ROUTES.values()]
        result = subprocess.run(['node', '-e', script, json.dumps(routes)],
                                text=True, capture_output=True, check=True)
        self.assertIn('preserve path/query', result.stdout)


if __name__ == '__main__':
    unittest.main()
