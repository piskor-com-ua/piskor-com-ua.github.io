# ARD schema snapshot

`ard-entry.schema.json` is the unmodified upstream schema from
`ards-project/ard-spec`, commit `49eb4df6f3841ccecc5c31d5175117337b568bdf`,
retrieved on 2026-10-18:

https://github.com/ards-project/ard-spec/blob/49eb4df6f3841ccecc5c31d5175117337b568bdf/spec/schemas/ard-entry.schema.json

Its Apache 2.0 license is preserved in `ARD-LICENSE`. These files are build-only;
they are not copied to the public artifact. `npm run test:discovery` validates
the generated manifest against `ArdManifest` and separately runs the conformance
validator shipped with the pinned Lighthouse version. Update the snapshot and
both checks together when adopting a new proposal revision.

## Agent Skills discovery draft 0.2.0

`agent-skills-discovery.schema.json` is a locally authored validation of the
requirements in Cloudflare's **draft**, not a downloaded official JSON Schema:

https://github.com/cloudflare/agent-skills-discovery-rfc/blob/1bd1167983fa5ac9cd47987710c525308eda1a98/README.md

Checked on 2026-10-18, RFC sections Discovery Index, Integrity and Verification,
and HTTP Considerations. The RFC's `$schema` URL is an opaque version identifier
and need not resolve to a JSON Schema. Its upstream repository contains no schema
file. This local schema therefore has its own `urn:piskor:` identity. Unknown
fields remain permitted, as required by the RFC's client guidance. Format
constraints for skill names/descriptions also follow
https://agentskills.io/specification .

The generated `/.well-known/agent-skills/index.json` points to the existing
single-file browsing skill and hashes its exact published bytes. It supplements
both ARD paths, does not publish an incompatible legacy 0.1 index, and does not
advertise remote MCP, authentication or commerce services. The checker verifies
the local schema, real URL, frontmatter metadata and SHA-256 digest separately.
This schema and provenance remain build-only.

## MCP Server Card extension v1

`mcp-server-card.schema.json` is the **unmodified upstream generated JSON Schema**
from `modelcontextprotocol/experimental-ext-server-card`, current main revision
`526201bbc80231daa40ffcdecfc9da4e54e5dc93`, retrieved on 2026-10-19:

https://github.com/modelcontextprotocol/experimental-ext-server-card/blob/526201bbc80231daa40ffcdecfc9da4e54e5dc93/schema.json

SHA-256: `2c772b51edb367f154771d84ddbae87ddba00a624422c8e46f218a9ac03bf042`.
The complete schema document contains `$defs`; validate a card against its
`#/$defs/ServerCard`, not the unconstrained document root. The upstream Apache 2.0
license is preserved in `MCP-SERVER-CARD-LICENSE`. Both files are build-only.

The primary charter was checked at `modelcontextprotocol/modelcontextprotocol`
main revision `1155ca460e5097019f32769b38dcba194432e2fb`:

https://github.com/modelcontextprotocol/modelcontextprotocol/blob/1155ca460e5097019f32769b38dcba194432e2fb/seps/2127-mcp-server-cards.md

SEP-2127 is **Final**, merged on 2026-10-06; the former SEP-1649 description and
old card examples do not define the current format. The charter delegates the
normative wire format to the extension repository. The exact `schema.ts` source
SHA-256 is `f8321e0ada31f32e372bb715c27f917229d02675d52b4fa9a14909df5905f2e9`.
The pinned discovery specification is:

https://github.com/modelcontextprotocol/experimental-ext-server-card/blob/526201bbc80231daa40ffcdecfc9da4e54e5dc93/docs/discovery.md

Its SHA-256 is `633dacfe5bcdbb3ed2f177be7dd7f9943ed2484a5fdd13bd2b742f43a14c2786`.
It prescribes `application/mcp-server-card+json`, reverse-DNS server identity,
remote transport URLs and per-remote `supportedProtocolVersions`. Cards omit
primitive definitions and negotiated capabilities; these come from live protocol
operations. Do not reintroduce tools/capabilities through vendor `_meta`.

The current extension permits arbitrary unreserved card locations and recommends
`<streamable-http-url>/server-card`. PISKOR retains its explicitly agreed
`/.well-known/mcp/server-card.json` path, linked from the runtime RFC 9727 API
catalog and guide, for the separately verified scanner's lookup. This path is a
local compatibility decision, not the extension's recommended default. The existing
AI catalog remains its own versioned contract; no incompatible entry is fabricated.
The metadata response uses public, credential-free CORS as required by the pinned
extension; `/mcp` retains its own stricter Origin policy. PISKOR's explicit
`no-store` freshness policy is stricter than the extension's cache recommendation.

`python3 -m unittest discover -s scripts -p test_mcp_discovery.py` verifies the
pinned bytes and generated card schema, exact transport/version agreement,
source-only data, RFC linkset preservation, deterministic output and a byte-for-byte
unchanged Pages artifact. These checks do not prove live MCP or scanner acceptance.
