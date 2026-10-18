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
