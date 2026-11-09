#!/usr/bin/env node
/**
 * insomnia_api_test.mjs - log in against the BAC Ping journey using the values stored in an
 * Insomnia export, then send ONE authenticated request through the gateway of a chosen
 * environment and print the response. Node 18+ only, no npm dependencies.
 *
 * Credentials are read from env vars (never from argv, never printed):
 *   INSOMNIA_TEST_USER, INSOMNIA_TEST_PASSWORD
 *
 * Example:
 *   INSOMNIA_TEST_USER=<user> INSOMNIA_TEST_PASSWORD=<password> \
 *   node insomnia_api_test.mjs --export ~/Desktop/insomnia-export.BAC.123 --env QA \
 *     --path /security-devices/internal/device-metrics-information --query userIdentifier=<user>
 *
 * Exit codes: 0 ok (any HTTP status from the target), 2 bad usage, 3 login needs take-over,
 *             4 login failed, 5 export/env problem, 6 refused by guardrail.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';

// ---------------------------------------------------------------- args
const MULTI = new Set(['query', 'header']);
const FLAGS = new Set(['take-over', 'fresh', 'no-cache', 'print-curl', 'confirm-write',
  'allow-protected-env', 'list-envs', 'help']);

function parseArgs(argv) {
  const a = { query: [], header: [] };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (!t.startsWith('--')) fail(2, `Unexpected argument: ${t}`);
    const k = t.slice(2);
    if (FLAGS.has(k)) { a[k] = true; continue; }
    const v = argv[++i];
    if (v === undefined) fail(2, `Missing value for --${k}`);
    if (MULTI.has(k)) a[k].push(v); else a[k] = v;
  }
  return a;
}

function fail(code, msg) {
  console.error(`ERROR: ${msg}`);
  process.exit(code);
}
const log = (m) => console.error(`[insomnia-api-test] ${m}`);

const HELP = `Usage: node insomnia_api_test.mjs --export <dir|file> --env <NAME> --path </p> [options]
  --export <path>      Insomnia export (directory of .yaml files, or one .yaml). Default: auto-discover
                       ($INSOMNIA_EXPORT, then ~/Desktop and ~/Downloads "insomnia-export*")
  --env <NAME>         Sub-environment name inside the export (DEV, QA, ...). Required
  --path <path>        Gateway path incl. service prefix, e.g. /security-devices/internal/x
  --method <M>         GET (default), POST, PUT, PATCH, DELETE
  --query k=v          Query param (repeatable)
  --header "K: V"      Extra header (repeatable; overrides defaults)
  --body <json>        Request body        --body-file <file>
  --user <name>        Login user (default $INSOMNIA_TEST_USER); password only via $INSOMNIA_TEST_PASSWORD
  --take-over          Allow closing an existing session of that user if Ping asks for it
  --fresh | --no-cache Ignore / do not write the cached session
  --device-json <json> Device used for login AND x-device-id (default: built-in test device)
  --channel <c>        'channel' header (default mobile)   --country <CC> (default CR)
  --accept-version <v> Accept-Version header (default 1.0.0)
  --journey <name>     Ping journey (default: highest bacJourneyLogin* found in the export)
  --print-curl         Also print a curl with tokens replaced by placeholders (for Insomnia)
  --confirm-write      Required for non-GET methods
  --allow-protected-env Required for PRE/PROD-like environments
  --list-envs          List environments found in the export and exit`;

// ---------------------------------------------------------------- insomnia export parsing
function discoverExport(explicit) {
  const cands = [explicit, process.env.INSOMNIA_EXPORT].filter(Boolean);
  for (const base of [path.join(os.homedir(), 'Desktop'), path.join(os.homedir(), 'Downloads')]) {
    if (!fs.existsSync(base)) continue;
    const hits = fs.readdirSync(base).filter((n) => /^insomnia-export/i.test(n))
      .map((n) => path.join(base, n))
      .sort((x, y) => fs.statSync(y).mtimeMs - fs.statSync(x).mtimeMs);
    cands.push(...hits);
  }
  for (const c of cands) if (c && fs.existsSync(c)) return c;
  fail(5, 'Insomnia export not found. Pass --export <dir|file> or set INSOMNIA_EXPORT.');
}

function exportFiles(p) {
  const st = fs.statSync(p);
  if (st.isFile()) return [p];
  return fs.readdirSync(p).filter((n) => /\.ya?ml$/i.test(n)).map((n) => path.join(p, n));
}

const indentOf = (s) => s.length - s.trimStart().length;

function scalar(raw) {
  const v = raw.trim();
  if (v.startsWith("'") && v.endsWith("'") && v.length >= 2) return v.slice(1, -1).replace(/''/g, "'");
  if (v.startsWith('"') && v.endsWith('"') && v.length >= 2) {
    try { return JSON.parse(v); } catch { return v.slice(1, -1); }
  }
  return v;
}

/** Returns [{name, modified, data, file}] for every environment entry found in a workspace yaml. */
function parseEnvs(text, file) {
  const lines = text.split(/\r?\n/);
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^(\s*)- name:\s*(.+)$/);
    if (!m) continue;
    const meta = lines.slice(i + 1, i + 4).join('\n');
    if (!/id:\s*env_/.test(meta)) continue;
    const d = m[1].length;
    let modified = 0, j = i + 1;
    for (; j < lines.length; j++) {
      const mm = lines[j].match(/^\s+modified:\s*(\d+)/);
      if (mm && !modified) modified = Number(mm[1]);
      if (/^\s+data:\s*$/.test(lines[j]) && indentOf(lines[j]) === d + 2) break;
      if (indentOf(lines[j]) <= d && lines[j].trim()) { j = -1; break; }
    }
    if (j < 0 || j >= lines.length) continue;
    const data = {};
    let lastKey = null;
    for (j = j + 1; j < lines.length; j++) {
      const ln = lines[j];
      if (!ln.trim()) continue;
      const ind = indentOf(ln);
      if (ind < d + 4) break;
      const kv = ln.match(/^\s*([\w\-.]+):\s*(.*)$/);
      if (ind === d + 4 && kv) { data[kv[1]] = kv[2]; lastKey = kv[1]; }
      else if (lastKey) data[lastKey] += ' ' + ln.trim();
    }
    for (const k of Object.keys(data)) data[k] = scalar(data[k]);
    out.push({ name: m[2].trim(), modified, data, file });
  }
  return out;
}

const REQUIRED = ['url_ping_env', 'realm_ping_env', 'oauth_client_id_ping', 'ping_cookie_id', 'base_url',
  'publick_key_plain', 'private_key_plain', 'login_Api_key', 'login_helper_base_path', 'api_key'];

function loadEnvironments(files) {
  const all = [];
  for (const f of files) all.push(...parseEnvs(fs.readFileSync(f, 'utf8'), f));
  return all;
}

function pickEnv(all, name) {
  const matches = all.filter((e) => e.name.toLowerCase() === name.toLowerCase());
  if (!matches.length) {
    const names = [...new Set(all.map((e) => e.name))].join(', ') || '(none)';
    fail(5, `Environment "${name}" not found in the export. Found: ${names}`);
  }
  const complete = matches.filter((e) => REQUIRED.every((k) => e.data[k]));
  if (!complete.length) {
    const have = matches.map((e) => REQUIRED.filter((k) => !e.data[k]).join('/')).join(' | ');
    fail(5, `Environment "${name}" exists but lacks login variables (missing: ${have}).`);
  }
  complete.sort((x, y) => y.modified - x.modified);
  return complete[0];
}

function detectJourney(files) {
  let best = null;
  for (const f of files) {
    for (const m of fs.readFileSync(f, 'utf8').matchAll(/bacJourneyLogin(\d+(?:_\d+)*)/g)) {
      const ver = m[1].split('_').map(Number);
      if (!best || cmpVer(ver, best.ver) > 0) best = { name: m[0], ver };
    }
  }
  return best?.name;
}
function cmpVer(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0);
    if (d) return d;
  }
  return 0;
}

// ---------------------------------------------------------------- http helpers
const shortJson = (o) => JSON.stringify(o, (k, v) =>
  typeof v === 'string' && v.length > 80 ? `${v.slice(0, 16)}...<${v.length} chars>` : v, 2);

function cookieJar() {
  const jar = {};
  return {
    store(res) {
      for (const c of res.headers.getSetCookie?.() ?? []) {
        const [kv] = c.split(';');
        const i = kv.indexOf('=');
        jar[kv.slice(0, i)] = kv.slice(i + 1);
      }
    },
    set(k, v) { jar[k] = v; },
    header() { return Object.entries(jar).map(([k, v]) => `${k}=${v}`).join('; '); },
  };
}

async function http(url, { method = 'GET', headers = {}, body, retries = 0 } = {}) {
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(url, { method, headers, body, redirect: 'manual', signal: AbortSignal.timeout(60000) });
    if (attempt < retries && [502, 503, 504].includes(res.status)) {
      log(`HTTP ${res.status}, retrying once`);
      continue;
    }
    return res;
  }
}

// ---------------------------------------------------------------- login
const DEFAULT_DEVICE = { id: '2', platformId: '233', device_display_name: 'Samsung Galaxy S23', brand: 'Samsung',
  model: 'SM-11B', device_type: 'Android Phone', os_display: 'Android 14' };

class LoginError extends Error { constructor(code, msg) { super(msg); this.exitCode = code; } }

async function login({ env, user, password, journey, deviceB64, takeOver }) {
  const d = env.data;
  const authUrl = `${d.url_ping_env}/am/json/realms/root/realms/${d.realm_ping_env}/authenticate`;
  const jar = cookieJar();
  let tx;
  const hdr = () => ({
    'Accept-API-Version': 'resource=2.1, protocol=1.0', 'Content-Type': 'application/json',
    'User-Agent': 'insomnia/10.1.1', ...(tx ? { 'x-forgerock-transactionid': tx } : {}),
    ...(jar.header() ? { Cookie: jar.header() } : {}),
  });
  const post = async (url, body) => {
    const r = await http(url, { method: 'POST', headers: hdr(), body: body ? JSON.stringify(body) : undefined });
    jar.store(r);
    const text = await r.text();
    let json; try { json = JSON.parse(text); } catch { json = { raw: text.slice(0, 300) }; }
    return { status: r.status, headers: r.headers, json };
  };

  // 1. init
  let r = await post(`${authUrl}?authIndexType=service&authIndexValue=${journey}`);
  if (r.status !== 200 || !r.json.authId) throw new LoginError(4, `Init login failed (HTTP ${r.status}): ${shortJson(r.json).slice(0, 300)}`);
  tx = r.headers.get('x-forgerock-transactionid');
  log(`1/6 journey ${journey} started`);

  // 2. choice (Login) + public key + device
  r = await post(authUrl, { authId: r.json.authId, stage: 'Login', callbacks: [
    { type: 'ChoiceCallback', output: [{ name: 'prompt', value: 'Elige una opcion:' }, { name: 'choices', value: ['Login', 'device_binding'] }, { name: 'defaultChoice', value: 0 }], input: [{ name: 'IDToken1', value: 0 }], _id: 0 },
    { type: 'NameCallback', output: [{ name: 'prompt', value: 'Key' }], input: [{ name: 'IDToken2', value: d.publick_key_plain }], _id: 1 },
    { type: 'NameCallback', output: [{ name: 'prompt', value: 'deviceId' }], input: [{ name: 'IDToken3', value: deviceB64 }], _id: 2 },
    { type: 'MetadataCallback', output: [{ name: 'data', value: {} }], _id: 3 }] });
  if (r.status !== 200 || !r.json.authId) throw new LoginError(4, `Choice step failed (HTTP ${r.status}): ${shortJson(r.json).slice(0, 300)}`);
  log('2/6 device + public key registered');

  // 3. user / password
  r = await post(authUrl, { authId: r.json.authId, stage: 'Login', callbacks: [
    { type: 'NameCallback', output: [{ name: 'prompt', value: 'User Name' }], input: [{ name: 'IDToken1', value: user }], _id: 0 },
    { type: 'PasswordCallback', output: [{ name: 'prompt', value: 'Password' }], input: [{ name: 'IDToken2', value: password }], _id: 1 },
    { type: 'MetadataCallback', output: [{ name: 'data', value: {} }], _id: 2 }] });
  if (r.status !== 200) throw new LoginError(4, `Credentials rejected (HTTP ${r.status}): ${shortJson(r.json).slice(0, 300)}`);
  let meta = r.json.callbacks?.[0]?.output?.[0]?.value;
  if (!r.json.authId && !r.json.tokenId) throw new LoginError(4, `Login step returned no authId: ${shortJson(r.json).slice(0, 300)}`);

  // 3.1 optional take over
  if (meta?.metadata?.require === 'TAKE_OVER_SESSION_DECISION') {
    if (!takeOver) {
      throw new LoginError(3, `User "${user}" already has an active session. Re-run with --take-over to close it (this logs the user out of the other device/app).`);
    }
    log('3/6 existing session found -> taking it over (other session is closed)');
    r = await post(authUrl, { authId: r.json.authId, stage: 'Login', callbacks: [
      { type: 'MetadataCallback', output: [{ name: 'data', value: { status: { retryLimit: '8', attempt: '1', result: 'OK', error: '', description: 'La sesion del usuario ya existe ' }, metadata: { journeyName: 'LOGIN', require: 'TAKE_OVER_SESSION_DECISION' } } }], _id: 3 },
      { type: 'ChoiceCallback', output: [{ name: 'prompt', value: 'Take Session:' }, { name: 'choices', value: ['False', 'True'] }, { name: 'defaultChoice', value: 0 }], input: [{ name: 'IDToken2', value: 1 }], _id: 4 }] });
    if (r.status !== 200) throw new LoginError(4, `Take-over failed (HTTP ${r.status}): ${shortJson(r.json).slice(0, 300)}`);
    meta = r.json.callbacks?.[0]?.output?.[0]?.value;
  } else {
    log('3/6 credentials accepted (no previous session)');
  }

  // session key (RSA) -> helper
  const encKey = meta?.metadata?.sessionKey;
  let sessionKey = '';
  if (encKey) {
    const priv = crypto.createPrivateKey({ key: Buffer.from(d.private_key_plain, 'base64'), format: 'der', type: 'pkcs8' });
    const dec = crypto.privateDecrypt({ key: priv, padding: crypto.constants.RSA_PKCS1_PADDING }, Buffer.from(encKey, 'base64')).toString('utf8');
    const h = await http(`${d.login_helper_base_path}/helper`, { headers: { 'Content-Type': 'application/json', 'header-value': dec, 'x-api-key': d.login_Api_key } });
    if (h.status === 200) sessionKey = (await h.json()).value ?? '';
    else log(`helper returned HTTP ${h.status}; continuing without x-custom-session-key`);
  }

  // 4. session token (post back the callbacks received)
  const body = r.json.tokenId ? null : { authId: r.json.authId, callbacks: r.json.callbacks };
  let tokenId = r.json.tokenId;
  if (body) {
    const r4 = await post(authUrl, body);
    tokenId = r4.json.tokenId;
    if (!tokenId) throw new LoginError(4, `Session token step failed (HTTP ${r4.status}): ${shortJson(r4.json).slice(0, 300)}`);
  }
  jar.set(d.ping_cookie_id, tokenId);
  log('4/6 session token obtained');

  // 5. authorize (PKCE)
  const verifier = crypto.randomBytes(72).toString('base64url').slice(0, 96);
  const challenge = crypto.createHash('sha256').update(verifier).digest('base64url');
  const redirect = 'https://sdk.baccredomatic.com/callback';
  const q = new URLSearchParams({ client_id: d.oauth_client_id_ping, redirect_uri: redirect, response_type: 'code',
    state: crypto.randomUUID(), prompt: 'none', code_challenge: challenge, code_challenge_method: 'S256' });
  const base = `${d.url_ping_env}/am/oauth2/realms/root/realms/${d.realm_ping_env}`;
  const a = await http(`${base}/authorize?${q}`, { headers: { Cookie: jar.header() } });
  const code = new URL(a.headers.get('location') || '', 'https://x').searchParams.get('code');
  if (!code) throw new LoginError(4, `Authorize returned no code (HTTP ${a.status}).`);
  log('5/6 authorization code obtained');

  // 6. token
  const t = await http(`${base}/access_token`, { method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded', Cookie: jar.header() },
    body: new URLSearchParams({ client_id: d.oauth_client_id_ping, code, grant_type: 'authorization_code', redirect_uri: redirect, code_verifier: verifier }) });
  const tj = await t.json().catch(() => ({}));
  if (!tj.access_token) throw new LoginError(4, `Token endpoint failed (HTTP ${t.status}).`);
  log('6/6 access token obtained');
  return { accessToken: tj.access_token, tokenId, sessionKey, pingCookie: d.ping_cookie_id };
}

function jwtExp(token) {
  try { return JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString()).exp * 1000; } catch { return Date.now() + 300000; }
}

// ---------------------------------------------------------------- cache
function cacheFile(envName, user, baseUrl) {
  const h = crypto.createHash('sha1').update(`${envName}|${user}|${baseUrl}`).digest('hex').slice(0, 16);
  return path.join(os.tmpdir(), 'insomnia-api-test', `${h}.json`);
}
function readCache(f) {
  try {
    const c = JSON.parse(fs.readFileSync(f, 'utf8'));
    if (c.exp - 60000 > Date.now()) return c;
  } catch { /* none */ }
  return null;
}
function writeCache(f, c) {
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, JSON.stringify(c), { mode: 0o600 });
}

// ---------------------------------------------------------------- main
const args = parseArgs(process.argv.slice(2));
if (args.help) { console.log(HELP); process.exit(0); }

const exportPath = discoverExport(args.export);
const files = exportFiles(exportPath);
const envs = loadEnvironments(files);

if (args['list-envs']) {
  for (const e of envs) {
    const ok = REQUIRED.every((k) => e.data[k]) ? 'login-ready' : 'incomplete';
    console.log(`${e.name}\t${ok}\t${path.basename(e.file)}\t${e.data.base_url ?? ''}`);
  }
  process.exit(0);
}

if (!args.env) fail(2, '--env is required (use --list-envs to see the options).');
if (!args.path) fail(2, '--path is required (gateway path including the service prefix).');
const method = (args.method || 'GET').toUpperCase();
if (method !== 'GET' && !args['confirm-write']) fail(6, `${method} changes data: ask the user to confirm and re-run with --confirm-write.`);
if (/(^|[^a-z])(pre|prd|prod|production|uat)([^a-z]|$)/i.test(args.env) && !args['allow-protected-env']) {
  fail(6, `Environment "${args.env}" looks protected. Only run after explicit user approval, with --allow-protected-env.`);
}

const user = args.user || process.env.INSOMNIA_TEST_USER;
const password = process.env.INSOMNIA_TEST_PASSWORD;
if (!user) fail(2, 'Login user missing: pass --user or set INSOMNIA_TEST_USER.');

const env = pickEnv(envs, args.env);
const baseUrl = env.data.base_url.replace(/\/$/, '');
const journey = args.journey || detectJourney(files) || 'bacJourneyLogin2_7_6';
const device = args['device-json'] ? JSON.parse(args['device-json']) : DEFAULT_DEVICE;
const deviceB64 = Buffer.from(JSON.stringify(device)).toString('base64');
log(`export=${path.basename(exportPath)} env=${env.name} base=${baseUrl} journey=${journey} user=${user}`);

const cf = cacheFile(env.name, user, baseUrl);
let session = args.fresh ? null : readCache(cf);
if (session && session.deviceB64 !== deviceB64) session = null;
if (session) {
  log('reusing cached session (use --fresh to log in again)');
} else {
  if (!password) fail(2, 'Password missing: set INSOMNIA_TEST_PASSWORD (never pass it in argv).');
  try {
    session = await login({ env, user, password, journey, deviceB64, takeOver: !!args['take-over'] });
  } catch (e) {
    if (e instanceof LoginError) fail(e.exitCode, e.message);
    throw e;
  }
  session.exp = jwtExp(session.accessToken);
  session.deviceB64 = deviceB64;
  if (!args['no-cache']) writeCache(cf, session);
}

// request
const url = new URL(baseUrl + (args.path.startsWith('/') ? args.path : '/' + args.path));
for (const kv of args.query) {
  const i = kv.indexOf('=');
  url.searchParams.append(kv.slice(0, i), kv.slice(i + 1));
}
const headers = {
  'Accept-Version': args['accept-version'] || '1.0.0', 'Content-Type': 'application/json',
  channel: args.channel || 'mobile', country: args.country || 'CR', 'x-device-id': deviceB64,
  traceparent: `00-${crypto.randomBytes(16).toString('hex')}-${crypto.randomBytes(8).toString('hex')}-01`,
  Authorization: `Bearer ${session.accessToken}`, 'X-Custom-Token': session.accessToken,
  'x-api-key': env.data.api_key, Cookie: `${session.pingCookie}=${session.tokenId}`,
  ...(session.sessionKey ? { 'x-custom-session-key': session.sessionKey } : {}),
};
for (const h of args.header) {
  const i = h.indexOf(':');
  headers[h.slice(0, i).trim()] = h.slice(i + 1).trim();
}
let body;
if (args['body-file']) body = fs.readFileSync(args['body-file'], 'utf8');
else if (args.body) body = args.body;

const t0 = Date.now();
const res = await http(url, { method, headers, body, retries: method === 'GET' ? 1 : 0 });
const text = await res.text();
const ms = Date.now() - t0;

console.log(`REQUEST  ${method} ${url.toString()}`);
console.log(`STATUS   ${res.status}`);
console.log(`TIME     ${ms} ms`);
console.log('RESPONSE');
try { console.log(JSON.stringify(JSON.parse(text), null, 2)); } catch { console.log(text.slice(0, 4000)); }

if (args['print-curl']) {
  const redact = { Authorization: 'Bearer <access_token>', 'X-Custom-Token': '<access_token>', 'x-api-key': '<api_key de la env>',
    Cookie: `${session.pingCookie}=<tokenId>`, 'x-custom-session-key': '<session_key>' };
  const lines = [`curl --request ${method} \\`, `  --url '${url.toString()}' \\`];
  for (const [k, v] of Object.entries(headers)) lines.push(`  --header '${k}: ${redact[k] ?? v}' \\`);
  if (body) lines.push(`  --data '${body.replace(/'/g, "'\\''")}'`); else lines[lines.length - 1] = lines[lines.length - 1].replace(/ \\$/, '');
  console.log('\nCURL (tokens redacted)\n' + lines.join('\n'));
}
