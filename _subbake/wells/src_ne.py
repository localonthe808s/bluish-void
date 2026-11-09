#!/usr/bin/env python3
"""Nebraska CSD Test Hole Database (Conservation and Survey Division, UNL; THDB.accdb read with the pure-python _mdb
reader). ~5.6k CSD test holes with geologist sample descriptions (table Lith: unit + description by footage); 'do' (ditto)
rows repeat the previous description. Depths in feet. Coordinates: Lat/Lng NAD83, mostly computed from the PLSS
subsection + footages (Lat_Lng_ref empty, loc='plss'); a few GPS/survey. Elevation = Fin_Elev (DEM). Updated as needed
(the zip is regenerated; file dated 2026-11-06)."""
import os, re, sys, time, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _mdb

URL = 'https://csdportal1.unl.edu/webdata/DB/THDB.zip'   # linked from https://csd.unl.edu/geology/testholes/ (go.unl.edu/thdbdl)
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'ne')


def db():
    os.makedirs(CACHE, exist_ok=True)
    z = os.path.join(CACHE, 'THDB.zip'); x = os.path.join(CACHE, 'x', 'THDB.accdb')
    if not (os.path.exists(z) and os.path.getsize(z) > 0):
        for a in range(3):
            try:
                b = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=900).read()
                open(z + '.part', 'wb').write(b); os.replace(z + '.part', z); break
            except Exception:
                if a == 2: raise
                time.sleep(10)
    if not os.path.exists(x) or os.path.getmtime(x) < os.path.getmtime(z):
        os.makedirs(os.path.dirname(x), exist_ok=True)
        with zipfile.ZipFile(z) as zf, zf.open('THDB.accdb') as src, open(x + '.part', 'wb') as o:
            while True:
                b = src.read(1 << 20)
                if not b: break
                o.write(b)
        os.replace(x + '.part', x)
    return _mdb.MDB(x)


def _s(v):
    v = re.sub(r'\s+', ' ', str(v)).strip() if v is not None else ''
    return '' if v in ('None', '-', '--') else v


def wells():
    m = db()
    hdr = {}
    for r in m.rows('GenChar'):
        lat, lon = r.get('Lat'), r.get('Lng')
        if lat is None or lon is None or not (39.9 <= lat <= 43.1 and -104.1 <= lon <= -95.2): continue
        hdr[r['DBid']] = r
    rows = {}
    for r in m.rows('Lith'):
        if r.get('DBid') in hdr and r.get('DepFm') is not None:
            rows.setdefault(r['DBid'], []).append(r)
    for k in sorted(rows):
        h = hdr[k]; log = []; prev = ''
        for r in sorted(rows[k], key=lambda r: (r['DepFm'], r.get('DepTo') if r.get('DepTo') is not None else 1e9, r.get('Unique_ID') or 0)):
            unit = _s(r.get('LithUnit')); d = _s(r.get('Descrpt'))
            if d.lower().rstrip('.') in ('do', 'ditto'): d = prev
            elif d.lower() == 'no detailed description recorded': d = ''
            else: prev = d
            txt = (unit + ': ' + d) if unit and d else (unit or d)
            if not txt: continue
            t, b = round(float(r['DepFm']), 2), r.get('DepTo')
            b = round(float(b), 2) if b is not None else None
            if t < 0: continue
            log.append([t, float(b) if b is not None and b >= t else None, txt[:120]])
        if not log: continue
        el = h.get('Fin_Elev') or h.get('FldLog_Elev'); el = float(el) if el and 800 <= el <= 5500 else None
        td = h.get('TD'); td = float(td) if td and td > 0 else None
        y = h.get('YrDrill'); y = str(int(y)) if y and 1880 <= y <= 2100 else None
        ref = _s(h.get('Lat_Lng_ref')).lower()
        yield {'id': 'ne:%s' % k, 'lat': float(h['Lat']), 'lon': float(h['Lng']), 'elev_ft': el, 'depth_ft': td, 'src': 'ne',
               'name': ('CSD test hole ' + _s(h.get('LogID'))) if _s(h.get('LogID')) else None, 'date': y, 'log': log,
               'loc': ref if ref in ('gps', 'surveyor') else 'plss'}
