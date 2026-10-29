#!/usr/bin/env python3
"""HOW OLD THE FOREST IS (user 2026-10-29, "do it"). NACP Forest Age Maps at 1-km Resolution (Pan et al. 2011, ORNL DAAC
doi 10.3334/ORNLDAAC/1096): ca04_usak06_1km.tif, the age of the trees in years -- the US (with Alaska) as of 2006, Canada as of
2004; Albers, float32, nodata -9999. Needs the Earthdata login (~/.netrc) to download.
Cut to web-mercator palette PNGs z3-8 for North America: palette index = age in whole years (1-250, 250 = 250 and over), so the
page reads the age back from a pixel and turns it into the decade the forest started. Pale yellow (young) to deep red-brown (old).
    python3 forest_age.py SRC_TIF OUT"""
import math, os, sys
import numpy as np, rasterio
from rasterio.warp import reproject
from rasterio.transform import from_origin
from rasterio.enums import Resampling
from PIL import Image
Z = 8; BL = 2   # BL = 2^(Z-7): one block ends as one z7 tile
W0, S0, E0, N0 = -170.0, 24.0, -52.0, 72.0
R = 6378137.0
STOPS = [(1, (255, 245, 170)), (15, (255, 214, 90)), (40, (247, 150, 40)), (80, (215, 80, 30)), (130, (160, 30, 30)), (200, (95, 15, 25)), (250, (60, 10, 20))]   # the page's FAGE.STOPS
def palette():
    pal = np.zeros((256, 3), np.int32); seen = set()
    for m in range(1, 251):
        for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
            if a <= m <= b: f = (m - a) / (b - a); c = tuple(round(ca[i] + (cb[i] - ca[i]) * f) for i in range(3)); break
        while c in seen: c = (c[0], c[1], (c[2] + 1) % 256)   # every age its own color
        pal[m] = c; seen.add(c)
    return pal
ALPHA = bytes([0] + [225] * 250 + [0] * 5)
def tx(lo, z): return (lo + 180) / 360 * 2 ** z
def ty(la, z): r = math.radians(la); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z
def merc(t, z): return t / 2 ** z * 2 * math.pi * R - math.pi * R
def half(a):   # mean age of the forested cells of each 2x2; a cell stays empty unless 2 of 4 are forest
    h, w = a.shape; b = a.reshape(h // 2, 2, w // 2, 2).astype(np.float32); m = b > 0
    n = m.sum((1, 3)); s = (b * m).sum((1, 3)); r = np.where(n >= 2, s / np.maximum(n, 1), 0)
    return np.clip(np.round(r), 0, 250).astype(np.uint8)
def main(src, out):
    pal = palette(); flat = []; [flat.extend(int(v) for v in pal[i]) for i in range(256)]
    def save(arr, z, x, y):
        if not arr.any(): return 0
        d = os.path.join(out, str(z), str(x)); os.makedirs(d, exist_ok=True)
        im = Image.fromarray(arr, 'P'); im.putpalette(flat); im.save(os.path.join(d, '%d.png' % y), optimize=True, transparency=ALPHA); return 1
    ds = rasterio.open(src)
    bx0, bx1 = int(tx(W0, Z)) // BL, int(tx(E0, Z)) // BL + 1; by0, by1 = int(ty(N0, Z)) // BL, int(ty(S0, Z)) // BL + 1
    z7 = {}; n = 0; P = BL * 256
    for by in range(by0, by1):
        for bx in range(bx0, bx1):
            X0, Y0 = bx * BL, by * BL
            l, r_ = merc(X0, Z), merc(X0 + BL, Z); t, b = -merc(Y0, Z), -merc(Y0 + BL, Z)
            a = np.full((P, P), -9999, np.float32)
            reproject(rasterio.band(ds, 1), a, src_nodata=-9999, dst_nodata=-9999, dst_crs='EPSG:3857', dst_transform=from_origin(l, t, (r_ - l) / P, (t - b) / P), resampling=Resampling.nearest)
            m = np.where(a > 0, np.clip(np.round(a), 1, 250), 0).astype(np.uint8)
            if not m.any(): continue
            lv = m
            for z in range(Z, 6, -1):
                k = 2 ** (Z - z); tt = BL // k
                for j in range(tt):
                    for i in range(tt): n += save(lv[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256], z, X0 // k + i, Y0 // k + j)
                if z > 7: lv = half(lv)
            z7[(X0 // BL, Y0 // BL)] = lv
        print('row', by, 'tiles', n, flush=True)
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
