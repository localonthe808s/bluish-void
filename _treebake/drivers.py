#!/usr/bin/env python3
"""WHY THE FOREST WENT (user 2026-10-29: TREES improvements, "do them all - start with 1 2 3"). WRI / Google DeepMind, Global drivers of
forest loss at 1 km, 2001-2025, v1.3 (Sims et al. 2025, ERL 20 074027; CC BY 4.0; zenodo.org/records/19485190). Band 1 is the dominant
driver of the 1 km cell's tree cover loss over the whole period: 1 permanent agriculture, 2 hard commodities (mining, energy),
3 shifting cultivation, 4 logging, 5 wildfire, 6 settlements & infrastructure, 7 other natural disturbances (storms, floods,
landslides); 255 no loss. Bands 2-8 are the model's per-class scores (0-255).
Cut to web-mercator palette PNGs z2-z8 (nearest: classes are categories): OUT/{z}/{x}/{y}.png. The page reads the class back from the
palette color on tap.
    python3 drivers.py drivers_forest_loss_1km_2001_2025_v1_3.tif OUT"""
import math, os, sys
import numpy as np, rasterio
from PIL import Image
PAL = {1: (232, 163, 61), 2: (140, 90, 60), 3: (242, 209, 107), 4: (63, 158, 122), 5: (228, 87, 46), 6: (154, 163, 173), 7: (79, 163, 209)}
def main(src, out, zmax=8):
    with rasterio.open(src) as d: a = d.read(1); T = d.transform
    H, W = a.shape; print('read', a.shape, flush=True)
    has = (a >= 1) & (a <= 7)
    flat = [0] * 768; trns = bytearray(256)
    for k, c in PAL.items(): flat[k * 3:k * 3 + 3] = c; trns[k] = 255
    n = 0
    for z in range(2, zmax + 1):
        N = 2 ** z; px = np.arange(256) + .5
        for ty in range(N):
            # tile latitude span -> source rows; skip empty bands fast
            la0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / N)))); la1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + 1) / N))))
            if la1 > 84 or la0 < -56: continue
            yy = (ty * 256 + px) / (N * 256); lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * yy))))
            rows = np.clip(((lat - T.f) / T.e).astype(np.int64), 0, H - 1)
            r0, r1 = rows.min(), rows.max() + 1
            if not has[r0:r1].any(): continue
            for tx in range(N):
                lon = (tx * 256 + px) / (N * 256) * 360 - 180
                cols = np.clip(((lon - T.c) / T.a).astype(np.int64), 0, W - 1)
                if not has[r0:r1, cols.min():cols.max() + 1].any(): continue
                t = a[rows[:, None], cols[None, :]]
                t = np.where((t >= 1) & (t <= 7), t, 0).astype(np.uint8)
                if not t.any(): continue
                dd = os.path.join(out, str(z), str(tx)); os.makedirs(dd, exist_ok=True)
                im = Image.fromarray(t, 'P'); im.putpalette(flat); im.save(os.path.join(dd, '%d.png' % ty), optimize=True, transparency=bytes(trns)); n += 1
        print('z', z, 'tiles so far', n, flush=True)
if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
