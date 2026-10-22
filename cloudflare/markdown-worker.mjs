import {handleMcp} from './mcp-server.mjs';
// PUBLIC_PAGE_DATA is prepended by the artifact-only deterministic generator.
const DISCOVERY = '</.well-known/ard.json>; rel="ard"; type="application/ard+json", </.well-known/agent-skills/index.json>; rel="agent-skills"; type="application/json", </.well-known/api-catalog>; rel="api-catalog"; type="application/linkset+json", </llms.txt>; rel="describedby"; type="text/plain"';
const HTML_ROUTE = '/en/portfolio/2022/zabava-restaurant-sambir/';
const decodedHtml = new WeakMap();

function explicitlyAcceptsBrotli(value) {
  if (typeof value !== 'string' || !value) return false;
  const entries = value.split(',').map(part => part.trim()).filter(part => /^br(?:\s*;|$)/i.test(part));
  if (entries.length !== 1) return false;
  // RFC 9110 qvalue: at most three decimals, 0..1. Explicit coding
  // overrides wildcard preference; a wildcard alone never opts this route in.
  const match = /^br(?:\s*;\s*q\s*=\s*(0(?:\.\d{0,3})?|1(?:\.0{0,3})?))?$/i.exec(entries[0]);
  return Boolean(match) && (match[1] === undefined || Number(match[1]) > 0);
}

function precompressedHtml(request, data, env) {
  if (env.HTML_PRECOMPRESSED_DISABLED === 'true') return null;
  const url = new URL(request.url);
  // Cloudflare normalizes the header to br,gzip. Only its original client
  // value establishes consent to Brotli; missing/null/empty CF values do not.
  // Plain Fetch Request environments have no cf property and use the header.
  const clientEncoding = request.cf === undefined
    ? request.headers.get('Accept-Encoding') : request.cf?.clientAcceptEncoding;
  if (url.origin !== 'https://piskor.com.ua' || url.pathname !== HTML_ROUTE || url.search ||
      !['GET', 'HEAD'].includes(request.method) || request.headers.get('Accept') === 'text/markdown' ||
      !explicitlyAcceptsBrotli(clientEncoding)) return null;
  const item = data.html?.[HTML_ROUTE];
  if (!item || item.encoding !== 'br' || item.language !== 'en' || item.revision !== data.revision ||
      !/^[a-f0-9]{64}$/.test(item.sha256) || !/^[a-f0-9]{64}$/.test(item.encodedSha256) ||
      !Number.isSafeInteger(item.bytes) || item.bytes <= 0 ||
      !Number.isSafeInteger(item.encodedBytes) || item.encodedBytes <= 0 ||
      typeof item.bodyBase64 !== 'string') return null;
  const etag = `"sha256-${item.encodedSha256}-br"`;
  const headers = new Headers({
    'Content-Type': 'text/html; charset=utf-8', 'Content-Language': 'en',
    'Content-Encoding': 'br', 'Cache-Control': 'public, max-age=600, no-transform',
    'Vary': 'Accept, Accept-Encoding', 'ETag': etag,
    'Access-Control-Allow-Origin': '*',
    'Content-Signal': 'ai-input=yes, ai-train=no, search=yes',
    'Link': DISCOVERY, 'X-Piskor-HTML-Version': data.revision, 'X-Piskor-HTML-SHA256': item.sha256,
  });
  const condition = request.headers.get('If-None-Match');
  const unchanged = condition?.split(',').some(part => part.trim() === '*' || part.trim().replace(/^W\//, '') === etag);
  const status = unchanged ? 304 : 200;
  let body = null;
  if (request.method === 'GET' && status === 200) {
    body = decodedHtml.get(item);
    if (!body) {
      try {body = Uint8Array.from(atob(item.bodyBase64), character => character.charCodeAt(0));}
      catch {return null;}
      if (body.byteLength !== item.encodedBytes) return null;
      decodedHtml.set(item, body);
    }
  }
  // Cloudflare requires manual for already encoded bytes. No Content-Length:
  // Workers derives the actual transmitted size from this fixed Uint8Array.
  return new Response(body, {status, headers, encodeBody: 'manual'});
}

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
  const mcp = await handleMcp(request, data, env);
  if (mcp) return mcp;
  const originFetch = dependencies.fetch ?? fetch;
  const nowSeconds = dependencies.nowSeconds ?? Date.now() / 1000;
  const url = new URL(request.url);
  const readable = request.method === 'GET' || request.method === 'HEAD';
  let markdown = null;
  if (url.origin === 'https://piskor.com.ua' && readable) {
    // Headers combines duplicate fields. Only this exact resulting value is accepted.
    if (request.headers.get('Accept') === 'text/markdown') {
      let page = data.pages[url.pathname + url.search];
      // Home's only query-dependent behavior is the decoded `lang` parameter.
      // Other home queries leave public content unchanged; use its canonical MD.
      if (!page && (url.pathname === '/' || url.pathname === '/en/') &&
          !url.searchParams.has('lang')) page = data.pages[url.pathname];
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
      'Content-Signal': 'ai-input=yes, ai-train=no, search=yes',
      'Link': DISCOVERY,
      'X-Piskor-Markdown-Version': data.revision,
    });
    return new Response(request.method === 'HEAD' ? null : document.body, {status: 200, headers});
  }
  const html = precompressedHtml(request, data, env);
  if (html) return html;
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
