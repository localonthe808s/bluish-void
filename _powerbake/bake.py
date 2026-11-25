"""POWER PLANTS on the EARTH SYSTEMS globe (2026-11-25). Every power-sector source in Climate TRACE (climatetrace.org, CC BY 4.0),
2025 estimates: name, country, fuel, capacity MW, generation MWh, CO2e (100-yr) tonnes, lat/lon.
Writes out/plants_v1.json = {year, n, cols, rows} sorted by emissions, largest first.  Upload:
rclone copyto out/plants_v1.json r2:bluishvoid-bg/power/plants_v1.json --s3-no-check-bucket"""
import json, os, sys, time, urllib.request
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out'); os.makedirs(OUT, exist_ok=True)
YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
rows, off = [], 0
while True:
    u = f'https://api.climatetrace.org/v7/sources?sectors=power&limit=1000&offset={off}&year={YEAR}'
    for k in range(4):
        try: page = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluishvoid.com power bake'}), timeout=90)); break
        except Exception as e: print('retry', off, e); time.sleep(3)
    else: raise SystemExit('failed at ' + str(off))
    for a in page:
        c = a.get('centroid') or {}
        if c.get('latitude') is None: continue
        rows.append([a.get('id'), (a.get('name') or '').strip(), a.get('country') or '', (a.get('assetType') or '').strip(),
                     round(a.get('capacity') or 0, 1), round(a.get('activity') or 0), round(a.get('emissionsQuantity') or 0),
                     round(c['latitude'], 4), round(c['longitude'], 4)])
    print(off, len(page), len(rows), flush=True)
    if len(page) < 1000: break
    off += 1000
rows.sort(key=lambda r: -r[6])
doc = {'year': YEAR, 'source': 'Climate TRACE (climatetrace.org), CC BY 4.0', 'n': len(rows),
       'cols': ['id', 'name', 'cc', 'fuel', 'mw', 'mwh', 'co2e_t', 'lat', 'lon'], 'rows': rows}
s = json.dumps(doc, separators=(',', ':'), ensure_ascii=False); open(os.path.join(OUT, 'plants_v1.json'), 'w').write(s)
print('wrote', len(rows), 'plants', len(s) // 1024, 'KB')
