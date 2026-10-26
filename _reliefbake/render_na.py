#!/usr/bin/env python3
"""Relief past the US border: Canada, Alaska's full depth, Mexico, Central America, the Caribbean, Greenland (user
2026-10-16: "lets add rivers and relief for all north america and the caribbean", "dont limit yourself to those sources").

Source outside the US: the AWS open Terrain Tiles (elevation-tiles-prod, Mapzen's "terrarium" pyramid, keyless). It is
already a web-mercator pyramid on our exact tile grid, built from the best national survey per country: Canada's CDEM,
Mexico's INEGI relief, SRTM over Central America and the Caribbean, ArcticDEM in the far north, GMTED/ETOPO1 behind.
Inside the US the lidar-based 3DEP stays the source (render.py); on a block that straddles a border or a coast, 3DEP is
fetched and its gaps (Canada, Mexico) filled from the terrain tiles. The terrain tiles carry BATHYMETRY too, so anything
at or below 0 m is masked out -- the overlay stays clear over water, as before (land below sea level inside the US keeps
3DEP's value).
Same shading and output as render.py; only the elevation fetch differs.
"""
import io, math, urllib.request
import os, threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
import render as RD

TT = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/%d/%d/%d.png'
_pool = ThreadPoolExecutor(12)
CACHE = os.environ.get('TT_CACHE')

def _tile(z, x, y):
    n = 2 ** z
    if not (0 <= y < n): return None
    x %= n
    cp = os.path.join(CACHE, str(z), str(x), '%d.png' % y) if CACHE else None   # TT_CACHE: the world bake's three passes read each tile once
    if cp and os.path.exists(cp):
        try:
            a = np.asarray(Image.open(cp).convert('RGB'), np.float32); return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
        except Exception: pass
    for attempt in range(4):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(TT % (z, x, y), headers={'User-Agent': 'bluishvoid.com relief bake'}), timeout=60).read()
            if cp:
                os.makedirs(os.path.dirname(cp), exist_ok=True); tmp = cp + '.%d' % threading.get_ident(); open(tmp, 'wb').write(raw); os.replace(tmp, cp)
            a = np.asarray(Image.open(io.BytesIO(raw)).convert('RGB'), np.float32)
            return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
        except Exception:
            pass
    raise RuntimeError('terrain tile %d/%d/%d failed' % (z, x, y))

def terr_block(z, bx, by, B):
    """the block's B x B tiles plus PAD px all round, metres, NaN at/below sea level -- the same grid fetch_block returns"""
    T, P = RD.T, RD.PAD
    xs, ys = range(bx * B - 1, bx * B + B + 1), range(by * B - 1, by * B + B + 1)
    jobs = {(x, y): _pool.submit(_tile, z, x, y) for x in xs for y in ys}
    big = np.full(((B + 2) * T, (B + 2) * T), np.nan, np.float32)
    for (x, y), f in jobs.items():
        a = f.result()
        if a is not None:
            i, j = y - (by * B - 1), x - (bx * B - 1)
            big[i * T:(i + 1) * T, j * T:(j + 1) * T] = a
    out = big[T - P:T + B * T + P, T - P:T + B * T + P].copy()
    out[~(out > 0)] = np.nan                          # the sea floor and the sea surface: clear
    return out

def render_block(z, bx, by, B, use3dep):
    x0, _, _, y1 = RD.tile_bounds(z, bx * B, by * B)
    _, y0, x1, _ = RD.tile_bounds(z, bx * B + B - 1, by * B + B - 1)
    px = (x1 - x0) / (B * RD.T); ymid = (y0 + y1) / 2
    A = terr_block(z, bx, by, B)
    if use3dep:
        D, _, _ = RD.fetch_block(z, bx, by, B)
        A = np.where(np.isfinite(D), D, A)            # 3DEP wherever it has ground; the terrain tiles beyond the border
    rgba, ok = RD.shade(A, px, ymid, z)
    for i in range(B):
        for j in range(B):
            T = RD.T
            sub = rgba[j * T:(j + 1) * T, i * T:(i + 1) * T]
            land = bool(ok[j * T:(j + 1) * T, i * T:(i + 1) * T].any())
            im = Image.fromarray(sub, 'RGBA') if land and sub[..., 3].max() >= 3 else None
            yield bx * B + i, by * B + j, im, land
