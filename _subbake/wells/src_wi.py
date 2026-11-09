#!/usr/bin/env python3
"""Wisconsin wiscLITH v3 (WGNHS Open-File Report 2009-03; MS Access .mdb, read with the pure-python _mdb reader).
Geologist descriptions of cuttings/core: LITHOLOGY (~12.1k wells, rock type + color + grain size + notes) and FORMATNS
(stratigraphic picks, ~44k wells). A well's log is its LITHOLOGY intervals when it has any ('kind': 'lith'), else its
formation intervals ('kind': 'formations'). Depths in feet. Coordinates: LATITUDE/LONGITUDE in LOCATION, derived mostly
from the PLSS legal description (quarter-quarter... calls) - 'loc' = 'plss'. Driller and engineer names are never output.
Static release (file dated 2019-12-20); no update cadence."""
import os, re, sys, time, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _mdb

URL = 'https://data.wgnhs.wisc.edu/pubshare/WOFR2009-03.zip'
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'wi')
GRAIN = {'Vfn': 'very fine', 'VF': 'very fine', 'Fn': 'fine', 'M': 'medium', 'C': 'coarse', 'VC': 'very coarse', 'Gr': 'granule',
         'SP': 'small pebble', 'MP': 'medium pebble', 'LP': 'large pebble', 'Cb': 'cobble', 'Bl': 'boulder'}


def db():
    os.makedirs(CACHE, exist_ok=True)
    z = os.path.join(CACHE, 'WOFR2009-03.zip'); x = os.path.join(CACHE, 'x', 'wiscLITH.mdb')
    if not (os.path.exists(z) and os.path.getsize(z) > 0):
        for a in range(3):
            try:
                b = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=900).read()
                open(z + '.part', 'wb').write(b); os.replace(z + '.part', z); break
            except Exception:
                if a == 2: raise
                time.sleep(10)
    if not os.path.exists(x):
        os.makedirs(os.path.dirname(x), exist_ok=True)
        with zipfile.ZipFile(z) as zf, zf.open('wiscLITH.mdb') as src, open(x + '.part', 'wb') as o:
            while True:
                b = src.read(1 << 20)
                if not b: break
                o.write(b)
        os.replace(x + '.part', x)
    return _mdb.MDB(x)


def _s(v):
    v = re.sub(r'\s+', ' ', str(v)).strip() if v is not None else ''
    return '' if v in ('--', '-', 'None') else v


def wells():
    m = db()
    loc = {}
    for r in m.rows('LOCATION'):
        lat, lon = r.get('LATITUDE'), r.get('LONGITUDE')
        if lat is None or lon is None or not (42.4 <= lat <= 47.4 and -93.0 <= lon <= -86.2): continue
        loc[r['WELL_ID']] = r
    yr = {}
    for r in m.rows('DRILLERS'):
        y = r.get('YEAR_COMPLETED')
        if y and 1800 <= y <= 2100: yr[r['WELL_ID']] = str(y)
    lith = {}
    for r in m.rows('LITHOLOGY'):
        t = r.get('LITH_TOP')
        if t is None or t < 0 or r['WELL_ID'] not in loc: continue
        b = r.get('LITH_BOTTOM')
        parts = [_s(r.get('ROCK_TYPE')), _s(r.get('COLOR'))]
        gm = _s(r.get('LITH_MODE')) or _s(r.get('RANGE_ROCK_TYPE'))
        if gm:
            g = ' to '.join(dict.fromkeys(GRAIN.get(p.strip(), p.strip()) for p in gm.split('/') if p.strip()))
            if g: parts.append(g)
        parts.append(_s(r.get('DESCRIPTION')).rstrip('.'))
        d = ', '.join(p for p in parts if p)
        if not d: continue
        k = (round(t, 2), round(b, 2) if b is not None else None)
        lith.setdefault(r['WELL_ID'], {}).setdefault(k, []).append((_s(r.get('PRIORITY')).lower() or 'z', d))
    fm = {}
    for r in m.rows('FORMATNS'):
        t = r.get('TOP')
        if t is None or t < 0 or r['WELL_ID'] not in loc: continue
        n = _s(r.get('FORM_NAME'))
        if n: fm.setdefault(r['WELL_ID'], []).append([round(t, 2), r.get('BOTTOM'), n])
    for wid in sorted(set(lith) | set(fm)):
        L = loc[wid]
        if wid in lith:
            kind = 'lith'; log = []
            for (t, b), ds in lith[wid].items():
                ds.sort(); txt = '; '.join(dict.fromkeys(d for _, d in ds))
                log.append([float(t), float(b) if b is not None and b >= t else None, txt[:120]])
        else:
            kind = 'formations'
            log = [[float(t), round(float(b), 2) if b is not None and b >= t else None, n[:120]] for t, b, n in fm[wid]]
        log.sort(key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
        el = L.get('ELEVATION'); el = float(el) if el and 550 <= el <= 2000 else None
        dep = L.get('TOTAL_DEPTH') or L.get('WELL_DEPTH'); dep = float(dep) if dep and dep > 0 else None
        wu = _s(L.get('WISC_UNIQUE_WELL_NO'))
        yield {'id': 'wi:%d' % wid, 'lat': float(L['LATITUDE']), 'lon': float(L['LONGITUDE']), 'elev_ft': el, 'depth_ft': dep, 'src': 'wi',
               'name': ('WUWN ' + wu) if wu else 'WGNHS %d' % wid, 'date': yr.get(wid), 'log': log, 'loc': 'plss', 'kind': kind,
               'use': _s(L.get('WELL_USE')) or None}
