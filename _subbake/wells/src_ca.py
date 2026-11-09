#!/usr/bin/env python3
"""California — DWR Well Completion Reports (OSWCR index, ~1.1M reports) on the California Natural Resources Agency open-data
portal, dataset 'well-completion-reports' (https://data.cnra.ca.gov/dataset/well-completion-reports), with three
machine-readable geologic-log tables: Free Form (~1.09M intervals / ~90k reports, mostly digitized by USGS and DWR's AEM
program), Quick Pick (~7k reports) and USCS/ASTM D2488 (~3k reports). Interval depths in feet. CSVs refreshed daily.
One log per report: free form > quick pick > USCS (and within free form the DATASOURCE with the most rows).
Owner well number, address, APN and driller name columns are never read. Coordinates: most reports sit at the centre of the
PLSS section (METHODOFDETERMINATIONLL 'Derived from TRS' / LLACCURACY 'Centroid of Section'), passed through as 'loc'."""
import csv, os, re, sys, time, urllib.request
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'ca')
P = 'https://data.cnra.ca.gov/dataset/647afc02-8954-426d-aabd-eff418d2652c/resource/'
FILES = {'wcr': P + '8da7b93b-4e69-495d-9caa-335691a1896b/download/wellcompletionreports.csv',
         'ff': P + 'def8769a-c9a1-4cf7-9522-2588f20f2f39/download/geologiclog_freeform.csv',
         'qp': P + '35a622d6-58e5-406a-a034-a17012132fc5/download/geologiclog_quickpick.csv',
         'us': P + '8762f589-156d-499d-9a06-3a7db1ebe34d/download/geologiclog_uscs.csv'}
BOX = (32.4, 42.1, -124.6, -114.0)
csv.field_size_limit(10 ** 7)


def fetch(u):
    path = os.path.join(CACHE, u.rsplit('/', 1)[1])
    if os.path.exists(path) and os.path.getsize(path) > 0: return path
    os.makedirs(CACHE, exist_ok=True)
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


def rd(key):
    return csv.DictReader(open(fetch(FILES[key]), encoding='utf-8', errors='replace', newline=''))


def num(s):
    try:
        v = float(str(s).replace(',', '').strip())
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def cl(*parts):
    return re.sub(r'\s+', ' ', ', '.join(p.strip() for p in parts if p and p.strip())).strip()[:120]


def wells():
    logs = {}
    ff = {}
    for r in rd('ff'):
        t, top = cl(r['DESCRIPTION']), num(r['INTERVALSTART'])
        if not t or top is None: continue
        ff.setdefault(r['WCRNUMBER'], {}).setdefault(r.get('DATASOURCE') or '', []).append((top, num(r['INTERVALEND']), t))
    for w, d in ff.items():
        logs[w] = max(d.values(), key=len)
    ff = None
    for key, fn in (('qp', lambda r: cl(r['MATERIALDESCRIPTION']) or cl(r['MATERIALCOLOR'], r['MATERIALTYPE'], r['MATERIALTEXTURE'])),
                    ('us', lambda r: cl(r['SOILCLASSIFICATION'], r['SOILCOLOR'], r['SOILDESCRIPTION']))):
        add = {}
        for r in rd(key):
            if r['WCRNUMBER'] in logs: continue
            t, top = fn(r), num(r['INTERVALSTART'])
            if not t or top is None: continue
            add.setdefault(r['WCRNUMBER'], []).append((top, num(r['INTERVALEND']), t))
        logs.update(add)
    seen = set()
    for r in rd('wcr'):
        w = r['WCRNUMBER']
        if w not in logs or w in seen: continue
        lat, lon = num(r['DECIMALLATITUDE']), num(r['DECIMALLONGITUDE'])
        if lat is None or lon is None: continue
        if lon > 0: lon = -lon
        if not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
        seen.add(w)
        lg = sorted(set(logs[w]), key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
        m = re.search(r'(18|19|20)\d\d', r.get('DATEWORKENDED') or '')
        el = num(r['GROUNDSURFACEELEVATION'])
        dep = num(r['TOTALCOMPLETEDDEPTH']) or num(r['TOTALDRILLDEPTH'])
        yield {'id': 'ca:' + w, 'lat': lat, 'lon': lon, 'elev_ft': el if el and -300 < el < 15000 else None,
               'depth_ft': dep if dep and dep > 0 else None, 'src': 'ca', 'name': w, 'date': m.group(0) if m else None,
               'log': [[round(x[0], 1), None if x[1] is None else round(x[1], 1), x[2]] for x in lg],
               'kind': (r.get('PLANNEDUSEFORMERUSE') or '').strip() or None,
               'loc': (r.get('LLACCURACY') or r.get('METHODOFDETERMINATIONLL') or '').strip() or None}


if __name__ == '__main__':
    n = k = 0
    for w in wells(): n += 1; k += len(w['log'])
    print('wells', n, 'intervals', k)
