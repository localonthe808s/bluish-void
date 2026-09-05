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

const OWNER = 'localonthe808s';
const REPO = 'bluish-void';
const WORKFLOW = 'kalshi-nyc.yml';
const REF = 'main';

async function dispatch(env) {
  if (!env.GH_TOKEN) {
    return { ok: false, status: 0, detail: 'GH_TOKEN secret is not set' };
  }
  const url = `https://api.github.com/repos/${OWNER}/${REPO}` +
              `/actions/workflows/${WORKFLOW}/dispatches`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GH_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      // GitHub rejects API requests without one
      'User-Agent': 'bluishvoid-kalshi-cron'
    },
    body: JSON.stringify({ ref: REF })
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

async function kalshiGet(env, path, query) {
  const key = await crypto.subtle.importKey(
    'pkcs8', pemToDer(env.KALSHI_PRIVATE_KEY),
    { name: 'RSA-PSS', hash: 'SHA-256' }, false, ['sign']);
  const ts = String(Date.now());
  const sig = await crypto.subtle.sign(
    { name: 'RSA-PSS', saltLength: 32 }, key,
    new TextEncoder().encode(ts + 'GET' + path));
  const res = await fetch(KALSHI + path + (query || ''), {
    headers: {
      'KALSHI-ACCESS-KEY': env.KALSHI_API_KEY_ID,
      'KALSHI-ACCESS-TIMESTAMP': ts,
      'KALSHI-ACCESS-SIGNATURE': btoa(String.fromCharCode(...new Uint8Array(sig))),
      'Accept': 'application/json',
      'User-Agent': 'bluishvoid-kalshi-cron'
    }
  });
  if (!res.ok) throw new Error('kalshi ' + path + ' -> ' + res.status);
  return res.json();
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
    'Access-Control-Allow-Headers': 'authorization',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin'
  };
}
const ALLOWED = 'https://bluishvoid.com';

async function obsDump(request, env) {
  // Behind the same token as /positions. The trail is not secret, but an open
  // endpoint that lists a KV namespace is a free way for anyone to burn the
  // day's read quota and blind the study.
  const url = new URL(request.url);
  const given = (request.headers.get('authorization') || '').replace(/^Bearer\s+/i, '')
                || url.searchParams.get('t') || '';
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
  // key,      ICAO,   IEM network, IEM station
  ['ny_high',  'KNYC', 'NY_ASOS', 'NYC'],
  ['chi_high', 'KMDW', 'IL_ASOS', 'MDW'],
  ['mia_high', 'KMIA', 'FL_ASOS', 'MIA'],
  ['aus_high', 'KAUS', 'TX_ASOS', 'AUS'],
  ['den_high', 'KDEN', 'CO_ASOS', 'DEN'],
  ['lax_high', 'KLAX', 'CA_ASOS', 'LAX'],
  ['phl_high', 'KPHL', 'PA_ASOS', 'PHL']
];

// THE STATION TRAP, and it cost a whole 45-day study before it was found.
//   v3 /wx/observations/current?icaoCode=KNYC -> Central Park   RIGHT
//   v1 /location/KNYC:9:US/observations/...   -> LaGuardia      WRONG
// Same ICAO, two endpoints, two different stations three miles and two degrees
// apart. Only the v3 current form is used here. `language` is REQUIRED: without
// it the answer is HTTP 400 with every field null, which reads like a station
// outage rather than a malformed request.
const TWC_KEY = 'e1f10a1e78da46f5b10a1e78da96f525';

async function obsSnapshot() {
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
      const d = new Date().toLocaleDateString('en-CA', { timeZone: {
        ny_high: 'America/New_York', chi_high: 'America/Chicago',
        mia_high: 'America/New_York', aus_high: 'America/Chicago',
        den_high: 'America/Denver',   lax_high: 'America/Los_Angeles',
        phl_high: 'America/New_York' }[key] });
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
  return { t, rows };
}

async function logObs(env) {
  if (!env.OBS) return 'no KV binding';
  const snap = await obsSnapshot();
  // One key per tick. ~192 ticks a day against a 1000/day free write limit, and
  // the key sorts lexicographically because the timestamp does.
  await env.OBS.put(`obs:${snap.t}`, JSON.stringify(snap.rows), {
    expirationTtl: 60 * 60 * 24 * 120        // 120 days is far past any analysis
  });
  const lead = snap.rows.filter((r) => r.max7 != null && r.iem != null && r.max7 > r.iem);
  return `${snap.rows.length} rows` + (lead.length
    ? `, max7 above iem: ${lead.map((r) => `${r.key} +${(r.max7 - r.iem).toFixed(1)}`).join(' ')}`
    : '');
}

export default {
  async scheduled(event, env, ctx) {
    // EVERY tick logs; only the original four minutes dispatch. The cron went to
    // */5 for the observation trail, and the daily job must not suddenly run
    // twelve times an hour -- it takes ~5 minutes and the runs would overlap.
    ctx.waitUntil((async () => {
      try {
        console.log(`[obs-log] ${new Date().toISOString()} ${await logObs(env)}`);
      } catch (e) {
        console.log(`[obs-log] FAILED ${e}`);
      }
    })());
    const minute = new Date().getUTCMinutes();
    if (![5, 20, 35, 50].includes(minute)) return;
    ctx.waitUntil((async () => {
      let r;
      try {
        r = await dispatch(env);
      } catch (e) {
        r = { ok: false, status: 0, detail: String(e) };
      }
      // One retry: a transient GitHub 5xx should not cost the hour, and the job
      // is idempotent — a lock is written once and never rewritten.
      if (!r.ok && r.status >= 500) {
        await new Promise((s) => setTimeout(s, 4000));
        try {
          r = await dispatch(env);
        } catch (e) {
          r = { ok: false, status: 0, detail: String(e) };
        }
      }
      console.log(`[kalshi-cron] ${event.cron} -> ${r.ok ? 'dispatched' : 'FAILED'} ` +
                  `(http ${r.status}) ${r.detail}`);
    })());
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors(ALLOWED) });
    }
    if (url.pathname === '/positions') return positions(request, env);
    if (url.pathname === '/obs') return obsDump(request, env);

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
      schedule_utc: ['*/5 12-23 * * *', '*/5 0-4 * * *'],
      dispatch_minutes: [5, 20, 35, 50],
      obs_log: env.OBS ? 'KV bound' : 'NO KV BINDING - not logging',
      now_utc: new Date().toISOString(),
      note: 'Triggering is cron-only. Runs appear at github.com/' + OWNER + '/' + REPO + '/actions'
    };
    return new Response(JSON.stringify(body, null, 2), {
      status: healthy ? 200 : 503,
      headers: { 'content-type': 'application/json; charset=utf-8' }
    });
  }
};
