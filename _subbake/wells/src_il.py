#!/usr/bin/env python3
"""Illinois: ISGS ILGeoTech SPT service (maps.isgs.illinois.edu ILGeoTech/SPT MapServer) - engineering borings
(mostly IDOT highway borings) from the ISGS Wells and Borings database with a described lithology table:
layer 0 SPT_Header (API, lat/lon, total depth, completion date), table 2 Lithology (HBFORMATION_TOP/BOTTOM,
HBFORMATION = the boring log's words, FORMATION_NAME = the ISGS unit). Small: ~86 borings. The 390k-record ILWATER
water-well layer carries no interval table (logs are per-well PDFs at data.prairie.illinois.edu), so it is not used.
Units: feet unless Metric is set (then meters, converted)."""
import json, os, re, time, datetime, urllib.parse, urllib.request
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'il')
B = 'https://maps.isgs.illinois.edu/arcgis/rest/services/ILGeoTech/SPT/MapServer'
BOX = (36.9, 42.6, -91.6, -87.4)


def get(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return json.load(open(path))
    for a in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
            d = json.loads(b)
            if 'error' in d: raise ValueError(str(d['error'])[:200])
            open(path, 'wb').write(b); time.sleep(0.2); return d
        except Exception:
            time.sleep(3 * (a + 1))
    raise RuntimeError('IL fetch failed ' + url)


def allrows(layer, fields, geom=False):
    out, off = [], 0
    while True:
        q = {'where': '1=1', 'outFields': fields, 'returnGeometry': 'true' if geom else 'false', 'f': 'json',
             'orderByFields': 'OBJECTID', 'resultOffset': off, 'resultRecordCount': 1000}
        d = get('%s/%d/query?%s' % (B, layer, urllib.parse.urlencode(q)), os.path.join(CACHE, 'l%d_%06d.json' % (layer, off)))
        fs = d.get('features', []); out += fs
        if not d.get('exceededTransferLimit') or not fs: return out
        off += len(fs)


def wells():
    os.makedirs(CACHE, exist_ok=True)
    logs = {}
    for f in allrows(2, 'API,HBFORMATION_TOP,HBFORMATION_BOTTOM,HBFORMATION,FORMATION_NAME,Metric'):
        a = f['attributes']
        k = (a.get('API'), (a.get('FORMATION_NAME') or '').strip())
        top, bot = a.get('HBFORMATION_TOP'), a.get('HBFORMATION_BOTTOM')
        if a.get('API') is None or top is None: continue
        m = 3.28084 if (a.get('Metric') or '').strip().upper() in ('Y', 'YES', 'TRUE', '1', 'M') else 1.0
        d = re.sub(r'\s+', ' ', a.get('HBFORMATION') or '').strip()
        fm = (a.get('FORMATION_NAME') or '').strip()
        if fm and fm.lower() not in d.lower(): d = (d + ' (' + fm + ')') if d else fm
        top = float(top) * m; bot = None if bot is None else float(bot) * m
        if bot is not None and bot < top: top, bot = bot, top
        logs.setdefault(int(a['API']), []).append([round(top, 1), None if bot is None else round(bot, 1), d[:120]])
    seen = set()
    for f in allrows(0, 'API,COMP_DATE,TOTAL_DEPTH,LATITUDE,LONGITUDE,Metric,TYPE'):
        a = f['attributes']; api = a.get('API')
        if api is None or int(api) not in logs or int(api) in seen: continue
        lat, lon = a.get('LATITUDE'), a.get('LONGITUDE')
        if lat is None or lon is None or not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
        seen.add(int(api))
        yr = None
        if isinstance(a.get('COMP_DATE'), (int, float)):
            y = (datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=a['COMP_DATE'])).year
            if 1850 <= y <= 2030: yr = str(y)
        dp = a.get('TOTAL_DEPTH')
        if dp and (a.get('Metric') or '').strip().upper() in ('Y', 'YES', 'TRUE', '1', 'M'): dp = dp * 3.28084
        yield {'id': 'il:%d' % int(api), 'lat': float(lat), 'lon': float(lon), 'elev_ft': None, 'depth_ft': float(dp) if dp else None,
               'src': 'il', 'name': None, 'date': yr, 'log': sorted(logs[int(api)], key=lambda x: (x[0], x[1] or 0)), 'kind': a.get('TYPE')}
