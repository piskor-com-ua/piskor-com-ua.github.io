# MCP discovery and final-artifact data

`scripts/mcp_discovery.py` exposes `generate_mcp_data(site, revision)` for the Worker
bundle builder. It returns `contract`, `projects`, `contacts` and `publications`;
`MCP_PUBLICATION_PATHS` lists the exact runtime resources. Each publication has a
UTF-8 `body` string and `contentType`. The function writes no files, so no MCP
advertisement can reach Pages before the actual server is activated.

The generated Pages artifact must contain `.nojekyll`, a valid
`project-catalog.json`, a homepage with one `#contact` subtree, and the existing
RFC 9727 `/.well-known/api-catalog`. The generator reuses the catalog schema validator
from `agent_api.py`. Public contact names and phone/WhatsApp/Viber hrefs come only
from that homepage; unrelated anchors outside `#contact` are ignored. Unsupported,
malformed or duplicate contact URLs fail the bundle build. If `en/index.html` is
present, its contact URLs must match the Ukrainian homepage in the same order;
localized names may differ. A full lowercase git SHA is required.

The static `agent-resources/mcp-contract.json` owns identity, endpoint, supported
protocol versions and tool schemas. The Server Card uses a reverse-DNS identity
matching runtime discovery and version `<contract version>+<full source SHA>`.
The guide includes current record counts, tool input schemas and published-data
semantics; the runtime API-catalog overlay preserves the existing static GET
catalog entries. The guide distinguishes current `server/discover` from legacy
`initialize` and records Ukrainian defaults, full section text, search bounds,
anonymous access and the absence of message actions or sessions.

The card follows the current upstream Server Card v1 schema, which excludes
primitive definitions and negotiated capabilities. The tools are documented in the
guide and listed by the actual server. See the pinned primary-source revisions,
SHA-256 values, schema-reference details and license in
[schema provenance](../scripts/schemas/README.md#mcp-server-card-extension-v1).
The agreed `/.well-known/mcp/server-card.json` URL is a local compatibility choice;
the current extension recommends `<streamable-http-url>/server-card` and permits
other locations. The RFC 9727 overlay provides an explicit link to this card.

Only the matching Worker bundle serves these resources, using GET/HEAD and the
exact MIME types, `no-store`, robots directives, the owner's Content Signals and
`X-Piskor-MCP-Version`. A present card alone proves neither a working server nor
Agentic Browsing scores. Runtime/client tests, scanner results and performance
measurements remain separate release acceptance evidence. No local schema result
establishes FCP, LCP or Speed Index below 1000 ms.
