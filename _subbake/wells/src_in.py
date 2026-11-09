#!/usr/bin/env python3
"""Indiana: IDNR Division of Water, Water Well Record Database, as published on IndianaMap (gisdata.in.gov hosted
feature service WaterWells_1): layer 0 = ~415k well points (Web Mercator, asked for in WGS84), table 1 = ~2.13M lithology
rows (dblrefno, dbltop, dblbottom, strformati = the driller's words). Paged by objectid range, 1000 rows a page
(the server max), sequential with a small sleep, every page cached gzipped. Wells located only to a county centroid are
dropped; the rest are field located (GPS/field), office located/geocoded, address-geocoded, or the centre of a PLSS
quarter section (loc_type says which). Units: feet."""
import gzip, json, os, re, time, datetime, urllib.parse, urllib.request
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'in')
B = 'https://gisdata.in.gov/server/rest/services/Hosted/WaterWells_1/FeatureServer'
STEP = 1000
BOX = (37.7, 41.8, -88.2, -84.7)


def get(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with gzip.open(path, 'rb') as f: return json.loads(f.read())
    for a in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
            d = json.loads(b)
            if 'error' in d: raise ValueError(str(d['error'])[:200])
            with gzip.open(path + '.part', 'wb') as f: f.write(b)
            os.rename(path + '.part', path)
            time.sleep(0.1)
            return d
        except Exception:
            time.sleep(3 * (a + 1))
    raise RuntimeError('IN fetch failed: ' + url)


def maxoid(layer):
    q = {'where': '1=1', 'f': 'json', 'outStatistics': json.dumps([{'statisticType': 'max', 'onStatisticField': 'objectid', 'outStatisticFieldName': 'mx'}])}
    d = get('%s/%d/query?%s' % (B, layer, urllib.parse.urlencode(q)), os.path.join(CACHE, 'max_%d.json.gz' % layer))
    return int(d['features'][0]['attributes']['mx'])


def pages(layer, fields, extra):
    sub = os.path.join(CACHE, 'l%d' % layer); os.makedirs(sub, exist_ok=True)
    mx = maxoid(layer)
    for lo in range(0, mx, STEP):
        q = {'where': 'objectid>%d AND objectid<=%d' % (lo, lo + STEP), 'outFields': fields, 'f': 'json', 'orderByFields': 'objectid'}
        q.update(extra)
        d = get('%s/%d/query?%s' % (B, layer, urllib.parse.urlencode(q)), os.path.join(sub, '%08d.json.gz' % lo))
        for f in d.get('features', []): yield f


def num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def wells():
    os.makedirs(CACHE, exist_ok=True)
    logs = {}
    for f in pages(1, 'dblrefno,dbltop,dblbottom,strformati', {'returnGeometry': 'false'}):
        a = f['attributes']; r = a.get('dblrefno'); top = num(a.get('dbltop')); bot = num(a.get('dblbottom'))
        d = re.sub(r'\s+', ' ', a.get('strformati') or '').strip()[:120]
        if r is None or top is None or (not d and bot is None): continue
        if bot is not None and bot < top: top, bot = bot, top
        logs.setdefault(int(r), []).append([top, bot, d])
    seen = set()
    for f in pages(0, 'dblrefno,loc_type,dbldepth,dblgrndelev,dtmcompdate', {'outSR': '4326', 'returnGeometry': 'true'}):
        a = f['attributes']; g = f.get('geometry') or {}
        r = a.get('dblrefno')
        if r is None: continue
        r = int(r)
        if r not in logs or r in seen: continue
        if (a.get('loc_type') or '').startswith('County'): continue
        lat, lon = num(g.get('y')), num(g.get('x'))
        if lat is None or lon is None or not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
        seen.add(r)
        dt = a.get('dtmcompdate'); yr = None
        if isinstance(dt, (int, float)):
            try:
                y = (datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=dt)).year
                if 1850 <= y <= 2030: yr = str(y)
            except (OverflowError, ValueError):
                pass
        log, k = [], set()
        for iv in sorted(logs[r], key=lambda x: (x[0], x[1] if x[1] is not None else 1e9)):
            if tuple(iv) in k: continue
            k.add(tuple(iv)); log.append(iv)
        el, dp = num(a.get('dblgrndelev')), num(a.get('dbldepth'))
        yield {'id': 'in:%d' % r, 'lat': round(lat, 6), 'lon': round(lon, 6), 'elev_ft': el or None, 'depth_ft': dp or None,
               'src': 'in', 'name': None, 'date': yr, 'log': log, 'loc': a.get('loc_type')}
