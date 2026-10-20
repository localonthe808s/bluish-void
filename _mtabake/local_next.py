#!/usr/bin/env python3
"""Each subway platform's NEXT LOCAL STOP, for the boards' LOCAL / EXPRESS split (user 2026-10-19: "say UPTOWN LOCAL UPTOWN
EXPRESS"). From the MTA's static GTFS (rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip): for every directional platform (stop_id
with its N/S), every distinct stop that a scheduled trip calls at next; the nearest of them is the local stop. A live train
whose next stop is a different, farther one is running express past it -- the board reads that off the realtime feed's own
stop list, so a 4 running local overnight or a rerouted train is named for what it is doing. Kept only where a platform has
more than one next stop (about the express stations); elsewhere every train is simply the local.

    python3 local_next.py gtfs_subway.zip OUT.json
"""
import csv, io, json, math, sys, zipfile, collections
Z = zipfile.ZipFile(sys.argv[1])
rd = lambda n: csv.DictReader(io.TextIOWrapper(Z.open(n), 'utf-8-sig'))
pos = {r['stop_id']: (float(r['stop_lat']), float(r['stop_lon'])) for r in rd('stops.txt')}
seq = collections.defaultdict(list)
for r in rd('stop_times.txt'): seq[r['trip_id']].append((int(r['stop_sequence']), r['stop_id']))
nxt = collections.defaultdict(collections.Counter)
for t, s in seq.items():
    s.sort()
    for (a, x), (b, y) in zip(s, s[1:]): nxt[x][y] += 1
def dist(a, b):
    (la1, lo1), (la2, lo2) = pos[a], pos[b]; return math.hypot((la2 - la1) * 111.32, (lo2 - lo1) * 111.32 * math.cos(math.radians(la1)))
out = {}
for x, C in nxt.items():
    if len(C) < 2 or x not in pos: continue
    cand = [y for y, n in C.items() if y in pos and n >= 5]                # a stray reroute is not a pattern
    if len(cand) < 2: continue
    out[x] = min(cand, key=lambda y: dist(x, y))
json.dump(out, open(sys.argv[2], 'w'), separators=(',', ':'), sort_keys=True)
print(len(out), 'platforms with a local and an express next stop')
