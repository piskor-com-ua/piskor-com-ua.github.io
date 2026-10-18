# ARD та WebMCP: перевірка інтеграції

Дата: 18.10.2026. База: `origin/main`, `8e839cf0e20cfbdac9db2f5967cefd368b43eefa`.

## Реалізовано

- Єдине джерело для `/.well-known/ard.json` і сумісного `/.well-known/ai-catalog.json`; HTML discovery-посилання на сторінках із WebMCP.
- Реальний публічний skill описує пошук кейсів, мови, підтверджені факти, секції, звичайну навігацію й читання контактів. Він не видає WebMCP за віддалений MCP-сервер і не дозволяє надсилання повідомлень.
- Необов'язковий first-party токен у конфігурації; метатег перед адаптером, перевірка формату, origin, feature, scope і строку. Перевірка метаданих не доводить валідності криптографічного підпису: це підтверджує Chrome.
- CI перевіряє актуальну закріплену ARD-схему, валідатор Lighthouse 13.5.0, реальний файл skill та схеми параметрів інструментів. У build-процесах використовується той самий Python interpreter, що запустив збірку.

## Підтверджено локально

- Повна збірка й 16 Python-тестів; 112 сторінок із SEO/мовними парами, 46 двомовних кейсів, 184 адаптивні картки та правила медіа/швидкодії.
- П'ять тестів WebMCP виконання: поточний і попередній API, відсутність API, точність пошуку/мов/року/деталей, відхилення неправильних параметрів, контакти й повторний запит після помилки.
- `npm run test:discovery`: актуальна схема ARD та Lighthouse conformance без помилок і попереджень; усі три input schemas компілюються.
- Нативні інструменти в Codex Browser: пошук «398» за 2026 повертає Брюховичі з точним опублікованим статусом; англійська Замарстинівська повертає вісім секцій; контакти — телефон, WhatsApp і Viber. `limit: 0` відхиляється.
- UA desktop та EN mobile 390 px: мова, кейс із каталогу, відсутність горизонтального переповнення, eager-перша обкладинка, галерея, ArrowRight/Escape і повернення фокуса.
- Один локальний mobile Lighthouse 13.5.0 / Chrome 155 на gzip preview: Performance/Accessibility/Best Practices 100, SEO 69, CLS 0; `ard-schema` — pass. FCP 0,90 с, LCP 1,88 с, SI 1,43 с. Це діагностичний запуск без production CDN/HTTPS, не парний benchmark і не доказ відсутності регресії чи досягнення мобільного SI ≤1 с.

## Production Origin Trial

WebMCP Origin Trial активний для Chrome 149–162 до 30.03.2027. Після проблеми завантаження авторизованої форми користувач самостійно отримав і надав токен. Два third-party варіанти відхилені; коректний first-party токен додано в цей самий PR. Перевірені метадані: origin `https://piskor.com.ua:443`, feature `WebMCP`, expiry `2027-03-30T00:00:00Z`, без `isThirdParty` та `isSubdomain`. Перевірка метаданих ще не підтверджує активацію та підпис Chrome на production.

У початковому локальному Lighthouse до додавання токена два WebMCP-аудити залишалися N/A. `form-coverage` теж залишається N/A: форми не додавалися. Нативний виклик у сумісному Codex Browser і локальна компіляція схем не замінюють перевірку production Origin Trial; токен прив'язаний до живого origin і не активує API на localhost.

Для завершення релізу: повторити CI з токеном, дочекатися Pages deployment та перевірити токен, ресурси й Agentic Browsing у production. Cloudflare змінювати лише після мерджу; `noindex` залишається.

## Джерела

- https://developer.chrome.com/docs/lighthouse/agentic-browsing/scoring
- https://developer.chrome.com/docs/web-platform/origin-trials
- https://developer.chrome.com/origintrials/#/view_trial/4163014905550602241
- https://agenticresourcediscovery.org/spec/
- Закріплена схема та ліцензія: `scripts/schemas/README.md`.
