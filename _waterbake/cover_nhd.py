#!/usr/bin/env python3
"""THE NHD COVER (2026-11-07): the z13 tiles (~5 km) lying wholly inside the states already baked. The page skips OpenStreetMap's inland
water only on those tiles and draws NHD's there; a tile that crosses a state line or the border keeps OpenStreetMap's (the far side of the
line has no NHD of ours yet). Census cartographic boundaries (cb_2023_us_state_500k, public domain).

    python3 cover_nhd.py STATES.shp OUT.json "New York" ["Vermont" ...]
"""
import json, math, sys
import shapefile, shapely
from shapely.geometry import shape, box
from shapely.ops import unary_union
R = 6378137.0; S = 2 * math.pi * R; Z = 13
shp, out, names = sys.argv[1], sys.argv[2], set(sys.argv[3:])
rd = shapefile.Reader(shp); fi = [f[0] for f in rd.fields[1:]]; ni = fi.index('NAME')
polys = [shape(sr.shape.__geo_interface__) for sr in rd.shapeRecords() if sr.record[ni] in names]
U = unary_union(polys)
def merc(xy):
    import numpy as np
    lon = xy[:, 0]; lat = np.clip(xy[:, 1], -85, 85)
    return np.column_stack([np.radians(lon) * R, np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * R])
UM = shapely.transform(U, merc); shapely.prepare(UM)
ts = S / 2 ** Z; x0, y0, x1, y1 = UM.bounds; cells = []
for tx in range(int((x0 + S / 2) // ts), int((x1 + S / 2) // ts) + 1):
    for ty in range(int((S / 2 - y1) // ts), int((S / 2 - y0) // ts) + 1):
        bx0 = -S / 2 + tx * ts; by1 = S / 2 - ty * ts
        if UM.contains(box(bx0, by1 - ts, bx0 + ts, by1)): cells.append('%d/%d' % (tx, ty))
json.dump({'z': Z, 'states': sorted(names), 'cells': cells}, open(out, 'w'), separators=(',', ':'))
print(len(cells), 'cells,', sorted(names))
