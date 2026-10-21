#!/usr/bin/env python3
"""THE SEA CHANNELS AND SEAMOUNTS, OFF THE SEA FLOOR (2026-10-21, user: "visualize seachannels better, its just a straight line
and make sure canyons and seamounts are properly outlined and traced"). trace.py traced the canyons the gazetteer gives as a
point; the 61 it gives as a crude line (two or three vertices -- MORESBY SEACHANNEL was one straight segment across 450 km) and
every seamount without a footprint (445 of 570) were left as charted. Here, on the same AWS Terrain Tiles at z9 (trace.tile):

  CANYONS with a crude course: the least-cost path between the course's two ends (each snapped to the deepest cell within
  ~4 km), the cost of a step rising with its depth above the window's floor -- so the path keeps to the channel's thalweg.
  Kept when the path stays under 1.8x the straight distance (a path that wanders that far has lost the channel).
  SEAMOUNTS (Seamount, Guyot, Tablemount, Knoll, Hill, Peak, Pinnacle, Mound) with no outline: the closed contour a fifth of the
  way up from the surrounding floor (the 25th percentile of the window's rim) to the peak (the highest cell within ~6 km of the
  charted point) that encloses the peak; relief under 200 m (100 m for knolls and hills) is not a mount at this resolution and
  keeps its point. Groups (Seamounts, Hills, Seamount Chain) keep theirs.
Both simplified and rounded with two Chaikin passes, as trace.py does.

    python3 trace2.py names_v2.json names_v3.json
"""
import json, math, sys, os
import numpy as np
from scipy.ndimage import gaussian_filter
from skimage.graph import route_through_array
from skimage.measure import find_contours
from shapely.geometry import LineString, Polygon, Point
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trace as TT
Z, T = TT.Z, TT.T

def window(w, s, e, n, cap=14):
    x0, y1 = TT.tile_xy(w, s, Z); x1, y0 = TT.tile_xy(e, n, Z)
    x0, y0, x1, y1 = int(math.floor(x0)), int(math.floor(y0)), int(math.floor(x1)), int(math.floor(y1))
    if x1 - x0 + 1 > cap or y1 - y0 + 1 > cap: return None
    rows = []
    for ty in range(y0, y1 + 1):
        rows.append(np.hstack([TT.tile(tx, ty) for tx in range(x0, x1 + 1)]))
    return np.vstack(rows), x0, y0

def to_px(lon, lat, x0, y0):
    x, y = TT.tile_xy(lon, lat, Z); return int((y - y0) * T), int((x - x0) * T)
def to_ll(py, px, x0, y0):
    return TT.xy_lonlat(x0 + (px + .5) / T, y0 + (py + .5) / T, Z)
def km(pts):
    return sum(math.hypot((b[0] - a[0]) * 111.32 * math.cos(math.radians(a[1])), (b[1] - a[1]) * 111.32) for a, b in zip(pts, pts[1:]))
def chaikin(P, n=2):
    P = np.asarray(P)
    for _ in range(n):
        if len(P) < 3: break
        Q = np.empty((2 * (len(P) - 1), 2)); Q[0::2] = .75 * P[:-1] + .25 * P[1:]; Q[1::2] = .25 * P[:-1] + .75 * P[1:]; P = np.vstack([P[:1], Q, P[-1:]])
    return P

def canyon(line):
    A, B = line[0], line[-1]
    span = max(abs(B[0] - A[0]), abs(B[1] - A[1])); pad = max(0.25, span * 0.25)
    W = window(min(A[0], B[0]) - pad, min(A[1], B[1]) - pad, max(A[0], B[0]) + pad, max(A[1], B[1]) + pad)
    if W is None: return None
    E, x0, y0 = W; E = gaussian_filter(E.astype(float), 1.5)
    lo, hi = np.percentile(E, 2), np.percentile(E, 98)
    cost = 1 + 40 * np.clip((E - lo) / max(hi - lo, 1), 0, 1) ** 1.5; cost[E > -20] = 500   # land and the shallows: off limits
    H, Wd = E.shape
    def snap(p):
        py, px = to_px(p[0], p[1], x0, y0); r = 16
        a0, b0 = max(0, py - r), max(0, px - r); sub = E[a0:py + r + 1, b0:px + r + 1]
        if not sub.size: return None
        j, i = np.unravel_index(np.argmin(sub), sub.shape); return (a0 + j, b0 + i)
    a, b = snap(A), snap(B)
    if not a or not b or not (0 <= a[0] < H and 0 <= a[1] < Wd and 0 <= b[0] < H and 0 <= b[1] < Wd): return None
    path, _ = route_through_array(cost, a, b, fully_connected=True, geometric=True)
    pts = [to_ll(py, px, x0, y0) for py, px in path]
    straight = km([A, B]); L = km(pts)
    if straight < 5 or L > 1.8 * straight: return None
    P = chaikin(np.asarray(LineString(pts).simplify(0.004).coords))
    out = [[round(x, 3), round(y, 3)] for x, y in P]
    # IN A CHANNEL, OR NOT AT ALL: the least-cost path always arrives, channel or no channel (MORESBY SEACHANNEL's ran down the
    # regional slope: 16% of it below the floor 2.5-5 km either side). trace.py's good traces measure 62-89%; under half is kept out.
    from incise import incision
    inc = incision(out)
    if not inc or inc[0] < 0.5: return None
    return out, round(L)

MOUNT = {'SEAMOUNT': 35, 'GUYOT': 40, 'TABLEMOUNT': 40, 'KNOLL': 12, 'HILL': 14, 'PEAK': 20, 'PINNACLE': 10, 'MOUND': 10}
GROUP = ('SEAMOUNTS', 'HILLS', 'KNOLLS', 'CHAIN', 'MOUNDS')
def mount(f):
    nm = f['n']
    if any(nm.endswith(g) or (' ' + g + ' ') in (' ' + nm + ' ') for g in GROUP): return None
    kind = next((k for k in MOUNT if nm.endswith(k)), None)
    if not kind: return None
    rkm = MOUNT[kind]; lon, lat = f['c']; dlat = rkm / 111.32; dlon = rkm / (111.32 * math.cos(math.radians(lat)))
    W = window(lon - dlon, lat - dlat, lon + dlon, lat + dlat, cap=6)
    if W is None: return None
    E, x0, y0 = W; E = gaussian_filter(E.astype(float), 1.0); H, Wd = E.shape
    cy, cx = to_px(lon, lat, x0, y0)
    # the window as a disc of rkm around the point, in pixels (mercator: ground metres per px at this latitude)
    mpp = 40075016.7 * math.cos(math.radians(lat)) / (2 ** Z * T); R = int(rkm * 1000 / mpp)
    ys, xs = np.ogrid[:H, :Wd]; d = np.hypot(ys - cy, xs - cx)
    near = d <= max(4, 6000 / mpp)
    if not near.any(): return None
    pk = np.argmax(np.where(near, E, -1e9)); py, px = np.unravel_index(pk, E.shape); peak = E[py, px]
    rim = (d > R * .85) & (d <= R)
    if not rim.any() or peak > -5: return None
    base = np.percentile(E[rim], 25); relief = peak - base
    if relief < (100 if kind in ('KNOLL', 'HILL', 'MOUND', 'PINNACLE') else 200): return None
    Ein = np.where(d <= R, E, base - 1)
    for frac in (0.2, 0.3, 0.45):
        lvl = base + frac * relief
        for c in find_contours(Ein, lvl):
            if len(c) < 8 or np.hypot(*(c[0] - c[-1])) > 1.5: continue
            poly = Polygon(c[:, ::-1])
            if not poly.is_valid: poly = poly.buffer(0)
            if poly.is_empty or not poly.contains(Point(px, py)): continue
            if math.sqrt(poly.area / math.pi) > R * .9: continue                  # the contour ran to the rim: not this mount's own
            # ...and none of it may touch the sampled disc or the window's edge: a clipped contour draws the window (an arc, a
            # ruler-straight side -- SAURY and POZHARSKY in the first run), not the mount; a higher contour is tried instead
            dd = np.hypot(c[:, 0] - cy, c[:, 1] - cx)
            if dd.max() > R * .88 or c[:, 0].min() < 2 or c[:, 1].min() < 2 or c[:, 0].max() > H - 3 or c[:, 1].max() > Wd - 3: continue
            pts = [to_ll(y, x, x0, y0) for x, y in poly.exterior.coords]
            P = chaikin(np.asarray(Polygon(pts).simplify(0.003).exterior.coords))
            return [[round(x, 3), round(y, 3)] for x, y in P], int(relief)
    return None

def main(src, out):
    J = json.load(open(src)); nc = nm = 0
    for f in J['f']:
        try:
            if f['k'] == 'canyon' and f.get('g', {}).get('l'):
                L = f['g']['l'][0]
                if len(L) <= 3:
                    r = canyon(L)
                    if r: f['g'] = {'l': [r[0]]}; f['km'] = r[1]; nc += 1; print('canyon', f['n'], r[1], 'km', flush=True)
                    else: f['crude'] = 1; print('canyon untraceable, course hidden', f['n'], flush=True)   # the page draws no straight line for it
            elif f['k'] == 'mount' and not f.get('g', {}).get('p'):
                r = mount(f)
                if r: f['g'] = {'p': [r[0]]}; f['relief'] = r[1]; nm += 1
        except Exception as e:
            print('fail', f['n'], e, flush=True)
    J['src'] += '; courses and footprints traced off AWS Terrain Tiles (z9) where the gazetteer has none or a crude one'
    json.dump(J, open(out, 'w'), separators=(',', ':')); print('canyons retraced', nc, 'mounts outlined', nm)
if __name__ == '__main__': main(*sys.argv[1:3])
