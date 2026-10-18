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

def splice(coords, seed, near=0.15):
    """A SEED LINE THROUGH THE REAL TOWNS where Fenneman's border is not the landform (user 2026-10-18: "the line stops at
    Fenneman's Edwards Plateau border so the Austin-Waco stretch is missing"; "it follows Fenneman's section border west
    around the Royal Gorge area"). The seed replaces the Fenneman vertices between the ones nearest its two ends, or -- when
    one end lies past the line's end -- extends it (write that seed to END at the line). Not near this part: unchanged."""
    c = [list(map(float, p)) for p in coords]; S = [list(map(float, p)) for p in seed]
    d = lambda p: [math.hypot(q[0] - p[0], q[1] - p[1]) for q in c]
    d0, d1 = d(S[0]), d(S[-1])
    if min(min(d0), min(d1)) > near: return c, False
    i, j = int(np.argmin(d0)), int(np.argmin(d1))
    if i <= j: return c[:i] + S + c[j + 1:], True
    return c[:j] + S[::-1] + c[i + 1:], True

def lip(a, b, plateau, seed, cache, T=30.0, close=2.0, opn=1.0, dl=0.0025, pad=0.6):
    """THE RIM AROUND THE CANYONS (user 2026-10-18: "two stretches cut across canyon country instead of wrapping the
    escarpment around the canyons ... trace the rim as an elevation contour/lip on the DEM"). For a tableland whose edge is
    cut by canyons (the Llano Estacado: Palo Duro, Tule, Quitaque, Blanco), a corridor snap cannot follow a canyon 40 km in
    and back out. Instead the tableland itself is found: its top surface is fitted (a cubic in lon/lat over the ground well
    inside the section, the playas and draws rejected), and the lip is where the ground falls T m below that surface. Draws
    narrower than ~2*close km are bridged, slivers thinner than ~2*opn km dropped, the piece holding `seed` kept, and its
    outline is cut between the points nearest a and b (the Fenneman line's two ends), running a -> b.
    plateau: the section polygon (shapely). Returns an Nx2 lon/lat array."""
    from shapely import vectorized
    from scipy import ndimage as ndi
    from skimage import measure
    from skimage.morphology import remove_small_holes
    w = min(a[0], b[0]) - pad * 2; e = max(a[0], b[0]) + pad; s = min(a[1], b[1]) - pad; n = max(a[1], b[1]) + pad
    lat0 = (s + n) / 2; lo = np.arange(w, e, dl); la = np.arange(n, s, -dl * math.cos(math.radians(lat0)))
    LO, LA = np.meshgrid(lo, la)
    Zr = elev(LO.ravel(), LA.ravel(), cache).reshape(LO.shape)
    Zs = gaussian_filter1d(gaussian_filter1d(Zr, 1, axis=0), 1, axis=1)
    m = vectorized.contains(plateau.buffer(-0.35), LO, LA)
    x0, y0 = float(LO[m].mean()), float(LA[m].mean())
    X = lambda x, y: np.c_[np.ones_like(x), x, y, x * x, x * y, y * y, x ** 3, y ** 3, x * x * y, x * y * y]
    x, y, z = LO[m][::7] - x0, LA[m][::7] - y0, Zs[m][::7]; keep = np.ones(len(z), bool)
    for _ in range(6):
        cf = np.linalg.lstsq(X(x[keep], y[keep]), z[keep], rcond=None)[0]
        r = z - X(x, y) @ cf; keep = r > -2 * np.std(r[keep])
    R = Zs - (X(LO.ravel() - x0, LA.ravel() - y0) @ cf).reshape(LO.shape)
    px = dl * 111.32 * math.cos(math.radians(lat0))
    M = (R > -T) & vectorized.contains(plateau.buffer(0.12), LO, LA)
    M = remove_small_holes(M, int(60 / px ** 2))                     # playas
    disk = lambda r: np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r
    M = ndi.binary_closing(M, disk(max(1, round(close / px))), border_value=1)
    M = ndi.binary_opening(M, disk(max(1, round(opn / px))), border_value=1)
    lab, _ = ndi.label(M)
    k = lab[int(np.argmin(np.abs(la - seed[1]))), int(np.argmin(np.abs(lo - seed[0])))]
    M = remove_small_holes(lab == k, int(60 / px ** 2))
    F = ndi.gaussian_filter(M.astype(float), 2.0)
    C = max(measure.find_contours(F, 0.5), key=len)
    P = np.c_[np.interp(C[:, 1], np.arange(len(lo)), lo), np.interp(C[:, 0], np.arange(len(la)), la)]
    # cut: from the outline point nearest b, walk toward a and stop at the FIRST pass within 3 km of it (the outline can
    # come back near a after looping round a spur; the nearest point overall may be that later pass)
    da = np.hypot((P[:, 0] - a[0]) * math.cos(math.radians(lat0)), P[:, 1] - a[1]) * 111.32
    ib = int(np.argmin(np.hypot(P[:, 0] - b[0], P[:, 1] - b[1])))
    ia = int(np.argmin(da)); step = 1 if ia > ib else -1
    near = np.nonzero(da[ib::step] < 3.0)[0]
    if len(near): ia = ib + step * int(near[0])
    P = P[ia:ib + 1] if ia <= ib else P[ib:ia + 1][::-1]
    P = np.c_[gaussian_filter1d(P[:, 0], 2, mode='nearest'), gaussian_filter1d(P[:, 1], 2, mode='nearest')]   # ~0.5 km
    return P

def simp(P, tol):
    ls = LineString(P).simplify(tol, preserve_topology=False)
    return [[round(x, 4), round(y, 4)] for x, y in ls.coords]
