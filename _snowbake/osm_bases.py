"""Base-area point per OpenSkiMap ski area in the target states.
Base = the densest cluster of lift bottom stations (lower end of each lift,
600 m radius), ties broken by lower elevation; point = mean of that cluster.
usage: python3 -I osm_bases.py ski_areas.geojson lifts.geojson > osm_bases.json"""
import json, sys, math
NE = {'ME','NH','VT','MA','CT','NY','NJ','PA'}; W = {'WA','OR','CA','NV'}
areas = {}
for f in json.load(open(sys.argv[1]))['features']:
    p = f['properties']
    st = next((pl['iso3166_2'][3:] for pl in p.get('places') or [] if (pl.get('iso3166_2') or '').startswith('US-')), None)
    if st not in NE | W: continue
    s = p.get('statistics') or {}
    vh = p.get('viewportHint') or {}
    areas[p['id']] = dict(osm_id=p['id'], name=p.get('name'), state=st, status=p.get('status'),
        activities=p.get('activities'), websites=p.get('websites'),
        max_ft=round(s['maxElevation']*3.28084) if s.get('maxElevation') is not None else None,
        min_ft=round(s['minElevation']*3.28084) if s.get('minElevation') is not None else None,
        center=vh.get('center'), sources=p.get('sources'), bottoms=[])
def dist(a, b):
    return 6371000*math.hypot(math.radians(a[0]-b[0])*math.cos(math.radians(a[1])), math.radians(a[1]-b[1]))
for f in json.load(open(sys.argv[2]))['features']:
    p = f['properties']
    if p.get('status') not in ('operating', None): continue
    if p.get('liftType') in ('magic_carpet', 'rope_tow', 'zip_line', 'goods'): continue
    g = f['geometry']
    if g['type'] != 'LineString': continue
    c = g['coordinates']; a, b = c[0], c[-1]
    if len(a) > 2 and len(b) > 2: low = a if a[2] <= b[2] else b
    else: low = a
    for sa in p.get('skiAreas') or []:
        sid = sa['properties']['id']
        if sid in areas: areas[sid]['bottoms'].append((low[0], low[1], low[2] if len(low) > 2 else 9e9, p.get('name')))
for a in areas.values():
    bs = a.pop('bottoms'); a['n_lifts'] = len(bs)
    if not bs: continue
    best = max(bs, key=lambda x: (sum(1 for y in bs if dist(x, y) < 600), -x[2]))
    cl = [y for y in bs if dist(best, y) < 600]
    a['base'] = [round(sum(y[1] for y in cl)/len(cl), 5), round(sum(y[0] for y in cl)/len(cl), 5)]
    a['base_cluster'] = [y[3] for y in cl]
    a['base_cluster_ft'] = round(min(y[2] for y in cl)*3.28084)
json.dump(list(areas.values()), sys.stdout, indent=1)
