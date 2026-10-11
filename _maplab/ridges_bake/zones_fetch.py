import json, urllib.request, time, sys
from concurrent.futures import ThreadPoolExecutor
from shapely.geometry import shape, box, mapping
UA = {'User-Agent': 'bluishvoid.com zone bake (https://bluishvoid.com)', 'Accept': 'application/geo+json'}
def get(u, tries=5):
    for t in range(tries):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
        except Exception as e: err = e; time.sleep(1.5 * (t + 1))
    print('FAIL', u, err); return None
RB = box(-81.2, 37.677, -73.35, 42.922)
ids = []
for st in ['OH', 'WV', 'VA', 'MD', 'PA']:
    for ty in ['forecast', 'county']:
        j = get('https://api.weather.gov/zones?type=%s&area=%s' % (ty, st))
        ids += [(ty, f['properties']['id']) for f in (j or {}).get('features', [])]
print(len(ids), 'zones listed'); sys.stdout.flush()
out = {}
def one(t):
    ty, zid = t; j = get('https://api.weather.gov/zones/%s/%s' % (ty, zid))
    if not j or not j.get('geometry'): return
    try:
        g = shape(j['geometry']).buffer(0)
        if not g.intersects(RB): return
        g = g.simplify(0.0126).buffer(0).intersection(box(-81.6, 34.0, -65.0, 47.6))
    except Exception as e:
        print('GEOM', zid, e); return
    polys = list(g.geoms) if hasattr(g, 'geoms') else [g]
    rings = [[[round(x, 4), round(y, 4)] for x, y in p.exterior.coords] for p in polys if p.geom_type == 'Polygon' and not p.is_empty]
    if rings: out[zid] = rings
with ThreadPoolExecutor(4) as ex: list(ex.map(one, ids))
json.dump(out, open(sys.argv[1], 'w'), separators=(',', ':')); print(len(out), 'zones in the ridges box')
