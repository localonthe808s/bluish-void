#!/usr/bin/env python3
"""UNDERSEA FEATURES BY NAME (user 2026-10-16: "highlight all underwater geology like rivers and mountains especially on the
west coast"). The GEBCO Gazetteer of Undersea Feature Names (IHO-IOC SCUFN, served by NOAA NCEI at
www.ngdc.noaa.gov/gazetteer/feature, paged with &offset=) -- every feature named by the international committee, with its
point and, for about a third, its traced course or outline (a canyon's axis, a fracture zone, a seamount's footprint).
Kept: North America's seas (-180..-40, 5..80 N, and the Aleutians west of the date line).

Each feature: n (name as charted), k (class: 'ridge' the long structures, 'canyon' the underwater rivers, 'mount' the
underwater mountains, 'basin' the plains, troughs and banks), z (the zoom it is named from, by class and by size), c (its
point), g (its course or outline, simplified to ~200 m).

    python3 names.py gaz/na.json OUT.json
"""
import json, sys, math
from shapely import wkt
KIND = {'ridge': {'Ridge', 'Fracture Zone', 'Rise', 'Trench', 'Escarpment', 'Spur', 'Plateau', 'Province', 'Fan', 'Abyssal Plain', 'Terrace', 'Slope'},
        'canyon': {'Canyon', 'Valley', 'Seachannel', 'Sea Channel', 'Channel', 'Gap', 'Canyons', 'Gully', 'Moat'},
        'mount': {'Seamount', 'Seamounts', 'Guyot', 'Tablemount', 'Knoll', 'Knolls', 'Hill', 'Hills', 'Peak', 'Pinnacle', 'Mound', 'Seamount Chain', 'Reef', 'Shoal'},
        'basin': {'Basin', 'Trough', 'Bank', 'Hole', 'Deep', 'Depression', 'Sill', 'Saddle', 'Shelf', 'Plain'}}
def kind(t):
    for k, s in KIND.items():
        if t in s: return k
    return 'basin'
def main(src, out):
    F = json.load(open(src)); rows = []
    for f in F:
        t = f['type']['name']; nm = f['name'].strip()
        try: p = wkt.loads(f['geometry'])
        except Exception: continue
        c = p if p.geom_type == 'Point' else p.representative_point()
        g = None; ext = 0
        if f.get('secondaryGeometry'):
            try:
                s = wkt.loads(f['secondaryGeometry']).simplify(0.002)
                ext = max(s.bounds[2] - s.bounds[0], s.bounds[3] - s.bounds[1])
                if s.geom_type == 'LineString': g = {'l': [[[round(x, 3), round(y, 3)] for x, y in s.coords]]}
                elif s.geom_type == 'MultiLineString': g = {'l': [[[round(x, 3), round(y, 3)] for x, y in q.coords] for q in s.geoms]}
                elif s.geom_type == 'Polygon': g = {'p': [[[round(x, 3), round(y, 3)] for x, y in s.exterior.coords]]}
                elif s.geom_type == 'MultiPolygon': g = {'p': [[[round(x, 3), round(y, 3)] for x, y in q.exterior.coords] for q in s.geoms]}
            except Exception: g = None
        k = kind(t)
        # named from: the long structures at continental scale, the rest as they come into reach; size brings any of them in earlier
        z = {'ridge': 4, 'basin': 6, 'canyon': 6, 'mount': 7}[k]
        if ext > 3: z = min(z, 4)
        elif ext > 1: z = min(z, 5)
        elif ext > 0.4: z = min(z, 6)
        label = nm if nm.lower().endswith(t.lower()) else nm + ' ' + t
        r = {'n': label.upper(), 'k': k, 'z': z, 'c': [round(c.x, 3), round(c.y, 3)]}
        if g: r['g'] = g
        rows.append(r)
    rows.sort(key=lambda r: r['z'])
    json.dump({'src': 'GEBCO Gazetteer of Undersea Feature Names (IHO-IOC SCUFN), via NOAA NCEI', 'f': rows}, open(out, 'w'), separators=(',', ':'))
    print(len(rows), 'features')
if __name__ == '__main__': main(*sys.argv[1:3])
