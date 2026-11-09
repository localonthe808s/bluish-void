#!/usr/bin/env python3
"""Washington — Washington Geological Survey (DNR) Subsurface Geology Information System: ~108k geotechnical borings/test pits
+ ~25k high-quality water wells (mostly from Ecology well reports, locations refined), with ~460k described layers.
MapServer https://gis.dnr.wa.gov/site3/rest/services/Geology/Subsurface_Data/MapServer : layer 0 'Borehole information',
layer 1 'Water wells', table 18 'Subsurface Layer Data' (TOP_DEPTH_FT/BOTTOM_DEPTH_FT/DESCRIPTION, feet). Paged by OBJECTID
(2000/page, sequential, cached). The same data ships as a file geodatabase (ger_portal_subsurface_database.zip) which stdlib
cannot read. CONTRACTOR_NAME and GEOLOGIST are never read. Ecology's full well-report archive (~500k+) is scanned images only.
Env WELLS_WA_CLASSES=water (water wells only) | all (default)."""
import json, os, re, time, urllib.parse, urllib.request
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'wa')
MS = 'https://gis.dnr.wa.gov/site3/rest/services/Geology/Subsurface_Data/MapServer/'
BOX = (45.4, 49.1, -124.9, -116.8)


def get(u, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return json.load(open(path))
    for a in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=180).read()
            d = json.loads(b.decode('utf-8'))
            if 'error' in d: raise ValueError(d['error'])
            tmp = path + '.part'; open(tmp, 'wb').write(b); os.replace(tmp, path); time.sleep(0.2); return d
        except Exception:
            time.sleep(5 * (a + 1))
    raise RuntimeError('failed ' + u)


def pages(layer, fields, geom):
    d = os.path.join(CACHE, 'L%d' % layer); os.makedirs(d, exist_ok=True)
    last, i = -1, 0
    while True:
        q = {'where': 'OBJECTID>%d' % last, 'outFields': 'OBJECTID,' + fields, 'orderByFields': 'OBJECTID',
             'resultRecordCount': 2000, 'returnGeometry': 'false', 'f': 'json'}
        j = get(MS + '%d/query?' % layer + urllib.parse.urlencode(q), os.path.join(d, 'p%05d_%d.json' % (i, last)))
        fs = j.get('features') or []
        if not fs: return
        for f in fs: yield f['attributes']
        last = max(f['attributes']['OBJECTID'] for f in fs); i += 1


def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def wells():
    logs = {}
    for a in pages(18, 'BOREHOLE_ID,TOP_DEPTH_FT,BOTTOM_DEPTH_FT,DESCRIPTION,SYMBOL_LITHOLOGY,USCS', False):
        t = clean(a.get('DESCRIPTION')) or clean(a.get('SYMBOL_LITHOLOGY')) or clean(a.get('USCS'))
        if not t or a.get('TOP_DEPTH_FT') is None or a.get('BOREHOLE_ID') is None: continue
        logs.setdefault(str(a['BOREHOLE_ID']), []).append((round(float(a['TOP_DEPTH_FT']), 1),
                                                           None if a.get('BOTTOM_DEPTH_FT') is None else round(float(a['BOTTOM_DEPTH_FT']), 1), t[:120]))
    layers = (1,) if os.environ.get('WELLS_WA_CLASSES', 'all') == 'water' else (1, 0)
    seen = set()
    for L in layers:
        for a in pages(L, 'BOREHOLE_ID,BOREHOLE_NAME,BOREHOLE_CLASS,BOREHOLE_TYPE,BOREHOLE_DEPTH_FT,BOREHOLE_DATE,ELEVATION_FT,LATITUDE,LONGITUDE,LOCATION_CONFIDENCE', False):
            bid = str(a.get('BOREHOLE_ID'))
            if bid in seen or bid not in logs: continue
            lat, lon = a.get('LATITUDE'), a.get('LONGITUDE')
            if lat is None or lon is None or not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
            seen.add(bid)
            lg = sorted(set(logs[bid]), key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
            nm = clean(a.get('BOREHOLE_NAME'))
            nm = nm if (nm and re.search(r'\d', nm) and len(nm) <= 30) else None  # keep boring labels like 'MW-3', drop word-only names
            dt = a.get('BOREHOLE_DATE')
            yr = time.strftime('%Y', time.gmtime(dt / 1000.0)) if isinstance(dt, (int, float)) else None
            yield {'id': 'wa:' + bid, 'lat': float(lat), 'lon': float(lon), 'elev_ft': a.get('ELEVATION_FT'),
                   'depth_ft': a.get('BOREHOLE_DEPTH_FT'), 'src': 'wa', 'name': nm,
                   'date': yr if yr and '1850' <= yr <= '2030' else None,
                   'log': [list(x) for x in lg], 'kind': a.get('BOREHOLE_TYPE') or a.get('BOREHOLE_CLASS'),
                   'loc': a.get('LOCATION_CONFIDENCE')}


if __name__ == '__main__':
    n = k = 0
    for w in wells(): n += 1; k += len(w['log'])
    print('wells', n, 'intervals', k)
