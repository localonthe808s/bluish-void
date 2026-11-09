#!/usr/bin/env python3
"""OFFSHORE DRILLING (user 2026-11-08: "are we able to track off shore drilling?" -> "yes queue both after the wells").

Every offshore oil and gas well, platform and pipeline we may show:
  US     BOEM/BSEE OCS layers (gis.boem.gov BOEM_BSEE/{GOA,POC,AK,ATL}_Layers): wells (spud date, type, status, total depth),
         platforms (installed, removed), pipelines. Public domain (US government).
  NORWAY Norwegian Offshore Directorate (Sodir) FactMaps: wellbores (purpose, what was found, status, depths, the rock at the
         bottom), facilities in place, pipelines. NLOD (Norwegian Licence for Open Government Data), credit Sodir.
Out: R2 under/offshore_v1.pmtiles, layers w (wells), p (platforms / facilities), l (pipelines).
    python3 offshore_bake.py OUTDIR [--upload]
"""
import json, os, subprocess, sys, time, urllib.parse, urllib.request
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com offshore bake)'}
B = 'https://gis.boem.gov/arcgis/rest/services/BOEM_BSEE/%s/MapServer/%d'
NO = 'https://factmaps.sodir.no/api/rest/services/Factmaps/FactMapsWGS84/MapServer/%d'
US = {'GOA': {'p': 0, 'w': 1, 'l': 2}, 'POC': {'p': 0, 'w': 1, 'l': 2}, 'AK': {'p': 0, 'w': 1}, 'ATL': {'w': 1}}
FT = 3.28084


def page(url, step=1000):
    off = 0
    while True:
        q = url + '/query?' + urllib.parse.urlencode({'where': '1=1', 'outFields': '*', 'outSR': 4326, 'f': 'geojson', 'resultOffset': off, 'resultRecordCount': step, 'geometryPrecision': 5})
        for a in range(4):
            try: j = json.load(urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=180)); break
            except Exception as e: print('  retry', a, e, flush=True); time.sleep(4 * (a + 1))
        else: raise SystemExit('failed ' + q)
        F = j.get('features') or []
        for f in F: yield f
        if len(F) < step: return
        off += len(F); time.sleep(0.3)


def yr(v):
    if v is None or v == '': return None
    if isinstance(v, (int, float)): return time.gmtime(v / 1000).tm_year if abs(v) > 1e6 else int(v)
    s = str(v); return int(s[-4:]) if s[-4:].isdigit() else None


def num(v):
    try: return float(v)
    except Exception: return None


def main(out, up):
    os.makedirs(out, exist_ok=True); L = {'w': open(os.path.join(out, 'w.ndjson'), 'w'), 'p': open(os.path.join(out, 'p.ndjson'), 'w'), 'l': open(os.path.join(out, 'l.ndjson'), 'w')}; n = {}
    def put(k, g, p):
        if not g or not g.get('coordinates'): return   # some Norwegian wellbores have no position
        if k == 'w' and str(p.get('s') or '').upper() == 'WILL NEVER BE DRILLED': return
        if p.get('y') == 0: p['y'] = None
        L[k].write(json.dumps({'type': 'Feature', 'geometry': g, 'properties': dict({a: b for a, b in p.items() if b not in (None, '')}, L=k)}) + '\n'); n[k] = n.get(k, 0) + 1
    for reg, ids in US.items():
        if 'w' in ids:
            for f in page(B % (reg + '_Layers', ids['w'])):
                a = f['properties']; put('w', f['geometry'], {'c': 'us', 'r': reg, 'n': (a.get('API_NUMBER') or ''), 'nm': (a.get('WELL_NAME') or '').strip(), 't': a.get('TYPE_CODE_DESC'), 's': a.get('STATUS_DESCRIPTION'),
                                                          'y': yr(a.get('SPUD_DATE')), 'd': num(a.get('DEPTH'))})
        if 'p' in ids:
            for f in page(B % (reg + '_Layers', ids['p'])):
                a = f['properties']; put('p', f['geometry'], {'c': 'us', 'r': reg, 'n': a.get('COMPLEX_ID_NUM'), 'y': yr(a.get('INSTALL_DATE')), 'x': yr(a.get('REMOVAL_DATE'))})
        if 'l' in ids:
            for f in page(B % (reg + '_Layers', ids['l'])):
                a = f['properties']; put('l', f['geometry'], {'c': 'us', 'r': reg, 'pr': a.get('PROD_CODE'), 'st': a.get('STATUS_CODE'), 'sz': a.get('PPL_SIZE_CODE')})
        print(reg, n, flush=True)
    for f in page(NO % 201):
        a = f['properties']
        put('w', f['geometry'], {'c': 'no', 'nm': a.get('wlbWellboreName'), 't': (a.get('wlbWellType') or '').title(), 'pu': a.get('wlbPurpose'), 'co': a.get('wlbContent'), 's': a.get('wlbStatus'), 'y': a.get('wlbEntryYear'),
                                   'd': round(a['wlbTotalDepth'] * FT) if a.get('wlbTotalDepth') else None, 'wd': round(a['wlbWaterDepth'] * FT) if a.get('wlbWaterDepth') else None,
                                   'fm': (a.get('wlbFormationAtTd') or '').strip(), 'ag': (a.get('wlbAgeAtTd') or '').strip(), 'op': a.get('wlbDrillingOperator'), 'u': a.get('wlbFactPageUrl')})
    for f in page(NO % 304):
        a = f['properties']; put('p', f['geometry'], {'c': 'no', 'nm': a.get('fclName'), 'k': a.get('fclKind'), 'y': yr(a.get('fclStartupDate')), 'op': a.get('fclCurrentOperatorName'), 'fu': a.get('fclFunctions'), 'ph': a.get('fclPhase'), 'wd': round(a['fclWaterDepth'] * FT) if a.get('fclWaterDepth') else None})
    for f in page(NO % 311):
        a = f['properties']; put('l', f['geometry'], {'c': 'no', 'nm': a.get('pplName'), 'pr': a.get('pplMedium'), 'st': a.get('pplCurrentPhase'), 'op': a.get('cmpLongName')})
    print('all', n, flush=True)
    for f in L.values(): f.close()
    pm = os.path.join(out, 'offshore_v1.pmtiles')
    subprocess.run(['tippecanoe', '-o', pm, '-f', '-Z2', '-z12', '--drop-densest-as-needed', '--extend-zooms-if-still-dropping', '-r1', '--maximum-tile-bytes=500000',
                    '-L', 'w:' + os.path.join(out, 'w.ndjson'), '-L', 'p:' + os.path.join(out, 'p.ndjson'), '-L', 'l:' + os.path.join(out, 'l.ndjson')], check=True)
    print('pmtiles', os.path.getsize(pm) // 1024, 'KB')
    if up: subprocess.run(['rclone', 'copyto', pm, 'r2:bluishvoid-bg/under/offshore_v1.pmtiles', '--s3-no-check-bucket', '--header-upload', 'Content-Type: application/vnd.pmtiles', '--header-upload', 'Cache-Control: public, max-age=86400'], check=True)


if __name__ == '__main__':
    main(sys.argv[1], '--upload' in sys.argv)
