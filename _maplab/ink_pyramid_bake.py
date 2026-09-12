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


def tiles_for(level, min_land):
    """-> [(r, c, w, s, e, n)] for every tile worth baking at this level."""
    from shapely.geometry import box as sbox
    land = land_union()
    grid = 2 ** (level - 1)                     # z5 -> 16, z6 -> 32
    out = []
    for r in range(grid):
        for c in range(grid):
            tx0 = X0 + (X1 - X0) * c / grid
            tx1 = X0 + (X1 - X0) * (c + 1) / grid
            ty1 = Y1 - (Y1 - Y0) * r / grid
            ty0 = Y1 - (Y1 - Y0) * (r + 1) / grid
            t = sbox(tx0, ty0, tx1, ty1)
            if not t.intersects(land):
                continue
            if min_land > 0 and t.intersection(land).area / t.area < min_land:
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
        self.js("""(function(){
          VIEWS.city.flood = null;          /* the lime trap */
          VIEWS.city.w = %r; VIEWS.city.e = %r;
          VIEWS.city.s = %r; VIEWS.city.n = %r;
          renderAll(); return 1;
        })()""" % (w, e, s, n))

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
              var c = document.querySelectorAll('#grid canvas')[1];
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
        data = self.js("(function(){var c=document.querySelectorAll('#grid canvas')[1];"
                       "return c ? c.toDataURL('image/png') : null;})()")
        if not data:
            raise RuntimeError('no INK canvas to read')
        raw = base64.b64decode(data.split(',', 1)[1])
        with open(path, 'wb') as f:
            f.write(raw)
        return shrink(path) or len(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--level', type=int, required=True, choices=(5, 6))
    ap.add_argument('--out', required=True, help='directory for the PNGs')
    ap.add_argument('--min-land', type=float, default=0.0,
                    help='skip tiles with less than this fraction of land (0-1)')
    ap.add_argument('--limit', type=int, default=0, help='stop after N tiles (a trial run)')
    ap.add_argument('--dry', action='store_true', help='list the work and exit')
    a = ap.parse_args()

    grid, tiles = tiles_for(a.level, a.min_land)
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
        name = 'nyc-basemap-ink-dry-z%d-r%dc%d.png' % (a.level, r, c)
        path = os.path.join(a.out, name)
        # RESUMABLE: a five-figure file is a real tile; anything smaller is a
        # half-written one from an interrupted run and gets done again.
        if os.path.exists(path) and os.path.getsize(path) > 10000:
            done.append((r, c))
            skipped += 1
            continue
        try:
            lab.render(w, s, e, n)
            ok = lab.settled()
            size = lab.grab(path)
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
