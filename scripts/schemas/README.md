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
