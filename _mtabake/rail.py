#!/usr/bin/env python3
"""The LIRR's and Metro-North's track for LOCAL (user 2026-10-19: "we dont show the MNR / LIRR train lines" -- their live trains
were dots on no line). Both railroads' static GTFS (rrgtfsfeeds.s3.amazonaws.com/gtfslirr.zip, gtfsmnr.zip): every shape, joined
to its route through trips.txt, the route's own published color; per route a shape is kept only where it adds track the route's
kept shapes do not already run within 6 m of. Two levels as the subway's: ~8 m ('p', z<=15) and ~1.5 m ('ph', z16+).

    python3 rail.py gtfslirr.zip gtfsmnr.zip OUT.json
"""
import csv, io, json, math, sys, zipfile, collections
from shapely.geometry import LineString
K = math.cos(math.radians(40.8)); M = 111320.0
out = []
for path, rr in ((sys.argv[1], 'LIRR'), (sys.argv[2], 'MNR')):
    Z = zipfile.ZipFile(path); rd = lambda n: csv.DictReader(io.TextIOWrapper(Z.open(n), 'utf-8-sig'))
    routes = {r['route_id']: r for r in rd('routes.txt')}
    s2r = {}
    for t in rd('trips.txt'):
        if t.get('shape_id'): s2r.setdefault(t['shape_id'], collections.Counter())[t['route_id']] += 1
    S = collections.defaultdict(list)
    for r in rd('shapes.txt'): S[r['shape_id']].append((int(r['shape_pt_sequence']), float(r['shape_pt_lon']), float(r['shape_pt_lat'])))
    by = collections.defaultdict(list)
    for sid, pts in S.items():
        if sid not in s2r: continue
        pts.sort(); L = LineString([(lo * M * K, la * M) for _, lo, la in pts])
        if L.length > 200: by[s2r[sid].most_common(1)[0][0]].append(L)
    for rid, Ls in by.items():
        Ls.sort(key=lambda l: -l.length); kept = []
        for L in Ls:
            n = max(2, int(L.length / 40))
            fresh = sum(1 for i in range(n + 1) if not any(k.distance(L.interpolate(i / n, normalized=True)) < 6 for k in kept))
            if not kept or fresh > 3: kept.append(L)
        rt = routes.get(rid, {}); c = '#' + (rt.get('route_color') or '808183')
        nm = rt.get('route_long_name') or rt.get('route_short_name') or rid
        ll = lambda g, tol: [[round(x / (M * K), 5), round(y / M, 5)] for x, y in g.simplify(tol).coords]
        for L in kept: out.append({'rr': rr, 'n': nm, 'c': c, 'p': ll(L, 8), 'ph': ll(L, 1.5)})
json.dump(out, open(sys.argv[3], 'w'), separators=(',', ':'))
print(len(out), 'lines;', collections.Counter(o['rr'] for o in out), sum(len(o['p']) for o in out), 'lo pts,', sum(len(o['ph']) for o in out), 'hi pts')
