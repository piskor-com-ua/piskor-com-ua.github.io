// PUBLIC_PAGE_DATA is prepended by the artifact-only deterministic generator.
const DISCOVERY = '</.well-known/ard.json>; rel="ard"; type="application/ard+json", </.well-known/agent-skills/index.json>; rel="agent-skills"; type="application/json", </.well-known/api-catalog>; rel="api-catalog"; type="application/linkset+json", </llms.txt>; rel="describedby"; type="text/plain"';

export function diagnosticParameters(request, env, revision, nowSeconds) {
  const url = new URL(request.url);
  const raw = env.MD_DIAGNOSTIC_START;
  if (url.origin !== 'https://piskor.com.ua' || url.pathname !== '/' || request.method !== 'GET' ||
      typeof raw !== 'string' || !/^\d{10}$/.test(raw)) return null;
  const start = Number(raw);
  if (nowSeconds < start || nowSeconds >= start + 180) return null;
  const accept = request.headers.get('Accept');
  const classification = accept === null ? 'missing' : accept === 'text/markdown' ? 'exact' :
    accept.includes('text/html') ? 'html' : 'other';
  return `; piskor-md-version=${revision}; query-present=${url.search ? 'yes' : 'no'}; method=GET; accept-class=${classification}; accept-length=${accept?.length ?? 0}`;
}

export async function handle(request, env, context, data, dependencies = {}) {
  context?.passThroughOnException?.();
  const originFetch = dependencies.fetch ?? fetch;
  const nowSeconds = dependencies.nowSeconds ?? Date.now() / 1000;
  const url = new URL(request.url);
  const readable = request.method === 'GET' || request.method === 'HEAD';
  let markdown = null;
  if (url.origin === 'https://piskor.com.ua' && readable) {
    // Headers combines duplicate fields. Only this exact resulting value is accepted.
    if (request.headers.get('Accept') === 'text/markdown') {
      const page = data.pages[url.pathname + url.search];
      if (page) markdown = page.markdown;
    }
    // Direct alternatives retain their ordinary any-Accept behavior, no query aliases.
    const direct404Query = (url.pathname === '/agent-markdown/404-en.md' && url.search === '?lang=en') ||
      (url.pathname === '/agent-markdown/404.md' && url.search === '?lang=uk');
    if ((!url.search || direct404Query) && Object.hasOwn(data.documents, url.pathname)) markdown = url.pathname;
  }
  if (markdown) {
    const document = data.documents[markdown];
    const headers = new Headers({
      'Content-Type': 'text/markdown; charset=utf-8',
      'Content-Language': document.language,
      'Content-Length': String(document.bytes),
      'Cache-Control': 'no-store',
      'Vary': 'Accept',
      'X-Robots-Tag': 'noindex, nofollow',
      'Content-Signal': 'ai-input=yes, ai-train=no, search=yes',
      'Link': DISCOVERY,
      'X-Piskor-Markdown-Version': data.revision,
    });
    return new Response(request.method === 'HEAD' ? null : document.body, {status: 200, headers});
  }
  const response = await originFetch(request);
  const diagnostic = diagnosticParameters(request, env, data.revision, nowSeconds);
  if (!diagnostic || response.status !== 200 ||
      response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'text/html') return response;
  const headers = new Headers(response.headers);
  headers.set('Content-Type', headers.get('Content-Type') + diagnostic);
  return new Response(response.body, {status: response.status, statusText: response.statusText, headers});
}

export default {
  fetch(request, env, context) {
    return handle(request, env, context, PUBLIC_PAGE_DATA);
  },
};
