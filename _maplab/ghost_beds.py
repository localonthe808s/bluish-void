#!/usr/bin/env python3
"""STREAM BEDS, TAPERED (user 2026-10-29: "refine the widths and make sure it's refined"). Each buried course in ghost-rivers.json becomes a
teal bed in ghost-marsh.json (bed: 1) whose width grows from its source to its mouth, the way a stream widens downstream:
  - the MOUTH is the end nearest the 1865-era water -- today's shore, or another course it joins; the other end is the source;
  - width at the source 5 m, at the mouth 7 m + 1 m per 60 m of course, capped 9-26 m, along (s / L) ^ 0.7;
  - the course is smoothed first (running mean + Chaikin x2) so the bed's edges are curves, not the tracer's kinks;
  - the bed is the union of round sections every 3 m (each pair's hull), simplified to 0.6 m.
    python3 _maplab/ghost_beds.py      (rewrites the bed: 1 features of ghost-marsh.json in place)"""
import json, math, os
import numpy as np
from shapely.geometry import shape, mapping, Point, Polygon, LineString
from shapely.ops import unary_union, transform
from shapely.strtree import STRtree
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..')
K = math.cos(math.radians(40.75))
to_m = lambda x, y, z=None: (x * 111320 * K, y * 110540)
to_d = lambda x, y, z=None: (x / (111320 * K), y / 110540)

def smooth(c):
    P = np.array(c, float)
    if len(P) > 7: P = np.vstack([P[:1], [P[max(0, i - 3):i + 4].mean(0) for i in range(1, len(P) - 1)], P[-1:]])
    for _ in range(2):
        o = [P[0]]
        for a, b in zip(P[:-1], P[1:]): o += [a * .75 + b * .25, a * .25 + b * .75]
        o.append(P[-1]); P = np.array(o)
    return P

def main():
    R = json.load(open(os.path.join(ROOT, 'ghost-rivers.json'))); M = json.load(open(os.path.join(ROOT, 'ghost-marsh.json')))
    shore = unary_union([Polygon(r).buffer(0) for b in json.load(open(os.path.join(ROOT, 'city_boroughs.json')))['hi'] for r in b['r'] if len(r) > 3])
    shore = transform(to_m, shore).boundary
    lines = []
    for f in R['features']:
        g = shape(f['geometry'])
        for part in (g.geoms if hasattr(g, 'geoms') else [g]):
            if part.geom_type == 'LineString' and len(part.coords) > 1: lines.append((f['properties'].get('src', 'Viele 1865'), transform(to_m, part)))
    tree = STRtree([l for _, l in lines])
    beds = {}
    for i, (src, l) in enumerate(lines):
        a, b = Point(l.coords[0]), Point(l.coords[-1])
        def reach(p):   # how close this end is to water: the shore, or another course
            d = shore.distance(p)
            for j in tree.query(p.buffer(40)):
                if j != i: d = min(d, lines[j][1].distance(p))
            return d
        C = smooth(list(l.coords) if reach(b) <= reach(a) else list(l.coords)[::-1])   # source first
        seg = np.hypot(*np.diff(C, axis=0).T); s = np.concatenate([[0], np.cumsum(seg)]); L = s[-1]
        if L < 5: continue
        wm = min(26, max(9, 7 + L / 60))
        n = max(2, int(L / 3)); ss = np.linspace(0, L, n)
        X = np.interp(ss, s, C[:, 0]); Y = np.interp(ss, s, C[:, 1])
        W = 5 + (wm - 5) * (ss / L) ** 0.7
        circ = [Point(x, y).buffer(w / 2, 12) for x, y, w in zip(X, Y, W)]
        beds.setdefault(src, []).append(unary_union([unary_union([circ[k], circ[k + 1]]).convex_hull for k in range(len(circ) - 1)]))
    M['features'] = [f for f in M['features'] if not f['properties'].get('bed')]
    n = 0
    for src, polys in beds.items():
        u = transform(to_d, unary_union(polys).simplify(0.6))
        for p in (u.geoms if hasattr(u, 'geoms') else [u]):
            gj = mapping(p); gj = {'type': 'Polygon', 'coordinates': [[[round(x, 6), round(y, 6)] for x, y in r] for r in gj['coordinates']]}
            M['features'].append({'type': 'Feature', 'properties': {'src': src, 'bed': 1, 'boro': 'Manhattan' if 'Viele' in src else 'outer boroughs'}, 'geometry': gj}); n += 1
    json.dump(M, open(os.path.join(ROOT, 'ghost-marsh.json'), 'w'), separators=(',', ':'))
    print(n, 'beds', os.path.getsize(os.path.join(ROOT, 'ghost-marsh.json')), 'bytes')

if __name__ == '__main__':
    main()
