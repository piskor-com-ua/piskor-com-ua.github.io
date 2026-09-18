# PISKOR Architect

Jekyll builds the approved bilingual site without changing its browser-side design or interactions.

## Local preview

Use the Ruby version in `.ruby-version` and Bundler from `Gemfile.lock`.

```sh
bundle install
python3 scripts/build-site.py
python3 -m http.server 4173 --bind 127.0.0.1 --directory _site
```

Open http://127.0.0.1:4173/. Rebuild after source changes. Serve `_site`, not `concept`: the latter now contains Jekyll front matter and templates.

## Structure

- `_config.yml`: Jekyll source, destination, Pages root URL and publication exclusions.
- `concept/_layouts/document.html`: shared HTML document layout.
- `concept/*.html`: page content, language and explicit existing permalinks.
- `concept/*.css`, `concept/*.js`, `concept/assets/`: unchanged design and interactive runtime.
- `scripts/build-site.py`: runs locked Jekyll, fingerprints CSS/JS and validates the public artifact.
- `.github/workflows/site.yml`: installs locked gems, validates and publishes only from `main`.

Jekyll 4.4.1 is built through GitHub Actions and hosted by GitHub Pages. Do not switch Pages to the legacy branch builder: its `github-pages` gem pins Jekyll 3.10.0. `.nojekyll` in the completed artifact prevents a second build; it does not bypass our Jekyll build.

## Dependency updates

Dependabot checks gems daily. Review updates in PRs; CI uses `Gemfile.lock`, including checksums and macOS/Linux platforms. Run `bundle update`, `bundle outdated --strict`, then the build and browser checks. New major versions outside Jekyll compatibility constraints are not forced.

The preview remains `noindex,nofollow`. Migration does not authorize enabling indexing, changing domains, merging or deploying.

See [migration evidence](docs/jekyll-migration.md).

## Search metadata and URLs

Public routes include `/`, `/en/`, the portfolio catalog, individual project pages and year archives such as `/portfolio/2023/`, with matching English routes under `/en/`. Year archives are direct clean URLs and are intentionally not placed in the main navigation. Old project `.html` URLs are intentionally removed. Jekyll generates localized metadata, canonical/hreflang links, JSON-LD, robots.txt and sitemap.xml. See [SEO configuration and indexing safeguards](docs/seo-urls.md). Indexing remains disabled; the normal build enforces noindex on every page.

## Adding a portfolio project

Add Ukrainian and English HTML documents to `concept/_projects/` using the existing apartment documents as templates. Keep a shared `project_id` and numeric `project_year` (the year the project was made, not its upload date) in both translations. Include that year in every project permalink, for example `/portfolio/2025/project-slug/`, and set reciprocal `uk_url`/`en_url` values accordingly. Set the language, explicit clean permalink, SEO title/description, card_title, card_summary, cover and cover_alt. Images must use published assets. Set `published: false` on unfinished documents.

Both catalogs and their structured ItemList populate automatically from the localized collection. Projects sort by year descending; documents with a missing project_year appear last without a displayed year. The apartment year is awaiting user confirmation. The sitemap includes collection documents automatically when indexing is eventually approved. The curated homepage feature card remains separate from the complete catalog.
