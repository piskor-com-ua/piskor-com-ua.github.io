from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import re
import subprocess
import unittest

from first_paint import (HOME_CRITICAL_SCRIPTS, inline_home_critical_scripts,
                         validate_home_inline_scripts)


class HomeCriticalInlineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.nojekyll').touch()
        (self.root / 'en').mkdir()
        self.controllers = {}
        for name in HOME_CRITICAL_SCRIPTS:
            source = (Path('concept') / name).read_bytes()
            (self.root / name).write_bytes(source)
            self.controllers[name] = source
        for relative, language in [('index.html', 'uk'), ('en/index.html', 'en')]:
            scripts = ''.join('<script src="/' + name + '?v='
                              + hashlib.sha256(self.controllers[name]).hexdigest()[:12]
                              + '" defer></script>' for name in HOME_CRITICAL_SCRIPTS)
            (self.root / relative).write_text('<html lang="' + language + '"><head>'
                '<meta name="robots" content="noindex,nofollow">' + scripts
                + '<template id="home-controllers"><script src="/story.js?v=abc"></script>'
                '<script src="/automation.js?v=def"></script><script src="/app.js?v=ghi"></script></template>'
                '</head><body><div id="app" data-home-render="' + language + '">'
                '<section id="contact"><a href="tel:+380974781005">Public phone</a></section>'
                '</div><noscript>Visible native content</noscript></body></html>')
        (self.root / '404.html').write_text('<script src="/agent-tools.js" defer></script>Unchanged 404')
        (self.root / 'alias.html').write_text('Unchanged alias')

    def test_home_only_exact_sources_order_and_no_duplicate_execution(self):
        preserved = {name: (self.root / name).read_bytes() for name in ['404.html', 'alias.html', *HOME_CRITICAL_SCRIPTS]}
        self.assertEqual(inline_home_critical_scripts(self.root), 2)
        for relative in ['index.html', 'en/index.html']:
            html = (self.root / relative).read_text()
            validate_home_inline_scripts(self.root, html)
            self.assertIn('noindex,nofollow', html)
            self.assertIn('<noscript>Visible native content</noscript>', html)
            self.assertIn('<script src="/story.js?v=abc">', html)
            self.assertLess(html.index('id="contact"'), html.index('data-inline-home-critical='))
            self.assertLess(html.index('data-inline-home-critical="agent-tools.js"'), html.index('data-inline-home-critical="home-bootstrap.js"'))
            self.assertLess(html.index('data-inline-home-critical="home-bootstrap.js"'), html.index('data-inline-home-critical="url-compat.js"'))
            for source in self.controllers.values():
                self.assertIn(source.decode(), html)
        self.assertEqual(preserved, {name: (self.root / name).read_bytes() for name in preserved})
        with self.assertRaises(ValueError):
            inline_home_critical_scripts(self.root)

    def test_validation_rejects_tampered_hash_source_wrapper_order_and_duplicates(self):
        inline_home_critical_scripts(self.root)
        original = (self.root / 'index.html').read_text()
        changes = [
            original.replace('data-source-sha256="', 'data-source-sha256="bad', 1),
            original.replace('Find published PISKOR', 'Invented PISKOR', 1),
            original.replace("document.addEventListener('DOMContentLoaded'", "document.addEventListener('load'", 1),
            original.replace('data-inline-home-critical="agent-tools.js"', 'data-inline-home-critical="url-compat.js"', 1),
            original.replace('</body>', '<script data-inline-home-critical="agent-tools.js"></script></body>'),
            original.replace('</head>', '<script src="/agent-tools.js" defer></script></head>'),
            original.replace('</body>', '<footer>Late body content</footer></body>'),
        ]
        for changed in changes:
            with self.subTest(changed=changed[-80:]), self.assertRaises(ValueError):
                validate_home_inline_scripts(self.root, changed)

    def test_future_script_attributes_hash_or_source_timing_changes_fail_before_any_write(self):
        original_uk = (self.root / 'index.html').read_bytes()
        page = self.root / 'en/index.html'
        original_en = page.read_text()
        for attribute in ['async', 'type="module"', 'nonce="nonce"', 'integrity="sha256-abc"']:
            with self.subTest(attribute=attribute):
                page.write_text(original_en.replace(' defer>', ' defer ' + attribute + '>', 1))
                with self.assertRaises(ValueError):
                    inline_home_critical_scripts(self.root)
                self.assertEqual((self.root / 'index.html').read_bytes(), original_uk)
        page.write_text(original_en.replace('?v=', '?v=wrong', 1))
        with self.assertRaises(ValueError):
            inline_home_critical_scripts(self.root)
        page.write_text(original_en)
        for unsafe in ['</script>', 'document.currentScript.src', 'document.addEventListener("DOMContentLoaded", fn)']:
            with self.subTest(unsafe=unsafe):
                (self.root / 'agent-tools.js').write_text(unsafe)
                with self.assertRaises(ValueError):
                    inline_home_critical_scripts(self.root)
                self.assertEqual((self.root / 'index.html').read_bytes(), original_uk)

    def test_native_tools_register_on_dom_ready_before_load_with_complete_contacts(self):
        inline_home_critical_scripts(self.root)
        html = (self.root / 'index.html').read_text()
        payloads = re.findall(r'<script data-inline-home-critical="[^"]+"[^>]*>\n(.*?)\n</script>', html, re.S)
        script = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
let input='';process.stdin.on('data',chunk=>input+=chunk);process.stdin.on('end',async()=>{
 const callbacks=[],events=[],registered=[];
 const document={readyState:'loading',documentElement:{lang:'uk'},
   modelContext:{registerTool(tool){assert.equal(document.readyState,'interactive');registered.push(tool);}},
   addEventListener(name,callback,options){assert.equal(name,'DOMContentLoaded');assert.equal(options.once,true);callbacks.push(callback);},
   getElementById(){return null;},
   querySelectorAll(selector){assert.equal(selector,'#contact a[href]');return[{textContent:'Public phone',getAttribute:()=> 'tel:+380974781005'}];}};
 const context=vm.createContext({document,navigator:{},addEventListener:name=>events.push(name)});
 for(const source of JSON.parse(input))vm.runInContext(source,context);
 assert.equal(registered.length,0);assert.equal(callbacks.length,3);assert.deepEqual(events,[]);
 document.readyState='interactive';for(const callback of callbacks)callback();
 assert.deepEqual(registered.map(tool=>tool.name),['search_projects','get_project_details','get_contact_options']);
 assert.deepEqual(events,['load','hashchange']);
 const contacts=JSON.parse(await registered[2].execute());assert.equal(contacts.contacts[0].url,'tel:+380974781005');
 console.log('DOM-ready registration/contact/compatibility timing verified');
}).on('error',error=>{throw error;});
'''
        result = subprocess.run(['node', '-e', script], input=json.dumps(payloads), text=True,
                                capture_output=True, check=True)
        self.assertIn('timing verified', result.stdout)

    def test_source_directory_is_never_rewritten(self):
        with self.assertRaises(ValueError):
            inline_home_critical_scripts(Path('concept'))


if __name__ == '__main__':
    unittest.main()
