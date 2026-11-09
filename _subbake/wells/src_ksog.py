#!/usr/bin/env python3
"""Kansas oil & gas wells, Kansas Geological Survey: formation TOPS (ks_tops.zip, ~2.1M picks on ~197k wells) turned into a
stratigraphic column. Each pick's top runs to the next deeper pick (or the pick's own BASE when KGS gives one; the last one to
the well's total depth from ks_wells.zip, else open). Picks are measured depths in feet below the log datum (usually kelly
bushing, a few ft above ground). Where several sources pick the same unit, the KGS pick wins, else the shallowest.
Descriptions are formation/member names (e.g. 'Heebner Shale Member'), not cuttings descriptions.
Coordinates NAD27 lon/lat from footages / quarter calls / GPS (~58% footages, 18% GPS, rest quarter-call or section centre);
'loc' carries it. Operators and lease names are dropped; name = API number."""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _kgs

LOC = {'From GPS': 'gps', 'Calc. from footages': 'footages', 'Calc. from quarter calls': 'plss', 'Center of section': 'section'}


def wells():
    meta = {}
    for r in _kgs.rows('ksog', 'ks_wells.zip'):
        lat, lon = _kgs.num(r.get('LATITUDE')), _kgs.num(r.get('LONGITUDE'))
        if not _kgs.inks(lat, lon): continue
        y = None
        for k in ('SPUD', 'COMPLETION', 'PERMIT'):
            m = re.search(r'(\d{4})\s*$', r.get(k) or '')
            if m: y = m.group(1); break
        el = _kgs.num(r.get('SURFACE_ELEVATION_LIDAR')) or _kgs.num(r.get('ELEVATION'))
        meta[r['KID']] = (lat, lon, el, _kgs.num(r.get('DEPTH')), y, LOC.get(r.get('LONG_LAT_SOURCE'), 'unknown'),
                          (r.get('API_NUMBER') or '').strip() or None)
    picks = {}
    for r in _kgs.rows('ksog', 'ks_tops.zip'):
        kid = r['KID']
        if kid not in meta: continue
        t = _kgs.num(r.get('TOP'))
        fm = re.sub(r'\s+', ' ', r.get('FORMATION') or '').strip()[:120]
        if t is None or t < 0 or not fm: continue
        b = _kgs.num(r.get('BASE'))
        if b is not None and b <= t: b = None
        kgs = (r.get('SOURCE') or '').startswith('KGS')
        d = picks.setdefault(kid, {})
        k = fm.lower(); old = d.get(k)
        if old is None or (kgs and not old[3]) or (kgs == old[3] and t < old[0]):
            d[k] = (t, b, fm, kgs)
    for kid in sorted(picks, key=lambda s: int(s) if s.isdigit() else 0):
        lat, lon, el, dep, yr, loc, api = meta[kid]
        p = sorted(picks[kid].values(), key=lambda x: (x[0], x[2]))
        if dep is not None and dep <= 0: dep = None
        log = []
        for i, (t, b, fm, _) in enumerate(p):
            nxt = next((q[0] for q in p[i + 1:] if q[0] > t), None)
            bot = b if b is not None else (nxt if nxt is not None else (dep if dep and dep > t else None))
            log.append([t, bot, fm])
        if el is not None and not (500 <= el <= 4100): el = None
        yield {'id': 'ksog:' + kid, 'lat': lat, 'lon': lon, 'elev_ft': el, 'depth_ft': dep, 'src': 'ksog', 'name': api and ('API ' + api),
               'date': yr, 'log': log, 'loc': loc, 'kind': 'tops'}
