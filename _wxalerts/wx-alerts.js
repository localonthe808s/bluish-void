// BLUISH WEATHER ALERTS (2026-10-13). Five alerts for any place a phone signs up for (HOME, WORK, ...):
//   UMBRELLA    8 AM local, once a day, when rain is likely between 8 AM and 10 PM
//   RAIN SOON   rain starting in the next ~15-45 minutes (Open-Meteo's 15-minute forecast; quiet 11 PM - 6 AM)
//   SEVERE      a National Weather Service WARNING for that exact point, the moment it is active (US only)
//   SWINGS      7 PM local: frost tonight, heat tomorrow, or tomorrow 20+ degrees colder than today
//   AURORA      7 PM local: tonight's forecast Kp puts the aurora in view from there, with mostly clear skies
//   LIGHTNING   strikes within 10 miles (Blitzortung's live network), then the all-clear 30 minutes after the last one
//   EARTHQUAKE  every minute: a USGS quake (worldwide, M2.5+) whose shaking is likely felt at the place
//   WILDFIRE    a new wildfire within 15 miles (NIFC incidents, US)
//   AIR         the air turning unhealthy (US AQI 151+, Open-Meteo air quality), once a day
//   SUNSET      about an hour before sunset, when tonight's sunset scores EXCELLENT or EPIC (70+) on the site's own formula
// SEVERE is split in two lanes (2026-10-13, user: "flash flooding / tornados / earthquakes most importantly" -> "make
// sure all hazards are covered"): the storm-based warnings drawn as polygons (tornado, flash flood, severe thunderstorm,
// extreme wind, snow squall) are read nationally EVERY MINUTE and matched to each place by the warning's own outline;
// every other NWS warning (hurricane, storm surge, tsunami, flood, winter storm, blizzard, ice storm, extreme heat and
// cold, high wind, red flag, dust storm, avalanche ...) is read per place every 10 minutes.
// Open to anyone, no key: the weather is not private. Locations are rounded to 0.01 deg (~1 km) before they are kept,
// and phones within that box share one forecast check. Pushes use the same VAPID key and the same bv-sw.js as the
// Kalshi alerts (webpush.js is shared), so a phone has one subscription for both.
import { pushOne } from '../_kalshi/cron-worker/webpush.js';
import { issTrack, issAlert, eclipsesSoon, eclipseAlerts, meteorAlert } from './space-alerts.js';

const ORIGIN = 'https://bluishvoid.com';
const UA = '(bluishvoid.com weather alerts, https://bluishvoid.com)';
const TYPES = ['umbrella', 'rain', 'severe', 'swing', 'aurora', 'lightning', 'quake', 'fire', 'air', 'sunset', 'iss', 'eclipse', 'meteor'];
const PUSH_HOSTS = /(^|\.)(push\.apple\.com|fcm\.googleapis\.com|push\.services\.mozilla\.com|notify\.windows\.com)$/;
const BATCH = 1500;          /* places per tick (2 calls each + pushes): the account is on Workers Paid (10,000 calls per run), so every place is checked every tick; the cursor only rotates past 1,500 */

const cors = { 'Access-Control-Allow-Origin': ORIGIN, 'Access-Control-Allow-Headers': 'content-type',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', 'Vary': 'Origin' };
const J = (o, st) => new Response(JSON.stringify(o), { status: st || 200, headers: { 'content-type': 'application/json', ...cors } });
const r2 = (x) => Math.round(x * 100) / 100;
const gkey = (l) => `${l.lat.toFixed(2)},${l.lon.toFixed(2)}`;

async function getSubs(env){ return (await env.WX.get('subs', { type: 'json' })) || []; }

/* ---------------------------------------------------------------- sign-up ------------------------------------------ */
async function route(request, env) {
  const url = new URL(request.url);
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
  if (url.pathname === '/health') {   /* the Kalshi worker's watchdog reads this */
    const b0 = await env.WX.get('beat', { type: 'json' }).catch(() => null);
    return J({ ok: !!b0, last: b0 && b0.at, ageMin: b0 ? Math.round((Date.now() - Date.parse(b0.at)) / 6e4) : null });
  }
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
    /* kind 'space' (2026-10-16, user: "send me a test space alert"): a FIXED sample in the real ISS format, marked as a test --
       the caller picks only which sample, never the words, so this cannot be used to push arbitrary text */
    const msg = b.kind === 'space'
      ? { title: 'TEST · ISS overhead · 5:51 AM', body: 'Visible 5:51 AM for 6 min: appears 24° up in the SW, 65° up in the SE, sets in the NE. (A sample: the real one comes 10-20 minutes before a pass you can see.)', tag: 'wx-test-space', url: '/#go=space' }
      : { title: 'BLUISH weather alerts are on', body: `For ${m.locs.map((l) => l.name).join(' and ')}: ${m.types.map(label).join(', ')}.`, tag: 'wx-test', url: '/' };
    const r = await pushOne(m, msg, jwk(env), 'high');
    return J({ ok: r.status >= 200 && r.status < 300 });
  }
  if (url.pathname === '/subscribe') {
    const s = b.sub;
    let host = ''; try { host = new URL(s.endpoint).hostname; } catch (_) {}
    if (!s || !s.keys || !s.keys.p256dh || !s.keys.auth || !PUSH_HOSTS.test(host)) return J({ error: 'bad subscription' }, 400);
    const locs = (Array.isArray(b.locs) ? b.locs : []).slice(0, 5).map((l) => ({
      name: String(l.name || 'HERE').toUpperCase().replace(/[^A-Z0-9 ]/g, '').slice(0, 14) || 'HERE',
      lat: r2(+l.lat), lon: r2(+l.lon),
      /* each place its own alerts (user 2026-10-14); a place without a list takes the phone's */
      types: Array.isArray(l.types) ? TYPES.filter((t) => l.types.indexOf(t) >= 0) : null })).filter((l) => isFinite(l.lat) && isFinite(l.lon) && Math.abs(l.lat) <= 90 && Math.abs(l.lon) <= 180);
    const given = TYPES.filter((t) => Array.isArray(b.types) && b.types.indexOf(t) >= 0);
    const types = locs.some((l) => l.types) ? TYPES.filter((t) => locs.some((l) => (l.types || given).indexOf(t) >= 0)) : given;
    locs.forEach((l) => { if (!l.types) delete l.types; });
    if (!locs.length || !types.length) return J({ error: 'pick at least one place and one alert' }, 400);
    const keep = subs.filter((x) => x.endpoint !== s.endpoint).slice(-1999);
    keep.push({ endpoint: s.endpoint, keys: { p256dh: s.keys.p256dh, auth: s.keys.auth }, locs, types, at: new Date().toISOString() });
    await env.WX.put('subs', JSON.stringify(keep));
    return J({ ok: true });
  }
  return J({ error: 'not found' }, 404);
}
const label = (t) => ({ umbrella: 'umbrella', rain: 'rain soon', severe: 'severe warnings', swing: 'big swings', aurora: 'aurora', lightning: 'lightning', quake: 'earthquakes', fire: 'wildfires', air: 'unhealthy air', sunset: 'great sunsets', iss: 'ISS overhead', eclipse: 'eclipses', meteor: 'meteor showers' })[t] || t;
const jwk = (env) => (typeof env.VAPID_JWK === 'string' ? JSON.parse(env.VAPID_JWK) : env.VAPID_JWK);

/* ---------------------------------------------------------------- the checks --------------------------------------- */
const hm = (h, m) => { const ap = h < 12 ? 'AM' : 'PM', h12 = h % 12 || 12; return m ? `${h12}:${String(m).padStart(2, '0')} ${ap}` : `${h12} ${ap}`; };

/* the place's forecast: hourly rain odds/amounts and cloud, daily highs/lows (yesterday..tomorrow), the 15-minute rain */
async function forecast(lat, lon) {
  const u = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&hourly=precipitation_probability,precipitation,cloud_cover,weather_code,cape,cloud_cover_low,cloud_cover_mid,cloud_cover_high,relative_humidity_2m,pressure_msl,wind_speed_300hPa`
    + '&daily=temperature_2m_max,temperature_2m_min,sunset&minutely_15=precipitation&forecast_minutely_15=12&past_minutely_15=2'
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
    body: `The northern lights may be visible low to the north after dark (Kp ${kpTonight.toFixed(0)} forecast). Skies ${cloud < 30 ? 'clear' : 'mostly clear'} (${Math.round(cloud)}% cloud).`, urg: 'high' };
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
  return (j.features || []).map((x) => x.properties || {}).filter((p) => /Warning$/.test(p.event || '') && p.status !== 'Test' && POLY_EVENTS.indexOf(p.event) < 0 && vtecKey(p)).map((p) => {
    const until = p.ends || p.expires; let u = '';
    if (until) { const m = /T(\d\d):(\d\d)/.exec(until); if (m) u = `Until ${hm(+m[1], +m[2])}. `; }
    return { key: vtecKey(p), cool: 3 * 864e5, title: p.event, body: (u + warnFacts(p)).slice(0, 220), urg: 'high' };
  });
}

/* ---------------------------------------------------------------- lightning ---------------------------------------- */
/* Blitzortung (volunteer VLF network, free for non-commercial use with credit): the same public socket the site's radar
   reads. The whole planet comes down it (~5 strikes/s), so it is opened only when some place could have a storm --
   a rain chance of 20% or more (or thunder) now or within two hours -- or a storm is already near,
   and only for a short sample each tick. */
const LTG_HOSTS = ['ws1', 'ws7', 'ws8'], LTG_MI = 10;
function lzw(b) { const e = {}, d = String(b).split(''); let c = d[0], f = c, o = 256, k; const out = [c];
  for (let i = 1; i < d.length; i++) { const cc = d[i].charCodeAt(0); k = cc < 256 ? d[i] : (e[cc] !== undefined ? e[cc] : f + c); out.push(k); c = k.charAt(0); e[o++] = f + c; f = k; }
  return out.join(''); }
const miles = (a, b, c, d) => { const R = 3958.8, r = Math.PI / 180, x = Math.sin((c - a) * r / 2), y = Math.sin((d - b) * r / 2);
  return 2 * R * Math.asin(Math.sqrt(x * x + Math.cos(a * r) * Math.cos(c * r) * y * y)); };
const compass = (a, b, c, d) => { const r = Math.PI / 180, y = Math.sin((d - b) * r) * Math.cos(c * r), x = Math.cos(a * r) * Math.sin(c * r) - Math.sin(a * r) * Math.cos(c * r) * Math.cos((d - b) * r);
  return ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(((Math.atan2(y, x) / r + 360) % 360) / 45) % 8]; };
function stormy(f, now) {
  const H = f.hourly; if (!H || !H.weather_code) return false;
  for (let i = 0; i < H.time.length; i++) { const t = H.time[i]; if (t < now.iso.slice(0, 13) || t > hourPlus(now.iso, 2)) continue;
    /* any real rain chance, not just forecast thunder: on 2026-10-13 a storm was striking near Ogdensburg NY under a
       forecast of rain with CAPE 0 and no thunder code -- a thunder-only gate would have missed it */
    if ((H.weather_code[i] || 0) >= 95 || (H.precipitation_probability[i] || 0) >= 20) return true; }
  return false;
}
/* how long the storm should last there: consecutive hours from now with thunder in the forecast or a 50%+ rain chance */
function stormLength(f, now) {
  const H = f.hourly; let n = 0, started = false;
  for (let i = 0; i < H.time.length; i++) { const t = H.time[i]; if (t.slice(0, 13) < now.iso.slice(0, 13)) continue;
    const wet = (H.weather_code[i] || 0) >= 95 || (H.precipitation_probability[i] || 0) >= 50;
    if (wet) { n++; started = true; } else if (started || n === 0 && t.slice(0, 13) > now.iso.slice(0, 13)) break; }
  if (n <= 1) return 'Looks like a short storm, under an hour.';
  const end = new Date(Date.parse(now.iso.slice(0, 13) + ':00:00Z') + n * 3600e3);
  return n >= 4 ? `Looks like a long storm, about ${n} hours (until around ${hm(end.getUTCHours())}).` : `Should last about ${n} hours, until around ${hm(end.getUTCHours())}.`;
}
const hourPlus = (iso, h) => new Date(Date.parse(iso.slice(0, 13) + ':00:00Z') + h * 3600e3).toISOString().slice(0, 13);
/* listen for `ms`, keep strikes within ~25 mi of any of the given places: [lat, lon, tMs] */
async function sampleStrikes(places, ms) {
  const out = [];
  for (let h = 0; h < LTG_HOSTS.length; h++) {
    let ws; try { const r = await fetch(`https://${LTG_HOSTS[h]}.blitzortung.org/`, { headers: { Upgrade: 'websocket', Origin: 'https://map.blitzortung.org' } }); ws = r.webSocket; } catch (_) {}
    if (!ws) continue;
    ws.accept(); ws.send('{"a":111}');
    ws.addEventListener('message', (ev) => { let j; try { j = JSON.parse(lzw(ev.data)); } catch (_) { return; }
      if (typeof j.lat !== 'number') return;
      for (const p of places) if (Math.abs(j.lat - p.lat) < 0.4 && Math.abs(j.lon - p.lon) < 0.5) { out.push([j.lat, j.lon, Date.now()]); break; } });
    await new Promise((r) => setTimeout(r, ms));
    try { ws.close(); } catch (_) {}
    return { ok: true, strikes: out, secs: ms / 1000 };
  }
  return { ok: false, strikes: out };
}

/* ONE ALERT, NOT TWO (user 2026-10-14: "if work and home are nearby only show one without mentioning HOME or WORK / dont send
   one for both"). Each phone's alerts from one tick are collected first; the same event (same type and key, the place's own
   box stripped off) at places within NEAR_MI of each other goes out ONCE, with no place name. Far-apart places keep theirs. */
const NEAR_MI = 15;
/* where a tap lands (user 2026-10-14): the view that shows the thing the alert is about */
const GO = { severe: 'radar', rain: 'radar', lightning: 'radar', umbrella: 'radar', quake: 'hazards', fire: 'hazards', air: 'hazards', aurora: 'aurora', sunset: 'golden', swing: 'top', iss: 'space', eclipse: 'space', meteor: 'space' };
async function sendMerged(env, pend, dead, log, state) {
  let sent = 0;
  for (const ep of Object.keys(pend)) {
    const items = pend[ep], used = new Array(items.length).fill(false);
    for (let i = 0; i < items.length; i++) {
      if (used[i]) continue; used[i] = true;
      const A = items[i], group = [A];
      for (let j = i + 1; j < items.length; j++) { const B = items[j];
        if (!used[j] && B.type === A.type && B.ekey === A.ekey && (A.type === 'meteor' || A.type === 'eclipse' || group.some((g) => miles(g.lat, g.lon, B.lat, B.lon) <= NEAR_MI))) { used[j] = true; group.push(B); } }
      const one = group.length > 1, a = A.a;
      let body = one ? String(a.body).replace(new RegExp(' of ' + A.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b'), '') : a.body;
      /* A METEOR SHOWER IS ONE NOTIFICATION, however far apart the places (user 2026-10-16: "if you follow multiple areas and
         theyre all saying theres a meteor shower, can you merge them into one"): the shared numbers once, each place only
         where it differs (its clouds, or its rate and best hour) */
      if (A.type === 'meteor' && one && a.parts) {
        const P = group.map((g) => ({ n: g.name, p: g.a.parts })).filter((x) => x.p);
        const top = Math.max(...P.map((x) => x.p.rate));
        const same = P.every((x) => x.p.best === P[0].p.best && x.p.rate >= 0.9 * top);   /* 86 vs 88 an hour is the same night */
        const cl = (x) => (x.p.cc != null ? `clouds ${x.p.cc}%` : '');
        body = same
          ? `Up to about ${top} an hour under dark skies, best around ${P[0].p.best} with the radiant ${P[0].p.alt}° up in the ${P[0].p.dir}. `
            + (P.some((x) => x.p.cc != null) ? P.map((x) => `${x.n} ${cl(x) || 'clouds unknown'}`).join(', ') + '. ' : '') + P[0].p.moon
          : P.map((x) => `${x.n}: about ${x.p.rate}/hr, best ${x.p.best}${cl(x) ? ', ' + cl(x) : ''}`).join('. ') + '. ' + P[0].p.moon;
      }
      /* AN ECLIPSE TOO (user 2026-10-16: "merge eclipse alerts across places too"): one notification; said once when every place
         sees the same thing, else a short line per place (coverage and times differ a lot across a continent) */
      let title = one ? a.title : `${a.title}${a.sep || ' \u00b7 '}${A.name}`;
      if (A.type === 'eclipse' && one && a.parts) {
        const P = group.map((g) => ({ n: g.name, p: g.a.parts })).filter((x) => x.p);
        const cl = (x) => (x.p.cc != null ? `clouds ${x.p.cc}%` : '');
        body = P.every((x) => x.p.words === P[0].p.words)
          ? P[0].p.words + (P.some((x) => x.p.cc != null) ? ' ' + P.map((x) => `${x.n} ${cl(x) || 'clouds unknown'}`).join(', ') + '.' : '')
          : (() => { const by = {}; P.forEach((x) => { const k = x.p.short + (cl(x) ? ', ' + cl(x) : ''); (by[k] = by[k] || []).push(x.n); });   /* places that see it alike share a line */
              return Object.keys(by).map((k) => `${by[k].join(', ')}: ${k}`).join('. ') + '. ' + P[0].p.safe; })();
        if (/:soon$/.test(A.ekey) && P.some((x) => x.p.short !== P[0].p.short)) title = `${P[0].p.base} starts soon`;
      }
      if (dead.has(ep)) continue;
      /* and once per phone: places in other time zones reach 7 PM (a shower) or 8 AM (an eclipse notice) in a later tick; the
         30-minute eclipse warning stays per place -- a different place's eclipse starts at a different moment */
      const once = state && (A.type === 'meteor' || (A.type === 'eclipse' && /:(week|day)$/.test(A.ekey))) ? `ep:${ep.slice(-24)}|${A.ekey}` : null;
      if (once && state[once]) continue;
      if (once) state[once] = Date.now();
      try { const r = await pushOne(A.s, { title, body, tag: `${A.type}:${A.ekey}`, url: '/#go=' + (GO[A.type] || 'top') }, jwk(env), a.urg);
        if (r.status === 404 || r.status === 410) dead.add(ep); else if (r.status < 300) sent++; else log.push(`push ${r.status}`); } catch (e) { log.push(String(e)); }
    }
  }
  return sent;
}

/* ---------------------------------------------------------------- hazards: fast lane ------------------------------- */
const POLY_EVENTS = ['Tornado Warning', 'Flash Flood Warning', 'Severe Thunderstorm Warning', 'Extreme Wind Warning', 'Snow Squall Warning'];
function inRing(lon, lat, ring) { let c = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) { const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
    if (((yi > lat) !== (yj > lat)) && (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) c = !c; }
  return c; }
function inGeom(lon, lat, g) { if (!g) return false;
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
  return polys.some((P) => inRing(lon, lat, P[0]) && !P.slice(1).some((h) => inRing(lon, lat, h))); }
/* THE WARNING'S OWN EVENT NUMBER (2026-10-14): NWS reissues a warning under a new id every time it is extended or updated,
   which alerted the same tornado twice. VTEC ("/O.EXT.KOKX.TO.W.0012.261014T2100Z-.../") names the event: office +
   phenomenon + significance + event number + year stays the same through every update. Cancellations/expiries return null. */
function vtecKey(p) {
  const v = ((p.parameters || {}).VTEC || [])[0] || '', m = /\/O\.(\w{3})\.(\w{4})\.(\w{2})\.(\w)\.(\d{4})\.(\d{2})?/.exec(v);
  if (!m) return `nws:${p.id}`;
  if (m[1] === 'CAN' || m[1] === 'EXP') return null;
  return `nws:${m[2]}.${m[3]}.${m[4]}.${m[5]}`;   /* no year: a CON reissue writes its start as 000000; event numbers recur yearly, far beyond the 3-day memory */
}
/* the hazard itself from the NWS text ("* WHAT...Snow. Total accumulations 6 to 10 inches."), never the instructions */
function warnFacts(p) {
  const d = String(p.description || '').replace(/\s+/g, ' ');
  const w = /\*\s*WHAT\.\.\.(.*?)(?=\*\s*[A-Z ]{3,}\.\.\.|$)/.exec(d);
  const tidy = (x) => x.trim().replace(/\.+$/, '') + '.';
  if (w) return tidy(w[1]);
  const h = /HAZARD\.\.\.(.*?)(?=SOURCE\.\.\.|IMPACT\.\.\.|$)/.exec(d);
  if (h) return tidy(h[1]);
  /* fire-weather style: the measured lines (WINDS / RELATIVE HUMIDITY / TEMPERATURES ...) */
  const parts = []; const rx = /\*\s*(WINDS?|RELATIVE HUMIDITY|HUMIDITY|TEMPERATURES?|SNOW|ICE|VISIBILITY)\.\.\.(.*?)(?=\*\s*[A-Z ]{3,}\.\.\.|$)/g; let m;
  while ((m = rx.exec(d)) && parts.length < 3) parts.push(m[1].charAt(0) + m[1].slice(1).toLowerCase() + ': ' + m[2].trim().replace(/\.+$/, ''));
  if (parts.length) return parts.join('. ') + '.';
  return String(p.headline || '').replace(/ issued .*? by NWS.*$/i, '');
}
async function polyWarnings() {
  const r = await fetch('https://api.weather.gov/alerts/active?status=actual&event=' + POLY_EVENTS.map(encodeURIComponent).join(','), { headers: { 'User-Agent': UA, 'Accept': 'application/geo+json' } });
  if (!r.ok) throw new Error(`nws ${r.status}`);
  return ((await r.json()).features || []).filter((f) => f.geometry);
}
function warnMsg(f) {
  const p = f.properties || {}, P = p.parameters || {}, first = (k) => (P[k] && P[k][0]) || '';
  const cat = first('tornadoDamageThreat') === 'CATASTROPHIC' || first('flashFloodDamageThreat') === 'CATASTROPHIC';
  const pds = first('tornadoDamageThreat') === 'CONSIDERABLE' || first('flashFloodDamageThreat') === 'CONSIDERABLE';
  let title = p.event;
  if (cat) title = p.event === 'Tornado Warning' ? 'TORNADO EMERGENCY' : p.event === 'Flash Flood Warning' ? 'FLASH FLOOD EMERGENCY' : p.event;
  const det = first('tornadoDetection'); const until = p.ends || p.expires; let u = '';
  if (until) { const m = /T(\d\d):(\d\d)/.exec(until); if (m) u = `Until ${hm(+m[1], +m[2])}. `; }
  const lead = p.event === 'Tornado Warning' ? (det === 'OBSERVED' ? 'Tornado observed. ' : 'Tornado indicated by radar. ') : '';
  const hail = first('maxHailSize'), wind = first('maxWindGust'), extra = [hail && +hail > 0 ? `hail up to ${hail} in` : '', wind ? `gusts to ${String(wind).replace(/\s*MPH/i, ' mph')}` : ''].filter(Boolean).join(', ');
  return { key: vtecKey(p), title: (pds && !cat ? title + ' (particularly dangerous)' : title), body: (u + lead + (extra ? extra.charAt(0).toUpperCase() + extra.slice(1) + '. ' : '') + (lead || extra ? '' : warnFacts(p))).trim().slice(0, 230), urg: 'high' };
}
/* felt shaking, roughly: intensity from magnitude and hypocentral distance (a California-style attenuation, MMI ~
   3.67 + 1.17 M - 3.19 log10(km)); 3 and up is felt by some -- 3.5 missed an M4.5 at 40 mi and an M6 at 120 mi */
const MMI_WORD = (x) => x >= 8 ? 'severe' : x >= 7 ? 'very strong' : x >= 6 ? 'strong' : x >= 5 ? 'moderate' : x >= 4 ? 'light' : 'weak, felt by some';
function quakeAt(q, lat, lon) {
  const [qlon, qlat, depth] = q.geometry.coordinates, d = miles(lat, lon, qlat, qlon), km = Math.hypot(d * 1.609, depth || 10);
  const mmi = 3.67 + 1.17 * q.properties.mag - 3.19 * Math.log10(Math.max(km, 5));
  return { mi: d, mmi, dir: compass(lat, lon, qlat, qlon) };
}
async function fastTick(env) {
  const subs = await getSubs(env);
  const want = subs.filter((s) => s.types.indexOf('severe') >= 0 || s.types.indexOf('quake') >= 0); if (!want.length) return 'no phones';
  const state = (await env.WX.get('state:fast', { type: 'json' })) || {}, before = JSON.stringify(state), now = Date.now();
  let W = [], Q = [], sent = 0; const log = [], dead = new Set(), PEND = {};
  if (want.some((s) => s.types.indexOf('severe') >= 0)) { try { W = await polyWarnings(); } catch (e) { log.push(String(e)); } }
  if (want.some((s) => s.types.indexOf('quake') >= 0)) { try { const r = await fetch('https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_hour.geojson'); Q = r.ok ? ((await r.json()).features || []).filter((q) => now - q.properties.time < 45 * 60e3) : []; } catch (e) { log.push(String(e)); } }
  for (const s of want) for (const l of s.locs) {
    const out = [];
    const lt = l.types || s.types;   /* this place's own alerts */
    if (lt.indexOf('severe') >= 0) for (const f of W) if (vtecKey(f.properties || {}) && inGeom(l.lon, l.lat, f.geometry)) out.push(warnMsg(f));
    if (lt.indexOf('quake') >= 0) for (const q of Q) { const a = quakeAt(q, l.lat, l.lon); if (a.mmi < 3) continue;
      const P = q.properties, ago = Math.max(1, Math.round((now - P.time) / 60e3));
      out.push({ key: `eq:${q.id}`, title: `M${P.mag.toFixed(1)} earthquake`, urg: a.mmi >= 5 ? 'high' : 'normal',
        body: `${Math.round(a.mi)} miles ${a.dir} of ${l.name}, ${ago} min ago (${P.place}). Shaking there likely ${MMI_WORD(a.mmi)}.${P.tsunami ? ' Tsunami message issued.' : ''}` }); }
    for (const a of out) {
      const sk = `${gkey(l)}|${s.endpoint.slice(-24)}|${a.key}`; if (state[sk]) continue; state[sk] = now;
      (PEND[s.endpoint] = PEND[s.endpoint] || []).push({ s, type: a.key.split(':')[0], ekey: a.key, a, name: l.name, lat: l.lat, lon: l.lon });
    }
  }
  sent += await sendMerged(env, PEND, dead, log);
  for (const sk of Object.keys(state)) if (now - state[sk] > 3 * 864e5) delete state[sk];
  if (JSON.stringify(state) !== before) await env.WX.put('state:fast', JSON.stringify(state));
  if (dead.size) await env.WX.put('subs', JSON.stringify(subs.filter((x) => !dead.has(x.endpoint))));
  return `fast: ${W.length} polygon warnings, ${Q.length} quakes, ${sent} sent${log.length ? ' | ' + log.join(' | ') : ''}`;
}

/* ---------------------------------------------------------------- hazards: 10-minute lane ------------------------- */
let FIRES = null;
async function firesNear(lat, lon) {
  if (lat < 17 || lat > 72 || lon > -60) return [];
  if (!FIRES) { const r = await fetch('https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/USA_Wildfires_v1/FeatureServer/0/query?where=' + encodeURIComponent("IncidentTypeCategory='WF' AND (PercentContained IS NULL OR PercentContained<100)") + '&outFields=IrwinID,IncidentName,DailyAcres,PercentContained,FireDiscoveryDateTime&outSR=4326&f=geojson');
    FIRES = r.ok ? ((await r.json()).features || []) : []; }
  return FIRES.filter((f) => f.geometry && f.geometry.coordinates).map((f) => ({ f, d: miles(lat, lon, f.geometry.coordinates[1], f.geometry.coordinates[0]) })).filter((x) => x.d <= 15)
    .map(({ f, d }) => { const P = f.properties, c = f.geometry.coordinates;
      return { key: `fire:${P.IrwinID || P.IncidentName}`, cool: 30 * 864e5, title: 'Wildfire nearby', urg: d <= 5 ? 'high' : 'normal',
        body: `${P.IncidentName || 'A wildfire'} is ${Math.max(1, Math.round(d))} miles ${compass(lat, lon, c[1], c[0])}${P.DailyAcres ? `, ${Math.round(P.DailyAcres).toLocaleString('en-US')} acres` : ''}${P.PercentContained != null ? `, ${P.PercentContained}% contained` : ''}.` }; });
}
async function airNow(lat, lon, now) {
  if (now.h < 7 || now.h >= 22) return null;   /* quiet hours (user 2026-10-14): unhealthy air waits for 7 AM; the day's key lets the morning tick send it */
  const lvlOf = (a) => (a >= 301 ? 'hazardous' : a >= 201 ? 'very unhealthy' : 'unhealthy');
  /* MEASURED first (user 2026-10-29: "switch the air alert to measured too"): EPA AirNow monitors within 25 miles, through the proxy's
     /airnow route (it holds the key, caches 15 min per ~5 km). The highest pollutant AQI is the AQI, AirNow's own rule. Only where no
     monitor reports does the CAMS model (Open-Meteo) decide, and the alert then says it is a model estimate. */
  try {
    const r = await fetch(`https://proxy.bluishvoid.com/airnow?kind=obs&lat=${(+lat).toFixed(2)}&lon=${(+lon).toFixed(2)}`, { headers: { 'User-Agent': 'bluish-wx-alerts' } });
    const rows = r.ok ? await r.json() : null;
    if (Array.isArray(rows)) {
      let top = null;
      for (const x of rows) { const a = x.nowcastAQI; if (a != null && a >= 0 && (!top || a > top.nowcastAQI)) top = x; }
      if (top) {
        const a = top.nowcastAQI; if (a < 151) return null;
        const p = String(top.parameterName || '').toUpperCase() === 'OZONE' ? 'ozone' : String(top.parameterName || '');
        return { key: `air:${now.date}`, title: 'Unhealthy air', urg: a >= 201 ? 'high' : 'normal',
          body: `US AQI ${a} (${lvlOf(a)}) measured${top.siteName ? ` at ${top.siteName}` : ''}, from ${p}.` };
      }
    }
  } catch (_) { /* no measured reading: the model below */ }
  const r = await fetch(`https://air-quality-api.open-meteo.com/v1/air-quality?latitude=${lat}&longitude=${lon}&current=us_aqi,pm2_5,ozone`); if (!r.ok) return null;
  const c = (await r.json()).current || {}; const a = c.us_aqi; if (a == null || a < 151) return null;
  return { key: `air:${now.date}`, title: 'Unhealthy air', urg: a >= 201 ? 'high' : 'normal',
    body: `US AQI ${a} (${lvlOf(a)}), model estimate (no air monitor nearby)${c.pm2_5 != null ? `, PM2.5 ${Math.round(c.pm2_5)} \u00b5g/m\u00b3` : ''}.` };
}

/* ---------------------------------------------------------------- sunset ------------------------------------------- */
/* THE SITE'S OWN SUNSET SCORE, server side (user 2026-10-14: "make an alert for good sunsets"). index.html's showGoldenInsight
   (scoreOnly) is THE score; this is its formula on the same inputs the worker can reach: the 100-point budget -- cloud canvas
   (mid+high) 25, western horizon clear 18 (low cloud overhead AND along the light path 60-400 km toward the sun), aerosol 15
   (CAMS AOD), dry air 12, dry conditions 10, pressure 8, clearing bonus 8, upper winds 4 -- the sun-blocked cap 25 and the
   light-path cap/penalty. Left out: the card's cloud-genus read, the NWS cross-check and the smoke/front intel (page-only).
   Fires 55-75 min before sunset, once a day per place, at 70+ (EXCELLENT / EPIC, the site's cutoffs) AND some mid/high cloud. */
function sunsetAz(lat, dateIso) {
  const d = new Date(dateIso + 'T12:00:00Z'), n = Math.floor((d - Date.UTC(d.getUTCFullYear(), 0, 0)) / 864e5), r = Math.PI / 180;
  const dec = -23.44 * Math.cos(r * 360 / 365 * (n + 10)), c = Math.sin(dec * r) / Math.cos(lat * r);
  return 360 - Math.acos(Math.max(-1, Math.min(1, c))) / r;            /* degrees from north, west of south at sunset */
}
function dest(lat, lon, km, az) { const R = 6371, r = Math.PI / 180, d = km / R, b = az * r, la = lat * r, lo = lon * r;
  const la2 = Math.asin(Math.sin(la) * Math.cos(d) + Math.cos(la) * Math.sin(d) * Math.cos(b));
  const lo2 = lo + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(la), Math.cos(d) - Math.sin(la) * Math.sin(la2));
  return [la2 / r, lo2 / r]; }
async function sunsetScore(f, lat, lon, ssIso) {
  const H = f.hourly, T = Date.parse(ssIso + ':00Z');
  const near = (arr) => { let s = 0, w = 0; for (let i = 0; i < H.time.length; i++) { const dt = Math.abs(Date.parse(H.time[i] + ':00Z') - T) / 60e3; if (dt > 90 || arr[i] == null) continue; const k = 1 - dt / 120; s += arr[i] * k; w += k; } return w ? s / w : null; };
  const at = (arr, h) => { let best = null, bd = 1e12; for (let i = 0; i < H.time.length; i++) { const dt = Math.abs(Date.parse(H.time[i] + ':00Z') - (T - h * 3600e3)); if (dt < bd && arr[i] != null) { bd = dt; best = arr[i]; } } return best; };
  const cL = Math.round(near(H.cloud_cover_low) || 0), cM = Math.round(near(H.cloud_cover_mid) || 0), cH = Math.round(near(H.cloud_cover_high) || 0);
  const rh = near(H.relative_humidity_2m), pr = near(H.precipitation), pNow = at(H.pressure_msl, 0), p3 = at(H.pressure_msl, 3), w300 = near(H.wind_speed_300hPa);
  const pre = at(H.precipitation, 4), preL = at(H.cloud_cover_low, 4);
  /* the light path: low (and thick mid) cloud 60/150/250/400 km toward the setting sun, weighted as the page does */
  const az = sunsetAz(lat, ssIso.slice(0, 10)), KM = [60, 150, 250, 400], WT = { 60: 0.7, 150: 1, 250: 1, 400: 0.8 };
  let block = null, lows = [];
  try { const P = KM.map((k) => dest(lat, lon, k, az));
    const r = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${P.map((p) => p[0].toFixed(3)).join(',')}&longitude=${P.map((p) => p[1].toFixed(3)).join(',')}&hourly=cloud_cover_low,cloud_cover_mid&forecast_days=2&timezone=GMT`);
    const J = r.ok ? await r.json() : null; const A = Array.isArray(J) ? J : J ? [J] : [];
    if (A.length === 4) { block = 0; A.forEach((j, i) => { const h = j.hourly; let bi = 0, bd = 1e12; for (let q = 0; q < h.time.length; q++) { const dt = Math.abs(Date.parse(h.time[q] + ':00Z') - (T - (f.utc_offset_seconds || 0) * 1000)); if (dt < bd) { bd = dt; bi = q; } }
      const l = h.cloud_cover_low[bi] || 0, m = h.cloud_cover_mid[bi] || 0; lows.push(Math.round(l)); block = Math.max(block, WT[KM[i]] * l / 100, KM[i] >= 250 ? 0.6 * Math.max(0, m - 60) / 40 : 0); }); block = Math.min(1, block); } } catch (_) {}
  let aod = null;
  try { const r = await fetch(`https://air-quality-api.open-meteo.com/v1/air-quality?latitude=${lat}&longitude=${lon}&hourly=aerosol_optical_depth&forecast_days=2&timezone=auto`);
    if (r.ok) { const j = await r.json(), h = j.hourly; let s2 = 0, n2 = 0; for (let i = 0; i < h.time.length; i++) { if (Math.abs(Date.parse(h.time[i] + ':00Z') - T) <= 90 * 60e3 && h.aerosol_optical_depth[i] != null) { s2 += h.aerosol_optical_depth[i]; n2++; } } if (n2) aod = s2 / n2; } } catch (_) {}
  const blocked = cM >= 85 || (cM >= 70 && cH >= 60) || cL >= 80;
  let sc = 0; const mh = (cM + cH) / 2;
  sc += mh >= 90 ? 0 : mh >= 80 ? 4 : (mh >= 30 && mh <= 70) ? 25 : (mh >= 20 && mh <= 80) ? 19 : mh >= 10 ? 12 : 8;
  const effL = block != null ? Math.max(cL, Math.round(block * 100)) : cL;
  let ls = effL <= 10 ? 18 : effL <= 25 ? 14 : effL <= 40 ? 9 : effL <= 60 ? 4 : 1;
  if (preL != null && preL > 40 && effL < 30) ls = Math.min(18, ls + 4); sc += ls;
  sc += blocked ? 0 : aod != null ? (aod < 0.1 ? 15 : aod < 0.15 ? 13 : aod < 0.22 ? 10 : aod < 0.32 ? 6 : aod < 0.5 ? 3 : 1) : 8;
  sc += rh == null ? 0 : blocked ? 0 : rh <= 55 ? 12 : rh <= 65 ? 10 : rh <= 75 ? 7 : rh <= 85 ? 4 : 2;
  sc += pr == null ? 0 : pr <= 0 ? 10 : pr < 0.02 ? 7 : pr < 0.1 ? 3 : 0;
  const trend = pNow != null && p3 != null ? pNow - p3 : 0;
  sc += pNow == null ? 4 : trend > 0.5 ? (pNow >= 1016 ? 8 : 6) : Math.abs(trend) <= 0.5 ? (pNow >= 1020 ? 7 : 5) : 3;
  sc += (pre != null && pre > 0.01 && (pr || 0) <= 0 && trend > 0.5) ? 5 : 0;                    /* clearing after rain, pressure up */
  sc += blocked ? 0 : w300 == null ? 1 : w300 > 60 ? 4 : w300 > 40 ? 3 : 1;
  let fin = Math.round(sc);
  if (blocked) fin = Math.min(fin, 25);
  if (block != null) { const cv = Math.min(1, (cM + cH) / 60);
    if (block > 0.8) fin = Math.min(fin, 30); else if (block > 0.4) fin -= Math.round(18 * (block - 0.4) / 0.4 * (0.4 + 0.6 * cv)); else if (block < 0.2 && cv > 0.3 && cL < 40) fin = Math.min(100, fin + 6); }
  fin = Math.max(0, Math.min(100, fin));
  const label = fin >= 85 ? 'EPIC' : fin >= 70 ? 'EXCELLENT' : fin >= 55 ? 'GOOD' : fin >= 40 ? 'FAIR' : fin >= 25 ? 'POOR' : 'UNLIKELY';
  return { score: fin, label, cL, cM, cH, block, aod, rh };
}
async function sunsetAlert(f, now, lat, lon) {
  const D = f.daily; if (!D || !D.sunset) return null;
  const ss = D.sunset.find((x) => x && x.slice(0, 10) === now.date); if (!ss) return null;
  const mins = (Date.parse(ss + ':00Z') - Date.parse(now.iso + ':00Z')) / 60e3;
  if (mins < 55 || mins > 75) return null;
  const S = await sunsetScore(f, lat, lon, ss); if (S.score < 70) return null;
  if ((S.cM + S.cH) / 2 < 15) return null;   /* no clouds to light: clean dry air alone scores 70 (LA, 10-14) but a bare sky is not a show */
  const t = (iso, add) => { const d = new Date(Date.parse(iso + ':00Z') + add * 60e3); return hm(d.getUTCHours(), d.getUTCMinutes()); };
  const sky = `${Math.round((S.cM + S.cH) / 2)}% mid and high cloud to catch the color`;
  return { key: `sunset:${now.date}`, title: `GOLDEN HOUR \u00b7 ${S.label === 'EPIC' ? 'EPIC' : 'GREAT'}`, sep: ' | ', urg: 'normal',   /* user 2026-10-14 */
    body: `${S.label} (score ${S.score}). Sunset ${t(ss, 0)}, best color about ${t(ss, -5).replace(/ [AP]M$/, '')}–${t(ss, 15)}: ${sky}${S.block != null && S.block < 0.25 ? ', clear toward the sun' : ''}.` };
}

/* ---------------------------------------------------------------- the tick ----------------------------------------- */
async function tick(env) {
  const subs = await getSubs(env); if (!subs.length) return 'no phones';
  const groups = {};
  for (const s of subs) for (const l of s.locs) { const k = gkey(l); (groups[k] = groups[k] || { lat: l.lat, lon: l.lon, who: [] }).who.push({ s, name: l.name, types: l.types || s.types }); }
  const keys = Object.keys(groups).sort();
  let cur = 0; if (keys.length > BATCH) cur = (+(await env.WX.get('cursor')) || 0) % keys.length;
  const todo = keys.length > BATCH ? keys.slice(cur, cur + BATCH).concat(keys.slice(0, Math.max(0, cur + BATCH - keys.length))) : keys;
  const state = (await env.WX.get('state', { type: 'json' })) || {}, before = JSON.stringify(state), now = Date.now(), cache = {};
  let sent = 0, dead = new Set(), log = []; const PEND = {};
  const F = {};
  for (const k of todo) { try { F[k] = await forecast(groups[k].lat, groups[k].lon); } catch (e) { log.push(`${k} ${e.message}`); } }
  /* lightning: which places need listening (storm-capable forecast, or a storm already near), then one shared sample */
  const ltgWho = todo.filter((k) => F[k] && groups[k].who.some((w) => w.types.indexOf('lightning') >= 0)
    && (stormy(F[k], localNow(F[k])) || state[`${k}|ltg:on`]));
  /* space (2026-10-16): the ISS track and the coming eclipses are worked out once per tick, then read per place */
  const wantsT = (t) => todo.some((k) => groups[k].who.some((w) => w.types.indexOf(t) >= 0));
  let ISS = null, ECL = null;
  if (wantsT('iss')) { try { ISS = await issTrack(env, UA); } catch (e) { log.push('iss ' + e.message); } }
  if (wantsT('eclipse')) { try { ECL = eclipsesSoon(); } catch (e) { log.push('eclipse ' + e.message); } }
  let LTG = null;
  if (ltgWho.length) { LTG = await sampleStrikes(ltgWho.map((k) => groups[k]), ltgWho.some((k) => state[`${k}|ltg:on`]) ? 150000 : 90000); log.push(`ltg ${ltgWho.length} places, ${LTG.strikes.length} strikes${LTG.ok ? '' : ' (no socket)'}`); }
  for (const k of todo) {
    const g = groups[k], f = F[k]; if (!f) continue;
    const ln = localNow(f), found = [];
    if (LTG && LTG.ok && ltgWho.indexOf(k) >= 0) {
      const near = LTG.strikes.map((p) => ({ p, d: miles(g.lat, g.lon, p[0], p[1]) })).filter((x) => x.d <= LTG_MI).sort((a, b) => a.d - b.d);
      const on = state[`${k}|ltg:on`];
      if (near.length) {
        state[`${k}|ltg:last`] = now; state[`${k}|ltg:quiet`] = 0;
        if (!on) { state[`${k}|ltg:on`] = now;
          const n0 = near[0], len = stormLength(f, ln);
          found.push(['lightning', { key: `ltg:${now}`, title: 'Lightning nearby', urg: 'high',
            body: `Strikes within ${LTG_MI} miles: the nearest ${Math.max(1, Math.round(n0.d))} mile${Math.max(1, Math.round(n0.d)) > 1 ? 's' : ''} ${compass(g.lat, g.lon, n0.p[0], n0.p[1])}, ${near.length} in the last ${LTG.secs >= 150 ? 'two and a half minutes' : 'minute and a half'}. ${len}`}]); }
      } else if (on) {
        /* the all-clear: 30 minutes since the last strike we saw AND three quiet samples in a row (we listen in samples, not continuously) */
        state[`${k}|ltg:quiet`] = (state[`${k}|ltg:quiet`] || 0) + 1;
        if (now - (state[`${k}|ltg:last`] || on) >= 30 * 60e3 && state[`${k}|ltg:quiet`] >= 3) {
          delete state[`${k}|ltg:on`]; delete state[`${k}|ltg:quiet`]; }   /* the episode closes quietly: no all-clear alert (user 2026-10-14) */
      }
    }
    const wantsAny = (t) => g.who.some((w) => w.types.indexOf(t) >= 0);
    if (wantsAny('umbrella')) { const a = umbrella(f, ln); if (a) found.push(['umbrella', a]); }
    if (wantsAny('rain')) { const a = rainSoon(f, ln); if (a) found.push(['rain', a]); }
    if (wantsAny('swing')) { const a = swings(f, ln); if (a) found.push(['swing', a]); }
    if (wantsAny('aurora') && ln.h === 19) { const a = aurora(f, ln, await kpTonightFor(cache, f.utc_offset_seconds || 0, ln.date), g.lat); if (a) found.push(['aurora', a]); }
    if (wantsAny('severe')) { try { for (const a of await severe(g.lat, g.lon)) found.push(['severe', a]); } catch (_) {} }
    if (wantsAny('fire')) { try { for (const a of await firesNear(g.lat, g.lon)) found.push(['fire', a]); } catch (_) {} }
    if (wantsAny('air')) { try { const a = await airNow(g.lat, g.lon, ln); if (a) found.push(['air', a]); } catch (_) {} }
    if (wantsAny('sunset')) { try { const a = await sunsetAlert(f, ln, g.lat, g.lon); if (a) found.push(['sunset', a]); } catch (_) {} }
    if (wantsAny('iss') && ISS) { try { const a = issAlert(ISS, g, f); if (a) found.push(['iss', a]); } catch (_) {} }
    if (wantsAny('eclipse') && ECL && ECL.length) { try { for (const a of eclipseAlerts(ECL, g, f, ln)) found.push(['eclipse', a]); } catch (_) {} }
    if (wantsAny('meteor')) { try { const a = meteorAlert(g, f, ln); if (a) found.push(['meteor', a]); } catch (_) {} }
    for (const [type, a] of found) {
      const sk = `${k}|${a.key}`, last = state[sk] || 0;
      if (a.cool ? now - last < a.cool : last) continue;                               /* dated keys: once ever; others: cool-down */
      state[sk] = now;
      /* the event's own identity, without the box: lightning episodes and the rain-soon nudge are per place, so they match by type */
      const ekey = /^(ltg|ltgclear):/.test(a.key) ? a.key.split(':')[0] : a.key;
      for (const w of g.who) {
        if (w.types.indexOf(type) < 0) continue;
        (PEND[w.s.endpoint] = PEND[w.s.endpoint] || []).push({ s: w.s, type, ekey, a, name: w.name, lat: g.lat, lon: g.lon });
      }
    }
  }
  sent += await sendMerged(env, PEND, dead, log, state);
  for (const sk of Object.keys(state)) if (state[sk] > 1e12 && now - state[sk] > 4 * 864e5) delete state[sk];   /* timestamps only: counters (ltg:quiet) are not times */
  if (JSON.stringify(state) !== before) await env.WX.put('state', JSON.stringify(state));
  if (dead.size) await env.WX.put('subs', JSON.stringify(subs.filter((s) => !dead.has(s.endpoint))));
  if (keys.length > BATCH) await env.WX.put('cursor', String((cur + BATCH) % keys.length));
  return `${todo.length}/${keys.length} places, ${sent} sent${log.length ? ' | ' + log.slice(0, 4).join(' | ') : ''}`;
}

export default {
  fetch: route,
  async scheduled(event, env, ctx) {
    /* one trigger, two lanes: the fast lane every minute, the 10-minute lane on minutes ending in 0 -- read off
       event.scheduledTime, not the wall clock (a late tick must not skip its slot) */
    /* heartbeat: when the trigger last ran and how it was labelled (a deployed schedule that never fired went unnoticed for an hour on 10-13) */
    ctx.waitUntil(env.WX.put('beat', JSON.stringify({ at: new Date().toISOString(), cron: event.cron, sched: new Date(event.scheduledTime || 0).toISOString() })).catch(() => {}));
    /* FAST_ONLY: the bluish-hazard-fast worker (same code, every-minute trigger) runs just the fast lane and stamps
       beat:fast; this worker then leaves the fast lane to it, so no warning goes out twice */
    if (env.FAST_ONLY) {
      ctx.waitUntil(env.WX.put('beat:fast', String(Date.now())).catch(() => {}));
      ctx.waitUntil(fastTick(env).then((r) => console.log(`[fast] ${r}`)).catch((e) => console.log(`[fast] FAILED ${e}`)));
      return;
    }
    const fb = +(await env.WX.get('beat:fast').catch(() => 0)) || 0;
    if (Date.now() - fb > 3 * 60e3) ctx.waitUntil(fastTick(env).then((r) => console.log(`[wx] ${r}`)).catch((e) => console.log(`[wx] fast FAILED ${e}`)));
    if (new Date(event.scheduledTime || Date.now()).getUTCMinutes() % 10 === 0)
      ctx.waitUntil(tick(env).then((r) => console.log(`[wx] ${r}`)).catch((e) => console.log(`[wx] FAILED ${e}`)));
  },
  // exported for tests
  _t: { vtecKey, umbrella, rainSoon, swings, aurora, minKp, localNow, severe, warnFacts, stormLength, inGeom, warnMsg, quakeAt, firesNear, airNow, fastTick, sendMerged, sunsetScore, sunsetAlert, sunsetAz }
};
