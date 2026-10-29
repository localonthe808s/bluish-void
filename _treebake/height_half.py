#!/usr/bin/env python3
"""Fetch one Meta canopy-height 10-degree tile, keep it at half resolution (0.0005 deg, ~55 m: the mean of the 2x2 cells
that hold a height), delete the original. For Canada and Mexico, where the full tiles (~15 GB) do not fit on disk.
    python3 height_half.py TMP_DIR OUT_DIR LAT LON"""
import os, subprocess, sys
import numpy as np, rasterio
from rasterio.transform import Affine
B = 'https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float_epsg4326_v3_10deg/'
def main(tmp, out, la, lo):
    nm = 'meta_chm_lat=%.1f_lon=%.1f_avg.tif' % (float(la), float(lo)); dst = os.path.join(out, nm)
    if os.path.exists(dst): return
    src = os.path.join(tmp, nm)
    subprocess.run(['curl', '-s', '--retry', '5', '-C', '-', '-o', src, B + nm], check=True)
    with rasterio.open(src) as r:
        H, W = r.height // 2, r.width // 2; T = r.transform * Affine.scale(2)
        prof = dict(driver='GTiff', dtype='uint16', width=W, height=H, count=1, crs=r.crs, transform=T, compress='lzw', tiled=True, blockxsize=512, blockysize=512)
        with rasterio.open(dst + '.part', 'w', **prof) as o:
            S = 1024
            for y in range(0, r.height, S):
                a = r.read(1, window=((y, min(y + S, r.height)), (0, r.width))).astype(np.float32)
                h = a.shape[0] // 2; b = a[:h * 2].reshape(h, 2, W, 2); ok = b != 65535
                n = ok.sum((1, 3)); s = np.where(ok, b, 0).sum((1, 3))
                o.write(np.where(n >= 2, np.round(s / np.maximum(n, 1)), 65535).astype(np.uint16)[None], window=((y // 2, y // 2 + h), (0, W)))
    os.rename(dst + '.part', dst); os.remove(src); print('half', nm, flush=True)
if __name__ == '__main__': main(*sys.argv[1:])
