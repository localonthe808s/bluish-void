#!/usr/bin/env python3
"""Minnesota County Well Index (CWI), Minnesota Geological Survey + Minnesota Department of Health, via the Minnesota Geospatial
Commons GeoPackage 'Well Information from County Well Index for the General Public' (non-public-water-supply wells; ~830 MB
SQLite, read with stdlib sqlite3). Log = table C5ST (driller's description + color + hardness), depths in feet.
Coordinates are UTM 15N NAD83 (UTME/UTMN). Located wells ('allwells' with UTM) carry the CWI geocode method in 'loc'
(GPS / digitized from 1:24k / ...); wells only in 'unloc_wells' are placed from the PLSS description by MDH and are
UNVERIFIED (loc='plss-unverified'); set MN_UNLOC=0 to skip them. WELLNAME (owner names) is never read."""
import os, re, sqlite3, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _utm

URL = 'https://operations.gis.data.mn.gov/api/publicdownload/download/207/water_well_information_non_pws.gpkg'
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'mn')
GCM = {'S': 'surveyed', 'A': 'digitized-24k', 'A**': 'digitized-24k', 'B': 'digitized-100k', 'I': 'gps', 'G': 'gps', 'G3': 'gps',
       'G6A': 'gps', 'G6O': 'gps', 'DS1': 'digitized-24k', 'DS2': 'digitized-12k', 'PQ6': 'plss', 'SPL': 'state-plane', 'UNK': 'unknown'}


def fetch():
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, 'water_well_information_non_pws.gpkg')
    if os.path.exists(p) and os.path.getsize(p) > 0: return p
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=1800) as r, open(p + '.part', 'wb') as o:
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    o.write(b)
            os.replace(p + '.part', p); return p
        except Exception:
            if a == 2: raise
            time.sleep(10 * (a + 1))


def _s(x):
    return re.sub(r'\s+', ' ', str(x)).strip() if x is not None else ''


def wells():
    db = sqlite3.connect('file:%s?mode=ro' % fetch(), uri=True)
    color = {_s(c): _s(d).lower() for c, d in db.execute('select CODE, DESCRPTN from COLOR')}
    hard = {_s(c): _s(d).lower() for c, d in db.execute('select CODE, DESCRPTN from HARDNESS')}
    meta = {}
    q = ('select RELATEID, UTME, UTMN, ELEVATION, DEPTH_DRLL, DEPTH_COMP, DATE_DRLL, GCM_CODE, USE_C, UNIQUE_NO, AQUIFER from %s')
    srcs = [('allwells', None)]
    if os.environ.get('MN_UNLOC', '1') != '0': srcs.append(('unloc_wells', 'plss-unverified'))
    for tbl, tag in srcs:
        for rid, e, n, el, dd, dc, dt, gcm, use, uno, aq in db.execute(q % tbl):
            if rid in meta or e is None or n is None: continue
            try: lat, lon = _utm.to_ll(float(e), float(n), 15)
            except Exception: continue
            if not (43.3 <= lat <= 49.5 and -97.4 <= lon <= -89.4): continue
            dep = dd or dc
            yr = str(int(dt))[:4] if dt and 1850 <= int(dt) // 10000 <= 2100 else None
            el = float(el) if el and 600 <= el <= 2400 else None
            meta[rid] = (lat, lon, el, float(dep) if dep and dep > 0 else None, yr, tag or GCM.get(_s(gcm), 'unknown'),
                         _s(use) or None, _s(uno).lstrip('0') or None, _s(aq) or None)
    cur = None; log = []

    def emit(rid, log):
        m = meta.get(rid)
        if not m or not log: return None
        log.sort(key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
        lat, lon, el, dep, yr, loc, use, uno, aq = m
        return {'id': 'mn:' + rid.lstrip('0'), 'lat': lat, 'lon': lon, 'elev_ft': el, 'depth_ft': dep, 'src': 'mn',
                'name': uno and ('MN unique no. ' + uno), 'date': yr, 'log': log, 'loc': loc, 'use': use, 'aq': aq}

    for rid, t, b, desc, col, hd, strat in db.execute(
            'select RELATEID, DEPTH_TOP, DEPTH_BOT, DRLLR_DESC, COLOR, HARDNESS, STRAT from C5ST order by RELATEID, DEPTH_TOP, C5ST_SEQ_NO'):
        if rid != cur:
            if cur is not None:
                w = emit(cur, log)
                if w: yield w
            cur = rid; log = []
        if t is None or t < 0: continue
        d = _s(desc)
        if not d: continue
        if d.isupper(): d = d.capitalize()
        for extra in (color.get(_s(col)) or _s(col).lower(), hard.get(_s(hd)) or _s(hd).lower()):
            if extra and extra.lower() not in d.lower(): d = (d + ', ' + extra) if d else extra
        b = float(b) if b is not None and b >= t else None
        log.append([float(t), b, d[:120]])
    if cur is not None:
        w = emit(cur, log)
        if w: yield w
