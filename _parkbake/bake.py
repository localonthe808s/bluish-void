#!/usr/bin/env python3
"""The named parts of New York's three great parks for LOCAL's map labels (user 2026-10-19: "at a low zoom where things fit, i
want central park and prospect park, flushing meadows corona park, to have all of their subsections labeled inside their parks").

OpenStreetMap through Overpass: every named area inside Central Park, Prospect Park and Flushing Meadows-Corona Park that is a
part of the park -- meadows and lawns (landuse grass / meadow / recreation_ground, leisure pitch when it is a whole field like
The Great Lawn, not "Ball Field 3"), woods (natural wood / yes: The Ramble), water (Harlem Meer, Prospect Lake, Meadow Lake),
gardens, nature reserves, zoos, rinks, peninsulas -- plus the named hills as points. Left out: the animal enclosures inside the
zoos, playgrounds, numbered fields and courts, paths, bridges and buildings. Each area keeps its outer ring (simplified to ~1.5 m)
and its pole of inaccessibility (the interior point farthest from the edge, where a name has the most room).

    python3 bake.py OUT.json [RAW.json]
(macOS's system Python cannot complete Overpass's TLS handshake; then fetch with curl and pass the file:
 python3 -c 'import bake' is not needed -- curl -s --data-urlencode data@<(python3 bake.py --query) https://overpass-api.de/api/interpreter > raw.json)
"""
import json, math, re, sys, urllib.request, urllib.parse
from shapely.geometry import Polygon, MultiPolygon, Point, shape
from shapely.ops import polylabel, unary_union, linemerge
from shapely import wkt

Q = """[out:json][timeout:180];
( wr["leisure"="park"]["name"~"^(Central Park|Prospect Park|Flushing Meadows.Corona Park)$"](40.55,-74.05,40.82,-73.80); )->.p;
.p out geom;
.p map_to_area ->.a;
( wr(area.a)["name"]; node(area.a)["name"]["natural"="peak"]; );
out geom;"""

AREA = [('leisure', r'^(park|garden|nature_reserve|common|recreation_ground|pitch|ice_rink|golf_course)$'),
        ('natural', r'^(water|wood|grassland|scrub|wetland|heath|yes|peninsula)$'),
        ('landuse', r'^(grass|meadow|forest|recreation_ground)$'),
        ('tourism', r'^(zoo|artwork)$'), ('water', r'.')]
DROP = re.compile(r'(\bfield\s*\d|\bballfield\s*\d|\bcourt|\bplayground|\bdog run|\bparking)', re.I)

def axis(P):
    """the long axis of an area's minimum rotated rectangle, as a SCREEN angle in degrees (y down), within (-90, 90]: a name that
    cannot sit level in a long, slanted area (The Long Meadow, Central Park) lies along it instead"""
    k = math.cos(math.radians(P.centroid.y))
    from shapely.affinity import scale
    R = scale(P, xfact=k, yfact=1, origin=(0, 0)).minimum_rotated_rectangle
    c = list(R.exterior.coords)
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1]); e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    dx, dy = e1 if math.hypot(*e1) >= math.hypot(*e2) else e2
    a = -math.degrees(math.atan2(dy, dx))
    while a <= -90: a += 180
    while a > 90: a -= 180
    return round(a, 1)

def rings(e):
    """outer rings of a way or a multipolygon relation, as shapely polygons"""
    if e['type'] == 'way':
        g = [(p['lon'], p['lat']) for p in e.get('geometry', [])]
        return [Polygon(g)] if len(g) >= 4 and g[0] == g[-1] else []
    outer = [[(p['lon'], p['lat']) for p in m.get('geometry', [])] for m in e.get('members', []) if m.get('role') == 'outer' and m.get('geometry')]
    from shapely.geometry import LineString
    merged = linemerge([LineString(c) for c in outer if len(c) >= 2])
    parts = list(merged.geoms) if hasattr(merged, 'geoms') else [merged]
    return [Polygon(l.coords) for l in parts if l.is_ring]

def main():
    if sys.argv[1] == '--query': print(Q); return
    if len(sys.argv) > 2:
        E = json.load(open(sys.argv[2]))['elements']; return build(E)
    req = urllib.request.Request('https://overpass-api.de/api/interpreter', data=urllib.parse.urlencode({'data': Q}).encode(),
                                 headers={'User-Agent': 'bluishvoid.com park parts bake'})
    E = json.load(urllib.request.urlopen(req, timeout=240))['elements']
    build(E)

def build(E):
    parks, out = {}, []
    for e in E:
        t = e.get('tags', {})
        if t.get('leisure') == 'park' and re.match(r'^(Central Park|Prospect Park|Flushing Meadows.Corona Park)$', t.get('name', '')):
            P = unary_union([r.buffer(0) for r in rings(e)])
            if not P.is_empty: parks[t['name']] = P.union(parks[t['name']]) if t['name'] in parks else P
    zoos = unary_union([r.buffer(0) for e in E if e.get('tags', {}).get('tourism') == 'zoo' for r in rings(e)])
    M = 1 / 111320.0                                         # ~metres -> degrees
    seen = set()
    for e in E:
        t = e.get('tags', {}); nm = t.get('name', '').strip()
        if not nm or nm in parks or DROP.search(nm): continue
        if e['type'] == 'node':
            if t.get('natural') != 'peak': continue
            pt = Point(e['lon'], e['lat']); park = next((k for k, v in parks.items() if v.contains(pt)), None)
            if park and ('p', nm) not in seen:
                seen.add(('p', nm)); out.append({'n': nm, 'k': 'peak', 'park': park, 'c': [round(e['lon'], 6), round(e['lat'], 6)]})
            continue
        kind = next((k + ':' + t[k] for k, rx in AREA if k in t and re.match(rx, t[k])), None)
        if not kind and set(t) <= {'name', 'wikidata', 'wikipedia', 'source', 'note'}: kind = 'area'      # North Woods: a named area and nothing else
        if not kind or 'highway' in t or 'building' in t: continue
        if t.get('leisure') == 'pitch' and not re.search(r'lawn|meadow|ballfields$', nm, re.I): continue
        polys = [r.buffer(0) for r in rings(e)]
        if not polys: continue
        P = max(polys, key=lambda p: p.area)
        park = next((k for k, v in parks.items() if v.intersection(P).area > 0.6 * P.area), None)
        if not park: continue
        if t.get('tourism') != 'zoo' and not zoos.is_empty and zoos.contains(P.representative_point()): continue   # the enclosures
        if (nm, park) in seen: continue
        seen.add((nm, park))
        S = P.simplify(1.5 * M, preserve_topology=True)
        c = polylabel(S, tolerance=0.5 * M)
        out.append({'n': nm, 'k': kind, 'park': park, 'c': [round(c.x, 6), round(c.y, 6)], 'a': axis(S),
                    'g': [[round(x, 6), round(y, 6)] for x, y in S.exterior.coords]})
    areas = {o['n'] for o in out if 'g' in o}
    out = [o for o in out if o['k'] != 'peak' or o['n'] not in areas]   # Great Hill is a lawn too: the area wins
    for k, v in parks.items():                               # the parks themselves, so their own names fit-test here too
        S = max(v.geoms, key=lambda p: p.area) if hasattr(v, 'geoms') else v
        S = S.simplify(3 * M, preserve_topology=True); c = polylabel(S, tolerance=1 * M)
        out.append({'n': k, 'k': 'park', 'park': k, 'c': [round(c.x, 6), round(c.y, 6)], 'a': axis(S), 'g': [[round(x, 6), round(y, 6)] for x, y in S.exterior.coords]})
    json.dump(out, open(sys.argv[1], 'w'), separators=(',', ':'))
    print(len(out), 'features;', sum(1 for o in out if o['k'] == 'peak'), 'hills;', {p: sum(1 for o in out if o['park'] == p) for p in parks})

main()
