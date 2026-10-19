# Публічний read-only HTTP MCP PISKOR

## Узгоджений контракт реалізації

Авторизовано замовником 19.10.2026. Один PR від main `1f9df5cf936059c95291fba1f2c888e2a806eb74`; активація Cloudflare тільки після мерджу, успішного Pages і перевірки відповідного CI artifact.

- Endpoint: `POST https://piskor.com.ua/mcp`, без query, anonymous public read-only. GET/HEAD/DELETE не відкривають stream/session і повертають 405; жодних write, повідомлень, приватних файлів, OAuth або облікових записів. OPTIONS лише коректний same-origin preflight.
- Версії: актуальна `2026-07-28` (server/discover, per-request _meta і відповідні metadata headers, resultType) та сумісність `2025-11-25` через initialize/initialized, JSON-only stateless transport. Не заявляти підтримку інших версій. Невідомі методи/версії та malformed requests повертають protocol/HTTP errors згідно версії.
- Три інструменти з `agent-resources/mcp-contract.json`: search_projects, get_project_details, get_contact_options. Параметри та пошукова семантика з browser WebMCP, включно з section texts; default language uk, explicit en. Жодної залежності від Accept-Language.
- Дані — тільки фінальний artifact: project-catalog.json і публічні contact links головної. Під час запиту немає fetch до чужих URL, source files, origin catalog, credentials, KV/R2 або фонового оновлення. Дані й server version/revision відтворювані в matching Worker bundle; source fingerprint включено в manifest.
- Runtime handler `handleMcp(request, data)` у cloudflare/mcp-server.mjs повертає Response для /mcp, його query negatives і точних runtime-discovery URL; null для всього іншого. Викликається перед Markdown negotiation в існуючому Worker. HTML і asset passthrough залишаються такими самими.
- Discovery generation: scripts/mcp_discovery.py, `generate_mcp_data(site, revision)`, повертає `{contract, projects, contacts, publications}`. publications mapping exact path → `{body, contentType}`. Server Card тільки `/.well-known/mcp/server-card.json`, MCP guide `/agent-api/mcp.md`, runtime overlay RFC9727 `/.well-known/api-catalog` із збереженням нинішніх catalog entries. Runtime serving забезпечує атомарну активацію discovery із самим сервером; ці нові publications не копіюються до Pages.
- Server Card описує готовий Streamable HTTP endpoint, identity та protocol versions за актуальною upstream-схемою. Чинна Final extension не допускає tools/capabilities у картці: їх публікують реальні tools/list і guide. MIME картки application/mcp-server-card+json; public metadata CORS * тільки для картки, без credentials. Власні runtime discovery resources GET/HEAD, правильний MIME, no-store, noindex,nofollow, Content-Signal і X-Piskor-MCP-Version=full git SHA.
- /mcp: обмеження body 16 KiB і читання stream з лімітом, bounded parameters/results; no-store; без логів, сесій, credentials і платних bindings. Invalid present Origin →403, absent Origin дозволено для native clients, URL origin повинен бути production. Не додавати wildcard credentialed CORS. Fail-open на рівні CF захищає HTML, але quota exhaustion не є успішним MCP: перевіряти 404/5xx як failures.

## Rate limiting та активація

Вбудований Worker Rate Limiting binding `MCP_RATE_LIMITER` використовує namespace `1782407601`, `limit:120`, `period:60` та фіксований ключ `piskor-mcp:tools-call:v1`. Це спільний бюджет tool invocations у кожній Cloudflare location, без ідентифікаторів відвідувачів/IP, KV/R2 чи додаткових runtime credentials. Він не є глобальним лічильником, гарантією захисту від розподіленого навантаження або заміною загальної квоти Workers. Перевищення →429 і Retry-After60; відсутній/несправний binding →503. Discovery, initialize, Markdown, HTML і assets не витрачають цей бюджет.

Зміна binding входить у той самий PR і застосовується атомарно з версією Worker тільки після мерджу та Pages. Не підвищувати тариф або ліміти витрат. Після активації зберегти readback binding, версію й реальні успішні tools/call; denied/503 гілки перевіряються локально з явними test doubles. Не видавати їх за production saturation test. [Офіційний runtime API](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/).

## Паралельна робота та приймання

Server owner: runtime, інтеграція у наявний Worker, deterministic matching bundle й його manifest. Discovery owner: generate_mcp_data, правдивий Server Card/schema provenance, MCP guide й runtime API catalog, власні Python-тести. QA owner: незалежні transport/protocol/data negative fixtures, реальний сумісний клієнт, parity UA/EN/section search, WebMCP single-registration і retry. Integration owner: P1 live release gate, CI, maintenance docs, artifact/publication verification.

Інтеграція послідовно після контракту: усі тести/build/schema → незалежний GPT-6.1 review → один PR/required CI → merge/Pages → matching Worker100% → protocol/client/API/discovery/HTTP/HTML/native WebMCP/is it agent ready → PSI10URL both modes. Зберігати невдалі speed measurements і коректні N/A; нинішній mobile LCP target не досягнутий, новий MCP сам по собі його не виправляє.

Primary specs: [MCP2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http), [discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover), [MCP2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [optional authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization). Server Card proposal needs pinned provenance; its presence is not proof of working tools.

## Відкат і підтримка

Перед активацією зберегти поточний deployment/version ID і точну конфігурацію routes/privacy. При MCP-регресії повернути попередню перевірену версію Worker, зберігши Markdown і звичайний HTML; не вмикати старі експериментальні rewrite rules навмання. Повторити byte/language/version checks. Контент Worker повинен відповідати обраній публікації Pages. Відкат версії не слід вважати автоматичним видаленням runtime variables чи всіх binding/configuration settings: перечитати фактичний стан.
