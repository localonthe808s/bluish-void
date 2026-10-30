#!/usr/bin/env python3
"""CROPS, OUR OWN TILES (user 2026-10-29, "do them all": CropScape's WMS was slow). USDA NASS Cropland Data Layer (public domain),
read from the Chill Icechunk store on Source Cooperative (2008-2025, EPSG:5070) at its 240 m level (30m/8x, block MODE of the 30 m
classes), cut to web-mercator palette tiles z3-9 like NLCD: cdn land/cdl/<year>/{z}/{x}/{y}.png. Palette index = CDL class code in
USDA's own colors, each nudged unique so a tap reads the class back (land/cdl/classes.json: code -> [name, rgb]).
Background, clouds and water clear. Needs Python >= 3.11 for icechunk:
    uv run --python 3.12 --with icechunk --with xarray --with zarr --with rasterio --with pillow python cdl.py OUT YEAR [YEAR...]"""
import json, math, os, sys
import numpy as np, rasterio
from rasterio.warp import reproject
from rasterio.transform import from_origin
from rasterio.enums import Resampling
from PIL import Image
Z = 9; BL = 4
W0, S0, E0, N0 = -125.0, 24.3, -66.8, 49.5
R = 6378137.0
CLEAR = {0, 81, 83, 111}
def tx(lo, z): return (lo + 180) / 360 * 2 ** z
def ty(la, z): r = math.radians(la); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z
def merc(t, z): return t / 2 ** z * 2 * math.pi * R - math.pi * R
def store():
    import icechunk, xarray as xr
    st = icechunk.s3_storage(bucket='chill', prefix='usda-cropland-data-layer/v0.1.0.icechunk', endpoint_url='https://data.source.coop', region='us-east-1', anonymous=True, force_path_style=True)
    return xr.open_zarr(icechunk.Repository.open(st).readonly_session('main').store, group='30m/8x', chunks=None)
def main(out, years):
    ds = store(); v = ds['crop_type']; names = v.attrs['class_names']; cols = v.attrs['class_colors']
    pal = np.zeros((256, 3), np.int32); seen = set(); classes = {}
    for k in sorted(int(c) for c in cols):
        h = cols[str(k)]; c = (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
        while c in seen: c = (c[0], c[1], (c[2] + 2) % 256)
        pal[k] = c; seen.add(c); classes[k] = [names[str(k)], list(c)]
    os.makedirs(out, exist_ok=True); json.dump({str(k): q for k, q in classes.items() if k not in CLEAR}, open(os.path.join(out, 'classes.json'), 'w'), separators=(',', ':'))
    flat = []; [flat.extend(int(x) for x in pal[i]) for i in range(256)]
    trns = bytes([0 if i in CLEAR else 230 for i in range(256)])
    x0, y0 = float(ds.x.values[0]) - 120, float(ds.y.values[0]) + 120
    src_T = from_origin(x0, y0, 240, 240)
    for year in years:
        a = v.sel(year=year).values.astype(np.uint8); print(year, 'read', a.shape, flush=True)
        def save(arr, z, x, y):
            if not (trns_np[arr] > 0).any(): return 0
            d = os.path.join(out, str(year), str(z), str(x)); os.makedirs(d, exist_ok=True)
            im = Image.fromarray(arr, 'P'); im.putpalette(flat); im.save(os.path.join(d, '%d.png' % y), optimize=True, transparency=trns); return 1
        trns_np = np.frombuffer(trns, np.uint8)
        bx0, bx1 = int(tx(W0, Z)) // BL, int(tx(E0, Z)) // BL + 1; by0, by1 = int(ty(N0, Z)) // BL, int(ty(S0, Z)) // BL + 1
        z7 = {}; n = 0; P = BL * 256
        for by in range(by0, by1):
            for bx in range(bx0, bx1):
                X0, Y0 = bx * BL, by * BL
                l, r_ = merc(X0, Z), merc(X0 + BL, Z); t, b = -merc(Y0, Z), -merc(Y0 + BL, Z)
                m = np.zeros((P, P), np.uint8)
                reproject(a, m, src_transform=src_T, src_crs='EPSG:5070', src_nodata=0, dst_nodata=0, dst_crs='EPSG:3857', dst_transform=from_origin(l, t, (r_ - l) / P, (t - b) / P), resampling=Resampling.nearest)
                if not (trns_np[m] > 0).any(): continue
                lv = m
                for z in range(Z, 6, -1):
                    k = 2 ** (Z - z); tt = BL // k
                    for j in range(tt):
                        for i in range(tt): n += save(lv[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256], z, X0 // k + i, Y0 // k + j)
                    if z > 7: lv = lv[::2, ::2]
                z7[(X0 // BL, Y0 // BL)] = lv
        for z in range(6, 2, -1):
            nxt = {}
            for (x, y), q in z7.items():
                k = (x // 2, y // 2); big = nxt.get(k)
                if big is None: big = nxt[k] = np.zeros((512, 512), np.uint8)
                big[(y % 2) * 256:(y % 2 + 1) * 256, (x % 2) * 256:(x % 2 + 1) * 256] = q
            z7 = {}
            for (x, y), big in nxt.items(): q = big[::2, ::2]; n += save(q, z, x, y); z7[(x, y)] = q
        print(year, 'tiles', n, flush=True)
if __name__ == '__main__':
    main(sys.argv[1], [int(y) for y in sys.argv[2:]])
