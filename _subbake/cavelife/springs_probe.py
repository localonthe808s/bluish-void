"""Probe USGS Water Data OGC API for spring gages: latest discharge (00060) + day-of-year
percentile normals. Source: https://api.waterdata.usgs.gov (USGS, public domain).
Usage: python3 -I springs_probe.py <outdir> ID [ID...]   (writes raw responses to outdir)
Written 2026-11-07."""
import sys, json, urllib.request, datetime, time
out = sys.argv[1]; ids = sys.argv[2:]
UA = {'User-Agent': 'bluishvoid.com (dashboard)'}
def get(u):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r:
                return json.loads(r.read())
        except Exception as e:
            err = e; time.sleep(2)
    return {'error': str(err)}
md = datetime.date.today().strftime('%m-%d')
res = {}
for i in ids:
    L = get(f'https://api.waterdata.usgs.gov/ogcapi/v1/collections/latest-continuous/items?monitoring_location_id=USGS-{i}&parameter_code=00060&f=json')
    N = get(f'https://api.waterdata.usgs.gov/statistics/v0/observationNormals?monitoring_location_id=USGS-{i}&parameter_code=00060&computation_type=percentile&start_date={md}&end_date={md}')
    json.dump({'latest': L, 'normals': N}, open(f'{out}/{i}.json', 'w'))
    fs = L.get('features') or []
    lv = [(f['properties'].get('time'), f['properties'].get('value'), f['properties'].get('statistic_id')) for f in fs]
    pct = None
    for f in (N.get('features') or []):
        for d in f['properties'].get('data', []):
            if d.get('parent_statistic_id') == '00003':
                v = d['values'][0]; pct = (v['values'][3], v.get('sample_count'))
    lv.sort(reverse=True)
    print(i, len(lv), lv[:1], '| p50:', pct)
    time.sleep(0.3)
