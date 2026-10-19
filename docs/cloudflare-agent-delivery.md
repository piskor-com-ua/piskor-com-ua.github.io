# Доставка ресурсів для агентів через Cloudflare Free

[JSON](cloudflare-agent-delivery.json) фіксує базові правила, **застосовані 18.10.2026 після PR #54**; ID наведені в `applied_baseline`. Це не експорт усієї зони й не інструмент розгортання. Не створювати ці правила повторно. Новий [умовний fallback Markdown](cloudflare-markdown-fallback.md) ще не застосований: будь-які його зміни Cloudflare дозволені тільки після мерджу нового PR, успішного main CI/Pages deployment і перевірки опублікованої версії. Налаштування індексації, consent, аналітики та безпеки не входять до цього плану.

## Представлення Markdown

Збірка створює Markdown з того самого фінального публічного HTML, зберігаючи мову, факти, canonical URL і чинний `noindex`. Приватні матеріали, скрипти й прихований службовий зміст не є джерелами цього представлення. Перелік пар HTML/Markdown публікується в `/agent-markdown/routes.json` і оновлюється з кожною збіркою; файли не редагувати вручну.

Перемикання діє лише для GET/HEAD на `piskor.com.ua` з **одним заголовком Accept, повне значення якого — `text/markdown`**. Це навмисно обмежений opt-in, а не повний розбір пріоритетів RFC Accept. Значення з `q=0`, `q=1`, параметрами, кількома media ranges, дубльованими Accept, `*/*`, звичайний browser Accept і відсутній Accept не перемикають HTML. Не замінювати перевірку на `contains "text/markdown"`.

| Публічний URL | Внутрішній шлях до готового файлу |
|---|---|
| `/` | `/agent-markdown/index.md` |
| `/en/` | `/agent-markdown/en/index.md` |
| `/portfolio/2026/example/` | `/agent-markdown/portfolio/2026/example/index.md` |
| `/404.html` | `/agent-markdown/404.md` |
| `/404.html?lang=en` | `/agent-markdown/404-en.md` |

Перший rewrite додає префікс і `index.md` до шляхів із кінцевим `/` **лише за порожнього query string**. Ще два охоплюють наявний `/404.html`: точний query `lang=en` обирає EN-файл; порожній query або точний `lang=uk` — UA-файл. Решта query, включно з `/?lang=en`, зайвими, повтореними чи закодованими параметрами, залишають звичайний HTML. Це не дозволяє Markdown української сторінки підмінити клієнтський мовний перехід HTML.

EN-правило розташоване перед загальним, але правильність забезпечують їхні неперетинні умови query. Умови правил однієї фази бачать початкові поля: зміна URI першим rewrite не заважає збігу наступного правила. Каталоги `/assets/`, `/.well-known/`, `/agent-api/`, `/agent-skills/` і `/agent-markdown/` виключені з rewrite каталогів. Query string ніколи не переписується; довільна query-negotiation не обіцяється. Це навмисно обмежена підтримка канонічних URL, а не еквівалент URLSearchParams. Якщо у майбутньому з’явиться публічний `.html` поза `/404.html`, доповнити правила й перевірку відповідності маршрутам; зараз іншого такого документа немає.

Невідомий шлях не можна спрямовувати на наявний `404.md`: це перетворить помилку на HTTP 200. Невідомий шлях із `/` може бути переписаний у відповідний відсутній Markdown-файл, після чого GitHub Pages має повернути **404 із початковим HTML MIME**. Правила MIME й спільне правило discovery/policy спрацьовують лише за HTTP 200; невідомі 404 зберігають `noindex` у HTML meta. Окремого `/en/404.html` немає; його не рекламувати. За прямим `/404.html` зберігається фактичний статус цього документа на origin — rewrite не створює статус помилки самостійно.

## Кеш і заголовки

URL Rewrite виконується перед Cache Rules. Пізніші фази бачать змінений `http.request.uri.path`; raw-поля зберігають оригінальний шлях. Cloudflare документує створення окремих cache entries після переписування URI. Однак `Vary: Accept` сам по собі не ізолює варіанти в стандартному Cloudflare-кеші. [Порядок фаз](https://developers.cloudflare.com/cache/how-to/cache-rules/order/), [значення полів між фазами](https://developers.cloudflare.com/ruleset-engine/about/rules/#field-values-during-rule-evaluation), [окремі URI та cache entries](https://developers.cloudflare.com/cache/advanced-configuration/serve-tailored-content/), [обробка Vary](https://developers.cloudflare.com/cache/concepts/cache-control/).

Початковий план додає явний **bypass edge cache тільки для `/agent-markdown/`**. Він має стояти після будь-яких інших правил, які могли б зробити цей префікс cache eligible. Це не змінює cache key, HTML-кеш чи місячне кешування версійованих фото/шрифтів. Готові Markdown-файли віддає GitHub Pages; Worker, Snippet, конвертація на запит, нові секрети або платний тариф не потрібні. Вплив самих правил на затримку не виміряний і нульовим не оголошується.

Response rules:

- Одне спільне правило для HTTP 200 додає `X-Robots-Tag: noindex, nofollow` і Link до реальних ARD, Agent Skills, API catalog та llms.txt; наявні X-Robots-Tag і Link не замінюються. HEAD `/.well-known/api-catalog` також отримує `rel="api-catalog"`, як вимагає RFC 9727.
- Це саме правило встановлює явно обрану замовником політику `Content-Signal: ai-input=yes, ai-train=no, search=yes`. `search=yes` описує перевагу використання змісту й не скасовує чинний `noindex`; індексація залишається вимкненою. Перед збереженням перевірити відсутність іншого правила з суперечливою політикою.
- Одне правило Add додає `Vary: Accept` до HTML/Markdown: воно створює поле, якщо його немає, і зберігає всі наявні однойменні поля, включно з Accept-Encoding. Умова пропускає `Vary: *`, залишаючи його без змін. Дубльоване Accept у Vary не змінює семантики.
- Встановлюють `text/markdown; charset=utf-8` лише для готових Markdown-ресурсів за HTTP 200; для ARD — `application/ard+json`. Коректний origin MIME `application/json` на JSON-ресурсах перевіряється й зберігається без окремого правила.
- Для `/.well-known/api-catalog` встановлюють `application/linkset+json; profile="https://www.rfc-editor.org/info/rfc9727"`. У каталозі лише реальний GET `/project-catalog.json`; WebMCP-функції браузера не рекламуються як HTTP, MCP або A2A сервер.

Response Header Transform Rules не змінюють уже прийняте рішення про Cloudflare-кешування. Тому встановлення Content-Type чи Vary не замінює окремого cache rule. Add зберігає наявні однойменні заголовки. [Документація заголовків](https://developers.cloudflare.com/rules/transform/response-header-modification/), [RFC 9727](https://www.rfc-editor.org/rfc/rfc9727.html).

## Порядок базового застосування й контроль

До будь-якого збереження експортувати чинні правила, їхні ID/пріоритети та DNS. Перевірити на origin всі згенеровані Markdown, ARD/skill index, API catalog, OpenAPI та guide, включно з byte/hash-порівнянням потрібної версії. У Dashboard перевірити залишок Free quota в кожній фазі та прийнятність усіх виразів: план додає **три URL rewrites, одне Cache Rule і п’ять Response Header Rules** — вісім Transform Rules загалом. Документація Free вказує 10 активних Transform Rules; фактичні квоти та вже зайняті місця підтверджувати у поточній зоні, не припускати, що всі місця вільні. [Доступність Transform Rules](https://developers.cloudflare.com/rules/transform/).

Спочатку додати reserved-prefix cache bypass, потім п’ять response rules в порядку JSON. Три URL rewrites увімкнути останніми. Поля правил перечитати після Save; успішне збереження не замінює HTTP-перевірки. Не замінювати весь існуючий phase ruleset вмістом цього JSON і не змінювати сторонні правила заради вміщення в quota.

Перевірка після застосування:

- UA/EN головні, загальні й річні каталоги, кейси, явні `/404.html`, `/404.html?lang=uk` та `/404.html?lang=en`; GET і HEAD, прямий Markdown URL та виключені префікси. Канонічні directory URL з порожнім query перемикаються. Directory URL з будь-яким query, зокрема `/?lang=en`, залишають HTML. Для 404 повторені `lang=en&lang=uk`/`lang=uk&lang=en`, зайві та закодовані параметри також залишають HTML. Кожен успішний Markdown має збігатися зі своїм файлом; HTML — з HTML цієї версії.
- Всі негативні Accept-випадки, наведені вище. Чергувати HTML → Markdown і Markdown → HTML з холодним та теплим кешем. Тіло або Content-Type іншого представлення є помилкою приймання.
- Невідомі шляхи з `/` та `.html`: статус 404, початковий error MIME, без soft 404. MIME override не має маскувати помилки GitHub чи Cloudflare.
- Правильні MIME, Link, Vary та noindex; збереження security/cache headers, UA/EN посилань, фото, шрифтів, consent/tracking і native WebMCP. Наявність правил не є виміром їхнього результату.
- GET/HEAD API catalog, посилання на фактичний JSON endpoint і OpenAPI-схему; native WebMCP окремо перевірити реальними read-only викликами в сумісному браузері.
- Ефективний bypass negotiated Markdown і збереження HTML-кешу. Лише після перевірки доставки повторити той самий readiness scan; бал сканера не є доказом повної застосовності, видимості в AI-пошуку чи виконання FCP/LCP/SI.

## DNS-AID: застосований запис

JSON фіксує **HTTPS ServiceMode** запис `_index._agents.piskor.com.ua`, priority 1, TargetName `piskor.com.ua`, `alpn="h2,h3"`, port 443. Це експериментальна організаційна точка HTTPS-discovery: головна сторінка має реальні Link до ARD, Agent Skills та API catalog. Вона не заявляє існування MCP/A2A серверів або автентифікації. У DNS-AID draft §3.2 протокол і схема індексу залишені поза межами специфікації; конкретна машинна сумісність такої HTML-точки потребує окремої перевірки. [Чинний досліджений draft DNS-AID](https://datatracker.ietf.org/doc/html/draft-mozleywilliams-dnsop-dnsaid-02).

Запис створений 18.10.2026. За окремим явним дозволом власника Cloudflare DNSSEC увімкнений, DS зареєстрований у реєстратора; ланцюжок перевірено незалежно, Google і Cloudflare resolver повернули AD=true. isitagentready після цього підтвердив DNS-AID. Це датовані докази, не гарантія всіх resolver чи майбутнього стану. Не змінювати DNSSEC/DS повторно для Markdown; MX/SPF/DKIM/DMARC збережені. Не підміняти запис довільним TXT або фіктивним MCP/A2A endpoint.

## Відкат базового плану (історична процедура)

Для нового Markdown fallback використовувати його окремий відкат; базові правила не вимикати. Якщо потрібен відкат саме всього базового плану: спочатку вимкнути три URL rewrites та перевірити звичайний HTML. Потім прибрати лише додані цим планом cache bypass і п’ять response rules за збереженими ID; за потреби відновити попередній порядок з експорту. Якщо DNS-запис було створено — видалити тільки його. Зберегти всі попередні DNS/cache/security/consent/noindex налаштування. Перевірити HTML обома мовами, 404, опубліковані хеші ресурсів і noindex та зберегти докази відкату.
