"""Florida subsidence incident reports, v2 -> under/fl_sinkholes_v2.json (user 2026-11-08: "yes do the sinkhole info").

v1's fields (see fl_sinkholes_bake.py) plus, per report:
  c   county (title case)
  zn  sinkhole-type zone 1-4 the point falls in (FGS_PUBLIC MapServer/5, after Sinclair and Stewart 1985)
  wv  water visible in the hole 'y'|'n';  wb  water level, ft below the land surface
  lv  limestone visible 'y'|'n';  cv  cave visible 'y'|'n'
  sl  slope of the sides, degrees
  rp  repair status 'r' repaired | 'p' planned | 'n' not repaired
  dr  drainage structure nearby (stormwater pond, ditch, lake, culvert, canal, creek, pavement)
  so  soil, normalized: 'sand' | 'clayey sand' | 'clay' | 'organic' (free text is dropped)
  ms  1 = dimensions measured (SIZDIM M), not estimated
PRIVACY: report name, report source, owner city/zip, access directions and comments are never requested or kept.
Usage: python3 -I fl_sinkholes_v2_bake.py <dir with p*.json query pages> <zones_full.pkl> <out.json>
"""
import sys, json, glob, datetime, collections, pickle
from shapely.geometry import Point
from shapely.strtree import STRtree
src, zp, out = sys.argv[1:4]
U = pickle.load(open(zp, 'rb')); ZK = {'Area I': 1, 'Area II': 2, 'Area III': 3, 'Area IV': 4}
polys, zk = [], []
for a, u in U.items():
    for p in getattr(u, 'geoms', [u]): polys.append(p); zk.append(ZK[a])
tree = STRtree(polys)
SH = {'C': 'circular', 'E': 'elongate'}; RT = {'R': 'rapid', 'S': 'slow'}; YN = {'Y': 'y', 'N': 'n'}
RP = {'Repaired': 'r', 'Planned': 'p', 'Not Repaired': 'n'}
DR = {'Stormwater Pond': 'stormwater pond', 'Ditch': 'ditch', 'Lake': 'lake', 'Culvert': 'culvert', 'Canal': 'canal', 'Creek': 'creek',
      'Impervious Surface (Anthropogenic)': 'pavement', 'Impervious Surface (Natural)': 'bare rock'}
def soil(s):
    s = (s or '').upper()
    if not s or 'UNK' in s: return None
    if 'MUCK' in s or 'PEAT' in s or 'ORGANIC' in s: return 'organic'
    if 'CLAY' in s and 'SAND' in s: return 'clayey sand'
    if 'CLAY' in s: return 'clay'
    if 'SAND' in s: return 'sand'
    return None
feats = []
for f in sorted(glob.glob(src + '/p*.json')):
    for x in json.load(open(f))['features']:
        a, g = x['attributes'], x.get('geometry')
        if not g: continue
        p = {}
        if a['EVENT_DATE'] is not None: p['d'] = datetime.datetime.utcfromtimestamp(a['EVENT_DATE'] / 1000).strftime('%Y-%m-%d')
        for k, o in (('SINLNGTH', 'l'), ('SINWIDTH', 'w'), ('SINDEPTH', 'dp')):
            v = a[k]
            if v and v != 999: p[o] = round(v, 1) if v % 1 else int(v)
        if a['SINSHAPE'] in SH: p['t'] = SH[a['SINSHAPE']]
        p['v'] = {'Y': 'y', 'N': 'n'}.get((a['TRUE_SINK'] or '').strip(), 'u')
        if a['SUBRATE'] in RT: p['r'] = RT[a['SUBRATE']]
        if a['PROPDAM'] == 'Y': p['pd'] = 1
        if a['ACCURACY'] in ('TWNRNG', 'COUNTY', 'UNKWN'): p['x'] = 1
        if a['COUNTY']: p['c'] = a['COUNTY'].title().replace('Desoto', 'DeSoto').replace('Dade', 'Miami-Dade') if a['COUNTY'] != 'MIAMI-DADE' else 'Miami-Dade'
        for k, o in (('WATSIN', 'wv'), ('LIMVIS', 'lv'), ('CAVVIS', 'cv')):
            if a[k] in YN: p[o] = YN[a[k]]
        if a['WATBLS'] is not None and 0 <= a['WATBLS'] < 400: p['wb'] = a['WATBLS']
        if a['SLOPE'] and 0 < a['SLOPE'] <= 90: p['sl'] = a['SLOPE']
        if a['REPAIR_S'] in RP: p['rp'] = RP[a['REPAIR_S']]
        if a['DRAINSTR'] in DR: p['dr'] = DR[a['DRAINSTR']]
        s = soil(a['SOILTYPE'])
        if s: p['so'] = s
        if a['SIZDIM'] == 'M': p['ms'] = 1
        pt = Point(g['x'], g['y'])
        for i in tree.query(pt):
            if polys[i].covers(pt): p['zn'] = zk[i]; break
        feats.append({'type': 'Feature', 'properties': p, 'geometry': {'type': 'Point', 'coordinates': [round(g['x'], 4), round(g['y'], 4)]}})
feats.sort(key=lambda f: f['properties'].get('d', ''))
dates = [f['properties']['d'] for f in feats if 'd' in f['properties']]
fc = {'type': 'FeatureCollection',
      'meta': {'title': 'Florida subsidence incident reports', 'asof': datetime.date.today().isoformat(), 'newest_event': max(dates),
               'source': 'Florida Geological Survey, FDEP: FGS_SUBSIDENCE MapServer/0; zones FGS_PUBLIC MapServer/5',
               'attribution': 'Subsidence incident reports: Florida Geological Survey, FDEP',
               'note': 'most reports are unverified (v=u); not every incident is a true sinkhole'},
      'features': feats}
json.dump(fc, open(out, 'w'), separators=(',', ':'))
P = [f['properties'] for f in feats]
print(len(feats), min(dates), max(dates))
for k in ['c', 'zn', 'wv', 'lv', 'cv', 'rp', 'dr', 'so', 'ms', 'sl', 'wb']:
    print(k, sum(1 for p in P if k in p), collections.Counter(p.get(k) for p in P if k in p).most_common(6))
