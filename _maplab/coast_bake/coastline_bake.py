"""THE GREEN COAST TRIM for a wide view (2026-10-11, user: "bake our green continental trim to all the map radar maps").
The ocean's edge, traced off the view's own GMRT grid so it lies on its raster's shore, as THE COAST's city_coast_line.json:
the water connected to a seed point out at sea (lakes, Erie and the Finger Lakes whose beds sit below sea level, are left out),
lightly smoothed, contoured, simplified to about a screen pixel, written as {src, r:[[lon,lat,lon,lat,...],...]}.
python3 coastline_bake.py <X0,Y0,X1,Y1> <W> <H> <grid.nc> <seedLon,seedLat> <simplify_px> <out.json> [border]"""
import sys, json, math, numpy as np
from scipy.ndimage import label, gaussian_filter
from skimage.measure import find_contours
from shapely.geometry import LineString
sys.path.insert(0, __file__.rsplit('/', 1)[0]); from lut2 import load, sample
R = 6378137.0
bx = tuple(float(v) for v in sys.argv[1].split(',')); W, H = int(sys.argv[2]), int(sys.argv[3])
Z, _ = sample(load(sys.argv[4]), bx, W, H)
slon, slat = (float(v) for v in sys.argv[5].split(',')); eps = float(sys.argv[6])
X0, Y0, X1, Y1 = bx
sx = int((slon * math.pi / 180 * R - X0) / (X1 - X0) * W); sy = int((Y1 - R * math.log(math.tan(math.pi / 4 + slat * math.pi / 360))) / (Y1 - Y0) * H)
# every body below sea level, as the raster draws it, EXCEPT the lakes whose beds dip under it: the seed only proves the
# grid reads; the Great Lakes and Finger Lakes (west of -75, north of 41.3) and Champlain go, and so do ponds under 40 px
lab, n = label(Z < 0); assert lab[sy, sx], 'seed is not in water'
BORDER = len(sys.argv) > 8 and sys.argv[8] == 'border'   # LA: only water reaching the frame's edge is the sea (the Salton Sea and
edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))  # Death Valley sit below sea level inland)
keep = np.zeros(n + 1, bool)
cnt = np.bincount(lab.ravel(), minlength=n + 1); sxm = np.bincount(lab.ravel(), weights=np.tile(np.arange(W), H), minlength=n + 1); sym = np.bincount(lab.ravel(), weights=np.repeat(np.arange(H), W), minlength=n + 1)
for i in range(1, n + 1):
    if cnt[i] < 40: continue
    if BORDER:
        keep[i] = i in edge and cnt[i] > 2000; continue
    cx, cy = sxm[i] / cnt[i], sym[i] / cnt[i]
    lon = (X0 + (cx + .5) / W * (X1 - X0)) / R * 180 / math.pi; lat = (2 * math.atan(math.exp((Y1 - (cy + .5) / H * (Y1 - Y0)) / R)) - math.pi / 2) * 180 / math.pi
    if lon < -75.0 and lat > 41.3: continue
    if lat > 43.5 and -73.6 < lon < -73.0: continue
    if (lat > 44.0 and lon < -74.0) or (lat > 44.8 and lon < -71.0): continue   # the St. Lawrence: a river, not the coast
    keep[i] = True
sea = gaussian_filter(keep[lab].astype(np.float32), 0.8)
out = []
for c in find_contours(sea, 0.5):
    if len(c) < 6: continue
    ls = LineString([(x, y) for y, x in c]).simplify(eps)
    if ls.length < 4: continue
    if ls.is_closed and ls.length < 36: continue      # marsh islets: a scatter of tiny rings reads as noise, not shore
    r = []
    for x, y in ls.coords:
        lon = (X0 + (x + 0.5) / W * (X1 - X0)) / R * 180 / math.pi
        lat = (2 * math.atan(math.exp((Y1 - (y + 0.5) / H * (Y1 - Y0)) / R)) - math.pi / 2) * 180 / math.pi
        r += [round(lon, 4), round(lat, 4)]
    out.append(r)
json.dump({'src': 'GMRT ocean edge of this view\'s grid (coastline_bake.py), seed %s, simplified %s px of %dx%d' % (sys.argv[5], eps, W, H), 'r': out},
          open(sys.argv[7], 'w'), separators=(',', ':'))
print(sys.argv[7], len(out), 'lines', sum(len(r) // 2 for r in out), 'points')
