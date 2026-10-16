#!/usr/bin/env python3
"""National land relief tiles (user 2026-10-16: "does the national map have topographical lidar data? it looks flat" ->
"do 2": our own bake rather than USGS's ready-made shaded relief).

Source: USGS 3DEP (elevation.nationalmap.gov 3DEPElevation ImageServer) -- the best 3DEP elevation for each spot, lidar
derived across most of the lower 48. Fetched as float32 for a BLOCK of tiles at once (B x B tiles of 256 px plus a 2 px
pad, one request), shaded with a multidirectional hillshade, and written as a transparent OVERLAY for the dark map:
sunlit slopes a thin white, shadowed slopes black, flat ground and water fully clear, so the basemap's own colors (parks,
deserts, beaches) stay and only gain shape. Vertical exaggeration grows as the zoom falls, so ranges still read at z5.
Output: 256 px WebP RGBA.
"""
import io, math, urllib.parse, urllib.request
import numpy as np, tifffile
from PIL import Image

SRC = 'https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage'
R = 6378137.0
T = 256
PAD = 2

def tile_bounds(z, x, y):
    n = 2 ** z; s = 2 * math.pi * R / n; x0 = -math.pi * R + x * s; y1 = math.pi * R - y * s
    return x0, y1 - s, x0 + s, y1

def merc_lat(ym):
    return math.degrees(math.atan(math.sinh(ym / R)))

def fetch_block(z, bx, by, B):
    """float32 elevations (m) for tiles x in [bx*B, bx*B+B), y likewise, with PAD px all round; NaN off the data"""
    x0, _, _, y1 = tile_bounds(z, bx * B, by * B)
    _, y0, x1, _ = tile_bounds(z, bx * B + B - 1, by * B + B - 1)
    px = (x1 - x0) / (B * T)
    bb = (x0 - PAD * px, y0 - PAD * px, x1 + PAD * px, y1 + PAD * px)
    n = B * T + 2 * PAD
    q = dict(bbox=','.join('%.3f' % v for v in bb), bboxSR=3857, imageSR=3857, size='%d,%d' % (n, n), format='tiff',
             pixelType='F32', interpolation='RSP_BilinearInterpolation', noData=-99999, f='image')
    req = urllib.request.Request(SRC + '?' + urllib.parse.urlencode(q), headers={'User-Agent': 'bluishvoid.com relief bake'})
    raw = urllib.request.urlopen(req, timeout=180).read()
    a = tifffile.imread(io.BytesIO(raw)).astype(np.float32)
    if a.ndim == 3: a = a[..., 0]
    a[(a < -500) | (a > 9000)] = np.nan
    return a, px, (y0 + y1) / 2

def exaggeration(z):
    # z12 x1.6 ... z5 x8: a range has to stay legible as the zoom falls and each pixel averages more ground
    return float(np.clip(1.6 * 1.26 ** (12 - z), 1.6, 8.0))

def shade(A, px, ymid, z):
    """A: padded elevation block. Returns RGBA uint8 for the unpadded block."""
    land = np.isfinite(A)
    Z = np.where(land, A, np.nan)
    # fill NaN with the nearest-ish valid value so the coast does not shade as a cliff into the sea
    if (~land).any() and land.any():
        Zf = np.where(land, A, 0.0); W = land.astype(np.float32)
        for _ in range(3):
            s = np.zeros_like(Zf); w = np.zeros_like(W)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    s += np.roll(np.roll(Zf * W, dy, 0), dx, 1); w += np.roll(np.roll(W, dy, 0), dx, 1)
            fill = np.where(w > 0, s / np.maximum(w, 1e-6), 0)
            Zf = np.where(W > 0, Zf, fill); W = np.maximum(W, (w > 0).astype(np.float32))
        Z = Zf
    else:
        Z = np.where(land, A, 0.0)
    ground = px * math.cos(math.radians(merc_lat(ymid)))      # mercator px -> metres on the ground
    gy, gx = np.gradient(Z.astype(np.float64), ground)
    ex = exaggeration(z)
    gx *= ex; gy *= ex
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)            # image rows run south, so +gy is downhill to the south
    alt = math.radians(45)
    hs = 0.0; wsum = 0.0
    for az, w in ((315, 0.50), (270, 0.20), (360, 0.20), (225, 0.10)):
        a = math.radians(az)
        hs = hs + w * (math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(a - aspect)); wsum += w
    hs = hs / wsum
    flat = math.sin(alt)
    d = (hs - flat)[PAD:-PAD, PAD:-PAD]
    ok = land[PAD:-PAD, PAD:-PAD]
    sl = slope[PAD:-PAD, PAD:-PAD]
    lit = np.clip(d / 0.25, 0, 1) ** 0.9
    dark = np.clip(-d / 0.45, 0, 1) ** 0.85
    amb = np.clip(sl / math.radians(55), 0, 1) * 0.10        # steep ground darkens a touch whichever way it faces
    a_lit = 0.20 * lit
    a_dark = np.clip(0.60 * dark + amb, 0, 0.66)
    white = a_lit > a_dark
    alpha = np.where(white, a_lit, a_dark) * ok
    rgb = np.where(white[..., None], np.array([236, 242, 255], np.float32), np.array([0, 2, 8], np.float32))
    out = np.dstack([rgb, alpha[..., None] * 255]).astype(np.uint8)
    return out, ok

def render_block(z, bx, by, B):
    """yields (x, y, image or None, has_land) for each tile of the block"""
    A, px, ymid = fetch_block(z, bx, by, B)
    rgba, ok = shade(A, px, ymid, z)
    for i in range(B):
        for j in range(B):
            sub = rgba[j * T:(j + 1) * T, i * T:(i + 1) * T]
            land = bool(ok[j * T:(j + 1) * T, i * T:(i + 1) * T].any())
            im = Image.fromarray(sub, 'RGBA') if land and sub[..., 3].max() >= 3 else None
            yield bx * B + i, by * B + j, im, land

if __name__ == '__main__':
    import sys
    z, bx, by, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    for x, y, im, land in render_block(z, bx, by, 1):
        if im: im.save(out, 'WEBP', quality=85, method=6); print('ok', out)
        else: print('empty', land)
