// bluish-tiles: serves the R2 basemap archive as cached z/x/y vector tiles. See wrangler.toml for why.
import { PMTiles, ResolvedValueCache } from 'pmtiles';

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
    if (url.pathname === '/' || url.pathname === '/health') return new Response(JSON.stringify({ ok: true, archives: Object.keys(ARCHIVES) }), { headers: { 'Content-Type': 'application/json', ...cors } });
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
