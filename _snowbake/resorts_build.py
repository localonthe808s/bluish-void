"""Build resorts_v1.json for the WATER > SNOW tab.

Pipeline (redo from scratch):
 1. curl https://tiles.openskimap.org/geojson/ski_areas.geojson and .../lifts.geojson
    (OpenSkiMap, ODbL, data from OpenStreetMap) into their own scratch dirs.
 2. python3 -I osm_bases.py ski_areas.geojson lifts.geojson > osm_bases.json
    (base point = densest cluster of lift bottom stations per ski area)
 3. parts/*.json: per-state research files (official stats, tickets, hours, passes),
    written by hand/agents following AGENT_BRIEF.txt; each entry carries osm_name.
 4. python3 -I resorts_build.py [--check-urls]  -> resorts_v1.json
    joins coordinates, sanity-checks state boxes and distance to the OSM area,
    optionally re-checks every website/tickets URL (HTTP 200-399 after redirects).
"""
import json, glob, math, os, sys, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (bluishvoid.com snow bake)"
BOX = {  # lat_min, lat_max, lon_min, lon_max (generous)
 'ME': (43.0, 47.5, -71.1, -66.9), 'NH': (42.7, 45.31, -72.6, -70.6), 'VT': (42.72, 45.02, -73.45, -71.46),
 'MA': (41.2, 42.89, -73.51, -69.9), 'CT': (40.95, 42.06, -73.73, -71.78), 'NY': (40.49, 45.02, -79.77, -71.85),
 'NJ': (38.92, 41.36, -75.56, -73.89), 'PA': (39.71, 42.27, -80.52, -74.68), 'WA': (45.54, 49.0, -124.8, -116.9),
 'OR': (41.99, 46.3, -124.6, -116.46), 'CA': (32.5, 42.01, -124.5, -114.1), 'NV': (35.0, 42.0, -120.01, -114.0)}
def dist_km(a, b):
    return 6371*math.hypot(math.radians(a[1]-b[1])*math.cos(math.radians(a[0])), math.radians(a[0]-b[0]))
def check(url):
    try:
        out = subprocess.run(['curl', '-sL', '-o', '/dev/null', '-m', '25', '-A', UA, '-w', '%{http_code} %{url_effective}', url],
                             capture_output=True, text=True, timeout=40).stdout.split(' ', 1)
        return int(out[0]), out[1] if len(out) > 1 else url
    except Exception:
        return 0, url
osm = json.load(open(os.path.join(HERE, 'osm_bases.json')))
by_name = {}
for a in osm: by_name.setdefault(a['name'], []).append(a)
ORDER = ['id','name','region','state','status','note','lat','lon','src_loc','summit_ft','base_ft','vertical_ft','trails','lifts','acres','src_stats',
         'website','tickets','passes','hours','hours_note','hours_src','season','night_skiing','unverified_403','src']
out, problems = [], []
for fn in sorted(glob.glob(os.path.join(HERE, 'parts', '*.json'))):
    for r in json.load(open(fn)):
        r = dict(r)
        on = r.pop('osm_name', None)
        cands = [a for a in by_name.get(on, []) if a['state'] == r['state']] or by_name.get(on, [])
        a = cands[0] if cands else None
        if a and a.get('base') and 'lat' not in r:
            r['lat'], r['lon'] = a['base']
            r['src_loc'] = 'OpenSkiMap (ODbL, OpenStreetMap data): mean of the main cluster of lift bottom stations [%s], area id %s' % (', '.join(x or '?' for x in a['base_cluster'][:6]), a['osm_id'][:12])
        elif a and a.get('center') and 'lat' not in r:
            r['lat'], r['lon'] = round(a['center'][1], 5), round(a['center'][0], 5)
            r['src_loc'] = 'OpenSkiMap (ODbL, OpenStreetMap data): ski-area viewport center (no lifts mapped), area id %s' % a['osm_id'][:12]
        if 'lat' not in r: problems.append((r['id'], 'no coordinates')); continue
        b = BOX[r['state']]
        if not (b[0] <= r['lat'] <= b[1] and b[2] <= r['lon'] <= b[3]): problems.append((r['id'], 'outside state box'))
        if a and a.get('center'):
            d = dist_km((r['lat'], r['lon']), (a['center'][1], a['center'][0]))
            if d > 10: problems.append((r['id'], 'base %.1f km from OSM area center' % d))
        out.append({k: r[k] for k in ORDER if k in r} | {k: v for k, v in r.items() if k not in ORDER})
FIX = json.load(open(os.path.join(HERE, 'fixes.json')))  # spot-check corrections (null = remove field)
for r in out:
    for k, v in FIX.get(r['id'], {}).items():
        if k == '_src_add': r['src'] = r.get('src', []) + [u for u in v if u not in r.get('src', [])]
        elif v is None: r.pop(k, None)
        else: r[k] = v
ids = [r['id'] for r in out]
for i in set(ids):
    if ids.count(i) > 1: problems.append((i, 'duplicate id'))
if '--check-urls' in sys.argv:
    for r in out:
        for k in ('website', 'tickets'):
            if k in r:
                code, eff = check(r[k])
                if not (200 <= code < 400):
                    if code == 403 and r.get('unverified_403'): continue
                    problems.append((r['id'], '%s %s -> %s' % (k, r[k], code)))
out.sort(key=lambda r: (r['region'] != 'northeast', r['state'], r['name']))
json.dump(out, open(os.path.join(HERE, 'resorts_v1.json'), 'w'), indent=1, ensure_ascii=False)
print(len(out), 'resorts written')
for p in problems: print('PROBLEM', *p)
