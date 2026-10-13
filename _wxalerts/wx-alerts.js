// BLUISH WEATHER ALERTS (2026-10-13). Five alerts for any place a phone signs up for (HOME, WORK, ...):
//   UMBRELLA    8 AM local, once a day, when rain is likely between 8 AM and 10 PM
//   RAIN SOON   rain starting in the next ~15-45 minutes (Open-Meteo's 15-minute forecast; quiet 11 PM - 6 AM)
//   SEVERE      a National Weather Service WARNING for that exact point, the moment it is active (US only)
//   SWINGS      7 PM local: frost tonight, heat tomorrow, or tomorrow 20+ degrees colder than today
//   AURORA      7 PM local: tonight's forecast Kp puts the aurora in view from there, with mostly clear skies
// Open to anyone, no key: the weather is not private. Locations are rounded to 0.01 deg (~1 km) before they are kept,
// and phones within that box share one forecast check. Pushes use the same VAPID key and the same bv-sw.js as the
// Kalshi alerts (webpush.js is shared), so a phone has one subscription for both.
import { pushOne } from '../_kalshi/cron-worker/webpush.js';

const ORIGIN = 'https://bluishvoid.com';
const UA = '(bluishvoid.com weather alerts, https://bluishvoid.com)';
const TYPES = ['umbrella', 'rain', 'severe', 'swing', 'aurora'];
const PUSH_HOSTS = /(^|\.)(push\.apple\.com|fcm\.googleapis\.com|push\.services\.mozilla\.com|notify\.windows\.com)$/;
const BATCH = 1500;          /* places per tick (2 calls each + pushes): the account is on Workers Paid (10,000 calls per run), so every place is checked every tick; the cursor only rotates past 1,500 */

const cors = { 'Access-Control-Allow-Origin': ORIGIN, 'Access-Control-Allow-Headers': 'content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Vary': 'Origin' };
const J = (o, st) => new Response(JSON.stringify(o), { status: st || 200, headers: { 'content-type': 'application/json', ...cors } });
const r2 = (x) => Math.round(x * 100) / 100;
const gkey = (l) => `${l.lat.toFixed(2)},${l.lon.toFixed(2)}`;

async function getSubs(env){ return (await env.WX.get('subs', { type: 'json' })) || []; }

/* ---------------------------------------------------------------- sign-up ------------------------------------------ */
async function route(request, env) {
  const url = new URL(request.url);
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
  if (request.method !== 'POST') return J({ error: 'POST' }, 405);
  let b = {}; try { b = await request.json(); } catch (_) {}
  const subs = await getSubs(env);
  const ep = (b.sub && b.sub.endpoint) || b.endpoint || '';
  if (url.pathname === '/me') { const m = subs.find((x) => x.endpoint === ep); return J(m ? { locs: m.locs, types: m.types } : {}); }
  if (url.pathname === '/unsubscribe') {
    const keep = subs.filter((x) => x.endpoint !== ep);
    if (keep.length !== subs.length) await env.WX.put('subs', JSON.stringify(keep));
    return J({ ok: true });
  }
  if (url.pathname === '/test') {
    const m = subs.find((x) => x.endpoint === ep); if (!m) return J({ error: 'not signed up' }, 404);
    const r = await pushOne(m, { title: 'BLUISH weather alerts are on', body: `For ${m.locs.map((l) => l.name).join(' and ')}: ${m.types.map(label).join(', ')}.`, tag: 'wx-test', url: '/' }, jwk(env), 'high');
    return J({ ok: r.status >= 200 && r.status < 300 });
  }
  if (url.pathname === '/subscribe') {
    const s = b.sub;
    let host = ''; try { host = new URL(s.endpoint).hostname; } catch (_) {}
    if (!s || !s.keys || !s.keys.p256dh || !s.keys.auth || !PUSH_HOSTS.test(host)) return J({ error: 'bad subscription' }, 400);
    const locs = (Array.isArray(b.locs) ? b.locs : []).slice(0, 5).map((l) => ({
      name: String(l.name || 'HERE').toUpperCase().replace(/[^A-Z0-9 ]/g, '').slice(0, 14) || 'HERE',
      lat: r2(+l.lat), lon: r2(+l.lon) })).filter((l) => isFinite(l.lat) && isFinite(l.lon) && Math.abs(l.lat) <= 90 && Math.abs(l.lon) <= 180);
    const types = TYPES.filter((t) => Array.isArray(b.types) && b.types.indexOf(t) >= 0);
    if (!locs.length || !types.length) return J({ error: 'pick at least one place and one alert' }, 400);
    const keep = subs.filter((x) => x.endpoint !== s.endpoint).slice(-1999);
    keep.push({ endpoint: s.endpoint, keys: { p256dh: s.keys.p256dh, auth: s.keys.auth }, locs, types, at: new Date().toISOString() });
    await env.WX.put('subs', JSON.stringify(keep));
    return J({ ok: true });
  }
  return J({ error: 'not found' }, 404);
}
const label = (t) => ({ umbrella: 'umbrella', rain: 'rain soon', severe: 'severe warnings', swing: 'big swings', aurora: 'aurora' })[t] || t;
const jwk = (env) => (typeof env.VAPID_JWK === 'string' ? JSON.parse(env.VAPID_JWK) : env.VAPID_JWK);

/* ---------------------------------------------------------------- the checks --------------------------------------- */
const hm = (h, m) => { const ap = h < 12 ? 'AM' : 'PM', h12 = h % 12 || 12; return m ? `${h12}:${String(m).padStart(2, '0')} ${ap}` : `${h12} ${ap}`; };

/* the place's forecast: hourly rain odds/amounts and cloud, daily highs/lows (yesterday..tomorrow), the 15-minute rain */
async function forecast(lat, lon) {
  const u = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&hourly=precipitation_probability,precipitation,cloud_cover`
    + '&daily=temperature_2m_max,temperature_2m_min&minutely_15=precipitation&forecast_minutely_15=12&past_minutely_15=2'
    + '&past_days=1&forecast_days=2&temperature_unit=fahrenheit&precipitation_unit=inch&timezone=auto';
  const r = await fetch(u); if (!r.ok) throw new Error(`open-meteo ${r.status}`);
  return r.json();
}
/* local "now" as the same naive string Open-Meteo uses for its times */
function localNow(f) { const d = new Date(Date.now() + (f.utc_offset_seconds || 0) * 1000); return { iso: d.toISOString().slice(0, 16), h: d.getUTCHours(), m: d.getUTCMinutes(), date: d.toISOString().slice(0, 10) }; }

function umbrella(f, now) {
  if (now.h !== 8) return null;
  const H = f.hourly, rows = [];
  for (let i = 0; i < H.time.length; i++) { const t = H.time[i]; if (t.slice(0, 10) !== now.date) continue; const h = +t.slice(11, 13);
    if (h >= 8 && h <= 21) rows.push({ h, p: H.precipitation_probability[i] || 0, a: H.precipitation[i] || 0 }); }
  const wet = rows.filter((r) => r.p >= 50); if (!wet.length) return null;
  const tot = wet.reduce((s, r) => s + r.a, 0); if (tot < 0.02) return null;
  const pk = wet.reduce((a, r) => (r.a > a.a ? r : a), wet[0]), pmax = Math.max(...wet.map((r) => r.p));
  const from = wet[0].h, to = wet[wet.length - 1].h + 1;
  return { key: `umb:${now.date}`, title: 'Umbrella today', body: `Rain likely ${(from < 12) === (to < 12) ? hm(from).replace(/ [AP]M$/, '') : hm(from)}\u2013${hm(to % 24)} (up to ${pmax}%), heaviest around ${hm(pk.h)}.`, urg: 'normal' };
}

function rainSoon(f, now) {
  if (now.h >= 23 || now.h < 6) return null;
  const M = f.minutely_15; if (!M || !M.time) return null;
  let i0 = -1; for (let i = 0; i < M.time.length; i++) if (M.time[i] <= now.iso) i0 = i;
  if (i0 < 0) return null;
  const v = (i) => (M.precipitation[i] || 0);
  if (v(i0) >= 0.005 || (i0 > 0 && v(i0 - 1) >= 0.005)) return null;          /* already raining: not "starting" */
  let s = -1; for (let i = i0 + 1; i <= i0 + 3 && i < M.time.length; i++) if (v(i) >= 0.01) { s = i; break; }
  if (s < 0) return null;
  let e = s, pk = 0; while (e < M.time.length && v(e) >= 0.005) { pk = Math.max(pk, v(e)); e++; }
  const rate = pk * 4, kind = rate < 0.1 ? 'Light rain' : rate < 0.3 ? 'Moderate rain' : 'Heavy rain';
  const mins = Math.max(10, (s - i0) * 15 - now.m % 15), dur = (e - s) * 15;
  return { key: 'rain', cool: 3 * 3600e3, title: 'Rain soon',
    body: `${kind} starting in about ${Math.round(mins / 5) * 5} minutes${e >= M.time.length ? ', lasting a while' : `, for about ${dur >= 60 ? (dur / 60).toFixed(dur % 60 ? 1 : 0) + ' hour' + (dur > 60 ? 's' : '') : dur + ' minutes'}`}.`, urg: 'normal' };
}

function swings(f, now) {
  if (now.h !== 19) return null;
  const D = f.daily; if (!D || D.time.length < 3) return null;
  const tMax = D.temperature_2m_max[1], tMin = D.temperature_2m_min[1], nMax = D.temperature_2m_max[2], nMin = D.temperature_2m_min[2];
  const out = [];
  if (nMin != null && nMin <= 32 && tMin > 32) out.push(nMin <= 28 ? `Hard freeze tonight: down to ${Math.round(nMin)}° by morning.` : `Frost tonight: down to ${Math.round(nMin)}° by morning.`);
  if (nMax != null && nMax >= 90 && tMax < 90) out.push(`Heat tomorrow: up to ${Math.round(nMax)}°.`);
  if (nMax != null && tMax != null && tMax - nMax >= 20) out.push(`Much colder tomorrow: a high of ${Math.round(nMax)}°, ${Math.round(tMax - nMax)}° below today.`);
  return out.length ? { key: `swing:${now.date}`, title: out.length > 1 ? 'Big swings ahead' : out[0].split(':')[0], body: out.join(' '), urg: 'normal' } : null;
}

/* the site's own rule (index.html auroraVisibilityPctFromKp): geomagnetic latitude ~ latitude - 11 in North America,
   and the Kp it takes to put the aurora on the horizon there */
function minKp(lat) { const g = lat - 11;
  return g >= 66 ? 0 : g >= 62 ? 2 : g >= 58 ? 4 : g >= 54 ? 5 : g >= 50 ? 6 : g >= 40 ? 7 : g >= 30 ? 8 : 9; }
function aurora(f, now, kpTonight, lat) {
  if (now.h !== 19 || kpTonight == null || lat < 0) return null;
  const margin = kpTonight - minKp(lat); if (margin < 1) return null;                  /* "likely" or better only */
  const H = f.hourly, cc = [];
  for (let i = 0; i < H.time.length; i++) { const t = H.time[i], h = +t.slice(11, 13);
    if ((t.slice(0, 10) === now.date && h >= 21) || (t.slice(0, 10) > now.date && h <= 2)) cc.push(H.cloud_cover[i] || 0); }
  const cloud = cc.length ? cc.reduce((a, b) => a + b, 0) / cc.length : 100; if (cloud > 60) return null;
  return { key: `aurora:${now.date}`, title: 'Aurora tonight',
    body: `The northern lights may be visible low to the north after dark (Kp ${kpTonight.toFixed(0)} forecast). Skies look ${cloud < 30 ? 'clear' : 'mostly clear'}; get away from city lights.`, urg: 'high' };
}
async function kpTonightFor(cache, offsetSec, date) {
  if (!cache.kp) { try { const r = await fetch('https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json'); cache.kp = r.ok ? await r.json() : []; } catch (_) { cache.kp = []; } }
  let best = null; const next = new Date(Date.parse(date + 'T12:00:00Z') + 864e5).toISOString().slice(0, 10);
  for (const row of cache.kp) { if (!row || row.observed === 'observed') continue; const k = parseFloat(row.kp); if (isNaN(k)) continue;
    const t = new Date(Date.parse(String(row.time_tag).replace(' ', 'T') + (/Z$/.test(row.time_tag) ? '' : 'Z')) + offsetSec * 1000), d = t.toISOString().slice(0, 10), h = t.getUTCHours();
    if ((d === date && h >= 21) || (d === next && h <= 3)) best = best == null ? k : Math.max(best, k); }
  return best;
}

async function severe(lat, lon) {
  if (lat < 17 || lat > 72 || lon > -60) return [];                                   /* NWS covers the US */
  const r = await fetch(`https://api.weather.gov/alerts/active?point=${lat},${lon}`, { headers: { 'User-Agent': UA, 'Accept': 'application/geo+json' } });
  if (!r.ok) return [];
  const j = await r.json();
  return (j.features || []).map((x) => x.properties || {}).filter((p) => /Warning$/.test(p.event || '') && p.status !== 'Test').map((p) => {
    const until = p.ends || p.expires; let u = '';
    if (until) { const m = /T(\d\d):(\d\d)/.exec(until); if (m) u = `Until ${hm(+m[1], +m[2])}. `; }
    const ins = String(p.instruction || '').replace(/\s+/g, ' ').trim().split(/(?<=\.)\s/)[0] || '';
    return { key: `nws:${p.id}`, cool: 3 * 864e5, title: p.event, body: (u + (ins || p.headline || '')).slice(0, 220), urg: 'high' };
  });
}

/* ---------------------------------------------------------------- the tick ----------------------------------------- */
async function tick(env) {
  const subs = await getSubs(env); if (!subs.length) return 'no phones';
  const groups = {};
  for (const s of subs) for (const l of s.locs) { const k = gkey(l); (groups[k] = groups[k] || { lat: l.lat, lon: l.lon, who: [] }).who.push({ s, name: l.name }); }
  const keys = Object.keys(groups).sort();
  let cur = 0; if (keys.length > BATCH) cur = (+(await env.WX.get('cursor')) || 0) % keys.length;
  const todo = keys.length > BATCH ? keys.slice(cur, cur + BATCH).concat(keys.slice(0, Math.max(0, cur + BATCH - keys.length))) : keys;
  const state = (await env.WX.get('state', { type: 'json' })) || {}, before = JSON.stringify(state), now = Date.now(), cache = {};
  let sent = 0, dead = new Set(), log = [];
  for (const k of todo) {
    const g = groups[k]; let f;
    try { f = await forecast(g.lat, g.lon); } catch (e) { log.push(`${k} ${e.message}`); continue; }
    const ln = localNow(f), found = [];
    const wantsAny = (t) => g.who.some((w) => w.s.types.indexOf(t) >= 0);
    if (wantsAny('umbrella')) { const a = umbrella(f, ln); if (a) found.push(['umbrella', a]); }
    if (wantsAny('rain')) { const a = rainSoon(f, ln); if (a) found.push(['rain', a]); }
    if (wantsAny('swing')) { const a = swings(f, ln); if (a) found.push(['swing', a]); }
    if (wantsAny('aurora') && ln.h === 19) { const a = aurora(f, ln, await kpTonightFor(cache, f.utc_offset_seconds || 0, ln.date), g.lat); if (a) found.push(['aurora', a]); }
    if (wantsAny('severe')) { try { for (const a of await severe(g.lat, g.lon)) found.push(['severe', a]); } catch (_) {} }
    for (const [type, a] of found) {
      const sk = `${k}|${a.key}`, last = state[sk] || 0;
      if (a.cool ? now - last < a.cool : last) continue;                               /* dated keys: once ever; others: cool-down */
      state[sk] = now;
      for (const w of g.who) {
        if (w.s.types.indexOf(type) < 0 || dead.has(w.s.endpoint)) continue;
        try {
          const r = await pushOne(w.s, { title: `${a.title} · ${w.name}`, body: a.body, tag: `${type}:${k}`, url: '/' }, jwk(env), a.urg);
          if (r.status === 404 || r.status === 410) dead.add(w.s.endpoint); else if (r.status < 300) sent++; else log.push(`push ${r.status}`);
        } catch (e) { log.push(String(e)); }
      }
    }
  }
  for (const sk of Object.keys(state)) if (now - state[sk] > 4 * 864e5) delete state[sk];
  if (JSON.stringify(state) !== before) await env.WX.put('state', JSON.stringify(state));
  if (dead.size) await env.WX.put('subs', JSON.stringify(subs.filter((s) => !dead.has(s.endpoint))));
  if (keys.length > BATCH) await env.WX.put('cursor', String((cur + BATCH) % keys.length));
  return `${todo.length}/${keys.length} places, ${sent} sent${log.length ? ' | ' + log.slice(0, 4).join(' | ') : ''}`;
}

export default {
  fetch: route,
  async scheduled(event, env, ctx) {
    ctx.waitUntil(tick(env).then((r) => console.log(`[wx] ${r}`)).catch((e) => console.log(`[wx] FAILED ${e}`)));
  },
  // exported for tests
  _t: { umbrella, rainSoon, swings, aurora, minKp, localNow, severe }
};
