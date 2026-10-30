#!/usr/bin/env python3
"""LAND COVER PAST THE BORDER (user 2026-10-29, "do them all": "LAND COVER and CROPS stop at the US border"). The CEC's North American
Land Change Monitoring System, 2020 v2 (30 m, Landsat; Canada and Mexico 2020, the lower 48 2019, Alaska 2021; CEC terms: free with
credit). Read from the file's own 240 m overview (OVERVIEW_LEVEL=2, 8x), cut to web-mercator palette tiles z3-9 for Canada, Mexico and
Alaska -- the lower 48 is masked out, where the page keeps USGS Annual NLCD and its years on top. Palette index = NALCMS class 1-19;
each class drawn in its NLCD twin's color, so one key reads across the border (each nudged to be unique, for the tap). Water clear.
    NE=.../ne_50m_admin_0_countries.shp python3 nalcms.py SRC_TIF OUT"""
import math, os, sys
import numpy as np, rasterio
from rasterio.warp import reproject
from rasterio.transform import from_origin
from rasterio.enums import Resampling
from rasterio.features import rasterize
from PIL import Image
Z = 9; BL = 4   # one block = one z7 tile
W0, S0, E0, N0 = -170.0, 14.0, -52.0, 72.0
R = 6378137.0
# NALCMS class -> its NLCD twin's color (the page's LND.NA keeps the names)
TWIN = {1: '#1c5f2c', 2: '#1c5f2c', 3: '#1c5f2c', 4: '#68ab5f', 5: '#68ab5f', 6: '#b5c58f', 7: '#ccb879', 8: '#ccb879', 9: '#dfdfc2', 10: '#dfdfc2',
        11: '#ccb879', 12: '#dfdfc2', 13: '#b3ac9f', 14: '#b8d9eb', 15: '#ab6c28', 16: '#b3ac9f', 17: '#eb0000', 19: '#d1def8'}
def palette():
    pal = np.zeros((256, 3), np.int32); seen = set()
    for k, h in sorted(TWIN.items()):
        c = (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
        while c in seen: c = (c[0], c[1], (c[2] + 3) % 256)
        pal[k] = c; seen.add(c)
    return pal
def tx(lo, z): return (lo + 180) / 360 * 2 ** z
def ty(la, z): r = math.radians(la); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z
def merc(t, z): return t / 2 ** z * 2 * math.pi * R - math.pi * R
def lower48():
    import shapefile
    from shapely.geometry import shape, MultiPolygon
    from shapely.ops import transform as stransform
    from pyproj import Transformer
    r = shapefile.Reader(os.environ['NE']); i = [f[0] for f in r.fields[1:]].index('ADM0_A3')
    g = [shape(sr.shape.__geo_interface__) for sr in r.shapeRecords() if sr.record[i] == 'USA'][0]
    parts = [p for p in (g.geoms if hasattr(g, 'geoms') else [g]) if p.centroid.x > -128 and p.centroid.y < 50]
    fwd = Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True).transform
    return stransform(fwd, MultiPolygon(parts))
def main(src, out):
    pal = palette(); flat = []; [flat.extend(int(v) for v in pal[i]) for i in range(256)]
    trns = bytes([0] + [235] * 17 + [0] + [235] + [0] * 236)   # 0 and 18 (water) clear
    def save(arr, z, x, y):
        if not arr.any(): return 0
        d = os.path.join(out, str(z), str(x)); os.makedirs(d, exist_ok=True)
        im = Image.fromarray(arr, 'P'); im.putpalette(flat); im.save(os.path.join(d, '%d.png' % y), optimize=True, transparency=trns); return 1
    L48 = lower48()
    ds = rasterio.open(src, OVERVIEW_LEVEL=2)
    bx0, bx1 = int(tx(W0, Z)) // BL, int(tx(E0, Z)) // BL + 1; by0, by1 = int(ty(N0, Z)) // BL, int(ty(S0, Z)) // BL + 1
    z7 = {}; n = 0; P = BL * 256
    for by in range(by0, by1):
        for bx in range(bx0, bx1):
            X0, Y0 = bx * BL, by * BL
            l, r_ = merc(X0, Z), merc(X0 + BL, Z); t, b = -merc(Y0, Z), -merc(Y0 + BL, Z)
            T = from_origin(l, t, (r_ - l) / P, (t - b) / P)
            a = np.zeros((P, P), np.uint8)
            reproject(rasterio.band(ds, 1), a, src_nodata=127, dst_nodata=0, dst_crs='EPSG:3857', dst_transform=T, resampling=Resampling.nearest)
            a[(a > 19) | (a == 18)] = 0
            if not a.any(): continue
            m = rasterize([(L48, 1)], out_shape=a.shape, transform=T, fill=0, dtype='uint8').astype(bool); a[m] = 0
            if not a.any(): continue
            lv = a
            for z in range(Z, 6, -1):
                k = 2 ** (Z - z); tt = BL // k
                for j in range(tt):
                    for i in range(tt): n += save(lv[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256], z, X0 // k + i, Y0 // k + j)
                if z > 7: lv = lv[::2, ::2]
            z7[(X0 // BL, Y0 // BL)] = lv
        print('row', by, 'tiles', n, flush=True)
    for z in range(6, 2, -1):
        nxt = {}
        for (x, y), a in z7.items():
            k = (x // 2, y // 2); big = nxt.get(k)
            if big is None: big = nxt[k] = np.zeros((512, 512), np.uint8)
            big[(y % 2) * 256:(y % 2 + 1) * 256, (x % 2) * 256:(x % 2 + 1) * 256] = a
        z7 = {}
        for (x, y), big in nxt.items(): a = big[::2, ::2]; n += save(a, z, x, y); z7[(x, y)] = a
    print('done', n, flush=True)
if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
