#!/usr/bin/env python3
"""Drive render.py over the US: a quadtree from z5, descending only where a tile has water, and past z9 only over the shelf
(some water shallower than 200 m -- deeper than that the tiles match the basemap's own water, so nothing is lost by
stopping). Resumable: every tile is written as it is made, and empty ones are listed in done.txt.

    python3 bake.py --out OUT [--box W,S,E,N] [--maxz 13] [--workers 6]
    python3 bake.py --out OUT --cover [--merge OLD/cover.json]   # write cover.json: the z8 tiles that hold any baked tile
                                                                  # (the client's index), joined with an earlier bake's

Regions: the lower 48 + Great Lakes, Hawaii, Puerto Rico / USVI to z13; Alaska to z10 (its shelf alone would double the bake).

THE ATLANTIC EXTENSION (2026-10-19, user: "extend our seafloor across the whole atlantic"): --set ext bakes EXT_REGIONS into a
new OUT, with --have pointing at the first bake so its z10+ tiles stand (they are neither re-rendered nor copied):
  - the lower 48 again at z5-9 only, out to 135 W: the mosaic-hole fix (render.py) for the wide tiles, and the old box edge
    at 125.5 W (a tone step off northern California from z7) moved out to the z5 tile edge;
  - the Atlantic basin, the Gulf and the Caribbean, out to Africa and Europe, 10 S to the Arctic circle, z5-10;
  - the east Pacific storm belt south of the lower 48, z5-10.
Upload OUT over bathy/v1, with cover.json merged with the first bake's (--cover --merge).
"""
import argparse, json, math, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import render as RD

REGIONS = [((-125.5, 24.0, -66.5, 49.6), 13), ((-160.6, 18.5, -154.4, 22.6), 13), ((-68.2, 17.5, -64.3, 18.8), 13),
           ((-179.9, 51.0, -129.5, 71.6), 10)]
EXT_REGIONS = [((-135.0, 24.0, -66.5, 49.6), 9), ((-100.0, -10.0, 20.0, 66.6), 10), ((-135.0, -10.0, -100.0, 24.0), 10)]

def lonlat_tile(lon, lat, z):
    n = 2 ** z; lat = max(-85, min(85, lat))
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

def tile_lonlat_box(z, x, y):
    n = 2 ** z; lon0 = x / n * 360 - 180; lon1 = (x + 1) / n * 360 - 180
    la = lambda t: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t / n))))
    return lon0, la(y + 1), lon1, la(y)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--box'); ap.add_argument('--maxz', type=int, default=13)
    ap.add_argument('--minz', type=int, default=5); ap.add_argument('--workers', type=int, default=6); ap.add_argument('--cover', action='store_true')
    ap.add_argument('--set', choices=('us', 'ext'), default='us'); ap.add_argument('--have'); ap.add_argument('--merge')
    A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
    if A.cover:
        cov = set()
        for z in os.listdir(A.out):
            if not z.isdigit() or int(z) < 8: continue
            k = 2 ** (int(z) - 8)
            for x in os.listdir(os.path.join(A.out, z)):
                for f in os.listdir(os.path.join(A.out, z, x)):
                    if f.endswith('.webp'): cov.add('%d/%d' % (int(x) // k, int(f[:-5]) // k))
        if A.merge: cov |= set(json.load(open(A.merge)))
        json.dump(sorted(cov), open(os.path.join(A.out, 'cover.json'), 'w'), separators=(',', ':')); print('cover', len(cov)); return
    regions = [((tuple(float(v) for v in A.box.split(','))), A.maxz)] if A.box else (EXT_REGIONS if A.set == 'ext' else REGIONS)
    donef = os.path.join(A.out, 'done.txt'); done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    hdone = set()
    if A.have and os.path.exists(os.path.join(A.have, 'done.txt')):
        hdone = {k for k in open(os.path.join(A.have, 'done.txt')).read().split() if int(k.split('/')[0]) >= 10}
    lock = threading.Lock(); stats = {'made': 0, 'empty': 0, 'err': 0, 't0': time.time()}; dlog = open(donef, 'a')
    def path(z, x, y): return os.path.join(A.out, str(z), str(x), '%d.webp' % y)
    def inbox(z, x, y, box):
        w, s, e, n = tile_lonlat_box(z, x, y); return not (e < box[0] or w > box[2] or n < box[1] or s > box[3])
    def work(z, x, y):
        """returns (has_water, shelf) for the descent"""
        key = '%d/%d/%d' % (z, x, y); p = path(z, x, y)
        if key in done or key in hdone: return (False, False)
        if A.have and z >= 10:                           # the first bake's tile stands
            hp = os.path.join(A.have, str(z), str(x), '%d.webp' % y)
            if os.path.exists(hp + '.m'): return (True, open(hp + '.m').read().split()[0] == '1')
        meta = p + '.m'
        if os.path.exists(p) and os.path.exists(meta): m = open(meta).read().split(); return (True, m[0] == '1')
        for attempt in range(4):
            try:
                im, shelf = RD.render(z, x, y, want_shelf=True); break
            except Exception as ex:
                if attempt == 3:
                    with lock: stats['err'] += 1
                    print('ERR', key, ex, flush=True); return (False, False)
                time.sleep(5 * (attempt + 1))
        if im is None:
            with lock: done.add(key); dlog.write(key + '\n'); dlog.flush(); stats['empty'] += 1
            return (False, False)
        os.makedirs(os.path.dirname(p), exist_ok=True); im.save(p, 'WEBP', quality=82, method=5); open(meta, 'w').write('1' if shelf else '0')
        with lock: stats['made'] += 1
        return (True, shelf)
    for box, maxz in regions:
        maxz = min(maxz, A.maxz)
        x0, y1 = lonlat_tile(box[0], box[1], A.minz); x1, y0 = lonlat_tile(box[2], box[3], A.minz)
        level = [(A.minz, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        with ThreadPoolExecutor(A.workers) as ex:
            while level:
                z = level[0][0]
                res = list(ex.map(lambda t: (t, work(*t)), level))
                nxt = []
                for (zz, x, y), (wat, shelf) in res:
                    if not wat or zz >= maxz or (zz >= 9 and not shelf): continue
                    for dx in (0, 1):
                        for dy in (0, 1):
                            c = (zz + 1, 2 * x + dx, 2 * y + dy)
                            if inbox(*c, box): nxt.append(c)
                el = time.time() - stats['t0']
                print('z%d done: %d tiles -> next %d | made %d empty %d err %d | %.0f min' % (z, len(level), len(nxt), stats['made'], stats['empty'], stats['err'], el / 60), flush=True)
                level = nxt
main() if __name__ == '__main__' else None
