#!/usr/bin/env python3
"""THE LIVE REGION MAPS, BAKED (user 2026-10-23: "how can we improve those loading?" -> "do all 4").

NATIONWIDE and the 14 region pills used to draw their backdrop in the visitor's browser: a 4 MB terrain raster, ~50 vector
tiles and a 1600 px canvas render, on every first visit to a region. The result never changes between map-style edits, so
it is baked here once, from the page's OWN stitcher, and served as one JPEG per view from /radarmaps/<area>.jpg.

Run with the site on http://localhost:8000 (python3 -m http.server 8000 in the repo):
    python3 _maplab/radarmaps_bake.py
It drives the page in headless Chromium, opens each view, waits for window._staBasemap to hold the stitched map and writes
the bytes as they are. The CDN overlays (relief, seafloor, depth) send no CORS header to localhost, so the script adds one
to those responses; the live site gets its own. RE-BAKE (and bump ?v= in _NAT_MAP_V in index.html) after any change to
the continental flavour, the terrain bakes, the overlays or a region box. The page falls back to stitching if a file is missing.
"""
import asyncio, base64, os, sys, time
from playwright.async_api import async_playwright

VIEWS = ['conus', 'ne', 'se', 'gl', 'nw', 'sw', 'upms', 'loms', 'nrock', 'srock', 'splains', 'ak', 'hi', 'pr', 'gu']
AREA = {'conus': 'conus', 'ne': 'us-ne', 'se': 'us-se', 'gl': 'us-nc', 'nw': 'us-nw', 'sw': 'us-sw', 'upms': 'upper-ms',
        'loms': 'south-ms', 'nrock': 'n-rockies', 'srock': 's-rockies', 'splains': 's-plains', 'ak': 'alaska',
        'hi': 'hawaii', 'pr': 'pr', 'gu': 'guam'}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'radarmaps')

async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--force-color-profile=srgb'])
        pg = await (await b.new_context(viewport={'width': 1400, 'height': 1000})).new_page()
        async def cors(route):
            try:
                r = await route.fetch(); h = dict(r.headers); h['access-control-allow-origin'] = '*'
                await route.fulfill(response=r, headers=h)
            except Exception:
                await route.continue_()
        await pg.route(lambda u: 'cdn.bluishvoid.com/' in u and any(k in u for k in ('/relief/', '/seafloor/', '/bathy/')), cors)
        await pg.goto('http://localhost:8000/?bakemaps=1&t=%d' % time.time(), wait_until='domcontentloaded', timeout=90000)
        await pg.wait_for_timeout(15000)
        await pg.evaluate("document.getElementById('clouds-radar-widget').scrollIntoView({block:'start'}); [...document.querySelectorAll('#clouds-radar-widget > .widget-head .cw-sec')].filter(b=>/SKY/.test(b.textContent))[0].click(); 1")
        await pg.wait_for_timeout(2500)
        await pg.evaluate("var t=document.querySelector('.cira-tab[data-tab=\"goes\"]'); t&&t.click(); 1")
        await pg.wait_for_timeout(4000)
        for v in (sys.argv[1:] or VIEWS):
            key = 'nat-' + AREA[v]   # NATIONWIDE's stitch is keyed nat-conus since it is drawn at 2400 px
            await pg.evaluate("(k)=>{ if (window._staBasemap) delete window._staBasemap[k]; }", key)
            await pg.evaluate("(v)=>window._setLiveView(v)", v)
            u = None
            for _ in range(120):
                await pg.wait_for_timeout(500)
                u = await pg.evaluate("(k)=>(window._staBasemap||{})[k]||null", key)
                if u: break
            if not u or not u.startswith('data:image/jpeg'):
                print(v, 'FAILED'); continue
            raw = base64.b64decode(u.split(',', 1)[1])
            open(os.path.join(OUT, AREA[v] + '.jpg'), 'wb').write(raw)
            print(v, AREA[v], len(raw) // 1024, 'KB')
        await b.close()

asyncio.run(main())
