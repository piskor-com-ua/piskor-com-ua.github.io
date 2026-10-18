import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from agent_api import (API_CATALOG_LINK, API_CATALOG_MEDIA_TYPE, API_CATALOG_PATH,
                       API_DOC_PATH, API_PATHS, OPENAPI_PATH, ORIGIN, generate_agent_api)
from agent_catalog import generate_agent_catalog


class AgentApiTests(unittest.TestCase):
    def make_catalog(self, output):
        """Produce source JSON through the real HTML-to-catalog generator."""
        (output / '.nojekyll').touch()
        for language, prefix, title in [('uk', '', 'Теплий дім'), ('en', '/en', 'A warm home')]:
            route = prefix + '/portfolio/2026/example-house/'
            page = output / route.lstrip('/') / 'index.html'
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text('<dl class="project-facts"><dt>Area</dt><dd>100 m²</dd></dl>'
                            '<section class="case-chapter" id="shared-spaces"><h2>' + title +
                            '</h2><p>Published project details.</p></section>')
            index = output / (prefix.lstrip('/') + '/portfolio').lstrip('/') / 'index.html'
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text('<a class="portfolio-card" data-project-id="example-house" href="' + route +
                             '"><p class="eyebrow">Project visualization</p><h3>' + title +
                             '</h3><p>Public summary.</p></a>')
        generate_agent_catalog(output)
        return json.loads((output / 'project-catalog.json').read_text())

    def test_real_catalog_has_one_get_operation_with_exact_schema_and_no_auth_claims(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            catalog = self.make_catalog(output)
            original = (output / 'project-catalog.json').read_bytes()
            self.assertEqual(generate_agent_api(output), API_PATHS)
            spec = json.loads((output / OPENAPI_PATH).read_text())
            self.assertEqual(spec['openapi'], '3.1.0')
            self.assertEqual(spec['servers'], [{'url': ORIGIN}])
            self.assertEqual(set(spec['paths']), {'/project-catalog.json'})
            operation = spec['paths']['/project-catalog.json']
            self.assertEqual(set(operation), {'get'})
            self.assertNotIn('parameters', operation['get'])
            self.assertEqual(spec['security'], [])
            self.assertNotIn('securitySchemes', spec['components'])
            schemas = spec['components']['schemas']
            for schema_name, sample in [('ProjectCatalog', catalog), ('Project', catalog['projects'][0]),
                                        ('Fact', catalog['projects'][0]['facts'][0]),
                                        ('Section', catalog['projects'][0]['sections'][0])]:
                self.assertEqual(set(schemas[schema_name]['required']), set(sample))
                self.assertEqual(set(schemas[schema_name]['properties']), set(sample))
                self.assertIs(schemas[schema_name]['additionalProperties'], False)
            self.assertEqual(schemas['Project']['properties']['language']['enum'], ['uk', 'en'])
            self.assertEqual(schemas['ProjectCatalog']['properties']['version']['const'], 1)
            self.assertEqual((output / 'project-catalog.json').read_bytes(), original)

    def test_rfc9727_linkset_points_only_to_real_local_documents(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.make_catalog(output)
            generate_agent_api(output)
            catalog = json.loads((output / API_CATALOG_PATH).read_text())
            listing, endpoint = catalog['linkset']
            self.assertEqual(listing['anchor'], ORIGIN + '/' + API_CATALOG_PATH)
            self.assertEqual(listing['item'], [{'href': ORIGIN + '/project-catalog.json',
                                              'type': 'application/json'}])
            self.assertEqual(endpoint['anchor'], ORIGIN + '/project-catalog.json')
            self.assertEqual(set(endpoint), {'anchor', 'service-desc', 'service-doc'})
            for relation in ('service-desc', 'service-doc'):
                for link in endpoint[relation]:
                    parsed = urlsplit(link['href'])
                    self.assertEqual(parsed.scheme + '://' + parsed.netloc, ORIGIN)
                    self.assertTrue((output / parsed.path.lstrip('/')).is_file())
            self.assertEqual(API_CATALOG_MEDIA_TYPE,
                             'application/linkset+json; profile="https://www.rfc-editor.org/info/rfc9727"')
            self.assertEqual(API_CATALOG_LINK,
                             '<https://piskor.com.ua/.well-known/api-catalog>; rel="api-catalog"')

    def test_publication_is_deterministic_and_does_not_embed_stale_project_examples(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            catalog = self.make_catalog(output)
            generate_agent_api(output)
            before = {path: (output / path).read_bytes() for path in API_PATHS}
            catalog['projects'].reverse()
            catalog['projects'][0]['name'] = 'Updated published title'
            catalog['projects'][0]['facts'] = []
            catalog['projects'][0]['sections'] = []
            (output / 'project-catalog.json').write_text(json.dumps(catalog))
            generate_agent_api(output)
            self.assertEqual(before, {path: (output / path).read_bytes() for path in API_PATHS})
            guide = (output / API_DOC_PATH).read_text()
            self.assertIn('filter its `projects` array locally', guide)
            self.assertIn('separate\nbrowser-side WebMCP tools', guide)
            self.assertIn('regenerated during the site build', guide)
            self.assertNotIn('Updated published title', guide)

    def test_source_schema_drift_and_wrong_types_fail_before_publication(self):
        for mutation in ('extra', 'missing', 'wrong-language', 'bool-version', 'nested-extra',
                         'wrong-fact-type', 'absolute-url', 'missing-section-fragment'):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                output = Path(directory)
                catalog = copy.deepcopy(self.make_catalog(output))
                project = catalog['projects'][0]
                if mutation == 'extra':
                    catalog['unexpected'] = True
                elif mutation == 'missing':
                    del project['year']
                elif mutation == 'wrong-language':
                    project['language'] = 'fr'
                elif mutation == 'bool-version':
                    catalog['version'] = True
                elif mutation == 'nested-extra':
                    project['sections'][0]['unpublished'] = 'value'
                elif mutation == 'wrong-fact-type':
                    project['facts'][0]['value'] = 100
                elif mutation == 'absolute-url':
                    project['url'] = 'https://unrelated.example/portfolio/2026/example-house/'
                else:
                    project['sections'][0]['url'] = project['url']
                (output / 'project-catalog.json').write_text(json.dumps(catalog))
                with self.assertRaises(ValueError):
                    generate_agent_api(output)
                self.assertTrue(all(not (output / path).exists() for path in API_PATHS))

    def test_missing_source_and_non_artifact_do_not_create_discovery(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(ValueError, 'generated Pages artifact'):
                generate_agent_api(output)
            (output / '.nojekyll').touch()
            with self.assertRaises(FileNotFoundError):
                generate_agent_api(output)
            self.assertTrue(all(not (output / path).exists() for path in API_PATHS))


if __name__ == '__main__':
    unittest.main()
