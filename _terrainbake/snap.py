#!/usr/bin/env python3
"""THE EDGES ON THE REAL GROUND (user 2026-10-18: "geological weather visuals are crudely drawn and are not cleanly outlining
features ... A real fix means rebuilding that data file at finer detail"). The Fenneman borders bake.py starts from are drawn at
~1:7,000,000, so a line can sit 5-10 km off the escarpment it names, cutting across valleys and spurs. This module moves each
edge onto the actual step in the ground:

  1. the Fenneman line is smoothed (~8 km) and cut into stations 1 km apart, each with a normal pointing to the high side;
  2. along each normal, +-CORR km, the elevation is read off the AWS open Terrain Tiles (Mapzen terrarium, keyless, the
     source _reliefbake already uses) at z9 (~230 m at 40 N) every 250 m, smoothed, and its rise toward the high side
     taken over a 3 km window -- the escarpment is where that rise is steepest;
  3. a Viterbi pass picks one offset per station: the steepest ground, a small pull back to the Fenneman line, and a cost
     for every 0.5 km the trace jumps between neighbors, so the line follows ONE face instead of hopping ridge to ridge;
  4. stretches where even the best offset is nearly flat (no real step: a gap, a river cut, a seam on a plain) are dropped;
  5. Chaikin smoothing, then Douglas-Peucker at ~200 m (0.002 deg) for the full line and ~1 km (0.01 deg) for the
     national view.
"""
import io, math, os, urllib.request
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import LineString

Z = 9
TT = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/%d/%d/%d.png'
_tiles = {}

def _tile(x, y, cache):
    k = (x, y)
    if k in _tiles: return _tiles[k]
    fn = os.path.join(cache, '%d_%d_%d.png' % (Z, x, y))
    if not os.path.exists(fn):
        for a in range(4):
            try:
                b = urllib.request.urlopen(TT % (Z, x, y), timeout=30).read(); open(fn, 'wb').write(b); break
            except Exception:
                if a == 3: raise
    a = np.asarray(Image.open(fn).convert('RGB')).astype(np.float32)
    _tiles[k] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    return _tiles[k]

def elev(lon, lat, cache):
    """bilinear elevation (m) at arrays of lon/lat from the z9 terrarium pyramid"""
    lon = np.asarray(lon, float); lat = np.asarray(lat, float); n = 256 * 2 ** Z
    px = (lon + 180) / 360 * n - .5
    s = np.sin(np.radians(lat)); py = (0.5 - np.log((1 + s) / (1 - s)) / (4 * np.pi)) * n - .5
    x0, y0 = np.floor(px).astype(int), np.floor(py).astype(int); fx, fy = px - x0, py - y0
    def g(xi, yi):
        out = np.empty(xi.shape, np.float32); tx, ty = xi // 256, yi // 256
        key = tx * 100000 + ty
        for k in np.unique(key):
            m = key == k; t = _tile(int(k // 100000), int(k % 100000), cache)
            out[m] = t[yi[m] % 256, xi[m] % 256]
        return out
    return (g(x0, y0) * (1 - fx) * (1 - fy) + g(x0 + 1, y0) * fx * (1 - fy) + g(x0, y0 + 1) * (1 - fx) * fy + g(x0 + 1, y0 + 1) * fx * fy)

def _km(c, lat0):
    k = math.cos(math.radians(lat0)) * 111.32
    return np.c_[(c[:, 0]) * k, c[:, 1] * 111.32], k

def chaikin(P, n=2):
    for _ in range(n):
        if len(P) < 3: return P
        Q = [P[0]]
        for a, b in zip(P[:-1], P[1:]): Q += [a * .75 + b * .25, a * .25 + b * .75]
        Q.append(P[-1]); P = np.array(Q)
    return P

def snap(coords, up, cache, corr=15.0, minstep=18.0, pull=0.6, jump=0.15, mode='face'):
    """coords: the Fenneman line (lon, lat); up: +1 when the high side is the line's left-hand normal (bake.py's sense).
    Returns (list of snapped pieces as Nx2 lon/lat arrays, stats)."""
    c = np.array(coords, float); lat0 = float(c[:, 1].mean())
    xy, k = _km(c, lat0)
    seg = np.hypot(*np.diff(xy, axis=0).T); s = np.r_[0, np.cumsum(seg)]; Ltot = s[-1]
    if Ltot < 5: return [], {}
    st = np.arange(0, Ltot, 1.0)
    bx, by = np.interp(st, s, xy[:, 0]), np.interp(st, s, xy[:, 1])
    sig = 8.0 if Ltot > 60 else 3.0                      # base line smoothed so the normals do not swing at every kink
    bx, by = gaussian_filter1d(bx, sig, mode='nearest'), gaussian_filter1d(by, sig, mode='nearest')
    tx, ty = np.gradient(bx), np.gradient(by); tl = np.hypot(tx, ty) + 1e-9
    nx, ny = -ty / tl * up, tx / tl * up                  # toward the high side
    offs = np.arange(-corr, corr + 1e-6, 0.5)              # candidate offsets (km)
    samp = np.arange(-corr - 3, corr + 3 + 1e-6, 0.25)     # the profile, 250 m
    PX = bx[:, None] + nx[:, None] * samp[None, :]; PY = by[:, None] + ny[:, None] * samp[None, :]
    E = elev((PX / k).ravel(), (PY / 111.32).ravel(), cache).reshape(PX.shape)
    E = gaussian_filter1d(E, 2, axis=1)                   # ~500 m
    E = gaussian_filter1d(E, 1, axis=0)                   # and a little along the line
    w = 6                                                  # 1.5 km each way: rise over 3 km
    rise = (np.roll(E, -w, axis=1) - np.roll(E, w, axis=1)) / 3.0   # m/km toward the high side
    idx = ((offs + corr + 3) / 0.25).round().astype(int)
    G = np.clip(rise[:, idx], 0, None)                    # stations x offsets
    # WHICH LINE ON THE STEP: 'face' = the steepest part (a cliff band like the Allegheny Front); 'foot' = where the ground
    # starts to climb out of the lowland (a mountain front seen from the plains: Boulder sits AT the line, not 3 km up the
    # foothills); 'rim' = where the climb ends at the top (the Mogollon Rim is the plateau's lip). Read over 2.5 km each way.
    a = 10
    ahead = (np.roll(E, -a, axis=1) - E)[:, idx] / 2.5; behind = (E - np.roll(E, a, axis=1))[:, idx] / 2.5
    S = G if mode == 'face' else np.clip(ahead - np.clip(behind, 0, None), 0, None) * (ahead > 0) if mode == 'foot' else \
        np.clip(behind - np.clip(ahead, 0, None), 0, None) * (behind > 0)
    S = 0.75 * S + 0.25 * G if mode != 'face' else S        # stay on a real slope, not any kink
    ref = np.percentile(S.max(axis=1), 75) or 1.0
    cost = -S / ref + pull * (offs[None, :] / corr) ** 2
    # Viterbi: at most 2 offset steps (1 km) between stations 1 km apart
    n, m = cost.shape; D = cost[0].copy(); B = np.zeros((n, m), int)
    for i in range(1, n):
        best = np.full(m, np.inf); arg = np.zeros(m, int)
        for d in (-2, -1, 0, 1, 2):
            sh = np.full(m, np.inf)
            if d >= 0: sh[d:] = D[:m - d] if d else D
            else: sh[:d] = D[-d:]
            sh = sh + jump * abs(d)
            better = sh < best; best[better] = sh[better]; arg[better] = (np.arange(m) - d)[better]
        D = best + cost[i]; B[i] = arg
    path = np.zeros(n, int); path[-1] = int(np.argmin(D))
    for i in range(n - 1, 0, -1): path[i - 1] = B[i, path[i]]
    o = gaussian_filter1d(offs[path], 1.5, mode='nearest')
    g = np.array([G[i, max(0, path[i] - 6):path[i] + 7].max() for i in range(n)])   # the slope within 3 km of the trace
    gs = gaussian_filter1d(g, 3, mode='nearest')
    X, Y = bx + nx * o, by + ny * o
    # 4. drop the flat stretches: 25 km or more with the steepest rise under minstep m/km (a shorter dip -- a river cut
    #    through the rim -- is bridged, so one feature reads as one line)
    weak = gs < minstep
    keep = np.ones(n, bool); i = 0
    while i < n:
        if weak[i]:
            j = i
            while j < n and weak[j]: j += 1
            if j - i >= 25: keep[i:j] = False
            i = j
        else: i += 1
    pieces = []; i = 0
    while i < n:
        if keep[i]:
            j = i
            while j < n and keep[j]: j += 1
            if j - i >= 20: pieces.append((i, j))
            i = j
        else: i += 1
    out = []
    for a, b in pieces:
        P = np.c_[X[a:b] / k, Y[a:b] / 111.32]
        P = chaikin(P, 2)
        out.append(P)
    return out, {'len': Ltot, 'kept': float(keep.sum()), 'medoff': float(np.median(np.abs(offs[path]))), 'medrise': float(np.median(g))}

def simp(P, tol):
    ls = LineString(P).simplify(tol, preserve_topology=False)
    return [[round(x, 4), round(y, 4)] for x, y in ls.coords]
