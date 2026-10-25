// bluish-tiles: serves the R2 basemap archive as cached z/x/y vector tiles. See wrangler.toml for why.
import { PMTiles, ResolvedValueCache } from 'pmtiles';
import { railRoute, subwayRoute, delaysRoute } from './rail.js';

const ALLOWED_ORIGINS = ['https://bluishvoid.com', 'https://www.bluishvoid.com', 'http://localhost:8000', 'http://localhost:3000'];
const ARCHIVES = { 'bluish-basemap-20260829': 'basemap/bluish-basemap-20260829.pmtiles' };   // URL name -> R2 key (add a new build here)
const TILE = /^\/([\w.-]+)\/(\d{1,2})\/(\d+)\/(\d+)\.mvt$/;

class R2Source {
  constructor(bucket, key){ this.bucket = bucket; this.key = key; }
  getKey(){ return this.key; }
  async getBytes(offset, length, signal, etag){
    const obj = await this.bucket.get(this.key, { range: { offset, length }, onlyIf: etag ? { etagMatches: etag } : undefined });
    if (!obj || !('body' in obj)) throw new Error('R2 range miss ' + this.key);
    return { data: await obj.arrayBuffer(), etag: obj.etag };
  }
}

const shared = new ResolvedValueCache(25, undefined);   // header + directories, kept per isolate across requests
const opened = {};
function archive(env, name){
  if (!opened[name]) opened[name] = new PMTiles(new R2Source(env.BUCKET, ARCHIVES[name]), shared);
  return opened[name];
}

export default {
  async fetch(request, env, ctx){
    const origin = request.headers.get('Origin') || '';
    const cors = {
      'Access-Control-Allow-Origin': ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0],
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Vary': 'Origin'
    };
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    if (request.method !== 'GET') return new Response('GET only', { status: 405, headers: cors });
    const url = new URL(request.url);
    if (url.pathname === '/rail/v1/nyc.json') return railRoute(url, ctx, cors);
    if (url.pathname === '/subway/v1/nyc.json') return subwayRoute(url, ctx, cors);
    if (url.pathname === '/subway/v1/delays.json') return delaysRoute(url, ctx, cors);   /* measured subway delays (rail.js) */   /* the subway's trains between stations (rail.js) */   /* the LIRR's and Metro-North's trains, on their track (rail.js) */
    /* FORECAST MODEL FRAMES, CACHED (2026-10-21, user: "lets do cloudflare"). FORECASTS + MODELS reads NCEP MAG's GIFs
       (mag.ncep.noaa.gov/data/...), which answer `no-cache, private` at ~0.3 s a frame, so every visit fetched every frame
       again. MAG reuses a path for each day's run of that hour (hrrr/18/... is today's 18Z, then tomorrow's), so the page
       adds the run's date (?r=YYYYMMDDHH) and the cache keys on it: a frame of one run never changes, kept a week at the edge
       and a day in the browser. A frame not published yet (the run still coming in) is a 404 kept one minute, its key
       carrying the minute so it does not outlive that whatever TTL the zone applies. Only MAG's model image paths pass. */
    const mg = url.pathname.match(/^\/mag\/((?:gfs|nam|nam-hires|hrrr|href|nbm|gefs-mean-sprd)\/\d\d\/[A-Za-z0-9_.\-\/]{4,160}\.gif)$/);
    if (mg && !mg[1].includes('..')){
      const run = /^\d{10}$/.test(url.searchParams.get('r') || '') ? url.searchParams.get('r') : '';
      const cache = caches.default, key = new Request(url.origin + url.pathname + '?r=' + (run || 'now-' + Math.floor(Date.now() / 600000)), { method: 'GET' });
      let hit = await cache.match(key), tag = 'HIT';
      if (!hit){
        const miss = await cache.match(new Request(key.url + '&miss=' + Math.floor(Date.now() / 60000)));
        if (miss) return new Response(null, { status: 404, headers: { ...cors, 'Cache-Control': 'no-store', 'X-Mag-Cache': 'MISS-404' } });
        tag = 'MISS';
        let up = null;
        try { up = await fetch('https://mag.ncep.noaa.gov/data/' + mg[1], { headers: { 'User-Agent': 'bluishvoid.com forecast cache' } }); } catch (e) {}
        if (!up || up.status === 404 || up.status === 403){
          ctx.waitUntil(cache.put(new Request(key.url + '&miss=' + Math.floor(Date.now() / 60000)), new Response('', { status: 200, headers: { 'Cache-Control': 'public, max-age=60' } })));
          return new Response(null, { status: 404, headers: { ...cors, 'Cache-Control': 'no-store', 'X-Mag-Cache': 'MISS' } });
        }
        const ct = up.headers.get('content-type') || '';
        if (!up.ok || ct.indexOf('image') < 0) return new Response(null, { status: 502, headers: { ...cors, 'Cache-Control': 'no-store', 'X-Upstream': up.status + ' ' + ct.slice(0, 30) } });
        hit = new Response(await up.arrayBuffer(), { status: 200, headers: { 'Content-Type': 'image/gif',
          'Cache-Control': run ? 'public, max-age=86400, s-maxage=604800' : 'public, max-age=300, s-maxage=600' } });
        ctx.waitUntil(cache.put(key, hit.clone()));
      }
      hit = new Response(hit.body, hit); hit.headers.set('X-Mag-Cache', tag);
      for (const k in cors) hit.headers.set(k, cors[k]);
      return hit;
    }
    if (url.pathname === '/' || url.pathname === '/health') return new Response(JSON.stringify({ ok: true, archives: Object.keys(ARCHIVES) }), { headers: { 'Content-Type': 'application/json', ...cors } });
    /* GOES FRAMES, CACHED (2026-10-20, user: "can we cache or cloudflare these somehow so they play smoothly"). The LIVE CLOUDS
       loop reads NESDIS STAR's sector frames (cdn.star.nesdis.noaa.gov), which answer `cache-control: off` -- so every visit
       downloaded the whole loop again (6 h = 72 frames, ~64 MB at 1200 px), and their outage of 10-20 left it blank. A frame's
       name carries its UTC time and never changes, so each is kept at the edge and in the browser for a year; the directory
       listing is what changes (a frame every 5 min), so it is kept 60 s. Only the sector imagery paths are passed. */
    /* + CONUS (2026-10-24): the continental loop's fallback frames. + THE FULL DISK (2026-10-23): the satellite loop's videos are now cut from NESDIS's full-disk GeoColor, which has no
       state lines in it (_goesvid/bake.py); the GitHub runner cannot reach NESDIS, so it reads them through here too. The
       21696 px rendition (~70 MB) is not passed. */
    const gm = url.pathname.match(/^\/goes\/(GOES1[6-9])\/(ABI|GLM)\/(?:SECTOR\/([a-z]{2,4})|FD|CONUS)\/([A-Za-z0-9]{2,32})\/(\d{11}_GOES1[6-9]-(?:ABI|GLM)-(?:[a-z]{2,4}|FD|CONUS)-[A-Za-z0-9]{2,32}-\d{3,5}x\d{3,5}\.jpg)?$/);
    if (gm && gm[5] && /-21696x/.test(gm[5])) return new Response(null, { status: 404, headers: { ...cors, 'Cache-Control': 'no-store' } });
    if (gm){
      const file = gm[5] || '', listing = !file;
      /* the listing's key carries the minute: a stored copy came back with the zone's 4 h TTL in place of the 60 s asked for,
         so its freshness does not rest on the cache honouring max-age */
      const cache = caches.default, key = new Request(url.origin + url.pathname + (listing ? '?m=' + Math.floor(Date.now() / 60000) : ''), { method: 'GET' });
      let hit = await cache.match(key), tag = 'HIT';
      if (!hit){
        tag = 'MISS';
        const up = await fetch('https://cdn.star.nesdis.noaa.gov/' + gm[1] + '/' + gm[2] + (gm[3] ? '/SECTOR/' + gm[3] : url.pathname.indexOf('/CONUS/') > 0 ? '/CONUS' : '/FD') + '/' + gm[4] + '/' + file, { headers: { 'User-Agent': 'bluishvoid.com satellite loop cache' } });
        if (!up.ok) return new Response(null, { status: up.status === 404 ? 404 : 502, headers: { ...cors, 'Cache-Control': 'no-store' } });
        let body = await up.arrayBuffer();
        if (listing){
          /* the listing runs ten days back (1.7 MB for one sector); the loop's longest choice is 48 h, so the frames of the
             last 49 h are kept as bare links, the same href="<name>" the page reads */
          const names = [...new Set((new TextDecoder().decode(body).match(/href="\d{11}_[^"]+\.jpg"/g) || []).map((h) => h.slice(6, -1)))].sort();
          const t = (n) => Date.UTC(+n.slice(0, 4), 0, 1) + (+n.slice(4, 7) - 1) * 864e5 + (+n.slice(7, 9)) * 36e5 + (+n.slice(9, 11)) * 6e4;
          const t1 = names.length ? t(names[names.length - 1]) : 0;
          body = names.filter((n) => t(n) > t1 - 49 * 36e5).map((n) => '<a href="' + n + '"></a>').join('\n');
        }
        hit = new Response(body, { status: 200, headers: listing
          ? { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'public, max-age=60' }
          : { 'Content-Type': 'image/jpeg', 'Cache-Control': 'public, max-age=31536000, immutable' } });
        ctx.waitUntil(cache.put(key, hit.clone()));
      }
      hit = new Response(hit.body, hit); hit.headers.set('X-Tile-Cache', tag);
      hit.headers.set('Cache-Control', listing ? 'public, max-age=60' : 'public, max-age=31536000, immutable');   /* a cache HIT came back at 4 h */
      for (const k in cors) hit.headers.set(k, cors[k]);
      return hit;
    }
    /* HIMAWARI-9 AND METEOSAT-12, CACHED (2026-10-24, user: "add himawari and meteosat" to FORECASTS' satellites). CIRA SLIDER
       serves them keyless but without CORS, and the satellite player loads frames as crossOrigin images: the times list passes
       through here (60 s, keyed by the minute like the GOES listing) and each frame (its path carries its time) is kept a year.
       Only these two satellites, their full disks and Himawari's Japan sector, zoom 00-01. */
    /* + GOES-19, GOES-18, GK2A full disks (2026-10-25, the baked world map: _goesvid/worldbake.py stitches all five) */
    const sj = url.pathname.match(/^\/slider\/json\/(himawari|meteosat-12|goes-19|goes-18|gk2a)\/(full_disk|japan)\/([a-z0-9_.-]{2,64})\/latest_times\.json$/);
    const si = url.pathname.match(/^\/slider\/imagery\/(\d{4})\/(\d{2})\/(\d{2})\/(himawari|meteosat-12|goes-19|goes-18|gk2a)---(full_disk|japan)\/([a-z0-9_.-]{2,64})\/(\d{14})\/(0[01])\/(\d{3}_\d{3})\.png$/);
    if (sj || si){
      const listing = !!sj, cache = caches.default, key = new Request(url.origin + url.pathname + (listing ? '?m=' + Math.floor(Date.now() / 60000) : ''), { method: 'GET' });
      let hit = await cache.match(key), tag = 'HIT';
      if (!hit){
        tag = 'MISS';
        const up = await fetch('https://slider.cira.colostate.edu/data' + url.pathname.slice(7), { headers: { 'User-Agent': 'bluishvoid.com satellite loop cache' } });
        if (!up.ok) return new Response(null, { status: up.status === 404 ? 404 : 502, headers: { ...cors, 'Cache-Control': 'no-store' } });
        hit = new Response(await up.arrayBuffer(), { status: 200, headers: listing
          ? { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=60' }
          : { 'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=31536000, immutable' } });
        ctx.waitUntil(cache.put(key, hit.clone()));
      }
      hit = new Response(hit.body, hit); hit.headers.set('X-Tile-Cache', tag);
      hit.headers.set('Cache-Control', listing ? 'public, max-age=60' : 'public, max-age=31536000, immutable');
      for (const k in cors) hit.headers.set(k, cors[k]);
      return hit;
    }
    /* MACROSTRAT, CACHED (2026-10-17, user: "do ... the macrostrat caching too"): /macrostrat/carto/{z}/{x}/{y}.png passes
       through to tiles.macrostrat.org (CC-BY, credited on the page) and keeps each tile at the edge for a week -- the geologic
       map changes rarely, and their server answers in ~300 ms where our edge answers in tens. */
    const mm = url.pathname.match(/^\/macrostrat\/(carto|carto-slim)\/(\d{1,2})\/(\d+)\/(\d+)\.png$/);
    if (mm){
      const z = +mm[2], x = +mm[3], y = +mm[4];
      if (z > 18 || x >= 2 ** z || y >= 2 ** z) return new Response('bad tile', { status: 400, headers: cors });
      const cache = caches.default, key = new Request(url.origin + url.pathname, { method: 'GET' });
      let hit = await cache.match(key), tag = 'HIT';
      if (!hit){
        tag = 'MISS';
        const up = await fetch('https://tiles.macrostrat.org/' + mm[1] + '/' + z + '/' + x + '/' + y + '.png', { headers: { 'User-Agent': 'bluishvoid.com tile cache' } });
        if (!up.ok) return new Response(null, { status: up.status === 404 ? 404 : 502, headers: { ...cors, 'Cache-Control': 'public, max-age=300' } });
        hit = new Response(await up.arrayBuffer(), { status: 200, headers: { 'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=86400, s-maxage=604800' } });
        ctx.waitUntil(cache.put(key, hit.clone()));
      }
      hit = new Response(hit.body, hit); hit.headers.set('X-Tile-Cache', tag);
      for (const k in cors) hit.headers.set(k, cors[k]);
      return hit;
    }
    /* 1 M LIDAR, NATIONAL (2026-10-17, user: "add lidar 1m to the national basemap bake"). USGS 3DEP's best available
       elevation -- 1 m lidar wherever the program has flown it, which is most of the lower 48 -- rendered by its own image
       service as a hillshade (single light, NW, flat ground = 180), one 256 px tile per request, z12-17. A full national
       pyramid at those zooms is tens of millions of tiles, so the bake is LAZY: the first request for a tile fetches it
       from USGS and writes it to R2 (lidar/v1/{z}/{x}/{y}.png); every request after reads R2 through the edge cache. The
       page turns the gray into the relief layer's look (white light, black shadow, flat ground clear). */
    /* v2 (2026-10-19, user: "deploy"): format=png32. Plain png comes back as 8-bit gray with gray 253 marked transparent, so
       the brightest sunlit slopes (Santa Monica Mountains, Honolulu's ridges, the Grand Canyon's lit walls) came out as holes
       -- 104, 90 and 224 px a tile measured; png32 has none, at ~45% more bytes. v1 stays as it was for cached pages */
    const ml = url.pathname.match(/^\/lidar\/(v1|v2)\/(\d{1,2})\/(\d+)\/(\d+)\.png$/);
    if (ml){
      const ver = ml[1], z = +ml[2], x = +ml[3], y = +ml[4];
      if (z < 12 || z > 17 || x >= 2 ** z || y >= 2 ** z) return new Response('bad tile', { status: 400, headers: cors });
      const cache = caches.default, key = new Request(url.origin + url.pathname, { method: 'GET' }), rk = 'lidar/' + ver + '/' + z + '/' + x + '/' + y + '.png';
      let hit = await cache.match(key), tag = 'EDGE';
      if (!hit){
        const ob = await env.BUCKET.get(rk);
        if (ob){ tag = 'R2'; hit = new Response(ob.body, { status: 200, headers: { 'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=604800, s-maxage=2592000' } }); }
        else {
          tag = 'USGS';
          const W = 2 * Math.PI * 6378137, sz = W / 2 ** z, bb = [-W / 2 + x * sz, W / 2 - (y + 1) * sz, -W / 2 + (x + 1) * sz, W / 2 - y * sz].map((v) => v.toFixed(2)).join(',');
          const q = 'f=image&format=' + (ver === 'v2' ? 'png32' : 'png') + '&bbox=' + bb + '&bboxSR=3857&imageSR=3857&size=256,256&interpolation=RSP_BilinearInterpolation&renderingRule='
            + encodeURIComponent(JSON.stringify({ rasterFunction: 'Hillshade Gray' }));
          /* USGS turns away about one first request in three from the edge, fast (~0.4 s), and serves the same tile on
             the next try: three tries, a short backoff between */
          let buf = null, why = '';
          for (let attempt = 0; attempt < 3 && !buf; attempt++){
            if (attempt) await new Promise((r) => setTimeout(r, attempt * 400));
            try {
              const up = await fetch('https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage?' + q, { headers: { 'User-Agent': 'bluishvoid.com lidar cache' } });
              const ct = up.headers.get('content-type') || '';
              if (up.ok && ct.indexOf('image') >= 0) buf = await up.arrayBuffer(); else why = up.status + ' ' + ct.slice(0, 30);
            } catch (e) { why = String(e).slice(0, 60); }
          }
          if (!buf) return new Response(null, { status: 502, headers: { ...cors, 'Cache-Control': 'no-store', 'X-Upstream': why } });
          ctx.waitUntil(env.BUCKET.put(rk, buf, { httpMetadata: { contentType: 'image/png', cacheControl: 'public, max-age=604800' } }));
          hit = new Response(buf, { status: 200, headers: { 'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=604800, s-maxage=2592000' } });
        }
        ctx.waitUntil(cache.put(key, hit.clone()));
      }
      hit = new Response(hit.body, hit); hit.headers.set('X-Tile-Cache', tag);
      for (const k in cors) hit.headers.set(k, cors[k]);
      return hit;
    }
    const m = url.pathname.match(TILE);
    if (!m || !ARCHIVES[m[1]]) return new Response('not found', { status: 404, headers: cors });
    const z = +m[2], x = +m[3], y = +m[4];
    if (z > 22 || x >= 2 ** z || y >= 2 ** z) return new Response('bad tile', { status: 400, headers: cors });

    // one cache entry per tile, origin-free (the CORS header is added on the way out)
    const cache = caches.default, key = new Request(url.origin + url.pathname, { method: 'GET' });
    let hit = await cache.match(key);
    if (!hit){
      const p = archive(env, m[1]);
      const hdr = await p.getHeader();
      let body = null, status = 204;
      if (z >= hdr.minZoom && z <= hdr.maxZoom){
        const t = await p.getZxy(z, x, y);
        if (t && t.data && t.data.byteLength){ body = t.data; status = 200; }
      }
      hit = new Response(body, { status, headers: {
        'Content-Type': 'application/x-protobuf',
        'Cache-Control': 'public, max-age=86400, s-maxage=31536000, immutable'
      } });
      ctx.waitUntil(cache.put(key, hit.clone()));
      hit = new Response(hit.body, hit);
      hit.headers.set('X-Tile-Cache', 'MISS');
    } else {
      hit = new Response(hit.body, hit);
      hit.headers.set('X-Tile-Cache', 'HIT');
    }
    for (const k in cors) hit.headers.set(k, cors[k]);
    return hit;
  }
};
