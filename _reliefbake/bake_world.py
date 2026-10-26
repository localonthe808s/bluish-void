#!/usr/bin/env python3
"""THE WORLD, z3 to ZMAX (2026-10-26, user: "a high quality map for the rest of the world too ... a long bake that would give
high quality resolution to the global / hemisphere views" -> "we could do this in chunks right? if we do z8 today doing z9
wouldnt take as long?"). Three pyramids from the same AWS Terrain Tiles, the same looks as North America's:

    --mode land    the land hillshade (render_na, no 3DEP)                  -> upload over relief/v1 with --ignore-existing
    --mode sea     the sea-floor hillshade (render_sea)                     -> upload over seafloor/v1 with --ignore-existing
    --mode depth   the depth tint (_bathybake's STOPS ramp on this DEM)     -> its own pyramid, bathy/world1, under bathy/v3

Each zoom descends only under tiles that held land (or sea). CHUNKS: --zmin/--zmax; a later --zmin 9 run re-walks z3-8 from the
has-file (no rendering) to find z9's tiles, and --box limits a region. Resumable: <mode>_has.txt / <mode>_done.txt in OUT.
    TT_CACHE=/Users/vvvaa/relief_bake/tt_cache python3 bake_world.py --mode land --out OUT --zmax 8 [--workers 6]
"""
import argparse, math, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import numpy as np
import mapbox_vector_tile as mvt
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as RD, render_na as RN, render_sea as RS
from bake import lonlat_tile

STOPS = [(0, (42, 92, 134)), (2, (36, 82, 124)), (5, (31, 72, 112)), (10, (27, 63, 102)), (20, (24, 55, 92)),
         (50, (21, 48, 83)), (100, (20, 44, 78)), (200, (19, 41, 74)), (1000, (17, 37, 68)), (4000, (14, 31, 60))]   # _bathybake/render.py
def ramp(d):
    ds = np.array([s[0] for s in STOPS], float); cs = np.array([s[1] for s in STOPS], float)
    ld = np.log1p(np.clip(d, 0, 6000)); lds = np.log1p(ds)
    return np.stack([np.interp(ld, lds, cs[:, c]) for c in range(3)], -1)

MVT = 'https://tiles.bluishvoid.com/bluish-basemap-20260829/{z}/{x}/{y}.mvt'
def water_mask(z, x, y, n=256):
    """the basemap's own water polygons for a tile: below sea level is not sea (the Netherlands' polders, the Caspian lowland, Death
    Valley, Qattara), so the depth tint and the sea-floor shading are cut to our map's water (_bathybake/render.py water_mask)"""
    req = urllib.request.Request(MVT.format(z=z, x=x, y=y), headers={'Origin': 'https://bluishvoid.com', 'User-Agent': 'bluish-world-bake'})
    raw = b''
    for k in range(4):
        try: raw = urllib.request.urlopen(req, timeout=60).read(); break
        except urllib.error.HTTPError as e:
            if e.code in (204, 404): break
            time.sleep(3 * (k + 1))
        except Exception: time.sleep(3 * (k + 1))
    im = Image.new('L', (n, n), 0)
    if raw:
        t = mvt.decode(raw); ext = 4096; sc = n / ext; d = ImageDraw.Draw(im)
        for f in t.get('water', {}).get('features', []):
            g = f['geometry']
            if g['type'] not in ('Polygon', 'MultiPolygon'): continue
            for poly in ([g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']):
                for i, ring in enumerate(poly):
                    pts = [(q[0] * sc, (ext - q[1]) * sc) for q in ring]
                    if len(pts) > 2: d.polygon(pts, fill=255 if i == 0 else 0)
    return np.asarray(im) > 127

def depth_block(z, bx, by, B):
    A = RS.sea_block(z, bx, by, B)[RD.PAD:-RD.PAD, RD.PAD:-RD.PAD]
    sea = np.isfinite(A) & (A < -1)
    T = RD.T; W = np.zeros_like(sea)
    for i in range(B):
        for j in range(B): W[j * T:(j + 1) * T, i * T:(i + 1) * T] = water_mask(z, bx * B + i, by * B + j, T)
    sea &= W
    rgb = ramp(np.where(sea, -A, 0))
    alpha = np.where(sea, 255, 0).astype(np.uint8)
    for i in range(B):
        for j in range(B):
            sl = (slice(j * T, (j + 1) * T), slice(i * T, (i + 1) * T)); has = bool(sea[sl].any())
            im = None
            if has:
                im = Image.fromarray(np.dstack([rgb[sl].astype(np.uint8), alpha[sl]]), 'RGBA')
                im.putalpha(im.getchannel('A').filter(ImageFilter.GaussianBlur(0.7)))
            yield bx * B + i, by * B + j, im, has

def land_exag(z): return float(np.clip(1.6 * 1.26 ** (12 - z), 1.6, 13.0))   # bake_low's curve: uncapped below z5

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--mode', required=True, choices=['land', 'sea', 'depth']); ap.add_argument('--out', required=True)
    ap.add_argument('--zmin', type=int, default=3); ap.add_argument('--zmax', type=int, default=8); ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--box', default='-180,-85,180,85'); A = ap.parse_args()
    BOX = tuple(float(v) for v in A.box.split(','))
    if A.mode == 'land': RD.exaggeration = land_exag
    def sea_masked(z, bx, by, B):
        for x, y, im, h in RS.render_block(z, bx, by, B):
            if im is not None:
                a = np.asarray(im).copy(); a[..., 3] = (a[..., 3] * water_mask(z, x, y, RD.T)).astype(np.uint8)
                im = Image.fromarray(a, 'RGBA') if a[..., 3].max() >= 3 else None
            yield x, y, im, h
    render = {'land': lambda z, bx, by, B: RN.render_block(z, bx, by, B, False), 'sea': sea_masked, 'depth': depth_block}[A.mode]
    os.makedirs(A.out, exist_ok=True)
    hasf, donef = os.path.join(A.out, A.mode + '_has.txt'), os.path.join(A.out, A.mode + '_done.txt')
    has = set(open(hasf).read().split()) if os.path.exists(hasf) else set()
    done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    hlog, dlog = open(hasf, 'a'), open(donef, 'a'); lock = threading.Lock(); st = {'made': 0, 'err': 0, 't0': time.time()}
    def work(z, bx, by, B):
        key = '%d/%d/%d/%d' % (z, bx, by, B)
        if key in done: return
        for attempt in range(5):
            try: rows = list(render(z, bx, by, B)); break
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
    z0 = min(3, A.zmin)   # --zmin 2 adds the whole-world zoom (16 tiles)
    x0, y1 = lonlat_tile(BOX[0], BOX[1], z0); x1, y0 = lonlat_tile(BOX[2] - 1e-9, BOX[3], z0)
    need = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    for z in range(z0, A.zmax + 1):
        if z >= A.zmin:
            B = 1 if z < 6 else 4
            blocks = sorted({(x // B, y // B) for x, y in need})
            with ThreadPoolExecutor(A.workers) as ex: list(ex.map(lambda b: work(z, b[0], b[1], B), blocks))
            print('%s z%d: %d tiles in %d blocks | made %d err %d | %.0f min' % (A.mode, z, len(need), len(blocks), st['made'], st['err'], (time.time() - st['t0']) / 60), flush=True)
        if z == A.zmax: break
        bx0, by1 = lonlat_tile(BOX[0], BOX[1], z + 1); bx1, by0 = lonlat_tile(BOX[2] - 1e-9, BOX[3], z + 1)
        need = {(2 * x + dx, 2 * y + dy) for x, y in need if '%d/%d/%d' % (z, x, y) in has for dx in (0, 1) for dy in (0, 1)}
        need = {(x, y) for x, y in need if bx0 <= x <= bx1 and by0 <= y <= by1}
    print('DONE', A.mode, st, flush=True)
main() if __name__ == '__main__' else None
