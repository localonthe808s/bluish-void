#!/usr/bin/env python3
"""ALBANY RURAL CEMETERY INTO THE CITY'S CEMETERY FILES (2026-11-12, user: "is there a high detailed map of the tombs in these cemetaries in albany
like we did for the bake in NYC cemetaries" -> "i only need the cemetary in the photo for albany").

Stones: detected in New York State's orthoimagery (NYS ITS, orthos.its.ny.gov, latest year covering Albany, ~25 cm) by alb_detect.py: a pale
grey spot brighter than its 3 m surroundings, 2-90 px, not dry-grass yellow, with a dark shadow within ~1.5 m to its northwest (spring sun in
the southeast), outside tree shadows and off the OSM drives. Appended to /city_stones.json in its own encoding (2 m positions, 512 m cells,
keyed by cell). Grounds, drives (service/track, 4.5 m) and footpaths (path/footway) from OpenStreetMap appended to /city_cemeteries.json.
Re-running is safe: stones already present are skipped, the cemetery is added once.

    python3 _cembake/alb_ortho.py <ortho dir>            (16 tiles of 2,000 px, 25 cm, one at a time)
    python3 _cembake/alb_detect.py <ortho dir> <osm.json> <out dir> 34 25
    python3 _cembake/albany_merge.py <stones_px.npy> <ortho grid.txt> <osm.json> <repo root>
"""
import base64, json, os, sys
import numpy as np

SP, GRID, OSM, ROOT = sys.argv[1:5]
X0, Y1, RES = [float(v) for v in open(GRID).read().split()[:3]]
P = np.load(SP)
X = X0 + P[:, 0] * RES
Y = Y1 - P[:, 1] * RES

st = json.load(open(os.path.join(ROOT, 'city_stones.json')))
cz = st['cell']
cells = {}
for x, y in zip(X, Y):
    i, j = int((x - st['x0']) // cz), int((y - st['y0']) // cz)
    bx, by = st['x0'] + i * cz, st['y0'] + j * cz
    cells.setdefault((i, j), set()).add((min(255, int((x - bx) // 2)), min(255, int((y - by) // 2))))
added = 0
for (i, j), pts in cells.items():
    key = '%d,%d' % (i, j)
    old = bytearray(base64.b64decode(st['c'][key])) if key in st['c'] else bytearray()
    have = set((old[q], old[q + 1]) for q in range(0, len(old) - 1, 2))
    new = sorted(pts - have)
    added += len(new)
    for a, b in new:
        old += bytes([a, b])
    st['c'][key] = base64.b64encode(bytes(old)).decode()
st['n'] = st['n'] + added
json.dump(st, open(os.path.join(ROOT, 'city_stones.json'), 'w'), separators=(',', ':'))

cm = json.load(open(os.path.join(ROOT, 'city_cemeteries.json')))
d = json.load(open(OSM))['elements']
r5 = lambda g: [round(g['lon'], 5), round(g['lat'], 5)]
cem = [e for e in d if e.get('tags', {}).get('landuse') == 'cemetery'][0]
first = r5(cem['geometry'][0])
if not any(poly and poly[0] and poly[0][0] == first for poly in cm['c']):
    cm['c'].append([[r5(g) for g in cem['geometry']]])
    for e in d:
        hw = e.get('tags', {}).get('highway')
        if hw in ('service', 'track'):
            cm['d'].append([r5(g) for g in e['geometry']])
        elif hw in ('path', 'footway'):
            cm['p'].append([r5(g) for g in e['geometry']])
json.dump(cm, open(os.path.join(ROOT, 'city_cemeteries.json'), 'w'), separators=(',', ':'))
print('stones added', added, 'total', st['n'], '| cemeteries', len(cm['c']), 'drives', len(cm['d']), 'paths', len(cm['p']))
