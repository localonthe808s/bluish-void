#!/usr/bin/env python3
"""Kansas WWC5 (Water Well Completion Records), Kansas Geological Survey: driller's lithology logs for ~247k water wells and
test holes, from the KGS bulk archive (wwc5_wells.zip + wwc5_lith_log.zip, refreshed by KGS about monthly). Depths in feet.
Coordinates: NAD83 lon/lat; ~76% are computed from the PLSS legal description (quarter-quarter-quarter call, i.e. a ~10-acre
spot, worst case ~1/4 mi), ~24% GPS. 'loc' carries 'gps' or 'plss'. Owners, directions, driller names are dropped."""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kgs


def wells():
    meta = {}
    for r in _kgs.rows('ks', 'wwc5_wells.zip'):
        lat = _kgs.num(r.get('NAD83_LATITUDE')) or _kgs.num(r.get('LATITUDE'))
        lon = _kgs.num(r.get('NAD83_LONGITUDE')) or _kgs.num(r.get('LONGITUDE'))
        if not _kgs.inks(lat, lon): continue
        y = re.search(r'(\d{4})\s*$', r.get('COMPLE_DATE') or '')
        meta[r['WELL_ID']] = (lat, lon, _kgs.num(r.get('ELEV')), _kgs.num(r.get('WELL_DEPTH')), y.group(1) if y else None,
                              'gps' if (r.get('LONG_LAT_TYPE') or '').upper().startswith('GPS') else 'plss', (r.get('WELL_USE') or '').strip() or None)
    cur = None; log = []

    def emit(wid, log):
        m = meta.get(wid)
        if not m or not log: return None
        log.sort(key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
        out = []; seen = set()
        for iv in log:
            k = (iv[0], iv[1], iv[2].lower())
            if k in seen: continue
            seen.add(k); out.append(iv)
        lat, lon, el, dep, yr, loc, use = m
        if el is not None and not (500 <= el <= 4100): el = None
        if dep is not None and dep <= 0: dep = None
        return {'id': 'ks:' + wid, 'lat': lat, 'lon': lon, 'elev_ft': el, 'depth_ft': dep, 'src': 'ks', 'name': 'WWC5 ' + wid,
                'date': yr, 'log': out, 'loc': loc, 'use': use}

    # the lith file is grouped by WELL_ID; tolerate it not being so by buffering per id
    buf = {}
    for r in _kgs.rows('ks', 'wwc5_lith_log.zip'):
        wid = r['WELL_ID']
        t, b = _kgs.num(r.get('TOP')), _kgs.num(r.get('BOTTOM'))
        d = re.sub(r'\s+', ' ', (r.get('LOG') or '')).strip()[:120]
        if t is None or not d or t < 0: continue
        if b is not None and b < t: b = None
        buf.setdefault(wid, []).append([t, b, d])
        if cur is not None and wid != cur and cur in buf:
            w = emit(cur, buf.pop(cur))
            if w: yield w
        cur = wid
    for wid, lg in buf.items():
        w = emit(wid, lg)
        if w: yield w
