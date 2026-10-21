#!/usr/bin/env python3
"""v2 (2026-10-19): bake render.py's shaded floor again over EXACTLY the tiles an earlier bake made -- no quadtree descent,
the tile list is the union of the .webp files under the --from directories (the first bake and the Atlantic extension).
Tiles are grouped into render.block_size(z) blocks (one NOAA request per block). Resumable: written tiles are skipped,
tiles that came back empty go to empty.txt, blocks that failed after all retries go to err.txt (run again to retry them).

    python3 rebake.py --out OUT --from DIR [--from DIR ...] [--workers 6] [--zooms 5-13] [--only LIST]
"""
import argparse, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as RD

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--from', dest='src', action='append', required=True)
    ap.add_argument('--workers', type=int, default=6); ap.add_argument('--zooms', default='5-13')
    ap.add_argument('--only', help='a file of z/x/y lines: bake just those of the --from tiles (v2.1 seam re-bake)')
    A = ap.parse_args(); z0, z1 = (int(v) for v in A.zooms.split('-'))
    keys = set()
    for d in A.src:
        for z in range(z0, z1 + 1):
            zd = os.path.join(d, str(z))
            if not os.path.isdir(zd): continue
            for x in os.listdir(zd):
                if not x.isdigit(): continue
                for f in os.listdir(os.path.join(zd, x)):
                    if f.endswith('.webp'): keys.add((z, int(x), int(f[:-5])))
    if A.only:
        want = set()
        for ln in open(A.only):
            t = ln.split()
            if t: want.add(tuple(int(v) for v in t[0].replace('.webp', '').split('/')))
        keys &= want
    path = lambda z, x, y: os.path.join(A.out, str(z), str(x), '%d.webp' % y)
    os.makedirs(A.out, exist_ok=True)
    ef = os.path.join(A.out, 'empty.txt'); empty = set(open(ef).read().split()) if os.path.exists(ef) else set()
    todo = [k for k in keys if '%d/%d/%d' % k not in empty and not os.path.exists(path(*k))]
    blocks = {}
    for z, x, y in todo:
        B = RD.block_size(z); blocks.setdefault((z, x // B, y // B, B), set()).add((x, y))
    order = sorted(blocks, key=lambda b: (b[0], b[1], b[2]))
    print('tiles %d, to do %d in %d blocks' % (len(keys), len(todo), len(order)), flush=True)
    lock = threading.Lock(); st = dict(made=0, empty=0, err=0, blocks=0, t0=time.time())
    elog = open(ef, 'a'); errlog = open(os.path.join(A.out, 'err.txt'), 'a')
    def work(b):
        z, bx, by, B = b
        for attempt in range(6):
            try: res = RD.render_block(z, bx, by, B, blocks[b]); break
            except Exception as ex:
                if attempt == 5:
                    with lock: st['err'] += 1; errlog.write('%d/%d/%d/%d %s\n' % (z, bx, by, B, ex)); errlog.flush()
                    print('ERR', b, ex, flush=True); return
                time.sleep(4 * (attempt + 1) ** 2)
        for (x, y), (im, shelf) in res.items():
            if im is None:
                with lock: st['empty'] += 1; elog.write('%d/%d/%d\n' % (z, x, y)); elog.flush()
                continue
            p = path(z, x, y); os.makedirs(os.path.dirname(p), exist_ok=True)
            im.save(p + '.tmp', 'WEBP', quality=82, method=5); os.replace(p + '.tmp', p)
            with lock: st['made'] += 1
        with lock:
            st['blocks'] += 1
            if st['blocks'] % 200 == 0:
                el = time.time() - st['t0']; done = st['made'] + st['empty']
                print('z%d blocks %d/%d | made %d empty %d err %d | %.1f tiles/s | eta %.0f min' % (z, st['blocks'], len(order), st['made'], st['empty'], st['err'],
                      done / el, (len(todo) - done) / max(done / el, 1e-6) / 60), flush=True)
    with ThreadPoolExecutor(A.workers) as ex: list(ex.map(work, order))
    print('DONE made %d empty %d err %d in %.0f min' % (st['made'], st['empty'], st['err'], (time.time() - st['t0']) / 60), flush=True)
main() if __name__ == '__main__' else None
