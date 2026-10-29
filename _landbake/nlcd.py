#!/usr/bin/env python3
"""LAND COVER, 1985 TO 2024 (user 2026-10-29: "pull more land data" -> Annual NLCD). USGS Annual NLCD Collection 1 (public domain), the
lower 48 every year at 30 m; read here from each year's 240 m overview (Kyle Barron's Source Cooperative mirror of s3://usgs-landcover)
and cut into web-mercator tiles z3-z9 (z9 ~ 230 m at 40 N) per year: cdn land/nlcd/<year>/{z}/{x}/{y}.png, palette PNGs in USGS's own
class colors, water and no-data clear. Closer than z9 the page reads MRLC's own map service.
    python3 nlcd.py OUTDIR YEAR [YEAR...]"""
import math, os, sys
import numpy as np, rasterio
from pyproj import Transformer
from PIL import Image
SRC = '/vsicurl/https://data.source.coop/kylebarron/usgs-landcover/annual-nlcd/c1/v1/cu/mosaic/Annual_NLCD_LndCov_%d_CU_C1V1.tif'
Z = 9; W0, S0, E0, N0 = -125.0, 24.3, -66.8, 49.5
def tx(lo, z): return (lo + 180) / 360 * 2 ** z
def ty(la, z): r = math.radians(la); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z
def bake(year, out):
    with rasterio.open(SRC % year, OVERVIEW_LEVEL=2) as r:
        a = r.read(1); T = r.transform; crs = r.crs; cmap = r.colormap(1)
    print(year, 'overview', a.shape, flush=True)
    x0, x1 = int(tx(W0, Z)), int(tx(E0, Z)) + 1; y0, y1 = int(ty(N0, Z)), int(ty(S0, Z)) + 1
    PW, PH = (x1 - x0) * 256, (y1 - y0) * 256
    tr = Transformer.from_crs('EPSG:3857', crs, always_xy=True); R = 6378137.0; world = 2 ** Z * 256
    mx = (x0 * 256 + np.arange(PW) + .5) / world * 2 * math.pi * R - math.pi * R
    mos = np.zeros((PH, PW), np.uint8)
    for r0 in range(0, PH, 512):
        rr = np.arange(r0, min(PH, r0 + 512)); my = math.pi * R - (y0 * 256 + rr + .5) / world * 2 * math.pi * R
        X, Y = np.meshgrid(mx, my); ax, ay = tr.transform(X, Y)
        c = ((ax - T.c) / T.a).astype(np.int64); rw = ((ay - T.f) / T.e).astype(np.int64)
        ok = (c >= 0) & (c < a.shape[1]) & (rw >= 0) & (rw < a.shape[0])
        blk = np.zeros(X.shape, np.uint8); blk[ok] = a[rw[ok], c[ok]]; mos[r0:r0 + len(rr)] = blk
    pal = np.zeros((256, 4), np.uint8)
    for k, v in cmap.items(): pal[k] = v[:3] + (255,)
    for k in (0, 11, 12, 250): pal[k, 3] = 0 if k != 12 else 255   # water and no-data clear; snow kept
    flat = []; [flat.extend(pal[i][:3]) for i in range(256)]; trns = bytes(int(pal[i][3]) for i in range(256))
    def save(arr, z, x, y):
        if not arr.any() or not (pal[arr][..., 3] > 0).any(): return
        d = os.path.join(out, str(year), str(z), str(x)); os.makedirs(d, exist_ok=True)
        im = Image.fromarray(arr, 'P'); im.putpalette(flat); im.save(os.path.join(d, '%d.png' % y), optimize=True, transparency=trns)
    lvl = mos; n = 0
    for z in range(Z, 2, -1):
        s = 2 ** (Z - z); bx0, by0 = x0 // s, y0 // s
        if z < Z:   # halve: nearest (classes are categories), keep the tile grid aligned to the z-grid
            off_x, off_y = (x0 - bx0 * s) * 256 // s, (y0 - by0 * s) * 256 // s
            lv = mos[::s, ::s]; pad = np.zeros((lv.shape[0] + off_y + 256, lv.shape[1] + off_x + 256), np.uint8); pad[off_y:off_y + lv.shape[0], off_x:off_x + lv.shape[1]] = lv; lvl = pad
        else: lvl = mos
        for ty_ in range(lvl.shape[0] // 256):
            for tx_ in range(lvl.shape[1] // 256):
                save(lvl[ty_ * 256:(ty_ + 1) * 256, tx_ * 256:(tx_ + 1) * 256], z, bx0 + tx_, by0 + ty_); n += 1
    print(year, 'tiles', n, flush=True)
if __name__ == '__main__':
    out = sys.argv[1]
    for y in sys.argv[2:]: bake(int(y), out)
