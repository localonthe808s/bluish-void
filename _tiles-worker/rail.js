// /rail/v1/nyc.json -- the LIRR's and Metro-North's trains, placed on their track, with where each is headed and when it gets
// there (user 2026-10-20: "yes build and deploy it"). Both railroads' GTFS-realtime feeds are read here once per ~10 s per edge,
// not by every viewer every 30 s (~27 KB of protobuf each); each train is snapped onto its branch (city_commuter_rail.json, the
// same file and line order the page draws), and its next station and predicted arrival come from the same feed's trip update,
// so its speed and direction are known from ONE read: v = (next station's distance along the track - its own) / (time to it).
// The page glides each train at that speed, holds it at the station until its departure, and eases into each new read.
const FEEDS = [['LIRR', 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/lirr%2Fgtfs-lirr'],
               ['MNR', 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/mnr%2Fgtfs-mnr']];
const TRACK_URL = 'https://bluishvoid.com/city_commuter_rail.json?v=2';
const GK = Math.cos(40.75 * Math.PI / 180) * 111320, GY = 111320;

// ---- a minimal protobuf reader (GTFS-realtime is all the page has ever needed: varints, lengths, fixed32 floats)
function varint(b, i){ let v = 0, s = 1; for (;;){ const x = b[i++]; v += (x & 127) * s; if (!(x & 128)) return [v, i]; s *= 128; } }
function walk(b, dv, s, e, cb){ let i = s; while (i < e){ let t; [t, i] = varint(b, i); const f = Math.floor(t / 8), w = t & 7;
  if (w === 0){ let v; [v, i] = varint(b, i); cb(f, w, v, 0, 0); }
  else if (w === 2){ let n; [n, i] = varint(b, i); cb(f, w, 0, i, i + n); i += n; }
  else if (w === 5){ cb(f, w, dv.getFloat32(i, true), 0, 0); i += 4; }
  else if (w === 1) i += 8; else return; } }
const str = (b, s, e) => new TextDecoder().decode(b.subarray(s, e));
function decode(buf, keepAll){
  const b = new Uint8Array(buf), dv = new DataView(buf), veh = [], tu = {};
  walk(b, dv, 0, b.length, (f, w, v, s, e) => { if (f !== 2 || w !== 2) return;
    walk(b, dv, s, e, (f2, w2, v2, s2, e2) => {
      if (f2 === 4 && w2 === 2){ const o = { trip: '', route: '', id: '', la: null, lo: null, br: null, t: 0, st: null, stop: '' };
        walk(b, dv, s2, e2, (f3, w3, v3, s3, e3) => {
          if (f3 === 1 && w3 === 2) walk(b, dv, s3, e3, (f4, w4, v4, s4, e4) => { if (f4 === 1 && w4 === 2) o.trip = str(b, s4, e4); else if (f4 === 5 && w4 === 2) o.route = str(b, s4, e4); });
          else if (f3 === 2 && w3 === 2) walk(b, dv, s3, e3, (f4, w4, v4) => { if (w4 === 5){ if (f4 === 1) o.la = v4; else if (f4 === 2) o.lo = v4; else if (f4 === 3) o.br = v4; } });
          else if (f3 === 4 && w3 === 0) o.st = v3;
          else if (f3 === 5 && w3 === 0) o.t = v3;
          else if (f3 === 7 && w3 === 2) o.stop = str(b, s3, e3);
          else if (f3 === 8 && w3 === 2) walk(b, dv, s3, e3, (f4, w4, v4, s4, e4) => { if (f4 === 1 && w4 === 2) o.id = str(b, s4, e4); });
        });
        if (keepAll || (isFinite(o.la) && isFinite(o.lo) && Math.abs(o.la) > 1)) veh.push(o); }
      else if (f2 === 3 && w2 === 2){ let trip = '', route = ''; const sts = [];
        walk(b, dv, s2, e2, (f3, w3, v3, s3, e3) => {
          if (f3 === 1 && w3 === 2) walk(b, dv, s3, e3, (f4, w4, v4, s4, e4) => { if (f4 === 1 && w4 === 2) trip = str(b, s4, e4); else if (f4 === 5 && w4 === 2) route = str(b, s4, e4); });
          else if (f3 === 2 && w3 === 2){ const u = { stop: '', a: 0, d: 0 };
            walk(b, dv, s3, e3, (f4, w4, v4, s4, e4) => {
              if (f4 === 4 && w4 === 2) u.stop = str(b, s4, e4);
              else if ((f4 === 2 || f4 === 3) && w4 === 2) walk(b, dv, s4, e4, (f5, w5, v5) => { if (f5 === 2 && w5 === 0){ if (f4 === 2) u.a = v5; else u.d = v5; } });
            });
            if (u.stop) sts.push(u); } });
        if (trip) tu[trip] = { route, sts }; }
    }); });
  return { veh, tu };
}

// ---- the track, per isolate: each line in metres, its length along, and where each of its railroad's stations falls on it
let TRACK = null, TRACK_AT = 0;
async function track(){
  if (TRACK && Date.now() - TRACK_AT < 6 * 3600e3) return TRACK;
  const j = await (await fetch(TRACK_URL, { cf: { cacheTtl: 3600 } })).json();
  const lines = (j.lines || []).map((ln) => { const P = ln.p.map((c) => [c[0] * GK, c[1] * GY]), S = [0];
    let x0 = 1e12, y0 = 1e12, x1 = -1e12, y1 = -1e12;
    P.forEach((p, i) => { if (i) S.push(S[i - 1] + Math.hypot(p[0] - P[i - 1][0], p[1] - P[i - 1][1])); x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); });
    return { rr: ln.rr, P, S, bb: [x0 - 300, y0 - 300, x1 + 300, y1 + 300], st: {} }; });
  lines.forEach((T) => (j.stations || []).forEach((o) => { if (o.rr !== T.rr) return; const pr = onLine(T, o.lo * GK, o.la * GY); if (pr && pr.d < 80) T.st[o.id] = pr.s; }));
  TRACK = lines; TRACK_AT = Date.now(); return TRACK;
}
function onLine(T, x, y){ if (x < T.bb[0] || x > T.bb[2] || y < T.bb[1] || y > T.bb[3]) return null; let best = null;
  for (let i = 1; i < T.P.length; i++){ const a = T.P[i - 1], b = T.P[i], dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy || 1e-9;
    const t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / L2)), d = Math.hypot(a[0] + t * dx - x, a[1] + t * dy - y);
    if (!best || d < best.d) best = { d, s: T.S[i - 1] + t * Math.sqrt(L2) }; }
  return best; }

async function build(){
  const T = await track(), now = Date.now(), out = [];
  const reads = await Promise.all(FEEDS.map(([rr, u]) => fetch(u, { cf: { cacheTtl: 8 } }).then((r) => r.ok ? r.arrayBuffer() : null).then((ab) => ab ? [rr, decode(ab)] : [rr, null]).catch(() => [rr, null])));
  for (const [rr, D] of reads){ if (!D) continue;
    for (const o of D.veh){
      const t = o.t ? o.t * 1000 : now, U = D.tu[o.trip], x = o.lo * GK, y = o.la * GY;
      // the next station still ahead: the first update whose departure (or arrival) is still to come
      const nxU = U ? U.sts.find((u) => (u.d || u.a) * 1000 > t - 15000) : null;
      // the branch: the nearest line of this railroad, a line that carries the next station preferred within 60 m
      let best = null;
      T.forEach((L, li) => { if (L.rr !== rr) return; const pr = onLine(L, x, y); if (!pr) return;
        const sc = pr.d - (nxU && L.st[nxU.stop] != null ? 60 : 0); if (!best || sc < best.sc) best = { li, s: pr.s, d: pr.d, sc }; });
      const rec = { id: rr + ':' + (o.id || o.trip), rr, r: o.route || (U && U.route) || '', t, la: +o.la.toFixed(5), lo: +o.lo.toFixed(5) };
      if (best && best.d <= 150){
        rec.li = best.li; rec.s = Math.round(best.s);
        const L = T[best.li], ns = nxU ? L.st[nxU.stop] : null;
        if (ns != null){ rec.nx = Math.round(ns); rec.na = (nxU.a || nxU.d) * 1000; rec.nd = (nxU.d || nxU.a) * 1000;
          const dtA = (rec.na - t) / 1000, ds = ns - best.s;
          if (o.st === 1 || Math.abs(ds) < 40){ rec.v = 0; rec.dir = 0; }                       // at the platform: hold until it departs
          else { rec.dir = ds > 0 ? 1 : -1; rec.v = dtA > 5 ? Math.round(Math.max(-40, Math.min(40, ds / dtA)) * 100) / 100 : 0; } }
        else { rec.v = 0; rec.dir = 0; }
      }
      out.push(rec); } }
  return { at: now, n: T.length, trains: out };
}

export async function railRoute(url, ctx, cors){
  const cache = caches.default, key = new Request('https://tiles.bluishvoid.com/rail/v1/nyc.json', { method: 'GET' });
  let hit = await cache.match(key);
  if (!hit){
    let body; try { body = JSON.stringify(await build()); } catch (e){ return new Response(JSON.stringify({ error: String(e) }), { status: 502, headers: { 'Content-Type': 'application/json', ...cors } }); }
    hit = new Response(body, { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=10' } });
    ctx.waitUntil(cache.put(key, hit.clone()));
  }
  const h = new Headers(hit.headers); Object.entries(cors).forEach(([k, v]) => h.set(k, v)); h.set('Cache-Control', 'public, max-age=8');
  return new Response(hit.body, { status: 200, headers: h });
}


// /subway/v1/nyc.json -- the subway's trains between stations (user 2026-10-20: "yes build it from zoom 14, have them be aware of
// active delays and alerts"). The subway's feeds give no coordinates: each train's next station (its vehicle entity's stop_id)
// and when it gets there (its trip update). city_subway_pairs.json (_mtabake/pairs.py) says, for that route and platform, the
// station it comes from, the scheduled run, and both stations' places along the route's track; the page places it at
// sN - (sN - sP) * (time to N) / run, so it glides and arrives on the feed's own prediction. Flags: held -- stopped at a platform
// for 2.5+ min; late -- past its predicted arrival by 90+ s with the feed still saying it is coming.
// Each train: [route, shapeRoute, line, sP, sN, run s, arrival (unix s), status 1 = at the platform, held, late, next stop, last stop]
const SUB_FEEDS = ['', '-ace', '-bdfm', '-g', '-jz', '-nqrw', '-l'].map((s) => 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs' + s);
const PAIRS_URL = 'https://bluishvoid.com/city_subway_pairs.json?v=1';
let PAIRS = null, PAIRS_AT = 0;
async function pairs(){
  if (PAIRS && Date.now() - PAIRS_AT < 6 * 3600e3) return PAIRS;
  PAIRS = await (await fetch(PAIRS_URL, { cf: { cacheTtl: 3600 } })).json(); PAIRS_AT = Date.now(); return PAIRS; }
// the seven subway feeds, decoded, shared by the trains (buildSub) and the measured delays (buildDelays) within ~10 s
let SUBR = null, SUBR_AT = 0;
async function subReads(){
  if (SUBR && Date.now() - SUBR_AT < 10000) return SUBR;
  const p = Promise.all(SUB_FEEDS.map((u) => fetch(u, { cf: { cacheTtl: 10 } }).then((r) => r.ok ? r.arrayBuffer() : null).then((ab) => ab ? decode(ab, true) : null).catch(() => null)));
  SUBR = p; SUBR_AT = Date.now(); return p;
}
async function buildSub(){
  const PR = await pairs(), now = Date.now(), out = [];
  const reads = await subReads();
  let feeds = 0;
  for (const D of reads){ if (!D) continue; feeds++;
    for (const o of D.veh){
      if (!o.route || o.route === 'SI' || o.route === 'SS') continue;            // Staten Island stays off, as on the map
      const U = D.tu[o.trip], sts = U ? U.sts : [], nowS = now / 1000;
      // PLACED BY THE PREDICTED TIMES, NOT THE STATUS (2026-10-20). The vehicle's STOPPED_AT outlives the stop: of 397 trains
      // flagged so at 6:55 PM, 250 were past their predicted departure (median 12 s) and 104 no longer listed the stop at all --
      // only 43 were standing at a platform, and the map pinned all 397 there ("they look stuck"). The train is between the last
      // listed stop whose time has passed and the first whose time is still ahead: it leaves the one at tD and reaches the other
      // at tA, and the page glides it between them (dwelling while tD is ahead).
      const ar = (x) => x.a || x.d, dp = (x) => x.d || x.a;
      const k = sts.findIndex((x) => ar(x) > nowS);
      let N, tA, tD = 0;
      if (k < 0){ N = o.stop || (sts.length ? sts[sts.length - 1].stop : ''); const x = sts.find((q) => q.stop === N); tA = x ? ar(x) : (o.t || nowS); }
      else { N = sts[k].stop; tA = ar(sts[k]); if (k > 0) tD = dp(sts[k - 1]); }
      if (!N) continue;
      const P0 = PR[o.route + '|' + N] || PR[o.route.replace(/X$/, '') + '|' + N]; if (!P0) continue;   // not yet left its first stop, or off its pattern
      if (!tD) tD = tA - P0[4];
      const standing = k > 0 && o.st === 1 && o.stop === sts[k - 1].stop && tD > nowS;
      const held = standing && o.t && nowS - o.t > 150, late = k < 0 && tA && nowS > tA + 90;
      let h = 0; for (let i = 0; i < o.trip.length; i++) h = (h * 31 + o.trip.charCodeAt(i)) >>> 0;
      out.push([o.route, P0[0], P0[1], P0[2], P0[3], P0[4], Math.round(tA), standing ? 1 : 0, held ? 1 : 0, late ? 1 : 0, N,
                sts.length ? sts[sts.length - 1].stop : N, Math.round(tD), h.toString(36)]);
    } }
  return { at: now, feeds, trains: out };
}
export async function subwayRoute(url, ctx, cors){
  const cache = caches.default, key = new Request('https://tiles.bluishvoid.com/subway/v1/nyc.json', { method: 'GET' });
  let hit = await cache.match(key);
  if (!hit){
    let body; try { body = JSON.stringify(await buildSub()); } catch (e){ return new Response(JSON.stringify({ error: String(e) }), { status: 502, headers: { 'Content-Type': 'application/json', ...cors } }); }
    hit = new Response(body, { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=12' } });
    ctx.waitUntil(cache.put(key, hit.clone()));
  }
  const h = new Headers(hit.headers); Object.entries(cors).forEach(([k, v]) => h.set(k, v)); h.set('Cache-Control', 'public, max-age=10');
  return new Response(hit.body, { status: 200, headers: h });
}


/* MEASURED SUBWAY DELAYS AT THE EDGE (2026-10-20, user: "do this"). THE CITY's cwMeasRun (index.html), moved here so the page
   reads one small JSON instead of all seven raw feeds every 30 s (~80 KB a minute while the subway lines are on screen). Same
   rules, same output objects:
     HELD  STOPPED_AT the same station across reads for 4+ min AND its predictions slipped 3+ min (not at its first or last stop)
     LATE  a predicted arrival slipped 5+ min since first seen
     GAP   at a station with 3+ trains coming, one interval over max(12 min, 2.5 x scheduled headway, 2.2 x the line's live
           median, 2.5 x the station's own median), and only where the hole is arriving within 15 min
   HELD and LATE need minutes of watching: the per-train history lives in the colo's cache (one copy for every isolate there),
   so it carries across visitors -- the page had to start from nothing on every visit. */
const GRAPH_URL = 'https://bluishvoid.com/city_subway_graph.json?v=2';
let GRAPH = null, GRAPH_AT = 0;
async function subGraph(){
  if (GRAPH && Date.now() - GRAPH_AT < 6 * 3600e3) return GRAPH;
  const G = await (await fetch(GRAPH_URL, { cf: { cacheTtl: 3600 } })).json();
  G._node = {}; G.n.forEach((n) => { G._node[n[0]] = n; });
  G._in = {}; G.e.forEach((e) => { G._in[e[2] + e[3] + '|' + e[1]] = 1; });
  G._srv = {}; G.e.forEach((e) => { [e[0], e[1]].forEach((id) => { const k = e[2] + e[3]; (G._srv[k] = G._srv[k] || {})[id] = 1; }); });
  GRAPH = G; GRAPH_AT = Date.now(); return G;
}
const routeShow = (rt) => (rt === 'GS' || rt === 'FS' || rt === 'H') ? 'S' : (rt === 'SI' ? 'SIR' : rt);
const HIST_KEY = 'https://tiles.bluishvoid.com/subway/v1/_hist';
async function buildDelays(){
  const cache = caches.default, G = await subGraph(), reads = await subReads(), now = Date.now() / 1000;
  let M = { since: now, hist: {} };
  try { const h = await cache.match(HIST_KEY); if (h){ const j = await h.json(); if (j && j.hist && now - (j.at || 0) < 600) M = j; } } catch (e) {}
  const H = M.hist, ev = [], trips = {};
  let feeds = 0;
  for (const D of reads){ if (!D) continue; feeds++;
    for (const [tid, U] of Object.entries(D.tu)){ const T = trips[tid] = trips[tid] || { rt: '', st: [], vs: null, vsid: '' };
      if (U.route) T.rt = U.route; const st = U.sts.map((x) => [x.stop, x.a || x.d]).filter((x) => x[1]); if (st.length) T.st = st; }
    for (const o of D.veh){ if (!o.trip) continue; const T = trips[o.trip] = trips[o.trip] || { rt: o.route, st: [], vs: null, vsid: '' };
      if (o.st != null){ T.vs = o.st; T.vsid = o.stop; } } }
  const base = (sid) => sid.replace(/[NS]$/, ''), rtOf = (rt) => rt === 'SS' ? 'SI' : rt, seen = {};
  for (const tid of Object.keys(trips)){
    const T = trips[tid], rt = rtOf(T.rt); if (!rt || rt === 'SI' || !T.st.length) continue;
    const dir = /N$/.test(T.st[0][0]) ? 'N' : 'S', h = H[tid] = H[tid] || { sid: '', since: now, pred: {} };
    seen[tid] = 1; let heldNow = 0, worst = 0, wsid = '';
    for (const x of T.st){ if (x[1] < now || x[1] > now + 1800) continue;
      const p0 = h.pred[x[0]]; if (!p0){ h.pred[x[0]] = [x[1], now]; continue; }
      if (now - p0[1] >= 240){ const d = (x[1] - p0[0]) / 60; if (d > worst){ worst = d; wsid = x[0]; } } }
    for (const k of Object.keys(h.pred)) if (h.pred[k][0] < now - 120) delete h.pred[k];   // stops it has passed: the stored history stays small
    if (T.vs === 1 && T.vsid){
      if (h.sid !== T.vsid){ h.sid = T.vsid; h.since = now; }
      const held = (now - h.since) / 60, last = T.st[T.st.length - 1][0] === T.vsid, origin = !G._in[rt + dir + '|' + base(T.vsid)];
      if (held >= 4 && worst >= 3 && !last && !origin && G._node[base(T.vsid)]){ ev.push({ k: 'held', rt, dir, sid: base(T.vsid), m: held }); heldNow = 1; }
    } else h.sid = '';
    if (!heldNow && worst >= 5 && G._node[base(wsid)]) ev.push({ k: 'late', rt, dir, sid: base(wsid), m: worst });
  }
  for (const tid of Object.keys(H)) if (!seen[tid]) delete H[tid];
  const arr = {};
  for (const tid of Object.keys(trips)){ const T = trips[tid], rt = rtOf(T.rt); if (!rt || rt === 'SI') continue;
    for (const x of T.st){ if (x[1] < now - 30) continue; const k = rt + (/N$/.test(x[0]) ? 'N' : 'S'); ((arr[k] = arr[k] || {})[base(x[0])] = arr[k][base(x[0])] || []).push(x[1]); } }
  for (const k of Object.keys(arr)){
    const A = arr[k], srv = G._srv[k] || {}, gaps = [];
    for (const sid of Object.keys(A)){ const L = A[sid].sort((a, b) => a - b); for (let i = 1; i < L.length; i++) gaps.push(L[i] - L[i - 1]); }
    if (gaps.length < 6) continue;
    gaps.sort((a, b) => a - b);
    const med = gaps[gaps.length >> 1], hs = (G.h || {})[k] || 480, thr = Math.max(720, 2.5 * hs, 2.2 * med);
    for (const sid of Object.keys(A)){ const L = A[sid]; if (L.length < 3 || !srv[sid] || !G._node[sid]) continue;
      const g2 = []; for (let i = 1; i < L.length; i++) g2.push(L[i] - L[i - 1]);
      const srt = g2.slice().sort((a, b) => a - b), md = srt[(srt.length - 1) >> 1], big = srt[srt.length - 1];
      if (!(big > Math.max(thr, 2.5 * md))) continue;
      const gi = g2.indexOf(big); if (L[gi] - now > 900) continue;
      ev.push({ k: 'gap', rt: k.slice(0, -1), dir: k.slice(-1), sid, m: big / 60 }); }
  }
  const grp = {};
  ev.forEach((e, ei) => { const key = e.k === 'gap' ? e.rt + e.dir + e.k : e.rt + e.dir + e.k + ei; const g = grp[key] = grp[key] || { rt: e.rt, dir: e.dir, k: e.k, sids: [], m: 0 }; g.sids.push(e.sid); if (e.m != null && e.m > g.m) g.m = e.m; });
  const out = [];
  for (const g of Object.values(grp)){
    const pts = g.sids.map((id) => { const n = G._node[id]; return [n[2], n[3], n[1]]; });
    const r = routeShow(g.rt), m = Math.round(g.m);
    const short = g.k === 'held' ? (g.sids.length > 1 ? g.sids.length + ' TRAINS HELD' : 'TRAIN HELD ' + m + ' MIN') : g.k === 'late' ? 'RUNNING ' + m + ' MIN LATE' : m + ' MIN GAP';
    const where = pts.length === 1 ? pts[0][2] : pts[0][2] + ' TO ' + pts[pts.length - 1][2];
    const text = g.k === 'held' ? (g.sids.length > 1 ? g.sids.length + ' ' + r + ' trains are stopped at stations, the longest for ' + m + ' min (' + where + ').' : 'A ' + r + ' train has been stopped at ' + where + ' for ' + m + ' min.')
      : g.k === 'late' ? 'A ' + r + ' train now arrives ' + m + ' min later than it was predicted to a few minutes ago (' + where + ').'
      : 'Along ' + where + ' there is a ' + m + ' min hole between ' + r + ' trains, far longer than the spacing either side of it.';
    out.push({ kind: 'Measured delay', measured: true, short, text: text + ' Measured from the MTA’s live train positions, not a posted alert.', routes: [g.rt], dir: g.dir, bor: [], pts, mins: g.m });
  }
  out.sort((a, b) => (b.mins || 0) - (a.mins || 0));
  M.at = now;
  await cache.put(HIST_KEY, new Response(JSON.stringify(M), { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=900' } }));
  return { at: Math.round(now), feeds, trips: Object.keys(trips).length, watchingMin: Math.round((now - M.since) / 60), list: out.slice(0, 10) };
}
export async function delaysRoute(url, ctx, cors){
  const cache = caches.default, key = new Request('https://tiles.bluishvoid.com/subway/v1/delays.json?m=' + Math.floor(Date.now() / 25000), { method: 'GET' });
  let hit = await cache.match(key);
  if (!hit){
    let body; try { body = JSON.stringify(await buildDelays()); } catch (e){ return new Response(JSON.stringify({ error: String(e) }), { status: 502, headers: { 'Content-Type': 'application/json', ...cors } }); }
    hit = new Response(body, { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=25' } });
    ctx.waitUntil(cache.put(key, hit.clone()));
  }
  const h = new Headers(hit.headers); Object.entries(cors).forEach(([k, v]) => h.set(k, v)); h.set('Cache-Control', 'public, max-age=20');
  return new Response(hit.body, { status: 200, headers: h });
}
