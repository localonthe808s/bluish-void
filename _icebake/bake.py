#!/usr/bin/env python3
"""THE ICE AGE FOR ANY PLACE (user 2026-10-17: "can geology have glacial info like NYC did"). THE CITY shows where the ice
stopped (the Harbor Hill moraine), its kettles, erratics and flow; for the continent the equivalent is the ice sheet itself:
NADI-1, North American Deglacial Isochrones version 1 (Dalton et al. 2023, Quaternary Science Reviews; Zenodo
10.5281/zenodo.8161764, CC BY 4.0) -- the ice sheet's margin every 500 years from 25,000 to 1,000 calendar years ago, best
estimate ('OPTIMAL'). Each time step dissolved, holes kept, simplified to ~2 km, coordinates to 3 decimals.

    python3 bake.py NADI_DIR OUT.json
"""
import json, os, re, sys
import shapefile
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

def rings(g):
    out = []
    for p in (g.geoms if g.geom_type == 'MultiPolygon' else [g]):
        if p.is_empty or p.area < 0.01: continue
        out.append([[[round(x, 3), round(y, 3)] for x, y in p.exterior.coords]] + [[[round(x, 3), round(y, 3)] for x, y in r.coords] for r in p.interiors if len(r.coords) > 4])
    return out

def main(src, dst):
    steps = []
    for f in os.listdir(src):
        m = re.match(r'([\d.]+)ka_cal_OPTIMAL_.*\.shp$', f)
        if not m: continue
        ka = float(m.group(1))
        g = unary_union([shape(s.__geo_interface__).buffer(0) for s in shapefile.Reader(os.path.join(src, f)).iterShapes()])
        g = g.simplify(0.02, preserve_topology=True).buffer(0)
        steps.append({'ka': ka, 'p': rings(g)})
    steps.sort(key=lambda s: -s['ka'])
    json.dump({'src': 'NADI-1, Dalton et al. 2023 (QSR), CC BY 4.0, zenodo.org/records/8161764', 's': steps}, open(dst, 'w'), separators=(',', ':'))
    print(len(steps), 'steps', [s['ka'] for s in steps][:6], '...', os.path.getsize(dst) // 1024, 'KB')

if __name__ == '__main__': main(*sys.argv[1:3])
