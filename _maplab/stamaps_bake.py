#!/usr/bin/env python3
"""EVERY STATION'S NEAREST MAP, BAKED (2026-10-24, user: "what about the nearest").

NEAREST draws the continental flavour over the LOCAL map's relief, coastal depth and seafloor tiles with the archive's town
names on top (_stitchLocalBM in index.html). In the browser that is ~4 s of vector drawing, ~3 s of names and ~50 tile
requests on every first visit, so every one of the 156 NEXRAD stations' maps is drawn here, by the page's own stitcher, and
served as one JPEG from cdn.bluishvoid.com/radarmaps/sta/v1/<station>.jpg (the page falls back to stitching if one is missing).

Run with the site on http://localhost:8000:
    python3 _maplab/stamaps_bake.py OUT_DIR [KOKX KDIX ...]
then upload:
    rclone copy OUT_DIR r2:bluishvoid-bg/radarmaps/sta/v1 --s3-no-check-bucket --header-upload "Cache-Control: public, max-age=604800"
RE-BAKE into a new v<N> (and bump _STA_MAP_V in index.html) after any change to the flavour, the overlays or _localBoxFor.
The CDN overlays send no CORS header to localhost, so this script adds one to those responses.
"""
import asyncio, base64, os, re, sys, time
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1]
src = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
i = src.index('var RADAR_SITES = ['); ids = re.findall(r'id:"([A-Z0-9]{4})"', src[i:src.index('];', i)])
ids = [x for x in (sys.argv[2:] or ids)]
WORKERS = 3


async def worker(p, queue, n):
    b = await p.chromium.launch()
    pg = await (await b.new_context(viewport={'width': 1200, 'height': 900})).new_page()
    async def cors(route):
        try:
            r = await route.fetch(); h = dict(r.headers); h['access-control-allow-origin'] = '*'
            await route.fulfill(response=r, headers=h)
        except Exception:
            await route.continue_()
    await pg.route(lambda u: 'cdn.bluishvoid.com/' in u and any(k in u for k in ('/relief/', '/seafloor/', '/bathy/')), cors)
    await pg.goto('http://localhost:8000/?bakemaps=1&t=%d' % time.time(), wait_until='domcontentloaded', timeout=90000)
    await pg.wait_for_timeout(12000)
    while queue:
        sid = queue.pop(0)
        out = os.path.join(OUT, sid.lower() + '.jpg')
        if os.path.exists(out): continue
        t = time.time()
        u = await pg.evaluate("""(sid) => new Promise(res => {
            var b0 = window._bvLocalBoxFor(sid), b = {}; for (var k in b0) b[k] = b0[k]; b.sid = 'bake-' + sid;
            window._stitchLocalBM(b, function(u){ res(u || null); }); setTimeout(function(){ res(null); }, 150000); })""", sid)
        if not u or not u.startswith('data:image/jpeg'):
            print(n, sid, 'FAILED', flush=True); continue
        open(out, 'wb').write(base64.b64decode(u.split(',', 1)[1]))
        print(n, sid, os.path.getsize(out) // 1024, 'KB', '%.0fs' % (time.time() - t), flush=True)
    await b.close()


async def main():
    os.makedirs(OUT, exist_ok=True)
    queue = list(ids)
    async with async_playwright() as p:
        await asyncio.gather(*[worker(p, queue, n) for n in range(WORKERS)])

asyncio.run(main())
