// Public, stateless JSON-only Streamable HTTP MCP. All facts come from the matching
// final Pages artifact embedded by build_markdown_worker.py; this module never fetches.
const MCP_ORIGIN = 'https://piskor.com.ua';
const MCP_CURRENT = '2026-07-28';
const MCP_LEGACY = '2025-11-25';
const MCP_VERSIONS = [MCP_CURRENT, MCP_LEGACY];
const MCP_BODY_LIMIT = 16 * 1024;
const MCP_RESULT_LIMIT = 256 * 1024;
const MCP_META_PREFIX = 'io.modelcontextprotocol/';
const mcpObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const mcpId = value => typeof value === 'string' || Number.isSafeInteger(value);

function mcpHeaders(data, type = 'application/json; charset=utf-8') {
  return new Headers({'Content-Type': type, 'Cache-Control': 'no-store',
    'X-Robots-Tag': 'noindex, nofollow', 'Content-Signal': 'ai-input=yes, ai-train=no, search=yes',
    'X-Piskor-MCP-Version': data.revision});
}
function mcpResponse(data, status, body, extra = {}) {
  const headers = mcpHeaders(data);
  for (const [key, value] of Object.entries(extra)) headers.set(key, value);
  return new Response(body === undefined ? null : JSON.stringify(body), {status, headers});
}
function mcpError(data, id, code, message, status = 400, details, extra = {}) {
  return mcpResponse(data, status, {jsonrpc: '2.0', ...(mcpId(id) ? {id} : {}),
    error: {code, message, ...(details === undefined ? {} : {data: details})}}, extra);
}
function mcpResult(data, id, version, result) {
  const complete = version === MCP_CURRENT ? {...result, resultType: 'complete',
    _meta: {[MCP_META_PREFIX + 'serverInfo']: {...data.mcp.contract.serverInfo, version: data.mcp.contract.serverInfo.version + '+' + data.revision}}} : result;
  const body = {jsonrpc: '2.0', id, result: complete};
  if (new TextEncoder().encode(JSON.stringify(body)).byteLength > MCP_RESULT_LIMIT) {
    return mcpError(data, id, -32603, 'Published result exceeds the response limit.', 500);
  }
  return mcpResponse(data, 200, body);
}
async function mcpReadBody(request) {
  const length = request.headers.get('Content-Length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MCP_BODY_LIMIT)) {
    // Do not buffer a declared oversized body, including a misleading stream.
    request.body?.cancel().catch(() => {});
    throw 413;
  }
  if (!request.body) throw 400;
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MCP_BODY_LIMIT) {
        reader.cancel().catch(() => {});
        throw 413;
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
  } finally { reader.releaseLock(); }
}
function mcpHeaderName(value) {
  if (value === null || /[^\x20-\x7e]/.test(value)) return null;
  if (value.startsWith('=?base64?') && value.endsWith('?=')) {
    const encoded = value.slice(9, -2);
    if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) return null;
    try {
      return new TextDecoder('utf-8', {fatal: true}).decode(Uint8Array.from(atob(encoded), char => char.charCodeAt(0)));
    } catch { return null; }
  }
  return value;
}
function mcpArgumentError(input, schema) {
  if (Object.keys(input).some(key => !Object.hasOwn(schema.properties, key))) {
    return 'Unknown tool argument. Use only the fields documented by tools/list.';
  }
  const missing = (schema.required || []).find(key => !Object.hasOwn(input, key));
  if (missing) return `Provide the required ${missing} argument.`;
  for (const [key, value] of Object.entries(input)) {
    const rule = schema.properties[key];
    if (rule.type === 'string' && typeof value !== 'string') return `${key} must be a string.`;
    if (rule.type === 'integer' && !Number.isSafeInteger(value)) return `${key} must be an integer.`;
    if (rule.maxLength !== undefined && Array.from(value).length > rule.maxLength) return `${key} must contain at most ${rule.maxLength} characters.`;
    if (rule.enum && !rule.enum.includes(value)) return `${key} must be one of: ${rule.enum.join(', ')}.`;
    if (rule.minimum !== undefined && value < rule.minimum) return `${key} must be at least ${rule.minimum}.`;
    if (rule.maximum !== undefined && value > rule.maximum) return `${key} must be at most ${rule.maximum}.`;
    if (rule.pattern && !new RegExp(rule.pattern).test(value)) return `${key} must match the format documented by tools/list.`;
  }
  return null;
}
function mcpRunTool(mcp, name, input) {
  const language = input.language || 'uk';
  if (name === 'get_contact_options') return {contacts: mcp.contacts};
  if (name === 'get_project_details') {
    const project = mcp.projects.find(p => p.id === input.project_id && p.language === language);
    return project || null;
  }
  const text = value => value.toLocaleLowerCase().normalize('NFKC').replace(/[’‘]/g, "'");
  const terms = text(input.query || '').split(/\s+/).filter(Boolean);
  const projects = mcp.projects.filter(project => {
    if (project.language !== language || (input.year !== undefined && input.year !== project.year)) return false;
    if (!terms.length) return true;
    const haystack = text([project.name, project.summary, project.label,
      ...project.facts.map(f => f.value), ...project.sections.map(s => s.text)].join(' '));
    return terms.every(term => haystack.includes(term));
  });
  return {total: projects.length, projects: projects.slice(0, input.limit ?? 10)
    .map(({id, name, url, year, summary, label}) => ({id, name, url, year, summary, label}))};
}
function mcpAcceptsJson(request) {
  const accepted = new Set();
  for (const item of (request.headers.get('Accept') || '').split(',')) {
    const [type, ...parameters] = item.trim().toLowerCase().split(';');
    const quality = parameters.filter(parameter => parameter.trim().startsWith('q='));
    if (quality.length > 1) return false;
    const q = quality.length ? quality[0].trim().slice(2) : '1';
    if (!/^(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)$/.test(q)) return false;
    if (Number(q) > 0) accepted.add(type.trim());
  }
  return accepted.has('application/json') && accepted.has('text/event-stream');
}

export async function handleMcp(request, data, env = {}) {
  // Keep old Markdown fixtures and unrelated routes byte-for-byte compatible.
  if (!data.mcp) return null;
  const url = new URL(request.url);
  const hasQuery = url.href.split('#', 1)[0].includes('?');
  const publication = !hasQuery && Object.hasOwn(data.mcp.publications, url.pathname)
    ? data.mcp.publications[url.pathname] : null;
  if (url.pathname !== '/mcp' && !publication) return null;
  if (url.origin !== MCP_ORIGIN) return mcpError(data, undefined, -32600, 'Production origin required.', 403);
  const origin = request.headers.get('Origin');
  const publicCard = publication && url.pathname === '/.well-known/mcp/server-card.json';
  if (!publicCard && origin !== null && origin !== MCP_ORIGIN) return mcpError(data, undefined, -32600, 'Origin is not allowed.', 403);
  if (publication) {
    if (!['GET', 'HEAD'].includes(request.method)) return mcpResponse(data, 405, undefined, {Allow: 'GET, HEAD'});
    const headers = mcpHeaders(data, publication.contentType);
    headers.set('Content-Length', String(new TextEncoder().encode(publication.body).byteLength));
    // SEP-2127 requires public cross-origin retrieval of the Server Card, without credentials.
    if (url.pathname === '/.well-known/mcp/server-card.json') headers.set('Access-Control-Allow-Origin', '*');
    return new Response(request.method === 'HEAD' ? null : publication.body, {headers});
  }
  if (hasQuery) return mcpError(data, undefined, -32600, 'The MCP endpoint does not accept a query.');
  if (request.method === 'OPTIONS') {
    const allowed = ['accept', 'content-type', 'mcp-protocol-version', 'mcp-method', 'mcp-name'];
    const requested = (request.headers.get('Access-Control-Request-Headers') || '').split(',').map(x => x.trim().toLowerCase()).filter(Boolean);
    if (origin !== MCP_ORIGIN || request.headers.get('Access-Control-Request-Method') !== 'POST' || requested.some(x => !allowed.includes(x))) {
      return mcpError(data, undefined, -32600, 'Only a same-origin POST preflight is supported.');
    }
    return mcpResponse(data, 204, undefined, {'Access-Control-Allow-Origin': MCP_ORIGIN,
      'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': allowed.join(', '), Vary: 'Origin'});
  }
  if (request.method !== 'POST') return mcpResponse(data, 405, undefined, {Allow: 'POST, OPTIONS'});
  if (request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') {
    return mcpError(data, undefined, -32600, 'Content-Type must be application/json.', 415);
  }
  if (!mcpAcceptsJson(request)) return mcpError(data, undefined, -32600, 'Accept must include application/json and text/event-stream.', 406);
  let message;
  try { message = await mcpReadBody(request); }
  catch (error) { return mcpError(data, undefined, error === 413 ? -32600 : -32700,
    error === 413 ? 'Request body exceeds 16 KiB.' : 'Invalid UTF-8 JSON body.', error === 413 ? 413 : 400); }
  if (!mcpObject(message) || message.jsonrpc !== '2.0' || typeof message.method !== 'string' ||
      (Object.hasOwn(message, 'id') && !mcpId(message.id)) ||
      (message.params !== undefined && !mcpObject(message.params)) ||
      Object.keys(message).some(key => !['jsonrpc', 'id', 'method', 'params'].includes(key))) {
    return mcpError(data, undefined, -32600, 'Expected one JSON-RPC request or notification.');
  }
  const {id, method} = message;
  const params = message.params || {};
  const headerVersion = request.headers.get('MCP-Protocol-Version');
  const meta = params._meta;
  const bodyVersion = mcpObject(meta) ? meta[MCP_META_PREFIX + 'protocolVersion'] : undefined;
  // Legacy initialize is the only handshake and may omit its HTTP version header.
  const version = method === 'initialize' && !bodyVersion ? params.protocolVersion : (headerVersion || bodyVersion);
  if (headerVersion && bodyVersion && headerVersion !== bodyVersion) return mcpError(data, id, -32020, 'Protocol version header/body mismatch.');
  if (!MCP_VERSIONS.includes(version)) {
    if (!version) return mcpError(data, id, -32020, 'MCP-Protocol-Version header is required.');
    return mcpError(data, id, -32022, 'Unsupported protocol version.', 400, {requested: String(version), supported: MCP_VERSIONS});
  }
  if (version === MCP_CURRENT) {
    const methodHeader = request.headers.get('Mcp-Method');
    if (!headerVersion || headerVersion !== bodyVersion || methodHeader !== method || /[^\x20-\x7e]/.test(methodHeader || '')) {
      return mcpError(data, id, -32020, 'Required metadata headers are missing or do not match the request.');
    }
    if (!mcpObject(meta) || !mcpObject(meta[MCP_META_PREFIX + 'clientCapabilities'])) {
      return mcpError(data, id, -32602, 'Per-request clientCapabilities metadata must be an object.');
    }
    const clientInfo = meta[MCP_META_PREFIX + 'clientInfo'];
    if (clientInfo !== undefined && (!mcpObject(clientInfo) || typeof clientInfo.name !== 'string' || typeof clientInfo.version !== 'string')) {
      return mcpError(data, id, -32602, 'Invalid clientInfo metadata.');
    }
    if (['tools/call', 'prompts/get', 'resources/read'].includes(method)) {
      const expected = method === 'resources/read' ? params.uri : params.name;
      if (typeof expected !== 'string' || mcpHeaderName(request.headers.get('Mcp-Name')) !== expected) {
        return mcpError(data, id, -32020, 'Mcp-Name header is missing, malformed or does not match the request.');
      }
    }
  } else if (method !== 'initialize' && headerVersion !== MCP_LEGACY) {
    return mcpError(data, id, -32020, 'Legacy requests after initialize require MCP-Protocol-Version.');
  }
  if (!Object.hasOwn(message, 'id')) {
    if (version === MCP_LEGACY && method === 'notifications/initialized') return mcpResponse(data, 202);
    return mcpError(data, undefined, -32601, 'Unsupported notification.', 400);
  }
  const invalidParams = () => mcpError(data, id, -32602, 'Parameters do not match the documented schema.');
  const only = fields => Object.keys(params).every(key => key === '_meta' || fields.includes(key));
  if (method === 'initialize' && version === MCP_LEGACY) {
    if ((headerVersion && headerVersion !== MCP_LEGACY) || !only(['protocolVersion', 'capabilities', 'clientInfo']) ||
        params.protocolVersion !== MCP_LEGACY || !mcpObject(params.capabilities) || !mcpObject(params.clientInfo) ||
        typeof params.clientInfo.name !== 'string' || typeof params.clientInfo.version !== 'string') return invalidParams();
    return mcpResult(data, id, version, {protocolVersion: MCP_LEGACY, capabilities: {tools: {}},
      serverInfo: {...data.mcp.contract.serverInfo, version: data.mcp.contract.serverInfo.version + '+' + data.revision}});
  }
  if (method === 'server/discover' && version === MCP_CURRENT) {
    if (!only([])) return invalidParams();
    return mcpResult(data, id, version, {supportedVersions: MCP_VERSIONS, capabilities: {tools: {}}, ttlMs: 0, cacheScope: 'public'});
  }
  if (method === 'ping' && version === MCP_LEGACY) {
    if (!only([])) return invalidParams();
    return mcpResult(data, id, version, {});
  }
  if (method === 'tools/list') {
    // This fixed three-tool catalog has no pagination cursor or continuation state.
    if (!only(['cursor']) || params.cursor !== undefined) return invalidParams();
    return mcpResult(data, id, version, {tools: data.mcp.contract.tools,
      ...(version === MCP_CURRENT ? {ttlMs: 0, cacheScope: 'public'} : {})});
  }
  if (method === 'tools/call') {
    if (!only(['name', 'arguments']) || typeof params.name !== 'string') return invalidParams();
    const tool = data.mcp.contract.tools.find(tool => tool.name === params.name);
    if (!tool) return mcpError(data, id, -32602, 'Unknown tool name.');
    const input = params.arguments === undefined ? {} : params.arguments;
    if (!mcpObject(input)) return invalidParams();
    const argumentError = mcpArgumentError(input, tool.inputSchema);
    if (argumentError) return mcpResult(data, id, version, {isError: true,
      content: [{type: 'text', text: argumentError}]});
    // One anonymous key shares the allowance across all tools at each Cloudflare
    // location. Never derive a key from requests, IP addresses or user identifiers.
    // A missing or failed binding fails this endpoint closed without an origin fetch.
    let allowance;
    try {
      if (typeof env?.MCP_RATE_LIMITER?.limit !== 'function') throw new Error('Unavailable limiter');
      allowance = await env.MCP_RATE_LIMITER.limit({key: 'piskor-mcp:tools-call:v1'});
      if (!mcpObject(allowance) || typeof allowance.success !== 'boolean') throw new Error('Invalid limiter result');
    } catch {
      return mcpError(data, id, -32603, 'Tool invocation limiting is temporarily unavailable.', 503);
    }
    if (!allowance.success) return mcpError(data, id, -42901, 'Tool invocation rate limit exceeded. Retry after 60 seconds.',
      429, undefined, {'Retry-After': '60'});
    const value = mcpRunTool(data.mcp, tool.name, input);
    if (value === null) return mcpResult(data, id, version, {isError: true,
      content: [{type: 'text', text: 'Project not found in the selected language.'}]});
    return mcpResult(data, id, version, {content: [{type: 'text', text: JSON.stringify(value)}], structuredContent: value});
  }
  return mcpError(data, id, -32601, 'Method not found.', version === MCP_CURRENT ? 404 : 200);
}
