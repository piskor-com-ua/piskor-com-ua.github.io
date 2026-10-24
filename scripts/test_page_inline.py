from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import re
import subprocess
import unittest

from first_paint import (HOME_CRITICAL_SCRIPTS, PAGE_CRITICAL_PROFILES,
                         ENGINEERING_INLINE_PAGES,
                         inline_critical_scripts, inline_page_critical_scripts,
                         page_critical_profile, validate_page_inline_scripts)


class PageCriticalInlineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.nojekyll').touch()
        for name in {*HOME_CRITICAL_SCRIPTS, 'portfolio.js', 'not-found.js'}:
            (self.root / name).write_bytes((Path('concept') / name).read_bytes())
        self.pages = {
            'portfolio/2026/case/index.html': ('project-page', ['agent-tools.js', 'portfolio.js']),
            'en/portfolio/2025/legacy/index.html': ('project-page', ['agent-tools.js', 'portfolio.js', 'url-compat.js']),
            'portfolio/index.html': ('project-page catalog-page', ['agent-tools.js']),
            'en/portfolio/2020/index.html': ('project-page catalog-page', ['agent-tools.js']),
            '404.html': ('not-found-page', ['not-found.js', 'agent-tools.js']),
            'old-alias/index.html': ('project-page', ['agent-tools.js']),
            'portfolio/2027/redirect/index.html': ('project-page', ['agent-tools.js', 'portfolio.js']),
        }
        for relative, (classes, names) in self.pages.items():
            self.write_page(relative, classes, names, language='en' if relative.startswith('en/') else 'uk')
        redirect = self.root / 'portfolio/2027/redirect/index.html'
        redirect.write_text(redirect.read_text().replace('<head>', '<head><meta http-equiv="refresh" content="0;url=/portfolio/">'))
        for relative, language in [('index.html', 'uk'), ('en/index.html', 'en')]:
            self.write_page(relative, '', HOME_CRITICAL_SCRIPTS,
                            '<div data-home-render="' + language + '">Home</div>', language)

    def script(self, name):
        digest = hashlib.sha256((self.root / name).read_bytes()).hexdigest()[:12]
        return '<script src="/' + name + '?v=' + digest + '" defer></script>'

    def write_page(self, relative, classes, names, content='Visible case/gallery/contact content', language='uk'):
        page = self.root / relative
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text('<html lang="' + language + '"><head><meta name="robots" content="index,follow,max-image-preview:large">'
                        + ''.join(self.script(name) for name in names) + '</head><body class="' + classes + '">'
                        + content + '<noscript>Native navigation</noscript></body></html>')

    def snapshots(self):
        return {p: p.read_bytes() for p in self.root.rglob('*.html')}

    def payloads(self, page):
        return re.findall(r'<script data-inline-page-critical="[^"]+"[^>]*>\n(.*?)\n</script>',
                          (self.root / page).read_text(), re.S)

    def run_node(self, script, payload):
        result = subprocess.run(['node', '-e', script], input=json.dumps(payload), text=True,
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def engineering_pages(self):
        name = 'engineering-automation.js'
        (self.root / name).write_bytes((Path('concept') / name).read_bytes())
        pages = []
        for relative in sorted(ENGINEERING_INLINE_PAGES):
            self.write_page(relative, 'engineering-page', [name, 'agent-tools.js'],
                            language='en' if relative.startswith('en/') else 'uk')
            page = self.root / relative
            page.write_text(page.read_text().replace('defer></script>', 'defer fetchpriority="low"></script>', 1))
            pages.append(page)
        return pages

    def test_engineering_exact_sources_order_minification_and_route_scope(self):
        from case_minification import minify_fragment
        pages = self.engineering_pages()
        unknown = self.root / 'engineering-other/index.html'
        unknown.parent.mkdir()
        unknown.write_bytes(pages[0].read_bytes())
        original = unknown.read_bytes()
        source = (self.root / 'engineering-automation.js').read_bytes()
        self.assertEqual(inline_page_critical_scripts(self.root), 7)
        self.assertEqual(unknown.read_bytes(), original)
        self.assertEqual((self.root / 'engineering-automation.js').read_bytes(), source)
        for page in pages:
            html = page.read_text()
            self.assertEqual(page_critical_profile(self.root, page, html), 'engineering')
            self.assertNotIn('src="/engineering-automation.js', html)
            self.assertNotIn('src="/agent-tools.js', html)
            self.assertIn('Visible case/gallery/contact content', html)
            self.assertIn('<noscript>Native navigation</noscript>', html)
            self.assertLess(html.index('data-inline-page-critical="engineering-automation.js"'),
                            html.index('data-inline-page-critical="agent-tools.js"'))
            validate_page_inline_scripts(self.root, page, html)
            compact = minify_fragment(html)
            validate_page_inline_scripts(self.root, page, compact)
            scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', compact, re.S)
            self.run_node('const vm=require("node:vm");let s="";process.stdin.on("data",v=>s+=v);'
                          'process.stdin.on("end",()=>JSON.parse(s).forEach(code=>new vm.Script(code)));', scripts)
            with self.assertRaisesRegex(ValueError, 'source/hash'):
                validate_page_inline_scripts(self.root, page, compact.replace('data-source-sha256="', 'data-source-sha256="0', 1))

    def test_engineering_rejects_unreviewed_hints_order_inert_and_duplicate_dependencies_atomically(self):
        pages = self.engineering_pages()
        original = pages[-1].read_text()
        script = self.script('agent-tools.js')
        changes = {
            'priority': lambda html: html.replace('fetchpriority="low"', 'fetchpriority="high"'),
            'async': lambda html: html.replace('fetchpriority="low"', 'fetchpriority="low" async'),
            'duplicate': lambda html: html.replace('</head>', script + '</head>'),
            'inert': lambda html: html.replace('<head>', '<head><template>').replace('</head>', '</template></head>'),
            'order': lambda html: html.replace(script, '').replace('<head>', '<head>' + script),
        }
        for label, change in changes.items():
            with self.subTest(label=label):
                pages[-1].write_text(change(original))
                before = self.snapshots()
                with self.assertRaisesRegex(ValueError, 'dependency'):
                    inline_page_critical_scripts(self.root)
                self.assertEqual(self.snapshots(), before)
        pages[-1].write_text(original)
        controller = self.root / 'engineering-automation.js'
        old_digest = hashlib.sha256(controller.read_bytes()).hexdigest()[:12]
        controller.write_text('document.currentScript.remove();')
        new_digest = hashlib.sha256(controller.read_bytes()).hexdigest()[:12]
        for page in pages:
            page.write_text(page.read_text().replace(old_digest, new_digest))
        before = self.snapshots()
        with self.assertRaisesRegex(ValueError, 'timing review'):
            inline_page_critical_scripts(self.root)
        self.assertEqual(self.snapshots(), before)

    def test_known_profiles_exact_payloads_keep_retained_scripts_unknown_pages_and_source_assets(self):
        before = self.snapshots()
        assets = {p: p.read_bytes() for p in self.root.glob('*.js')}
        self.assertEqual(inline_critical_scripts(self.root), {'home': 2, 'page': 5})
        self.assertEqual((self.root / 'old-alias/index.html').read_bytes(), before[self.root / 'old-alias/index.html'])
        self.assertEqual((self.root / 'portfolio/2027/redirect/index.html').read_bytes(), before[self.root / 'portfolio/2027/redirect/index.html'])
        for relative in self.pages:
            page = self.root / relative
            html = page.read_text()
            profile = page_critical_profile(self.root, page, html)
            if profile is None:
                continue
            validate_page_inline_scripts(self.root, page, html)
            names = PAGE_CRITICAL_PROFILES[profile]
            for name in names:
                self.assertIn('data-inline-page-critical="' + name + '"', html)
                self.assertNotIn('src="/' + name, html)
            self.assertIn('Visible case/gallery/contact content', html)
            self.assertIn('<noscript>Native navigation</noscript>', html)
            self.assertIn('index,follow,max-image-preview:large', html)
        legacy = (self.root / 'en/portfolio/2025/legacy/index.html').read_text()
        self.assertIn(self.script('url-compat.js'), legacy)
        error = (self.root / '404.html').read_text()
        self.assertIn(self.script('not-found.js'), error)
        self.assertLess(error.index(self.script('not-found.js')), error.index('data-inline-page-critical'))
        for page, source in assets.items():
            self.assertEqual(page.read_bytes(), source)
        with self.assertRaises(ValueError):
            inline_page_critical_scripts(self.root)

    def test_invalid_late_page_prevents_every_home_and_page_write(self):
        page = self.root / 'portfolio/2026/case/index.html'
        original = page.read_text()
        for attribute in ['async', 'type="module"', 'nonce="nonce"', 'integrity="sha256-abc"', 'defer']:
            with self.subTest(attribute=attribute):
                page.write_text(original.replace(' defer>', ' defer ' + attribute + '>', 1))
                before = self.snapshots()
                with self.assertRaises(ValueError):
                    inline_critical_scripts(self.root)
                self.assertEqual(self.snapshots(), before)
        for bad in [original.replace('?v=', '?v=wrong', 1),
                    original.replace('</head>', self.script('portfolio.js') + '</head>'),
                    original.replace(self.script('agent-tools.js') + self.script('portfolio.js'),
                                     self.script('portfolio.js') + self.script('agent-tools.js')),
                    original.replace('agent-tools.js', 'portfolio.js', 1),
                    original.replace('</head>', '</head><script data-inline-page-critical="portfolio.js"></script>')]:
            page.write_text(bad)
            before = self.snapshots()
            with self.assertRaises(ValueError):
                inline_critical_scripts(self.root)
            self.assertEqual(self.snapshots(), before)
        page.write_text(original)
        controller = self.root / 'portfolio.js'
        for unsafe in ['</script>', 'document.currentScript.src', 'document.addEventListener("DOMContentLoaded", callback)']:
            controller.write_text(unsafe)
            before = self.snapshots()
            with self.assertRaises(ValueError):
                inline_critical_scripts(self.root)
            self.assertEqual(self.snapshots(), before)

    def test_validator_rejects_hash_payload_order_mixed_duplicate_and_unknown_profiles(self):
        inline_page_critical_scripts(self.root)
        page = self.root / 'portfolio/2026/case/index.html'
        original = page.read_text()
        for bad in [original.replace('data-source-sha256="', 'data-source-sha256="wrong', 1),
                    original.replace('const dialog =', 'const dialog = null; const unused =', 1),
                    original.replace('data-inline-page-critical="agent-tools.js"', 'data-inline-page-critical="portfolio.js"', 1),
                    original.replace('</head>', self.script('portfolio.js') + '</head>'),
                    original.replace('</body>', '<script data-inline-page-critical="portfolio.js"></script></body>'),
                    original.replace('{ once: true }', '{ once: false }', 1)]:
            with self.assertRaises(ValueError):
                validate_page_inline_scripts(self.root, page, bad)
        with self.assertRaises(ValueError):
            validate_page_inline_scripts(self.root, self.root / 'old-alias/index.html', original)
        with self.assertRaises(ValueError):
            inline_page_critical_scripts(Path('concept'))

    def test_unreviewed_dependencies_before_between_after_controllers_fail_before_any_write(self):
        (self.root / 'extra.js').write_text('window.dependsOnGallery = true;')
        page = self.root / 'portfolio/2026/case/index.html'
        original = page.read_text()
        for attributes in ['defer', 'async', 'type="module"', '']:
            extra = self.script('extra.js').replace(' defer>', (' ' + attributes if attributes else '') + '>')
            for anchor in [self.script('agent-tools.js'), self.script('portfolio.js'), '</head>']:
                with self.subTest(attributes=attributes, anchor=anchor):
                    page.write_text(original.replace(anchor, extra + anchor))
                    before = self.snapshots()
                    with self.assertRaises(ValueError):
                        inline_critical_scripts(self.root)
                    self.assertEqual(self.snapshots(), before)
        page.write_text(original)
        inline_page_critical_scripts(self.root)
        prepared = page.read_text()
        for anchor in ['</head>', '</body>']:
            with self.assertRaises(ValueError):
                validate_page_inline_scripts(self.root, page, prepared.replace(anchor, self.script('extra.js') + anchor))

    def test_known_scripts_must_be_active_head_children_and_inline_callbacks_active_body_children(self):
        page = self.root / 'portfolio/index.html'
        original = page.read_text()
        critical = self.script('agent-tools.js')
        mutations = [original.replace(critical, '<template>' + critical + '</template>'),
                     original.replace(critical, '<noscript>' + critical + '</noscript>'),
                     original.replace('<head>', '<head inert>'),
                     original.replace('<html ', '<html inert '),
                     original.replace(critical, '<div>' + critical + '</div>'),
                     original.replace(critical, '').replace('</body>', critical + '</body>')]
        for html in mutations:
            page.write_text(html)
            before = self.snapshots()
            with self.assertRaises(ValueError):
                inline_critical_scripts(self.root)
            self.assertEqual(self.snapshots(), before)
        page.write_text(original)
        inline_page_critical_scripts(self.root)
        prepared = page.read_text()
        for wrapper in ['template', 'noscript', 'div inert']:
            # An unclosed inert wrapper used to evade the exact body-end check.
            bad = prepared.replace('<script data-inline-page-critical=', '<' + wrapper + '><script data-inline-page-critical=', 1)
            with self.assertRaises(ValueError):
                validate_page_inline_scripts(self.root, page, bad)

    def test_retained_dependencies_require_exact_hash_attributes_order_active_context_and_coverage(self):
        for relative, retained in [('404.html', 'not-found.js'), ('en/portfolio/2025/legacy/index.html', 'url-compat.js')]:
            page = self.root / relative
            original = page.read_text()
            tag = self.script(retained)
            for changed in [tag.replace('?v=', '?v=wrong'), tag.replace(' defer>', ' async>'),
                            tag + tag, '<template>' + tag + '</template>']:
                page.write_text(original.replace(tag, changed))
                before = self.snapshots()
                with self.assertRaises(ValueError):
                    inline_critical_scripts(self.root)
                self.assertEqual(self.snapshots(), before)
            if retained == 'not-found.js':
                page.write_text(original.replace(tag, ''))
            else:
                page.write_text(original.replace(tag, '').replace(self.script('portfolio.js'), tag + self.script('portfolio.js')))
            before = self.snapshots()
            with self.assertRaises(ValueError):
                inline_critical_scripts(self.root)
            self.assertEqual(self.snapshots(), before)
            page.write_text(original)
        inline_page_critical_scripts(self.root)
        page = self.root / '404.html'
        html = page.read_text()
        for bad in [html.replace(self.script('not-found.js'), ''),
                    html.replace(self.script('not-found.js'), self.script('not-found.js').replace('?v=', '?v=wrong'))]:
            with self.assertRaises(ValueError):
                validate_page_inline_scripts(self.root, page, bad)

    def test_actual_gallery_and_native_tools_bind_once_at_dom_ready_and_restore_focus(self):
        inline_page_critical_scripts(self.root)
        code = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');let raw='';process.stdin.on('data',c=>raw+=c).on('end',async()=>{
 const callbacks=[],registered=[],fetches=[];let focused=null;
 const node=()=>({events:{},addEventListener(name,fn){(this.events[name]??=[]).push(fn);},emit(name,event={}){for(const fn of this.events[name]||[])fn(event);}});
 const image=node(),caption={textContent:''},close=node(),prev=node(),next=node(),dialog=node();
 Object.assign(dialog,{open:false,querySelector(selector){return({'img':image,'.lightbox-caption':caption,'[data-close]':close,'[data-prev]':prev,'[data-next]':next})[selector];},showModal(){this.open=true;},close(){this.open=false;this.emit('close');}});
 const items=[0,1].map(index=>Object.assign(node(),{dataset:{full:'/full-'+index+'.webp'},querySelector:()=>({alt:'Photo '+index}),parentElement:{querySelector:()=>({textContent:'Room '+index})},focus(){focused=this;}}));
 const document={readyState:'loading',documentElement:{lang:'uk'},modelContext:{registerTool(tool){assert.equal(document.readyState,'interactive');registered.push(tool);}},addEventListener(name,callback,options){assert.equal(name,'DOMContentLoaded');assert.equal(options.once,true);callbacks.push(callback);},querySelector:()=>dialog,querySelectorAll(selector){if(selector==='[data-gallery]')return items;assert.equal(selector,'#contact a[href]');return[{textContent:'Public phone',getAttribute:()=> 'tel:+380974781005'}];}};
 const context=vm.createContext({document,navigator:{},fetch:()=>{fetches.push('unexpected');throw Error('Unexpected early fetch')}});
 for(const source of JSON.parse(raw))vm.runInContext(source,context);
 assert.equal(registered.length,0);assert.equal(items[0].events.click,undefined);assert.deepEqual(fetches,[]);
 document.readyState='interactive';for(const callback of callbacks.splice(0))callback();
 assert.deepEqual(registered.map(t=>t.name),['search_projects','get_project_details','get_contact_options']);assert.equal(items[0].events.click.length,1);
 const contacts=JSON.parse(await registered[2].execute());assert.equal(contacts.contacts[0].url,'tel:+380974781005');
 items[0].emit('click');assert.equal(dialog.open,true);assert.equal(image.src,'/full-0.webp');assert.equal(image.alt,'Photo 0');assert.ok(caption.textContent.includes('Room 0'));
 next.emit('click');assert.equal(image.src,'/full-1.webp');prev.emit('click');assert.equal(image.src,'/full-0.webp');
 let prevented=false;dialog.emit('keydown',{key:'ArrowLeft',preventDefault(){prevented=true;}});assert.ok(prevented);assert.equal(image.src,'/full-1.webp');
 dialog.emit('keydown',{key:'ArrowRight',preventDefault(){}});assert.equal(image.src,'/full-0.webp');
 image.emit('touchstart',{touches:[{clientX:200}]});image.emit('touchend',{changedTouches:[{clientX:50}]});assert.equal(image.src,'/full-1.webp');
 close.emit('click');assert.equal(dialog.open,false);assert.equal(focused,items[0]);
 items[1].emit('click');dialog.emit('click',{target:dialog});assert.equal(dialog.open,false);assert.equal(focused,items[1]);
 assert.equal(callbacks.length,0);assert.equal(registered.length,3);
 document.querySelector=()=>null;vm.runInContext(JSON.parse(raw)[1],context);callbacks.shift()();assert.equal(registered.length,3);
 console.log('Actual gallery navigation/swipe/caption/close-focus, absent-dialog no-op and native three tools verified');
});'''
        self.assertIn('verified', self.run_node(code, self.payloads('portfolio/2026/case/index.html')))

    def test_actual_404_localization_precedes_native_registration_and_language_defaults(self):
        inline_page_critical_scripts(self.root)
        payload = {'notFound': (self.root / 'not-found.js').read_text(), 'inline': self.payloads('404.html')}
        code = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');let raw='';process.stdin.on('data',c=>raw+=c).on('end',async()=>{
 const input=JSON.parse(raw),callbacks=[],registered=[];let fetches=0;
 const element=(dataset={})=>({dataset,textContent:'UA',attrs:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},getAttribute(k){return this.attrs[k];}});
 const contact=element({errorEn:'Public phone'});contact.attrs.href='tel:+380974781005';
 const languageLinks=['uk','en'].map(language=>element({errorLang:language})),pathLink=element({errorPath:'/portfolio/'}),markdown={href:'/agent-markdown/404.md'},structured={textContent:JSON.stringify({'@graph':[{'@type':'WebPage',name:'UA'}]})},metas={};
 const document={readyState:'loading',documentElement:{lang:'uk'},modelContext:{registerTool(tool){assert.equal(document.readyState,'interactive');assert.equal(document.documentElement.lang,'en');registered.push(tool);}},addEventListener(name,fn,options){assert.equal(name,'DOMContentLoaded');assert.equal(options.once,true);callbacks.push(fn);},querySelector(selector){if(selector==='link[rel="alternate"][type="text/markdown"]')return markdown;if(selector==='script[type="application/ld+json"]')return structured;return metas[selector]??={content:'UA'};},querySelectorAll(selector){return({'[data-error-en]':[contact],'[data-error-en-label]':[],'[data-error-path]':[pathLink],'[data-error-lang]':languageLinks,'#contact a[href]':[contact]})[selector];}};
 const location={href:'https://piskor.com.ua/missing?lang=en',pathname:'/missing',search:'?lang=en'};
 const context=vm.createContext({document,location,URL,URLSearchParams,navigator:{},fetch:async()=>{fetches++;return{ok:true,json:async()=>({version:1,projects:['uk','en'].map(language=>({id:'case',language,name:language,url:'/'+language,year:2026,summary:'Published',label:'Case',facts:[],sections:[]}))})}}});
 for(const source of input.inline)vm.runInContext(source,context);
 assert.equal(registered.length,0);vm.runInContext(input.notFound,context);assert.equal(document.documentElement.lang,'en');assert.equal(markdown.href,'/agent-markdown/404-en.md');assert.equal(pathLink.attrs.href,'/en/portfolio/');assert.equal(languageLinks[1].attrs['aria-current'],'page');
 document.readyState='interactive';for(const fn of callbacks.splice(0))fn();assert.equal(registered.length,3);assert.equal(fetches,0);
 const projects=JSON.parse(await registered[0].execute({}));assert.equal(projects.projects.length,1);assert.equal(projects.projects[0].name,'en');assert.equal(fetches,1);
 const contacts=JSON.parse(await registered[2].execute());assert.equal(contacts.contacts[0].name,'Public phone');assert.equal(contacts.contacts[0].url,'tel:+380974781005');console.log('Actual 404 locale and DOM-ready native registration verified');
});'''
        self.assertIn('verified', self.run_node(code, payload))

    def test_retained_legacy_compatibility_registers_before_dom_ready_and_restores_hash_after_gallery(self):
        inline_page_critical_scripts(self.root)
        payload = {'compatibility': (self.root / 'url-compat.js').read_text(),
                   'inline': self.payloads('en/portfolio/2025/legacy/index.html')}
        code = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');let raw='';process.stdin.on('data',c=>raw+=c).on('end',()=>{
 const input=JSON.parse(raw),ready=[],listeners={},navigation=[];let galleryBound=false;
 const location={hash:'#gallery',pathname:'/en/portfolio/2025/legacy/',search:'?preview=1'};
 const document={documentElement:{lang:'en'},addEventListener(name,fn){assert.equal(name,'DOMContentLoaded');ready.push(fn);},getElementById(id){assert.equal(id,'project-story');return{scrollIntoView(options){assert.equal(options.behavior,'instant');assert.ok(galleryBound);navigation.push(id);}};},querySelector(){galleryBound=true;return null;}};
 const context=vm.createContext({document,navigator:{},location,history:{replaceState(_state,_title,url){assert.equal(url,'/en/portfolio/2025/legacy/?preview=1#project-story');}},addEventListener(name,fn){listeners[name]=fn;}});
 for(const source of input.inline)vm.runInContext(source,context);
 // This external defer script runs before the queued DOM-ready callbacks.
 vm.runInContext(input.compatibility,context);assert.deepEqual(Object.keys(listeners),['load','hashchange']);assert.equal(galleryBound,false);
 for(const fn of ready)fn();assert.ok(galleryBound);listeners.load();listeners.hashchange();assert.deepEqual(navigation,['project-story','project-story']);console.log('Retained legacy load/hash compatibility verified');
});'''
        self.assertIn('verified', self.run_node(code, payload))


if __name__ == '__main__':
    unittest.main()
