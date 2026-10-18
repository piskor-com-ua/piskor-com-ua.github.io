"""Describe the existing public JSON catalog without inventing server operations."""
import json
from pathlib import Path
import re


ORIGIN = 'https://piskor.com.ua'
API_CATALOG_PATH = '.well-known/api-catalog'
OPENAPI_PATH = 'agent-api/openapi.json'
API_DOC_PATH = 'agent-api/index.md'
API_PATHS = (API_CATALOG_PATH, OPENAPI_PATH, API_DOC_PATH)
API_CATALOG_MEDIA_TYPE = 'application/linkset+json; profile="https://www.rfc-editor.org/info/rfc9727"'
API_CATALOG_LINK = '<' + ORIGIN + '/' + API_CATALOG_PATH + '>; rel="api-catalog"'


def _object(properties):
    return {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}


def catalog_schemas():
    """The fields emitted by agent_catalog.generate_agent_catalog, including empty lists."""
    text = {'type': 'string'}
    project_url = r'^/(en/)?portfolio/[0-9]{4}/[^/#?]+/$'
    return {
        'ProjectCatalog': _object({
            'version': {'type': 'integer', 'const': 1},
            'projects': {'type': 'array', 'items': {'$ref': '#/components/schemas/Project'}},
        }),
        'Project': _object({
            'id': text,
            'language': {'type': 'string', 'enum': ['uk', 'en']},
            'year': {'type': 'integer'},
            'name': text,
            'url': {'type': 'string', 'pattern': project_url},
            'summary': text,
            'label': text,
            'facts': {'type': 'array', 'items': {'$ref': '#/components/schemas/Fact'}},
            'sections': {'type': 'array', 'items': {'$ref': '#/components/schemas/Section'}},
        }),
        'Fact': _object({'label': text, 'value': text}),
        'Section': _object({
            'title': text,
            'url': {'type': 'string', 'pattern': project_url[:-1] + r'#[^#?\s]+$'},
            'text': text,
        }),
    }


def _validate_shape(value, schema, schemas, location='catalog'):
    """Check this fixed schema subset so catalog shape changes cannot silently stale docs."""
    if '$ref' in schema:
        schema = schemas[schema['$ref'].rsplit('/', 1)[1]]
    kind = schema['type']
    valid_type = {'object': type(value) is dict, 'array': type(value) is list,
                  'string': type(value) is str, 'integer': type(value) is int}[kind]
    if not valid_type:
        raise ValueError(location + ': expected ' + kind)
    if 'const' in schema and value != schema['const']:
        raise ValueError(location + ': unsupported value')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(location + ': unsupported value')
    if 'pattern' in schema and re.search(schema['pattern'], value) is None:
        raise ValueError(location + ': invalid relative case URL')
    if kind == 'object':
        if set(value) != set(schema['required']):
            raise ValueError(location + ': fields differ from the documented contract')
        for name, child in schema['properties'].items():
            _validate_shape(value[name], child, schemas, location + '.' + name)
    elif kind == 'array':
        for index, child in enumerate(value):
            _validate_shape(child, schema['items'], schemas, location + '[' + str(index) + ']')


def generate_agent_api(output):
    """Write an RFC 9727 linkset, OpenAPI 3.1 contract and guide for one real GET."""
    output = Path(output)
    if not (output / '.nojekyll').is_file():
        raise ValueError('Only a generated Pages artifact may receive API discovery')
    catalog = json.loads((output / 'project-catalog.json').read_text())
    schemas = catalog_schemas()
    _validate_shape(catalog, schemas['ProjectCatalog'], schemas)
    endpoint = ORIGIN + '/project-catalog.json'
    linkset = {'linkset': [
        {'anchor': ORIGIN + '/' + API_CATALOG_PATH,
         'item': [{'href': endpoint, 'type': 'application/json'}]},
        {'anchor': endpoint,
         'service-desc': [{'href': ORIGIN + '/' + OPENAPI_PATH, 'type': 'application/json'}],
         'service-doc': [{'href': ORIGIN + '/' + API_DOC_PATH, 'type': 'text/markdown'}]},
    ]}
    specification = {
        'openapi': '3.1.0',
        'info': {
            'title': 'PISKOR public project catalog', 'version': '1.0.0',
            'description': 'Read-only, build-generated public project facts from the bilingual portfolio. '
                           'Fetch the complete catalog and filter locally. No server-side search or writes.',
        },
        'servers': [{'url': ORIGIN}],
        'security': [],
        'paths': {'/project-catalog.json': {'get': {
            'operationId': 'getProjectCatalog',
            'summary': 'Read the complete bilingual project catalog',
            'description': 'Returns the published snapshot. Each project has a language and relative '
                           'case/section links. Order is not guaranteed. No query parameters are supported.',
            'responses': {'200': {
                'description': 'Public project catalog, regenerated when the site is built.',
                'content': {'application/json': {'schema': {'$ref': '#/components/schemas/ProjectCatalog'}}},
            }},
        }}},
        'components': {'schemas': schemas},
        'externalDocs': {'url': ORIGIN + '/' + API_DOC_PATH},
    }
    guide = '''# PISKOR public project catalog

Read the studio's published project facts with `GET https://piskor.com.ua/project-catalog.json`.
The response is JSON with `version: 1` and a `projects` array. No credentials are required.

[OpenAPI 3.1 contract](https://piskor.com.ua/agent-api/openapi.json) · [API catalog](https://piskor.com.ua/.well-known/api-catalog)

## Read and filter

Fetch the complete document once and filter its `projects` array locally by `id`, `language`
(`uk` or `en`), `year` or text. The endpoint has no search, language or pagination parameters.
Both language entries describe the same project through their shared `id`; array order is not a contract.
Case and section URLs are relative to `https://piskor.com.ua`.

Each project contains `id`, `language`, `year`, `name`, `url`, `summary`, `label`, `facts` and
`sections`. Facts contain `label` and `value`; sections contain `title`, `url` and `text`.
These are the facts and implementation status published on the linked portfolio pages.
Use those pages as the source when presenting a project; do not infer missing information.

## Updates and scope

The JSON snapshot and this schema are regenerated during the site build. They do not provide
live building telemetry, a real-time inventory or a per-request database query. Respect HTTP
cache headers and check the latest published document when freshness matters.

This HTTP API only reads the catalog. It cannot create bookings, submit messages or change projects.
The website's `search_projects`, `get_project_details` and `get_contact_options` tools are separate
browser-side WebMCP tools: they require a compatible browser and are not HTTP, MCP-server or A2A
endpoints. The public catalog is an anonymous, read-only HTTPS resource.

[Portfolio browsing skill](https://piskor.com.ua/agent-skills/piskor-portfolio/SKILL.md)
'''
    documents = {API_CATALOG_PATH: json.dumps(linkset, ensure_ascii=False, separators=(',', ':')) + '\n',
                 OPENAPI_PATH: json.dumps(specification, ensure_ascii=False, separators=(',', ':')) + '\n',
                 API_DOC_PATH: guide}
    for relative, content in documents.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return API_PATHS
