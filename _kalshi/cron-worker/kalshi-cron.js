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
