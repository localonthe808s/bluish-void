#!/usr/bin/env python3
"""NYC'S STREET TREES BY NEIGHBORHOOD (user 2026-10-29: option 1 -- shade each neighborhood by its leading street tree instead of drawing
683,000 points). The 2015 Street Tree Census (NYC Parks, open data uvpi-gqnh), live trees only, counted inside each 2020 Neighborhood
Tabulation Area of city_nta2020.json (point in polygon): each NTA's top six species with their shares and the tree count.
    python3 nyc_nta.py census.csv city_nta2020.json OUT.json      -> cdn trees/nyc_nta_v1.json"""
import csv, json, sys, collections
from shapely.geometry import shape, Point, MultiPolygon, Polygon
from shapely.strtree import STRtree
def main(src, nta, out):
    A = json.load(open(nta))['a']; polys = []; ids = []
    for r in A:
        rings = r[9]; ps = [Polygon(p[0], p[1:]) for p in rings]; g = MultiPolygon(ps).buffer(0); polys.append(g); ids.append(r[0])
    tree = STRtree(polys); C = collections.defaultdict(collections.Counter); n = 0
    for row in csv.DictReader(open(src)):
        if row.get('status') != 'Alive' or not row.get('spc_common'): continue
        try: p = Point(float(row['longitude']), float(row['latitude']))
        except Exception: continue
        for k in tree.query(p):
            if polys[k].contains(p): C[ids[k]][row['spc_common'].strip().lower()] += 1; n += 1; break
    outd = {}
    for i, c in C.items():
        tot = sum(c.values()); outd[i] = {'t': tot, 's': [[sp, round(v / tot * 100, 1)] for sp, v in c.most_common(6)]}
    lead = collections.Counter(v['s'][0][0] for v in outd.values())
    json.dump({'src': '2015 Street Tree Census, NYC Parks (NYC Open Data uvpi-gqnh), live trees', 'nta': outd, 'lead': lead.most_common()}, open(out, 'w'), separators=(',', ':'))
    print(n, 'trees in', len(outd), 'neighborhoods; leading species:', lead.most_common(12))
if __name__ == '__main__': main(*sys.argv[1:4])
