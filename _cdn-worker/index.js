// A missing z/x/y tile under the routed folders becomes an empty 204 (cached a day, CORS for our origins).
// Leaflet's <img> tiles take a 204 as an error and draw their errorTileUrl, as with the 404, minus the console line;
// _bvZxyQuiet (vector tiles) reads an empty body as an empty tile. Anything that is not tile-shaped passes through untouched.
// A TILE THAT EXISTS IS KEPT A YEAR (user 2026-10-19: "set the tiles to cache for a year"), at the edge and in the browser
// (immutable): a baked tile never changes under its address -- every re-bake ships under a new one (?b=N, a v2 folder, the
// foliage's daily ?d=date) -- so a year costs nothing and repeat visits fetch no tiles at all. Indexes (cover.json, meta.json)
// are not tile-shaped and keep the bucket's own headers.
const ALLOWED_ORIGINS = ['https://bluishvoid.com', 'https://www.bluishvoid.com', 'http://localhost:8000', 'http://localhost:3000'];
const TILE = /\/\d{1,2}\/\d+\/\d+\.(webp|png|jpg|mvt|pbf)$/;

export default {
  async fetch(request) {
    const url = new URL(request.url);
    // only a tile path keeps its miss for a day; an index (cover.json) fetched before its upload must not stick as a 404
    if (!TILE.test(url.pathname)) return fetch(request);
    const r = await fetch(request, { cf: { cacheTtlByStatus: { '200-299': 31536000, '404': 86400 } } });
    if (r.status === 200){
      const h = new Headers(r.headers);
      h.set('Cache-Control', 'public, max-age=31536000, immutable');
      return new Response(r.body, { status: 200, headers: h });
    }
    if (r.status !== 404) return r;
    const origin = request.headers.get('Origin') || '';
    const h = new Headers({ 'Cache-Control': 'public, max-age=86400', 'Vary': 'Origin', 'X-Tile': 'empty' });
    if (ALLOWED_ORIGINS.includes(origin)) h.set('Access-Control-Allow-Origin', origin);
    return new Response(null, { status: 204, headers: h });
  }
};
