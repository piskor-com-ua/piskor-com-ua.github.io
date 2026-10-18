import json
import tempfile
import unittest
from pathlib import Path

from agent_content import generate_agent_content, markdown_path, page_route


class AgentContentTests(unittest.TestCase):
    def test_public_routes_and_facts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.nojekyll').touch()
            (root / '.well-known').mkdir()
            (root / 'en').mkdir()
            source = '''<html lang="en"><head><title>Published case</title><meta name="robots" content="noindex,nofollow"><link rel="canonical" href="https://piskor.com.ua/en/"></head><body><nav><a href="/portfolio/">Projects</a></nav><main><h1>Actual title</h1><p>Design proposal; area 77 m².</p><h2 id="lighting">Lighting</h2><p>Potential automation.</p><script>PRIVATE_SCRIPT</script><style>STYLE_CONTENT</style><p hidden>HIDDEN_TEXT</p><a href="#lighting">Lighting section</a><img alt="Published living room" src="/assets/room.webp"></main><footer><a href="tel:+380974781005">Public phone</a></footer></body></html>'''
            (root / 'en/index.html').write_text(source)
            (root / '404.html').write_text(source)
            routes = generate_agent_content(root)
            self.assertEqual({item['url'] for item in routes}, {'/en/', '/404.html'})
            text = (root / 'agent-markdown/en/index.md').read_text()
            for value in ['Actual title', '77 m²', 'Potential automation.', 'https://piskor.com.ua/en/#lighting', 'tel:+380974781005', 'noindex,nofollow', 'Published living room']:
                self.assertIn(value, text)
            for value in ['PRIVATE_SCRIPT', 'STYLE_CONTENT', 'HIDDEN_TEXT']:
                self.assertNotIn(value, text)
            poppy = json.loads((root / '.well-known/poppy.json').read_text())
            self.assertEqual(poppy['web'], {})
            self.assertNotIn('auth', poppy)
            self.assertNotIn('apis', poppy)
            original = text
            generate_agent_content(root)
            self.assertEqual(original, (root / 'agent-markdown/en/index.md').read_text())

    def test_english_error_uses_public_translations_and_source_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                generate_agent_content(root)
            (root / '.nojekyll').touch()
            (root / '404.html').write_text('<html lang="uk"><head><title>Помилка</title></head><body><h1 data-error-en="Not found">Немає</h1><a data-error-path="/#contact" href="/#contact">Contact</a><button><h3>Published service</h3></button><p>Literal [text] * words</p><a href=" javascript:alert(1)">Unsafe</a></body></html>')
            (root / 'not-found.js').write_text("const title = 'Page not found';")
            routes = generate_agent_content(root)
            self.assertEqual(len(routes), 2)
            text = (root / 'agent-markdown/404-en.md').read_text()
            self.assertIn('# Not found', text)
            self.assertIn('https://piskor.com.ua/en/#contact', text)
            self.assertIn('### Published service', text)
            self.assertIn('Literal \\[text\\] \\* words', text)
            self.assertNotIn('javascript:', text)

    def test_paths(self):
        self.assertEqual(page_route(Path('index.html')), '/')
        self.assertEqual(page_route(Path('en/portfolio/index.html')), '/en/portfolio/')
        self.assertEqual(markdown_path(Path('404.html')), 'agent-markdown/404.md')


if __name__ == '__main__':
    unittest.main()
