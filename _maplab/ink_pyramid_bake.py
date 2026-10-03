#!/usr/bin/env python3
"""Bake the CITY backdrop's deep tiles (z5, z6) by driving the DEPLOYED map lab.

WHY A HARNESS AT ALL.  The existing pyramid (z1-z4, 106 files) was captured
ad-hoc over CDP, which is why re-baking has always been painful.  This is the
reusable version: resumable, filtered to the land that matters, and it writes
the manifest the widget needs.

WHY THE DEPLOYED LAB.  The PMTiles archive allows origin https://bluishvoid.com
and nothing else -- a localhost copy of the lab gets no CORS header at all and
renders nothing.  So this drives the real page.  Headless Chrome hangs on this
map, so it is GUI Chrome with a debugging port:

    open -na "Google Chrome" --args --remote-debugging-port=9222 \
         --user-data-dir=/tmp/bv-cdp-profile --no-first-run \
         "https://bluishvoid.com/_maplab/"
    python3 _maplab/ink_pyramid_bake.py --level 6 --out /tmp/ink_z6

ONLY WHERE THERE IS CITY.  The ladder's box is the radar box -- 77.5 x 68.2 km,
most of it ocean, New Jersey and Long Island Sound.  Baking all of it at z6 is
1,024 tiles and about seven hours.  Tiles are kept only where they intersect
Brooklyn, Queens, Manhattan or the Bronx (user 2026-09-12: "just brooklyn queens
manhattan bronx need this level of clarity"), which is 386 tiles across z5+z6.
Measured: of 6,868 deep views sampled on land, 96.9% are fully covered by that
set, 3.1% mix sharp tiles with the coarse upscale at the coast, and none are
entirely coarse -- a gap falls through to the full-extent z1 image that already
sits under the composed view, never to navy.

THE BOROUGH GEOJSON RING TRAP.  In bathy/nyc_boroughs.json each borough is ONE
Polygon whose rings are SEPARATE LANDMASSES, not exterior-plus-holes: ring 0 has
almost no area and the real landmass sits in what GeoJSON calls a hole.  Read it
naively and every borough comes out near-empty, which undercounts tiles about
sevenfold.  Every ring is unioned as its own polygon here, and the areas are
asserted against the true ones at startup so this cannot regress silently.

THE LIME TRAP.  The lab draws the DEP stormwater layer by default at
"radioactive lime".  The shipped tiles contain none of it, so every render sets
VIEWS.city.flood = null first, or the whole pyramid ships with yellow blobs.
"""
import argparse
import base64
import json
import math
import os
import sys
import time
import urllib.request

import websocket                       # websocket-client; `websockets` is NOT it

HERE = os.path.dirname(os.path.abspath(__file__))
BOROS = os.path.join(HERE, 'bathy', 'nyc_boroughs.json')
LAB = 'bluishvoid.com/_maplab'
PORT = 9222
BAKE_LEVEL = 9

# the radar box the whole ladder is arithmetic on (_cityBoxCfg in index.html)
X0, Y0, X1, Y1 = -8273078, 4936445, -8195528, 5004638
TILEPX = 1100
KEEP = ('Brooklyn', 'Queens', 'Manhattan', 'Bronx')
# true land areas, km^2 -- the ring trap is silent without this check
REAL_KM2 = {'Brooklyn': 180.0, 'Queens': 281.0, 'Manhattan': 59.1,
            'Bronx': 109.0, 'Staten Island': 151.0}
R = 6378137.0


def merc(lon, lat):
    return (R * math.radians(lon),
            R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def unmerc(x, y):
    return (math.degrees(x / R),
            math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2))


def land_union():
    """-> shapely geometry of the four boroughs, in mercator metres."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    doc = json.load(open(BOROS))
    per = {}
    for ft in doc['features']:
        name = ft['properties']['name']
        rings = ft['geometry']['coordinates']
        polys = [Polygon([merc(x, y) for x, y in r]).buffer(0)
                 for r in rings if len(r) >= 4]
        per[name] = unary_union([p for p in polys if not p.is_empty])
    k = math.cos(math.radians(40.7)) ** 2          # mercator -> ground, at NYC
    for name, g in per.items():
        got = g.area * k / 1e6
        want = REAL_KM2[name]
        if abs(got - want) / want > 0.08:
            raise SystemExit(
                'borough geometry looks wrong: %s is %.1f km2, expected ~%.1f. '
                'Check the ring encoding (see the docstring).' % (name, got, want))
    return unary_union([per[b] for b in KEEP])


# THE WATERS (2026-09-27, user: "redo the rivers ... at a farther refined zoom level that promises accuracy
# for the hudson / east river / harbor / jamaica bay"). The deep levels were baked only where a tile touched
# one of the four boroughs, so the far bank of the Hudson, the middle of the Upper Bay and most of Jamaica Bay
# fell through to the 70 m/px image underneath. These boxes (w, s, e, n) name the four waters; a tile is kept
# where it meets one of them AND the clean z3 level shows water in it, both banks included.
WATERS = {
    'hudson':      [(-74.050, 40.690, -73.990, 40.760), (-74.025, 40.755, -73.925, 40.855), (-73.985, 40.850, -73.885, 40.935)],
    'east river':  [(-74.005, 40.695, -73.900, 40.805), (-73.940, 40.775, -73.775, 40.825), (-73.945, 40.795, -73.905, 40.880)],
    'harbor':      [(-74.105, 40.590, -73.990, 40.712)],
    'jamaica bay': [(-73.955, 40.545, -73.725, 40.672)],
}
WATER_MIN = 0.01          # of the tile, on the clean level


def water_grid():
    """-> (mask, W, H): the box's water from the sixteen z3 tiles in the repo (17.6 m a pixel), as a numpy bool."""
    import numpy as np
    from PIL import Image
    full = None
    for r in range(4):
        for c in range(4):
            im = Image.open(os.path.join(HERE, '..', 'nyc-basemap-ink-dry-z3-r%dc%d.png' % (r, c))).convert('RGB')
            if full is None:
                tw, th = im.size
                full = np.zeros((th * 4, tw * 4, 3), dtype='int16')
            full[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = np.asarray(im)
    rr, gg, bb = full[..., 0], full[..., 1], full[..., 2]
    return (bb > 60) & (bb > rr + 25) & (bb > gg + 8)


def tiles_for(level, min_land, waters=True, only_water=False):
    """-> [(r, c, w, s, e, n)] for every tile worth baking at this level."""
    from shapely.geometry import box as sbox
    from shapely.ops import unary_union
    land = land_union()
    grid = 2 ** (level - 1)                     # z5 -> 16, z6 -> 32, z7 -> 64
    wm = water_grid() if waters else None
    zones = unary_union([sbox(*(merc(w, s) + merc(e, n))) for bx in WATERS.values() for (w, s, e, n) in bx]) if waters else None
    out = []
    for r in range(grid):
        for c in range(grid):
            tx0 = X0 + (X1 - X0) * c / grid
            tx1 = X0 + (X1 - X0) * (c + 1) / grid
            ty1 = Y1 - (Y1 - Y0) * r / grid
            ty0 = Y1 - (Y1 - Y0) * (r + 1) / grid
            t = sbox(tx0, ty0, tx1, ty1)
            keep = level <= 4                     # z3/z4 are the whole box, every tile (they live in the repo)
            if not only_water and t.intersects(land):
                keep = not (min_land > 0 and t.intersection(land).area / t.area < min_land)
            if not keep and waters and t.intersects(zones):
                hh, ww = wm.shape
                cell = wm[int(hh * r / grid):int(hh * (r + 1) / grid), int(ww * c / grid):int(ww * (c + 1) / grid)]
                keep = cell.size > 0 and cell.mean() >= WATER_MIN
            if not keep:
                continue
            w, s = unmerc(tx0, ty0)
            e, n = unmerc(tx1, ty1)
            out.append((r, c, w, s, e, n))
    return grid, out


def shrink(path):
    """Strip the canvas PNG's dead alpha channel and re-encode. Lossless.

    toDataURL always hands back RGBA, and these tiles never use it -- measured
    across 40 baked tiles, every one had alpha flat at 255. Carrying that
    channel costs about 27% of the file for nothing: 206 MB over the set rather
    than 151, and 4.7-18.7 MB of transfer on a deep compose rather than
    3.4-13.7.

    JPEG was measured and REJECTED for these: at q95 it is LARGER than the PNG
    (934 KB vs 858 on a Midtown tile) and at q90 it saves only 1.3x while
    putting 28.8% of pixels off by more than 8 -- on flat borough orange that is
    visible ringing around every building edge and label. A vector-style map of
    large flat fields and hard edges is what PNG is for.

    A tile that genuinely uses alpha is left untouched, so this can never
    quietly flatten something that needed it.
    """
    try:
        from PIL import Image
    except ImportError:
        return None                      # PIL absent: keep the bytes as they are
    try:
        im = Image.open(path)
        if im.mode != 'RGBA':
            return None
        if im.getchannel('A').getextrema()[0] != 255:
            return None                  # real transparency -- do not touch it
        im.convert('RGB').save(path, 'PNG', optimize=True)
        return os.path.getsize(path)
    except Exception:
        return None                      # a shrink failure must never lose a tile


class Lab:
    """A CDP connection to the deployed lab tab."""

    def __init__(self):
        with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % PORT, timeout=10) as f:
            tabs = json.loads(f.read().decode())
        tab = next((t for t in tabs if t.get('type') == 'page' and LAB in (t.get('url') or '')), None)
        if not tab:
            raise SystemExit('no tab on %s -- open the lab in the debugging Chrome first' % LAB)
        # a slow tile can outrun a short timeout, and the reader dying mid-render
        # looks exactly like a failure while the page is still working
        self.ws = websocket.create_connection(tab['webSocketDebuggerUrl'],
                                              suppress_origin=True, timeout=600)
        self.n = 0

    def send(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({'id': self.n, 'method': method, 'params': params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == self.n:
                if 'error' in msg:
                    raise RuntimeError('%s: %s' % (method, msg['error']))
                return msg.get('result', {})

    def js(self, expr):
        r = self.send('Runtime.evaluate', expression=expr,
                      returnByValue=True, awaitPromise=True)
        if r.get('exceptionDetails'):
            d = r['exceptionDetails']
            raise RuntimeError((d.get('exception') or {}).get('description') or d.get('text'))
        return (r.get('result') or {}).get('value')

    def render(self, w, s, e, n):
        self.js('window.__BAKE_LEVEL = %d; 1' % BAKE_LEVEL)
        self.js("""(function(){
          VIEWS.city.flood = null;          /* the lime trap */
          VIEWS.city.cso = null;            /* THE STAIN TRAP (2026-09-27): with the outfalls on, drawSewerStain paints a
                                               near-black plume into the river at every pipe, cut square at the tile's
                                               edge. The 386 tiles of v2 carry it; the widget lifts it at compose
                                               (cwStainLift) until they are baked again. UNTESTED: not yet run. */
          if (window.__BAKE_LEVEL <= 4){ VIEWS.city.ghosts = null; VIEWS.city.wet = null; }   /* THE GHOST TRAP (2026-10-03): at
                                               z3/z4 scales the lab paints the buried streams and the old marsh in pale blue; the
                                               widget draws them as their own overlay, and the shipped z3/z4 never carried them */
          VIEWS.city.w = %r; VIEWS.city.e = %r;
          VIEWS.city.s = %r; VIEWS.city.n = %r;
          renderAll(); return 1;
        })()""" % (w, e, s, n))

    # THE CARD'S OWN CANVAS IS canvas.pannable (2026-09-27). Each card has carried six overlay canvases since
    # 09-19 (rail, traffic, tags, the sea), so '#grid canvas'[1] is a blank overlay of the FIRST card: a bake
    # with the old selector wrote 386 identical transparent tiles in twelve seconds each and reported success.
    def settled(self, quiet=2, poll=1.5, floor=6.0, ceiling=90.0):
        """Wait until the INK canvas stops changing.

        There is no completion event to hook, and a fixed sleep long enough for
        the worst tile would triple the run. So: poll a cheap signature of the
        canvas and call it done once it has not moved for `quiet` polls.
        """
        t0 = time.time()
        last, same = None, 0
        while time.time() - t0 < ceiling:
            time.sleep(poll)
            sig = self.js("""(function(){
              var c = document.querySelectorAll('#grid canvas.pannable')[1];
              if (!c) return '';
              var g = c.getContext('2d'), n = 0, step = 97;
              var d = g.getImageData(0, 0, c.width, c.height).data;
              for (var i = 0; i < d.length; i += 4 * step) n = (n * 31 + d[i] + d[i+1] * 7 + d[i+2] * 13) % 2147483647;
              return String(n);
            })()""")
            if sig and sig == last:
                same += 1
                if same >= quiet and time.time() - t0 >= floor:
                    return True
            else:
                same = 0
            last = sig
        return False

    def grab(self, path):
        data = self.js("(function(){var c=document.querySelectorAll('#grid canvas.pannable')[1];"
                       "return c ? c.toDataURL('image/png') : null;})()")
        if not data:
            raise RuntimeError('no INK canvas to read')
        raw = base64.b64decode(data.split(',', 1)[1])
        with open(path, 'wb') as f:
            f.write(raw)
        return shrink(path) or len(raw)


def main():
    ap = argparse.ArgumentParser()
    # z3 / z4 ADDED 2026-10-03 (the lidar relief re-bake): the whole box, every tile, written under the repo's own names.
    # z1 / z2 stay as captured -- at 35-70 m/px the relief does not read and they predate this harness.
    ap.add_argument('--level', type=int, required=True, choices=(3, 4, 5, 6, 7))
    ap.add_argument('--only-water', action='store_true', help='the four waters alone, not the boroughs (z7)')
    ap.add_argument('--all', action='store_true', help='with --only: any tile of the grid, not just the selected set')
    ap.add_argument('--out', required=True, help='directory for the PNGs')
    ap.add_argument('--min-land', type=float, default=0.0,
                    help='skip tiles with less than this fraction of land (0-1)')
    ap.add_argument('--limit', type=int, default=0, help='stop after N tiles (a trial run)')
    ap.add_argument('--dry', action='store_true', help='list the work and exit')
    ap.add_argument('--port', type=int, default=PORT, help='the debugging Chrome\'s port')
    ap.add_argument('--only', default='', help='bake just these tiles, "r,c r,c" (a trial)')
    a = ap.parse_args()
    globals()['PORT'] = a.port

    grid, tiles = tiles_for(a.level, a.min_land, only_water=a.only_water)
    globals()['BAKE_LEVEL'] = a.level
    if a.only:
        want = set(tuple(int(v) for v in t.split(',')) for t in a.only.split())
        if a.all:
            tiles = []
            for (r, c) in sorted(want):
                w, s = unmerc(X0 + (X1 - X0) * c / grid, Y1 - (Y1 - Y0) * (r + 1) / grid)
                e, n = unmerc(X0 + (X1 - X0) * (c + 1) / grid, Y1 - (Y1 - Y0) * r / grid)
                tiles.append((r, c, w, s, e, n))
        else:
            tiles = [t for t in tiles if (t[0], t[1]) in want]
    mpp = (X1 - X0) / grid / TILEPX
    print('z%d: %dx%d grid, %d tiles to bake, %.2f mercator m/px (%.2f ground)'
          % (a.level, grid, grid, len(tiles), mpp, mpp / 1.317))
    print('estimated %.1f hr at 20 s a tile' % (len(tiles) * 20 / 3600.0))
    if a.dry:
        for r, c, w, s, e, n in tiles[:10]:
            print('   r%dc%d  %.4f,%.4f .. %.4f,%.4f' % (r, c, w, s, e, n))
        print('   ... (%d more)' % max(0, len(tiles) - 10))
        return

    os.makedirs(a.out, exist_ok=True)
    lab = Lab()
    done, skipped, failed = [], 0, []
    t_start = time.time()
    for i, (r, c, w, s, e, n) in enumerate(tiles, 1):
        if a.limit and i > a.limit:
            break
        name = 'nyc-basemap-ink-dry-z%d-r%dc%d.png' % (a.level, r, c)        # z3/z4 share the repo's naming
        path = os.path.join(a.out, name)
        # RESUMABLE: a five-figure file is a real tile; anything smaller is a
        # half-written one from an interrupted run and gets done again.
        if os.path.exists(path) and os.path.getsize(path) > 10000:
            done.append((r, c))
            skipped += 1
            continue
        try:
            # THE SOCKET CAN DROP (2026-09-27: "Connection to remote host was lost" at tile 42 of 107, and the 65
            # after it failed on the dead socket in under a second). One drop must cost one retry, not the level.
            for attempt in (1, 2, 3):
                try:
                    lab.render(w, s, e, n)
                    ok = lab.settled()
                    size = lab.grab(path)
                    break
                except Exception as exc:
                    if attempt == 3:
                        raise
                    print('      (%s -- reconnecting, try %d)' % (str(exc)[:60], attempt + 1))
                    time.sleep(5 * attempt)
                    lab = Lab()
                    if lab.js("typeof VIEWS") != 'object':
                        lab.send('Page.reload')
                        time.sleep(25)
                        lab = Lab()
            done.append((r, c))
            el = time.time() - t_start
            left = (len(tiles) - i) * (el / max(1, i - skipped)) if i > skipped else 0
            print('  [%3d/%3d] r%dc%d  %6.1f KB%s  ~%.0f min left'
                  % (i, len(tiles), r, c, size / 1024.0,
                     '' if ok else '  (TIMED OUT, kept anyway)', left / 60))
        except Exception as exc:                     # one bad tile must not end the run
            failed.append((r, c, str(exc)[:80]))
            print('  [%3d/%3d] r%dc%d  FAILED: %s' % (i, len(tiles), r, c, str(exc)[:80]))

    # THE MANIFEST. Without it the widget re-requests every absent tile on every
    # deep compose forever -- _cityTile drops failed entries on purpose so that
    # transient failures retry, which makes a 404 permanent work, not a one-off.
    man = os.path.join(a.out, 'ink-pyramid-manifest.json')
    prev = {}
    if os.path.exists(man):
        prev = json.load(open(man))
    prev[str(a.level)] = sorted('%d,%d' % rc for rc in done)
    prev['box'] = [X0, Y0, X1, Y1]
    with open(man, 'w') as f:
        json.dump(prev, f, separators=(',', ':'))
    print('\nbaked %d, skipped %d already present, failed %d'
          % (len(done) - skipped, skipped, len(failed)))
    for r, c, why in failed:
        print('   r%dc%d %s' % (r, c, why))
    print('manifest: %s (%d tiles at z%d)' % (man, len(prev[str(a.level)]), a.level))


if __name__ == '__main__':
    main()
