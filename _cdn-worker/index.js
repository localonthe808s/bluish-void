// A missing z/x/y tile under the routed folders becomes an empty 204 (cached a day, CORS for our origins).
// Leaflet's <img> tiles take a 204 as an error and draw their errorTileUrl, as with the 404, minus the console line;
// _bvZxyQuiet (vector tiles) reads an empty body as an empty tile. Anything that is not a tile-shaped 404 passes through.
const ALLOWED_ORIGINS = ['https://bluishvoid.com', 'https://www.bluishvoid.com', 'http://localhost:8000', 'http://localhost:3000'];
const TILE = /\/\d{1,2}\/\d+\/\d+\.(webp|png|jpg|mvt|pbf)$/;

export default {
  async fetch(request) {
    const url = new URL(request.url);
    // only a tile path keeps its miss for a day; an index (cover.json) fetched before its upload must not stick as a 404
    if (!TILE.test(url.pathname)) return fetch(request);
    const r = await fetch(request, { cf: { cacheTtlByStatus: { '404': 86400 } } });
    if (r.status !== 404) return r;
    const origin = request.headers.get('Origin') || '';
    const h = new Headers({ 'Cache-Control': 'public, max-age=86400', 'Vary': 'Origin', 'X-Tile': 'empty' });
    if (ALLOWED_ORIGINS.includes(origin)) h.set('Access-Control-Allow-Origin', origin);
    return new Response(null, { status: 204, headers: h });
  }
};
