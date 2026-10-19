# Виправлення доставки Markdown: діагностика та умовний fallback

Стан: **підготовлено, не застосовано**. Базові rewrites і заголовки вже працюють зі звичайним HTTP-клієнтом. На 19.10.2026 isitagentready отримує HTML також в ізольованому Markdown-тесті. Його звіт показує намір `Accept: text/markdown`, але не доводить значення заголовка в Cloudflare. Причина ще не підтверджена. Схожий [зовнішній issue](https://github.com/cloudflare/agents/issues/1449) є гіпотезою, не доказом для цього домену.

[JSON](cloudflare-markdown-fallback.json) містить одну тимчасову діагностику та три **вимкнені** Single Redirect rules. Це ручний, умовний план, не автоматичний deploy. Зберегти дизайн, HTML/CSS/JS/медіа, noindex, consent, політику `ai-input=yes, ai-train=no, search=yes`, чинні DNS і native WebMCP. Worker, нові секрети й платні послуги не потрібні для цього дослідження.

## Порядок після мерджу

- Дочекатися успішного main CI/Pages та перевірити опублікований артефакт. До цього не зберігати змін Cloudflare.
- Зберегти поточні ID, порядок і поля правил. Перевірити фактичну квоту: база має 8 активних Transform Rules і окремий вимкнений font experiment. Нове діагностичне правило займає лише одне місце; не вимикати сторонні правила заради квоти. Single Redirects мають окрему квоту; перед застосуванням перевірити її в UI.
- Підготувати майбутнє UTC-вікно через `python3 scripts/prepare_markdown_delivery.py --start UNIX_SECOND --duration 180 --out output/markdown-diagnostic.json`. Вихід лише для перегляду, скрипт не має мережевих дій. Дозволено максимум 180 секунд; `START ≤ timestamp < END` є буквальними межами. Залишити час для ручного введення й перевірки перед початком.
- У UI перевірити прийнятність виразу; встановити діагностику останньою. Якщо вираз або квота не підтримуються, зупинити цей експеримент без зміни базових правил. Не розширювати фільтр.
- Усередині вікна зберегти один звичайний HTML-контроль та один ізольований Markdown scan. Записати час, CF-Ray, ID вікна й повний результат. Наявність маркера у контролі не підтверджує його на запиті сканера.
- Вимкнути діагностику навіть після помилки; перевірити новий звичайний Content-Type. Строк дії обмежує виконання правила, але downstream cache може зберігати стару відповідь. Не приймати старий Ray/ID за новий доказ.

## Що саме вимірюється

Тимчасова відповідь завжди залишається **`text/html; charset=utf-8`** з початковим HTML. До MIME додаються `piskor-diag`, `piskor-count`, `piskor-length` та URL-safe Base64-параметр `piskor-accept`. Це обмежене відображення лише власного Accept клієнта, не шифрування. IP, UA, cookies, authorization чи тіло запиту не збираються. Зовнішній log export і глобальний Tracing не вмикаються.

Перед кодуванням заголовки Accept об'єднуються через `|` і обрізаються до 128 байтів; окремо зберігаються cardinality й довжина joined значення. Декодувати Base64url без trim/нормалізації. `|` може міститися всередині значення, тому не відновлювати з нього межі заголовків. Значення є полем Cloudflare у response phase, а не wire capture; map також має платформні обмеження. Якщо `length > 128`, висновок про повне значення недопустимий.

| Спостереження у свіжому сканері | Наступна дія |
|---|---|
| Чинний ID, count=1, length=13, точне декодоване `text/markdown`, але HTML 200 | Дозволений обмежений trial раннього 307 для `/` |
| Accept відсутній, інший, дубльований або обрізаний | Не реконструювати намір і не розширювати Accept; зберегти результат як невирішений |
| Немає чинного маркера | Непереконливий результат; не робити висновку про Accept або пропущену фазу |

## Умовний 307 trial

Single Redirect виконується раніше URL Rewrite і завершує обробку першого запиту. Він може перевірити інший шлях доставки, якщо точний Accept доступний, але не відновить загублений заголовок. Спочатку обмежити directory-правило додатковим `and http.request.uri.path eq "/"`; решту залишити вимкненими. Це однакова поведінка для всіх клієнтів із точним Accept, без винятків для сканера, UA або IP.

За успіху першої перевірки можна ввімкнути повні три правила JSON. Контракт змінюється з прозорого HTTP 200 на **307 → явний Markdown URL**. GET/HEAD зберігають метод; ціль завжди на `https://piskor.com.ua`, query зберігається. Accept/query/мовні обмеження базового плану лишаються. Прямі службові префікси виключені, тому циклу немає. Резервні правила обмежені канонічними шляхами; encoded/dot/backslash варіанти не є обіцяним fallback. Початкові rewrites лишаються доступними для відкату.

Перший 307 перевіряти окремо без auto-follow: точний Location, статус і фактичні кеш-заголовки. Не припускати, що пізніші response/cache rules виконались на першому 307. Кінцевий 200 має бути справжнім Markdown, byte-exact до артефакту, з правильними MIME, Vary, policy та discovery. Невідомий шлях не можна перетворювати на Markdown 200; кінцевий 404 зберігає error HTML MIME.

Для повної перевірки: `python3 scripts/check-agent-delivery.py --site ACTUAL_PAGES_ARTIFACT --out output/agent-delivery-new --known-html-injection EXACT_EXISTING_BEACON --allow-markdown-redirects 307`. Зберігати сирі відповіді й хеші; дозволений HTML-виняток тільки один точний попередньо перевірений Cloudflare beacon. Відсутність або відмінність blob не можна ігнорувати загальним regex.

Зберігати нові redirect rules лише після свіжого **неінструментованого** scanner PASS і успішної матриці всіх HTML/Markdown пар, GET/HEAD, негативних Accept/query, 404 та HTML↔Markdown cache alternation. Окремо перевірити native WebMCP, Agentic 5/5 і незмінний вигляд UA/EN на mobile/desktop. Бал Content Site не видавати за All Checks; коректні OAuth/MCP-server/commerce N/A зберігати. FCP/LCP/SI залишаються окремими критеріями, не наслідком успішного Markdown.

За невдачі вимкнути **лише нові redirects** і діагностику. Перечитати стан у UI, перевірити звичайний HTML та чинне прозоре Markdown. Не змінювати базовий cache bypass, DNSSEC, безпеку, consent або шрифти для проходження сканера.

Первинні джерела: [порядок фаз](https://developers.cloudflare.com/ruleset-engine/reference/phases-list/), [Single Redirect settings](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/settings/), [функції виразів](https://developers.cloudflare.com/ruleset-engine/rules-language/functions/), [cross-zone subrequests у Transform Rules](https://developers.cloudflare.com/rules/transform/examples/add-request-header-subrequest-other-zone/).
