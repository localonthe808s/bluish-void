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

export default {
  async scheduled(event, env, ctx) {
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
      schedule_utc: ['5,20,35,50 12-23 * * *', '5,20,35,50 0-4 * * *'],
      now_utc: new Date().toISOString(),
      note: 'Triggering is cron-only. Runs appear at github.com/' + OWNER + '/' + REPO + '/actions'
    };
    return new Response(JSON.stringify(body, null, 2), {
      status: healthy ? 200 : 503,
      headers: { 'content-type': 'application/json; charset=utf-8' }
    });
  }
};
