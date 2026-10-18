# PISKOR Architect

Jekyll builds the bilingual site from shared templates, approved case content and source media.

## Local preview

Use the Ruby version in `.ruby-version` and Bundler from `Gemfile.lock`.

```sh
bundle install
python3 -m pip install -r requirements-build.txt
python3 scripts/build-site.py
node --test scripts/test-agent-tools.js
python3 -m http.server 4173 --bind 127.0.0.1 --directory _site
```

Open http://127.0.0.1:4173/. Rebuild after source changes. Serve `_site`, not `concept`: the latter now contains Jekyll front matter and templates.

## Structure

- `_config.yml`: Jekyll source, destination, Pages root URL and publication exclusions.
- `concept/_layouts/document.html`: shared HTML document layout.
- `concept/*.html`: page content, language and explicit existing permalinks.
- `concept/*.css`, `concept/*.js`, `concept/assets/`: shared visual styles, browser interactions and approved source assets.
- `scripts/build-site.py`: runs build regression tests and locked Jekyll, prepares responsive cards and agent discovery, optimizes generated media, versions resources and validates the public artifact. It reports the actual publication file count.
- `scripts/optimize_assets.py`: excludes unreferenced media from `_site` and rewrites static URLs to share byte-identical WebP/PNG files. Covers `srcset`, gallery `data-full`, posters, structured data and literal CSS/JS asset URLs; keeps font licenses and never deletes source assets. New media URLs must be explicit (not assembled dynamically from filename fragments) so build-time reference checks can find them. Every build recreates the artifact from the originals.
- `.github/workflows/site.yml`: installs locked gems, validates and publishes only from `main`.

Jekyll 4.4.1 is built through GitHub Actions and hosted by GitHub Pages. Do not switch Pages to the legacy branch builder: its `github-pages` gem pins Jekyll 3.10.0. `.nojekyll` in the completed artifact prevents a second build; it does not bypass our Jekyll build.

## Dependency updates

Dependabot checks gems daily. Review updates in PRs; CI uses `Gemfile.lock`, including checksums and macOS/Linux platforms. Run `bundle update`, `bundle outdated --strict`, then the build and browser checks. New major versions outside Jekyll compatibility constraints are not forced.

The preview remains `noindex,nofollow`. Migration does not authorize enabling indexing, changing domains, merging or deploying.

See [migration evidence](docs/jekyll-migration.md).

## Search metadata and URLs

Public routes include `/`, `/en/`, the portfolio catalog, individual project pages and year archives such as `/portfolio/2023/`, with matching English routes under `/en/`. Year archives are direct clean URLs and are intentionally not placed in the main navigation. Old project `.html` URLs are intentionally removed. Jekyll generates localized metadata, canonical/hreflang links, JSON-LD, robots.txt and sitemap.xml. See [SEO configuration and indexing safeguards](docs/seo-urls.md). Indexing remains disabled; the normal build enforces noindex on every page.

## Adding a portfolio project

Follow the mandatory [portfolio project rules](docs/portfolio-project-rules.md) and [AGENTS.md](AGENTS.md) for source review, area calculation, evidence-based automation, image selection, bilingual SEO, visual QA and publication consent. This section only describes the repository wiring.

Add Ukrainian and English HTML documents to `concept/_projects/` using the existing apartment documents as templates. Keep a shared `project_id` and source-confirmed numeric `project_year` in both translations; use a PDF creation year as a proxy only when the user explicitly approves it. Include that year in every project permalink, for example `/portfolio/2025/project-slug/`, and set reciprocal `uk_url`/`en_url` values accordingly. Set the language, explicit clean permalink, SEO title/description, card_title, card_summary, cover and cover_alt. Images must use published assets. Set `published: false` on unfinished documents.

Both catalogs and their structured ItemList populate automatically from the localized collection. Projects sort by year descending; documents with a missing project_year appear last as a technical fallback, not as permission to publish an incomplete case. The sitemap includes collection documents automatically when indexing is eventually approved. The curated homepage feature card remains separate from the complete catalog.

## Performance and agent maintenance

Follow [the mandatory maintenance contract](docs/performance-agentic-maintenance.md) for all functionality and content changes. The build prepares responsive cards, corrects image dimensions, combines catalog styles from shared sources, generates project-catalog.json and llms.txt from rendered cases, and versions media/fonts before CSS/JS. Original source media remain untouched. WebMCP tools read public facts when a supported API is present; ordinary browsers do not fetch the agent catalog. Current ARD and legacy Lighthouse discovery manifests reference the public portfolio browsing skill. After building, run `npm run test:agent` and `npm run test:discovery` to validate the tools and both discovery contracts. Configure a real first-party WebMCP token in `_config.yml` only after Chrome Origin Trial registration; an empty value leaves the trial inactive. Cloudflare changes follow merge and verified Pages deployment; indexing remains a separate approval.

The build also generates WOFF2 subsets from rendered and dynamic text, inlines the shared catalog styles and runs the existing consent controller at the start of body. Edit the original CSS/JS and fonts, never generated subsets or inline copies. Original font URLs remain available for cached pages. FontTools and Brotli versions are pinned in requirements-build.txt.

For compressed local comparisons, serve each built artifact with python3 scripts/serve-benchmark.py ARTIFACT --port PORT, then run node scripts/benchmark-lighthouse.cjs BASELINE_URL CANDIDATE_URL --runs 5 --modes mobile --output output/speed-index-benchmark. Retain the full range and distinguish these local results from production PSI.

For the full browser matrix, run npm ci, npx playwright install chromium, then npm run test:browser. CI runs this matrix on every PR and saves screenshots plus the route/viewport results as browser-verification. See [implementation evidence and benchmark method](docs/performance-agentic-evidence.md).
