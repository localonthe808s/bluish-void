// Cloudflare Worker: a reliable clock for the Kalshi daily job.
//
// WHY THIS EXISTS.  GitHub queues scheduled workflows on a best-effort basis and
// skips most of them under load: on the job's first day it fired 2 of ~10 slots,
// and never once in the 6pm window that writes the day's final call. Cloudflare
// cron triggers actually fire. So Cloudflare keeps the time and GitHub still does
// the work.
//
// WHY IT DOES NOT DO THE WORK ITSELF.  The forecast lives in
// _kalshi/kalshi_daily.py — five-model consensus, per-model rolling bias, a
// measured spread, the climate-day floor. Re-implementing that in JS would fork
// it, and the two copies would drift apart on the first change. This worker only
// presses the button.
//
// SETUP (all in your hands, no secrets in this repo):
//   1. Create a GitHub fine-grained personal access token
//        Settings -> Developer settings -> Personal access tokens -> Fine-grained
//        Repository access: only localonthe808s/bluish-void
//        Repository permissions: Actions = Read and write   (nothing else)
//   2. cd _kalshi/cron-worker && wrangler secret put GH_TOKEN
//        (paste the token when prompted; it is stored by Cloudflare, never here)
//   3. wrangler deploy
//
// Check it: GET the worker's URL for a status page. It never triggers anything —
// an open trigger endpoint is an invitation to abuse — so use `wrangler tail` or
// the Actions tab to watch the dispatches land.

import { pushAll, PUSH_KEY, vapidPublic } from './webpush.js';
const OWNER = 'localonthe808s';
const REPO = 'bluish-void';
const WORKFLOW = 'kalshi-nyc.yml';
const WORKFLOW_FAST = 'kalshi-nyc-fast.yml';   // Central Park alone, on the other five-minute marks
const REF = 'main';

// NYC sunset for the UTC date of `d` (NOAA's simple solar algorithm; within ~1 min -- the truth run starts early and
// samples for 20 minutes, so a minute either way does not matter).
// the evening's sunset at (lat, lon) for the local date of `d` (Wikipedia's sunrise equation, longitude east-positive; ~1 min)
function sunsetUTC(d, lat, lon, utcOff) {
  const rad = Math.PI / 180, loc = new Date(d.getTime() + utcOff * 3600000);
  const n = Math.round((Date.UTC(loc.getUTCFullYear(), loc.getUTCMonth(), loc.getUTCDate(), 12) - Date.UTC(2000, 0, 1, 12)) / 864e5);
  const Js = n - lon / 360, M = (357.5291 + 0.98560028 * Js) % 360;
  const C = 1.9148 * Math.sin(M * rad) + 0.02 * Math.sin(2 * M * rad) + 0.0003 * Math.sin(3 * M * rad), L = (M + C + 180 + 102.9372) % 360;
  const Jt = 2451545 + Js + 0.0053 * Math.sin(M * rad) - 0.0069 * Math.sin(2 * L * rad);
  const dec = Math.asin(Math.sin(L * rad) * Math.sin(23.44 * rad));
  const w = Math.acos((Math.sin(-0.833 * rad) - Math.sin(lat * rad) * Math.sin(dec)) / (Math.cos(lat * rad) * Math.cos(dec)));
  return new Date((Jt + w / (2 * Math.PI) - 2440587.5) * 864e5);
}

async function dispatch(env, workflow, inputs) {
  if (!env.GH_TOKEN) {
    return { ok: false, status: 0, detail: 'GH_TOKEN secret is not set' };
  }
  const url = `https://api.github.com/repos/${OWNER}/${REPO}` +
              `/actions/workflows/${workflow || WORKFLOW}/dispatches`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GH_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      // GitHub rejects API requests without one
      'User-Agent': 'bluishvoid-kalshi-cron'
    },
    body: JSON.stringify(inputs ? { ref: REF, inputs } : { ref: REF })
  });
  // 204 No Content is success here; anything else carries a reason worth logging
  const detail = res.status === 204 ? '' : (await res.text()).slice(0, 300);
  return { ok: res.status === 204, status: res.status, detail };
}

// ---------------------------------------------------------------- PRIVATE ----
// GET /positions -- what the account actually holds, for the panel.
//
// WHY IT LIVES HERE AND NOT IN THE REPO. bluishvoid.com is GitHub Pages: every
// file it serves is world-readable, and a JS gate or an overlay on the popup is
// decoration -- `curl` never touches the page. Anything the browser can show
// without a server checking who is asking IS public. So positions are not baked
// into kalshi_*.json at all. They are fetched here, behind a token, by a worker
// that already holds secrets and sits on a domain we control.
//
// The threat this actually addresses is a stranger reading a public URL. A token
// in localStorage does not defend against someone using the owner's own browser,
// and is not claimed to.
//
// SETUP (three secrets, none of them in this repo):
// THE KEY MUST BE READ-ONLY. Kalshi scopes API keys, and this worker only ever
// reads: grant `read` and nothing else. `write::trade` and `write::transfer` are
// what would let a leaked PANEL_TOKEN place orders or move money, and nothing
// here needs them. Kalshi does not document a per-endpoint scope for
// /portfolio/positions; `read` is the parent of the read endpoints, so it is the
// right grant, and a 403 from this endpoint would be the signal it is not.
//
//   wrangler secret put KALSHI_API_KEY_ID     the key's uuid
//   wrangler secret put KALSHI_PRIVATE_KEY    the PEM, newlines and all
//   wrangler secret put PANEL_TOKEN           any long random string you invent
//
// Kalshi signs with RSA-PSS/SHA-256 over `timestamp + METHOD + path`, salt length
// equal to the digest (32). The query string is NOT covered -- the same rule the
// Python side documents, and getting it wrong returns a 401 that looks like a bad
// key.
const KALSHI = 'https://api.elections.kalshi.com';

function pemToDer(pem) {
  const txt = pem.replace(/\\n/g, '\n');
  // Kalshi hands out an RSA_PRIVATE_KEY, which is PKCS#1. Python's
  // load_pem_private_key takes either, so the GitHub job never noticed.
  // WebCrypto takes PKCS#8 ONLY, and rejects PKCS#1 with a DataError that
  // surfaces here as an unexplained 502. Say what is wrong instead.
  if (/BEGIN RSA PRIVATE KEY/.test(txt)) {
    throw new Error('private key is PKCS#1; WebCrypto needs PKCS#8. Convert it: '
      + 'openssl pkcs8 -topk8 -nocrypt -in kalshi-key.pem -out kalshi-key-pkcs8.pem');
  }
  const b64 = txt.replace(/-----[A-Z ]+-----/g, '').replace(/\s+/g, '');
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}

// THE CPU BUDGET (2026-10-05). The free plan allows 10 ms of CPU per invocation, and an idle tick already spends 4-5.
// From 2026-10-03 the dark-flow watcher signed every call -- one per range, ~7 a minute -- and each one re-imported
// the key and ran a fresh RSA signature: 513 of 1,367 ticks were killed for CPU in one day, every minute from 9 AM to
// 8 PM ET. So the imported key lives for the isolate, and a signature is reused for the same path for a few seconds:
// it covers timestamp + GET + path and NOT the query, so the six trades calls in one tick are the same message.
// A reused signature that comes back 401 is dropped and the call is signed fresh, once.
let _kKey = null, _kPem = null;
const _kSig = new Map();                       // path -> { ts, sig }
const KSIG_REUSE_MS = 5000;
async function kalshiSig(env, path, fresh) {
  if (_kPem !== env.KALSHI_PRIVATE_KEY) {
    _kKey = await crypto.subtle.importKey(
      'pkcs8', pemToDer(env.KALSHI_PRIVATE_KEY),
      { name: 'RSA-PSS', hash: 'SHA-256' }, false, ['sign']);
    _kPem = env.KALSHI_PRIVATE_KEY; _kSig.clear();
  }
  const hit = _kSig.get(path);
  if (!fresh && hit && Date.now() - Number(hit.ts) < KSIG_REUSE_MS) return { ...hit, reused: true };
  const ts = String(Date.now());
  const sig = await crypto.subtle.sign(
    { name: 'RSA-PSS', saltLength: 32 }, _kKey,
    new TextEncoder().encode(ts + 'GET' + path));
  const out = { ts, sig: btoa(String.fromCharCode(...new Uint8Array(sig))) };
  _kSig.set(path, out);
  return out;
}

async function kalshiGet(env, path, query) {
  for (let fresh = false; ; fresh = true) {
    const s = await kalshiSig(env, path, fresh);
    const res = await fetch(KALSHI + path + (query || ''), {
      headers: {
        'KALSHI-ACCESS-KEY': env.KALSHI_API_KEY_ID,
        'KALSHI-ACCESS-TIMESTAMP': s.ts,
        'KALSHI-ACCESS-SIGNATURE': s.sig,
        'Accept': 'application/json',
        'User-Agent': 'bluishvoid-kalshi-cron'
      }
    });
    if (res.status === 401 && s.reused) { console.log(`[kalshi] reused signature refused on ${path}; signing fresh`); _kSig.delete(path); continue; }
    if (!res.ok) throw new Error('kalshi ' + path + ' -> ' + res.status);
    return res.json();
  }
}

// Constant-time-ish compare, so a failure does not leak the token by timing.
// BOTH SIDES ARE TRIMMED: a secret pasted into a dashboard field very often
// carries a trailing newline, and comparing lengths first turns that invisible
// character into a flat 401 that looks exactly like a wrong token.
function tokenOk(given, want) {
  given = String(given || '').trim();
  want = String(want || '').trim();
  if (!want || !given || given.length !== want.length) return false;
  let d = 0;
  for (let i = 0; i < given.length; i++) d |= given.charCodeAt(i) ^ want.charCodeAt(i);
  return d === 0;
}

function cors(origin) {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Headers': 'authorization, content-type',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin'
  };
}
const ALLOWED = 'https://bluishvoid.com';

async function obsLead(request, env) {
  // PUBLIC, unlike /obs. This returns aggregates and no raw rows, it is one KV
  // get rather than a namespace listing, and the page has to reach it on a plain
  // load -- a token in client JS is not a token. The raw trail stays gated.
  if (!env.OBS) {
    return new Response(JSON.stringify({ error: 'no KV binding' }), {
      status: 503, headers: { 'content-type': 'application/json', ...cors(ALLOWED) } });
  }
  const sum = await env.OBS.get(LEAD_KEY, { type: 'json' });
  return new Response(JSON.stringify(sum || { days: {}, ticks: 0 }), {
    headers: {
      'content-type': 'application/json; charset=utf-8',
      // a tick is five minutes; there is no point re-asking sooner
      'cache-control': 'public, max-age=120',
      ...cors(ALLOWED)
    } });
}


async function obsDump(request, env) {
  // Behind the same token as /positions. The trail is not secret, but an open
  // endpoint that lists a KV namespace is a free way for anyone to burn the
  // day's read quota and blind the study.
  const url = new URL(request.url);
  const given = (request.headers.get('authorization') || '').replace(/^Bearer\s+/i, '')
                || url.searchParams.get('t') || '';
  if (env.VIEWER_TOKEN && tokenOk(given, env.VIEWER_TOKEN)) {   /* a viewer key never sees the account */
    return new Response(JSON.stringify({ error: 'viewer' }), { status: 403, headers: { 'content-type': 'application/json', ...cors(ALLOWED) } });
  }
  if (!tokenOk(given, env.PANEL_TOKEN)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), {
      status: 401, headers: { 'content-type': 'application/json', ...cors(ALLOWED) } });
  }
  if (!env.OBS) {
    return new Response(JSON.stringify({ error: 'no KV binding' }), {
      status: 503, headers: { 'content-type': 'application/json', ...cors(ALLOWED) } });
  }
  // `since` is a plain ISO prefix, so obs_lead.py can pull only what it has not
  // seen. KV keys sort lexicographically and the timestamp does too.
  const since = url.searchParams.get('since') || '';
  const out = [];
  let cursor;
  do {
    const page = await env.OBS.list({ prefix: 'obs:', cursor, limit: 1000 });
    for (const k of page.keys) {
      if (since && k.name <= `obs:${since}`) continue;
      out.push(k.name);
    }
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor && out.length < 4000);
  out.sort();
  // JSONL, matching what obs_log.py writes locally, so one reader handles both.
  const body = [];
  for (const name of out.slice(0, 2000)) {
    const v = await env.OBS.get(name);
    if (!v) continue;
    try { for (const r of JSON.parse(v)) body.push(JSON.stringify(r)); } catch (e) { /* skip */ }
  }
  return new Response(body.join('\n') + '\n', {
    headers: { 'content-type': 'application/x-ndjson; charset=utf-8', ...cors(ALLOWED) } });
}


async function positions(request, env) {
  const url = new URL(request.url);
  const given = (request.headers.get('authorization') || '').replace(/^Bearer\s+/i, '')
                || url.searchParams.get('t') || '';
  if (env.VIEWER_TOKEN && tokenOk(given, env.VIEWER_TOKEN)) {   /* a viewer key never sees the account */
    return new Response(JSON.stringify({ error: 'viewer' }), { status: 403, headers: { 'content-type': 'application/json', ...cors(ALLOWED) } });
  }
  if (!tokenOk(given, env.PANEL_TOKEN)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), {
      status: 401,
      headers: { 'content-type': 'application/json', ...cors(ALLOWED) }
    });
  }
  try {
    const [bal, pos] = await Promise.all([
      kalshiGet(env, '/trade-api/v2/portfolio/balance'),
      // count_filter=position asks the exchange for rows with a non-zero
      // position, which is the whole question here. settlement_status is NOT a
      // parameter of this endpoint -- it is on /portfolio/settlements -- and
      // sending it invites a 400 that reads like an auth failure.
      kalshiGet(env, '/trade-api/v2/portfolio/positions',
                '?count_filter=position&limit=500')
    ]);
    const cash = bal.balance_dollars != null
      ? Number(bal.balance_dollars) : Number(bal.balance || 0) / 100;
    // FIELD NAMES AND UNITS, READ FROM THE SCHEMA RATHER THAN GUESSED. The first
    // attempt used `position` and treated the money as cents; the endpoint
    // answered with nulls and zeroes rather than an error, which is the worst
    // kind of wrong. The real names are position_fp (signed: negative is NO) and
    // *_dollars, and the dollar fields are fixed-point STRINGS already in
    // dollars -- dividing by 100 was inventing a hundredfold error.
    const num = (v) => { const x = Number(v); return isFinite(x) ? x : 0; };
    const held = (pos.market_positions || [])
      .map((m) => {
        const n = num(m.position_fp !== undefined ? m.position_fp : m.position);
        return {
          ticker: m.ticker,
          side: n > 0 ? 'yes' : 'no',
          contracts: Math.abs(n),
          exposure: num(m.market_exposure_dollars),
          traded: num(m.total_traded_dollars),
          realized: num(m.realized_pnl_dollars),
          fees: num(m.fees_paid_dollars)
        };
      })
      .filter((h) => h.contracts !== 0);
    const exposure = held.reduce((a, h) => a + h.exposure, 0);
    return new Response(JSON.stringify({
      at: new Date().toISOString(),
      cash: Math.round(cash * 100) / 100,
      // AT COST, and named that way. market_exposure_dollars is what the
      // position cost, not what it is worth now -- calling the sum "equity"
      // said $28 while the same positions were worth about $71 on the screen.
      // Sizing wants market value, which needs live prices the panel already
      // holds: contracts x the current bid. That multiplication belongs there,
      // not here, so this returns the honest input and lets the page finish it.
      cost_basis: Math.round((cash + exposure) * 100) / 100,
      positions: held
    }), { headers: { 'content-type': 'application/json',
                     'cache-control': 'no-store', ...cors(ALLOWED) } });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 502, headers: { 'content-type': 'application/json', ...cors(ALLOWED) }
    });
  }
}

// -------------------------------------------------------- observation log ----
//
// WHY THE WORKER AND NOT THE LAPTOP.  This records TWC's
// temperatureMaxSince7Am, a running maximum with intra-hour peaks in it. It is a
// CURRENT-ONLY field: there is no archive and no backfill. If nothing asks at
// 2:35 PM, that reading does not exist afterwards -- unlike IEM daily, the METAR
// and the six-hourly groups, which can all be re-fetched for any past day. So a
// logger that stops when a lid closes loses precisely the quantity it was built
// to measure, and permanently. A laptop cannot hold this job.
//
// WHY IT DOES THE WORK HERE, when the rest of this file deliberately does not:
// the thing being measured is LEAD IN MINUTES. Dispatching a GitHub runner adds
// thirty to sixty seconds of variable startup to every timestamp, which is noise
// laid directly on top of the signal. Four fetches and a KV write is not a
// forecast model, so there is no second copy to drift.
//
// 2026-09-05 is why: Central Park peaked at 79 at 2:33 PM, the 2:51 METAR read
// 77.0 because it had already fallen back, and the market repriced "78 or below"
// from 84c to 2c at about 4:25 PM -- before the 4:43 PM climate report. max7 held
// 79 the whole time. Whether that lead is real, and whether max7's spikes (that
// same day Chicago read 86 against IEM's 83 with the market 100% on 83-84, and it
// had not retracted hours later) make it unusable, is what this decides.
const OBS_MARKETS = [
  // key,      ICAO,   IEM network, IEM station -- the three cities the sheet
  // trades (2026-09-06); the other four were dropped with the rest
  ['ny_high',  'KNYC', 'NY_ASOS', 'NYC']
  // Austin, then Las Vegas, dropped 2026-10-06 ("we're going to focus on NY HIGH and LOW"). Both were taken out of APT5
  // and ALERT_MARKETS too on 2026-10-22 (user: "remove las vegas and austin from the workers").
];
// THE 5-MINUTE FEEDS, per market. New York's settlement sensor (Central Park)
// has no public 5-minute stream, so the three airports stand in for it. Las
// Vegas settles on Harry Reid (KLAS) and Austin on Bergstrom (KAUS) -- FAA
// airports, and their 5-minute observations ARE the settlement sensor's own.
// ONE CALL FOR EVERY 5-MINUTE STATION, used by the minute tick, the obs log
// and the public /sensors endpoint. {STID: {last, at, max7, n}} in each
// market's own zone; the "at" is the reading's local HH:MM.
// withSeries (the /sensors endpoint only): every reading of the station's
// LOCAL day so far, [[minutes since midnight, F], ...], so the sheet can draw
// the trend rather than quote one number (user 2026-09-07: "a line that shows
// every 5 minute reading ... so trends are visible"). The obs log and the
// alerts never ask for it -- it would bloat every KV row twentyfold.
//
// THE SOURCE IS api.weather.gov, KEYLESS (swapped off Synoptic 2026-09-09).
// Synoptic quoted $9,100/yr with a one-year minimum to keep serving this, and
// what it was serving was NWS data with a unit conversion on it: its /sensors
// output read 104 / 102.2 / 87.8 / 78.8, which are 40 / 39 / 31 / 26 C. The
// NWS feed is the same observations at the same cadence -- 5-minute for the
// six FAA airports, hourly for KNYC and KATT, exactly as Synoptic had it --
// so the swap costs no resolution and no station.
//
// Two shape differences from the old Synoptic call, both handled below:
//   - ONE CALL PER STATION, not one for all eight. Eight subrequests, issued
//     together; a station that fails is skipped, never the whole read.
//   - NEWEST FIRST, and timestamps are UTC. Both are inverted/converted here
//     so the rest of the worker keeps seeing oldest-last readings stamped in
//     the market's own zone, which is what every caller already assumes.
const NWS_UA = 'bluishvoid-kalshi (nicolas7iana@outlook.com)';
// IOWA STATE'S MESONET, ALONGSIDE (2026-10-22). On 10-22 api.weather.gov stopped updating every New York station at
// 9:15 AM (KNYC's newest at 12:51Z, KLGA's 13:15Z) while IEM, which takes the same METARs and 5-minute rows off the
// wire, had them through the afternoon -- the panel's lines stopped at 9 AM. IEM's obhistory carries the raw ob, so the
// temperature is read from its T group (tenths of a degree C, the same digits the weather service hands back); a row
// without one falls back to IEM's whole-degree tmpf. Merged like MADIS was: minute by minute, the weather service's
// reading kept where both have one. Kept 60 s in the edge cache so the panel's minute poll does not refetch it.
// (MADIS, which ran here for Las Vegas and Austin, went with those two cities on 10-22.)
const IEM_NET = { KNYC: ['NYC', 'NY_ASOS'], KLGA: ['LGA', 'NY_ASOS'], KJFK: ['JFK', 'NY_ASOS'], KEWR: ['EWR', 'NJ_ASOS'] };
async function iemRecent(stid, days) {
  const nn = IEM_NET[stid]; if (!nn) return [];
  const key = new Request(`https://iem-cache.bluishvoid.invalid/${stid}/${days.join(',')}`);
  let cache = null;
  try { cache = caches.default; const hit = await cache.match(key); if (hit) return await hit.json(); } catch (e) { /* no cache: fetch */ }
  const rows = [];
  await Promise.all(days.map(async (day) => {
    const ac = new AbortController(), timer = setTimeout(() => ac.abort(), 8000);
    try {
      const r = await fetch(`https://mesonet.agron.iastate.edu/api/1/obhistory.json?station=${nn[0]}&network=${nn[1]}&date=${day}`,
        { signal: ac.signal, headers: { 'User-Agent': NWS_UA } });
      if (!r.ok) return;
      for (const o of ((await r.json()).data || [])) {
        if (!o || !o.utc_valid) continue;
        const t = /\bT([01])(\d{3})[01]\d{3}\b/.exec(o.raw || '');
        const c = t ? (t[1] === '1' ? -1 : 1) * Number(t[2]) / 10 : (typeof o.tmpf === 'number' ? Math.round((o.tmpf - 32) * 50 / 9) / 10 : null);
        if (c != null && isFinite(c)) rows.push([o.utc_valid, c]);
      }
    } catch (e) { /* the weather service alone */ } finally { clearTimeout(timer); }
  }));
  if (cache) { try { await cache.put(key, new Response(JSON.stringify(rows), { headers: { 'content-type': 'application/json', 'cache-control': 'max-age=60' } })); } catch (e) { /* fine */ } }
  return rows;
}
async function readSensors(recentMin, withSeries) {
  const out = {};
  const tzOf = {};
  for (const k of Object.keys(APT5)) for (const st of APT5[k].stids.split(',')) tzOf[st] = APT5[k].tz;
  const start = new Date(Date.now() - (recentMin || 720) * 60000).toISOString().replace(/\.\d+Z$/, 'Z');
  await Promise.all(Object.keys(tzOf).map(async (stid) => {
    const tz = tzOf[stid];
    try {
      // both sources at once; either can be missing. IEM is asked for the station's local today, and yesterday too when
      // the window reaches back past midnight
      const dFmt = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' });
      const iemDays = [...new Set([dFmt.format(new Date(start)), dFmt.format(new Date())])];
      const [nws, iem] = await Promise.all([
        fetch(`https://api.weather.gov/stations/${stid}/observations?start=${start}`,
          { headers: { 'User-Agent': NWS_UA, 'Accept': 'application/geo+json' } })
          .then((r) => r.ok ? r.json() : null).catch(() => null),
        iemRecent(stid, iemDays)
      ]);
      // Local calendar date and local HH:MM for a UTC stamp, in the station's
      // own zone -- the same two fields the Synoptic `obtimezone=local` form
      // used to hand back already split.
      const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' });
      const hmFmt = new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
      const today = dayFmt.format(new Date());
      // every reading from both sources as [time, Celsius]; the weather service's first, so on a minute both carry,
      // its reading is the one kept (the values are the same sensor's)
      const obs = [];
      for (const f of ((nws && nws.features) || [])) {
        const p = (f && f.properties) || {};
        const c = p.temperature && p.temperature.value;
        if (typeof c === 'number' && p.timestamp) obs.push([new Date(p.timestamp), c, 'nws']);
      }
      const t0 = new Date(start);
      for (const [t, c] of iem) { const d = new Date(t); if (d >= t0) obs.push([d, c, 'iem']); }   // the same window the weather service was asked for
      // Oldest first, so `last` ends on the newest reading the way the old
      // top-to-bottom Synoptic loop did.
      obs.sort((a, b) => a[0] - b[0] || (a[2] === 'nws' ? -1 : 1));
      let mx = null, mxAt = null, last = null, lastAt = null, n = 0, nIem = 0;
      const series = [], seen = new Set();
      for (const [d, c, src] of obs) {
        if (isNaN(d)) continue;
        const day = dayFmt.format(d), hm = hmFmt.format(d);
        // A minute can arrive twice (the :51 METAR alongside a :50 five-minute
        // row is not a dupe, but a re-issued ob is, and so is the same reading
        // from both sources). First one in wins.
        const key = day + hm;
        if (seen.has(key)) continue;
        seen.add(key);
        // TO THE HUNDREDTH, which is not spurious precision: a Celsius tenth
        // converts to an exact hundredth of a degree F (26.1 C = 78.98 F), and
        // the panel's D1 prints that second decimal because it is measured.
        // Rounding to a tenth here would throw away a real digit -- the 0.1 C
        // hourly METARs land on x.x6 and x.x8, not on a tenth of a degree F.
        const v = Math.round((c * 9 / 5 + 32) * 100) / 100;
        const hh = Number(hm.slice(0, 2));
        n++; if (src === 'iem') nIem++;
        if (day === today && hh >= 7 && (mx == null || v > mx)) { mx = v; mxAt = hm; }
        last = v; lastAt = hm;
        if (withSeries && day === today) series.push([hh * 60 + Number(hm.slice(3, 5)), v]);
      }
      if (!n) return;
      out[stid] = { max7: mx, maxAt: mxAt, last, at: lastAt, n };
      if (nIem) out[stid].iem = nIem;     // readings only IEM had
      if (withSeries) out[stid].series = series;
    } catch (e) { /* one dead station must not cost the read */ }
  }));
  return out;
}
const APT5 = {
  // KNYC rides along for the trend line: Central Park reports HOURLY (its
  // 5-minute stream is NWS-run and not in the FAA feed; MADIS is closed to us:
  // 1-minute ASOS is government-only and its public 5-minute feed lacks KNYC), so its
  // points are the hourly reports, drawn as such. Never OWN5 for NY.
  ny_high:  { stids: 'KLGA,KJFK,KEWR,KNYC', tz: 'America/New_York' }
  // Las Vegas and Austin removed 2026-10-22 (user: "remove las vegas and austin from the workers")
};

// THE STATION TRAP, and it cost a whole 45-day study before it was found.
//   v3 /wx/observations/current?icaoCode=KNYC -> Central Park   RIGHT
//   v1 /location/KNYC:9:US/observations/...   -> LaGuardia      WRONG
// Same ICAO, two endpoints, two different stations three miles and two degrees
// apart. Only the v3 current form is used here. `language` is REQUIRED: without
// it the answer is HTTP 400 with every field null, which reads like a station
// outage rather than a malformed request.
const TWC_KEY = '5c241d89f91274015a577e3e17d43370';

async function obsSnapshot(env) {
  const t = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  const rows = [];
  // One batched METAR call for all seven, rather than seven -- subrequests are
  // capped per invocation and this is the only field that batches.
  let metar = {};
  try {
    const ids = OBS_MARKETS.map((m) => m[1]).join(',');
    const r = await fetch(
      `https://aviationweather.gov/api/data/metar?ids=${ids}&format=json&hours=3`,
      { headers: { 'User-Agent': 'bluishvoid-obs-log' } });
    if (r.ok) {
      for (const m of await r.json()) {
        if (m && m.temp != null && m.icaoId) {
          const f = Math.round((m.temp * 9 / 5 + 32) * 10) / 10;
          const cur = metar[m.icaoId];
          if (!cur || m.reportTime > cur.at) metar[m.icaoId] = { at: m.reportTime, f };
        }
      }
    }
  } catch (e) { /* one dead source must not cost the tick */ }

  await Promise.all(OBS_MARKETS.map(async ([key, icao, net, stn]) => {
    const row = { t, key };
    const mt = metar[icao];
    if (mt) { row.metar = mt.f; row.metar_at = mt.at; }
    try {
      const r = await fetch('https://api.weather.com/v3/wx/observations/current'
        + `?icaoCode=${icao}&units=e&language=en-US&format=json&apiKey=${TWC_KEY}`);
      if (r.ok) {
        const j = await r.json();
        if (typeof j.temperatureMaxSince7Am === 'number') row.max7 = j.temperatureMaxSince7Am;
        if (typeof j.temperature === 'number') row.now = j.temperature;
        if (typeof j.temperatureMax24Hour === 'number') row.max24 = j.temperatureMax24Hour;
      } else { row.err_twc = `http ${r.status}`; }
    } catch (e) { row.err_twc = String(e).slice(0, 60); }
    try {
      // The station's LOCAL date, which is what IEM's daily row is keyed by --
      // asking UTC would request tomorrow for half the day in the west.
      // THE ZONE COMES FROM APT5, the one table that lists every active market (2026-09-30). This used to be its
      // own list, from the seven-city days, with no las_high in it: Las Vegas fell back to UTC, so from 5 PM Pacific
      // every snapshot was filed under TOMORROW. The day's 5-minute row froze at the last pre-5 PM tick (its 'last'
      // stuck at the day's peak, which kept the bake's day "not cooling" all evening), and tomorrow's lead row opened
      // carrying tonight's TWC maximum.
      const d = new Date().toLocaleDateString('en-CA', { timeZone: (APT5[key] && APT5[key].tz) || 'America/New_York' });
      row.day = d;
      const [Y, M, D] = d.split('-').map(Number);
      const r = await fetch('https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py'
        + `?network=${net}&stations=${stn}&year1=${Y}&month1=${M}&day1=${D}`
        + `&year2=${Y}&month2=${M}&day2=${D}&format=comma`);
      if (r.ok) {
        const txt = await r.text();
        const lines = txt.trim().split('\n');
        const head = lines[0].split(','); const col = head.indexOf('max_temp_f');
        if (col > 0 && lines.length > 1) {
          const v = parseFloat(lines[lines.length - 1].split(',')[col]);
          if (!isNaN(v)) row.iem = v;
        }
      } else { row.err_iem = `http ${r.status}`; }
    } catch (e) { row.err_iem = String(e).slice(0, 60); }
    rows.push(row);
  }));
  // THE AIRPORTS' 5-MINUTE READINGS, as a regional early warning for New York.
  // Central Park's own 5-minute stream is not public (the FAA feed carries
  // LaGuardia, JFK and Newark at 5 minutes, the park hourly -- 2026-09-09).
  // So the three airports' 5-minute maxima since 7 AM ride on the New York
  // row, to be judged against TWC's field and the settlement: when the region
  // is peaking between the hourly reports, the park usually is too.
  {
    try {
      const sens = await readSensors(720);
      for (const key of Object.keys(APT5)) {
        const row = rows.find((x) => x.key === key);
        if (!row) continue;
        row.apt5 = {};
        for (const st of APT5[key].stids.split(',')) if (sens[st]) row.apt5[st] = sens[st];
      }
    } catch (e) { /* the rows stand without it */ }
  }
  return { t, rows };
}

// THE STUDY'S RUNNING ANSWER, FOLDED IN A TICK AT A TIME.
//
// The panel cannot scan a KV namespace on a page load, and the question does not
// need raw rows to answer -- it needs, per city-day, the peak each source
// reached and WHEN IT FIRST REACHED IT. That is a few hundred bytes and it can
// be maintained incrementally, so a page view costs one KV get.
//
// "First reached" is tracked against each source's OWN running peak: if a source
// later reads higher, its clock restarts, because the quantity of interest is
// when it arrived at the value the day ends on. A day is only reported once it
// has stopped moving -- while it is still climbing, whoever is merely EARLIEST
// reads as whoever is RIGHT, which is the exact mistake this study exists to
// avoid making twice.
const LEAD_KEY = 'lead:summary';
const LEAD_SOURCES = ['max7', 'iem', 'six'];

function foldLead(sum, snap) {
  sum = sum && typeof sum === 'object' ? sum : { days: {}, first: null };
  if (!sum.first) sum.first = snap.t;
  sum.last = snap.t;
  sum.ticks = (sum.ticks || 0) + 1;
  for (const r of snap.rows) {
    if (!r.day || !r.key) continue;
    const id = `${r.key}|${r.day}`;
    const d = (sum.days[id] = sum.days[id] || {});
    // TWC's since-7-AM field carries YESTERDAY'S maximum until 7 AM local, so
    // a night-time sighting of it is not a lead (it printed "led IEM by 1196
    // min" for a value set the day before, 2026-09-06). The market's zone:
    const tz = 'America/New_York';   /* New York is the only market (Las Vegas and Austin removed 2026-10-22) */
    const lh = Number(new Intl.DateTimeFormat('en-US', { timeZone: tz, hour: 'numeric', hour12: false }).format(new Date(r.t)));
    for (const src of LEAD_SOURCES) {
      const v = r[src];
      if (typeof v !== 'number') continue;
      if (src === 'max7' && lh < 7) continue;
      const cur = d[src];
      // strictly higher restarts the clock; equal keeps the FIRST sighting
      if (!cur || v > cur.v + 1e-9) d[src] = { v, at: r.t };
    }
    d.seen = r.t;
    // the airports' 5-minute maxima ride along, latest reading per station,
    // so the public summary can show the regional picture without the raw trail
    if (r.apt5) d.apt5 = { at: r.t, s: r.apt5 };
  }
  // 30 days is far more than any analysis needs and keeps the value small
  const cutoff = new Date(Date.parse(snap.t) - 30 * 864e5).toISOString().slice(0, 10);
  for (const id of Object.keys(sum.days)) {
    if (id.split('|')[1] < cutoff) delete sum.days[id];
  }
  return sum;
}

async function logObs(env) {
  if (!env.OBS) return 'no KV binding';
  const snap = await obsSnapshot(env);
  try {
    const prev = await env.OBS.get(LEAD_KEY, { type: 'json' });
    await env.OBS.put(LEAD_KEY, JSON.stringify(foldLead(prev, snap)));
  } catch (e) { /* the trail itself still gets written below */ }
  // One key per tick. ~192 ticks a day against a 1000/day free write limit, and
  // the key sorts lexicographically because the timestamp does.
  await env.OBS.put(`obs:${snap.t}`, JSON.stringify(snap.rows), {
    expirationTtl: 60 * 60 * 24 * 120        // 120 days is far past any analysis
  });
  const ny = snap.rows.find((r) => r.key === 'ny_high');
  const apt = ny && ny.apt5 ? ' apt5 ' + Object.keys(ny.apt5).map((k) => `${k}:${ny.apt5[k].max7}`).join(' ') : ' apt5 none';
  const lead = snap.rows.filter((r) => r.max7 != null && r.iem != null && r.max7 > r.iem);
  return `${snap.rows.length} rows` + apt + (lead.length
    ? `, max7 above iem: ${lead.map((r) => `${r.key} +${(r.max7 - r.iem).toFixed(1)}`).join(' ')}`
    : '');
}

// ALERTS, so the day does not arrive as a loss. On 2026-09-05 the 79 that
// settled New York surfaced at 4:25 PM and the holder learned it from the
// balance. Every five-minute tick now looks at the things that change a held
// position and pushes a message through ntfy.sh -- a topic the phone
// subscribes to, no account, no key. Three triggers, New York only:
//   1. the climate portal's status for yesterday/today flips (preliminary,
//      official) -- the number that pays, the moment it exists;
//   2. TWC's running maximum crosses a range edge on a rung you hold;
//   3. the market on a rung you hold moves 25 points or more from where it
//      was when you were last told.
// SETUP:  wrangler secret put NTFY_TOPIC   (a long random string; subscribe to
//         https://ntfy.sh/<that string> in the ntfy app). No topic, no alerts.
// State lives in KV under alert:state; a 30-minute cool-down per message key
// stops a flapping market from paging you every five minutes.
const ALERT_KEY = 'alert:state';
const ALERT_SERIES = 'KXHIGHNY';   // kept for the status page
// the markets the alerts watch: series prefix -> the settlement station TWC
// reads (v3 current with the ICAO), its zone, and the name on the phone
const ALERT_MARKETS = [
  { series: 'KXHIGHNY',  icao: 'KNYC', tz: 'America/New_York',    name: 'Central Park' }
  // Las Vegas and Austin removed 2026-10-22
];
const ALERT_COOLDOWN_MS = 30 * 60 * 1000;

function rungBounds(m) {
  // Kalshi states open bounds strictly: less/cap 79 = 78 or below.
  const f = m.floor_strike, c = m.cap_strike, st = m.strike_type;
  if (st === 'between') return [Number(f), Number(c)];
  if (st === 'less' || st === 'less_or_equal') {
    const hi = Number(c != null ? c : f); return [null, st === 'less' ? hi - 1 : hi];
  }
  const lo = Number(f); return [st === 'greater' ? lo + 1 : lo, null];
}
function rungLabel(b) {
  if (b[0] == null) return `${b[1]} or below`;
  if (b[1] == null) return `${b[0]} or above`;
  return `${b[0]} to ${b[1]}`;
}
function inRung(v, b) {
  const r = Math.round(v);
  return (b[0] == null || r >= b[0]) && (b[1] == null || r <= b[1]);
}
/* AN ACCOUNT, NOT AN ADDRESS (2026-10-03). ntfy.sh counts an anonymous publisher's daily quota by IP, and a Worker
   publishes from Cloudflare's shared egress: from there every POST answered 429 "daily message quota reached", so no
   alert from this worker reached the phone (the 8 AM review digest, a portal alert at 08:01, all of them) while the
   state recorded them as sent. With NTFY_TOKEN (an access token from a free ntfy.sh account, `wrangler secret put
   NTFY_TOKEN`) the quota is the account's own. */
function ntfyHeaders(env, h) {
  return env.NTFY_TOKEN ? Object.assign({ 'Authorization': `Bearer ${env.NTFY_TOKEN}` }, h) : h;
}
/* ONE DELIVERY TEST PER TOKEN CHANGE (2026-10-03): after NTFY_TOKEN went in, the first tick sends one alert and logs
   ntfy's answer, so "the token works" is a 200 seen on the phone, not an assumption. Bump NTFY_TEST to re-run; the KV
   mark keeps it to one message however many ticks follow. */
const NTFY_TEST = '2026-10-13-recheck';
/* the self-test only runs before this moment, so outside a test window the ticks never read its KV mark */
const NTFY_TEST_UNTIL = Date.parse('2026-10-14T04:00:00Z');
async function ntfySelfTest(env) {
  if (!env.NTFY_TOPIC || !env.OBS) return;
  const k = `ntfy:selftest:${NTFY_TEST}`;
  if (await env.OBS.get(k)) return;
  await env.OBS.put(k, new Date().toISOString());
  const r = await fetch(`https://ntfy.sh/${env.NTFY_TOPIC}`, { method: 'POST',
    body: `Delivery test from the Kalshi worker (${env.NTFY_TOKEN ? 'token set' : 'NO TOKEN'}). If this reached your phone, worker alerts are getting through.`,
    headers: ntfyHeaders(env, { 'Title': 'Kalshi alerts: delivery test', 'Priority': 'default' }) });
  const ans = `${r.status} ${r.ok ? 'delivered' : (await r.text()).slice(0, 300)}`;
  console.log(`[ntfy-test] ${ans}`);
  await env.OBS.put(`${k}:result`, JSON.stringify({ at: new Date().toISOString(), token: !!env.NTFY_TOKEN, answer: ans }));   /* readable afterwards, not only in the live log */
}

// THE COOL-DOWN IS SAVED BEFORE THE PUSH (2026-10-07). It used to be stamped in memory here and written to KV by the
// caller at the end of its tick -- after ntfy had already been posted. On the day KV's daily write cap was reached
// (944 of the free plan's 1,000, the 90 % mail arrived at 4:58 PM) that end-of-tick put would have thrown, the
// cool-down would never have landed, and the same page would have gone out every minute until midnight UTC. Now the
// state is put under its own key FIRST; if that write fails, notify throws and nothing is posted -- a quiet minute,
// not a paging loop (the tick's own log line names it). The caller's end-of-tick put still runs; one extra write per
// alert is nothing on Workers Paid.
async function notify(env, state, key, title, body, priority, stateKey) {
  const now = Date.now();
  const last = (state.sent || {})[key] || 0;
  if (now - last < ALERT_COOLDOWN_MS) return false;
  state.sent = state.sent || {};
  state.sent[key] = now;
  await env.OBS.put(stateKey || ALERT_KEY, JSON.stringify(state));
  /* two roads to the phone (2026-10-13): our own web push to the BLUISH home-screen app, and ntfy. Either landing counts;
     both outcomes are kept in KV (push:last) so a silent failure shows up on the sheet instead of nowhere. */
  /* who sees it: dark flow and the settlement read are about the market, so every subscribed phone; everything else
     (your positions, your jobs) only your own phones */
  const aud = /^(dark|portal):/.test(key) ? 'all' : 'owner';
  const pu = await pushAll(env, { title, body, tag: key, url: /^wxdown:/.test(key) ? '/' : '/#go=kalshi' }, priority === 'urgent' || priority === 'high' ? 'high' : 'normal', aud).catch((e) => ({ sent: 0, failed: 1, note: String(e) }));
  /* ntfy dropped (user 2026-10-14): it refused every post with its daily-limit 429 since 10-03; BLUISH's own push carries them */
  try { await env.OBS.put('push:last', JSON.stringify({ at: new Date().toISOString(), title, push: pu })); } catch (_) {}
  return pu.sent > 0;
}
function localDate(offsetDays) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
}
// THE JOB WATCHDOG (2026-09-07). The nightly refit and the weekly tune are
// what make the system learn, and a failed run reported itself only through
// GitHub's e-mail. Once a day at 13:00Z the worker asks GitHub for each
// study's newest run and pages the phone when it failed or never ran -- the
// same token that dispatches the bake, the same ntfy topic as the position
// alerts. Keyed by day so a failure pages once, not every tick.
const WATCHED = [
  { wf: 'kalshi-nightly.yml', name: 'nightly refit',    maxAgeH: 30, scanLog: true },
  // kalshi-tune.yml left the list 2026-10-02: the tune runs inside the nightly refit now (manual-only file)
  { wf: 'kalshi-nyc.yml',     name: 'five-minute bake', maxAgeH: 1, scanLog: true }
];
// A GREEN RUN IS NOT A WORKING RUN (2026-09-11). main() catches each market's
// exception so one city's outage cannot stop the other two, prints
// "<key> FAILED: <error>" and exits 0 -- so the job concludes `success` and
// this watchdog saw nothing while New York died on every run for eighteen
// hours (a redacted bet crashed its scoring; 09-10 went unscored and 09-11
// never got a noon lock). The log is the only place that failure exists, so
// the watchdog reads it.
//
// PER-JOB logs, not the run's: /runs/{id}/logs is a zip, which a Worker cannot
// unpack, while /jobs/{id}/logs is plain text. Both answer with a redirect to
// a storage host, followed MANUALLY here -- the Authorization header must not
// travel to that host (it is another origin, and it answers 400 when it does).
const FAILED_RX = /^\S+Z (\S+) FAILED: (.+)$/gm;
async function logFailures(env, runId) {
  const H = { 'Authorization': `Bearer ${env.GH_TOKEN}`, 'Accept': 'application/vnd.github+json',
              'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'bluishvoid-kalshi-cron' };
  const jr = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/actions/runs/${runId}/jobs`, { headers: H });
  if (!jr.ok) return { err: `jobs api ${jr.status}` };
  const hits = [];
  for (const j of ((await jr.json()).jobs || [])) {
    if (j.status !== 'completed') continue;
    const lr = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/actions/jobs/${j.id}/logs`,
      { headers: H, redirect: 'manual' });
    const loc = lr.headers.get('location');
    // no auth header on the redirect: a different origin, and it 400s with one
    const tr = loc ? await fetch(loc) : lr;
    if (!tr.ok) { hits.push({ key: j.name, err: `log ${tr.status}` }); continue; }
    const text = await tr.text();
    FAILED_RX.lastIndex = 0;
    // The word FAILED also appears in workflow comments echoed into the log, so
    // match the bake's own shape -- "<key> FAILED: <error>" on its own line.
    let m;
    while ((m = FAILED_RX.exec(text)) !== null) hits.push({ key: m[1], err: m[2].slice(0, 120) });
  }
  return { hits };
}
async function jobWatch(env) {
  if (!env.VAPID_JWK || !env.OBS || !env.GH_TOKEN) return 'watchdog off';
  const state = (await env.OBS.get(ALERT_KEY, { type: 'json' })) || {};
  const before = JSON.stringify(state);
  const today = new Date().toISOString().slice(0, 10);
  const dow = new Date().getUTCDay();
  const out = [];
  for (const w of WATCHED) {
    if (w.weekday != null && dow !== w.weekday) continue;
    let r = null;
    try {
      const res = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${w.wf}/runs?per_page=1`,
        { headers: { 'Authorization': `Bearer ${env.GH_TOKEN}`, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'bluishvoid-kalshi-cron' } });
      if (!res.ok) { out.push(`${w.name}: api ${res.status}`); continue; }
      r = ((await res.json()).workflow_runs || [])[0] || null;
    } catch (e) { out.push(`${w.name}: ${String(e).slice(0, 60)}`); continue; }
    const ageH = r ? (Date.now() - Date.parse(r.created_at)) / 36e5 : Infinity;
    const bad = !r ? 'never ran'
      : (r.status === 'completed' && r.conclusion !== 'success') ? `last run ${r.conclusion}`
      : ageH > w.maxAgeH ? `last run ${ageH.toFixed(0)} h ago` : null;
    if (bad) {
      await notify(env, state, `job:${w.wf}:${today}`, `Kalshi ${w.name}: ${bad}`,
        `${w.wf} \u00b7 ${bad}. ${r ? r.html_url : ''}`, 'high');
      out.push(`${w.name}: ${bad} (paged)`);
      continue;
    }
    // GREEN, BUT DID EVERY MARKET SURVIVE IT? Only worth asking of a finished
    // run; a job still going has half a log.
    if (!w.scanLog || r.status !== 'completed') { out.push(`${w.name}: ok`); continue; }
    let scan;
    try { scan = await logFailures(env, r.id); }
    catch (e) { out.push(`${w.name}: ok, log unread (${String(e).slice(0, 40)})`); continue; }
    if (scan.err) { out.push(`${w.name}: ok, log unread (${scan.err})`); continue; }
    if (!scan.hits.length) { out.push(`${w.name}: ok`); continue; }
    const what = scan.hits.map((h) => `${h.key}: ${h.err}`).join('\n');
    // keyed by day like the rest, so a market that fails every five minutes
    // pages once and the message names every market that died in that run
    await notify(env, state, `jobmkt:${w.wf}:${today}`,
      `Kalshi ${w.name}: ${scan.hits.map((h) => h.key).join(', ')} failing`,
      `The run passed but ${scan.hits.length} market(s) threw inside it:\n${what}\n${r.html_url}\nThat city's file stops updating -- no lock, no score -- while the job still reports success.`,
      'high');
    out.push(`${w.name}: green but ${scan.hits.map((h) => h.key).join('/')} FAILED (paged)`);
  }
  if (JSON.stringify(state) !== before) await env.OBS.put(ALERT_KEY, JSON.stringify(state));
  return out.join(' | ');
}
// THE MORNING REVIEW DIGEST (2026-10-02, "it should improve itself daily overnight"). A cloud Claude session
// (routine "Kalshi nightly review", 10:00Z) reviews the settled day, hunts for bugs and pushes its findings --
// and any proposed fix -- to the branch claude/kalshi-review-<date>, never to main. At 12:00Z (8 AM ET) this
// reads that branch's _kalshi/reviews/latest.json and pages a short summary, or says the review never landed.
// Its own KV key (review:<date>): alert:state is shared by two other jobs in the same minute.
async function reviewDigest(env) {
  if (!env.VAPID_JWK || !env.OBS) return 'digest off';
  const day = localDate(0);
  const key = `review:${day}`;
  if (await env.OBS.get(key)) return 'already sent';
  const branch = `claude/kalshi-review-${day}`;
  let doc = null, why = '';
  try {
    // the repo is public: raw needs no token, so the GH token's scope does not matter here
    const r = await fetch(`https://raw.githubusercontent.com/${OWNER}/${REPO}/${branch}/_kalshi/reviews/latest.json?t=${Date.now()}`,
      { headers: { 'User-Agent': 'bluishvoid-kalshi-cron' } });
    if (r.ok) doc = await r.json(); else why = `no review on ${branch} (http ${r.status})`;
  } catch (e) { why = String(e).slice(0, 80); }
  let title, body, pri = 'default';
  if (!doc || doc.date !== day) {
    title = 'Kalshi nightly review: nothing landed';
    body = `${why || 'the review file is for ' + (doc && doc.date)}. The routine is at claude.ai/code/routines; the bake and the nightly tune ran on their own.`;
    pri = 'high';
  } else {
    const f = doc.findings || [];
    const fixes = f.filter((x) => x.fix);
    title = `Kalshi review: ${f.length} finding${f.length === 1 ? '' : 's'}, ${fixes.length} fix${fixes.length === 1 ? '' : 'es'} proposed`;
    body = [doc.headline || ''].concat(f.slice(0, 5).map((x) => `- [${x.severity || 'note'}] ${x.title}${x.fix ? ' (fix on branch)' : ''}`))
      .concat(fixes.length ? [`Branch ${branch} -- nothing ships until you merge it.`] : []).join('\n');
    if (f.some((x) => x.severity === 'high')) pri = 'high';
  }
  // the day's mark goes in BEFORE the post, like notify(): a put that fails after a post would repeat the digest
  await env.OBS.put(key, '1', { expirationTtl: 60 * 60 * 48 });
  const pu = await pushAll(env, { title, body, tag: 'review', url: '/#go=kalshi' }, pri === 'high' ? 'high' : 'normal', 'owner').catch(() => ({ sent: 0 }));
  return `${title} (push ${pu.sent})`;
}
async function alertTick(env, sched) {
  if (!env.VAPID_JWK || !env.OBS) return 'alerts off';
  const state = (await env.OBS.get(ALERT_KEY, { type: 'json' })) || {};
  const before = JSON.stringify(state);
  const out = [];
  /* 0. WATCH THE WEATHER-ALERTS WORKER (2026-10-14, user picked "nothing watches the watcher"): every 10 minutes ask its
     /health; a heartbeat older than 30 minutes -- or no answer -- pages the owner's phones once an hour until it is back */
  if (new Date(sched || Date.now()).getUTCMinutes() % 10 === 7) {
    let age = null, why = '';
    /* read its heartbeat straight from its KV (binding WXKV): the workers.dev fetch from this worker never reached it -- the
       first live run (11:07 UTC 2026-10-14, alertTick is off 05-10 UTC) paged "no answer" while it ran every minute fine */
    try {
      if (env.WXKV){ const b = await env.WXKV.get('beat', { type: 'json' }); if (b && b.at) age = (Date.now() - Date.parse(b.at)) / 6e4; else why = 'no heartbeat'; }
      else { const h = await (await fetch('https://bluish-wx-alerts.junkyjunkjunkjunkjunk.workers.dev/health')).json(); age = h.ageMin; }
    } catch (e) { why = 'no answer'; }
    if (age == null || age > 30) {
      const hr = new Date().toISOString().slice(0, 13);
      await notify(env, state, `wxdown:${hr}`, 'Weather alerts are down',
        age == null ? `The weather-alerts worker gave ${why || 'no heartbeat'}. Weather and hazard alerts are not being checked.` : `The weather-alerts worker last ran ${Math.round(age)} minutes ago. Weather and hazard alerts are not being checked.`, 'high');
      out.push(`wx watchdog: ${age == null ? why || 'no beat' : Math.round(age) + ' min'}`);
    }
  }
  // 1. the portal, yesterday and today -- EVERY FIVE MINUTES (2026-10-06), not every minute: two fetches a minute for a
  // status that changes a couple of times a day were a sixth of the tick's outbound requests against a 10 ms CPU budget
  // (see THE CPU BUDGET). Minute 2 of each five, off the bake and obs minutes.
  state.portal = state.portal || {};
  const portalNow = new Date(sched || Date.now()).getUTCMinutes() % 5 === 2;
  for (const off of (portalNow ? [-1, 0] : [])) {
    const day = localDate(off);
    try {
      const j = await (await fetch(`https://weather.com/kalshi/api/climate/primary?date=${day}`,
        { headers: { 'User-Agent': 'Mozilla/5.0 bluishvoid-alerts' } })).json();
      const row = (j.results || []).find((r) => r.station && r.station.icao === 'KNYC');
      if (!row) continue;
      const st = row.status, v = row.data && row.data.maxTemp;
      const was = state.portal[day];
      if (st !== 'no_report' && st !== was) {
        await notify(env, state, `portal:${day}:${st}`,
          `Central Park ${day.slice(5).replace('-', '/')} high ${v}° \u00b7 ${st}`,
          st === 'official' ? 'Official. The market settles on this.' : 'Not final yet; the official number can still change.',
          st === 'official' ? 'high' : 'default');
        out.push(`portal ${day} ${st} ${v}`);
      }
      state.portal[day] = st;
    } catch (e) { out.push(`portal ${day} err`); }
  }
  // 2+3 need the held rungs
  let held = [];
  try {
    const pos = await kalshiGet(env, '/trade-api/v2/portfolio/positions',
                                '?count_filter=position&limit=200');
    held = (pos.market_positions || [])
      .map((m) => ({ ticker: m.ticker, n: Number(m.position_fp != null ? m.position_fp : m.position) }))
      .map((h) => ({ ...h, am: ALERT_MARKETS.find((a) => h.ticker.startsWith(a.series + '-')) }))
      .filter((h) => h.n !== 0 && h.am);
  } catch (e) { out.push('positions err'); }
  /* what you hold, for darkTick: a dark burst is pushed only when it goes against one of these (2026-10-16) */
  state.held = held.map((h) => ({ tk: h.ticker, n: h.n }));
  /* 1b. THE NOON LOCK CAN BE TOO LATE (2026-10-16, user: "the high was hit really early today ... a notification when the
     noon lock may be too late"). 10-16 named YES 74 or below at 82-88c with a 10-17c edge from 7 AM; at 10:45 the price ran
     to 93c and the bet was gone an hour before the lock. Measured on 39 days of the trail: 12 days had a morning bet and
     none at noon; bets first named BEFORE 9 AM won 13 of 18 (+40% a bet), those first named 9 AM-noon 5 of 8 (-2%), and
     chasing the last morning sighting lost (-8.5%). So: once a day, 7-9 AM ET, every five minutes (minute 3, after the
     bake lands), read the five-minute bake; a bet named before the lock on a market you do not already hold is pushed. */
  const nyNow = new Date(sched || Date.now()), nyH = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', hour12: false }).format(nyNow)) % 24;
  if (nyH >= 7 && nyH < 9 && nyNow.getUTCMinutes() % 5 === 3) {
    const day = localDate(0);
    if (!(state.sent || {})[`early:${day}`]) {
      try {
        const r = await fetch(`https://raw.githubusercontent.com/${OWNER}/${REPO}/main/kalshi_ny.json?t=${Date.now()}`, { headers: { 'User-Agent': 'bluishvoid-kalshi-cron' } });
        const T = r.ok ? ((await r.json()).today || {}) : {};
        const b = T.bet, rung = b && (T.ladder || []).find((x) => x.label === b.label);
        if (T.date === day && b && !T.locked && b.price != null && !(rung && held.some((h) => h.ticker === rung.ticker))) {
          const side = b.dir === 'against' ? 'NO' : 'YES', lab = b.label;
          await notify(env, state, `early:${day}`, `Morning bet · ${side} ${lab} at ${Math.round(b.price * 100)}¢`,
            `Model ${Math.round(b.q * 100)}% on ${side}, edge ${Math.round(b.ev * 100)}¢ after the fee. The noon lock may be too late: ` +
            `bets first named before 9 AM won 13 of 18; on 12 of 39 days the bet was gone by noon.`, 'high');
          out.push(`early bet ${side} ${lab} ${b.price}`);
        }
      } catch (e) { out.push('early bet err'); }
    }
  }
  if (!held.length) {
    state.mkt = {}; state.max7 = null; state.max7by = {};
    if (JSON.stringify(state) !== before) await env.OBS.put(ALERT_KEY, JSON.stringify(state));
    return out.concat(['no watched position']).join(', ');
  }
  // TWC's running max at each held market's settlement station (v3 current
  // with the ICAO is the station itself; before 7 AM local it is yesterday's)
  const max7by = {};
  for (const am of ALERT_MARKETS) {
    if (!held.some((h) => h.am === am)) continue;
    let v = null;
    try {
      const j = await (await fetch(`https://api.weather.com/v3/wx/observations/current?icaoCode=${am.icao}` +
        `&units=e&language=en-US&format=json&apiKey=${TWC_KEY}`)).json();
      if (typeof j.temperatureMaxSince7Am === 'number') v = j.temperatureMaxSince7Am;
    } catch (e) { /* no reading this tick */ }
    const lh = Number(new Intl.DateTimeFormat('en-US', { timeZone: am.tz, hour: 'numeric', hour12: false }).format(new Date()));
    max7by[am.series] = (lh < 7) ? null : v;
  }
  // THE SETTLEMENT SENSOR'S OWN 5-MINUTE READINGS, every minute. This is the
  // earliest public number there is for Las Vegas (KLAS) and Austin (KAUS):
  // the sensor the climate report is computed from, sampled twelve times an
  // hour. The market prices the hourly report; a reading here that crosses a
  // held rung's edge is known up to 55 minutes before that (2026-09-06).
  const OWN5 = {};   // was Las Vegas (KLAS) and Austin (KAUS), removed 2026-10-22; New York's sensor has no 5-minute feed
  let sens = {};
  if (held.some((h) => OWN5[h.am.series])) {
    try { sens = await readSensors(720); } catch (e) { out.push('sensors err'); }
  }
  // THE HOURLY REPORT, THE MINUTE IT PRINTS. The market prices the hourly
  // METAR and little else (minute anatomy of 2026-09-06: 0 -> 94c on 8,500
  // contracts three minutes after the 3:51 PM report read 75). The report is
  // public about a minute after the observation; this tick reads it every
  // minute and pushes the reading against the held rung before the move.
  const rep = {};
  const icaos = [...new Set(held.map((h) => h.am.icao))];
  if (icaos.length) {
    try {
      const r = await fetch(`https://aviationweather.gov/api/data/metar?ids=${icaos.join(',')}&format=json&hours=2`,
        { headers: { 'User-Agent': 'bluishvoid-alerts' } });
      if (r.ok) {
        for (const m of await r.json()) {
          if (!m || m.temp == null || !m.icaoId) continue;
          const cur = rep[m.icaoId];
          if (!cur || m.reportTime > cur.at) rep[m.icaoId] = { at: m.reportTime, f: Math.round((m.temp * 9 / 5 + 32) * 10) / 10, raw: (m.rawOb || '').slice(0, 5) };
        }
      }
    } catch (e) { out.push('metar err'); }
  }
  state.metar = state.metar || {};
  state.own5 = state.own5 || {};
  state.mkt = state.mkt || {};
  state.max7by = state.max7by || {};
  for (const h of held) {
    const max7 = max7by[h.am.series], prevMax7 = state.max7by[h.am.series];
    let m;
    try {
      m = (await (await fetch(`${KALSHI}/trade-api/v2/markets/${h.ticker}`,
        { headers: { 'Accept': 'application/json', 'User-Agent': 'bluishvoid-alerts' } })).json()).market;
    } catch (e) { out.push(`${h.ticker} err`); continue; }
    if (!m) continue;
    /* NO ALERTS ON A DAY THAT IS OVER (user 2026-10-28, 11 PM: "i just got a notification on my bet on NY highs today, that was settled
       hours ago"). The position stays in the portfolio until Kalshi settles it the next morning, and every hourly report kept pushing --
       6:32 PM, 11 PM, 7 AM the next day. A market whose local day has ended, or that is no longer trading, gets nothing here; the
       settlement itself is the portal alert's job */
    const mDay = (() => { const t = /-(\d{2})([A-Z]{3})(\d{2})-/.exec(h.ticker); if (!t) return null;
      const mo = { JAN: '01', FEB: '02', MAR: '03', APR: '04', MAY: '05', JUN: '06', JUL: '07', AUG: '08', SEP: '09', OCT: '10', NOV: '11', DEC: '12' }[t[2]];
      return mo ? `20${t[1]}-${mo}-${t[3]}` : null; })();
    const today0 = new Intl.DateTimeFormat('en-CA', { timeZone: h.am.tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    if ((mDay && mDay < today0) || (m.status && !/^(active|open)$/i.test(m.status))) { out.push(`${h.ticker} day over, quiet`); continue; }
    const b = rungBounds(m), label = rungLabel(b), side = h.n > 0 ? 'YES' : 'NO';
    const bid = Number(m.yes_bid_dollars), ask = Number(m.yes_ask_dollars);
    const mid = (isFinite(bid) && isFinite(ask) && ask > 0) ? (bid + ask) / 2 : null;
    /* THE CONTEXT EVERY POSITION ALERT CARRIES (user 2026-10-16: "that's not enough info" after the bodies were cut to a
       bare range): how far a reading is from the range, the other live number (TWC's high or the last report), and what
       the position is worth right now at the bid. */
    const sideBid = side === 'YES' ? bid : (isFinite(ask) ? 1 - ask : NaN);
    const holdTxt = `You hold ${Math.abs(h.n)} ${side} on ${label}` + (isFinite(sideBid) && sideBid > 0 ? `, bid ${Math.round(sideBid * 100)}¢` : '') + '.';
    const rp0 = rep[h.am.icao];
    const repTxt = rp0 ? `Last report ${rp0.f}° at ${new Date(rp0.at).toLocaleTimeString('en-US', { timeZone: h.am.tz, hour: 'numeric', minute: '2-digit' })}` : '';
    const gap = (v) => { const r = Math.round(v);
      return inRung(v, b) ? `In ${label}` : (b[1] != null && r > b[1]) ? `${r - b[1]}° above ${label}` : `${b[0] - r}° below ${label}`; };
    // 3. the market moved on your rung
    if (mid != null) {
      const anchor = state.mkt[h.ticker];
      if (anchor != null && Math.abs(mid - anchor) >= 0.25) {
        const dir = mid > anchor ? 'up' : 'down';
        const good = (side === 'YES') === (mid > anchor);
        await notify(env, state, `mkt:${h.ticker}:${Math.round(mid * 4)}`,
          `${label} ${dir} ${Math.round(anchor * 100)}¢ → ${Math.round(mid * 100)}¢`,
          `${good ? 'Good' : 'Bad'} for your ${side}. ${repTxt ? repTxt + (max7 != null ? ', TWC high ' + max7 + '°' : '') + '. ' : ''}${holdTxt}`,
          good ? 'default' : 'high');
        out.push(`${h.ticker} ${anchor}->${mid}`);
        state.mkt[h.ticker] = mid;
      } else if (anchor == null) {
        state.mkt[h.ticker] = mid;
      }
    }
    // 1a. a new hourly (or special) report from the settlement station -- only one that can still matter: a DAILY HIGH is set by the
    // warmest reading, so a report below the day's high so far changes nothing (2026-10-28: the evening reports were all noise)
    const rp = rep[h.am.icao];
    state.dayHi = state.dayHi || {};
    const dh = state.dayHi[h.ticker], runHi = Math.max(dh && dh.d === mDay ? dh.v : -999, max7 != null ? max7 : -999);
    const newHigh = rp && rp.f >= runHi - 0.5;
    if (rp) state.dayHi[h.ticker] = { d: mDay, v: Math.max(runHi, rp.f) };
    if (rp && state.metar[h.am.icao] !== rp.at && newHigh) {
      const inNow = inRung(rp.f, b), above = b[1] != null && rp.f > b[1] + 0.5, below = b[0] != null && rp.f < b[0] - 0.5;
      const bad = (side === 'YES') ? (above) : (inNow);
      const local = new Date(rp.at).toLocaleTimeString('en-US', { timeZone: h.am.tz, hour: 'numeric', minute: '2-digit' });
      await notify(env, state, `metar:${h.ticker}:${rp.at}`,
        `${h.am.name} ${rp.f}° \u00b7 ${local}${rp.raw.trim() === 'SPECI' ? ' special' : ''}`,
        `${gap(rp.f)}${bad ? ', bad for your ' + side : ''}. ${max7 != null ? 'TWC high so far ' + max7 + '°. ' : ''}${holdTxt}`,
        bad ? 'urgent' : 'default');
      out.push(`metar ${h.am.icao} ${rp.f}`);
    }
    // 1b. the settlement sensor itself crossed, or is about to cross, an edge
    const ownSt = OWN5[h.am.series], own = ownSt && sens[ownSt];
    if (own && own.max7 != null) {
      // A DAY'S RUNNING MAXIMUM ONLY EVER RISES, and this holds it to that.
      //
      // api.weather.gov is served from an edge cache that does not always hand
      // back the same window twice: sampled a minute apart it returned newest
      // rows of 01:05, then 01:10, then 01:05 again (2026-09-09). So the row
      // carrying the day's peak can drop out for a tick and come back. Taken at
      // face value that reads as the sensor FALLING out of the rung -- an
      // urgent alert, on a cache artifact, and a second one when it returned.
      // Synoptic answered from one response and never did this; the guard is
      // the cost of the free feed, and it is the right shape anyway.
      //
      // Keyed by the market's own local day so the peak resets at midnight
      // rather than pinning yesterday's high forever. A stored bare number is
      // the pre-2026-09-09 shape and is read as "no usable previous".
      const ownDay = new Intl.DateTimeFormat('en-CA',
        { timeZone: h.am.tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
      const rec = state.own5[ownSt];
      const prevOk = rec && typeof rec === 'object' && rec.d === ownDay && typeof rec.v === 'number';
      const prevOwn = prevOk ? rec.v : null;
      // The dip is discarded, not alerted on; only a genuine new high moves it.
      const ownMax = (prevOwn != null && prevOwn > own.max7) ? prevOwn : own.max7;
      const ownAt = (ownMax === own.max7) ? own.maxAt : rec.at;
      const wasIn = prevOwn != null ? inRung(prevOwn, b) : null, nowIn = inRung(ownMax, b);
      const wasAbove = prevOwn != null && b[1] != null && prevOwn > b[1] + 0.5;
      const nowAbove = b[1] != null && ownMax > b[1] + 0.5;
      if (prevOwn != null && (wasIn !== nowIn || wasAbove !== nowAbove)) {
        const bad = (side === 'YES') ? !nowIn : nowIn;
        await notify(env, state, `own5:${h.ticker}:${Math.round(ownMax)}`,
          `${h.am.name} sensor ${ownMax}° \u00b7 ${ownAt}`,
          `New high, ${nowIn ? 'inside' : nowAbove ? 'above' : 'below'} ${label} \u00b7 ${bad ? 'bad' : 'good'} for your ${side}. The market sees it at the next hourly report.`,
          bad ? 'urgent' : 'high');
        out.push(`own5 ${ownSt} ${prevOwn}->${ownMax}`);
      } else if (b[1] != null && ownMax <= b[1] + 0.5 && ownMax >= b[1] - 0.4 && (prevOwn == null || prevOwn < b[1] - 0.4)) {
        // within half a degree of the top edge: one warning, before it crosses
        await notify(env, state, `own5near:${h.ticker}`,
          `${h.am.name} sensor ${ownMax}° \u00b7 ${ownAt}`,
          `Within 0.5° of the top of ${label} \u00b7 you hold ${side}.`, 'high');
        out.push(`own5 near ${ownSt} ${ownMax}`);
      }
      state.own5[ownSt] = { d: ownDay, v: ownMax, at: ownAt };
    }
    // 2. TWC's running max crossed an edge of your rung
    if (max7 != null && prevMax7 != null && max7 !== prevMax7) {
      const wasIn = inRung(prevMax7, b), nowIn = inRung(max7, b);
      const wasAbove = b[1] != null && prevMax7 > b[1] + 0.5, nowAbove = b[1] != null && max7 > b[1] + 0.5;
      if (wasIn !== nowIn || wasAbove !== nowAbove) {
        const bad = (side === 'YES') ? !nowIn : nowIn;
        await notify(env, state, `max7:${h.ticker}:${max7}`,
          `${h.am.name} TWC high ${max7}°`,
          `Up from ${prevMax7}°: ${gap(max7).replace(/^In /, 'in ')}${bad ? ', bad for your ' + side : ''}. ${repTxt ? repTxt + '. ' : ''}${holdTxt}`,
          bad ? 'high' : 'default');
        out.push(`max7 ${h.am.series} ${prevMax7}->${max7}`);
      }
    }
  }
  if (state.dayHi) for (const k of Object.keys(state.dayHi)) if (!held.some((h) => h.ticker === k)) delete state.dayHi[k];   /* settled markets leave */
  for (const k of Object.keys(max7by)) if (max7by[k] != null) state.max7by[k] = max7by[k];
  for (const k of Object.keys(rep)) state.metar[k] = rep[k].at;
  // KV allows 1,000 writes a day on this plan; a minute cadence is 1,020 ticks.
  // The state only changes when something happened, so only then is it written.
  if (JSON.stringify(state) !== before) await env.OBS.put(ALERT_KEY, JSON.stringify(state));
  return out.length ? out.join(', ') : `quiet (${held.length} watched position${held.length === 1 ? '' : 's'})`;
}

// DARK FLOW (2026-10-02). The informed-flow study (_kalshi/insider_study.py, 28 days) found New York bursts of
// one-sided aggressive buying that land with NO public reading behind them ("dark") returned +2.7% (se 3.3) where
// the crowd's reactions to public readings returned -5.8% -- suggestive, unproven. This watches it live, so the
// sheet can draw it and the report can grade it on days the study never saw.
// Every minute 7 AM-8 PM ET: the minute two minutes ago, for every range of today's New York event, signed
// aggressive dollars (YES takers +, NO takers -). A minute with >= $150 one way is a BURST (about 56 a day, measured).
// It is a REACTION when a public release covers it -- a Central Park report (routine or special, +9 min), a climate
// report (+10), an NWS zone forecast or forecast discussion for New York (+10; added 2026-10-02 -- a forecast issue
// is public news, and bursts after one were being called dark), a rise in TWC's running maximum (+6) -- and DARK
// otherwise. SPLIT ORDERS (2026-10-02): a burst on the same range and side within 3 minutes of the last one is the same
// trader's order sliced, so it is folded into that burst (t1, minutes) instead of counted again. The nightly grader
// (dark_grade.py) rebuilds every day from the tape with the study's own adaptive threshold; this flat $150 is the live
// approximation the sheet draws. One KV record per day, written only
// when something changes (the free plan allows 1,000 writes a day). Public at /dark: the tape is public anyway.
/* ONE RULEBOOK WITH THE STUDY (2026-10-16): a burst is a minute whose signed aggressive money clears max($50, the 95th
   percentile of that market's minutes SO FAR today, this one included) -- dark_lib.bursts, which went causal the same day.
   It was a flat $150 here, so the sheet and the alerts showed a different set of bursts than the study graded. */
const DARK_FLOOR_USD = 50, DARK_PCTL = 0.95, DARK_ALERT_USD = 500;
const DARK_SURE_PX = 0.95;      // a burst paying this much for its side is a sweep, not dark (dark_lib.SURE_PX)
/* the triggers that carry their own jobs (wrangler.toml [triggers]; must match it character for character) */
const DARK_CRON = '* * * * *', OBS_CRON = '*/5 * * * *';
const DARK_WIN = { metar: 9, cli: 10, twc: 6, fcst: 10, apt: 15 }, DARK_MERGE_MIN = 3;
const KAPI = 'https://api.elections.kalshi.com/trade-api/v2';
function nyEventTicker(dayIso) {
  const [y, m, d] = dayIso.split('-').map(Number);
  return `KXHIGHNY-${String(y).slice(2)}${['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][m - 1]}${String(d).padStart(2, '0')}`;
}
async function kpub(env, path) {
  /* SIGNED, NOT ANONYMOUS (2026-10-03). The first live morning every tick died on "kalshi 429": Kalshi throttles
     anonymous calls from Cloudflare's shared egress (the same request from home answered 200 eight times running),
     so the record never got past fetching the market list. Signed with the worker's own READ-ONLY key the calls
     count against our account's limit instead. One retry after a short wait on a 429 either way. */
  const [p, q] = path.split('?');
  for (let i = 0; i < 2; i++) {
    try {
      if (env && env.KALSHI_API_KEY_ID && env.KALSHI_PRIVATE_KEY) return await kalshiGet(env, '/trade-api/v2' + p, q ? '?' + q : '');
      const r = await fetch(`${KAPI}${path}`, { headers: { 'User-Agent': 'bluishvoid-dark-flow', 'Accept': 'application/json' } });
      if (!r.ok) throw new Error(`kalshi ${r.status}`);
      return r.json();
    } catch (e) {
      if (i === 0 && /429/.test(String(e))) { await new Promise((res) => setTimeout(res, 1500)); continue; }
      throw e;
    }
  }
}
async function darkTick(env, sched) {
  if (!env.OBS) return 'no KV';
  const nyHour = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', hour12: false }).format(new Date(sched)));
  /* AROUND THE CLOCK (user 2026-10-17: "track the bets and pool money everything else overnight too"): was 7 AM-8 PM ET,
     and 10-15 and 10-17 were decided by a front at 1 AM, hours before the watcher woke */
  const day = localDate(0), key = `dark:${day}`;
  const rec = (await env.OBS.get(key, { type: 'json' })) || { day, event: nyEventTicker(day), markets: null, bursts: [], releases: [], twc: null };
  const before = JSON.stringify(rec);
  if (!rec.markets) {
    const j = await kpub(env, `/markets?event_ticker=${rec.event}`);
    rec.markets = (j.markets || []).map((m) => ({ tk: m.ticker, lab: rungLabel(rungBounds(m)) }));
  }
  // THE PUBLIC CLOCK, kept in the record so the sheet can draw it
  const seen = new Set(rec.releases.map((r) => r.k + r.t));
  const addRel = (k, t) => { if (!seen.has(k + t)) { rec.releases.push({ k, t }); seen.add(k + t); } };
  try {
    const mr = await fetch('https://aviationweather.gov/api/data/metar?ids=KNYC&format=json&hours=3', { headers: { 'User-Agent': 'bluishvoid-dark-flow' } });
    if (mr.ok) for (const m of await mr.json()) if (m && m.obsTime) addRel('metar', new Date(m.obsTime * 1000).toISOString());
  } catch (e) { /* the clock is best-effort; a missing release only makes a burst look dark */ }
  try {
    // one request for three products: the climate report and the two forecast products (zone forecast, discussion)
    const tx = await (await fetch('https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=CLINYC,ZFPOKX,AFDOKX&limit=8&fmt=text')).text();
    const now = new Date(sched);
    for (const m of tx.matchAll(/^(CDUS|FPUS|FXUS)\d+ K[A-Z]{3} (\d\d)(\d\d)(\d\d)\s*$/gm)) {
      const t = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), Number(m[2]), Number(m[3]), Number(m[4])));
      if (t > now) t.setUTCMonth(t.getUTCMonth() - 1);
      if (now - t < 36 * 3600e3) addRel(m[1] === 'CDUS' ? 'cli' : 'fcst', t.toISOString());
    }
  } catch (e) { /* as above */ }
  try {
    const tw = await (await fetch(`https://api.weather.com/v3/wx/observations/current?icaoCode=KNYC&units=e&language=en-US&format=json&apiKey=${TWC_KEY}`)).json();
    const v = tw && tw.temperatureMaxSince7Am;
    // THE DAY'S HIGH, NOT THE LATEST VALUE (2026-10-07). temperatureMaxSince7Am is a running max on paper, but the
    // field is blended and FLAPS: 66, 65, 66 ... On 10-07 it logged 45 "twc" releases in pairs two minutes apart, and
    // every flap was a KV write (down) and a release plus a write (up) -- most of the day's write budget, and a flap
    // back to a value the public already had is not a new reading. Only a value above the day's recorded high counts.
    /* NOT BEFORE 7:20, AND A BIG DROP IS A RESET (2026-10-16). At 7:00 the field still carries YESTERDAY's high for a
       few minutes; taken as the baseline it hid every rise on a cooler day (10-13: baseline 71 from 10-12, the day
       topped at 70, so no TWC release all day, and every burst after one was called dark). A fall of 3+ is the reset
       arriving late, not a flap: re-base without a release. */
    const nyMin = nyHour * 60 + Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', minute: 'numeric' }).format(new Date(sched)));
    if (typeof v === 'number' && nyMin >= 7 * 60 + 20) {
      if (rec.twc != null && v <= rec.twc - 3) rec.twc = v;
      else if (rec.twc == null || v > rec.twc) {
        if (rec.twc != null) addRel('twc', new Date(sched - 60000).toISOString());
        rec.twc = v;
      }
    }
  } catch (e) { /* as above */ }
  // THE MINUTE TWO MINUTES AGO, complete on every feed
  const m0 = Math.floor(sched / 60000) * 60000 - 120000, m1 = m0 + 60000;
  const covered = (t) => rec.releases.some((r) => { const a = Date.parse(r.t); return t >= a && t <= a + DARK_WIN[r.k] * 60000; });
  /* THE AIRPORTS' NEW HIGHS ARE PUBLIC TOO (2026-10-16). LaGuardia, Newark and JFK lead the park on a public 5-minute
     feed; a burst after one sets a new high for its day is a reaction. Fetched only when it can matter -- a burst to
     label this tick, or a dark one in the last 25 minutes that the feed (10-15 min behind) may now explain -- and a
     dark burst it explains is relabelled REACTION. Same definition as insider_study.apt_bumps: whole Celsius, a new
     high since 7 AM (a warm night would otherwise swallow the whole day), public for 15 minutes. */
  let aptDone = false;
  const aptCheck = async () => {
    if (aptDone) return; aptDone = true;
    const z = 'America/New_York', hrOf = (d) => Number(new Intl.DateTimeFormat('en-US', { timeZone: z, hour: 'numeric', hour12: false }).format(d)) % 24, dayOf = (d) => new Intl.DateTimeFormat('en-CA', { timeZone: z, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
    const start = day + 'T03:00:00Z';     // before local midnight in EDT and EST; the day filter below trims it
    await Promise.all(['KLGA', 'KEWR', 'KJFK'].map(async (st) => {
      try {
        const j = await (await fetch(`https://api.weather.gov/stations/${st}/observations?start=${start}`, { headers: { 'User-Agent': NWS_UA, 'Accept': 'application/geo+json' } })).json();
        const obs = ((j && j.features) || []).map((f) => [new Date(f.properties.timestamp), f.properties.temperature && f.properties.temperature.value])
          .filter((o) => typeof o[1] === 'number' && !isNaN(o[0]) && dayOf(o[0]) === day && hrOf(o[0]) >= 7).sort((a, b) => a[0] - b[0]);
        let mx = null;
        for (const [d, c] of obs) { const v = Math.round(c); if (mx != null && v > mx) addRel('apt', d.toISOString()); if (mx == null || v > mx) mx = v; }
      } catch (e) { /* best-effort, like the rest of the clock */ }
    }));
    for (const b of rec.bursts) if (b.cls === 'dark' && (covered(Date.parse(b.t)) || covered(Date.parse(b.t) + 59999))) b.cls = 'reaction';
  };
  if (rec.bursts.some((b) => b.cls === 'dark' && sched - Date.parse(b.t) < 25 * 60000)) await aptCheck();
  rec.mags = rec.mags || {}; rec.magsTo = rec.magsTo || {};
  const out = [];
  // its OWN cooldown record: alertTick reads and writes ALERT_KEY in the same minute, and two writers of one key race
  // read only when an alert might go out (2026-10-06): one KV read a minute, nearly always for nothing
  let state = null, sBefore = '', heldNow = null;
  const alertState = async () => { if (!state){ state = (await env.OBS.get('dark:alerts', { type: 'json' })) || {}; sBefore = JSON.stringify(state); } return state; };
  /* the five-minute ticks already spend most of the free plan's ~50 outbound requests (alerts + the obs log), so this
     skips them and the next tick takes both minutes */
  const mStart = (new Date(sched).getUTCMinutes() % 5 === 1) ? m0 - 60000 : m0;
  for (const mk of rec.markets) {
    let tr;
    try { tr = (await kpub(env, `/markets/trades?ticker=${mk.tk}&min_ts=${mStart / 1000}&max_ts=${m1 / 1000 - 1}&limit=1000`)).trades || []; }
    catch (e) { continue; }
    for (let mm = mStart; mm < m1; mm += 60000) {
    let net = 0, ys = 0, yn = 0, ns = 0, nn = 0, nt = 0;
    for (const t of tr) {
      const tt = Date.parse(t.created_time); if (tt < mm || tt >= mm + 60000) continue;
      const p = Number(t.yes_price_dollars), n = Number(t.count_fp); nt++;
      if (t.taker_side === 'yes') { net += n * p; ys += n * p; yn += n; } else { net -= n * (1 - p); ns += n * (1 - p); nn += n; }
    }
    if (!nt) continue;
    // the minute joins the day's distribution once (the five-minute ticks re-read a minute), then the causal threshold
    const mg = rec.mags[mk.tk] = rec.mags[mk.tk] || [];
    if (!(rec.magsTo[mk.tk] >= mm)) {
      const v = Math.round(Math.abs(net) * 100) / 100; let i = 0; while (i < mg.length && mg[i] < v) i++; mg.splice(i, 0, v);
      rec.magsTo[mk.tk] = mm;
    }
    const thr = Math.max(DARK_FLOOR_USD, mg.length ? mg[Math.floor(DARK_PCTL * (mg.length - 1))] : 0);
    if (Math.abs(net) < thr) continue;
    await aptCheck();
    const side = net > 0 ? 'yes' : 'no';
    const at = new Date(mm).toISOString();
    if (rec.bursts.some((b) => (b.t === at || b.t1 === at) && b.tk === mk.tk)) continue;
    const vwap = side === 'yes' ? (yn ? ys / yn : null) : (nn ? 1 - ns / nn : null);      // the YES price they traded at
    const usd = Math.round(Math.abs(net));
    const prev = rec.bursts.filter((b) => b.tk === mk.tk && b.side === side
      && mm - Date.parse(b.t1 || b.t) <= DARK_MERGE_MIN * 60000 && mm > Date.parse(b.t1 || b.t)).pop();
    let bb;
    if (prev) {                                // the same order, sliced: fold it in (price weighted by money)
      if (vwap != null) prev.px = prev.px == null ? Math.round(vwap * 100) / 100 : Math.round((prev.px * prev.usd + vwap * usd) / (prev.usd + usd) * 100) / 100;
      prev.usd += usd; prev.t1 = at; prev.minutes = (prev.minutes || 1) + 1; bb = prev;
    } else {
      /* SWEEPS ARE NOT DARK (2026-10-16): paying 95c+ for a side is collecting the last cents on a near-certain range
         (a $1,526 YES at 99c at 4:17 PM was alerted as dark). Same cut as dark_lib.is_sweep and the page. */
      const sideCost = vwap == null ? null : (side === 'yes' ? vwap : 1 - vwap);
      bb = { t: at, t1: at, tk: mk.tk, lab: mk.lab, side, usd, px: vwap == null ? null : Math.round(vwap * 100) / 100, minutes: 1,
             cls: (sideCost != null && sideCost >= DARK_SURE_PX) ? 'sweep' : (covered(mm) || covered(mm + 59999)) ? 'reaction' : 'dark' };
      rec.bursts.push(bb);
    }
    const cls = bb.cls;
    out.push(`${cls} ${side} ${mk.lab} $${usd}${prev ? ' (merged, $' + bb.usd + ')' : ''}`);
    /* PUSHED ONLY WHEN IT GOES AGAINST WHAT YOU HOLD (2026-10-16). Over 41 days dark bursts did not predict the next
       report (+0.06c +- 0.54) or beat their price, so a dark burst on its own is not news; one leaning against your
       position is the case worth a look. darkpos: keys go to the owner's phones only (notify's audience rule). */
    let mine = null;
    if (cls === 'dark' && bb.usd >= DARK_ALERT_USD && env.VAPID_JWK) {
      if (heldNow === null) heldNow = ((await env.OBS.get(ALERT_KEY, { type: 'json' })) || {}).held || [];
      mine = heldNow.find((x) => x.tk === mk.tk && ((x.n > 0 && side === 'no') || (x.n < 0 && side === 'yes'))) || null;
    }
    if (mine) {
      const hm = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' }).format(new Date(Date.parse(bb.t)));
      const last = rec.releases.filter((r) => Date.parse(r.t) <= mm).map((r) => Date.parse(r.t)).sort().pop();
      const since = last ? new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' }).format(new Date(last)) : 'this morning';
      await notify(env, await alertState(), `darkpos:${mk.tk}:${side}`, `Dark flow against your ${mine.n > 0 ? 'YES' : 'NO'} · ${mk.lab}`,
        `$${bb.usd.toLocaleString('en-US')} ${side.toUpperCase()}${bb.px == null ? '' : ' at ' + Math.round((side === 'yes' ? bb.px : 1 - bb.px) * 100) + '¢'} \u00b7 ${hm} \u00b7 no reading since ${since}.`, undefined, 'dark:alerts');
    }
    }
  }
  if (state && JSON.stringify(state) !== sBefore) await env.OBS.put('dark:alerts', JSON.stringify(state));
  if (JSON.stringify(rec) !== before) {
    rec.updated = new Date().toISOString();
    await env.OBS.put(key, JSON.stringify(rec), { expirationTtl: 60 * 60 * 24 * 120 });
  }
  return out.length ? out.join(', ') : 'no burst';
}
/* THE MIDNIGHT HOUR, WATCHED (2026-10-17). Under daylight time New York's climate day runs 1:00 AM - 12:59 AM, so
   12:00-12:59 AM is the LAST hour of the day before and 1:00 AM is where today starts. Nothing else covered it: the obs
   log stops at 04:55Z, the bake is not dispatched overnight, and api.weather.gov only keeps about a week. On 10-17 the
   park read 63 at 12:51 AM and 58 at 1:51 AM; the airports held 63-64 until ~1:25 AM, so today's high was set in the
   first minutes of the day by a reading no hourly report saw. This run, at 1:10, 1:25 and 1:40 AM EDT, keeps the whole
   window -- 11:45 PM to 1:20 AM -- for the park (hourly) and the three airports (5-minute), plus the derived numbers:
     tail   each station's max/min from 12:00 to 12:59 AM (yesterday's climate day)
     at1    each station's first reading at or after 1:00 AM
     delta  each airport's change from its reading nearest 12:51 to that first reading
     est    the park's 12:51 carried forward by the airports' median delta: the park's temperature as today begins
   KV `boundary:ny|<today>`, kept a year; GET /boundary?d= is public (it is public weather data). Silent in winter, when
   the climate day and the calendar day start together. */
const BOUNDARY_CRON = '10,25,40 5 * * *';
async function boundaryWatch(env, sched) {
  const z = 'America/New_York';
  const now = new Date(sched);
  const parts = (d) => Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: z, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(d).map((p) => [p.type, p.value]));
  const p = parts(now);
  const day = `${p.year}-${p.month}-${p.day}`;
  // 1:00 AM local as UTC: 05:00Z under EDT. In EST 05:00Z is MIDNIGHT, the climate day already starts on the calendar's
  const b = new Date(`${day}T05:00:00Z`);
  if (parts(b).hour !== '01') return `${day}: standard time, no straddle hour`;
  const t0 = new Date(b.getTime() - 75 * 60000), t1 = new Date(b.getTime() + 20 * 60000);
  const iso = (d) => d.toISOString().replace(/\.\d+Z$/, 'Z');
  const out = { day, boundary: iso(b), at: iso(now), st: {} };
  await Promise.all(['KNYC', 'KLGA', 'KJFK', 'KEWR'].map(async (st) => {
    try {
      const r = await fetch(`https://api.weather.gov/stations/${st}/observations?start=${iso(t0)}&end=${iso(t1)}`,
        { headers: { 'User-Agent': NWS_UA, 'Accept': 'application/geo+json' } });
      if (!r.ok) { out.st[st] = { err: `http ${r.status}` }; return; }
      const j = await r.json();
      const seen = new Set(), ser = [];
      for (const f of (j.features || [])) {
        const q = f.properties || {}, c = q.temperature && q.temperature.value;
        if (typeof c !== 'number' || !q.timestamp) continue;
        const t = new Date(q.timestamp); const k = iso(t).slice(0, 16);
        if (isNaN(t) || seen.has(k)) continue; seen.add(k);
        ser.push([iso(t), Math.round((c * 9 / 5 + 32) * 100) / 100]);
      }
      ser.sort((a, c) => (a[0] < c[0] ? -1 : 1));
      const ms = (x) => Date.parse(x[0]);
      const tail = ser.filter((x) => ms(x) >= b.getTime() - 3600000 && ms(x) < b.getTime());
      const after = ser.filter((x) => ms(x) >= b.getTime());
      const p51 = b.getTime() - 9 * 60000;
      const near = ser.filter((x) => Math.abs(ms(x) - p51) <= 240000).sort((a, c) => Math.abs(ms(a) - p51) - Math.abs(ms(c) - p51))[0];
      const o = { n: ser.length, ser };
      if (tail.length) { o.tailMax = Math.max(...tail.map((x) => x[1])); o.tailMin = Math.min(...tail.map((x) => x[1])); }
      if (near) o.p51 = near;
      if (after.length && ms(after[0]) - b.getTime() <= 10 * 60000) o.at1 = after[0];
      if (near && o.at1) o.delta = Math.round((o.at1[1] - near[1]) * 100) / 100;
      out.st[st] = o;
    } catch (e) { out.st[st] = { err: String(e).slice(0, 60) }; }
  }));
  const ds = ['KLGA', 'KJFK', 'KEWR'].map((s) => out.st[s] && out.st[s].delta).filter((v) => typeof v === 'number').sort((a, c) => a - c);
  const park = out.st.KNYC && out.st.KNYC.p51;
  if (ds.length) out.delta = ds[Math.floor(ds.length / 2)];
  if (park) out.park51 = park[1];
  if (park && ds.length) out.est = Math.round((park[1] + out.delta) * 10) / 10;
  if (env.OBS) {
    // a later run only replaces an earlier one when it saw at least as many airports reach the boundary
    const prev = await env.OBS.get(`boundary:ny|${day}`, { type: 'json' });
    if (!prev || !(prev.nAirports > ds.length)) {
      out.nAirports = ds.length;
      await env.OBS.put(`boundary:ny|${day}`, JSON.stringify(out), { expirationTtl: 60 * 60 * 24 * 366 });
    }
  }
  return `${day} park 12:51 ${park ? park[1] : '-'}, airports ${ds.length ? (out.delta >= 0 ? '+' : '') + out.delta : 'n/a'} -> ${out.est != null ? out.est : '-'} at 1:00 AM`;
}
async function boundaryRead(request, env) {
  const url = new URL(request.url);
  const d = /^\d{4}-\d\d-\d\d$/.test(url.searchParams.get('d') || '') ? url.searchParams.get('d') : localDate(0);
  const rec = env.OBS ? await env.OBS.get(`boundary:ny|${d}`, { type: 'json' }) : null;
  return new Response(JSON.stringify(rec || { day: d, none: true }), {
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'public, max-age=60', ...cors(ALLOWED) } });
}

async function darkRead(request, env) {
  const url = new URL(request.url);
  const d = /^\d{4}-\d\d-\d\d$/.test(url.searchParams.get('d') || '') ? url.searchParams.get('d') : localDate(0);
  const rec = env.OBS ? await env.OBS.get(`dark:${d}`, { type: 'json' }) : null;
  return new Response(JSON.stringify(rec || { day: d, bursts: [], releases: [] }), {
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'public, max-age=30', ...cors(ALLOWED) } });
}

/* WEB PUSH ROUTES (2026-10-13). GET /push/key -- the public key the page subscribes with (public by design).
   POST /push/subscribe, /push/unsubscribe, /push/test -- gated by the same PANEL_TOKEN as /positions: the alerts carry
   your positions, so only a browser that already holds the token can sign a phone up. GET /push/status -- the last
   delivery (gated too). */
async function pushRoute(request, env, url) {
  const H = { 'content-type': 'application/json', ...cors(ALLOWED) };
  const J = (o, st) => new Response(JSON.stringify(o), { status: st || 200, headers: H });
  if (!env.VAPID_JWK || !env.OBS) return J({ error: 'push not configured' }, 503);
  const jwk = JSON.parse(env.VAPID_JWK);
  if (url.pathname === '/push/key') return J({ key: vapidPublic(jwk) });
  /* two keys: PANEL_TOKEN is the owner's (your account, your alerts); VIEWER_TOKEN is the one you hand out -- it can
     sign a phone up for the market alerts and nothing else (2026-10-13) */
  const given = (request.headers.get('authorization') || '').replace(/^Bearer\s+/i, '');
  const role = tokenOk(given, env.PANEL_TOKEN) ? 'owner' : (env.VIEWER_TOKEN && tokenOk(given, env.VIEWER_TOKEN)) ? 'viewer' : null;
  if (!role) return J({ error: 'unauthorized' }, 401);
  const subs = (await env.OBS.get(PUSH_KEY, { type: 'json' })) || [];
  if (url.pathname === '/push/status'){
    if (role !== 'owner') return J({ error: 'owner only' }, 403);
    return J({ phones: subs.length, owners: subs.filter((x) => (x.role || 'owner') === 'owner').length, last: await env.OBS.get('push:last', { type: 'json' }) });
  }
  if (request.method !== 'POST') return J({ error: 'POST' }, 405);
  let b = {}; try { b = await request.json(); } catch (_) {}
  if (url.pathname === '/push/subscribe') {
    const s = b.sub;
    if (!s || !/^https:\/\//.test(s.endpoint || '') || !s.keys || !s.keys.p256dh || !s.keys.auth) return J({ error: 'bad subscription' }, 400);
    /* the owner's phones always keep their place; viewers are capped at the newest 50 */
    const rest = subs.filter((x) => x.endpoint !== s.endpoint);
    const owners = rest.filter((x) => (x.role || 'owner') === 'owner').slice(-5), viewers = rest.filter((x) => x.role === 'viewer').slice(-49);
    const keep = owners.concat(viewers);
    keep.push({ endpoint: s.endpoint, keys: { p256dh: s.keys.p256dh, auth: s.keys.auth }, role, at: new Date().toISOString(), ua: String(b.ua || '').slice(0, 80) });
    await env.OBS.put(PUSH_KEY, JSON.stringify(keep));
    return J({ ok: true, phones: keep.length });
  }
  if (url.pathname === '/push/mine') return J({ on: subs.some((x) => x.endpoint === b.endpoint) });   /* is this phone signed up here */
  if (url.pathname === '/push/unsubscribe') {
    const keep = subs.filter((x) => x.endpoint !== (b.endpoint || ''));
    await env.OBS.put(PUSH_KEY, JSON.stringify(keep));
    return J({ ok: true, phones: keep.length });
  }
  if (url.pathname === '/push/test') {
    /* the test goes to the asking phone only, never to everyone */
    const mine = subs.find((x) => x.endpoint === b.endpoint);
    if (!mine) return J({ error: 'this phone is not signed up' }, 404);
    const r = await pushAll(env, { title: 'BLUISH alerts are on', body: mine.role === 'viewer' ? 'This phone will get the Kalshi market alerts: dark flow and the Central Park settlement.' : 'This phone will get your Kalshi alerts from now on.', tag: 'push-test', url: '/' }, 'high', b.endpoint);
    return J({ ok: r.sent > 0, ...r });
  }
  return J({ error: 'not found' }, 404);
}

export default {
  async scheduled(event, env, ctx) {
    /* ONE JOB PER TRIGGER (2026-10-06). The free plan gives each invocation 10 ms of CPU, with some leniency for an
       occasional overrun. One invocation used to carry everything: a dark-flow minute made 12 outbound requests at
       12.5-18 ms, the five-minute minute (obs log + bake) 41-47 ms -- and on 10-06 a heavy :20 tick tipped the account
       into strict enforcement, after which EVERY tick died 6-9 requests in, 14:16-14:26 and 17:20-17:59 UTC. Each cron
       trigger fires its own invocation with its own budget (5 triggers per account on the free plan; this worker now
       uses 4), so the dark-flow watcher and the obs log ride their own triggers, and the original two keep the alerts,
       the bake dispatch, the watchdog and the sunset jobs. The one-time ntfy self-test is no longer read every minute.
       Routed by event.cron, which is the trigger's expression exactly as written in wrangler.toml. */
    const sched = event.scheduledTime || Date.now();
    if (event.cron === DARK_CRON){
      if (new Date(sched).getUTCMinutes() % 5 !== 0) ctx.waitUntil((async () => {
        try { console.log(`[dark] ${new Date().toISOString()} ${await darkTick(env, sched)}`); }
        catch (e) { console.log(`[dark] FAILED ${e}`); }
      })());
      return;
    }
    if (event.cron === BOUNDARY_CRON){
      ctx.waitUntil((async () => {
        try { console.log(`[boundary] ${new Date().toISOString()} ${await boundaryWatch(env, sched)}`); }
        catch (e) { console.log(`[boundary] FAILED ${e}`); }
      })());
      return;
    }
    if (event.cron === OBS_CRON){
      ctx.waitUntil((async () => {
        try { console.log(`[obs-log] ${new Date().toISOString()} ${await logObs(env)}`); }
        catch (e) { console.log(`[obs-log] FAILED ${e}`); }
      })());
      return;
    }
    if (sched < NTFY_TEST_UNTIL) ctx.waitUntil(ntfySelfTest(env).catch((e) => console.log(`[ntfy-test] FAILED ${e}`)));
    /* QUIET HOURS (2026-10-17). The trigger runs through the night now ("* 0-10"), but only for the bake dispatch: the
       phone alerts and the watchdog keep their old hours and stay off 05-10 UTC (1-6 AM daylight time), so nothing pages
       overnight -- the climate report's ~3 AM final included. */
    const quiet = (() => { const h = new Date(sched).getUTCHours(); return h >= 5 && h <= 10; })();
    if (!quiet) ctx.waitUntil((async () => {
      try {
        console.log(`[alerts] ${new Date().toISOString()} ${await alertTick(env, sched)}`);
      } catch (e) {
        console.log(`[alerts] FAILED ${e}`);
      }
    })());
    // EVERY tick logs; only the original four minutes dispatch. The cron went to
    // */5 for the observation trail, and the daily job must not suddenly run
    // twelve times an hour -- it takes ~5 minutes and the runs would overlap.
    // THE CRON IS EVERY MINUTE NOW, for the alerts: on 2026-09-05 the market
    // repriced New York in the minute ending 4:17 PM, and a five-minute tick
    // would have said so at 4:20. The observation log keeps its five-minute
    // cadence (one KV write per tick against a 1,000/day budget) and the
    // daily job its four minutes an hour.
    // THE SCHEDULED MINUTE, NOT THE WALL CLOCK. `new Date()` here is when the
    // invocation actually STARTED, and Cloudflare can deliver a tick late. On
    // 2026-09-11 the 23:00:40Z tick ran at ~23:01: its alerts line is stamped
    // 23:01:50Z where its neighbours log 4-11 s in, and that one invocation ran
    // NEITHER the hourly watchdog (minute === 0) NOR the five-minute obs log
    // (minute % 5) while every other 5-minute tick ran both. Two independent
    // gates missing on the same invocation is the minute being misread, not two
    // bugs -- and the same `minute` decides whether the bake is dispatched, so a
    // late tick was silently skipping bakes and KV writes too (one of seven in a
    // 36-minute sample). event.scheduledTime is the tick the cron asked for.
    const minute = new Date(event.scheduledTime || Date.now()).getUTCMinutes();
    // HOURLY, NOT ONCE AT 13:00Z. The 09-11 New York crash was invisible for
    // eighteen hours because the only check ran at 13:00Z and read the run's
    // conclusion, which was green. Three API calls and one 25 KB log an hour is
    // nothing, and paging stays keyed by day, so a failure still pages once.
    if (minute === 0 && !quiet) {
      ctx.waitUntil((async () => {
        try { console.log(`[watchdog] :${minute} ${new Date().toISOString()} ${await jobWatch(env)}`); }
        catch (e) { console.log(`[watchdog] FAILED ${e}`); }
      })());
      if (new Date(event.scheduledTime || Date.now()).getUTCHours() === 12) ctx.waitUntil((async () => {
        try { console.log(`[review] ${new Date().toISOString()} ${await reviewDigest(env)}`); }
        catch (e) { console.log(`[review] FAILED ${e}`); }
      })());
    }
    // THE SUNSET TRUTH (2026-09-26). Two minutes before New York's sunset, start sunset-truth.yml: it photographs the
    // west-facing cameras at sunset +5/+10/+15/+20 and scores how the sky actually coloured, next to the site's prediction
    // (sunset-log.yml). Dispatched from here because GitHub's own cron starts 15-60 min late -- a dispatch lands in seconds.
    {
      const st = new Date(event.scheduledTime || Date.now());
      [['nyc', 40.708, -73.969, -5], ['la', 34.05, -118.24, -8]].forEach(([city, la, lo, off]) => {
        const ss = sunsetUTC(st, la, lo, off);
        if (Math.floor((ss.getTime() - 2 * 60000) / 60000) !== Math.floor(st.getTime() / 60000)) return;
        ctx.waitUntil((async () => {
          let r; try { r = await dispatch(env, 'sunset-truth.yml', { city }); } catch (e) { r = { ok: false, status: 0, detail: String(e) }; }
          console.log(`[sunset-truth] ${city} sunset ${ss.toISOString()} -> ${r.ok ? 'dispatched' : 'FAILED'} (http ${r.status}) ${r.detail}`);
        })());
      });
    }
    // THE LIVE CLOUDS VIDEOS (2026-10-20, user: "yes build it"). goes-video.yml bakes the satellite loops into MP4s on R2
    // (_goesvid/bake.py); every 10 minutes at :03/:13/..., started here because GitHub's own schedule runs 10-30 min late.
    if (minute % 10 === 3) ctx.waitUntil((async () => {
      let r; try { r = await dispatch(env, 'goes-video.yml'); } catch (e) { r = { ok: false, status: 0, detail: String(e) }; }
      if (!r.ok) console.log(`[goes-video] dispatch FAILED (http ${r.status}) ${r.detail}`);
    })());
    // THE MIGRATION CAPTURE (2026-10-23, user: "is this playing properly? its BIRDS"). migration.yml captures the last two
    // hours of bird-only frames; MRMS keeps only ~2 h, so a skipped run is a hole in the night for good. GitHub's own
    // '7,37' schedule ran 8 times on 10-23 instead of ~40, and last night's loop came out 47 frames of 96 with 100- and
    // 220-minute holes. Started from here at :07/:37 instead; the workflow's concurrency group queues any overlap.
    if (minute === 7 || minute === 37) ctx.waitUntil((async () => {
      let r; try { r = await dispatch(env, 'migration.yml'); } catch (e) { r = { ok: false, status: 0, detail: String(e) }; }
      if (!r.ok) console.log(`[migration] dispatch FAILED (http ${r.status}) ${r.detail}`);
    })());
    // TWO LANES. The full 20-city bake on :05/:20/:35/:50; Central Park alone
    // on every other five-minute mark, so the New York sheet is never more
    // than a few minutes behind the newest report. Both merge into one file.
    if (minute % 5 !== 0) return;
    // ALL THREE CITIES EVERY FIVE MINUTES. With three markets the full bake is
    // about a minute, so the New York-only fast lane is no longer needed and
    // Las Vegas and Austin stop waiting fifteen minutes for a reading that
    // the market prices in one (2026-09-06).
    const wf = WORKFLOW;
    ctx.waitUntil((async () => {
      let r;
      try {
        r = await dispatch(env, wf);
      } catch (e) {
        r = { ok: false, status: 0, detail: String(e) };
      }
      // One retry: a transient GitHub 5xx should not cost the hour, and the job
      // is idempotent — a lock is written once and never rewritten.
      if (!r.ok && r.status >= 500) {
        await new Promise((s) => setTimeout(s, 4000));
        try {
          r = await dispatch(env, wf);
        } catch (e) {
          r = { ok: false, status: 0, detail: String(e) };
        }
      }
      console.log(`[kalshi-cron] ${event.cron} ${wf} -> ${r.ok ? 'dispatched' : 'FAILED'} ` +
                  `(http ${r.status}) ${r.detail}`);
    })());
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors(ALLOWED) });
    }
    if (url.pathname === '/positions') return positions(request, env);
    if (url.pathname.startsWith('/push/')) return pushRoute(request, env, url);
    if (url.pathname === '/obs') return obsDump(request, env);
    if (url.pathname === '/obs/lead') return obsLead(request, env);
    if (url.pathname === '/dark') return darkRead(request, env);
    if (url.pathname === '/boundary') return boundaryRead(request, env);
    if (url.pathname === '/sensors') {
      // PUBLIC, LIVE: the 5-minute stations' latest reading and high since 7 AM,
      // read from api.weather.gov on each request (keyless, so no secret). The
      // panel polls this every minute while it is open (2026-09-06: "it's about
      // seeing the latest information and knowing first when temp changes").
      let sens = {};
      // 26 HOURS, not 18 (2026-10-17): the panel's chart now runs midnight to midnight, and an 18-hour window lost the
      // overnight hours -- the 1 AM climate-day boundary among them -- from 6 PM on
      try { sens = await readSensors(1560, true); } catch (e) { /* empty */ }
      return new Response(JSON.stringify({ at: new Date().toISOString(), s: sens }), {
        headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...cors(ALLOWED) } });
    }

    // THE WATCHDOG, ON DEMAND. Token-gated, because it reads the repo's job
    // logs. It runs itself hourly; this is how a change to it gets verified
    // without waiting for the top of the hour, and how "is anything failing
    // right now" gets answered. Paging stays keyed by day, so calling this
    // cannot spam the phone.
    if (url.pathname === '/watchdog') {
      const given = (request.headers.get('authorization') || '').replace(/^Bearer\s+/i, '')
                    || url.searchParams.get('t') || '';
      if (!tokenOk(given, env.PANEL_TOKEN)) {
        return new Response(JSON.stringify({ error: 'unauthorized' }), {
          status: 401, headers: { 'content-type': 'application/json', ...cors(ALLOWED) } });
      }
      let said;
      try { said = await jobWatch(env); } catch (e) { said = `threw: ${e}`; }
      return new Response(JSON.stringify({ at: new Date().toISOString(), watchdog: said }), {
        headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...cors(ALLOWED) } });
    }

    // Status only. This deliberately cannot trigger a run: a public endpoint that
    // fires CI is an open invitation, and the cron is the point.
    //
    // The token is CHECKED, not merely counted. A token that has expired -- these
    // are issued with a fixed lifetime -- would still be "configured", so a
    // presence check would read healthy while every dispatch quietly 401s. One
    // read-only call against the workflow answers whether it actually works.
    let token = env.GH_TOKEN ? 'set, but unverified' : 'MISSING';
    let healthy = false;
    if (env.GH_TOKEN) {
      try {
        const r = await fetch(
          `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}`,
          { headers: {
              'Authorization': `Bearer ${env.GH_TOKEN}`,
              'Accept': 'application/vnd.github+json',
              'User-Agent': 'bluishvoid-kalshi-cron'
          } });
        healthy = r.ok;
        token = r.ok ? 'valid'
              : (r.status === 401 ? 'REJECTED - expired or revoked'
              : r.status === 404 ? 'REJECTED - no access to this repo/workflow'
              : `REJECTED - http ${r.status}`);
      } catch (e) {
        token = `could not be checked: ${e}`;
      }
    }
    const body = {
      worker: 'kalshi-cron',
      healthy,
      token,
      dispatches: `${OWNER}/${REPO} :: ${WORKFLOW} @ ${REF}`,
      // HAND-MAINTAINED, and it drifted: this still read the old hourly
      // schedule after the triggers went to every 15 minutes, so the status
      // page confidently reported a cadence the worker was not running.
      // Cloudflare does not expose a worker's own triggers to its code, so
      // this has to be kept in step with [triggers] in wrangler.toml by hand.
      schedule_utc: ['* 11-23 * * *', '* 0-10 * * *', BOUNDARY_CRON, DARK_CRON, OBS_CRON],
      dispatch_minutes: [5, 20, 35, 50],
      fast_lane_minutes: [0, 10, 15, 25, 30, 40, 45, 55],
      obs_log: env.OBS ? 'KV bound' : 'NO KV BINDING - not logging',
      alerts: env.VAPID_JWK ? 'web push to the BLUISH app; New York positions watched every 5 min' : 'off (no VAPID_JWK)',
      watchdog: (env.VAPID_JWK && env.GH_TOKEN) ? 'nightly refit, weekly tune and the bake checked hourly; a failed, missing or stale run pages, and so does a green run whose log says a market FAILED' : 'off',
      now_utc: new Date().toISOString(),
      note: 'Triggering is cron-only. Runs appear at github.com/' + OWNER + '/' + REPO + '/actions'
    };
    return new Response(JSON.stringify(body, null, 2), {
      status: healthy ? 200 : 503,
      headers: { 'content-type': 'application/json; charset=utf-8' }
    });
  }
};
