#!/usr/bin/env python3
"""Driver for render_sea.py: North America's seas, the Pacific to the date line and the Atlantic to 40 W, 5-80 N, z3-9,
descending only beneath tiles that hold sea floor. Resumable (sea_land.txt / sea_done.txt). Upload: rclone copy OUT
r2:bluishvoid-bg/seafloor/v1 (with cover.json via bake.py --cover).

    python3 bake_sea.py --out OUT [--workers 6] [--box W,S,E,N]

THE ATLANTIC EXTENSION (2026-10-19, user: "extend our seafloor across the whole atlantic"): the first run stopped at 40 W and
5 N, so the Main Development Region and the eastern Atlantic were flat navy. Two more boxes, baked into a new OUT and
uploaded over seafloor/v1 (tiles on the old edge come out byte-identical, every tile is shaded from its own neighbors only):
    --box -40,-10,20,80      the eastern Atlantic to Africa and Europe, the Mediterranean's west, down to 10 S
    --box -180,-10,-40,5     the strip south of 5 N across both basins (the hurricane map reaches 10 S)
then cover.json = this OUT's z8 index joined with the first bake's (bake.py --cover --merge).
"""
import argparse, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_sea as RS
from bake import lonlat_tile

BOX_US, MINZ, MAXZ = (-180.0, 5.0, -40.0, 80.0), 3, 9

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--workers', type=int, default=6); ap.add_argument('--box'); A = ap.parse_args()
    BOX = tuple(float(v) for v in A.box.split(',')) if A.box else BOX_US
    os.makedirs(A.out, exist_ok=True)
    landf, donef = os.path.join(A.out, 'sea_land.txt'), os.path.join(A.out, 'sea_done.txt')
    has = set(open(landf).read().split()) if os.path.exists(landf) else set()
    done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    hlog, dlog = open(landf, 'a'), open(donef, 'a'); lock = threading.Lock(); st = {'made': 0, 'err': 0, 't0': time.time()}
    def work(z, bx, by, B):
        key = '%d/%d/%d/%d' % (z, bx, by, B)
        if key in done: return
        for attempt in range(5):
            try: rows = list(RS.render_block(z, bx, by, B)); break
            except Exception as ex:
                if attempt == 4:
                    with lock: st['err'] += 1
                    print('ERR', key, ex, flush=True); return
                time.sleep(6 * (attempt + 1))
        for x, y, im, h in rows:
            if im is not None:
                p = os.path.join(A.out, str(z), str(x), '%d.webp' % y); os.makedirs(os.path.dirname(p), exist_ok=True)
                im.save(p, 'WEBP', quality=62, alpha_quality=62, method=4)
            with lock:
                if h:
                    k = '%d/%d/%d' % (z, x, y)
                    if k not in has: has.add(k); hlog.write(k + '\n')
                if im is not None: st['made'] += 1
        with lock: done.add(key); dlog.write(key + '\n'); dlog.flush(); hlog.flush()
    x0, y1 = lonlat_tile(BOX[0], BOX[1], MINZ); x1, y0 = lonlat_tile(BOX[2], BOX[3], MINZ)
    need = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    for z in range(MINZ, MAXZ + 1):
        B = 1 if z < 6 else 4
        blocks = sorted({(x // B, y // B) for x, y in need})
        with ThreadPoolExecutor(A.workers) as ex: list(ex.map(lambda b: work(z, b[0], b[1], B), blocks))
        print('z%d: %d tiles in %d blocks | made %d err %d | %.0f min' % (z, len(need), len(blocks), st['made'], st['err'], (time.time() - st['t0']) / 60), flush=True)
        if z == MAXZ: break
        bx0, by1 = lonlat_tile(BOX[0], BOX[1], z + 1); bx1, by0 = lonlat_tile(BOX[2], BOX[3], z + 1)
        need = {(2 * x + dx, 2 * y + dy) for x, y in need if '%d/%d/%d' % (z, x, y) in has for dx in (0, 1) for dy in (0, 1)}
        need = {(x, y) for x, y in need if bx0 <= x <= bx1 and by0 <= y <= by1}
main() if __name__ == '__main__' else None
