"""Florida subsidence incident reports -> under/fl_sinkholes_v1.json

SOURCE: Florida DEP, Florida Geological Survey (FGS), "Florida Subsidence Incident Reports"
  https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/FGS_SUBSIDENCE/MapServer/0
  (ArcGIS Online item 194ac159bd1e4be294b14dd882d42dcf, FDEP Open Data portal, item modified 2026-03-09;
   newest EVENT_DATE 2026-10-30 when pulled 2026-11-07). 4465 records, events 1909..2026.
  Info: https://floridadep.gov/fgs/sinkholes/content/subsidence-incident-reports
LICENCE: Florida public record, distributed "as is"; FGS asks for credit; "no proprietary rights may be
  attached". Attribution: "Subsidence incident reports: Florida Geological Survey, FDEP".
  Most records are NOT field-verified as sinkholes (TRUE_SINK U = unverified).
PRIVACY: report name, owner city/zip and comments are never requested.
FIELDS out (point props):
  d   EVENT_DATE (UTC date, stored at 00:00) 'YYYY-MM-DD'
  l,w,dp  length / width / depth in feet (0 and 999 placeholders dropped)
  t   shape: 'circular' | 'elongate' (SINSHAPE C/E; U omitted)
  v   verified sinkhole: 'y' | 'n' (= checked, not a sinkhole) | 'u' (unverified)
  r   subsidence rate 'rapid' | 'slow' (SUBRATE R/S; U omitted)
  pd  1 = property damage reported
  x   1 = location only to township/county/unknown (imprecise)
Usage: python3 -I fl_sinkholes_bake.py <dir with p*.json query pages> <out.json>
Written 2026-11-07.
"""
import sys, json, glob, datetime, collections
src, out = sys.argv[1:3]
SH = {'C': 'circular', 'E': 'elongate'}; RT = {'R': 'rapid', 'S': 'slow'}
feats = []
for f in sorted(glob.glob(src + '/p*.json')):
    for x in json.load(open(f))['features']:
        a, g = x['attributes'], x.get('geometry')
        if not g: continue
        p = {}
        if a['EVENT_DATE'] is not None:
            p['d'] = datetime.datetime.utcfromtimestamp(a['EVENT_DATE'] / 1000).strftime('%Y-%m-%d')
        for k, o in (('SINLNGTH', 'l'), ('SINWIDTH', 'w'), ('SINDEPTH', 'dp')):
            v = a[k]
            if v and v != 999: p[o] = round(v, 1) if v % 1 else int(v)
        if a['SINSHAPE'] in SH: p['t'] = SH[a['SINSHAPE']]
        p['v'] = {'Y': 'y', 'N': 'n'}.get((a['TRUE_SINK'] or '').strip(), 'u')
        if a['SUBRATE'] in RT: p['r'] = RT[a['SUBRATE']]
        if a['PROPDAM'] == 'Y': p['pd'] = 1
        if a['ACCURACY'] in ('TWNRNG', 'COUNTY', 'UNKWN'): p['x'] = 1
        feats.append({'type': 'Feature', 'properties': p,
                      'geometry': {'type': 'Point', 'coordinates': [round(g['x'], 4), round(g['y'], 4)]}})
feats.sort(key=lambda f: f['properties'].get('d', ''))
dates = [f['properties']['d'] for f in feats if 'd' in f['properties']]
fc = {'type': 'FeatureCollection',
      'meta': {'title': 'Florida subsidence incident reports', 'asof': '2026-11-07', 'newest_event': max(dates),
               'source': 'Florida Geological Survey, FDEP: FGS_SUBSIDENCE MapServer/0',
               'attribution': 'Subsidence incident reports: Florida Geological Survey, FDEP',
               'note': 'most reports are unverified (v=u); not every incident is a true sinkhole'},
      'features': feats}
json.dump(fc, open(out, 'w'), separators=(',', ':'))
print(len(feats), min(dates), max(dates), collections.Counter(f['properties']['v'] for f in feats),
      sum(1 for f in feats if 'x' in f['properties']))
