#!/usr/bin/env python3
"""WHERE THE OLD FOREST STANDS (user 2026-10-29: "Don't do county shapes for the old forest"). The fireshed polygons are replaced by
ORNL DAAC's 100 m map (Bruening et al. 2026, doi 10.3334/ORNLDAAC/2498): CONUS_mature_old_growth_probabilities_0100m.tif,
EPSG:6933, 5 uint8 bands 0-100, nodata 255; band 5 = the probability a pixel is old-growth forest (all land ownership, ~2022;
Tribal lands masked by the authors). Needs an Earthdata login (~/.netrc) to download.
Cut to web-mercator palette PNGs, z10 (~100 m a pixel at 45 N) down to z3: palette index = probability in whole percent, so a tap
reads it back from the pixel. Below 20% is clear; 20% -> 80%+ runs pale cyan -> deep blue, more opaque as it climbs.
    python3 oldgrowth.py SRC_TIF OUT"""
import math, os, sys
import numpy as np, rasterio
from rasterio.warp import reproject
from rasterio.transform import from_origin
from rasterio.enums import Resampling
from PIL import Image
Z = 10; BL = 8; LO = 20   # BL = 2^(Z-7): one block ends as one z7 tile
W0, S0, E0, N0 = -125.0, 24.3, -66.8, 49.5
R = 6378137.0
# BAND=4 cuts MATURE forest instead (user 2026-10-29, "do mature forest ..."): the same file's band 4, in blue beside old growth's cyan
BAND = int(os.environ.get('BAND', '5'))
def ogc(t):
    if BAND == 4: return (round(175 - 145 * t), round(195 - 115 * t), round(255 - 25 * t))   # the page's SPX.mtC
    return (round(200 - 200 * t), round(246 - 56 * t), 255)   # the page's SPX.ogC
def palette():
    pal = np.zeros((256, 3), np.int32); seen = set()
    for p in range(LO, 101):
        c = ogc(min(1.0, (p - LO) / 60.0))
        while c in seen: c = (c[0], (c[1] + 1) % 256, c[2])   # every percent its own color
        pal[p] = c; seen.add(c)
    return pal
ALPHA = bytes([0] * LO + [int(round(110 + 130 * min(1.0, (p - LO) / 60.0))) for p in range(LO, 101)] + [0] * 155)
def tx(lo, z): return (lo + 180) / 360 * 2 ** z
def ty(la, z): r = math.radians(la); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z
def merc(t, z): return t / 2 ** z * 2 * math.pi * R - math.pi * R   # tile edge -> mercator metres (x; y is flipped by the caller)
def half(a):   # the mean of the two highest of each 2x2: small stands stay visible when zoomed out without painting whole valleys
    h, w = a.shape; b = a.reshape(h // 2, 2, w // 2, 2).transpose(0, 2, 1, 3).reshape(h // 2, w // 2, 4).astype(np.int16)
    b.sort(axis=2); r = (b[:, :, 2] + b[:, :, 3]) / 2.0
    r = np.round(r).astype(np.uint8); r[r < LO] = 0; return r
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
            a = np.full((P, P), 255, np.uint8)
            reproject(rasterio.band(ds, BAND), a, src_nodata=255, dst_nodata=255, dst_crs='EPSG:3857', dst_transform=from_origin(l, t, (r_ - l) / P, (t - b) / P), resampling=Resampling.nearest)
            m = np.where(a == 255, 0, a).astype(np.uint8); m[m < LO] = 0; m[m > 100] = 100
            if not m.any(): continue
            lv = m
            for z in range(Z, 6, -1):
                k = 2 ** (Z - z); tt = BL // k
                for j in range(tt):
                    for i in range(tt): n += save(lv[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256], z, X0 // k + i, Y0 // k + j)
                if z > 7: lv = half(lv)
            z7[(X0 // BL, Y0 // BL)] = lv
            print('block', bx, by, 'tiles', n, flush=True)
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
