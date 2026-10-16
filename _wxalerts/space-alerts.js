// SPACE ALERTS (2026-10-16, user: "alerts for the ISS station being overhead for the users location / alerts for
// upcoming eclipses / alerts for meteor showers"). Three alert types for the same places the weather alerts watch:
//   ISS         10-20 minutes before a pass you can actually see: dark enough at the place (sun 4 deg+ down), the station
//               sunlit, climbing 25 deg+ above the horizon, and the sky not overcast (70% cloud or less)
//   ECLIPSE     solar and lunar eclipses VISIBLE from the place (sun or moon above the horizon during it; penumbral
//               lunar eclipses skipped -- the shading is too faint to notice): a week ahead and the morning of at 8 AM,
//               and 30 minutes before it starts (not between 11 PM and 6 AM)
//   METEOR      7 PM on a major shower's peak night, when the radiant gets 10 deg+ up in the dark hours and the best
//               hours look mostly clear
// The astronomy is two libraries, not hand-rolled: astronomy-engine (eclipses with local circumstances, sun/moon
// positions, a radiant's altitude) and satellite.js (SGP4, the standard model for a TLE -- the ISS elements from
// ARISS / AMSAT / CelesTrak, refreshed twice a day). The page's tap target is the space-events widget (#go=space).
import * as A from 'astronomy-engine';
import * as S from 'satellite.js';

const R2D = 180 / Math.PI, D2R = Math.PI / 180;
const dir8 = (az) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round((((az % 360) + 360) % 360) / 45) % 8];
const hmTxt = (h, m) => { const ap = h < 12 ? 'AM' : 'PM', h12 = h % 12 || 12; return `${h12}:${String(m).padStart(2, '0')} ${ap}`; };
/* a UTC instant as the place's local clock, with the weekday when it is not today */
const at = (ms, f, nowMs) => {
  const off = (f.utc_offset_seconds || 0) * 1000, d = new Date(ms + off), n = new Date((nowMs || Date.now()) + off);
  const day = d.toISOString().slice(0, 10) === n.toISOString().slice(0, 10) ? ''
    : (d.getUTCDate() === new Date(n.getTime() + 864e5).getUTCDate() ? 'tomorrow ' : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getUTCDay()] + ' ');
  return day + hmTxt(d.getUTCHours(), d.getUTCMinutes());
};
const clock = (ms, f) => { const d = new Date(ms + (f.utc_offset_seconds || 0) * 1000); return hmTxt(d.getUTCHours(), d.getUTCMinutes()); };
const localHour = (ms, f) => new Date(ms + (f.utc_offset_seconds || 0) * 1000).getUTCHours();
/* the forecast's cloud cover for the hour holding a UTC instant (the forecast reaches ~2 days; null past it) */
const cloudAt = (f, ms) => {
  const H = f.hourly; if (!H || !H.cloud_cover) return null;
  const key = new Date(ms + (f.utc_offset_seconds || 0) * 1000).toISOString().slice(0, 13);
  const i = H.time.findIndex((t) => t.slice(0, 13) === key); return i >= 0 ? H.cloud_cover[i] : null;
};
const sunAlt = (obs, ms) => { const eq = A.Equator(A.Body.Sun, new Date(ms), obs, true, true); return A.Horizon(new Date(ms), obs, eq.ra, eq.dec, 'normal').altitude; };

/* ------------------------------------------------------------------------------------------------ the ISS -------- */
/* once per tick: the station 8 to 34 minutes ahead every 30 s, Earth-fixed, and whether it is in sunlight */
export async function issTrack(env, UA) {
  /* THREE SOURCES, AND A BACK-OFF (2026-10-16). CelesTrak blocks an address for 2 hours on "excessive downloads" -- it blocked
     our tests within an hour, and a worker shares Cloudflare's addresses with everyone else who fetches it. So the ARISS and
     AMSAT copies first (the same NORAD elements, ARISS refreshed with each new set), CelesTrak last; a failed round waits an
     hour (KV key with a TTL) instead of retrying every ten minutes, which is what gets a source to block us. */
  let tle = await env.WX.get('tle:iss', { type: 'json' });
  if ((!tle || Date.now() - tle.at > 12 * 3600e3) && !(await env.WX.get('tle:iss:wait'))) {
    let got = null;
    for (const u of ['https://live.ariss.org/iss.txt', 'https://www.amsat.org/tle/current/nasabare.txt', 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE']) {
      try {
        const r = await fetch(u, { headers: { 'User-Agent': UA } }); if (!r.ok) continue;
        const L = (await r.text()).split(/\r?\n/).map((x) => x.trim()), i = L.findIndex((x) => /^1 25544/.test(x));
        if (i >= 0 && /^2 25544/.test(L[i + 1] || '')) { got = { l1: L[i], l2: L[i + 1], at: Date.now(), src: u.split('/')[2] }; break; }
      } catch (_) { /* next source */ }
    }
    if (got) { tle = got; await env.WX.put('tle:iss', JSON.stringify(tle)); }
    else await env.WX.put('tle:iss:wait', '1', { expirationTtl: 3600 });   /* keep the elements we have; a few days old is still close */
  }
  if (!tle) return null;
  const rec = S.twoline2satrec(tle.l1, tle.l2), t0 = Date.now() + 8 * 60e3, pts = [];
  for (let i = 0; i <= 52; i++) {
    const d = new Date(t0 + i * 30e3), pv = S.propagate(rec, d);
    if (!pv || !pv.position) continue;
    const ecf = S.eciToEcf(pv.position, S.gstime(d));
    /* sunlit unless behind the Earth's cylinder of shadow (plenty for a yes/no on a 400 km orbit) */
    const sv = A.GeoVector(A.Body.Sun, d, true), n = Math.hypot(sv.x, sv.y, sv.z), u = [sv.x / n, sv.y / n, sv.z / n];
    const r = [pv.position.x, pv.position.y, pv.position.z], dot = r[0] * u[0] + r[1] * u[1] + r[2] * u[2];
    const perp = Math.hypot(r[0] - dot * u[0], r[1] - dot * u[1], r[2] - dot * u[2]);
    pts.push({ t: d.getTime(), ecf, lit: dot > 0 || perp > 6371 });
  }
  return pts;
}

/* a visible pass starting 10-20 minutes from now (the tick runs every 10, so each pass is caught once) */
export function issAlert(P, g, f) {
  if (!P || !P.length) return null;
  const now = Date.now(), obsS = { longitude: g.lon * D2R, latitude: g.lat * D2R, height: 0.05 };
  const obsA = new A.Observer(g.lat, g.lon, 50);
  let vis = [];
  for (const p of P) {
    const la = S.ecfToLookAngles(obsS, p.ecf), el = la.elevation * R2D, az = la.azimuth * R2D;
    const ok = el >= 10 && p.lit;
    if (ok) vis.push({ t: p.t, el, az });
    else if (vis.length) break;                        /* the first visible stretch only */
  }
  if (vis.length < 2) return null;
  const start = vis[0].t, end = vis[vis.length - 1].t;
  if (start < now + 10 * 60e3 || start >= now + 20 * 60e3) return null;
  if (sunAlt(obsA, start) > -4) return null;           /* not dark enough to see it (at -4 to -6 the ISS still shows: Heavens-Above lists those passes, 10-17 6:40 AM) */
  const top = vis.reduce((a, b) => (b.el > a.el ? b : a));
  if (top.el < 25) return null;
  const cc = cloudAt(f, start); if (cc != null && cc > 70) return null;
  const mins = Math.max(1, Math.round((end - start) / 60e3 + 0.5));
  const fades = P.some((p) => p.t > end && p.t <= end + 60e3 && !p.lit);
  return { key: `iss:${Math.round(start / 60e3)}`, title: `ISS overhead · ${at(start, f)}`, urg: 'normal',
    /* "appears" when it comes out of Earth's shadow already high: "rises" would send you to the horizon (10-17 5:06 AM, at 36 deg) */
    body: `Visible ${at(start, f)} for ${mins} min: ${vis[0].el > 15 ? `appears ${Math.round(vis[0].el)}° up` : 'rises'} in the ${dir8(vis[0].az)}, `
      + (top.t === vis[0].t ? 'then sinks' : `${Math.round(top.el)}° up in the ${dir8(top.az)}, ${fades ? 'fades out' : 'sets'}`)   /* highest as it appears: say it once */
      + ` ${top.t === vis[0].t ? 'toward' : 'in'} the ${dir8(vis[vis.length - 1].az)}.${cc != null ? ` Clouds ${cc}%.` : ''}` };
}

/* --------------------------------------------------------------------------------------------- eclipses -------- */
/* once per tick: every solar and (umbral) lunar eclipse whose peak is within the next 8.5 days */
export function eclipsesSoon() {
  const now = Date.now(), lim = now + 8.5 * 864e5, out = [];
  let s = A.SearchGlobalSolarEclipse(new Date(now - 864e5));
  for (let i = 0; i < 3 && s.peak.date.getTime() < lim; i++, s = A.NextGlobalSolarEclipse(s.peak)) out.push({ body: 'sun', peak: s.peak.date.getTime() });
  let l = A.SearchLunarEclipse(new Date(now - 864e5));
  for (let i = 0; i < 3 && l.peak.date.getTime() < lim; i++, l = A.NextLunarEclipse(l.peak))
    if (l.kind !== 'penumbral') out.push({ body: 'moon', peak: l.peak.date.getTime(), kind: l.kind, sdP: l.sd_partial, sdT: l.sd_total });
  return out;
}

/* what this place sees of one eclipse: null if nothing, else its visible start/end and the words for the alert */
function localEclipse(E, g, f) {
  const obs = new A.Observer(g.lat, g.lon, 50);
  if (E.body === 'sun') {
    const L = A.SearchLocalSolarEclipse(new Date(E.peak - 864e5), obs);
    if (Math.abs(L.peak.time.date.getTime() - E.peak) > 864e5) return null;   /* that one never reaches this place */
    const ev = [L.partial_begin, L.peak, L.partial_end];
    if (!ev.some((e) => e.altitude > 0)) return null;
    let a = L.partial_begin.time.date.getTime(), b = L.partial_end.time.date.getTime();
    const aUp = L.partial_begin.altitude > 0, bUp = L.partial_end.altitude > 0;
    if (!aUp) { const r = A.SearchRiseSet(A.Body.Sun, obs, +1, L.partial_begin.time, 1); if (r) a = r.date.getTime(); }
    if (!bUp) { const r = A.SearchRiseSet(A.Body.Sun, obs, -1, L.peak.time, 1); if (r) b = r.date.getTime(); }
    const pk = L.peak.time.date.getTime(), kind = L.kind === 'total' ? 'TOTAL' : L.kind === 'annular' ? 'ANNULAR' : 'PARTIAL';
    const pct = kind === 'PARTIAL' ? Math.min(99, Math.floor(100 * L.obscuration)) : Math.round(100 * L.obscuration);   /* at the edge of the path a partial reads 99.6%: never call a partial 100% */
    const words = `${kind === 'PARTIAL' ? `The moon covers ${pct}% of the sun` : kind === 'TOTAL' ? 'Totality here' : 'A ring of fire here'}`
      + (L.peak.altitude > 0 ? ` at ${at(pk, f)}, the sun ${Math.round(L.peak.altitude)}° up` : ', with the most of it below the horizon')
      + `. ${aUp ? 'Starts' : 'Already under way at sunrise,'} ${at(a, f)}, ${bUp ? 'ends' : 'the sun sets still eclipsed at'} ${at(b, f)}.`
      + ' Never look at the sun without eclipse glasses.';
    return { id: new Date(E.peak).toISOString().slice(0, 16), start: a, end: b, title: `${kind === 'PARTIAL' ? 'Partial' : kind === 'TOTAL' ? 'Total' : 'Annular'} solar eclipse`, words,
      short: `${kind === 'PARTIAL' ? pct + '% covered' : kind === 'TOTAL' ? 'totality' : 'ring of fire'}${L.peak.altitude > 0 ? ' at ' + at(pk, f) : ''}, ${at(a, f)}–${at(b, f)}`,
      safe: 'Never look at the sun without eclipse glasses.' };
  }
  /* lunar: visible wherever the moon is up during the umbral phases */
  const pb = E.peak - E.sdP * 60e3, pe = E.peak + E.sdP * 60e3, tb = E.peak - (E.sdT || 0) * 60e3, te = E.peak + (E.sdT || 0) * 60e3;
  const up = (ms) => { const eq = A.Equator(A.Body.Moon, new Date(ms), obs, true, true); return A.Horizon(new Date(ms), obs, eq.ra, eq.dec, 'normal').altitude > 0; };
  let first = null, last = null;
  for (let t = pb; t <= pe; t += 5 * 60e3) if (up(t)) { if (first == null) first = t; last = t; }
  if (first == null) return null;
  /* totality is seen if the moon is up at ANY point of it, not just at the peak (NYC 3 Mar 2026: totality 6:04 AM, peak
     after moonset -- checking the peak alone said "totality happens with the moon down") */
  let totFirst = null, totLast = null;
  if (E.kind === 'total') for (let t = tb; t <= te; t += 2 * 60e3) if (up(t)) { if (totFirst == null) totFirst = t; totLast = t; }
  const totVis = totFirst != null;
  const words = (first > pb + 6e5 ? `The moon rises already in Earth's shadow at ${at(first, f)}` : `The moon enters Earth's shadow at ${at(pb, f)}`)
    + (E.kind === 'total' ? (totVis ? (totLast < te - 3e5 ? `, fully red from ${at(tb, f)} until it sets at ${at(totLast, f)}` : `, fully red ${at(Math.max(tb, totFirst), f)}–${at(te, f)}`) : ', but totality happens with the moon down') : `, most covered at ${at(E.peak, f)}`)
    + (last < pe - 6e5 ? (totVis && totLast < te - 3e5 ? '.' : `, and sets still eclipsed at ${at(last, f)}.`) : `, and leaves the shadow at ${at(pe, f)}.`)
    + ' Safe to watch with the naked eye.';
  return { id: new Date(E.peak).toISOString().slice(0, 16), start: first, end: last, title: `${E.kind === 'total' ? 'Total' : 'Partial'} lunar eclipse`, words,
    short: `${at(first, f)}–${at(last, f)}${E.kind === 'total' ? (totVis ? ', fully red from ' + at(Math.max(tb, totFirst), f) : ', not the totality') : ''}`,
    safe: 'Safe to watch with the naked eye.' };
}

/* the week-ahead and morning-of notices (8 AM local) and the 30-minute warning, for every eclipse this place sees */
export function eclipseAlerts(EC, g, f, ln) {
  const out = [], now = Date.now();
  for (const E of EC || []) {
    let L; try { L = localEclipse(E, g, f); } catch (_) { L = null; }
    if (!L || L.end < now) continue;
    const toStart = L.start - now, cc = cloudAt(f, L.start), cloud = cc != null ? ` Clouds forecast ${cc}%.` : '';
    const parts = { base: L.title, words: L.words, short: L.short, safe: L.safe, cc };   /* for one notification across places (sendMerged) */
    if (ln.h === 8 && toStart > 6.5 * 864e5 && toStart <= 7.5 * 864e5)
      out.push({ key: `ecl:${L.id}:week`, title: `${L.title} in a week`, urg: 'normal', body: L.words, parts: { ...parts, cc: null } });
    if (ln.h === 8 && toStart > 0 && toStart <= 864e5)
      out.push({ key: `ecl:${L.id}:day`, title: `${L.title} ${E.body === 'moon' && (localHour(L.start, f) >= 18 || localHour(L.start, f) < 6) ? 'tonight' : 'today'}`, urg: 'normal', body: L.words + cloud, parts });
    const h0 = localHour(L.start, f);
    if (toStart >= 20 * 60e3 && toStart < 40 * 60e3 && h0 >= 6 && h0 < 23)
      out.push({ key: `ecl:${L.id}:soon`, title: `${L.title} starts ${at(L.start, f)}`, urg: 'high', body: L.words + cloud, parts });
  }
  return out;
}

/* ----------------------------------------------------------------------------------------- meteor showers ------- */
/* the majors from the site's own table (ZHR 15+), peak night = the evening before the peak morning */
const SHOWERS = [
  { name: 'Quadrantids', m: 1, d: 3, zhr: 120, ra: 230, dec: 49 },
  { name: 'Lyrids', m: 4, d: 21, zhr: 18, ra: 271, dec: 34 },
  { name: 'Eta Aquariids', m: 5, d: 5, zhr: 50, ra: 338, dec: -1 },
  { name: 'Delta Aquariids', m: 7, d: 29, zhr: 25, ra: 340, dec: -16 },
  { name: 'Perseids', m: 8, d: 12, zhr: 100, ra: 48, dec: 58 },
  { name: 'Orionids', m: 10, d: 20, zhr: 20, ra: 95, dec: 16 },
  { name: 'Leonids', m: 11, d: 17, zhr: 15, ra: 152, dec: 22 },
  { name: 'Geminids', m: 12, d: 13, zhr: 150, ra: 112, dec: 33 }];

export function meteorAlert(g, f, ln) {
  if (ln.h !== 19) return null;
  const [y, mo, dd] = ln.date.split('-').map(Number), sh = SHOWERS.find((s) => s.m === mo && s.d === dd);
  if (!sh) return null;
  const obs = new A.Observer(g.lat, g.lon, 50), off = (f.utc_offset_seconds || 0) * 1000;
  const eve = Date.UTC(y, mo - 1, dd, 20) - off;                       /* 8 PM local tonight */
  let best = null;
  for (let i = 0; i <= 10; i++) {                                     /* 8 PM .. 6 AM */
    const t = eve + i * 3600e3; if (sunAlt(obs, t) > -12) continue;
    const alt = A.Horizon(new Date(t), obs, sh.ra / 15, sh.dec, 'normal');
    if (!best || alt.altitude > best.alt) best = { t, alt: alt.altitude, az: alt.azimuth };
  }
  if (!best || best.alt < 10) return null;
  const cl = [-3600e3, 0, 3600e3].map((d) => cloudAt(f, best.t + d)).filter((x) => x != null);
  const cc = cl.length ? Math.round(cl.reduce((a, b) => a + b, 0) / cl.length) : null;
  if (cc != null && cc > 70) return null;
  const moonEq = A.Equator(A.Body.Moon, new Date(best.t), obs, true, true);
  const moonUp = A.Horizon(new Date(best.t), obs, moonEq.ra, moonEq.dec, 'normal').altitude > 0;
  const lit = Math.round(100 * A.Illumination(A.Body.Moon, new Date(best.t)).phase_fraction);
  const rate = Math.max(1, Math.round(sh.zhr * Math.sin(best.alt * D2R)));
  return { key: `meteor:${sh.name}:${y}`, title: `${sh.name} peak tonight`, urg: 'normal',
    /* the pieces, for one notification across several places (sendMerged) */
    parts: { rate, best: clock(best.t, f), alt: Math.round(best.alt), dir: dir8(best.az), cc, moon: `Moon ${lit}% lit${moonUp ? ' and up then' : ', down then'}.` },
    body: `Up to about ${rate} an hour under dark skies, best around ${clock(best.t, f)} with the radiant ${Math.round(best.alt)}° up in the ${dir8(best.az)}. `
      + `Moon ${lit}% lit${moonUp ? ' and up then' : ', down then'}.${cc != null ? ` Clouds ${cc}%.` : ''}` };
}
