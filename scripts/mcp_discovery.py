"""Build runtime-only MCP discovery and data from a final Pages artifact.

Nothing is written to the artifact: discovery is activated with its matching Worker.
"""
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from agent_api import (API_CATALOG_MEDIA_TYPE, API_CATALOG_PATH, ORIGIN,
                       _validate_shape, catalog_schemas)

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / 'agent-resources/mcp-contract.json'
CARD_PATH = '/.well-known/mcp/server-card.json'
GUIDE_PATH = '/agent-api/mcp.md'
CARD_MEDIA_TYPE = 'application/mcp-server-card+json'
MCP_PUBLICATION_PATHS = (CARD_PATH, GUIDE_PATH, '/' + API_CATALOG_PATH)
CARD_SCHEMA_URI = 'https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json'
VOID = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                  'link', 'meta', 'param', 'source', 'track', 'wbr'))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'


class ContactParser(HTMLParser):
    """Only public anchor text and hrefs inside the final HTML #contact subtree."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.contact_depth = None
        self.contact_count = 0
        self.anchor = None
        self.contacts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in VOID:
            self.stack.append(tag)
        if attrs.get('id') == 'contact':
            self.contact_count += 1
            self.contact_depth = len(self.stack)
        if self.contact_depth is not None and tag == 'a' and 'href' in attrs:
            if self.anchor is not None:
                raise ValueError('Nested contact anchors')
            self.anchor = {'url': attrs['href'], 'text': []}

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor is not None:
            name = ' '.join(''.join(self.anchor['text']).replace('↗', '').split())
            if not name:
                raise ValueError('Contact link has no public name')
            self.contacts.append({'name': name, 'url': self.anchor['url']})
            self.anchor = None
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            if self.contact_depth is not None and index < self.contact_depth:
                self.contact_depth = None
            self.stack = self.stack[:index]

    def handle_data(self, text):
        if self.anchor is not None:
            self.anchor['text'].append(text)


def _contacts(path):
    parser = ContactParser()
    parser.feed(path.read_text(encoding='utf-8'))
    parser.close()
    if (parser.contact_count != 1 or parser.anchor is not None
            or parser.contact_depth is not None or not parser.contacts):
        raise ValueError('Final homepage must contain one complete #contact with public links')
    seen = set()
    for contact in parser.contacts:
        href = contact['url']
        parsed = urlsplit(href)
        valid = False
        if parsed.scheme == 'tel':
            valid = re.fullmatch(r'tel:\+[1-9][0-9]{6,14}', href) is not None
        elif parsed.scheme == 'https':
            valid = (parsed.netloc == 'wa.me' and not parsed.query and not parsed.fragment
                     and re.fullmatch(r'/[1-9][0-9]{6,14}', parsed.path) is not None)
        elif parsed.scheme == 'viber':
            query = parse_qs(parsed.query, strict_parsing=True)
            valid = (parsed.netloc == 'chat' and not parsed.path and not parsed.fragment
                     and set(query) == {'number'} and len(query['number']) == 1
                     and re.fullmatch(r'\+[1-9][0-9]{6,14}', query['number'][0]) is not None)
        if not valid or href in seen:
            raise ValueError('Invalid or duplicate public contact link: ' + href)
        seen.add(href)
    return parser.contacts


def _guide(contract, projects, revision):
    languages = {lang: sum(p['language'] == lang for p in projects) for lang in ('uk', 'en')}
    tools = '\n\n'.join('### `' + tool['name'] + '`\n\n' + tool['description'] +
                           '\n\n```json\n' + json.dumps(tool['inputSchema'], ensure_ascii=False,
                                                         sort_keys=True, indent=2) + '\n```'
                           for tool in contract['tools'])
    return f'''# PISKOR public read-only HTTP MCP

Connect to `{contract['endpoint']}` using Streamable HTTP, JSON-only, stateless POST.
No credentials, accounts or OAuth are required. This service reads published portfolio
facts and contact links; it cannot send messages, make bookings or change any data.

[Server Card]({contract['serverCard']}) · [API catalog]({ORIGIN}/{API_CATALOG_PATH})

## Connection and lifecycle

Supported protocol versions: {', '.join('`' + v + '`' for v in contract['protocolVersions'])}.
For `2026-07-28`, use `server/discover` for live identity and supported versions, and
per-request protocol metadata (`_meta`) and the corresponding MCP HTTP metadata headers.
For `2025-11-25`, use `initialize`, then `notifications/initialized`, then `tools/list`
and `tools/call` with `MCP-Protocol-Version: 2025-11-25`. The legacy initialization
sequence and current runtime discovery are separate protocol flows.
Send `Content-Type: application/json` and `Accept: application/json, text/event-stream`.
Responses are JSON; the server does not create sessions or persistent GET streams.
GET, HEAD and DELETE on `/mcp` return 405. There is no endpoint query string.
Requests are limited to 16 KiB. Unknown methods, versions and invalid parameters fail.
Native clients may omit Origin; a present Origin must be `{ORIGIN}`.

Use runtime `tools/list` for the authoritative tool definitions. The Server Card
contains identity, transport and versions; it intentionally omits primitive definitions
and negotiated capabilities, following the pinned Server Card extension schema.

## Published snapshot and language

This bundle contains {len(projects)} language-specific project records:
{languages['uk']} Ukrainian (`uk`) and {languages['en']} English (`en`). Shared project
IDs link the language variants. Data comes only from this release's final public
`project-catalog.json` and homepage `#contact` links; no private files or request-time
external fetches are used. Case and section URLs are relative to `{ORIGIN}`.
The matching source revision is `{revision}`; HTTP responses expose it in
`X-Piskor-MCP-Version`. Data changes require a new matching site/Worker release.

The default language is Ukrainian (`uk`), regardless of Accept-Language. Pass
`language: "en"` explicitly for English. `get_project_details` returns the complete
published record, including facts and all section titles, URLs and full section text.
Preserve published wording about proposals, realization and automation; do not infer
installed equipment or missing facts. No private address is added by this service.

## Search behavior and bounds

`search_projects` accepts a query up to 200 characters, optional year 1900–2100,
`uk`/`en` language, and a limit of 1–20 (default 10). It normalizes case and whitespace,
splits the query into words, and requires every word to occur as a substring of the
combined published name, summary, label, fact values and full section texts.
An omitted or empty query lists records in the chosen language; year is an exact filter.
The result gives the total matching count and up to the requested limit of summaries.
Use a returned ID with `get_project_details`; its ID is at most 100 lowercase letters,
digits or hyphens. An unknown ID/language pair fails. Unknown argument properties fail.
`get_contact_options` takes an empty object and returns published names and phone,
WhatsApp and Viber URLs. Reading a link never calls, opens a messenger or sends a message.

## Current tool input schemas

{tools}

## Delivery and acceptance limits

MCP and runtime discovery responses use `Cache-Control: no-store` and retain
`noindex,nofollow` and the owner's Content Signals policy. Server Card metadata is
advisory: verify its claims against the live endpoint. Browser-native WebMCP tools
remain a separate compatible-browser integration; the HTTP endpoint works without
browser WebMCP support. The static GET catalog remains available with its existing
[OpenAPI contract]({ORIGIN}/agent-api/openapi.json).

A valid card does not prove protocol or tool execution, Agentic Browsing 5/5, AI-search
visibility, or performance targets. Public runtime/client checks and page-specific
measurements are separate acceptance evidence. MCP does not establish FCP, LCP or
Speed Index below 1000 ms on any page.
'''


def _artifact_file(site, relative):
    target = site / relative
    try:
        target.resolve().relative_to(site.resolve())
    except ValueError as error:
        raise ValueError('MCP source escapes the final artifact: ' + relative) from error
    return target


def generate_mcp_data(site, revision):
    """Return deterministic Worker data; never mutate or publish the input artifact."""
    site = Path(site)
    if not _artifact_file(site, '.nojekyll').is_file():
        raise ValueError('MCP data requires a final generated Pages artifact')
    if not isinstance(revision, str) or re.fullmatch(r'[0-9a-f]{40}', revision) is None:
        raise ValueError('MCP revision must be a full lowercase git SHA')
    contract = json.loads(CONTRACT_PATH.read_text(encoding='utf-8'))
    catalog = json.loads(_artifact_file(site, 'project-catalog.json').read_text(encoding='utf-8'))
    schemas = catalog_schemas()
    _validate_shape(catalog, schemas['ProjectCatalog'], schemas)
    contacts = _contacts(_artifact_file(site, 'index.html'))
    if _artifact_file(site, 'en/index.html').is_file():
        english = _contacts(_artifact_file(site, 'en/index.html'))
        if [c['url'] for c in english] != [c['url'] for c in contacts]:
            raise ValueError('UA/EN public contact URLs differ')
    identity = contract['serverInfo']
    if re.fullmatch(r'[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+', identity['name']) is None:
        raise ValueError('MCP serverInfo.name must match the reverse-DNS Server Card identity')
    card = {'$schema': CARD_SCHEMA_URI, 'name': identity['name'],
            'title': identity['title'], 'version': identity['version'] + '+' + revision,
            'description': 'Read published PISKOR portfolio facts and public contact links.',
            'websiteUrl': ORIGIN + GUIDE_PATH,
            'remotes': [{'type': 'streamable-http', 'url': contract['endpoint'],
                         'supportedProtocolVersions': contract['protocolVersions']}]}
    linkset = copy.deepcopy(json.loads(_artifact_file(site, API_CATALOG_PATH).read_text(encoding='utf-8')))
    listing = next(entry for entry in linkset['linkset']
                   if entry.get('anchor') == ORIGIN + '/' + API_CATALOG_PATH)
    listing['item'].append({'href': contract['endpoint'], 'type': 'application/json'})
    linkset['linkset'].append({'anchor': contract['endpoint'],
                              'service-desc': [{'href': contract['serverCard'], 'type': CARD_MEDIA_TYPE}],
                              'service-doc': [{'href': ORIGIN + GUIDE_PATH, 'type': 'text/markdown'}]})
    publications = {
        CARD_PATH: {'body': _json(card), 'contentType': CARD_MEDIA_TYPE},
        GUIDE_PATH: {'body': _guide(contract, catalog['projects'], revision),
                     'contentType': 'text/markdown; charset=utf-8'},
        '/' + API_CATALOG_PATH: {'body': _json(linkset), 'contentType': API_CATALOG_MEDIA_TYPE},
    }
    return {'contract': contract, 'projects': catalog['projects'], 'contacts': contacts,
            'publications': publications}
