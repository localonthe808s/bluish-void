#!/usr/bin/env python3
"""EVERY CANYON OUTLINED, EVERY SEAMOUNT OUTLINED (2026-10-22, user: "canyons and seamounts should show them all illustrated not
just labeled, outline all canyons and seamounts, the hudson canyon isnt entirely outlined"). On v3 a canyon was a thalweg line
(96 of 152) or nothing (56), and 200 of 570 seamounts were a name on a point. Same sea floor as trace.py / trace2.py (AWS
Terrain Tiles z9, ~230 m a cell here):

  CANYONS -- the cut, not just its floor. The incision of every cell is how far it sits below the floor closed over it
  (a grey closing, ~6 km square, done as max- then min-filter): the valleys come out positive, the slopes and ridges zero.
  The canyon is the connected body of incision >= max(20 m, 20% of the median incision along its charted course) that the
  course runs through (or, with no course, that the charted point snaps into within ~4 km) -- so its head climbs as far up
  the shelf as the cut really goes (Hudson's ran short on v3) and its mouth stops where the cut fades on the rise. Its outline
  is that body's edge; its line is re-run as the least-cost path along the body from its shallowest to its deepest cell.
  A body over ~400 km of length or touching the window's edge on three sides is a whole slope, not a canyon, and is dropped.
  SEAMOUNTS -- every one. Lone mounts that trace2 left as points get the same contour rule (a fifth of the way up from the
  surrounding floor to the peak) with the relief floor lowered to 60 m; groups (SEAMOUNTS, HILLS, CHAIN, ...) outline every
  peak of 150 m or more within ~45 km of the charted point. What the bathymetry cannot show stays a point -- never invented.

    python3 trace3.py names_v3.json names_v4.json
"""
import json, math, sys, os
import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter, minimum_filter, label, binary_fill_holes, distance_transform_edt
from skimage.graph import route_through_array
from skimage.measure import find_contours
from shapely.geometry import Polygon, LineString
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trace as TT
import trace2 as T2
Z, T = TT.Z, TT.T


def mpp_at(lat):
    return 40075016.7 * math.cos(math.radians(lat)) / (2 ** Z * T)


def poly_ll(cont, x0, y0, tol):
    P = [T2.to_ll(p[0], p[1], x0, y0) for p in cont]
    g = Polygon(P)
    if not g.is_valid: g = g.buffer(0)
    if g.geom_type == 'MultiPolygon': g = max(g.geoms, key=lambda q: q.area)
    g = g.simplify(tol, preserve_topology=True)
    if g.is_empty or g.geom_type != 'Polygon': return None
    C = T2.chaikin(np.array(g.exterior.coords), 2)
    return [[round(x, 4), round(y, 4)] for x, y in C]


def canyon(f):
    g = f.get('g') or {}
    line = (g.get('l') or [None])[0] if not f.get('crude') else None
    pts = line if line else [f['c']]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    pad = 0.45
    W = T2.window(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad, cap=16)
    if W is None: return None
    E, x0, y0 = W; E = gaussian_filter(np.nan_to_num(E.astype(float), nan=0.0), 1.0)
    H, Wd = E.shape
    m = mpp_at(sum(ys) / len(ys)); r = max(9, int(6000 / m))
    close = minimum_filter(maximum_filter(E, size=2 * r + 1), size=2 * r + 1)
    inc = close - E; inc[E > -15] = 0
    # the course in pixels, resampled ~every cell
    cp = []
    for a, b in zip(pts, pts[1:] or pts):
        pa = T2.to_px(a[0], a[1], x0, y0); pb = T2.to_px(b[0], b[1], x0, y0); n = max(1, int(max(abs(pb[0] - pa[0]), abs(pb[1] - pa[1]))))
        for i in range(n + 1): cp.append((int(round(pa[0] + (pb[0] - pa[0]) * i / n)), int(round(pa[1] + (pb[1] - pa[1]) * i / n))))
    cp = [(y, x) for y, x in cp if 0 <= y < H and 0 <= x < Wd]
    if not cp: return None
    if len(pts) == 1:                                    # a charted point: snap into the strongest cut within ~4 km
        y, x = cp[0]; s = max(4, int(4000 / m))
        sub = inc[max(0, y - s):y + s + 1, max(0, x - s):x + s + 1]
        if sub.size == 0 or sub.max() < 20: return None
        dy, dx = np.unravel_index(np.argmax(sub), sub.shape); cp = [(max(0, y - s) + dy, max(0, x - s) + dx)]
    along = np.array([inc[y, x] for y, x in cp])
    thr = max(20.0, 0.2 * float(np.median(along[along > 0])) if (along > 0).any() else 20.0)
    body = inc >= thr
    lab, n = label(body)
    ids = {lab[y, x] for y, x in cp if lab[y, x]}
    if not ids: return None
    # the component(s) the course runs through, the one with the most course cells first
    cnt = {i: sum(1 for y, x in cp if lab[y, x] == i) for i in ids}
    keep = [i for i in ids if cnt[i] >= max(3, 0.15 * len(cp))] or [max(cnt, key=cnt.get)]
    M = np.isin(lab, keep)
    edges = sum([M[0, :].any(), M[-1, :].any(), M[:, 0].any(), M[:, -1].any()])
    yy, xx = np.nonzero(M)
    span_km = math.hypot((yy.max() - yy.min()) * m, (xx.max() - xx.min()) * m) / 1000
    if edges >= 3 or span_km > 400 or len(yy) < 20: return None
    M = binary_fill_holes(M)
    out = {'p': [], 'l': None, 'c': []}
    tol = 0.6 * m / 111320
    # the floor, end to end: the shallowest and deepest body cells, the least-cost path between them along the body
    Eb = np.where(M, E, np.nan)
    hy, hx = np.unravel_index(np.nanargmax(Eb), E.shape); dy_, dx_ = np.unravel_index(np.nanargmin(Eb), E.shape)
    lo, hi = np.nanmin(Eb), np.nanmax(Eb)
    cost = np.where(M, 1 + 30 * np.clip((E - lo) / max(hi - lo, 1), 0, 1) ** 1.5, 1e4)
    path = None
    try:
        path, _ = route_through_array(cost, (hy, hx), (dy_, dx_), fully_connected=True, geometric=True)
        L = [T2.to_ll(y, x, x0, y0) for y, x in path]
        ls = LineString(L).simplify(tol, preserve_topology=False)
        C = T2.chaikin(np.array(ls.coords), 2)
        if T2.km([tuple(q) for q in C]) >= 6: out['l'] = [[round(x, 4), round(y, 4)] for x, y in C]
    except Exception:
        path = None
    # v5: THE CUT HUGS ITS FLOOR -- the body trimmed to within ~8 km of the floor line (Hudson's v4 outline spilled into the
    # neighbouring slope halfway down), so a side valley or a slump scar beside it is not drawn as part of the canyon
    if path:
        P = np.ones(E.shape, bool); P[tuple(np.array(path).T)] = False
        M = M & (distance_transform_edt(P) * m <= 8000)
        lab2, _ = label(M); keep2 = {lab2[y, x] for y, x in path if lab2[y, x]}
        if keep2: M = np.isin(lab2, list(keep2))
    Ms = gaussian_filter(M.astype(float), 1.2)
    cs = find_contours(Ms, 0.5)
    if not cs: return None
    for c in sorted(cs, key=len, reverse=True)[:3]:
        if len(c) < 12: continue
        p = poly_ll(c, x0, y0, tol)
        if p and len(p) >= 6: out['p'].append(p)
    if not out['p']: return None
    # the deepest part of the cut: incision at least half the median along the floor
    if path:
        dep = np.array([inc[y, x] for y, x in path]); dmed = float(np.median(dep))
        out['d'] = int(round(dmed * 3.281 / 10) * 10)                      # feet, for the label
        Mi = M & (inc >= max(2 * thr, 0.5 * dmed))
        for c in sorted(find_contours(gaussian_filter(Mi.astype(float), 1.0), 0.5), key=len, reverse=True)[:4]:
            if len(c) < 10: continue
            p = poly_ll(c, x0, y0, tol)
            if p and len(p) >= 6: out['c'].append(p)
    out['len_km'] = round(span_km, 1); out['thr'] = round(thr)
    return out


GROUP = ('SEAMOUNTS', 'HILLS', 'KNOLLS', 'CHAIN', 'PEAKS', 'GUYOTS', 'MOUNTS', 'TABLEMOUNTS', 'PINNACLES', 'MOUNDS')


def mount_outline(E, x0, y0, py, px, m, rel_min):
    H, Wd = E.shape
    s = max(4, int(6000 / m))
    sub = E[max(0, py - s):py + s + 1, max(0, px - s):px + s + 1]
    if sub.size == 0: return None
    dy, dx = np.unravel_index(np.argmax(sub), sub.shape); py, px = max(0, py - s) + dy, max(0, px - s) + dx
    peak = E[py, px]
    R1, R2 = int(10000 / m), int(22000 / m)
    yy, xx = np.ogrid[:H, :Wd]; d2 = (yy - py) ** 2 + (xx - px) ** 2
    ring = E[(d2 >= R1 ** 2) & (d2 <= R2 ** 2)]
    if ring.size < 20: return None
    floor = np.percentile(ring, 25); rel = peak - floor
    if rel < rel_min or peak > -5: return None
    lev = floor + 0.2 * rel
    win = E[max(0, py - R2):py + R2 + 1, max(0, px - R2):px + R2 + 1]; oy, ox = max(0, py - R2), max(0, px - R2)
    for c in sorted(find_contours(win, lev), key=len, reverse=True):
        if len(c) < 8: continue
        pg = Polygon([(q[1], q[0]) for q in c])
        if not pg.is_valid: pg = pg.buffer(0)
        if pg.geom_type != 'Polygon' or not pg.contains(__import__('shapely').geometry.Point(px - ox, py - oy)): continue
        if pg.area * (m / 1000) ** 2 > 6000: return None                        # a whole plateau, not a mount
        cont = [(q[0] + oy, q[1] + ox) for q in c]
        base = poly_ll(cont, x0, y0, 0.5 * m / 111320)
        # v5: THE MOUNTAIN DRAWN AS A MOUNTAIN -- nested rings 45 / 70 / 90% of the way up, each the contour round the peak
        rings = []
        for fr in (0.45, 0.7, 0.9):
            for c2 in sorted(find_contours(win, floor + fr * rel), key=len, reverse=True):
                if len(c2) < 6: continue
                q2 = Polygon([(q[1], q[0]) for q in c2])
                if not q2.is_valid: q2 = q2.buffer(0)
                if q2.geom_type == 'Polygon' and q2.contains(__import__('shapely').geometry.Point(px - ox, py - oy)):
                    pp = poly_ll([(q[0] + oy, q[1] + ox) for q in c2], x0, y0, 0.4 * m / 111320)
                    if pp and len(pp) >= 5: rings.append([fr, pp])
                    break
        return base, round(float(rel)), (py, px), rings
    return None


def mounts(f):
    lon, lat = f['c']; group = any(w in f['n'].upper() for w in GROUP)
    pad = 0.55 if group else 0.3
    W = T2.window(lon - pad, lat - pad, lon + pad, lat + pad, cap=16)
    if W is None: return None
    E, x0, y0 = W; E = gaussian_filter(np.nan_to_num(E.astype(float), nan=0.0), 1.0)
    m = mpp_at(lat); py, px = T2.to_px(lon, lat, x0, y0)
    if not group:
        o = mount_outline(E, x0, y0, py, px, m, 100 if any(w in f['n'].upper() for w in ('KNOLL', 'HILL')) else 60)
        return {'p': [o[0]], 'rel': o[1], 'r': o[3]} if o and o[0] else None
    # every peak of 150 m or more within ~45 km
    rad = int(45000 / m); H, Wd = E.shape
    mx = maximum_filter(E, size=int(5000 / m) * 2 + 1)
    cand = np.argwhere((E == mx) & (E < -5))
    cand = [(y, x) for y, x in cand if (y - py) ** 2 + (x - px) ** 2 <= rad ** 2]
    cand.sort(key=lambda q: -E[q[0], q[1]])
    polys, seen, rings, rels = [], [], [], []
    for y, x in cand[:40]:
        if any((y - a) ** 2 + (x - b) ** 2 < (8000 / m) ** 2 for a, b in seen): continue
        o = mount_outline(E, x0, y0, y, x, m, 150)
        if o and o[0]:
            polys.append(o[0]); seen.append(o[2]); rings += o[3]; rels.append(o[1])
        if len(polys) >= 14: break
    return {'p': polys, 'r': rings, 'rel': max(rels)} if polys else None


def main(src, dst):
    J = json.load(open(src)); F = J['f']
    nc = nm = 0
    for i, f in enumerate(F):
        g = f.get('g') or {}
        try:
            if f['k'] == 'canyon':
                o = canyon(f)
                if o:
                    f['g'] = dict(g); f['g']['p'] = o['p']
                    if o.get('c'): f['g']['c'] = o['c']
                    if o.get('d'): f['d'] = o['d']
                    if o['l']: f['g']['l'] = [o['l']]; f.pop('crude', None)
                    nc += 1
                    print('canyon %-40s %5.0f km  thr %3d m  %d outline(s)%s' % (f['n'], o['len_km'], o['thr'], len(o['p']), '' if o['l'] else '  (no floor line)'), flush=True)
                else:
                    print('canyon %-40s kept as charted' % f['n'], flush=True)
            elif f['k'] == 'mount':
                o = mounts(f)
                if o:
                    f['g'] = dict(g)
                    if not g.get('p'): f['g']['p'] = o['p']; nm += 1
                    if o.get('r'): f['g']['r'] = o['r']
                    if o.get('rel'): f['h'] = int(round(o['rel'] * 3.281 / 50) * 50)        # feet above the floor round it, for the label
                    print('mount  %-40s %d outline(s)' % (f['n'], len(o['p'])), flush=True)
                else:
                    print('mount  %-40s kept as a point' % f['n'], flush=True)
        except Exception as e:
            print('ERR %s: %s' % (f['n'], e), flush=True)
    J['v'] = 4
    # back down to ~300 m detail and 3 decimals: the Chaikin passes quadruple the points (164k -> 28k; 184 KB gzipped)
    for f in F:
        g = f.get('g') or {}
        if g.get('p'):
            ps = []
            for p in g['p']:
                q = Polygon(p).simplify(0.0025, preserve_topology=True)
                if q.is_empty or q.geom_type != 'Polygon': continue
                c = [[round(x, 3), round(y, 3)] for x, y in q.exterior.coords]
                if len(c) >= 5: ps.append(c)
            g['p'] = ps
        if g.get('l'):
            g['l'] = [[[round(x, 3), round(y, 3)] for x, y in LineString(l).simplify(0.0015).coords] for l in g['l']]
        for k in ('c',):
            if g.get(k):
                g[k] = [[[round(x, 3), round(y, 3)] for x, y in Polygon(p).simplify(0.0025, preserve_topology=True).exterior.coords] for p in g[k] if len(p) >= 4]
        if g.get('r'):
            rr = []
            for fr, p in g['r']:
                q = Polygon(p).simplify(0.002, preserve_topology=True)
                if q.is_empty or q.geom_type != 'Polygon': continue
                c = [[round(x, 3), round(y, 3)] for x, y in q.exterior.coords]
                if len(c) >= 4: rr.append([fr, c])
            g['r'] = rr
    J['v'] = 5
    json.dump(J, open(dst, 'w'), separators=(',', ':'))
    print('canyons outlined %d, mounts newly outlined %d' % (nc, nm))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
