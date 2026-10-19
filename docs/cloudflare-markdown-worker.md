# Власна доставка Markdown через Worker

Це план власної реалізації, обраної замовником 19.10.2026 після невдалих bounded-тестів із PR #55. Він доповнює [базову конфігурацію](cloudflare-agent-delivery.md) й замінює припущення, що для подальшого дослідження достатньо лише Transform Rules. Стан застосування фіксується окремими післярелізними доказами; наявність цього документа не означає активного Worker або успішного isitagentready.

## Публічний HTTP MCP у тому самому Worker

На доручення замовника від 19.10.2026 цей самий bundle також містить [публічний read-only HTTP MCP](public-http-mcp.md). Точний `/mcp` і три runtime discovery resources обробляються перед Markdown negotiation; решта правил Markdown/HTML/assets залишаються такими самими. MCP-дані, Server Card і runtime API catalog вбудовуються з matching Pages artifact. Discovery активується атомарно з сервером, а не як окрема статична реклама у Pages.

Єдиний новий binding — вбудований `MCP_RATE_LIMITER` із `cloudflare/wrangler.jsonc`, без KV/R2, секретів чи платного upgrade. Він потрібен тільки для tools/call; outage повертає503, перевищення429. Після merge/Pages у versions upload передавати перевірений CI entrypoint і конфігурацію з binding; не запускати triggers deploy, не змінювати routes/TTL/logs/preview. Перед activation перевірити bundle+configuration hashes, після — binding/версію та реальні виклики. Саме `--keep-vars` не замінює конфігурацію binding.

## Зміст і контракт

`scripts/build_markdown_worker.py` збирає окремий `output/markdown-worker/worker.mjs` з фінального Pages-артефакту. Він вбудовує вже згенеровані публічні Markdown та routing table; не читає приватні джерела, не конвертує HTML під час запиту, не потребує KV/R2, API-токена чи платного Markdown for Agents. Генератор Worker не переписує переданий Pages-артефакт; окремий профіль HTML-доставки описано нижче.

Відомий маршрут, GET/HEAD і точне значення Accept `text/markdown` отримують HTTP 200 зі справжніми байтами відповідного Markdown. Прямі відомі Markdown URL також працюють. HEAD має порожнє тіло. Markdown містить `Content-Type: text/markdown; charset=utf-8`, `Vary: Accept`, `Cache-Control: no-store`, чинні чотири discovery Link, `X-Robots-Tag: noindex, nofollow`, `Content-Signal: ai-input=yes, ai-train=no, search=yes` і версію bundle в `X-Piskor-Markdown-Version`.

Це обмежена negotiation, а не повний HTTP Accept parser. Runtime Headers об'єднує повторні Accept; рядок із комою не проходить. Не стверджувати збереження raw cardinality/whitespace: перевірити реальні H1/H2 негативні випадки. Wildcard, mixed media ranges, будь-який q, відсутній Accept, невідомий маршрут, неканонічний path, неузгоджений query й інші методи передаються через `fetch(request)` без заміни HTML. Невідомий шлях має зберегти origin 404. Для каталогів query порожній; для `/404.html` дозволені лише чинні точні мовні стани. Не розширювати цей контракт за припущенням про сканер.

Для точних головних шляхів `/` і `/en/` запит GET/HEAD з точним Accept `text/markdown` може містити query, якщо в декодованих назвах параметрів немає `lang`. Такі параметри не змінюють вміст цих сторінок; повертається канонічний Markdown тієї самої мови. `lang`, зокрема закодований або повторений, залишається HTML passthrough, оскільки `concept/app.js` використовує його для мовного переходу. Назви решти параметрів, UA та IP не визначають поведінку; параметри не відображаються у відповіді й не журналюються. Для інших шляхів query-контракт не змінюється. Якщо на головних додається новий функціональний параметр, спочатку оновити цей контракт і перевірки, щоб Markdown не приховав його дію.

За відсутності `lang` на `/` мовний fallback — український (`Content-Language: uk`), незалежно від `Accept-Language` або мови браузера. `/en/` є явним вибором англійської версії, а не fallback, і зберігає англійський Markdown. Не визначати мову з несемантичних query-параметрів.

Підстава для корекції — обмежена production-діагностика 19.10.2026 о 08:51:29 UTC: runtime Worker побачив root GET, `query-present=yes`, `accept-class=exact`, `accept-length=13`; версія `61169c468aeedde0fc9283e231c88f770f9655b5`, Ray `a4ce8a887d935a71-VIE`. Значення або назва query не збирались. Це підтверджує відхилення через попередню вимогу порожнього query, але не доводить scanner PASS після корекції. Звичайний HTML-контроль у тому самому вікні зберіг байти Pages; діагностику прибрано перед подальшими перевірками.

`x-markdown-tokens` не вигадується: число токенів залежить від tokenizer і не є критерієм MIME. Cloudflare також [прибрав цей заголовок зі свого конвертера 09.10.2026](https://developers.cloudflare.com/changelog/post/2026-10-09-markdown-for-agents-in-process-conversion/).

## Окреме стиснене HTML-представлення Zabava EN

Лише точний `/en/portfolio/2022/zabava-restaurant-sambir/` без query може отримувати попередньо стиснені Brotli-байти **того самого фінального HTML Pages**. Це не інший дизайн або відповідь для сканера: вибір залежить від звичайних GET/HEAD та справжньої підтримки `br`. В Cloudflare використовувати початковий `request.cf.clientAcceptEncoding`: платформа нормалізує звичайний заголовок. Відсутнє значення, відмова `q=0`, непідтримане кодування, інший URL/query/метод зберігають origin passthrough. Точний Markdown negotiation та MCP мають пріоритет.

Generator стискає фінальні байти з quality11 й записує HTML/source та compressed SHA-256, довжини, source path і revision до manifest. Worker передає готові байти через `encodeBody: 'manual'`, `Content-Encoding: br`, `Cache-Control: public, max-age=600, no-transform` та `Vary: Accept, Accept-Encoding`. Він зберігає discovery, noindex, content signals і CORS; representation-specific ETag підтримує GET/HEAD/304. `HTML_PRECOMPRESSED_DISABLED=true` вимикає лише цю гілку; Markdown/MCP і origin HTML залишаються доступними. Не змінювати довгий HTML TTL чи глобальне стиснення заради одного URL.

Парність перевіряється при складанні та активації, **не порівнянням з origin під час кожного запиту**. Тому під час кожного наступного релізу обов’язково оновлювати Worker із matching artifact того самого main run та звіряти `X-Piskor-HTML-Version`, `X-Piskor-HTML-SHA256`, декодовані HTML-байти й ETag після публікації. Якщо таку парність неможливо забезпечити, до публікації нових Pages вимкнути селективну HTML-гілку через kill switch; не залишати старий bundle джерелом нового HTML. Успіх Pages окремо не завершує реліз.

Після активації перевірити реальну передачу `br` без повторного стиснення/ін’єкції, gzip-only/identity/`br;q=0`, HEAD/304, канонічну сторінку з query, UA-сторінку, 404, Markdown та всі три MCP tools. Unit-тест Node не емулює Cloudflare encoding/transforms. При розбіжності байтів або версії застосувати kill switch і origin fallback, зафіксувати відхилення та не оголошувати вимірювання прийнятими.

## Відтворення й перевірки до публікації

```sh
npm ci --ignore-scripts
python3 scripts/build-site.py
python3 scripts/build_markdown_worker.py --site _site --out output/markdown-worker --revision "$(git rev-parse HEAD)"
node --test scripts/test-markdown-worker.mjs
git diff --check
```

CI виконує той самий порядок, перевіряє parity всіх Markdown/HEAD, негативні запити й passthrough та зберігає **окремий** artifact `markdown-worker` після перевірок сайту. `manifest.json` зв'язує revision, routes, Markdown і bundle з фактичними SHA-256. Не вкладати Worker у `_site`. `cloudflare/wrangler.jsonc` навмисно не має активних routes, workers.dev, preview URLs або observability. Немає автоматичної зміни Cloudflare чи нових secrets.

## Застосування після мерджу

- Дочекатися успішних PR CI, мерджу й Deploy Pages від актуального main. Завантажити саме `markdown-worker` **цього main run**, перевірити SHA bundle/manifest і всі Markdown проти фактичного Pages artifact. PR artifact не є доказом main deployment.
- Перед зміною зберегти поточні Worker routes, базові дев'ять правил, вимкнені experiments і cache settings. Перевірити свіжу account quota та добовий трафік. Workers Free має 100 000 запитів на день на акаунт; загальний route рахує також passthrough HTML. Не підключати paid plan чи платні bindings.
- Завантажити перевірений module як `piskor-markdown` без GitHub integration, workers.dev, preview URLs, Logs, Traces або bindings. Якщо UI спершу створює Hello World, до завантаження вмісту сайту вимкнути workers.dev/preview/logs; початковий placeholder не є реалізацією й не має route домену. Не вмикати стандартні invocation logs: вони можуть містити URL/headers. Створення Worker без route ще не активує його для сайту.
- Додати більш специфічний **no-script** route `https://piskor.com.ua/assets/*`, потім `https://piskor.com.ua/*` до Worker. Не змінювати DNS/origin/custom domain. Exact `/` не охоплює query; `/*` охоплює весь path, тому root-діагностику обмежує код, а не нібито строковий route.
- Для робочого route увімкнути та перечитати **Fail open при вичерпанні квоти**. `ctx.passThroughOnException()` покриває інший випадок і не замінює цей setting. Якщо UI не дозволяє гарантувати quota fail-open, не залишати production route активним. Зберегти route ID/попередній стан для негайного відкату.
- Початкові три URL rewrites можна залишити для контролю: Worker обробляє й відомий переписаний Markdown path. Після підтвердження Worker-версії та успішної повної матриці вимкнути лише ці три rewrites, щоб Worker став єдиним власником negotiation. Базові response headers, cache bypass та вимкнені redirects не розширювати. Перевірити знову без перекриття старими rewrites; за невдачі повернути саме попередній стан.
- Пройти реальні GET/HEAD, H1/H2, exact/negative Accept, query/мови, прямий Markdown, origin404 і HTML↔Markdown alternation. Звіряти байти з artifact; не приймати HTML з Markdown MIME. Перевірити кеші, HTML/CSS/JS/зображення, noindex, consent, меню, UA/EN і три native WebMCP tools.

Для Worker acceptance запускати повну матрицю з `--expected-markdown-version MERGE_SHA`:

```sh
python3 scripts/check-agent-delivery.py --site ACTUAL_MAIN_PAGES_ARTIFACT --out NEW_EVIDENCE_DIRECTORY --expected-markdown-version MERGE_SHA
```

У кожній Markdown-відповіді потрібні один точний version header, `no-store` та відсутність спостереженого CF HIT. Згенерована Worker-відповідь може не мати `CF-Cache-Status`; його відсутність не підмінює перевірку source/route та чергування форматів. Старий режим verifier для rewrite-бази зберігає початкові cache checks. Виняток Cloudflare HTML injection дозволено додати лише через точний перевірений blob за звичайним контрактом verifier.

## Коротка діагностика сканера без журналів

За потреби встановити plaintext runtime variable `MD_DIAGNOSTIC_START` у майбутню UTC Unix-секунду. Код має жорстке вікно `[start, start + 180)` і працює тільки для root GET та реальної HTML 200 відповіді. Query не відображається: лише ознака наявності. Accept не відображається: лише клас exact/html/missing/other та довжина. Немає IP, UA, cookies, authorization, raw URL/query, console logging, persist/tail/export або стороннього endpoint.

Content-Type залишається правдивим HTML з тимчасовими діагностичними параметрами; тіло не змінюється. Зберегти один звичайний контроль і один свіжий isolated Markdown scanner, їхні час/Ray/version. Якщо scanner отримав Markdown — діагностичний HTML-маркер не потрібен. Маркер показує лише runtime-поля Worker цього запиту, не початкові wire bytes. Відсутність маркера не доводить причину чи втрату Accept.

Прибрати variable після одного контрольованого вікна й перевірити звичайний Content-Type. Не залишати параметри під час фінального uninstrumented Content Site scan та PSI. Для зміни query/Accept policy потрібен конкретний фактичний доказ і review; жодних scanner/UA/IP винятків, підміни MIME чи вигаданих можливостей.

## Свіжість наступних публікацій

**Кожне оновлення контенту, HTML або Markdown потребує відповідного Worker bundle з того самого main CI run.** Після Pages виконати перевірене завантаження нового Worker, потім звірити його `X-Piskor-Markdown-Version` та байти всіх Markdown із новим Pages artifact. До цього реліз не завершений. Не залишати старі факти в embedding і не називати наявність CI artifact автоматичним Cloudflare deploy.

Якщо синхронний paired rollout неможливий, спочатку вимкнути route і повернути перевірений baseline rewrite, який читає актуальний Markdown з Pages. Зберігати справжню причину fallback та повторно перевіряти delivery; попередній scanner PASS не переноситься на fallback автоматично.

Приймання Worker потребує свіжого Markdown PASS на isitagentready, повної HTTP-матриці, native WebMCP і Agentic 5/5. Зберігати також failures. Після остаточного Cloudflare стану повторити чинну вибірку 10 PSI URL обома режимами; це не замінює вимогу всіх сторінок та п'яти послідовних проходжень. Швидкісні вимоги залишаються відкритими до фактичного виконання.

## Відкат

При регресії вимкнути/прибрати тільки новий Worker route за збереженим ID, повернути три початкові rewrite expressions/status, прибрати diagnostic variable. No-script assets route сам не виконує код. Перечитати стан у UI й звірити HTML/MD/HEAD/404, кеші, policy, дизайн і agent tools. Не чіпати DNSSEC, origin, безпеку, аналітику, indexing або TTL сторонніх ресурсів.

Первинні джерела: [Routes і matching](https://developers.cloudflare.com/workers/configuration/routing/routes/), [limits і quota fail-open](https://developers.cloudflare.com/workers/platform/limits/), [passThroughOnException](https://developers.cloudflare.com/workers/runtime-apis/context/), [актуальний ліміт bundle](https://developers.cloudflare.com/changelog/post/2026-09-04-increased-worker-size-limit/), [Worker logs](https://developers.cloudflare.com/workers/observability/logs/workers-logs/).
