#!/usr/bin/env python3
"""Texas — TWDB Submitted Drillers Reports (SDR): every water-well report filed online by a licensed driller since 2001-2003
(~714k reports, ~713k with a lithology log). Bulk download (pipe-delimited text in a zip, rebuilt nightly, ~150 MB):
https://www.twdb.texas.gov/groundwater/data/SDRDownload.zip from https://www.twdb.texas.gov/groundwater/data/data-well-reports.asp
WellData.txt (location) + WellBoreHole.txt (depth) + WellLithology.txt (TopDepth/BottomDepth/LithologyDescription, feet).
WellData carries owner names/addresses and driller names/addresses: only the tracking number, coordinates, elevation and
drilling year are read out. Coordinates are the driller's (map pick or GPS), decimal degrees; reports flagged
KnownLocationError=Yes are dropped. Env WELLS_TXSDR_COUNTIES=Travis,Harris limits to counties (default all)."""
import io, os, re, time, urllib.request, zipfile
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'txsdr')
URL = 'https://www.twdb.texas.gov/groundwater/data/SDRDownload.zip'
BOX = (25.5, 36.8, -106.9, -93.2)


def fetch(u, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=600) as r, open(path + '.part', 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    f.write(b)
            os.replace(path + '.part', path); return path
        except Exception:
            time.sleep(5 * (a + 1))
    raise RuntimeError('download failed: ' + u)


def rows(z, name, join_last=False):
    """Yield lists; header first. A free-text last column with a stray pipe is re-joined when join_last."""
    with z.open(name) as fh:
        f = io.TextIOWrapper(fh, encoding='latin-1', newline='')
        h = f.readline().rstrip('\r\n').split('|'); n = len(h)
        yield h
        for line in f:
            p = line.rstrip('\r\n').split('|')
            if len(p) > n and join_last: p = p[:n - 1] + ['|'.join(p[n - 1:])]
            if len(p) != n: continue
            yield p


def num(s):
    try:
        v = float(s)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()[:120]


def wells():
    z = zipfile.ZipFile(fetch(URL, os.path.join(CACHE, 'SDRDownload.zip')))
    pre = 'SDRDownload/'
    cty = set(c.strip().lower() for c in os.environ.get('WELLS_TXSDR_COUNTIES', '').split(',') if c.strip())
    it = rows(z, pre + 'WellData.txt'); h = next(it); ix = {k: i for i, k in enumerate(h)}
    I_T, I_LA, I_LO, I_EL, I_DE, I_DS, I_KE, I_C = (ix['WellReportTrackingNumber'], ix['CoordDDLat'], ix['CoordDDLong'], ix['Elevation'],
                                                   ix['DrillingEndDate'], ix['DateSubmitted'], ix['KnownLocationError'], ix['County'])
    loc = {}
    for p in it:
        if p[I_KE].strip().lower() == 'yes': continue
        if cty and p[I_C].strip().lower() not in cty: continue
        lat, lon = num(p[I_LA]), num(p[I_LO])
        if lat is None or lon is None: continue
        if lon > 0: lon = -lon
        if not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
        y = (p[I_DE] or p[I_DS])[:4]
        el = num(p[I_EL])
        if el is not None and not (-300 < el < 9000): el = None
        loc[p[I_T]] = (lat, lon, el, y if re.match(r'^(19|20)\d\d$', y) else None)
    dep = {}
    it = rows(z, pre + 'WellBoreHole.txt'); h = next(it); ix = {k: i for i, k in enumerate(h)}
    for p in it:
        t = p[ix['WellReportTrackingNumber']]
        if t not in loc: continue
        b = num(p[ix['BottomDepth']])
        if b is not None and b > dep.get(t, 0): dep[t] = b

    def emit(t, lg):
        L = loc.get(t)
        if not L or not lg: return None
        lg.sort(key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
        seen = set(); out = []
        for x in lg:
            if x in seen: continue
            seen.add(x); out.append([round(x[0], 1), None if x[1] is None else round(x[1], 1), x[2]])
        d = dep.get(t) or max([x[1] for x in out if x[1] is not None] or [0]) or None
        return {'id': 'txsdr:' + t, 'lat': L[0], 'lon': L[1], 'elev_ft': L[2], 'depth_ft': d, 'src': 'txsdr',
                'name': 'SDR ' + t, 'date': L[3], 'log': out}

    it = rows(z, pre + 'WellLithology.txt', join_last=True); h = next(it); ix = {k: i for i, k in enumerate(h)}
    I_T, I_TO, I_BO, I_D = ix['WellReportTrackingNumber'], ix['TopDepth'], ix['BottomDepth'], ix['LithologyDescription']
    cur, lg = None, []
    for p in it:  # the file is grouped by tracking number (checked 2026-11-08)
        t = p[I_T]
        if t != cur:
            if cur is not None:
                w = emit(cur, lg)
                if w: yield w
            cur, lg = t, []
        if t not in loc: continue
        d, top = clean(p[I_D]), num(p[I_TO])
        if not d or top is None: continue
        lg.append((top, num(p[I_BO]), d))
    if cur is not None:
        w = emit(cur, lg)
        if w: yield w


if __name__ == '__main__':
    n = k = 0
    for w in wells(): n += 1; k += len(w['log'])
    print('wells', n, 'intervals', k)
