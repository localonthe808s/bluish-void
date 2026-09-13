#!/usr/bin/env python3
"""Bake the CITY FLOODS overlay pyramid by driving the DEPLOYED map lab.

WHY THIS FILE EXISTS.  The recipe that produced nyc-basemap-floods*.png on
2026-09-07 was never committed.  Recovering what it did cost most of a session:
the tiles carry a radioactive-green sewage slick the lab did not emit (a
post-process, lost), and they are only ~21% opaque while a lab render is 100%.
This reconstructs both halves so it never has to be worked out again.

WHAT A FLOODS TILE IS.  A DIFFERENCE, not a render.  Two passes over the same
box -- one with the story layers on (flood + cso), one with them nulled -- and
the tile keeps only the pixels that changed.  That is why the shipped tiles are
sparse, and why they contain orange city and pale blue water: the flood polygons
are semi-transparent, so what changed is the BLEND of story over ground, not the
story alone.  The widget composites that diff back over its own basemap.

  story ON   -> A
  story OFF  -> B
  tile       = A's RGB where |A-B| is material, alpha 255; transparent elsewhere

WHICH LAYERS ARE STORY -- MEASURED, NOT ASSUMED.  flood + cso + WET.  The wet
ground (bathy/ghost_wetground.json) is what carries the pale blue; leaving it on
in both passes cancels it and the tile comes out with 2.1% pale blue against the
shipped 19.5%.  Nulling it too lands the whole profile on the shipped one:

  B-pass nulls            opaque%    slick shoulder paleblue   orange
  SHIPPED                   5.86%   18.13%   28.28%   19.50%   21.30%
  flood+cso                 4.87%   21.53%   41.36%    2.12%   32.91%
  flood+cso+wet             6.88%   15.23%   29.38%   16.64%   23.97%   <-- this one
  flood+cso+wet+ghosts      7.38%   14.20%   27.92%   15.92%   25.85%

GHOSTS ARE NOT STORY.  Adding them moves every family FURTHER from the shipped
tile, which matches index.html ("flood tiles ONLY -- the ghost water vectors
moved to the cw-gv canvas, 2026-08-31", because baked in they upscaled into
blurry dashes).  They stay on in both passes so they cancel.

THE LIME TRAP, INVERTED.  ink_pyramid_bake.py sets VIEWS.city.flood = null on
every render because the ink pyramid must not carry the stormwater layer.  This
bake is the opposite: flood is the point.  Copying that line would produce 21
empty tiles.

NEVER CALL shrink().  The ink harness strips the alpha channel -- correct there,
where every tile is flat 255, and fatal here, where transparency IS the layer.

WHY THE DEPLOYED LAB.  The PMTiles archive allows origin https://bluishvoid.com
and nothing else; a localhost copy gets no CORS header and renders nothing.
Headless Chrome hangs on this map, so it is GUI Chrome with a debugging port:

    open -na "Google Chrome" --args --remote-debugging-port=9222 \
         --user-data-dir=/tmp/bv-cdp-profile --no-first-run \
         "https://bluishvoid.com/_maplab/"

    python3 _maplab/floods_bake.py --verify          # one tile, vs the shipped one
    python3 _maplab/floods_bake.py --level 2 --out /tmp/fl_z2
    python3 _maplab/floods_bake.py --level 3 --out /tmp/fl_z3

VERIFY FIRST.  --verify bakes the sw quadrant (which holds the Gowanus Canal)
and prints its opacity fraction and colour families beside the shipped tile's.
If the method were wrong, the fastest way to find out is one tile, not 21.
"""
import argparse
import base64
import io
import json
import math
import os
import sys
import time
import urllib.request

PORT = 9222
TILEPX = 1100
# the lab's VIEWS.city box -- identical to the ink harness's mercator box
W, S, E, N = -74.3183, 40.4834, -73.6217, 40.9478
R = 6378137.0

STORY_ON = {'flood': "'bathy/flood_stormwater.json'",
            'cso':   "'bathy/cso_outfalls.json'",
            'wet':   "'bathy/ghost_wetground.json'"}
# |dR|+|dG|+|dB| below this is encoder noise, not story. 18 is MEASURED, not
# picked: swept against the shipped sw tile, it reproduces the pale blue almost
# exactly (19.89% vs 19.50%) and every higher value makes the whole profile
# worse -- pale blue overshoots to 25.6% at 30 and 30.7% at 45 while orange
# collapses from 24.7% to 9.7%.
#
#   DIFF_MIN   opaque%    slick paleblue   orange      bytes
#   SHIPPED      5.86%   18.13%   19.50%   21.30%     134934
#   18           6.89%   15.28%   19.89%   24.67%     966562
#   30           5.36%   19.64%   25.57%   16.52%     965501
#   45           4.46%   23.60%   30.73%    9.74%     964704
#
# NOTE THE BYTES COLUMN: flat at ~965 KB whatever the threshold, while opacity
# nearly halves. So this tile's 7x size over the shipped one is NOT kept noise
# -- dropping half the kept pixels does not shrink it. PIL is writing a full
# RGBA buffer unoptimised and the 2026-09-07 tiles evidently went through
# something that quantised or stripped; no pngquant/oxipng/optipng is on PATH
# here. Unresolved, and a packaging question rather than a correctness one.
DIFF_MIN = 18


def merc_y(lat):
    return R * math.log(math.tan(math.pi / 4 + lat * math.pi / 360))


def boxes(level):
    """-> [(name, w, s, e, n)] for every tile at this level."""
    if level == 1:
        return [('nyc-basemap-floods.png', W, S, E, N)]
    g = 2 if level == 2 else 4
    y0, y1 = merc_y(S), merc_y(N)
    out = []
    for r in range(g):
        for c in range(g):
            bw = W + (E - W) * c / g
            be = W + (E - W) * (c + 1) / g
            # r0 is the NORTH row, matching the shipped r{row}c{col} names
            ytop = y1 - (y1 - y0) * r / g
            ybot = y1 - (y1 - y0) * (r + 1) / g
            bs = (2 * math.atan(math.exp(ybot / R)) - math.pi / 2) * 180 / math.pi
            bn = (2 * math.atan(math.exp(ytop / R)) - math.pi / 2) * 180 / math.pi
            if level == 2:
                name = 'nyc-basemap-floods-z2-%s%s.png' % ('n' if r == 0 else 's',
                                                           'w' if c == 0 else 'e')
            else:
                name = 'nyc-basemap-floods-z3-r%dc%d.png' % (r, c)
            out.append((name, bw, bs, be, bn))
    return out


class Lab(object):
    """A CDP connection to the deployed lab tab."""

    def __init__(self):
        import websocket
        with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % PORT, timeout=10) as f:
            tabs = [t for t in json.loads(f.read().decode()) if t.get('type') == 'page']
        tab = next((t for t in tabs if '_maplab' in (t.get('url') or '')), None)
        if not tab:
            raise SystemExit('no _maplab tab on port %d -- open the deployed lab first' % PORT)
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

    def render(self, w, s, e, n, story):
        """story=True -> flood+cso on; story=False -> both nulled."""
        self.js("""(function(){
          VIEWS.city.w = %r; VIEWS.city.e = %r;
          VIEWS.city.s = %r; VIEWS.city.n = %r;
          VIEWS.city.flood = %s;
          VIEWS.city.cso   = %s;
          VIEWS.city.wet   = %s;
          renderAll(); return 1;
        })()""" % (w, e, s, n,
                   STORY_ON['flood'] if story else 'null',
                   STORY_ON['cso'] if story else 'null',
                   STORY_ON['wet'] if story else 'null'))

    def settled(self, quiet=2, poll=1.5, floor=8.0, ceiling=120.0):
        """Wait until the ink canvas stops changing. No completion event exists."""
        t0 = time.time()
        last, same = None, 0
        while time.time() - t0 < ceiling:
            time.sleep(poll)
            sig = self.js("""(function(){
              var c = document.querySelectorAll('#grid canvas')[1];
              if (!c) return '';
              var g = c.getContext('2d'), n = 0, step = 97;
              var d = g.getImageData(0, 0, c.width, c.height).data;
              for (var i = 0; i < d.length; i += 4 * step)
                n = (n * 31 + d[i] + d[i+1] * 7 + d[i+2] * 13) % 2147483647;
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

    def grab(self):
        import numpy as np
        from PIL import Image
        data = self.js("(function(){var c=document.querySelectorAll('#grid canvas')[1];"
                       "return c ? c.toDataURL('image/png') : null;})()")
        if not data:
            raise RuntimeError('no lab canvas to read')
        raw = base64.b64decode(data.split(',', 1)[1])
        return np.array(Image.open(io.BytesIO(raw)).convert('RGBA'))


def bake_tile(lab, w, s, e, n):
    """Two passes over one box -> the difference tile."""
    import numpy as np
    lab.render(w, s, e, n, story=True)
    if not lab.settled():
        print('    (A pass never settled)')
    A = lab.grab()
    lab.render(w, s, e, n, story=False)
    if not lab.settled():
        print('    (B pass never settled)')
    B = lab.grab()

    d = np.abs(A[..., :3].astype(int) - B[..., :3].astype(int)).sum(axis=2)
    keep = d >= DIFF_MIN
    out = np.zeros_like(A)
    # RGB ONLY WHERE KEPT. Writing A's colour across the whole tile and masking
    # with alpha alone costs 4-12x the file: PNG compresses the colour planes
    # regardless of alpha, so every transparent pixel still carried detailed
    # city imagery. Measured on three z2 tiles -- nw 659 KB -> 52, ne 1224 ->
    # 299, se 833 -> 215. It is also why the byte count did not move when the
    # diff threshold changed: the RGB plane was identical either way and
    # dominated. PIL's optimize=True alone changed nothing (0.94-0.99x).
    out[..., :3] = np.where(keep[..., None], A[..., :3], 0)
    out[..., 3] = np.where(keep, 255, 0).astype(np.uint8)
    return out, keep


def families(a):
    """The colour families the widget's recolour cares about."""
    import numpy as np
    Rc, Gc, Bc, Ac = (a[..., 0].astype(int), a[..., 1].astype(int),
                      a[..., 2].astype(int), a[..., 3])
    op = Ac >= 30
    tot = max(1, op.sum())
    f = {
        'opaque %': 100.0 * op.mean(),
        'slick green': 100.0 * (op & (Gc > 150) & (Bc < 70) & (Rc < 170)).sum() / tot,
        'lime shoulder': 100.0 * (op & (Gc > 128) & (Rc > 140) & (Gc > Bc + 40)).sum() / tot,
        'pale blue': 100.0 * (op & (Bc > 200) & (Rc > 120) & (Rc < 190) & (Gc > 170)).sum() / tot,
        'orange city': 100.0 * (op & (Rc > 200) & (Gc > 90) & (Gc < 200) & (Bc < 130)).sum() / tot,
    }
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--level', type=int, choices=(1, 2, 3))
    ap.add_argument('--out', help='directory for the PNGs')
    ap.add_argument('--verify', action='store_true',
                    help='bake ONE tile (sw, which holds Gowanus) and compare to the shipped one')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    from PIL import Image

    if a.verify:
        name, w, s, e, n = [b for b in boxes(2) if b[0].endswith('sw.png')][0]
        print('verify: %s  %.4f,%.4f .. %.4f,%.4f' % (name, w, s, e, n))
        lab = Lab()
        t0 = time.time()
        tile, keep = bake_tile(lab, w, s, e, n)
        print('  baked in %.0fs, %.1f%% opaque' % (time.time() - t0, 100.0 * keep.mean()))
        out = '/tmp/verify_%s' % name
        Image.fromarray(tile).save(out)
        print('  wrote %s (%d bytes)' % (out, os.path.getsize(out)))
        import numpy as np
        shipped = np.array(Image.open(name).convert('RGBA')) if os.path.exists(name) else None
        fb = families(tile)
        print('\n  %-14s %9s %9s' % ('family', 'baked', 'shipped'))
        fs = families(shipped) if shipped is not None else None
        for k in fb:
            print('  %-14s %8.2f%% %8.2f%%' % (k, fb[k], fs[k] if fs else float('nan')))
        return

    if not a.level or not a.out:
        ap.error('--level and --out are required unless --verify')
    todo = boxes(a.level)
    print('z%d: %d tiles, 2 renders each' % (a.level, len(todo)))
    if a.dry:
        for nm, w, s, e, n in todo:
            print('   %-34s %.4f,%.4f .. %.4f,%.4f' % (nm, w, s, e, n))
        return

    os.makedirs(a.out, exist_ok=True)
    lab = Lab()
    t_start = time.time()
    for i, (nm, w, s, e, n) in enumerate(todo, 1):
        path = os.path.join(a.out, nm)
        # RESUMABLE: a real tile is four figures at least; smaller is a half-write
        if os.path.exists(path) and os.path.getsize(path) > 2000:
            print('  [%2d/%d] %-34s skip (exists)' % (i, len(todo), nm))
            continue
        t0 = time.time()
        tile, keep = bake_tile(lab, w, s, e, n)
        Image.fromarray(tile).save(path, optimize=True)
        print('  [%2d/%d] %-34s %5.1f%% opaque  %7d B  %4.0fs'
              % (i, len(todo), nm, 100.0 * keep.mean(), os.path.getsize(path),
                 time.time() - t0))
    print('done in %.1f min' % ((time.time() - t_start) / 60.0))


if __name__ == '__main__':
    main()
