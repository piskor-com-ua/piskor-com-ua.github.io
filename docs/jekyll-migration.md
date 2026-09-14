# Jekyll migration

Prepared locally on 2026-09-14 from published commit `94bb2a352604688b8928eb851245f027877a10e2`. Supersedes the earlier no-generator decision; preserves the approved site.

## Compatibility choice

The official Pages version matrix lists Jekyll 3.10.0 and github-pages 232 for the legacy builder. The existing repository uses GitHub Actions, where the official Jekyll documentation supports choosing the current Jekyll release. RubyGems and Jekyll documentation confirmed 4.4.1 as current during migration.

- https://pages.github.com/versions.json
- https://jekyllrb.com/docs/continuous-integration/github-actions/
- https://rubygems.org/gems/jekyll

Use Jekyll 4.4.1, not the github-pages meta-gem. Ruby is pinned to the locally verified 4.0.1; Bundler 4.0.20 and all resolved gems are locked. Linux x86_64 and macOS ARM platforms are included. Existing Actions are preserved; ruby/setup-ruby is pinned to a verified commit.

## Gems

Resolved compatible updates include sass-embedded 1.104.1, google-protobuf 4.36.1, addressable 2.9.0, i18n 1.15.2, json 2.21.2, concurrent-ruby 1.3.8 and ffi 1.17.4. `bundle outdated --strict` reports no compatible updates remaining.

Unrestricted major updates exist for json, Liquid, Rouge, terminal-table and unicode-display_width; these exceed constraints in the Jekyll dependency graph. Do not override those constraints. Daily Dependabot PRs cover Bundler as well as Actions. This compatibility check is not a comprehensive vulnerability audit.

## Preservation contract

- Page filenames and relative URLs remain unchanged. After the separately approved repository rename, the Pages host serves the site at its root and baseurl is empty.
- Shared document layout supplies doctype and language; each page has explicit front matter and permalink.
- CSS, JavaScript, images and fonts are unchanged. Client-side UA/EN switching, scenes, gestures, automation and gallery remain in the existing runtime.
- The Python command now invokes Jekyll rather than copying the site. It retains resource hashes and validates that private notes, source PNGs, JSON provenance and templates do not reach the artifact.
- No themes, SEO plugins, sitemap, feed or new markup are injected. Existing indexing restrictions remain.

## Local acceptance

`python3 scripts/build-site.py` passes: 70 entries, including 65 files. Comparing the complete pre-migration and Jekyll artifacts passes with `python3 scripts/check-migration-parity.py tmp/jekyll-baseline _site`. All file paths and contents match, normalizing only the newline between closing body/html tags in the two portfolio pages. No page content or runtime resource changes are hidden by that comparison.

All 26 existing gesture regression checks pass against Jekyll output. These are browser simulations, not physical Mac trackpad certification. The dependency lock resolves a Linux platform, but local execution is on macOS; GitHub Linux CI must still be run before merging.

Full-page screenshots compare the old and new artifacts for all three pages at 1440 px and 390 px, with reduced motion to stabilize capture. Five pairs are pixel-identical; desktop English portfolio differs by at most 1/255 per color channel (maximum mean channel difference 0.00021). Mobile comparisons use fresh browser contexts to avoid larger cached srcset images from a preceding desktop capture. Screenshot artifacts are local under `output/playwright/jekyll-*`; they are not published. Regular-motion gesture tests remain separate from reduced-motion visual comparisons. `bundle exec jekyll doctor` also passes.

The user approved PR creation, merge and publication on 2026-09-14 after the repository rename. Publication must wait for successful GitHub Linux CI; the Actions run and PR provide the final deployment record.
