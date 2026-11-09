#!/usr/bin/env python3
"""Pennsylvania: PaGWIS (Pennsylvania Groundwater Information System, DCNR Bureau of Geological Survey). The statewide
weekly package WellsByState_AllPackages.zip (~120 MB zip, ~1.2 GB of CSV) from the PaGEODE "Download Data" panel:
Geologic.csv = the driller's log (Interval Top/Bottom (ft), Interval Description), SiteInformation.csv = location
accuracy, elevation, local well id; GeneralInformation.csv = well depth. Coordinates come in decimal degrees with a
coded accuracy; codes 1-4 (300 mi .. 2 mi) and wells outside a PA box are dropped. Optional env PA_COUNTIES=BERKS,BUCKS
limits to counties (default: statewide). Units: feet."""
import csv, io, os, re, time, urllib.request, zipfile
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'pa')
URL = 'https://www.pagwisdriller.dcnr.pa.gov/PAGEOD/PaGeodSearch/DownloadStatewideWellDocument'
ZIP = os.path.join(CACHE, 'WellsByState_AllPackages.zip')
BOX = (39.6, 42.4, -80.65, -74.6)
csv.field_size_limit(10 ** 7)


def fetch():
    os.makedirs(CACHE, exist_ok=True)
    if os.path.exists(ZIP) and os.path.getsize(ZIP) > 10 ** 6: return ZIP
    for a in range(3):
        try:
            tmp = ZIP + '.part'
            with urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=600) as r, open(tmp, 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    f.write(b)
            os.rename(tmp, ZIP); return ZIP
        except Exception:
            time.sleep(5 * (a + 1))
    raise RuntimeError('PaGWIS download failed')


def rows(z, name):
    return csv.DictReader(io.TextIOWrapper(z.open(name), 'utf-8', errors='replace'))


def num(s):
    try:
        s = (s or '').strip()
        return float(s) if s else None
    except ValueError:
        return None


def wells():
    z = zipfile.ZipFile(fetch())
    cty = set(c.strip().upper() for c in os.environ.get('PA_COUNTIES', '').split(',') if c.strip())
    logs, date = {}, {}
    for r in rows(z, 'Geologic.csv'):
        wid = (r.get('PA Well ID') or '').strip()
        top, bot = num(r.get('Interval Top (ft)')), num(r.get('Interval Bottom (ft)'))
        d = r.get('Interval Description') or ''
        if None in r or r.get('Longitude (DD)') is None:   # ~90 rows with a stray quote: keep only the text before it
            d = d.split('"')[0]
        d = re.sub(r'\s+', ' ', d).strip()[:120]
        if not wid or (top is None and not d): continue
        if top is None: continue
        if bot is not None and bot < top: top, bot = bot, top
        logs.setdefault(wid, []).append([top, bot, d])
        dd = (r.get('Date Drilled') or '')[:4]
        if re.match(r'(1[89]|20)\d\d$', dd): date[wid] = dd
    site = {}
    for r in rows(z, 'SiteInformation.csv'):
        wid = (r.get('PA Well ID') or '').strip()
        if wid not in logs or wid in site: continue
        if cty and (r.get('County') or '').strip().upper() not in cty: continue
        acc = (r.get('Location Accuracy') or '').strip()[:1]
        if acc in ('1', '2', '3', '4'): continue
        if not acc and 'GPS' not in (r.get('Location Method') or ''): continue
        lat, lon = num(r.get('Latitude (DD)')), num(r.get('Longitude (DD)'))
        if lat is None or lon is None or not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
        el = num(r.get('Elevation (ft)'))
        nm = re.sub(r'\s+', ' ', (r.get('Local Well ID') or '')).strip() or None
        site[wid] = (lat, lon, el if el else None, nm)
    depth = {}
    for r in rows(z, 'GeneralInformation.csv'):
        wid = (r.get('PA Well ID') or '').strip()
        if wid in site and wid not in depth:
            v = num(r.get('Well Depth (ft)'))
            if v: depth[wid] = v
    for wid in sorted(site, key=lambda x: int(x) if x.isdigit() else 0):
        lat, lon, el, nm = site[wid]
        seen, log = set(), []
        for iv in sorted(logs[wid], key=lambda x: (x[0], x[1] if x[1] is not None else 1e9)):
            k = tuple(iv)
            if k in seen: continue
            seen.add(k); log.append(iv)
        yield {'id': 'pa:' + wid, 'lat': lat, 'lon': lon, 'elev_ft': el, 'depth_ft': depth.get(wid), 'src': 'pa',
               'name': nm, 'date': date.get(wid), 'log': log}
