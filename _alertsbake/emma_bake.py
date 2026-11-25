"""MeteoAlarm warning-area outlines for the worldwide hero alerts (2026-11-25).
Source: EUMETNET MeteoAlarm EMMA_ID geocodes (geocodes.json, via the MIT "meteoalarm" package by Niklas Jordan,
https://github.com/NiklasJordan/meteoalarm). MeteoAlarm terms: CC BY 4.0 equivalent, credit EUMETNET-MeteoAlarm.
Writes out/emma/<CC>.json  {code: [bbox, [rings...]]}  simplified ~0.005 deg, and out/emma/index.json {CC: bbox}.
Upload:  rclone copy out/emma r2:bluishvoid-bg/alerts/emma --s3-no-check-bucket"""
import json, os, sys, collections
from shapely.geometry import shape, mapping
src = sys.argv[1]; out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', 'emma'); os.makedirs(out, exist_ok=True)
d = json.load(open(src)); by = collections.defaultdict(dict); bb = {}
for f in d['features']:
    p = f['properties']; cc = p['country']; g = shape(f['geometry']).buffer(0).simplify(0.005, preserve_topology=True)
    if g.is_empty: continue
    polys = [g] if g.geom_type == 'Polygon' else list(g.geoms)
    rings = [[[round(x, 4), round(y, 4)] for x, y in pg.exterior.coords] for pg in polys]
    b = [round(v, 3) for v in g.bounds]
    by[cc][p['code']] = [b, rings]
    c = bb.get(cc); bb[cc] = b if not c else [min(c[0], b[0]), min(c[1], b[1]), max(c[2], b[2]), max(c[3], b[3])]
tot = 0
for cc, m in by.items():
    s = json.dumps(m, separators=(',', ':')); open(os.path.join(out, cc + '.json'), 'w').write(s); tot += len(s)
json.dump(bb, open(os.path.join(out, 'index.json'), 'w'), separators=(',', ':'))
print(len(by), 'countries', sum(len(m) for m in by.values()), 'areas', tot // 1024, 'KB total; largest',
      max((len(json.dumps(m)) // 1024, cc) for cc, m in by.items()))
