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
