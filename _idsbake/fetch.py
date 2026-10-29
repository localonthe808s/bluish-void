#!/usr/bin/env python3
"""TREES > PESTS & DISEASE (user 2026-10-29). USDA Forest Service Insect & Disease Detection Survey (IDS) damage AREAS, the aerial and
ground surveys of what is killing or stripping trees, CONUS + Alaska + Hawaii, 2021-2025 (public domain, Forest Health Protection).
The map service only draws them closer than 1:250,000 and caps a query at 2,000, so they are paged out here (ordered by objectid)
and baked to our own vector tiles (build.sh).
    python3 fetch.py OUTDIR [FIRST_YEAR LAST_YEAR]  -> OUTDIR/ids_<year>.geojsonl (one feature per line)"""
import json, os, sys, time, urllib.parse, urllib.request
B = 'https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_InsectandDiseaseSurvey_01/MapServer/1/query'
F = 'objectid,dca_common_name,damage_type,percent_mid,percent_affected,survey_year,acres,host_group,host'
def get(params):
    u = B + '?' + urllib.parse.urlencode(params)
    for k in range(5):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluish-void bake'}), timeout=180))
        except Exception as e: print('retry', k, e, flush=True); time.sleep(5 * (k + 1))
    raise SystemExit('failed ' + u[:200])
def year(y, out):
    p = os.path.join(out, 'ids_%d.geojsonl' % y)
    last = -1; n = 0
    if os.path.exists(p):   # resume
        for l in open(p): last = max(last, json.loads(l)['properties']['objectid']); n += 1
    with open(p, 'a') as fo:
        while True:
            j = get({'where': 'survey_year=%d AND objectid>%d' % (y, last), 'outFields': F, 'orderByFields': 'objectid', 'returnGeometry': 'true',
                     'outSR': 4326, 'maxAllowableOffset': 0.0001, 'geometryPrecision': 5, 'resultRecordCount': 2000, 'f': 'geojson'})
            fs = j.get('features') or []
            if not fs: break
            for f in fs:
                if f.get('geometry'): fo.write(json.dumps(f, separators=(',', ':')) + '\n'); n += 1
                last = max(last, f['properties']['objectid'])
            print(y, n, flush=True)
    return n
if __name__ == '__main__':
    out = sys.argv[1]; a, b = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (2021, 2025)
    for y in range(b, a - 1, -1): print('done', y, year(y, out), flush=True)
