#!/usr/bin/env python3
"""PFAS IN TAP WATER (user 2026-11-20: impaired waters, Superfund and PFAS on WATER > RIVERS).

EPA's PFAS Analytic Tools, drinking-water layer: every sample from the national tap-water surveys (UCMR 3 and UCMR 5) where a
PFAS chemical was found at or above the lab's reporting level -- about 40,000 sample rows. Folded here to one row per public
water system: where it is (EPA's estimate: the service area's center), who it serves, and for each chemical found the
highest result and its date.

Out: pfas_v1.json  { built, n, sys: [[lat, lon, name, state, people served, [[chemical, max ng/L, 'YYYY-MM-DD', times found], ...]], ...] }
Run: python3 _pfasbake/bake.py [out.json]     (no keys; a minute or two)
"""
import sys, os, json, time, datetime, urllib.request, urllib.parse

URL = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/PFAS_Analytic_Tools_Layers/FeatureServer/1/query'
FIELDS = 'OBJECTID,F_PWS_ID,PWS_Name,State,Population_Served,Latitude,Longitude,Collection_Date,Contaminant,Analytical_Result_Value__ng_L_'


def get(q, tries=4):
    u = URL + '?' + urllib.parse.urlencode(q)
    for i in range(tries):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (pfas-bake)'}), timeout=180).read())
            if 'features' in j:
                return j
            raise RuntimeError(str(j)[:200])
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(6 * (i + 1))


def day(s):
    try:
        m, d, y = str(s).split(' ')[0].split('/')
        return '%04d-%02d-%02d' % (int(y), int(m), int(d))
    except Exception:
        return ''


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pfas_v1.json')
    S, last, rows = {}, 0, 0
    while True:
        F = get({'where': "Result_At_or_Above_UCMR_MRL='Yes' AND OBJECTID>%d" % last, 'outFields': FIELDS, 'returnGeometry': 'false',
                 'orderByFields': 'OBJECTID', 'resultRecordCount': 2000, 'f': 'json'})['features']
        if not F:
            break
        for f in F:
            a = f['attributes']; last = max(last, a['OBJECTID']); rows += 1
            try:
                la, lo, v = float(a['Latitude']), float(a['Longitude']), float(a['Analytical_Result_Value__ng_L_'])
            except (TypeError, ValueError):
                continue
            s = S.setdefault(a['F_PWS_ID'], {'la': la, 'lo': lo, 'n': (a.get('PWS_Name') or '').strip(), 'st': (a.get('State') or '').strip(), 'pop': a.get('Population_Served') or 0, 'c': {}})
            c = s['c'].setdefault((a.get('Contaminant') or '').strip(), [0.0, '', 0])
            c[2] += 1
            if v > c[0]:
                c[0], c[1] = v, day(a.get('Collection_Date'))
        print('  read', rows, flush=True)
        if len(F) < 2000:
            break
    if rows < 20000:
        print('ONLY', rows, 'ROWS: not writing'); sys.exit(1)
    sysl = [[round(s['la'], 4), round(s['lo'], 4), s['n'], s['st'], s['pop'], sorted([[k, round(v[0], 1), v[1], v[2]] for k, v in s['c'].items()], key=lambda x: -x[1])] for s in S.values()]
    json.dump({'built': datetime.date.today().isoformat(), 'n': len(sysl), 'sys': sysl}, open(out, 'w'), separators=(',', ':'))
    over = sum(1 for s in sysl if any(c[0] in ('PFOA', 'PFOS') and c[1] > 4 for c in s[5]))
    print('wrote', out, os.path.getsize(out) // 1024, 'KB |', rows, 'sample rows ->', len(sysl), 'water systems |', over, 'with PFOA or PFOS over 4 ng/L')


if __name__ == '__main__':
    main()
