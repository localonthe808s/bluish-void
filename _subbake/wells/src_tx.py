#!/usr/bin/env python3
"""Texas — TWDB Groundwater Database (GWDB), the state's curated well inventory (~140k wells, ~16k with a lithology log).
Bulk download (pipe-delimited text in a zip, rebuilt nightly): https://www.twdb.texas.gov/groundwater/data/GWDBDownload.zip
from https://www.twdb.texas.gov/groundwater/data/data-well-reports.asp . WellMain.txt (location/depth/elevation) joined to
WellLithology.txt (TopDepth/BottomDepth/LithologyDescription, feet below land surface) on StateWellNumber.
Owner and driller columns are never read out. Coordinates: decimal degrees (NAD83), source per well (GPS, +/-1 sec, ...)."""
import io, os, re, time, urllib.request, zipfile
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'tx')
URL = 'https://www.twdb.texas.gov/groundwater/data/GWDBDownload.zip'
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


def rows(z, name):
    with z.open(name) as fh:
        f = io.TextIOWrapper(fh, encoding='latin-1', newline='')
        h = f.readline().rstrip('\r\n').split('|')
        n = len(h)
        for line in f:
            p = line.rstrip('\r\n').split('|')
            if len(p) < n: continue
            if len(p) > n: continue  # stray pipe inside a free-text field: skip the row rather than misalign
            yield dict(zip(h, p))


def num(s):
    try:
        v = float(s)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()[:120]


def wells():
    z = zipfile.ZipFile(fetch(URL, os.path.join(CACHE, 'GWDBDownload.zip')))
    pre = 'GWDBDownload/'
    logs = {}
    for r in rows(z, pre + 'WellLithology.txt'):
        d = clean(r['LithologyDescription'])
        t = num(r['TopDepth'])
        if not d or t is None: continue
        logs.setdefault(r['StateWellNumber'], []).append([t, num(r['BottomDepth']), d])
    for r in rows(z, pre + 'WellMain.txt'):
        swn = r['StateWellNumber']
        lg = logs.get(swn)
        if not lg: continue
        lat, lon = num(r['LatitudeDD']), num(r['LongitudeDD'])
        if lat is None or lon is None: continue
        if lon > 0: lon = -lon
        if not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
        lg.sort(key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
        seen = set(); out = []
        for x in lg:
            k = (x[0], x[1], x[2])
            if k in seen: continue
            seen.add(k); out.append([round(x[0], 1), None if x[1] is None else round(x[1], 1), x[2]])
        y = (r.get('DrillingYear') or '').strip()
        yield {'id': 'tx:' + swn, 'lat': lat, 'lon': lon, 'elev_ft': num(r['LandSurfaceElevation']),
               'depth_ft': num(r['WellDepth']), 'src': 'tx', 'name': 'SWN ' + swn,
               'date': y if re.match(r'^(18|19|20)\d\d$', y) else None, 'log': out,
               'aq': clean(r.get('Aquifer')) or None, 'loc': clean(r.get('CoordinateSource')) or None}


if __name__ == '__main__':
    n = k = 0
    for w in wells(): n += 1; k += len(w['log'])
    print('wells', n, 'intervals', k)
