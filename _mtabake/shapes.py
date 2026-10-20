#!/usr/bin/env python3
"""The subway's track as the MTA draws it, for LOCAL's lines (user 2026-10-19: "are the subway lines accurately drawn at every
level?" -> "yes do it, and fill in the missing route colors"). city_subway_lines.json (THE CITY's) is station-to-station: within
1 m median and 8-9 m worst of the MTA's shapes, but 3-7 px off on a curve at z16-17, and seven routes lacked some of their service
patterns (the 5 on the Flatbush branch, the A to Rockaway Park, the F's and E's reroutes...). This reads every shape in the MTA's
static GTFS, per route, keeps a variant only where it adds track the route's kept shapes do not already run within 4 m of, and
writes two levels: 'lo' simplified to ~8 m (z<=15, as before) and 'hi' to ~1 m (z16+). Coordinates [lon, lat] at 5 decimals.

    python3 shapes.py gtfs_subway.zip OUT.json
"""
import csv, io, json, math, sys, zipfile, collections
from shapely.geometry import LineString, Point
Z = zipfile.ZipFile(sys.argv[1])
rd = lambda n: csv.DictReader(io.TextIOWrapper(Z.open(n), 'utf-8-sig'))
K = math.cos(math.radians(40.7)); M = 111320.0
S = collections.defaultdict(list)
for r in rd('shapes.txt'): S[r['shape_id']].append((int(r['shape_pt_sequence']), float(r['shape_pt_lon']), float(r['shape_pt_lat'])))
by = collections.defaultdict(list)
for sid, pts in S.items():
    pts.sort(); L = LineString([(lo * M * K, la * M) for _, lo, la in pts])
    if L.length > 50: by[sid.split('.')[0]].append(L)
out = {}
for rt, Ls in by.items():
    Ls.sort(key=lambda l: -l.length); kept = []
    for L in Ls:
        # the part of L not already run by a kept shape (sampled every 15 m)
        n = max(2, int(L.length / 15)); new = []
        for i in range(n + 1):
            p = L.interpolate(i / n, normalized=True); new.append(not any(k.distance(p) < 4 for k in kept))
        if not kept or sum(new) > 6: kept.append(L)
    def ll(G, tol): return [[[round(x / (M * K), 5), round(y / M, 5)] for x, y in g.simplify(tol).coords] for g in G]
    out[rt] = {'lo': ll(kept, 8), 'hi': ll(kept, 1)}
json.dump(out, open(sys.argv[2], 'w'), separators=(',', ':'))
print({k: (len(v['lo']), sum(len(s) for s in v['lo']), sum(len(s) for s in v['hi'])) for k, v in sorted(out.items())})
