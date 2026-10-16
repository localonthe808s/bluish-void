#!/usr/bin/env python3
"""bake.py's driver for the rest of North America and the Caribbean (render_na.py). Writes into the SAME pyramid as the
US bake, so the client and cover.json need nothing new. Run it after bake.py has finished: blocks wholly inside the lower
48 are skipped (already baked from 3DEP); blocks that touch the border or Alaska are re-rendered from 3DEP with the
terrain tiles filling across the line.

    python3 bake_na.py --out OUT --physio physio.shp [--workers 6]

Regions: Canada + Alaska (+ the Aleutians, Ellesmere, west Greenland) to z12; the rest of Greenland to z9 (mostly ice
sheet, clear); the lower-48 box again (for its Canadian and Mexican margins) to z12; Mexico and Central America to
Panama, the Caribbean, Bermuda to z12. Resumable through na_land.txt / na_done.txt.
"""
import argparse, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shapefile
from shapely.geometry import shape, box
from shapely.ops import unary_union
import render as RD, render_na as RN
from bake import lonlat_tile

REGIONS = [((-179.9, 41.5, -52.0, 84.0), 12), ((-52.0, 59.0, -11.0, 84.0), 9), ((-125.5, 24.0, -66.5, 49.6), 12),
           ((-118.0, 7.0, -77.0, 33.0), 12), ((-85.0, 10.0, -59.0, 27.5), 12), ((-65.1, 32.1, -64.5, 32.6), 12)]

def tile_lonlat(z, x, y):
    import math
    n = 2 ** z
    return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--physio', required=True)
    ap.add_argument('--workers', type=int, default=6); A = ap.parse_args()
    us = unary_union([shape(s.shape.__geo_interface__).buffer(0) for s in shapefile.Reader(A.physio).iterShapeRecords()
                      if s.record.as_dict()['PROVINCE'].strip()]).simplify(0.02)
    inner, near = us.buffer(-0.15), us.buffer(0.3)
    ak = unary_union([box(-179.9, 51.0, -141.0, 71.6), box(-141.0, 54.4, -129.9, 60.5)])
    landf, donef = os.path.join(A.out, 'na_land.txt'), os.path.join(A.out, 'na_done.txt')
    land = set(open(landf).read().split()) if os.path.exists(landf) else set()
    done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    llog, dlog = open(landf, 'a'), open(donef, 'a')
    lock = threading.Lock(); st = {'made': 0, 'clear': 0, 'err': 0, 'skip': 0, 't0': time.time()}
    def work(z, bx, by, B):
        key = '%d/%d/%d/%d' % (z, bx, by, B)
        if key in done: return
        w, n = tile_lonlat(z, bx * B, by * B); e, s = tile_lonlat(z, bx * B + B, by * B + B)
        bb = box(w, s, e, n)
        if inner.contains(bb):                          # the US bake has it, from 3DEP
            with lock:
                st['skip'] += 1
                for i in range(B):
                    for j in range(B):
                        k = '%d/%d/%d' % (z, bx * B + i, by * B + j)
                        if k not in land: land.add(k); llog.write(k + '\n')
                done.add(key); dlog.write(key + '\n')
            return
        use3dep = near.intersects(bb) or ak.intersects(bb)
        for attempt in range(5):
            try:
                rows = list(RN.render_block(z, bx, by, B, use3dep)); break
            except Exception as ex:
                if attempt == 4:
                    with lock: st['err'] += 1
                    print('ERR', key, ex, flush=True); return
                time.sleep(6 * (attempt + 1))
        for x, y, im, has in rows:
            p = os.path.join(A.out, str(z), str(x), '%d.webp' % y)
            if im is not None:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                im.save(p, 'WEBP', quality=60, alpha_quality=60, method=4)
            with lock:
                if has:
                    k = '%d/%d/%d' % (z, x, y)
                    if k not in land: land.add(k); llog.write(k + '\n')
                st['made' if im is not None else 'clear'] += 1
        with lock: done.add(key); dlog.write(key + '\n'); dlog.flush(); llog.flush()
    for bxx, maxz in REGIONS:
        x0, y1 = lonlat_tile(bxx[0], bxx[1], 5); x1, y0 = lonlat_tile(bxx[2], bxx[3], 5)
        need = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
        for z in range(5, maxz + 1):
            B = 1 if z < 7 else 4
            blocks = sorted({(x // B, y // B) for x, y in need})
            with ThreadPoolExecutor(A.workers) as ex:
                list(ex.map(lambda b: work(z, b[0], b[1], B), blocks))
            print('%s z%d: %d tiles in %d blocks | made %d clear %d skip %d err %d | %.0f min' % (bxx, z, len(need), len(blocks), st['made'], st['clear'], st['skip'], st['err'], (time.time() - st['t0']) / 60), flush=True)
            if z == maxz: break
            bx0, by1 = lonlat_tile(bxx[0], bxx[1], z + 1); bx1, by0 = lonlat_tile(bxx[2], bxx[3], z + 1)
            need = {(2 * x + dx, 2 * y + dy) for x, y in need if '%d/%d/%d' % (z, x, y) in land for dx in (0, 1) for dy in (0, 1)}
            need = {(x, y) for x, y in need if bx0 <= x <= bx1 and by0 <= y <= by1}
main() if __name__ == '__main__' else None
