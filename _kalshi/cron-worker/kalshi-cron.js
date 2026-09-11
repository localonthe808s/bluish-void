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
const WORKFLOW_FAST = 'kalshi-nyc-fast.yml';   // Central Park alone, on the other five-minute marks
const REF = 'main';

async function dispatch(env, workflow) {
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
  // key,      ICAO,   IEM network, IEM station -- the three cities the sheet
  // trades (2026-09-06); the other four were dropped with the rest
  ['ny_high',  'KNYC', 'NY_ASOS', 'NYC'],
  ['las_high', 'KLAS', 'NV_ASOS', 'LAS'],
  ['aus_high', 'KAUS', 'TX_ASOS', 'AUS']
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
async function readSensors(recentMin, withSeries) {
  const out = {};
  const tzOf = {};
  for (const k of Object.keys(APT5)) for (const st of APT5[k].stids.split(',')) tzOf[st] = APT5[k].tz;
  const start = new Date(Date.now() - (recentMin || 720) * 60000).toISOString().replace(/\.\d+Z$/, 'Z');
  await Promise.all(Object.keys(tzOf).map(async (stid) => {
    const tz = tzOf[stid];
    try {
      const r = await fetch(`https://api.weather.gov/stations/${stid}/observations?start=${start}`,
        { headers: { 'User-Agent': NWS_UA, 'Accept': 'application/geo+json' } });
      if (!r.ok) return;
      const j = await r.json();
      // Local calendar date and local HH:MM for a UTC stamp, in the station's
      // own zone -- the same two fields the Synoptic `obtimezone=local` form
      // used to hand back already split.
      const dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' });
      const hmFmt = new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
      const today = dayFmt.format(new Date());
      // Oldest first, so `last` ends on the newest reading the way the old
      // top-to-bottom Synoptic loop did.
      const feats = (j.features || []).slice().reverse();
      let mx = null, mxAt = null, last = null, lastAt = null, n = 0;
      const series = [], seen = new Set();
      for (const f of feats) {
        const p = (f && f.properties) || {};
        const c = p.temperature && p.temperature.value;
        if (typeof c !== 'number' || !p.timestamp) continue;
        const d = new Date(p.timestamp);
        if (isNaN(d)) continue;
        const day = dayFmt.format(d), hm = hmFmt.format(d);
        // A minute can arrive twice (the :51 METAR alongside a :50 five-minute
        // row is not a dupe, but a re-issued ob is). Last one in wins.
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
        n++;
        if (day === today && hh >= 7 && (mx == null || v > mx)) { mx = v; mxAt = hm; }
        last = v; lastAt = hm;
        if (withSeries && day === today) series.push([hh * 60 + Number(hm.slice(3, 5)), v]);
      }
      if (!n) return;
      out[stid] = { max7: mx, maxAt: mxAt, last, at: lastAt, n };
      if (withSeries) out[stid].series = series;
    } catch (e) { /* one dead station must not cost the read */ }
  }));
  return out;
}
const APT5 = {
  // KNYC rides along for the trend line: Central Park reports HOURLY (its
  // 5-minute stream is NWS-run and not in the FAA feed; MADIS pending), so its
  // points are the hourly reports, drawn as such. Never OWN5 for NY.
  ny_high:  { stids: 'KLGA,KJFK,KEWR,KNYC', tz: 'America/New_York' },
  las_high: { stids: 'KLAS,KVGT',      tz: 'America/Los_Angeles' },
  aus_high: { stids: 'KAUS,KATT',      tz: 'America/Chicago' }
};

// THE STATION TRAP, and it cost a whole 45-day study before it was found.
//   v3 /wx/observations/current?icaoCode=KNYC -> Central Park   RIGHT
//   v1 /location/KNYC:9:US/observations/...   -> LaGuardia      WRONG
// Same ICAO, two endpoints, two different stations three miles and two degrees
// apart. Only the v3 current form is used here. `language` is REQUIRED: without
// it the answer is HTTP 400 with every field null, which reads like a station
// outage rather than a malformed request.
const TWC_KEY = 'e1f10a1e78da46f5b10a1e78da96f525';

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
    const tz = { ny_high: 'America/New_York', las_high: 'America/Los_Angeles', aus_high: 'America/Chicago' }[r.key] || 'America/New_York';
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
  { series: 'KXHIGHNY',  icao: 'KNYC', tz: 'America/New_York',    name: 'Central Park' },
  { series: 'KXHIGHTLV', icao: 'KLAS', tz: 'America/Los_Angeles', name: 'Las Vegas' },
  { series: 'KXHIGHAUS', icao: 'KAUS', tz: 'America/Chicago',     name: 'Austin' }
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
async function notify(env, state, key, title, body, priority) {
  const now = Date.now();
  const last = (state.sent || {})[key] || 0;
  if (now - last < ALERT_COOLDOWN_MS) return false;
  const r = await fetch(`https://ntfy.sh/${env.NTFY_TOPIC}`, {
    method: 'POST', body,
    headers: { 'Title': title, 'Priority': priority || 'default' }
  });
  state.sent = state.sent || {};
  state.sent[key] = now;
  return r.ok;
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
  { wf: 'kalshi-tune.yml',    name: 'weekly tune',      maxAgeH: 8 * 24, weekday: 1 },   // Mondays, after Sunday's run
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
  if (!env.NTFY_TOPIC || !env.OBS || !env.GH_TOKEN) return 'watchdog off';
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
        `${w.wf} -- ${bad}. ${r ? r.html_url : ''} The sheet keeps serving the last good study; nothing learns until this is fixed.`, 'high');
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
async function alertTick(env) {
  if (!env.NTFY_TOPIC || !env.OBS) return 'alerts off';
  const state = (await env.OBS.get(ALERT_KEY, { type: 'json' })) || {};
  const before = JSON.stringify(state);
  const out = [];
  // 1. the portal, yesterday and today
  state.portal = state.portal || {};
  for (const off of [-1, 0]) {
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
          `Central Park ${day}: ${st.toUpperCase()} ${v}°`,
          `weather.com/kalshi shows the ${day} high as ${v}° (${st}). ` +
          (st === 'official' ? 'This is the number that pays.' : 'Preliminary; the final comes ~3 AM.'),
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
  const OWN5 = { KXHIGHTLV: 'KLAS', KXHIGHAUS: 'KAUS' };
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
    const b = rungBounds(m), label = rungLabel(b), side = h.n > 0 ? 'YES' : 'NO';
    const bid = Number(m.yes_bid_dollars), ask = Number(m.yes_ask_dollars);
    const mid = (isFinite(bid) && isFinite(ask) && ask > 0) ? (bid + ask) / 2 : null;
    // 3. the market moved on your rung
    if (mid != null) {
      const anchor = state.mkt[h.ticker];
      if (anchor != null && Math.abs(mid - anchor) >= 0.25) {
        const dir = mid > anchor ? 'up' : 'down';
        const good = (side === 'YES') === (mid > anchor);
        await notify(env, state, `mkt:${h.ticker}:${Math.round(mid * 4)}`,
          `${label}: market ${dir} ${Math.round(anchor * 100)}¢ → ${Math.round(mid * 100)}¢`,
          `You hold ${Math.abs(h.n)} ${side}. The YES price moved from ${Math.round(anchor * 100)}¢ to ` +
          `${Math.round(mid * 100)}¢ -- ${good ? 'in your favour' : 'against you'}. ` +
          `The afternoon market prices the hourly readings, not the peak; the plan is to hold.`,
          good ? 'default' : 'high');
        out.push(`${h.ticker} ${anchor}->${mid}`);
        state.mkt[h.ticker] = mid;
      } else if (anchor == null) {
        state.mkt[h.ticker] = mid;
      }
    }
    // 1a. a new hourly (or special) report from the settlement station
    const rp = rep[h.am.icao];
    if (rp && state.metar[h.am.icao] !== rp.at) {
      const inNow = inRung(rp.f, b), above = b[1] != null && rp.f > b[1] + 0.5, below = b[0] != null && rp.f < b[0] - 0.5;
      const bad = (side === 'YES') ? (above) : (inNow);
      const local = new Date(rp.at).toLocaleTimeString('en-US', { timeZone: h.am.tz, hour: 'numeric', minute: '2-digit' });
      await notify(env, state, `metar:${h.ticker}:${rp.at}`,
        `${h.am.name} ${local} report: ${rp.f}° -- ${inNow ? 'inside' : above ? 'above' : 'below'} ${label}`,
        `The ${rp.raw.trim() === 'SPECI' ? 'special' : 'hourly'} report from ${h.am.icao} reads ${rp.f}°. ` +
        `You hold ${Math.abs(h.n)} ${side} on ${label}${bad ? ' -- this reading is against you' : ''}. ` +
        `The market prices this report within about two minutes; a reading between reports is invisible until the climate report.`,
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
          `${h.am.name} sensor ${ownMax}° at ${ownAt} -- ${nowIn ? 'inside' : nowAbove ? 'above' : 'below'} ${label}`,
          `${ownSt}'s own 5-minute reading set a new high of ${ownMax}° at ${ownAt} local. ` +
          `You hold ${Math.abs(h.n)} ${side} on ${label}${bad ? ' -- this is against you' : ' -- in your favour'}. ` +
          `This is the settlement sensor; the hourly report and the market see it up to 55 minutes later.`,
          bad ? 'urgent' : 'high');
        out.push(`own5 ${ownSt} ${prevOwn}->${ownMax}`);
      } else if (b[1] != null && ownMax <= b[1] + 0.5 && ownMax >= b[1] - 0.4 && (prevOwn == null || prevOwn < b[1] - 0.4)) {
        // within half a degree of the top edge: one warning, before it crosses
        await notify(env, state, `own5near:${h.ticker}`,
          `${h.am.name} sensor ${ownMax}°, near the top of ${label}`,
          `${ownSt} read ${ownMax}° at ${ownAt}, within half a degree of ${label}'s top edge. ` +
          `You hold ${Math.abs(h.n)} ${side}. One more tick decides it.`, 'high');
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
          `${h.am.name} running max ${max7}° (TWC)`,
          `TWC's temperatureMaxSince7Am went ${prevMax7}° → ${max7}°, ` +
          (nowIn ? `inside ${label}` : nowAbove ? `above ${label}` : `below ${label}`) +
          `. You hold ${Math.abs(h.n)} ${side} on ${label}${bad ? ' -- this is against you' : ''}. ` +
          `max7 is a blended field and has read high before; the climate report decides.`,
          bad ? 'high' : 'default');
        out.push(`max7 ${h.am.series} ${prevMax7}->${max7}`);
      }
    }
  }
  for (const k of Object.keys(max7by)) if (max7by[k] != null) state.max7by[k] = max7by[k];
  for (const k of Object.keys(rep)) state.metar[k] = rep[k].at;
  // KV allows 1,000 writes a day on this plan; a minute cadence is 1,020 ticks.
  // The state only changes when something happened, so only then is it written.
  if (JSON.stringify(state) !== before) await env.OBS.put(ALERT_KEY, JSON.stringify(state));
  return out.length ? out.join(', ') : `quiet (${held.length} watched position${held.length === 1 ? '' : 's'})`;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil((async () => {
      try {
        console.log(`[alerts] ${new Date().toISOString()} ${await alertTick(env)}`);
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
    if (minute === 0) {
      ctx.waitUntil((async () => {
        try { console.log(`[watchdog] :${minute} ${new Date().toISOString()} ${await jobWatch(env)}`); }
        catch (e) { console.log(`[watchdog] FAILED ${e}`); }
      })());
    }
    if (minute % 5 === 0) {
      ctx.waitUntil((async () => {
        try {
          console.log(`[obs-log] ${new Date().toISOString()} ${await logObs(env)}`);
        } catch (e) {
          console.log(`[obs-log] FAILED ${e}`);
        }
      })());
    }
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
    if (url.pathname === '/obs') return obsDump(request, env);
    if (url.pathname === '/obs/lead') return obsLead(request, env);
    if (url.pathname === '/sensors') {
      // PUBLIC, LIVE: the 5-minute stations' latest reading and high since 7 AM,
      // read from api.weather.gov on each request (keyless, so no secret). The
      // panel polls this every minute while it is open (2026-09-06: "it's about
      // seeing the latest information and knowing first when temp changes").
      let sens = {};
      try { sens = await readSensors(1080, true); } catch (e) { /* empty */ }
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
      schedule_utc: ['* 12-23 * * *', '* 0-4 * * *'],
      dispatch_minutes: [5, 20, 35, 50],
      fast_lane_minutes: [0, 10, 15, 25, 30, 40, 45, 55],
      obs_log: env.OBS ? 'KV bound' : 'NO KV BINDING - not logging',
      alerts: env.NTFY_TOPIC ? 'ntfy topic set; New York positions watched every 5 min' : 'off (no NTFY_TOPIC)',
      watchdog: (env.NTFY_TOPIC && env.GH_TOKEN) ? 'nightly refit, weekly tune and the bake checked hourly; a failed, missing or stale run pages, and so does a green run whose log says a market FAILED' : 'off',
      now_utc: new Date().toISOString(),
      note: 'Triggering is cron-only. Runs appear at github.com/' + OWNER + '/' + REPO + '/actions'
    };
    return new Response(JSON.stringify(body, null, 2), {
      status: healthy ? 200 : 503,
      headers: { 'content-type': 'application/json; charset=utf-8' }
    });
  }
};
