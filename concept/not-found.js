// GitHub Pages serves this same document at every missing URL. Keep that URL
// and its HTTP 404 response while matching the language of the requested path.
(() => {
  const requested = new URLSearchParams(location.search).get('lang');
  const english = requested === 'en' || (requested !== 'uk' && /^\/en(?:\/|$)/.test(location.pathname));
  const lang = english ? 'en' : 'uk';
  document.documentElement.lang = lang;

  if (english) {
    document.querySelectorAll('[data-error-en]').forEach((element) => {
      element.textContent = element.dataset.errorEn;
    });
    document.querySelectorAll('[data-error-en-label]').forEach((element) => {
      element.setAttribute('aria-label', element.dataset.errorEnLabel);
    });
    document.querySelectorAll('[data-error-path]').forEach((link) => {
      link.setAttribute('href', '/en' + link.dataset.errorPath);
    });
    const title = 'Page not found | PISKOR Architect';
    const description = 'This page isn’t here. Explore PISKOR Architect projects, discover our approach or get in touch.';
    document.title = title;
    for (const selector of ['meta[property="og:title"]', 'meta[name="twitter:title"]']) {
      document.querySelector(selector).content = title;
    }
    for (const selector of ['meta[name="description"]', 'meta[property="og:description"]', 'meta[name="twitter:description"]']) {
      document.querySelector(selector).content = description;
    }
    document.querySelector('meta[property="og:locale"]').content = 'en_GB';
    const structured = document.querySelector('script[type="application/ld+json"]');
    const graph = JSON.parse(structured.textContent);
    const page = graph['@graph'].find((node) => node['@type'] === 'WebPage');
    page.name = title;
    page.inLanguage = lang;
    structured.textContent = JSON.stringify(graph);
  }

  document.querySelectorAll('[data-error-lang]').forEach((link) => {
    const target = new URL(location.href);
    target.searchParams.set('lang', link.dataset.errorLang);
    target.hash = '';
    link.setAttribute('href', target.pathname + target.search);
    if (link.dataset.errorLang === lang) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
})();
