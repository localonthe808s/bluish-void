#!/usr/bin/env python3
"""CAVE ENTRANCE COUNTS BY CELL (user 2026-11-07: "is there a specific number? i dont like the vague 50,000+"). No authoritative national
cave count exists (state survey tallies disagree by tens of thousands), so the CAVES tab states counts it can measure exactly: the OpenStreetMap
cave entrances (ODbL) within 100 mi of the place. This bins caves.geojsonl (osm_caves_build.py's output) into 0.25-degree cells:
{"s": 0.25, "c": {"lat_i,lon_i": [entrances, show caves]}} where lat_i = floor(lat / 0.25).

    python3 cave_cells.py caves.geojsonl cave_cells_v1.json
"""
import json, math, sys, collections
def main(src, out):
    C = collections.defaultdict(lambda: [0, 0]); n = 0
    for ln in open(src):
        ln = ln.strip()
        if not ln: continue
        f = json.loads(ln); g = f.get('geometry') or {}; c = g.get('coordinates')
        if not c: continue
        k = '%d,%d' % (math.floor(c[1] / .25), math.floor(c[0] / .25)); C[k][0] += 1; n += 1
        if (f.get('properties') or {}).get('show'): C[k][1] += 1
    json.dump({'s': .25, 'n': n, 'c': C}, open(out, 'w'), separators=(',', ':'))
    print('entrances', n, 'cells', len(C))
if __name__ == '__main__': main(sys.argv[1], sys.argv[2])
