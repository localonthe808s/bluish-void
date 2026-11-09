#!/usr/bin/env python3
"""Michigan: EGLE Wellogic (statewide water-well database), public open-data MapServer EGLE/DwOpenData:
layer 3 "Wellogic Wells" (~1.18M records with lat/lon; METHD_COLL = how the point was collected) and table 4
"Well Lithology" (~5.8M rows: WELLID, SEQ_NUM, PRIM_LITH, LITH_MOD, COLOR, DEPTH = bottom of the unit,
THICKNESS). Top = DEPTH - THICKNESS (falls back to the previous unit's bottom). Drillers pick PRIM_LITH/LITH_MOD
from Wellogic's word lists, so the description is "<color> <lith>, <modifier>". Paged by OBJECTID range, 1000 rows
a page (the server max), sequential, pages cached gzipped (~7k requests the first time). Units: feet.
Optional env MI_COUNTIES=63,82 keeps only those 2-digit county codes (first two digits of WELLID)."""
import gzip, json, os, re, time, urllib.parse, urllib.request
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'mi')
B = 'https://gisagoegle.state.mi.us/arcgis/rest/services/EGLE/DwOpenData/MapServer'
STEP = 1000
BOX = (41.6, 48.4, -90.5, -82.1)


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
    raise RuntimeError('MI fetch failed: ' + url)


def maxoid(layer):
    q = {'where': '1=1', 'f': 'json', 'outStatistics': json.dumps([{'statisticType': 'max', 'onStatisticField': 'OBJECTID', 'outStatisticFieldName': 'mx'}])}
    d = get('%s/%d/query?%s' % (B, layer, urllib.parse.urlencode(q)), os.path.join(CACHE, 'max_%d.json.gz' % layer))
    return int(d['features'][0]['attributes']['mx'])


def pages(layer, fields):
    sub = os.path.join(CACHE, 'l%d' % layer); os.makedirs(sub, exist_ok=True)
    for lo in range(0, maxoid(layer), STEP):
        q = {'where': 'OBJECTID>%d AND OBJECTID<=%d' % (lo, lo + STEP), 'outFields': fields, 'returnGeometry': 'false',
             'orderByFields': 'OBJECTID', 'f': 'json'}
        d = get('%s/%d/query?%s' % (B, layer, urllib.parse.urlencode(q)), os.path.join(sub, '%08d.json.gz' % lo))
        for f in d.get('features', []): yield f['attributes']


def num(v):
    try:
        return None if v is None or v == '' else float(v)
    except (TypeError, ValueError):
        return None


def clean(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()


def build(rows):
    rows.sort(key=lambda a: (num(a.get('SEQ_NUM')) or 0))
    log, prev = [], 0.0
    for a in rows:
        bot, th = num(a.get('DEPTH')), num(a.get('THICKNESS'))
        if bot is None: continue
        top = bot - th if th is not None and 0 <= th <= bot else prev
        lith, mod, col = clean(a.get('PRIM_LITH')), clean(a.get('LITH_MOD')), clean(a.get('COLOR'))
        d = ' '.join(x for x in (col, lith) if x)
        if mod: d = d + ', ' + mod if d else mod
        if not d: continue
        log.append([round(top, 1), round(bot, 1), d[:120]]); prev = bot
    log.sort(key=lambda x: (x[0], x[1]))
    return log


def wells():
    os.makedirs(CACHE, exist_ok=True)
    cty = set(c.strip().zfill(2) for c in os.environ.get('MI_COUNTIES', '').split(',') if c.strip())
    info = {}
    for a in pages(3, 'WELLID,LATITUDE,LONGITUDE,ELEVATION,WELL_DEPTH,CONST_DATE,METHD_COLL'):
        wid = clean(a.get('WELLID'))
        if not wid or wid in info or (cty and wid[:2] not in cty): continue
        lat, lon = num(a.get('LATITUDE')), num(a.get('LONGITUDE'))
        if lat is None or lon is None or not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
        yr = (a.get('CONST_DATE') or '')[:4]
        info[wid] = (lat, lon, num(a.get('ELEVATION')) or None, num(a.get('WELL_DEPTH')) or None,
                     yr if re.match(r'(18|19|20)\d\d$', yr) else None)
    done, cur, buf = set(), None, []

    def emit(wid, rows):
        if wid in done or wid not in info: return None
        log = build(rows)
        if not log: return None
        done.add(wid)
        lat, lon, el, dp, yr = info[wid]
        return {'id': 'mi:' + wid, 'lat': lat, 'lon': lon, 'elev_ft': el, 'depth_ft': dp, 'src': 'mi',
                'name': None, 'date': yr, 'log': log}
    for a in pages(4, 'WELLID,SEQ_NUM,PRIM_LITH,LITH_MOD,COLOR,DEPTH,THICKNESS'):
        wid = clean(a.get('WELLID'))
        if wid != cur:
            if cur is not None:
                w = emit(cur, buf)
                if w: yield w
            cur, buf = wid, []
        buf.append(a)
    if cur is not None:
        w = emit(cur, buf)
        if w: yield w
