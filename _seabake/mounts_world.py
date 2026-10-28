#!/usr/bin/env python3
"""THE WORLD'S SEAMOUNTS (user 2026-10-27: "can we show the highlight seamounts on COAST / SEA / OCEAN" + OCEAN as a global map).
names_v5.json covers North America's seas only (with traced summit rings); this adds every other underwater mountain the
GEBCO Gazetteer names (IHO-IOC SCUFN, via NOAA NCEI): seamounts, guyots, tablemounts, knolls, hills, peaks -- its point, its
outline where the gazetteer has one (about half), and the zoom it is named from by size.

    python3 mounts_world.py ~/sea_bake/gaz/all.json ~/sea_bake/gaz/na.json OUT.json   -> cdn seafloor/mounts_world_v1.json
"""
import json, sys
from shapely import wkt
MOUNT = {'Seamount', 'Seamounts', 'Guyot', 'Tablemount', 'Knoll', 'Knolls', 'Hill', 'Hills', 'Peak', 'Pinnacle', 'Mound', 'Seamount Chain'}
def main(src, na, out):
    have = {f['id'] for f in json.load(open(na))}; rows = []
    for f in json.load(open(src)):
        t = f['type']['name']
        if t not in MOUNT or f['id'] in have: continue
        try: p = wkt.loads(f['geometry'])
        except Exception: continue
        c = p if p.geom_type == 'Point' else p.representative_point()
        g = None; ext = 0
        if f.get('secondaryGeometry'):
            try:
                s = wkt.loads(f['secondaryGeometry']).simplify(0.005)
                ext = max(s.bounds[2] - s.bounds[0], s.bounds[3] - s.bounds[1])
                polys = [s] if s.geom_type == 'Polygon' else list(s.geoms) if s.geom_type == 'MultiPolygon' else []
                if polys: g = [[[round(x, 3), round(y, 3)] for x, y in q.exterior.coords] for q in polys]
            except Exception: g = None
        z = 3 if ext > 2 else 4 if ext > 0.8 else 5 if ext > 0.3 else 6
        nm = f['name'].strip(); label = nm if nm.lower().endswith(t.lower()) else nm + ' ' + t
        r = {'n': label.upper(), 'z': z, 'c': [round(c.x, 3), round(c.y, 3)]}
        if g: r['p'] = g
        rows.append(r)
    rows.sort(key=lambda r: r['z'])
    json.dump({'src': 'GEBCO Gazetteer of Undersea Feature Names (IHO-IOC SCUFN), via NOAA NCEI', 'f': rows}, open(out, 'w'), separators=(',', ':'))
    print(len(rows), 'mounts outside North America')
if __name__ == '__main__': main(*sys.argv[1:4])
