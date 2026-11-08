#!/usr/bin/env python3
"""ACTIVE MINES (user 2026-11-08: "for geology, where did we land with mining" -> "yes add the active mines layer").

The Mine Safety and Health Administration's mine list (MSHA Open Government Data, Mines.zip, public domain, refreshed weekly): every
mine MSHA inspects, with its current status, commodity, operator, employees and coordinates. Kept: Active, Intermittent, New Mine and
Temporarily Idled (abandoned and sealed are the OLD MINES story). Out: under/mines_active_v1.json, a compact GeoJSON for THE ROCK's
UNDERGROUND row.

  k   kind (MSHA's canvass): sg sand and gravel, st stone, nm nonmetal (industrial minerals), co coal, me metal
  s   status: a active, i intermittent, n new mine, t temporarily idled;  sd the date it took that status
  ty  S surface, U underground, F facility (a plant or mill)
  n   name;  c commodity (primary SIC);  op operator;  ct controller (the parent company), when it differs
  e   employees (as reported to MSHA);  st state;  cn county;  p 1 = a portable operation (its point can be an office, not a pit)
  id  the MSHA mine ID (the key to its record in MSHA's Mine Data Retrieval System)

    python3 -I msha_bake.py OUT.json
"""
import csv, io, json, sys, urllib.request, zipfile
URL = 'https://arlweb.msha.gov/OpenGovernmentData/DataSets/Mines.zip'
KIND = {'SandAndGravel': 'sg', 'Stone': 'st', 'Nonmetal': 'nm', 'Coal': 'co', 'Metal': 'me'}
STAT = {'Active': 'a', 'Intermittent': 'i', 'New Mine': 'n', 'Temporarily Idled': 't'}
TYPE = {'Surface': 'S', 'Underground': 'U', 'Facility': 'F'}

def main(out):
    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0 (bluishvoid.com mines bake)'}), timeout=300).read()))
    name = [n for n in z.namelist() if n.lower().endswith('.txt')][0]
    csv.field_size_limit(10 ** 8)
    R = csv.DictReader(io.TextIOWrapper(z.open(name), encoding='latin-1'), delimiter='|')
    F = []; dates = []
    for r in R:
        s = STAT.get(r['CURRENT_MINE_STATUS'])
        if not s: continue
        try: la, lo = float(r['LATITUDE']), float(r['LONGITUDE'])
        except ValueError: continue
        if not (17 < la < 72 and -180 < lo < -60): continue           # the US and its territories in the Caribbean
        p = {'id': r['MINE_ID'], 'n': r['CURRENT_MINE_NAME'].strip(), 'k': KIND.get(r['PRIMARY_CANVASS'], 'nm'), 's': s, 'st': r['STATE']}
        t = TYPE.get(r['CURRENT_MINE_TYPE']);  c = r['PRIMARY_SIC'].strip(); op = r['CURRENT_OPERATOR_NAME'].strip(); ct = r['CURRENT_CONTROLLER_NAME'].strip()
        if t: p['ty'] = t
        if c: p['c'] = c
        if op: p['op'] = op
        if ct and ct.lower().rstrip('.,') not in op.lower(): p['ct'] = ct
        try:
            e = int(r['NO_EMPLOYEES'] or 0)
            if e: p['e'] = e
        except ValueError: pass
        if r['FIPS_CNTY_NM'].strip(): p['cn'] = r['FIPS_CNTY_NM'].strip()
        if r['PORTABLE_OPERATION'] == 'Y': p['p'] = 1
        if r['CURRENT_STATUS_DT']:
            m, d, y = (r['CURRENT_STATUS_DT'].split('/') + ['', '', ''])[:3]
            if y: p['sd'] = '%s-%s-%s' % (y, m, d)
        F.append({'type': 'Feature', 'properties': p, 'geometry': {'type': 'Point', 'coordinates': [round(lo, 4), round(la, 4)]}})
    F.sort(key=lambda f: f['properties'].get('e', 0))
    json.dump({'type': 'FeatureCollection', 'meta': {'source': 'MSHA Open Government Data, Mines', 'url': URL, 'n': len(F)}, 'features': F}, open(out, 'w'), separators=(',', ':'))
    from collections import Counter
    print(len(F), Counter(f['properties']['k'] for f in F), Counter(f['properties']['s'] for f in F), sum(f['properties'].get('e', 0) for f in F), 'employees')

if __name__ == '__main__':
    main(sys.argv[1])
