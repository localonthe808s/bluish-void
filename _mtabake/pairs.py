#!/usr/bin/env python3
"""Where a subway train is between two stations (user 2026-10-20: "yes build it from zoom 14, have them be aware of active delays
and alerts"). The subway's realtime feeds carry no coordinates, only each train's next station and when it gets there. This bakes,
from the MTA's static GTFS, for every route and every directional platform N: the station a train of that route most often comes
from (P), the scheduled run P -> N in seconds (median), and both stations' places along that route's track in
city_subway_shapes.json ('hi', metres at cos(40.7)) with the index of the line they lie on. The worker turns "due at N in 40 s"
into a place: sN - (sN - sP) * 40 / run.

    python3 pairs.py gtfs_subway.zip city_subway_shapes.json OUT.json      -> {"6|635N": [shapeRoute, li, sP, sN, run], ...}
(the W and the Z have no shapes of their own: they run on the N's / R's and the J's track, and borrow it)
"""
import csv, io, json, math, sys, zipfile, collections, statistics
Z = zipfile.ZipFile(sys.argv[1]); rd = lambda n: csv.DictReader(io.TextIOWrapper(Z.open(n), 'utf-8-sig'))
SH = json.load(open(sys.argv[2])); K = math.cos(math.radians(40.7)) * 111320; Y = 111320
pos = {}
for r in rd('stops.txt'): pos[r['stop_id']] = (float(r['stop_lon']) * K, float(r['stop_lat']) * Y)
t2r = {t['trip_id']: t['route_id'] for t in rd('trips.txt')}
def sec(h): a = h.split(':'); return int(a[0]) * 3600 + int(a[1]) * 60 + int(a[2])
seq = collections.defaultdict(list)
for r in rd('stop_times.txt'): seq[r['trip_id']].append((int(r['stop_sequence']), r['stop_id'], sec(r['arrival_time']), sec(r['departure_time'])))
pairs = collections.defaultdict(lambda: collections.defaultdict(list))
for tid, S in seq.items():
    rt = t2r.get(tid); S.sort()
    for a, b in zip(S, S[1:]):
        run = b[2] - a[3]
        if 20 <= run <= 1800: pairs[(rt, b[1])][a[1]].append(run)
lines = {}
for rt, v in SH.items():
    L = []
    for g in v['hi']:
        P = [(x * K, y * Y) for x, y in g]; S = [0.0]
        for i in range(1, len(P)): S.append(S[-1] + math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]))
        L.append((P, S))
    lines[rt] = L
def proj(L, p):
    P, S = L; best = None
    for i in range(1, len(P)):
        a, b = P[i - 1], P[i]; dx, dy = b[0] - a[0], b[1] - a[1]; l2 = dx * dx + dy * dy or 1e-9
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)); d = math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])
        if best is None or d < best[0]: best = (d, S[i - 1] + t * math.sqrt(l2))
    return best
out = {}; miss = collections.Counter()
for (rt, N), froms in pairs.items():
    cands = [c for c in ([rt, rt.rstrip('X')] + {'W': ['N', 'R', 'Q'], 'Z': ['J']}.get(rt, [])) if c in lines]
    if not cands or N not in pos: miss[rt] += 1; continue
    P = max(froms, key=lambda k: len(froms[k]))
    if P not in pos: continue
    run = int(statistics.median(froms[P]))
    best = None
    for ci, shape_rt in enumerate(cands):
        for li, L in enumerate(lines[shape_rt]):
            a = proj(L, pos[P]); b = proj(L, pos[N])
            if a and b and a[0] < 120 and b[0] < 120 and abs(b[1] - a[1]) > 50:
                sc = a[0] + b[0] + ci * 30                      # the route's own track first
                if best is None or sc < best[0]: best = (sc, shape_rt, li, a[1], b[1])
    if not best: miss[rt] += 1; continue
    out[rt + '|' + N] = [best[1], best[2], round(best[3]), round(best[4]), run]
json.dump(out, open(sys.argv[3], 'w'), separators=(',', ':'))
print(len(out), 'pairs; unplaced by route:', dict(miss))
