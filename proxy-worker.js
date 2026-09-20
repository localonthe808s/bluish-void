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
  'www.nhc.noaa.gov':             600,
  // ATCF a-deck model tracks (spaghetti) — no CORS upstream
  'ftp.nhc.noaa.gov':             600,
  'www.spc.noaa.gov':             600,
  'www.wpc.ncep.noaa.gov':        600,
  'www.cpc.ncep.noaa.gov':        600,
  'gibs.earthdata.nasa.gov':      600,
  'api.rss2json.com':             600,
  'kauai.ccmc.gsfc.nasa.gov':     300,
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
  'www.ndbc.noaa.gov':            600,
  'media.chp.ca.gov':             60,
  // ── THE CITY's TRAFFIC tab (2026-09-20). Both answer without a key and send no
  //    Access-Control-Allow-Origin. panynj = the Port Authority's crossing times (GWB,
  //    Lincoln, Holland, Bayonne, Goethals, Outerbridge: minutes now against usual).
  //    511ny = the state's event list, 2.7 MB for all of New York -- ALWAYS asked for
  //    with &shape=nyc511 (below), which cuts it to the city's closures and incidents. ──
  'www.panynj.gov':               120,
  '511ny.org':                    300
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
