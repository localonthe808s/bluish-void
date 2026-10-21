#!/usr/bin/env python3
"""THE NYC FLOOD-PRONE MAP, BAKED (user 2026-10-17: "do 1-4"). THE CITY's cwFlBuild repaints the four z2 flood quadrants
(nyc-basemap-floods-z2-{nw,ne,sw,se}.png) in the browser, pixel by pixel, into a white wash and then its blue tint; the
national map (LOCAL TIDES, NYC only) needs only that tint. Same rules here, once: the stormwater lime at full strength ->
the wash; its soft "shoulder" (lime mixed into the orange grid, strength read off green) -> the wash at that strength; the
sewer slick, the old marsh and the residue -> nothing. Then CW_FL_TINT [20,160,255, x1.3, cap .8]. Output: one PNG in THE
CITY's box (lon -74.3183..-73.6217, lat 40.4834..40.9478, web mercator), for cdn geo/nyc_flood_prone_v1.png.

    python3 bake.py REPO_DIR OUT.png
"""
import sys, os
import numpy as np
from PIL import Image
def main(repo, out):
    q = {k: np.asarray(Image.open(os.path.join(repo, 'nyc-basemap-floods-z2-%s.png' % k)).convert('RGBA')).astype(np.int32) for k in ('nw', 'ne', 'sw', 'se')}
    h, w = q['nw'].shape[:2]
    a = np.zeros((2 * h, 2 * w, 4), np.int32)
    a[:h, :w] = q['nw']; a[:h, w:] = q['ne']; a[h:, :w] = q['sw']; a[h:, w:] = q['se']
    r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    slick = (g > 150) & (b < 70) & (r < 170)
    full = ~slick & (g > r + 20) & (g > b + 60)
    sh = ~slick & ~full & (r > 140) & (g > 116) & (g > b + 40)
    t = np.clip((g - 114) / 141.0, 0, 1)
    wa = np.where(full, al, np.where(sh, np.round(al * np.minimum(1, t * 2.2)), 0))
    wa = np.where(al < 30, 0, wa)
    out_a = np.minimum(255 * 0.8, wa * 1.3).round().astype(np.uint8)
    img = np.zeros((2 * h, 2 * w, 4), np.uint8); img[..., 0] = 20; img[..., 1] = 160; img[..., 2] = 255; img[..., 3] = out_a
    img[out_a == 0, :3] = 0
    Image.fromarray(img).save(out, optimize=True)
    print(img.shape, 'coverage %.3f' % (out_a > 0).mean(), os.path.getsize(out) // 1024, 'KB')
if __name__ == '__main__': main(*sys.argv[1:3])
