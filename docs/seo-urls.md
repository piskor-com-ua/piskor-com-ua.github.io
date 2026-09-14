# Titles and clean bilingual URLs

Local implementation, 2026-09-14. Not yet published.

| Route | Title |
| --- | --- |
| `/` | Архітектура та дизайн інтер’єру у Львові · PISKOR Architect |
| `/en/` | Architecture & Interior Design in Lviv · PISKOR Architect |
| `/portfolio/` | Портфоліо архітектури та дизайну інтер’єру · PISKOR Architect |
| `/en/portfolio/` | Architecture & Interior Design Portfolio · PISKOR Architect |
| `/portfolio/lviv-apartment/` | Дизайн квартири у Львові, 98 м² · PISKOR Architect |
| `/en/portfolio/lviv-apartment/` | Apartment Interior Design in Lviv, 98 m² · PISKOR Architect |

Actual title tags use a vertical bar before the brand. Titles describe the service, location and project rather than the design-concept status. The project title rounds 97.72 m² to 98 m²; the exact area remains in the content.

Homepage metadata lives in `concept/_data/home_seo.yml`. Project metadata is in front matter. The shared SEO include emits unique titles, descriptions, self-canonicals, reciprocal uk/en/x-default alternates and Open Graph/Twitter metadata. The language switch keeps metadata and the clean language URL synchronized. `/en/` now has its own generated HTML and English metadata without requiring JavaScript.

## Section links

- Homepage: `#design-process`, `#architecture-services`, `#portfolio`, `#our-approach`, `#contact`.
- Project, both languages: `#project-story`, `#client-brief`, `#space-planning`, `#custom-storage`, `#materials-and-lighting`, `#design-result`, `#contact`.
- Semantic anchors deliberately remain stable between languages. They identify sections, not separately indexable pages. Old fragment names are recognized on the new pages.
- Per the user's explicit request, old `/lviv-apartment.html` and `/lviv-apartment-en.html` addresses are removed, with no redirect. Previously shared links to those addresses will return 404 after publication.
- Jekyll still writes directory index.html files. Public navigation and canonical URLs use trailing-slash routes, not .html links. GitHub Pages can still serve explicit /index.html requests; this is not a separate recommended URL.

## Verification and limits

Build validation now checks nested routes and root-relative resources. `scripts/check-seo.py` runs with every build and verifies the four metadata/language pairs, canonical URLs, clean links and absence of the old project files. Browser checks verify titles, images, language switch plus reload, semantic/legacy fragments, portfolio navigation, lightbox and old-route 404s. All 26 gesture tests pass with updated section selectors.

Noindex remains by prior agreement. Titles and slugs do not guarantee rankings. Main homepage content is still rendered by the existing JavaScript runtime; pre-rendering that content is a separate enhancement, not part of this URL/title edit. No content or visual redesign is intended.

## Generated search resources

`concept/sitemap.xml` and `concept/robots.txt` are native Jekyll templates. No new gems are needed. The shared SEO include also generates JSON-LD Organization and WebSite entities, plus CreativeWork and BreadcrumbList for project pages, using only existing public business facts.

`indexing_enabled: false` in `_config.yml` is the current policy. All HTML emits exactly one `noindex,nofollow` tag. Robots allows fetching pages so crawlers can read noindex; it is not an access-control or model-training policy. Search services that ignore directives cannot be technically excluded by metadata alone.

While indexing is disabled, sitemap.xml is an empty URL set and robots.txt does not advertise it. On an approved switch to `indexing_enabled: true`, Jekyll automatically includes canonical pages with uk_url/en_url front matter and their language alternates. Set `sitemap: false` to exclude a page. No invented change frequencies, priorities or build-time lastmod timestamps are emitted; optional `last_modified_at` must describe a real content update.

The production build check deliberately fails if any HTML loses noindex. Enabling indexing later therefore requires both an explicit configuration change and review of the indexing guard, not just an environment-variable accident. A temporary, non-published build tested the enabled mode: four canonical URLs with reciprocal alternates and a Sitemap declaration. The regular local artifact remains noindex.

There is no universally required AI-only SEO file. llms.txt is not added as a substitute for normal crawlable HTML, canonical URLs and structured metadata; Google documents that it does not use it for generative search. Training-crawler permissions are a separate decision and are not changed here. Nothing has been submitted to Search Console, indexing APIs or AI services.

Additional sources:

- https://developers.google.com/search/docs/crawling-indexing/block-indexing
- https://developers.google.com/search/docs/fundamentals/ai-optimization-guide

Sources checked for this work:

Catalog extension: projects now live in `concept/_projects/`. Both language catalogs render automatically from the collection using the shared `portfolio-projects.html` sorter. Numeric project_year sorts newest first; unknown years sort last and are not invented. The same list feeds CollectionPage/ItemList JSON-LD. Project breadcrumbs now include the real portfolio catalog, and homepage features link to the full catalog. Jekyll sitemap generation combines pages with collection documents.

- https://developers.google.com/search/docs/appearance/title-link
- https://developers.google.com/search/docs/crawling-indexing/url-structure
- https://developers.google.com/search/docs/crawling-indexing/links-crawlable
