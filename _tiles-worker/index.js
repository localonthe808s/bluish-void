// bluish-tiles: serves the R2 basemap archive as cached z/x/y vector tiles. See wrangler.toml for why.
import { PMTiles, ResolvedValueCache } from 'pmtiles';
import { railRoute } from './rail.js';

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
    if (url.pathname === '/rail/v1/nyc.json') return railRoute(url, ctx, cors);   /* the LIRR's and Metro-North's trains, on their track (rail.js) */
    if (url.pathname === '/' || url.pathname === '/health') return new Response(JSON.stringify({ ok: true, archives: Object.keys(ARCHIVES) }), { headers: { 'Content-Type': 'application/json', ...cors } });
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
