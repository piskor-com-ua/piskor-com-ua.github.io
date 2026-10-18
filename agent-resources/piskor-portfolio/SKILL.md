---
name: piskor-portfolio
description: Find and compare published PISKOR architecture and interior cases in Ukrainian or English, inspect their documented scope, and retrieve public studio contact links.
---

# Browse PISKOR projects

Use this guide for a user's request about PISKOR's public portfolio. It describes read-only browsing; it does not authorize messages, bookings, analytics consent, or access to private project files.

## Find a case

Open the [Ukrainian portfolio](https://piskor.com.ua/portfolio/) or [English portfolio](https://piskor.com.ua/en/portfolio/). In a browser with WebMCP, discover the page's current tools and their input schemas before calling them:

- `search_projects` searches published case text and facts. Use `query`, an optional integer `year`, `language` (`uk` or `en`), and `limit` (up to 20). An empty result means no match in the published catalog, not that the studio has never done such work.
- `get_project_details` takes a `project_id` returned by search and an optional `language`. It returns published facts, section text, and direct section links.
- `get_contact_options` takes an empty object and reads public contact links from the current page. It does not call the phone number or send a message.

If WebMCP is unavailable, use the normal year and case links. The [public JSON catalog](https://piskor.com.ua/project-catalog.json) and [navigation guide](https://piskor.com.ua/llms.txt) provide the same published case references. The JSON catalog has `version: 1` and a `projects` array; each language has its own record, with `id`, `language`, `year`, `name`, `url`, `summary`, `label`, `facts`, and `sections`. Resolve relative case and section URLs against `https://piskor.com.ua`.

## Verify and present

Open relevant case sections before making a recommendation. Preserve the distinction between completed work, design proposals, and potential automation scenarios. Report only facts supported by the linked case; missing equipment, dates, or implementation details are unknown. Cite the case or section URL supporting a claim.

For a language switch, use the case's language link or the catalog record with the same `id` and the requested `language`. Do not construct a translated slug. Section links lead to the content; gallery controls support keyboard navigation and Escape.

When contacts are requested, return the public links from the page's contact section. Sending a message or making a call is a separate action requiring the user's instruction. This guide and its discovery manifest do not change the site's indexing directives or grant permission to republish project media.
