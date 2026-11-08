"""Filter OpenSkiMap ski_areas.geojson to NE/West candidate areas.
usage: python3 -I osm_candidates.py /tmp/osm_dl/ski_areas.geojson > candidates.json"""
import json, sys
NE = {'ME','NH','VT','MA','CT','NY','NJ','PA'}
W = {'WA','OR','CA','NV'}
d = json.load(open(sys.argv[1]))
out = []
for f in d['features']:
    p = f['properties']
    if p.get('type') != 'skiArea': continue
    if 'downhill' not in (p.get('activities') or []): continue
    st = None
    for pl in p.get('places') or []:
        iso = pl.get('iso3166_2') or ''
        if iso.startswith('US-'): st = iso[3:]
    if st not in NE | W: continue
    s = p.get('statistics') or {}
    mx, mn = s.get('maxElevation'), s.get('minElevation')
    vert = (mx - mn) * 3.28084 if mx is not None and mn is not None else None
    region = 'northeast' if st in NE else 'west'
    thr = 500 if region == 'northeast' else 650
    if vert is None or vert < thr: continue
    lon, lat = f['geometry']['coordinates'][:2] if f['geometry']['type']=='Point' else (None,None)
    out.append(dict(osm_id=p['id'], name=p.get('name'), state=st, region=region, status=p.get('status'),
        vert_ft=round(vert), max_ft=round(mx*3.28084), min_ft=round(mn*3.28084), lat=lat, lon=lon,
        websites=p.get('websites'), sources=p.get('sources')))
out.sort(key=lambda r:(r['region'], r['state'], -r['vert_ft']))
json.dump(out, sys.stdout, indent=1)
