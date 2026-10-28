#!/usr/bin/env python3
"""Step 1 of the 1782 layer (then bhq1782.py): land vs water on the British Headquarters map, and its georeference.

  WORKDIR/bhq_full.jpg   NYPL stitch on Wikimedia Commons (Stevens_Facsimile_of_British_Headquarters_Map_of_New_York.jpg, 28582 x 12132)
  WORKDIR/thumb.png      Map Warper 13702's thumbnail (mapwarper.net/uploads/13702/thumb/1787_map.png, 100 x 44)
  WORKDIR/gcps_all.json  Map Warper 13702's control points (api/v1/maps/13702/gcps -- ten)

Writes land_r4.npy, ochre_r4.npy (the map at 1/4, ~4 m a pixel) and georef_affine.npy (full-image pixel -> local metres, see bhq1782.py).

  Georeference: Map Warper's image is not downloadable without an account, so its thumbnail is matched to this stitch (scale x, y and offset,
  Nelder-Mead on the correlation of a blurred 1/8 copy; 0.91) and the control points carried over; two more were set by eye in the north
  (Jeffrey's Hook, Mill Rock) where all ten were missing. Affine, leave-one-out median 67 m / worst 238 m; against shores that have not moved
  since (the Washington Heights cliffs, the Upper East Side) the 1782 shore sits a median ~110-120 m off.
  Land: ink or texture (local s.d. > 9 or grey < 182), the tan shore wash excluded; the mounting seams (columns / rows inked right across the
  sheet) are bridged from either side, closed, fields filled (holes < 60,000 px), opened; then, across each seam, land only where both sides are.
"""
import json, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage as nd
from scipy.optimize import minimize
Image.MAX_IMAGE_PIXELS = None


def georef(w):
    th = np.asarray(Image.open(os.path.join(w, 'thumb.png')).convert('L')).astype(float)
    S = nd.gaussian_filter(np.asarray(Image.open(os.path.join(w, 'bhq_full.jpg')).convert('L').reduce(8)).astype(float), 12)
    H, W = th.shape; yy, xx = np.mgrid[0:H, 0:W]
    def cost(p):
        r = nd.map_coordinates(S, [p[3] + (yy + .5) * p[1], p[2] + (xx + .5) * p[0]], order=1, mode='nearest')
        a = r - r.mean(); b = th - th.mean(); return -np.sum(a * b) / np.sqrt(np.sum(a * a) * np.sum(b * b))
    s0 = S.shape[1] / 100; best = min(([s0 * k, s0 * k, ox, oy] for k in np.linspace(.85, 1.15, 13) for ox in np.linspace(-200, 200, 9) for oy in np.linspace(-150, 150, 7)), key=cost)
    p = minimize(cost, best, method='Nelder-Mead', options={'xatol': .01, 'fatol': 1e-6, 'maxiter': 4000}).x
    k = 100 / 8992; T = [p[0] * k * 8, p[1] * k * 8, p[2] * 8, p[3] * 8]
    g = json.load(open(os.path.join(w, 'gcps_all.json')))
    X = [T[2] + q['x'] * T[0] for q in g] + [23244, 15718]; Y = [T[3] + q['y'] * T[1] for q in g] + [7373, 9075]
    lat = [float(q['lat']) for q in g] + [40.8503, 40.7797]; lon = [float(q['lon']) for q in g] + [-73.9471, -73.9418]
    X, Y, lat, lon = map(np.array, (X, Y, lat, lon))
    mx = (lon + 74) * 111320 * np.cos(np.radians(40.75)); my = (lat - 40.7) * 110540
    A = np.stack([np.ones_like(X), X / 1e4, Y / 1e4], 1)
    c = np.concatenate([np.linalg.lstsq(A, mx, rcond=None)[0], np.linalg.lstsq(A, my, rcond=None)[0]]); np.save(os.path.join(w, 'georef_affine.npy'), c)


def classify(w):
    a = np.asarray(Image.open(os.path.join(w, 'bhq_full.jpg')).reduce(4)).astype(np.float32)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]; gray = a.mean(-1)
    m = nd.uniform_filter(gray, 7); m2 = nd.uniform_filter(gray * gray, 7); sd = np.sqrt(np.maximum(m2 - m * m, 0))
    ochre = (R - B > 40) & (G - B > 20) & (gray > 140) & (gray < 222) & (sd < 14)
    ink = ((sd > 9) | (gray < 182)) & ~ochre; ink0 = (sd > 9) | (gray < 182)
    peaks = lambda f: np.where(f - nd.median_filter(f, 61) > 0.25)[0]
    cs, rs = peaks(ink.mean(0)), peaks(ink.mean(1)); Hh, W = ink.shape
    for c in cs:
        ink[:, max(0, c - 4):c + 5] = (ink[:, max(0, c - 9)] | ink[:, min(W - 1, c + 9)])[:, None]; ochre[:, max(0, c - 4):c + 5] = (ochre[:, max(0, c - 9)] & ochre[:, min(W - 1, c + 9)])[:, None]
    for r in rs:
        ink[max(0, r - 4):r + 5, :] = (ink[max(0, r - 9), :] | ink[min(Hh - 1, r + 9), :])[None, :]; ochre[max(0, r - 4):r + 5, :] = (ochre[max(0, r - 9), :] & ochre[min(Hh - 1, r + 9), :])[None, :]
    land = nd.binary_closing(ink, structure=np.ones((3, 3)), iterations=6)
    holes = nd.binary_fill_holes(land) & ~land; hl, hn = nd.label(holes); hs = nd.sum(np.ones_like(hl), hl, index=np.arange(1, hn + 1)); land |= np.r_[False, hs < 60000][hl]
    land = nd.binary_opening(land, iterations=4)
    keep = lambda L: (lambda lab, n: np.r_[False, nd.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1)) > 3000][lab])(*nd.label(L))
    land = keep(land)
    for c in cs: land[:, max(0, c - 9):c + 10] = (land[:, max(0, c - 14)] & land[:, min(W - 1, c + 14)])[:, None]
    for r in rs: land[max(0, r - 9):r + 10, :] = (land[max(0, r - 14), :] & land[min(Hh - 1, r + 14), :])[None, :]
    land = keep(land)
    np.save(os.path.join(w, 'land_r4.npy'), land); np.save(os.path.join(w, 'ochre_r4.npy'), ochre)


if __name__ == '__main__':
    georef(sys.argv[1]); classify(sys.argv[1]); print('ok')
