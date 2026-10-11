import pickle, numpy as np, netCDF4 as nc, math, json
from shapely.geometry import box
from shapely.ops import linemerge
from scipy.ndimage import gaussian_filter, map_coordinates
P = pickle.load(open('prov.pkl', 'rb')); B = box(-81.2, 37.677, -73.35, 42.922)
d = nc.Dataset('dl/gmrt_ridges.nc'); nx, ny = [int(v) for v in d['dimension'][:]]
z = np.array(d['z'][:], dtype=np.float32).reshape(ny, nx); LON0 = float(d['x_range'][0]); LAT1 = float(d['y_range'][1]); DX, DY = float(d['spacing'][0]), float(d['spacing'][1])
zs = gaussian_filter(z, 2.0)
def Zat(lon, lat): return map_coordinates(zs, [[(LAT1 - lat) / DY - .5], [(lon - LON0) / DX - .5]], order=1)[0]
l = P['APPALACHIAN PLATEAUS'].boundary.intersection(P['VALLEY AND RIDGE'].buffer(0.02)).intersection(B.buffer(-0.01))
l = linemerge(l); parts = sorted(l.geoms, key=lambda p: -p.length)
front = parts[0]   # -76.06,41.3 -> -80.39,37.69
# resample every ~3 km
n = int(front.length / 0.03); pts = [front.interpolate(i / n, normalized=True) for i in range(n + 1)]
P2 = np.array([[p.x, p.y] for p in pts])
off = []
for i in range(len(P2)):
    a = P2[max(0, i - 2)]; b = P2[min(len(P2) - 1, i + 2)]
    tx, ty = (b[0] - a[0]) * math.cos(math.radians(P2[i][1])), b[1] - a[1]; tl = math.hypot(tx, ty)
    nxv, nyv = -ty / tl, tx / tl          # normal (km-ish space)
    best = None
    for s in np.linspace(-10, 10, 41):    # km along the normal
        dl = s / 111.0
        lon = P2[i][0] + nxv * dl / math.cos(math.radians(P2[i][1])); lat = P2[i][1] + nyv * dl
        e = 1.5 / 111.0
        g = abs(Zat(lon + nxv * e / math.cos(math.radians(lat)), lat + nyv * e) - Zat(lon - nxv * e / math.cos(math.radians(lat)), lat - nyv * e)) / 3.0
        if best is None or g > best[0]: best = (g, s, Zat(lon, lat))
    off.append(best)
off = np.array(off)
print('points', len(P2), 'offset km: median %.1f  p90 %.1f' % (np.median(np.abs(off[:, 1])), np.percentile(np.abs(off[:, 1]), 90)), 'gradient m/km median %.0f' % np.median(off[:, 0]))
for i in range(0, len(P2), 12): print([round(v, 2) for v in P2[i]], 'off %.1f km grad %.0f m/km z %.0f' % (off[i, 1], off[i, 0], off[i, 2]))
np.save('front_pts.npy', P2); np.save('front_off.npy', off)
