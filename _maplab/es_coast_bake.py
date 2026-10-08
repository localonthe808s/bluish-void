"""es_coast.json -- the coastline the globe, the EARTH SYSTEMS canvases and the hazard maps draw in green.

v2 (2026-10-07, user: "less straight lining, i want real coastline shapes"): Natural Earth 1:50m land rings
(public domain) across the Americas, lightly Douglas-Peucker'd, 3 decimals; the rest of the world keeps the
1:110m lines of v1 so the file stays small. Output: a list of lines, each a list of [lat, lon].

    python3 -I _maplab/es_coast_bake.py <ne_50m_land.geojson> <old es_coast.json> <out es_coast.json>
    ne_50m_land: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson
"""
import json, sys, math

def in_box(lat, lon):
    # the Americas incl. Greenland's east coast; Africa and Europe stay outside
    if lon < -180 or lon > -18: return False
    if lat > 58: return True
    return lon <= -28

def dp(pts, tol):
    if len(pts) < 3: return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0; L2 = dx * dx + dy * dy
    best, bi = -1, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        if L2 == 0: d = math.hypot(x - x0, y - y0)
        else:
            t = max(0, min(1, ((x - x0) * dx + (y - y0) * dy) / L2))
            d = math.hypot(x - (x0 + t * dx), y - (y0 + t * dy))
        if d > best: best, bi = d, i
    if best > tol: return dp(pts[:bi + 1], tol)[:-1] + dp(pts[bi:], tol)
    return [pts[0], pts[-1]]

land = json.load(open(sys.argv[1])); old = json.load(open(sys.argv[2]))
out, n = [], 0
for f in land['features']:
    g = f['geometry']; polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
    for p in polys:
        for ring in p:
            run = []
            for lon, lat in ring:
                if in_box(lat, lon): run.append((lat, lon))
                elif run: out.append(run); run = []
            if run: out.append(run)
keep = []
for ln in out:
    if len(ln) < 2: continue
    s = dp(ln, 0.0025)
    keep.append([[round(a, 3), round(b, 3)] for a, b in s]); n += len(s)
# the rest of the world from v1, with any point inside the box dropped (the 50m rings cover it)
m = 0
for ln in old:
    run = []
    for lat, lon in ln:
        if not in_box(lat, lon): run.append([lat, lon])
        elif run: keep.append(run); m += len(run); run = []
    if len(run) > 1: keep.append(run); m += len(run)
keep = [l for l in keep if len(l) > 1]
json.dump(keep, open(sys.argv[3], 'w'), separators=(',', ':'))
print(f'lines {len(keep)}  americas pts {n} (50m)  elsewhere pts {m} (110m)')
