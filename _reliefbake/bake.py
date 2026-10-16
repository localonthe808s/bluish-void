#!/usr/bin/env python3
"""Drive render.py over the US: level by level from z5, each level's tiles fetched in B x B blocks (one 3DEP request per
block), descending only beneath tiles that hold land. Resumable: land.txt lists every tile with land (written or clear),
done.txt every finished block; a rerun skips both.

    python3 bake.py --out OUT [--box W,S,E,N] [--maxz 12] [--workers 6]
    python3 bake.py --out OUT --cover        # cover.json: the z8 tiles holding any baked tile (the client's index)

Regions: the lower 48 to z12; Hawaii and Puerto Rico / USVI to z12; Alaska to z9.
"""
import argparse, json, math, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as RD

REGIONS = [((-125.5, 24.0, -66.5, 49.6), 12), ((-160.6, 18.5, -154.4, 22.6), 12), ((-68.2, 17.5, -64.3, 18.8), 12),
           ((-179.9, 51.0, -129.5, 71.6), 9)]

def lonlat_tile(lon, lat, z):
    n = 2 ** z; lat = max(-85, min(85, lat))
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--box'); ap.add_argument('--maxz', type=int, default=12)
    ap.add_argument('--minz', type=int, default=5); ap.add_argument('--workers', type=int, default=6); ap.add_argument('--cover', action='store_true')
    A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
    if A.cover:
        cov = set()
        for z in os.listdir(A.out):
            if not z.isdigit() or int(z) < 8: continue
            k = 2 ** (int(z) - 8)
            for x in os.listdir(os.path.join(A.out, z)):
                for f in os.listdir(os.path.join(A.out, z, x)):
                    if f.endswith('.webp'): cov.add('%d/%d' % (int(x) // k, int(f[:-5]) // k))
        json.dump(sorted(cov), open(os.path.join(A.out, 'cover.json'), 'w'), separators=(',', ':')); print('cover', len(cov)); return
    regions = [((tuple(float(v) for v in A.box.split(','))), A.maxz)] if A.box else REGIONS
    landf, donef = os.path.join(A.out, 'land.txt'), os.path.join(A.out, 'done.txt')
    land = set(open(landf).read().split()) if os.path.exists(landf) else set()
    done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    llog, dlog = open(landf, 'a'), open(donef, 'a')
    lock = threading.Lock(); st = {'made': 0, 'clear': 0, 'err': 0, 't0': time.time()}
    def work(z, bx, by, B):
        key = '%d/%d/%d/%d' % (z, bx, by, B)
        if key in done: return
        for attempt in range(5):
            try:
                rows = list(RD.render_block(z, bx, by, B)); break
            except Exception as ex:
                if attempt == 4:
                    with lock: st['err'] += 1
                    print('ERR', key, ex, flush=True); return
                time.sleep(6 * (attempt + 1))
        for x, y, im, has in rows:
            if im is not None:
                p = os.path.join(A.out, str(z), str(x), '%d.webp' % y); os.makedirs(os.path.dirname(p), exist_ok=True)
                im.save(p, 'WEBP', quality=60, alpha_quality=60, method=4)
            with lock:
                if has:
                    k = '%d/%d/%d' % (z, x, y)
                    if k not in land: land.add(k); llog.write(k + '\n')
                st['made' if im is not None else 'clear'] += 1
        with lock: done.add(key); dlog.write(key + '\n'); dlog.flush(); llog.flush()
    for box, maxz in regions:
        maxz = min(maxz, A.maxz)
        x0, y1 = lonlat_tile(box[0], box[1], A.minz); x1, y0 = lonlat_tile(box[2], box[3], A.minz)
        need = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
        for z in range(A.minz, maxz + 1):
            B = 1 if z < 7 else 4
            blocks = sorted({(x // B, y // B) for x, y in need})
            with ThreadPoolExecutor(A.workers) as ex:
                list(ex.map(lambda b: work(z, b[0], b[1], B), blocks))
            el = time.time() - st['t0']
            print('z%d: %d tiles in %d blocks | made %d clear %d err %d | %.0f min' % (z, len(need), len(blocks), st['made'], st['clear'], st['err'], el / 60), flush=True)
            if z == maxz: break
            bx0, by1 = lonlat_tile(box[0], box[1], z + 1); bx1, by0 = lonlat_tile(box[2], box[3], z + 1)
            need = {(2 * x + dx, 2 * y + dy) for x, y in need if '%d/%d/%d' % (z, x, y) in land for dx in (0, 1) for dy in (0, 1)}
            need = {(x, y) for x, y in need if bx0 <= x <= bx1 and by0 <= y <= by1}
main() if __name__ == '__main__' else None
