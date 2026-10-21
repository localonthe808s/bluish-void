import math, numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates
import trace2 as T2
def incision(line, pad=0.3, side_km=(2.5, 5.0)):
    """share of the course that runs LOWER than the floor 2.5-5 km to either side (by >= 8 m), and the median depth of that cut"""
    xs = [p[0] for p in line]; ys = [p[1] for p in line]
    W = T2.window(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    if W is None: return None
    E, x0, y0 = W; E = gaussian_filter(E.astype(float), 1.0)
    P = []
    for lon, lat in line:
        x, y = T2.TT.tile_xy(lon, lat, T2.Z); P.append(((x - x0) * T2.T, (y - y0) * T2.T, lat))
    # resample every ~1 km
    Q = []
    for a, b in zip(P, P[1:]):
        mpp = 40075016.7 * math.cos(math.radians(a[2])) / (2 ** T2.Z * T2.T); n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) * mpp / 1000))
        for i in range(n): t = i / n; Q.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, mpp, b[0] - a[0], b[1] - a[1]))
    cut = []
    for x, y, mpp, dx, dy in Q:
        L = math.hypot(dx, dy) or 1; nx, ny = -dy / L, dx / L
        z0 = map_coordinates(E, [[y], [x]], order=1)[0]; sides = []
        for s in (-1, 1):
            vals = [map_coordinates(E, [[y + s * ny * k * 1000 / mpp], [x + s * nx * k * 1000 / mpp]], order=1)[0] for k in side_km]
            sides.append(min(vals))
        cut.append(min(sides) - z0)
    cut = np.array(cut)
    return round(float((cut >= 8).mean()), 2), round(float(np.median(cut)), 1), len(cut)
