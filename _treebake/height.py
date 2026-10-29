#!/usr/bin/env python3
"""HOW TALL THE TREES ARE (user 2026-10-29, TREES improvements "do them all - start with 1 2 3"). Meta & WRI High Resolution Canopy Height
(Tolan et al. 2024, CC BY 4.0, s3://dataforgood-fb-data/forests/v1): canopy height from 1 m imagery, here its 10-degree aggregates
(alsgedi_global_v6_float_epsg4326_v3_10deg/*_avg.tif: mean height in CENTIMETRES per 0.00025 deg cell, ~28 m; 65535 = no data).
Cut to web-mercator palette PNGs for the lower 48, z11 (~58 m a pixel at 40 N) down to z3: palette index = height in whole metres
(0-63), so the page reads the height back from a pixel's color. Below 3 m (lawns, fields, shrubs) is clear.
    python3 height.py SRC_DIR OUT"""
import glob, math, os, re, sys
import numpy as np, rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from PIL import Image
Z = 11; BL = 16; RES = 0.0005
W0, S0, E0, N0 = -125.0, 24.3, -66.8, 49.5
STOPS = [(3, (229, 245, 192)), (8, (181, 223, 138)), (14, (116, 196, 118)), (20, (49, 163, 84)), (27, (17, 130, 59)), (35, (0, 100, 50)), (48, (11, 61, 44)), (63, (6, 40, 30))]
def palette():
    pal = np.zeros((256, 3), np.int32)
    for m in range(3, 64):
        for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
            if a <= m <= b: f = (m - a) / (b - a); pal[m] = [round(ca[i] + (cb[i] - ca[i]) * f) for i in range(3)]; break
    seen = set()
    for m in range(3, 64):   # every height its own color, so a tap can read it back
        c = tuple(pal[m])
        while c in seen: c = (c[0], c[1], (c[2] + 1) % 256)
        pal[m] = c; seen.add(c)
    return pal
def tx(lo, z): return (lo + 180) / 360 * 2 ** z
def ty(la, z): r = math.radians(la); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z
def lat_of(y, z): return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z))))
def main(src, out):
    files = {}
    for p in glob.glob(os.path.join(src, '*_avg.tif')):
        m = re.search(r'lat=(-?[\d.]+)_lon=(-?[\d.]+)_avg', p); files[(float(m.group(1)), float(m.group(2)))] = rasterio.open(p)
    pal = palette(); flat = []; [flat.extend(int(v) for v in pal[i]) for i in range(256)]
    trns = bytes([0, 0, 0] + [255] * 61 + [0] * 192)
    def save(arr, z, x, y):
        if not (arr >= 3).any(): return 0
        d = os.path.join(out, str(z), str(x)); os.makedirs(d, exist_ok=True)
        im = Image.fromarray(arr, 'P'); im.putpalette(flat); im.save(os.path.join(d, '%d.png' % y), optimize=True, transparency=trns); return 1
    def half(a):   # mean of the 2x2 cells that hold trees; a cell stays tree-less unless 2 of 4 do
        h, w = a.shape; b = a.reshape(h // 2, 2, w // 2, 2).astype(np.float32); m = b >= 3
        n = m.sum((1, 3)); s = (b * m).sum((1, 3)); r = np.where(n >= 2, s / np.maximum(n, 1), 0)
        return np.clip(np.round(r), 0, 63).astype(np.uint8)
    bx0, bx1 = int(tx(W0, Z)) // BL, int(tx(E0, Z)) // BL + 1; by0, by1 = int(ty(N0, Z)) // BL, int(ty(S0, Z)) // BL + 1
    z7 = {}; n = 0
    for by in range(by0, by1):
        for bx in range(bx0, bx1):
            X0, Y0 = bx * BL, by * BL
            lo0, lo1 = X0 / 2 ** Z * 360 - 180, (X0 + BL) / 2 ** Z * 360 - 180
            la1, la0 = lat_of(Y0, Z), lat_of(Y0 + BL, Z)
            gw, gh = int(math.ceil((lo1 - lo0) / RES)), int(math.ceil((la1 - la0) / RES))
            grid = np.full((gh, gw), 65535, np.uint16); hit = False
            for (fla, flo), ds in files.items():   # file (lat=T, lon=L) spans lon L..L+10, lat T-10..T
                ilo0, ilo1, ila0, ila1 = max(lo0, flo), min(lo1, flo + 10), max(la0, fla - 10), min(la1, fla)
                if ilo0 >= ilo1 or ila0 >= ila1: continue
                c0, c1 = int((ilo0 - lo0) / RES), int(math.ceil((ilo1 - lo0) / RES)); r0, r1 = int((la1 - ila1) / RES), int(math.ceil((la1 - ila0) / RES))
                c1, r1 = min(c1, gw), min(r1, gh)
                if c1 <= c0 or r1 <= r0: continue
                win = from_bounds(ilo0, ila0, ilo1, ila1, ds.transform)
                grid[r0:r1, c0:c1] = ds.read(1, window=win, out_shape=(r1 - r0, c1 - c0), resampling=Resampling.nearest, boundless=True, fill_value=65535); hit = True
            if not hit: continue
            P = BL * 256; px = np.arange(P) + .5
            lon = (X0 * 256 + px) / (2 ** Z * 256) * 360 - 180
            lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (Y0 * 256 + px) / (2 ** Z * 256)))))
            cc = np.clip(((lon - lo0) / RES).astype(np.int64), 0, gw - 1); rr = np.clip(((la1 - lat) / RES).astype(np.int64), 0, gh - 1)
            v = grid[rr[:, None], cc[None, :]]
            m = np.where(v == 65535, 0, np.clip(np.round(v / 100.0), 0, 63)).astype(np.uint8); m[m < 3] = 0
            if not m.any(): continue
            lv = m
            for z in range(Z, 6, -1):
                k = 2 ** (Z - z); t = BL // k
                for j in range(t):
                    for i in range(t): n += save(lv[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256], z, X0 // k + i, Y0 // k + j)
                if z > 7: lv = half(lv)
            z7[(X0 // BL, Y0 // BL)] = lv
            print('block', bx, by, 'tiles', n, flush=True)
    # z6..z3 from the z7 tiles
    for z in range(6, 2, -1):
        nxt = {}
        for (x, y), a in z7.items():
            k = (x // 2, y // 2); big = nxt.get(k)
            if big is None: big = nxt[k] = np.zeros((512, 512), np.uint8)
            big[(y % 2) * 256:(y % 2 + 1) * 256, (x % 2) * 256:(x % 2 + 1) * 256] = a
        z7 = {}
        for (x, y), big in nxt.items(): a = half(big); n += save(a, z, x, y); z7[(x, y)] = a
    print('done', n, flush=True)
if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
