// Cloudflare Worker: bluish-void CORS proxy
//
// Deployed at e.g. https://bluish-void-proxy.<account>.workers.dev/?url=<encoded-target>
// (later, attach a custom domain like https://proxy.bluishvoid.com/?url=...)
//
// Wraps an upstream GET request and adds CORS + caching so a browser fetched
// from bluishvoid.com can hit endpoints that don't ship Access-Control-Allow-Origin
// headers (NASA JPL CNEOS, NOAA SWPC services, GOES image timestamps, etc.).
//
// Allowlists:
//   ALLOWED_ORIGINS  — which browser origins may use this proxy
//   ALLOWED_HOSTS    — which upstream hostnames may be proxied (prevents abuse)
//
// Edge cache:
//   CF caches by request URL for 5 minutes by default. Override with ?ttl=N seconds.

const ALLOWED_ORIGINS = [
  'https://bluishvoid.com',
  'https://www.bluishvoid.com',
  'http://localhost:8000',
  'http://localhost:3000'
];

const ALLOWED_HOSTS = [
  'ssd-api.jpl.nasa.gov',
  'api.nasa.gov',
  'apod.nasa.gov',
  'services.swpc.noaa.gov',
  'slider.cira.colostate.edu',
  'satlib.cira.colostate.edu',
  'api.rss2json.com',
  'water.noaa.gov',
  'kauai.ccmc.gsfc.nasa.gov'
];

const DEFAULT_CACHE_SECONDS = 300;

export default {
  async fetch(request) {
    const reqUrl = new URL(request.url);
    const origin = request.headers.get('Origin') || '';
    const corsOrigin = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];

    const corsHeaders = {
      'Access-Control-Allow-Origin': corsOrigin,
      'Vary': 'Origin'
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          ...corsHeaders,
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Max-Age': '86400'
        }
      });
    }

    if (request.method !== 'GET') {
      return new Response('Method not allowed', { status: 405, headers: corsHeaders });
    }

    const target = reqUrl.searchParams.get('url');
    if (!target) {
      return new Response(JSON.stringify({ error: 'Missing ?url= parameter' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    let targetUrl;
    try {
      targetUrl = new URL(target);
    } catch (e) {
      return new Response(JSON.stringify({ error: 'Invalid url parameter' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    if (!ALLOWED_HOSTS.includes(targetUrl.hostname)) {
      return new Response(JSON.stringify({ error: 'Upstream host not allowed', host: targetUrl.hostname }), {
        status: 403,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const ttlParam = parseInt(reqUrl.searchParams.get('ttl') || '', 10);
    const cacheTtl = Number.isFinite(ttlParam) && ttlParam > 0 && ttlParam <= 3600 ? ttlParam : DEFAULT_CACHE_SECONDS;

    try {
      const upstream = await fetch(targetUrl.toString(), {
        cf: { cacheTtl, cacheEverything: true }
      });
      const body = await upstream.arrayBuffer();
      const contentType = upstream.headers.get('Content-Type') || 'application/json';
      return new Response(body, {
        status: upstream.status,
        headers: {
          ...corsHeaders,
          'Content-Type': contentType,
          'Cache-Control': `public, max-age=${cacheTtl}`,
          'X-Proxy-Upstream': targetUrl.hostname
        }
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: 'Upstream fetch failed', detail: String(e) }), {
        status: 502,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }
};
