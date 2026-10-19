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

Тимчасова відповідь завжди залишається **`text/html; charset=utf-8`** з початковим HTML. До MIME додаються `piskor-diag`, `piskor-count`, `piskor-length` та URL-safe Base64-параметр `piskor-accept`, а також відповідні `piskor-raw-count`, `piskor-raw-length` і `piskor-raw-accept` для незмінного raw-поля. Це обмежене відображення лише власного Accept клієнта з двох представлень поля, не шифрування. IP, UA, cookies, authorization чи тіло запиту не збираються. Зовнішній log export і глобальний Tracing не вмикаються.

Перед кодуванням заголовки Accept об'єднуються через `|` і обрізаються до 128 байтів; окремо зберігаються cardinality й довжина joined значення. Декодувати Base64url без trim/нормалізації. `|` може міститися всередині значення, тому не відновлювати з нього межі заголовків. Значення є полем Cloudflare у response phase, а не wire capture; map також має платформні обмеження. Якщо `length > 128`, висновок про повне значення недопустимий.

| Спостереження у свіжому сканері | Висновок |
|---|---|
| Чинний ID, count=1, length=13, точне декодоване `text/markdown`, але HTML 200 | Точний Accept доступний у response phase; причина невиконання доставки ще не доведена |
| Accept відсутній, інший, дубльований або обрізаний | Не реконструювати намір і не розширювати Accept; значення на ранній фазі невідоме |
| Немає чинного маркера | Непереконливий результат; не робити висновку про Accept або пропущену фазу |

Поля можуть змінюватися **між фазами**, тому будь-який із цих результатів допускає один незалежний короткий trial раннього правила нижче. Це не припущення про загублений заголовок: саме правило вимагає точний Accept у своїй фазі й не відновлює його зі сканера, UA чи IP. [Значення полів між фазами](https://developers.cloudflare.com/ruleset-engine/about/rules/#field-values-during-rule-evaluation).

## Умовне збереження прямого 200 через початковий Accept

Якщо той самий scanner доказує **повний raw count=1, raw length=13 і точне декодоване `text/markdown`**, а поточне поле відрізняється, спочатку допустима заміна лише Accept-предиката в трьох наявних rewrites на відповідний `raw_exact_rewrites` із JSON. Це читання початкового поля, не OR із здогадом і не підміна заголовка. Не створювати дублікати правил; ID, дії, порядок, query, MIME й cache bypass залишаються. JSON-записи навмисно вимкнені як пропозиції; при ручному редагуванні копіюється тільки перевірений expression чинного правила.

Перед цим звичайні exact-контролі HTTP/1.1 з назвами `Accept`, `accept`, `ACCEPT` та HTTP/2, а також mixed/empty/missing/дубльовані Accept мають підтвердити семантику raw map у цій зоні. Nil raw-поля не означає відсутність заголовка на дроті. Доступність raw-полів задокументована для [response expressions](https://developers.cloudflare.com/rules/transform/response-header-modification/reference/fields-functions/) і [URL Rewrite filters](https://developers.cloudflare.com/rules/transform/url-rewrite/reference/fields-functions/); підтримку конкретного виразу й map підтверджує UI та контроль, не припущення про назви ключів. Raw-поле незмінне в межах workflow, але не є незалежним захопленням байтів на дроті.

Після зняття діагностики спочатку виконати один bounded root trial нижче: лише за доведеного raw-наміру замінити в його exact-предикаті обидва `http.request.headers["accept"]` на `raw.http.request.headers["accept"]`. Це заміна поля, не OR; raw/current root, query, методи, ціль і строк дії не змінюються. Пробний 307 не є доказом працездатності rewrite: після переходу на raw rewrites потрібні свіжий scanner PASS і повна матриця. За відмови або регресії повернути початкові expressions із базового JSON. Якщо raw-намір не доведений, цю заміну не застосовувати; незалежний exact-предикат раннього trial нижче залишається допустимим експериментом.

## Умовний 307 trial

Single Redirect виконується раніше URL Rewrite і завершує обробку першого запиту. Він може перевірити інший шлях доставки, якщо точний Accept доступний, але не відновить загублений заголовок. Спочатку підготувати `root_trial` через той самий helper з `--kind root-trial`, новим майбутнім `--start` та максимум 180 секундами. Він має окремі raw/current root і empty-query guards та буквальний строк дії; решту правил залишити вимкненими. Запустити звичайний HTML, exact Markdown і негативний Accept контролі та один свіжий ізольований scanner. Вимкнути/дати завершитися trial навіть за помилки, зберегти ID/Ray/час. Невдача або відсутність збігу не доводить причину. Загалом дозволений один bounded early trial: з поточним полем або, за окремим raw proof вище, з початковим полем. Це однакова поведінка для всіх клієнтів із точним Accept, без винятків для сканера, UA або IP.

За scanner PASS і успіху контролів можна замінити строкове root-правило повним directory-правилом та ввімкнути ще два правила JSON. Якщо окремо доведений raw-напрям потрібний і raw rewrites не дали scanner PASS, дозволена та сама точна заміна Accept-поля в трьох redirect-предикатах; жодних OR чи інших послаблень. Повна матриця й свіжий scanner PASS обов’язкові для збереження. За невдачі — відкат лише нового trial, без розширення предиката. Контракт змінюється з прозорого HTTP 200 на **307 → явний Markdown URL**. GET/HEAD зберігають метод; ціль завжди на `https://piskor.com.ua`, query зберігається. Accept/query/мовні обмеження базового плану лишаються. Прямі службові префікси виключені, тому циклу немає. Резервні правила обмежені канонічними шляхами; encoded/dot/backslash варіанти не є обіцяним fallback. Початкові rewrites лишаються доступними для відкату.

Перший 307 перевіряти окремо без auto-follow: точний Location, статус і фактичні кеш-заголовки. Не припускати, що пізніші response/cache rules виконались на першому 307. Кінцевий 200 має бути справжнім Markdown, byte-exact до артефакту, з правильними MIME, Vary, policy та discovery. Невідомий шлях не можна перетворювати на Markdown 200; кінцевий 404 зберігає error HTML MIME.

Для повної перевірки: `python3 scripts/check-agent-delivery.py --site ACTUAL_PAGES_ARTIFACT --out output/agent-delivery-new --known-html-injection EXACT_EXISTING_BEACON --allow-markdown-redirects 307`. Зберігати сирі відповіді й хеші; дозволений HTML-виняток тільки один точний попередньо перевірений Cloudflare beacon. Відсутність або відмінність blob не можна ігнорувати загальним regex.

Зберігати нові redirect rules лише після свіжого **неінструментованого** scanner PASS і успішної матриці всіх HTML/Markdown пар, GET/HEAD, негативних Accept/query, 404 та HTML↔Markdown cache alternation. Окремо перевірити native WebMCP, Agentic 5/5 і незмінний вигляд UA/EN на mobile/desktop. Бал Content Site не видавати за All Checks; коректні OAuth/MCP-server/commerce N/A зберігати. FCP/LCP/SI залишаються окремими критеріями, не наслідком успішного Markdown.

За невдачі вимкнути **лише нові redirects** і діагностику. Перечитати стан у UI, перевірити звичайний HTML та чинне прозоре Markdown. Не змінювати базовий cache bypass, DNSSEC, безпеку, consent або шрифти для проходження сканера.

Первинні джерела: [порядок фаз](https://developers.cloudflare.com/ruleset-engine/reference/phases-list/), [Single Redirect settings](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/settings/), [функції виразів](https://developers.cloudflare.com/ruleset-engine/rules-language/functions/), [cross-zone subrequests у Transform Rules](https://developers.cloudflare.com/rules/transform/examples/add-request-header-subrequest-other-zone/).
