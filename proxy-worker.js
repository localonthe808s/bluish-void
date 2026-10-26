// Cloudflare Worker: bluish-void edge cache + CORS proxy
//
// Deployed at https://proxy.bluishvoid.com/?url=<encoded-target>
// (dev URL: https://bluish-void-proxy.<account>.workers.dev/?url=...)
//
// Wraps upstream GET requests that lack Access-Control-Allow-Origin (NOAA, NASA,
// SWPC, CIRA, …) so the browser on bluishvoid.com can fetch them, AND caches the
// identical-for-everyone responses at the Cloudflare edge so every visitor isn't
// hammering slow government origins.
//
// Two wins over a plain pass-through:
//   1) Per-resource TTLs  — 1-minute space-weather feeds cache 60s; quasi-static
//      NASA imagery caches up to a day (CACHE_RULES below). The host keys also
//      double as the upstream allowlist (prevents open-proxy abuse).
//   2) Stale-on-error     — if the upstream is slow or down, serve the last good
//      cached copy instead of failing the widget (Cache API).
//
// Safety: every cache operation is wrapped in try/catch. If the cache layer ever
// throws, the worker still falls back to a plain fetch+CORS — caching can degrade
// but the proxy path can never break.
//
// Deploy:  wrangler deploy        (route: proxy.bluishvoid.com/*  — keep existing)

const ALLOWED_ORIGINS = [
  'https://bluishvoid.com',
  'https://www.bluishvoid.com',
  'http://localhost:8000',
  'http://localhost:3000'
];

// Per-host cache TTL in seconds. Hosts NOT listed here are rejected (403) — the
// keys are the upstream allowlist. Tune freely.
const CACHE_RULES = {
  // ── 1-minute space-weather feeds ──
  'services.swpc.noaa.gov':       60,
  // ── live imagery loops / model graphics (a few minutes) ──
  'www.star.nesdis.noaa.gov':     300,
  'satlib.cira.colostate.edu':    300,
  'slider.cira.colostate.edu':    300,
  'radar.weather.gov':            120,
  'mapservices.weather.noaa.gov': 120,
  'mag.ncep.noaa.gov':            600,
  'nomads.ncep.noaa.gov':         600,
  'www.emc.ncep.noaa.gov':        600,
  // ── forecasts / advisories (5–10 minutes) ──
  'api.weather.gov':              300,
  'water.noaa.gov':               300,
  'coast.noaa.gov':               86400,
  'erddap.ifremer.fr':            3600,   // Argo: one float's year of profiles, on tap (WATER > ARGO FLOATS, 2026-10-25)  // Sea Level Rise Viewer flood-depth tiles (static; the LOCAL tide map recolors them)
  // ── transit agencies' GTFS-realtime vehicle positions (LOCAL TRAFFIC tab; _transitbake/hosts.txt, 2026-10-16) ──
  'api.cityofkingston.ca': 15,
  'api.nextlift.ca': 15,
  'apps.santaclaritatransit.com': 15,
  'bct.tmix.se': 15,
  'breezerider.tripsparkhost.com': 15,
  'bt.mountainline.com': 15,
  'bus.gocitybus.com': 15,
  'bustracker.sbmtd.gov': 15,
  'cdn.mbta.com': 15,
  'cttprdtmgtfs.ctttrpcloud.com': 15,
  'developers.cata.org': 15,
  'drtonline.durhamregiontransit.com': 15,
  'duluthtransit.com': 15,
  'emerygoround.tripshot.com': 15,
  'everett.mapstrat.com': 15,
  'feed.ltd.org': 15,
  'gis4u.fresno.gov': 15,
  'glphprdtmgtfs.glphtrpcloud.com': 15,
  'gotriangle.tripsparkhost.com': 15,
  'gtfs-rt.gcrta.vontascloud.com': 15,
  'gtfs-rt.itsmarta.com': 15,
  'gtfs.cdta.org': 15,
  'gtfs.halifax.ca': 15,
  'gtfs.ltconline.ca': 15,
  'gtfs.viainfo.net': 15,
  'gtfsbridge.spokanetransit.com': 15,
  'gtfsr.tri-rail.com': 15,
  'gtfsrealtime.ridetransit.org': 15,
  'gtfsrt.golynx.com': 15,
  'gtfsrt.gptd.cadavl.com': 15,
  'gtfsrt.rvtd.cadavl.com': 15,
  'itransitnw.com': 15,
  'kart.connexionz.net': 15,
  'kttracker.com': 15,
  'mdotmta-gtfs-rt.s3.amazonaws.com': 15,
  'gtfsrt.prod.obanyc.com': 15,       // MTA Bus Time vehicle positions (keyless; LOCAL TRAFFIC, NYC buses)
  'metromap.cityofmadison.com': 15,
  'myride.bft.org': 15,
  'myride.shoretransit.org': 15,
  'myride2.broward.org': 15,
  'nextccbus.org': 15,
  'nywaterway.connexionz.net': 15,
  'opendata.burlington.ca': 15,
  'opendata.hamilton.ca': 15,
  'planmyride.blinetransit.com': 15,
  'racine.connexionz.net': 15,
  'realtime.arlingtontransit.com': 15,
  'realtime.prod.dash.obaweb.org': 15,
  'realtime.ridemcts.com': 15,
  'ride.smtd.org': 15,
  'rmwb-gtfsrt.civilia.ca': 15,
  'rt.pasadenatransit.net': 15,
  'rt.scmetro.org': 15,
  'rtabus.com': 15,
  'rtu.york.ca': 15,
  's3.amazonaws.com': 15,
  'slo.connexionz.net': 15,
  'sportranbus.com': 15,
  'strweb.skagittransit.org': 15,
  'tmgtfsprd.sorttrpcloud.com': 15,
  'transitdata.nashvillemta.org': 15,
  'truetime.portauthority.org': 15,
  'www.fairfaxcounty.gov': 15,
  'www.goraleighlive.org': 15,
  'www.metrostlouis.org': 15,
  'www.miapp.ca': 15,
  'www.myridebarrie.ca': 15,
  'www.ridedart.com': 15,
  'www.valleyregionaltransit.org': 15,
  'www3.septa.org': 15,
  'ycta.connexionz.net': 15,
  'www.nhc.noaa.gov':             600,
  // ATCF a-deck model tracks (spaghetti) — no CORS upstream
  'ftp.nhc.noaa.gov':             600,
  'www.spc.noaa.gov':             600,
  'www.wpc.ncep.noaa.gov':        600,
  'www.cpc.ncep.noaa.gov':        600,
  'gibs.earthdata.nasa.gov':      600,
  // Unidata THREDDS: NOAA GFS as WMS images (jet stream, wind belts, column moisture) for CLOUDS > EARTH SYSTEMS.
  // The flat map shows them as plain <img>, which needs no CORS; the GLOBE uses them as WebGL textures, which does,
  // and thredds sends no Access-Control-Allow-Origin. 30 min: GFS runs six-hourly, and one cached copy serves everyone.
  'thredds.ucar.edu':             1800,
  'api.rss2json.com':             600,
  'kauai.ccmc.gsfc.nasa.gov':     300,
  // NSO's GONG far-side server (one box behind three names). DEAD ENTRIES, kept as the record: it drops every
  // datacenter connection -- GitHub's runners, Cloudflare (522 from here), allorigins, codetabs -- and answers
  // only home connections (2026-10-10), so the helio bake's placeholder check cannot run from anywhere we have.
  'farside.nso.edu':              1800,
  'gong2.nso.edu':                1800,
  'gong.nso.edu':                 1800,
  'api.nasa.gov':                 300,
  'ssd-api.jpl.nasa.gov':         1800,
  // ── ISS live position (fast-moving; short TTL) ──
  // open-notify is http-only + no CORS, so the browser must reach it through
  // this worker. api.wheretheiss.at is the richer source (adds altitude/
  // velocity) but let its TLS cert expire 2026-07-19; listed so the card
  // upgrades back to it automatically once they renew. 10s: the ISS moves
  // ~4.6 mi/sec, and the card refetches on that cadence.
  'api.open-notify.org':          10,
  'api.wheretheiss.at':           10,
  // ── quasi-static imagery (1 hour+) ──
  'sdo.gsfc.nasa.gov':            3600,
  'svs.gsfc.nasa.gov':            3600,
  'soho.nascom.nasa.gov':         3600,
  'apod.nasa.gov':                3600,
  /* SPACE NEWS (2026-10-15): the three RSS feeds the news list reads (all public news feeds), and APOD's new home, whose
     page is the only place today's title lives now that the APOD API returns "NASA Science" for every date */
  'science.nasa.gov':             3600,
  'phys.org':                     900,
  'www.esa.int':                  1800,
  'hirise.lpl.arizona.edu':       3600,
  'images-assets.nasa.gov':       86400,
  'djlorenz.github.io':           86400,
  // ── NYC Ferry (2026-09-07): GTFS-RT trip updates + the static schedule zip.
  //    The feed answers fine but sends no Access-Control-Allow-Origin, so the
  //    city widget's ferry board has to come through here. 25 s matches the
  //    MTA feed cache the subway board already uses. ──
  'nycferry.connexionz.net':      25,
  // ── Los Angeles widget (2026-09-19). Both answer fine and send no
  //    Access-Control-Allow-Origin. coastwatch = NOAA's ERDDAP mirror of the NDBC
  //    wave buoys (one JSON call for every buoy off LA, ~30-min readings) for the
  //    SURF layer; CHP = the statewide dispatch log for the TRAFFIC layer. ──
  'coastwatch.pfeg.noaa.gov':     600,
  // ── GULF STREAM currents (2026-09-21). NESDIS CoastWatch ERDDAP (a different
  //    server from the PFEG one above): daily geostrophic surface currents from
  //    altimetry, u/v in m/s, keyless, no Access-Control-Allow-Origin. The grid is
  //    one day per day and lands two days late, so an hour of cache is nothing lost. ──
  'coastwatch.noaa.gov':          3600,
  'www.ndbc.noaa.gov':            600,
  'media.chp.ca.gov':             60,
  // ── THE CITY's TRAFFIC tab (2026-09-20). Both answer without a key and send no
  //    Access-Control-Allow-Origin. panynj = the Port Authority's crossing times (GWB,
  //    Lincoln, Holland, Bayonne, Goethals, Outerbridge: minutes now against usual).
  //    511ny = the state's event list, 2.7 MB for all of New York -- ALWAYS asked for
  //    with &shape=nyc511 (below), which cuts it to the city's closures and incidents. ──
  'www.panynj.gov':               120,
  '511ny.org':                    300,
  // ── Open-Meteo (2026-09-23). These answer with CORS, so the browser normally goes
  //    direct; they are listed so the fallback tier WORKS when a network blocks or
  //    rate-limits the direct call. Before this the hero's fallback hit a 403 here,
  //    then allorigins timed out at 12 s, and the top panel sat on "--" (seen on a
  //    work network while every other widget loaded). The forecast is hourly data,
  //    so 5 minutes of edge cache is nothing lost and spares Open-Meteo's per-IP quota. ──
  'api.open-meteo.com':           300,
  'air-quality-api.open-meteo.com': 600,
  'marine-api.open-meteo.com':    600,
  'geocoding-api.open-meteo.com': 86400,
  // ── NEUTRINO HUNTERS (2026-09-30). Super-K's realtime monitor picture, one GIF the observatory rewrites every
  //    ~22 s; the page reads the event's hit counts off it (needs the bytes, so the proxy), 20 s of edge cache
  //    so every viewer shares one fetch. Their site has no CORS header. ──
  'www-sk.icrr.u-tokyo.ac.jp':    20,
  // ── Caltrans District 7 camera list (THE BASIN). 1.85 MB raw, asked for with &shape=d7cctv, which keeps the in-service
  //    cameras and only the fields the widget reads (perf review 2026-10-12). The pages refresh it every 10 min. ──
  'cwwp2.dot.ca.gov':             600,
  // ── US Census address finder (2026-10-14): house numbers OpenStreetMap lacks ("7239 Chandan Blvd" found only the
  //    street there), for the phone-alerts place search. No CORS header on their side. A day of edge cache. ──
  'geocoding.geo.census.gov':     86400
};

// SHAPES: an upstream that is far too big to hand a phone is cut down HERE, once, and the
// slim copy is what gets cached and served. Asked for with &shape=<name>; unknown = ignored.
const SHAPES = {
  // 511NY: keep what is inside New York City and is a closure or an incident, and only the
  // fields the map reads. Measured 2026-09-20: 2,231 events / 2.7 MB -> 127 events / ~92 KB.
  nyc511(text) {
    const all = JSON.parse(text);
    const keep = ['ID', 'EventType', 'EventSubType', 'RoadwayName', 'DirectionOfTravel', 'Description',
                  'Latitude', 'Longitude', 'LastUpdated', 'Severity', 'LanesAffected', 'LanesStatus',
                  'StartDate', 'PlannedEndDate'];
    const out = (Array.isArray(all) ? all : []).filter(e =>
      e && e.Latitude > 40.49 && e.Latitude < 40.92 && e.Longitude > -74.27 && e.Longitude < -73.68 &&
      (e.EventType === 'closures' || e.EventType === 'accidentsAndIncidents')
    ).map(e => { const o = {}; keep.forEach(k => { o[k] = e[k]; }); return o; });
    return JSON.stringify(out);
  },
  // Caltrans D7 cameras: same {data:[{cctv:{...}}]} structure the pages parse, cut to in-service cameras with a current
  // picture, and to index / location (name, place, lat, lon, direction, route) / inService / imageData.static (url, rate).
  d7cctv(text) {
    const all = JSON.parse(text);
    const data = ((all && all.data) || []).map(o => o && o.cctv).filter(c => c && c.inService === 'true' &&
      c.imageData && c.imageData.static && c.imageData.static.currentImageURL).map(c => {
      const L = c.location || {}, S = c.imageData.static;
      return { cctv: { index: c.index, inService: c.inService,
        location: { locationName: L.locationName, nearbyPlace: L.nearbyPlace, latitude: L.latitude, longitude: L.longitude, direction: L.direction, route: L.route },
        imageData: { static: { currentImageURL: S.currentImageURL, currentImageUpdateFrequency: S.currentImageUpdateFrequency } } } };
    });
    return JSON.stringify({ data });
  }
};

const DEFAULT_TTL = 300;
const MAX_TTL = 86400;

function isAllowed(host) {
  return Object.prototype.hasOwnProperty.call(CACHE_RULES, host);
}

function ttlFor(host, override) {
  if (Number.isFinite(override) && override > 0) return Math.min(override, MAX_TTL);
  return CACHE_RULES[host] || DEFAULT_TTL;
}

function withCors(resp, cors, state, age) {
  const h = new Headers(resp.headers);
  for (const k in cors) h.set(k, cors[k]);
  if (state) h.set('X-BV-Cache', state);
  if (age != null) h.set('Age', String(age));
  return new Response(resp.body, { status: resp.status, headers: h });
}

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...cors, 'Content-Type': 'application/json' }
  });
}

// ── VEHICLE BOX (2026-10-18, perf item 16): &vbox=w,s,e,n on a GTFS-realtime vehicle-positions url. The LOCAL map's
//    TRAFFIC view drew only the buses in its box, yet pulled the MTA's whole city every 30 s (~252 KB protobuf, ~70 KB
//    brotli, ~1,960 buses). Here the feed is fetched ONCE per TTL under the SAME cache key as the plain path (so the raw
//    copy the old page path reads is shared, never refetched twice), decoded with the page's own walk, cut to the box
//    and sent as {box, v:[[route, lat, lon, bearing|null, timestamp], ...]}. The box is snapped OUTWARD to 0.05 degrees
//    so nearby pans share one cached cut. lat/lon/bearing are float32 on the wire: they go out as the SHORTEST string
//    that is still the same float32, and the page Math.frounds them back -- the very doubles its own decoder makes.
//    An old page never sends vbox, and an old worker ignores it (answers raw), so either side can ship first. ──
function vbParse(s) {
  const p = String(s || '').split(',').map(Number);
  if (p.length !== 4 || !p.every(Number.isFinite)) return null;
  const b = [Math.floor(p[0] * 20) / 20, Math.floor(p[1] * 20) / 20, Math.ceil(p[2] * 20) / 20, Math.ceil(p[3] * 20) / 20];
  if (!(b[0] < b[2] && b[1] < b[3]) || b[0] < -180 || b[2] > 180 || b[1] < -90 || b[3] > 90) return null;
  return b.map(x => Number(x.toFixed(2)));
}
function vbF32(v) {   // shortest decimal that is still this float32
  for (let p = 6; p < 10; p++) { const x = Number(v.toPrecision(p)); if (Math.fround(x) === v) return x; }
  return v;
}
function vbDecode(buf, box) {   // same walk as the page's gtfsVehicles(): FeedEntity 2 > vehicle 4 > trip 1 (route 5), position 2 (lat 1, lon 2, bearing 3), timestamp 5
  const b = new Uint8Array(buf), dv = new DataView(buf), out = [];
  const pv = (i) => { let v = 0, k = 1; for (;;) { const x = b[i++]; v += (x & 127) * k; if (!(x & 128)) return [v, i]; k *= 128; } };
  const walk = (s0, e0, cb) => { let i = s0, t;
    while (i < e0) { t = pv(i); i = t[1]; const fn = Math.floor(t[0] / 8), wt = t[0] & 7;
      if (wt === 0) { t = pv(i); cb(fn, 0, t[0], 0, 0); i = t[1]; }
      else if (wt === 2) { t = pv(i); i = t[1]; cb(fn, 2, 0, i, i + t[0]); i += t[0]; }
      else if (wt === 5) { cb(fn, 5, dv.getFloat32(i, true), 0, 0); i += 4; }
      else if (wt === 1) i += 8; else return; } };
  const str = (s0, e0) => { let o = ''; for (let q = s0; q < e0; q++) o += String.fromCharCode(b[q]); return o; };
  walk(0, b.length, (f, w, v, s0, e0) => { if (f !== 2 || w !== 2) return;
    walk(s0, e0, (f2, w2, v2, s2, e2) => { if (f2 !== 4 || w2 !== 2) return;
      const o = { r: '', la: null, lo: null, br: null, t: 0 };
      walk(s2, e2, (f3, w3, v3, s3, e3) => {
        if (f3 === 1 && w3 === 2) walk(s3, e3, (f4, w4, v4, s4, e4) => { if (f4 === 5 && w4 === 2) o.r = str(s4, e4); });
        else if (f3 === 2 && w3 === 2) walk(s3, e3, (f4, w4, v4) => { if (w4 === 5) { if (f4 === 1) o.la = v4; else if (f4 === 2) o.lo = v4; else if (f4 === 3) o.br = v4; } });
        else if (f3 === 5 && w3 === 0) o.t = v3;
      });
      if (Number.isFinite(o.la) && Number.isFinite(o.lo) && Math.abs(o.la) > 1 &&
          o.lo >= box[0] && o.la >= box[1] && o.lo <= box[2] && o.la <= box[3])
        out.push([o.r, vbF32(o.la), vbF32(o.lo), Number.isFinite(o.br) ? vbF32(o.br) : null, o.t]); }); });
  return out;
}
async function vehicleBox(targetUrl, box, ttl, cors, ctx) {
  const cache = caches.default;
  const rawKey = new Request(targetUrl.toString(), { method: 'GET' });   // the plain path's key: one raw copy serves both
  const bk = new URL(targetUrl.toString()); bk.searchParams.set('__bvvbox', box.join(','));
  const boxKey = new Request(bk.toString(), { method: 'GET' });
  const ageOf = (r) => (Date.now() - Number(r.headers.get('X-BV-Cached-At') || 0)) / 1000;
  // 1) a fresh cut of this box (its age is the RAW copy's, so cutting never stacks a second TTL on the data)
  let cut = null;
  try { cut = await cache.match(boxKey); } catch (e) { cut = null; }
  if (cut) { const a = ageOf(cut); if (a >= 0 && a < ttl) return withCors(cut, cors, 'HIT', Math.floor(a)); }
  // 2) the raw feed: the shared cached copy if fresh, else the origin (stored exactly as the plain path stores it)
  let raw = null, rawBuf = null, rawAt = 0, state = 'MISS';
  try { raw = await cache.match(rawKey); } catch (e) { raw = null; }
  if (raw && ageOf(raw) >= 0 && ageOf(raw) < ttl) { rawAt = Number(raw.headers.get('X-BV-Cached-At') || 0); rawBuf = await raw.arrayBuffer(); state = 'RAW-HIT'; }
  else {
    let up = null;
    try { up = await fetch(targetUrl.toString(), { headers: { 'User-Agent': 'bluishvoid-edge/1.0 (+https://bluishvoid.com)' } }); } catch (e) { up = null; }
    if (up && up.ok) {
      rawBuf = await up.arrayBuffer(); rawAt = Date.now();
      const rh = { 'Content-Type': up.headers.get('Content-Type') || 'application/octet-stream', 'Cache-Control': `public, max-age=${ttl}`,
                   'X-BV-Cached-At': String(rawAt), 'X-BV-Upstream': targetUrl.hostname };
      try { ctx.waitUntil(cache.put(rawKey, new Response(rawBuf, { status: 200, headers: rh }))); } catch (e) { /* best-effort */ }
    } else if (cut) return withCors(cut, cors, 'STALE-ERR', null);
    else if (raw) { rawAt = Number(raw.headers.get('X-BV-Cached-At') || 0); rawBuf = await raw.arrayBuffer(); state = 'STALE-ERR'; }
    else return json({ error: 'Upstream fetch failed', status: up ? up.status : 0 }, 502, cors);
  }
  // 3) cut it; a decode failure serves the last cut if there is one
  let body;
  try { body = JSON.stringify({ box, v: vbDecode(rawBuf, box) }); }
  catch (e) {
    if (cut) return withCors(cut, cors, 'STALE-ERR', null);
    return json({ error: 'Vehicle decode failed', detail: String(e) }, 502, cors);
  }
  const sh = { 'Content-Type': 'application/json', 'Cache-Control': `public, max-age=${ttl}`, 'X-BV-Cached-At': String(rawAt), 'X-BV-Upstream': targetUrl.hostname };
  if (state !== 'STALE-ERR') { try { ctx.waitUntil(cache.put(boxKey, new Response(body, { status: 200, headers: sh }))); } catch (e) { /* best-effort */ } }
  return withCors(new Response(body, { status: 200, headers: sh }), cors, state, Math.max(0, Math.floor((Date.now() - rawAt) / 1000)));
}

export default {
  async fetch(request, env, ctx) {
    const reqUrl = new URL(request.url);
    const origin = request.headers.get('Origin') || '';
    const corsOrigin = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
    const cors = { 'Access-Control-Allow-Origin': corsOrigin, 'Vary': 'Origin' };

    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: { ...cors, 'Access-Control-Allow-Methods': 'GET, OPTIONS', 'Access-Control-Max-Age': '86400' }
      });
    }
    if (request.method !== 'GET') {
      return new Response('Method not allowed', { status: 405, headers: cors });
    }

    const target = reqUrl.searchParams.get('url');
    if (!target) {
      // health check / no target
      return json({ ok: true, service: 'bluishvoid edge cache', hosts: Object.keys(CACHE_RULES).length }, 200, cors);
    }

    let targetUrl;
    try { targetUrl = new URL(target); }
    catch (e) { return json({ error: 'Invalid url parameter' }, 400, cors); }

    if (targetUrl.protocol !== 'https:' && targetUrl.protocol !== 'http:') {
      return json({ error: 'Unsupported protocol' }, 400, cors);
    }
    if (!isAllowed(targetUrl.hostname)) {
      return json({ error: 'Upstream host not allowed', host: targetUrl.hostname }, 403, cors);
    }

    const override = parseInt(reqUrl.searchParams.get('ttl') || '', 10);
    const ttl = ttlFor(targetUrl.hostname, override);
    // VEHICLE BOX (above): only when the page asks for it; every other request takes the unchanged path below
    if (reqUrl.searchParams.has('vbox')) {
      const box = vbParse(reqUrl.searchParams.get('vbox'));
      if (!box) return json({ error: 'Invalid vbox (want w,s,e,n)' }, 400, cors);
      try { return await vehicleBox(targetUrl, box, ttl, cors, ctx); }
      catch (e) { return json({ error: 'Vehicle box failed', detail: String(e) }, 502, cors); }   // the page then reads the raw feed
    }
    const cache = caches.default;
    // a shaped copy is a different object from the raw one: it gets its own cache key
    const shapeName = reqUrl.searchParams.get('shape') || '';
    const shape = Object.prototype.hasOwnProperty.call(SHAPES, shapeName) ? SHAPES[shapeName] : null;
    const keyUrl = new URL(targetUrl.toString());
    if (shape) keyUrl.searchParams.set('__bvshape', shapeName);
    const cacheKey = new Request(keyUrl.toString(), { method: 'GET' });

    // 1) Fresh edge hit? (guarded — cache errors never break the path)
    let cached = null;
    try { cached = await cache.match(cacheKey); } catch (e) { cached = null; }
    if (cached) {
      const age = (Date.now() - Number(cached.headers.get('X-BV-Cached-At') || 0)) / 1000;
      if (age >= 0 && age < ttl) return withCors(cached, cors, 'HIT', Math.floor(age));
    }

    // 2) Miss or stale → revalidate from origin
    let upstream;
    try {
      upstream = await fetch(targetUrl.toString(), {
        headers: { 'User-Agent': 'bluishvoid-edge/1.0 (+https://bluishvoid.com)' }
      });
    } catch (e) {
      if (cached) return withCors(cached, cors, 'STALE-ERR', null);
      return json({ error: 'Upstream fetch failed', detail: String(e) }, 502, cors);
    }

    if (!upstream.ok) {
      // serve stale rather than propagate a flaky 5xx, if we have anything
      if (cached) return withCors(cached, cors, 'STALE-ERR', null);
      const errBody = await upstream.arrayBuffer();
      return new Response(errBody, {
        status: upstream.status,
        headers: { ...cors, 'Content-Type': upstream.headers.get('Content-Type') || 'text/plain', 'X-BV-Cache': 'MISS-ERR' }
      });
    }

    let body = await upstream.arrayBuffer();
    let shaped = false;
    if (shape) {
      // if the upstream changes its format the shape throws: serve stale if we have it, else say so
      try { body = new TextEncoder().encode(shape(new TextDecoder().decode(body))).buffer; shaped = true; }
      catch (e) {
        if (cached) return withCors(cached, cors, 'STALE-ERR', null);
        return json({ error: 'Shape failed', shape: shapeName, detail: String(e) }, 502, cors);
      }
    }
    const storeHeaders = {
      'Content-Type': shaped ? 'application/json' : (upstream.headers.get('Content-Type') || 'application/octet-stream'),
      'Cache-Control': `public, max-age=${ttl}`,
      'X-BV-Cached-At': String(Date.now()),
      'X-BV-Upstream': targetUrl.hostname
    };

    // store a clean copy for future hits + stale-on-error (guarded)
    try { ctx.waitUntil(cache.put(cacheKey, new Response(body, { status: 200, headers: storeHeaders }))); }
    catch (e) { /* caching is best-effort */ }

    return withCors(new Response(body, { status: 200, headers: storeHeaders }), cors, cached ? 'REVALIDATED' : 'MISS', 0);
  }
};
