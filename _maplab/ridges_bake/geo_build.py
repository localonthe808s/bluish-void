import pickle, numpy as np, netCDF4 as nc, json, math
from shapely.geometry import box, Point, LineString
from shapely.ops import linemerge, unary_union
from shapely import vectorized
P = pickle.load(open('prov.pkl', 'rb')); B = box(-81.2, 37.677, -73.35, 42.922)
d = nc.Dataset('dl/gmrt_ridges.nc'); nx, ny = [int(v) for v in d['dimension'][:]]
z = np.array(d['z'][:], dtype=np.float32).reshape(ny, nx); LON0 = float(d['x_range'][0]); LAT1 = float(d['y_range'][1]); DX, DY = float(d['spacing'][0]), float(d['spacing'][1])
lon = LON0 + (np.arange(nx) + .5) * DX; lat = LAT1 - (np.arange(ny) + .5) * DY
st = 4; LO, LA = np.meshgrid(lon[::st], lat[::st]); Zs = z[::st, ::st]
def med_ft(geom):
    g = geom.intersection(B); m = vectorized.contains(g, LO, LA) & (Zs > 0)
    return int(round(np.median(Zs[m]) * 3.28084 / 100) * 100), int(m.sum())
belts = [('ALLEGHENY PLATEAU', 'APPALACHIAN PLATEAUS', (-79.75, 41.25)),
         ('RIDGE AND VALLEY', 'VALLEY AND RIDGE', (-77.55, 40.62)),
         ('BLUE RIDGE', 'BLUE RIDGE', (-78.05, 38.95)),
         ('PIEDMONT', 'PIEDMONT', (-76.75, 39.85)),
         ('HIGHLANDS', 'NEW ENGLAND', (-74.6, 40.95)),
         ('COASTAL PLAIN', 'COASTAL PLAIN', (-74.85, 39.55))]
out = {'belt': [], 'edge': []}
for n, pv, c in belts:
    ft, cnt = med_ft(P[pv]); inside = P[pv].contains(Point(c))
    print(n, ft, 'ft', cnt, 'inside' if inside else 'OUTSIDE!')
    out['belt'].append({'n': n, 'c': list(c), 'ft': ft})
def edge(a, b):
    l = P[a].boundary.intersection(P[b].buffer(0.02)).intersection(B.buffer(-0.01))
    l = linemerge(l) if l.geom_type == 'MultiLineString' else l
    return sorted([p for p in (l.geoms if hasattr(l, 'geoms') else [l]) if p.geom_type == 'LineString'], key=lambda p: -p.length)
R = lambda ls, eps=0.01: [[round(x, 3), round(y, 3)] for x, y in ls.simplify(eps).coords]
fr = edge('APPALACHIAN PLATEAUS', 'VALLEY AND RIDGE')
def chain(parts):                                # join runs end to end (linemerge misses the buffered seams)
    parts = [list(p.coords) for p in parts]; line = parts.pop(0)
    while parts:
        best = None
        for i, q in enumerate(parts):
            for rev in (False, True):
                qq = q[::-1] if rev else q
                for atEnd in (True, False):
                    a = line[-1] if atEnd else line[0]; b = qq[0] if atEnd else qq[-1]
                    dd = math.hypot(a[0] - b[0], a[1] - b[1])
                    if best is None or dd < best[0]: best = (dd, i, qq, atEnd)
        dd, i, qq, atEnd = best; parts.pop(i)
        if dd > 0.1: print('  gap', round(dd, 3)); 
        line = line + qq if atEnd else qq + line
    return LineString(line)
front = fr[0]                  # the Front from West Virginia to where it bends east past the West Branch; beyond, the boundary hooks round the anthracite valleys and is not the Front
front0 = fr[0]
# orient south -> north so the right-hand normal points EAST (plateau on the left/west)
if front.coords[0][1] > front.coords[-1][1]: front = LineString(front.coords[::-1])
print('front', round(front.length, 2), front.coords[0], front.coords[-1])
# three live sample points along the Front, with the east-pointing normal (unit, in km space)
smp = []
for f in (0.2, 0.45, 0.7):
    F0 = LineString(front0.coords[::-1]) if front0.coords[0][1] > front0.coords[-1][1] else front0
    p = F0.interpolate(f, normalized=True); a = F0.interpolate(max(0, f - 0.03), normalized=True); b = F0.interpolate(min(1, f + 0.03), normalized=True)
    tx, ty = (b.x - a.x) * math.cos(math.radians(p.y)), b.y - a.y; tl = math.hypot(tx, ty)
    nxv, nyv = ty / tl, -tx / tl
    if nxv < 0: nxv, nyv = -nxv, -nyv
    smp.append({'c': [round(p.x, 3), round(p.y, 3)], 'nE': round(nxv, 3), 'nN': round(nyv, 3)})
print(smp)
out['edge'].append({'n': 'ALLEGHENY FRONT', 'k': 'front', 'r': R(front), 'lab': [-78.42, 40.5], 'smp': smp, 'rise': 1300})   # rise: median measured across it
fall = edge('PIEDMONT', 'COASTAL PLAIN')[0]
out['edge'].append({'n': 'FALL LINE', 'k': 'fall', 'r': R(fall), 'lab': list(fall.interpolate(0.42, normalized=True).coords[0])})
mtn = chain(edge('BLUE RIDGE', 'PIEDMONT')[:1] + edge('VALLEY AND RIDGE', 'PIEDMONT')[:1] + edge('NEW ENGLAND', 'PIEDMONT')[:1])
print('mountain front', round(mtn.length, 2), mtn.coords[0], mtn.coords[-1])
out['edge'].append({'n': '', 'k': 'mtn', 'r': R(mtn)})
out['src'] = 'USGS Physiographic Divisions of the Conterminous U.S. (Fenneman & Johnson 1946); elevations GMRT'
s = json.dumps(out, separators=(',', ':')); open('city_ridges_geo.json', 'w').write(s); print(len(s), 'bytes')
