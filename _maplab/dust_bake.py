#!/usr/bin/env python3
"""EARTH SYSTEMS -> DESERT DUST: the model layer for the land the satellite cannot see.

The AIRS dust score (the view's picture) is surest over the sea and nearly blind over bright desert, so the central
Sahara can read as quiet while a model has thousands of micrograms per cubic metre of dust there (audit 2026-10-10).
This bakes ECMWF's CAMS global forecast of dust at the surface for the current hour on a 4-degree grid, through
Open-Meteo's keyless air-quality API (https://open-meteo.com/en/docs/air-quality-api, CC BY 4.0), and writes a small
JSON the page draws as a soft haze under the satellite footprints.

    python3 dust_bake.py out            -> out/cams.json   (~30 KB)

Grid: lon -180..176 step 4 (90), lat -58..70 step 4 (33) = 2,970 points, fetched 200 per call with a pause (Open-Meteo
weights a multi-point call by its points; 495 per call drew 429s).
"""
import datetime as dt, json, math, os, sys, time, urllib.parse, urllib.request

OUT = sys.argv[1] if len(sys.argv) > 1 else 'out'
os.makedirs(OUT, exist_ok=True)
STEP = 4; LON0 = -180; LAT0 = -58; NX = 90; NY = 33
API = 'https://air-quality-api.open-meteo.com/v1/air-quality'
now = dt.datetime.now(dt.timezone.utc); hour = now.hour

pts = [(LAT0 + j * STEP, LON0 + i * STEP) for j in range(NY) for i in range(NX)]
dust = [None] * len(pts); aod = [None] * len(pts)
CH = 200
for k in range(0, len(pts), CH):
    chunk = pts[k:k + CH]
    q = {'latitude': ','.join(str(p[0]) for p in chunk), 'longitude': ','.join(str(p[1]) for p in chunk),
         'hourly': 'dust,aerosol_optical_depth', 'forecast_days': 1, 'timezone': 'UTC'}
    for attempt in range(3):
        try:
            with urllib.request.urlopen(API + '?' + urllib.parse.urlencode(q), timeout=120) as r: rows = json.load(r)
            break
        except Exception as e:
            if attempt == 2: raise
            time.sleep(40 if '429' in str(e) else 5)
    if isinstance(rows, dict): rows = [rows]
    for n, row in enumerate(rows):
        h = row.get('hourly') or {}; d = (h.get('dust') or []); a = (h.get('aerosol_optical_depth') or [])
        dust[k + n] = None if hour >= len(d) or d[hour] is None else int(round(d[hour]))
        aod[k + n] = None if hour >= len(a) or a[hour] is None else round(a[hour], 2)
    time.sleep(6)

ok = sum(1 for v in dust if v is not None)
if ok < len(pts) * 0.9: raise SystemExit('only %d of %d points answered' % (ok, len(pts)))
peak = max(range(len(pts)), key=lambda i: dust[i] if dust[i] is not None else -1)
out = {'built': now.strftime('%Y-%m-%dT%H:%MZ'), 'hour': now.strftime('%Y-%m-%dT%H:00Z'),
       'what': 'CAMS global forecast of dust at the surface, micrograms per cubic metre, for the hour named; grid row-major from lat0/lon0 in steps of step degrees',
       'lat0': LAT0, 'lon0': LON0, 'step': STEP, 'nx': NX, 'ny': NY, 'dust': dust, 'aod': aod,
       'peak': {'v': dust[peak], 'lat': pts[peak][0], 'lon': pts[peak][1]},
       'credit': 'Copernicus Atmosphere Monitoring Service (CAMS) global forecast via Open-Meteo (CC BY 4.0)'}
json.dump(out, open(os.path.join(OUT, 'cams.json'), 'w'), separators=(',', ':'))
print('cams.json', os.path.getsize(os.path.join(OUT, 'cams.json')), 'bytes;', ok, 'points; peak', out['peak'], 'hour', out['hour'])
