#!/usr/bin/env python3
"""THE GREEN COAST, FROM THE REAL COASTLINE (user 2026-10-16: "refine the green trim to the real coastlines").

The first trim (2026-10-16) stroked the basemap's 'earth' layer. Two faults showed at z9-11 around Charleston: the archive
generalizes that layer hard per zoom (St Helena Sound came out as long straight jags), and OpenStreetMap closes every river
mouth and inlet with a straight CLOSING LINE across the water (the Stono, the Kiawah), which the stroke drew as a green
bar over open water.

This bakes our own from the full-resolution OSM coastline (osmdata.openstreetmap.de coastlines-split-4326, refreshed
daily, ODbL):
  - North America, Greenland, the Caribbean and Hawaii: lon < -50, or north of 59 N west of -11 (Greenland) minus Iceland;
    South America's Caribbean shore and the Atlantic islands are left out.
  - CLOSING LINES DROPPED. Segment length cannot tell them apart (measured around Charleston: Hunting Island's beach is
    mapped in 1.4-1.6 km straight segments, Breach Inlet's closing line is 1.4 km), so they are found the way OSM defines
    them: a closing line is where a river or estuary WATER AREA meets the coastline, so its LAND side is water. In this
    file the sea is on the LEFT of each line (checked on Myrtle Beach: running south-west, ocean to the south-east), so
    every coastline segment of 60 m or more (south of 62 N) whose point 30 m to its RIGHT lies inside a non-ocean water
    polygon of our own basemap (the z11 tiles of tiles.bluishvoid.com, the same OSM water the map draws) is dropped. A real
    shore has land there. Tested by eye on Charleston (inlets dropped, beaches kept), the Chesapeake (tributary mouths
    dropped, 600 miles of tidal banks kept; a midpoint-near-water test had wrongly dropped 15,000 bank segments) and New
    York (the Hudson's closing line at Inwood dropped). Shorter ones are under a pixel at every baked zoom.
  - per data zoom z3-10, simplified to a third of a pixel, features under 1.5 px across dropped (islets at continental
    scale), cut into MVT tiles (layer 'coast'). The page overzooms z10 as vector, so it stays sharp to street level.

    python3 bake.py coastlines-split-4326/lines.shp OUTDIR [water11.pkl cache]
"""
import gzip, math, os, sys
import numpy as np, shapefile
import mapbox_vector_tile
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import transform
from shapely.strtree import STRtree

def na(lon, lat):
    if lon > 0: return False
    if 63 <= lat <= 67 and -25 <= lon <= -13: return False            # Iceland
    if lon < -50: return not (lat < 12.6 and -77.3 < lon < -59 and not (                # South America's north shore...
        (-70.2 <= lon <= -68.2 and lat >= 11.9) or (-62 <= lon <= -60.4 and lat >= 10) or (-61.9 <= lon <= -61.3 and lat >= 11.9)))  # ...but keep ABC, Trinidad-Tobago, Grenada
    return lat > 59 and lon < -11                                     # Greenland

def in_hudson(lon, lat):
    """the corridor of _maplab/coast_bake/hudson_cut.py (2026-10-11), Battery to Troy"""
    if lat < 40.705 or lat > 42.80: return False
    if lat < 40.86: return -74.05 < lon < (-74.017 + (lat - 40.70) * 0.6)
    if lat < 41.1: return -73.99 < lon < -73.84
    if lat < 41.6: return -74.04 < lon < -73.84
    return -74.08 < lon < -73.60

def outer_only(lines, mouth=4.0, minpath=8.0, ratio=3.0, step=0.25):
    """THE GREEN STAYS ON THE OUTER LAND (user 2026-10-16: "is there a way you could break up the line and not have the line
    cross over the water ... maybe just let the green stick to the outer land"). Where the coastline wanders into a water
    body through a mouth under `mouth` km and comes back out more than max(`minpath`, `ratio` x the mouth) km of shore
    later, that stretch is an inlet, sound or estuary interior and is dropped: the line breaks at the mouth, nothing crosses.
    Inlet or peninsula is told by the turn: the sea is on the LEFT of each line, so a loop that encloses water runs
    COUNTER-CLOCKWISE (positive signed area, x east / y north) and is cut; a peninsula's loop runs clockwise and stays.
    Works on the merged lines, resampled to ~250 m for the neighbour search."""
    from scipy.spatial import cKDTree
    from shapely.ops import linemerge
    merged = linemerge(MultiLineString(lines)) if len(lines) > 1 else lines[0]
    merged = list(merged.geoms) if merged.geom_type == 'MultiLineString' else [merged]
    out, cut_km = [], 0.0
    for ln in merged:
        P = np.asarray(ln.coords)
        if len(P) < 4: out.append(ln); continue
        X = P[:, 0] * 111.32 * np.cos(np.radians(P[:, 1])); Y = P[:, 1] * 111.32
        sl = np.concatenate([[0], np.cumsum(np.hypot(np.diff(X), np.diff(Y)))])
        if sl[-1] < minpath: out.append(ln); continue
        keep = [0]
        for i in range(1, len(P)):
            if sl[i] - sl[keep[-1]] >= step: keep.append(i)
        keep = np.array(keep)
        if len(keep) < 4: out.append(ln); continue
        tree = cKDTree(np.column_stack([X[keep], Y[keep]]))
        drop = np.zeros(len(P), bool); intervals = []
        for a, nb in enumerate(tree.query_ball_point(np.column_stack([X[keep], Y[keep]]), mouth)):
            i = keep[a]; far = None
            for b in nb:
                if b <= a: continue
                j = keep[b]; d = math.hypot(X[j] - X[i], Y[j] - Y[i]); ds = sl[j] - sl[i]
                if ds > max(minpath, ratio * max(d, 0.05)) and (far is None or j > far): far = j
            if far is None: continue
            xs, ys = X[i:far + 1], Y[i:far + 1]
            area = 0.5 * (np.dot(xs[:-1], ys[1:]) - np.dot(xs[1:], ys[:-1]) + xs[-1] * ys[0] - xs[0] * ys[-1])
            if area > 0: intervals.append((i, far))
        for i, j in intervals: drop[i + 1:j] = True
        cut_km += float(np.sum(np.diff(sl)[drop[1:] & drop[:-1]]))
        run = []
        for k in range(len(P)):
            if drop[k]:
                if len(run) > 1: out.append(LineString(run))
                run = []
            else: run.append(P[k])
        if len(run) > 1: out.append(LineString(run))
    print('outer coast: %d lines, %.0f km of inlet and sound shores dropped' % (len(out), cut_km), flush=True)
    return out

def water11(tiles, cache):
    """non-ocean water polygons (lon/lat) from the basemap's z11 tiles, cached"""
    import pickle, urllib.request
    from concurrent.futures import ThreadPoolExecutor
    from shapely.geometry import shape as _shape
    have = pickle.load(open(cache, 'rb')) if os.path.exists(cache) else {}
    def get(t):
        x, y = t
        u = 'https://tiles.bluishvoid.com/bluish-basemap-20260829/11/%d/%d.mvt' % (x, y)
        for a in range(4):
            try:
                raw = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluishvoid coast bake', 'Origin': 'https://bluishvoid.com'}), timeout=60).read()
                break
            except Exception:
                if a == 3: return t, []
        if raw[:2] == b'\x1f\x8b': raw = gzip.decompress(raw)
        L = mapbox_vector_tile.decode(raw).get('water', {})
        w, s_, e, nn = tile_bounds(11, x, y)
        ys, yn = math.log(math.tan(math.pi / 4 + math.radians(s_) / 2)), math.log(math.tan(math.pi / 4 + math.radians(nn) / 2))
        ext = L.get('extent', 4096); out = []
        for f in L.get('features', []):
            if f['properties'].get('kind') == 'ocean' or f['geometry']['type'] not in ('Polygon', 'MultiPolygon'): continue
            g = _shape(f['geometry'])
            g = transform(lambda X, Y, Z=None: (w + np.asarray(X) / ext * (e - w), np.degrees(2 * np.arctan(np.exp(ys + np.asarray(Y) / ext * (yn - ys))) - np.pi / 2)), g)
            out.append(g.wkb)
        return t, out
    need = [t for t in tiles if t not in have]
    with ThreadPoolExecutor(24) as ex:
        for k, (t, polys) in enumerate(ex.map(get, need)):
            have[t] = polys
            if k % 1000 == 999: print('  water tiles', k + 1, '/', len(need), flush=True); pickle.dump(have, open(cache, 'wb'))
    pickle.dump(have, open(cache, 'wb'))
    from shapely import wkb as _wkb
    return [_wkb.loads(b) for t in tiles for b in have.get(t, [])]

def lonlat_tile(lon, lat, z):
    n = 2 ** z; lat = max(-85, min(85, lat))
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

def tile_bounds(z, x, y):
    n = 2 ** z
    w = x / n * 360 - 180; e = (x + 1) / n * 360 - 180
    nn = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n)))); s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return w, s, e, nn

merc = lambda g: transform(lambda X, Y, Z=None: (np.radians(X), np.log(np.tan(np.pi / 4 + np.radians(np.clip(Y, -85, 85)) / 2))), g)

def main(shp, out, cache=None):
    raw = []
    for sr in shapefile.Reader(shp).iterShapes():
        b = sr.bbox; cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if not na(cx, cy): continue
        pts = sr.points; parts = list(sr.parts) + [len(pts)]
        for i in range(len(parts) - 1):
            seg = np.asarray(pts[parts[i]:parts[i + 1]], float)
            if len(seg) > 1: raw.append(seg)
    print('lines', len(raw), flush=True)
    # candidate closing segments: 60 m or more, south of 62 N; the probe is 30 m to the right (the land side)
    probes, owner = [], []
    for li, P in enumerate(raw):
        k = np.cos(np.radians(P[:, 1]))[:-1]
        vx = (P[1:, 0] - P[:-1, 0]) * k * 111320.0; vy = (P[1:, 1] - P[:-1, 1]) * 111320.0; d = np.hypot(vx, vy) + 1e-9
        m = (P[1:] + P[:-1]) / 2
        rx = m[:, 0] + (vy / d) * 30 / (111320.0 * k); ry = m[:, 1] - (vx / d) * 30 / 111320.0
        for si in np.nonzero((d >= 60) & (m[:, 1] < 62))[0]: probes.append((rx[si], ry[si])); owner.append((li, si))
    probes = np.array(probes); print('candidate segments', len(probes), flush=True)
    tiles = sorted({lonlat_tile(x, y, 11) for x, y in probes})
    polys = water11(tiles, cache or os.path.join(out, '..', 'water11.pkl'))
    from shapely import make_valid
    polys = [make_valid(q) for q in polys]                   # the tiles carry a few self-touching rings (one at -128.03, 52.15)
    print('water polygons', len(polys), flush=True)
    # fast: an index over the PROBES, each water polygon picks its candidates by box, then one vectorized point-in-polygon
    from shapely import points as _points, contains_xy
    ptree = STRtree(_points(probes)); inside = set()
    for k, q in enumerate(polys):
        idx = ptree.query(q)
        if len(idx): inside.update(idx[contains_xy(q, probes[idx, 0], probes[idx, 1])].tolist())
        if k % 3000 == 2999: print('  polygons tested', k + 1, flush=True)
    cut = {}
    for qi in sorted(inside): li, si = owner[qi]; cut.setdefault(li, set()).add(si)
    # THE HUDSON IS NOT TRIMMED (user 2026-10-16: "cut the hudson from the coast trim too", as THE CITY's trims were on
    # 2026-10-11): every segment inside the Battery-to-Troy corridor of _maplab/coast_bake/hudson_cut.py is dropped
    nh = 0
    for li, P in enumerate(raw):
        m = (P[1:] + P[:-1]) / 2
        if not ((P[:, 1] > 40.70).any() and (P[:, 1] < 42.80).any() and (P[:, 0] > -74.08).any() and (P[:, 0] < -73.60).any()): continue
        for si in range(len(m)):
            if in_hudson(m[si, 0], m[si, 1]): cut.setdefault(li, set()).add(si); nh += 1
    print('hudson segments dropped', nh, flush=True)
    print('closing segments dropped', sum(len(v) for v in cut.values()), flush=True)
    lines = []
    for li, P in enumerate(raw):
        cs = cut.get(li)
        if not cs: lines.append(LineString(P)); continue
        cur = [P[0]]
        for si in range(len(P) - 1):
            if si in cs:
                if len(cur) > 1: lines.append(LineString(cur))
                cur = [P[si + 1]]
            else: cur.append(P[si + 1])
        if len(cur) > 1: lines.append(LineString(cur))
    lines = outer_only(lines)
    n_t = 0
    for z in range(3, 11):
        px = 360.0 / (256 * 2 ** z)
        geoms = []
        for g in lines:
            b = g.bounds
            if max(b[2] - b[0], b[3] - b[1]) < px * 1.5: continue
            s = g.simplify(px / 3, preserve_topology=False)
            if not s.is_empty: geoms.append(s)
        tree = STRtree(geoms)
        tiles = set()
        for g in geoms:
            b = g.bounds
            x0, y1 = lonlat_tile(b[0], b[1], z); x1, y0 = lonlat_tile(b[2], b[3], z)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1): tiles.add((x, y))
        cnt = 0
        for x, y in tiles:
            w, s_, e, nn = tile_bounds(z, x, y)
            pad = (e - w) * 4 / 256
            bb = box(w - pad, s_ - pad, e + pad, nn + pad)
            fs = []
            for i in tree.query(bb):
                gi = geoms[i].intersection(bb)
                if gi.is_empty or gi.geom_type not in ('LineString', 'MultiLineString', 'GeometryCollection'): continue
                if gi.geom_type == 'GeometryCollection':
                    ls = [q for q in gi.geoms if q.geom_type == 'LineString']
                    if not ls: continue
                    gi = MultiLineString(ls)
                fs.append({'geometry': merc(gi).wkb, 'properties': {}})
            if not fs: continue
            data = mapbox_vector_tile.encode([{'name': 'coast', 'features': fs}],
                                             default_options={'quantize_bounds': merc(box(w, s_, e, nn)).bounds, 'extents': 4096, 'y_coord_down': False})
            p = os.path.join(out, str(z), str(x)); os.makedirs(p, exist_ok=True)
            open(os.path.join(p, '%d.mvt' % y), 'wb').write(data); cnt += 1
        n_t += cnt
        print('z%d: %d lines, %d tiles' % (z, len(geoms), cnt), flush=True)
    print('tiles', n_t)

if __name__ == '__main__':
    main(*sys.argv[1:4])
