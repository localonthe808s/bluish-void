#!/usr/bin/env python3
"""THE UNDERWATER RIVERS' COURSES. The gazetteer gives most canyons and sea channels as a single charted point. Their course
is traced here off the sea floor itself: the AWS Terrain Tiles' bathymetry at z9 (~250 m at these latitudes), a window
~2.4 deg around the point, lightly smoothed; D8 flow directions and flow accumulation (cells sorted high to low, each
handing its count downhill); the charted point snapped to the strongest channel within ~2 km; then followed DOWNSTREAM
to where the channel fades on the fan, and UPSTREAM along its largest branch to the head on the shelf edge. Simplified,
then rounded with two Chaikin passes. A trace is kept only when it runs at least 8 km -- otherwise the canyon keeps its
point. This is the canyon's thalweg as the bathymetry shows it at ~250 m, not a survey line.

    python3 trace.py names_v1.json OUT.json
"""
import json, math, sys, io, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from shapely.geometry import LineString

Z = 9; T = 256
def tile_xy(lon, lat, z):
    n = 2 ** z; return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
def xy_lonlat(x, y, z):
    n = 2 ** z; return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
pool = ThreadPoolExecutor(16)
import os
CACHE = '/Users/vvvaa/sea_bake/terr9'
def tile(x, y):
    fp = os.path.join(CACHE, '%d_%d.png' % (x % 2 ** Z, y))
    raw = open(fp, 'rb').read() if os.path.exists(fp) else None
    if raw is None:
        u = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/%d/%d/%d.png' % (Z, x % 2 ** Z, y)
        for a in range(4):
            try: raw = urllib.request.urlopen(u, timeout=60).read(); break
            except Exception: pass
        if raw is None: return np.full((T, T), np.nan, np.float32)
        os.makedirs(CACHE, exist_ok=True); open(fp, 'wb').write(raw)
    a_ = np.asarray(Image.open(io.BytesIO(raw)).convert('RGB'), np.float32)
    return a_[..., 0] * 256 + a_[..., 1] + a_[..., 2] / 256 - 32768

D8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
def trace(lon, lat):
    cx, cy = tile_xy(lon, lat, Z); r = 4                                  # 9 x 9 tiles around the point
    x0, y0 = int(cx) - r, int(cy) - r
    jobs = {(i, j): pool.submit(tile, x0 + i, y0 + j) for i in range(2 * r + 1) for j in range(2 * r + 1)}
    E = np.zeros(((2 * r + 1) * T, (2 * r + 1) * T), np.float32)
    for (i, j), f in jobs.items(): E[j * T:(j + 1) * T, i * T:(i + 1) * T] = f.result()
    E = gaussian_filter(np.nan_to_num(E, nan=0.0), 1.5)
    H, W = E.shape
    # D8: the steepest lower neighbour
    best = np.zeros((H, W), np.int8) - 1; drop = np.zeros((H, W), np.float32)
    for k, (dy, dx) in enumerate(D8):
        sh = np.full((H, W), np.inf, np.float32)
        ys = slice(max(0, dy), H + min(0, dy)); yd = slice(max(0, -dy), H + min(0, -dy))
        xs = slice(max(0, dx), W + min(0, dx)); xd = slice(max(0, -dx), W + min(0, -dx))
        sh[yd, xd] = E[ys, xs]
        d = (E - sh) / (1.4142 if dy and dx else 1.0)
        m = d > drop; best[m] = k; drop[m] = d[m]
    order = np.argsort(-E, axis=None); acc = np.ones(H * W, np.float32); bf = best.ravel()
    for idx in order:
        k = bf[idx]
        if k < 0: continue
        y, x = divmod(idx, W); dy, dx = D8[k]; acc[(y + dy) * W + x + dx] += acc[idx]
    acc = acc.reshape(H, W)
    py, px = int((cy - y0) * T), int((cx - x0) * T); rr = 8
    win = acc[max(0, py - rr):py + rr + 1, max(0, px - rr):px + rr + 1]
    j, i = np.unravel_index(np.argmax(win), win.shape); py, px = max(0, py - rr) + j, max(0, px - rr) + i
    if acc[py, px] < 60 or E[py, px] > -30: return None
    down = [(py, px)]; y, x = py, px
    seen = {(py, px)}
    for _ in range(6000):
        k = best[y, x]
        if k < 0:                                                         # a hollow in the data: hop to the lowest lower cell within ~4 km
            R = 16; y0_, x0_ = max(0, y - R), max(0, x - R); sub = E[y0_:y + R + 1, x0_:x + R + 1]
            j, i = np.unravel_index(np.argmin(sub), sub.shape)
            if sub[j, i] >= E[y, x] - 0.5: break
            ty, tx = y0_ + j, x0_ + i
            n_ = max(abs(ty - y), abs(tx - x))
            for s_ in range(1, n_ + 1): down.append((y + round((ty - y) * s_ / n_), x + round((tx - x) * s_ / n_)))
            y, x = ty, tx
        else:
            dy, dx = D8[k]; y, x = y + dy, x + dx
            down.append((y, x))
        if not (1 <= y < H - 1 and 1 <= x < W - 1) or (y, x) in seen: break
        seen.add((y, x))
        if E[y, x] < -4200: break                                          # out on the abyssal plain: the channel is spent
    up = []; y, x = py, px
    for _ in range(4000):
        cand = []
        for k, (dy, dx) in enumerate(D8):
            yy, xx = y - dy, x - dx
            if 0 <= yy < H and 0 <= xx < W and best[yy, xx] == k: cand.append((acc[yy, xx], yy, xx))
        if not cand: break
        a, y, x = max(cand)
        if a < 40 or E[y, x] > -40: break
        up.append((y, x))
    path = up[::-1] + down
    pts = [xy_lonlat(x0 + (x + .5) / T, y0 + (y + .5) / T, Z) for y, x in path]
    if len(pts) < 3: return None
    ls = LineString(pts)
    km = sum(math.hypot((b[0] - a[0]) * 111.32 * math.cos(math.radians(a[1])), (b[1] - a[1]) * 111.32) for a, b in zip(pts, pts[1:]))
    if km < 8: return None
    P = np.asarray(ls.simplify(0.004).coords)
    for _ in range(2):
        if len(P) < 3: break
        Q = np.empty((2 * (len(P) - 1), 2)); Q[0::2] = .75 * P[:-1] + .25 * P[1:]; Q[1::2] = .25 * P[:-1] + .75 * P[1:]; P = np.vstack([P[:1], Q, P[-1:]])
    return [[round(a, 3), round(b, 3)] for a, b in P], round(km)

def main(src, out, only=None):
    J = json.load(open(src)); n = 0
    for f in J['f']:
        if f['k'] != 'canyon' or 'g' in f: continue
        if only and only.upper() not in f['n']: continue
        try: r = trace(*f['c'])
        except Exception as e: print('fail', f['n'], e); continue
        if r: f['g'] = {'l': [r[0]]}; f['km'] = r[1]; n += 1; print(f['n'], r[1], 'km', flush=True)
        else: print(f['n'], 'no channel', flush=True)
    json.dump(J, open(out, 'w'), separators=(',', ':')); print('traced', n)
if __name__ == '__main__': main(*sys.argv[1:4])
