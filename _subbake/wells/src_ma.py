#!/usr/bin/env python3
"""Massachusetts: MassDEP Well Driller Program well completion reports (WCRs).
Locations: MassDEP "Well Drillers Data Layer" (ArcGIS feature service Well_Location_Viewer_Data_4_26_23, a static snapshot of
4/26/2023: 127,011 parcel-validated WCRs of ~206,000 on file). Logs: each WCR's report, generated as a text PDF by the EEA Data
Portal (DataLakeAPI WellDrilling/generatereport/<id>); its OVERBURDEN and BEDROCK tables give From/To (ft) + Lithology + Color
+ Comment. Only WCRs flagged OVERBURDEN or BEDROCK = YES in the layer (~83,400) are fetched (MA_ALL=1 tries every WCR).
One PDF (~8-40 KB) per well, so a full run is ~83k polite requests (hours); MA_TOWNS=GLOUCESTER,ROCKPORT limits the towns,
MA_MAX caps the count, MA_WORKERS (default 1) and MA_SLEEP (default 0.3 s) set the pace. PDFs are cached, reruns are offline.
No owner, street address, or driller is output. Terms: "Permission is granted to copy and use the materials herein." (layer item)."""
import concurrent.futures as cf, json, os, re, time, urllib.parse, urllib.request, zlib
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'ma')
LAYER = 'https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services/Well_Location_Viewer_Data_4_26_23/FeatureServer/0/query'
REPORT = 'https://eeaonline.eea.state.ma.us/EEA/DataLake/V1.0/DataLakeAPI/WellDrilling/generatereport/%d'
FIELDS = 'Well_Completion_Report_ID,Latitude,Longitude,Town,Date_Drilled,Total_Depth_of_Well,Well_Type,Depth_to_Bedrock,OVERBURDEN,BEDROCK,ObjectId2'
SLEEP = float(os.environ.get('MA_SLEEP', '0.3'))


def get(u, path, timeout=90, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 0: return open(path, 'rb').read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for a in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()
            open(path + '.part', 'wb').write(b); os.replace(path + '.part', path); return b
        except Exception:
            time.sleep(3 * (a + 1))
    return None


def sites():
    where = '1=1' if os.environ.get('MA_ALL') else "OVERBURDEN='YES' OR BEDROCK='YES'"
    tag = 'all' if os.environ.get('MA_ALL') else 'lith'
    off, out = 0, []
    while True:
        q = urllib.parse.urlencode({'where': where, 'outFields': FIELDS, 'returnGeometry': 'false', 'orderByFields': 'ObjectId2',
                                    'resultOffset': off, 'resultRecordCount': 1000, 'f': 'json'})
        b = get(LAYER + '?' + q, os.path.join(CACHE, 'layer', '%s_%06d.json' % (tag, off)))
        if b is None: raise RuntimeError('layer page failed at offset %d' % off)
        d = json.loads(b)
        if 'features' not in d: raise RuntimeError('layer error: %s' % str(d)[:200])
        fs = [f['attributes'] for f in d['features']]
        out.extend(fs)
        if len(fs) < 1000 and not d.get('exceededTransferLimit'): break
        if not fs: break
        off += len(fs)
    return out


# ---- PDF table reader (the report is a generated PDF: every table cell is "q x y w h re W n ... BT ... (text) Tj ... ET Q")
CELL = re.compile(rb'q ([\d.-]+) ([\d.-]+) ([\d.-]+) ([\d.-]+) re W n\r?\n(.*?)\r?\nQ', re.S)
TXT = re.compile(rb'Td \(((?:\\.|[^\\)])*)\) Tj')


def unesc(s):
    s = s.decode('latin-1')
    return re.sub(r'\\([()\\])', r'\1', s)


def pages(b):
    for m in re.finditer(rb'stream\r?\n(.*?)endstream', b, re.S):
        try: s = zlib.decompress(m.group(1))
        except Exception: continue
        cells = []
        for c in CELL.finditer(s):
            t = [unesc(x) for x in TXT.findall(c.group(5))]
            if t: cells.append((float(c.group(1)), float(c.group(2)), ' '.join(x.strip() for x in t).strip()))
        if cells: yield cells


def fnum(s):
    try: return float(str(s).replace(',', '').strip())
    except (TypeError, ValueError): return None


def parse(b):
    log, cols = [], None
    for cells in pages(b):
        heads = sorted(set(round(y, 1) for x, y, t in cells if t == 'From(ft)'), reverse=True)
        lith_heads = []
        for hy in heads:
            row = {t: x for x, y, t in cells if abs(y - hy) < 0.6}
            if 'Lithology' in row and 'To(ft)' in row: lith_heads.append((hy, row))
        spans = []  # (ytop, ybottom, cols)
        first = heads[0] if heads else 1e9
        if cols is not None: spans.append((1e9 if not heads else first, -1e9, cols))  # continuation from previous page
        for hy, row in lith_heads:
            below = [h for h in heads if h < hy - 0.6]
            spans.append((hy, below[0] if below else -1e9, row))
            cols = row
        for ytop, ybot, row in spans:
            names = {'From(ft)': 'f', 'To(ft)': 't', 'Lithology': 'l', 'Color': 'c', 'Comment': 'm'}
            cx = [(names[k], v) for k, v in row.items() if k in names]
            rows = {}
            for x, y, t in cells:
                if not (ybot + 0.6 < y < ytop - 0.6): continue
                for k, v in cx:
                    if abs(x - v) < 1.5:
                        rows.setdefault(round(y, 1), {})[k] = t
            for y in sorted(rows, reverse=True):
                r = rows[y]
                top = fnum(r.get('f')); bot = fnum(r.get('t'))
                lith = re.sub(r'\s+', ' ', r.get('l') or '').strip()
                col = re.sub(r'\s+', ' ', r.get('c') or '').strip()
                com = re.sub(r'\s+', ' ', r.get('m') or '').strip()
                if top is None or r.get('f') == 'From(ft)' or not (lith or com): continue
                d = lith or com
                if col: d += ', ' + col.lower()
                if com and lith: d += '; ' + com
                log.append([top, bot if (bot is not None and bot >= top) else None, d[:120]])
    out, seen = [], set()
    for iv in sorted(log, key=lambda v: (v[0], v[1] if v[1] is not None else 1e9)):
        k = tuple(iv)
        if k in seen: continue
        seen.add(k)
        if out and out[-1][2] == iv[2] and out[-1][1] is not None and out[-1][1] == iv[0]:
            out[-1][1] = iv[1]; continue  # merge runs like Granite 3-103, 103-203, ... into one interval
        out.append(list(iv))
    return out


def year(s):
    m = re.search(r'(\d{4})', s or '')
    return m.group(1) if m and 1850 <= int(m.group(1)) <= 2030 else None


def wells():
    ss = sites()
    towns = set(t.strip().upper() for t in os.environ.get('MA_TOWNS', '').split(',') if t.strip())
    if towns: ss = [s for s in ss if (s.get('Town') or '').upper() in towns]
    seen, todo = set(), []
    for s in ss:
        i = s.get('Well_Completion_Report_ID')
        lat, lon = s.get('Latitude'), s.get('Longitude')
        if not i or i <= 0 or i in seen or lat is None or lon is None: continue
        if not (41.15 <= lat <= 42.95 and -73.6 <= lon <= -69.85): continue
        seen.add(i); todo.append(s)
    mx = int(os.environ.get('MA_MAX', '0') or 0)
    if mx: todo = todo[:mx]

    def one(s):
        i = int(s['Well_Completion_Report_ID'])
        p = os.path.join(CACHE, 'pdf', '%04d' % (i // 1000), '%d.pdf' % i)
        cached = os.path.exists(p) and os.path.getsize(p) > 0
        b = get(REPORT % i, p)
        if not cached: time.sleep(SLEEP)
        if not b or not b.startswith(b'%PDF'): return None
        log = parse(b)
        if not log: return None
        dep = fnum(s.get('Total_Depth_of_Well'))
        return {'id': 'ma:%d' % i, 'lat': float(s['Latitude']), 'lon': float(s['Longitude']), 'elev_ft': None,
                'depth_ft': dep if dep and dep > 0 else None, 'src': 'ma',
                'name': None, 'date': year(s.get('Date_Drilled')), 'log': [[round(a, 1), None if b2 is None else round(b2, 1), t] for a, b2, t in log],
                'type': s.get('Well_Type')}
    nw = int(os.environ.get('MA_WORKERS', '1'))
    if nw <= 1:
        for s in todo:
            w = one(s)
            if w: yield w
    else:
        with cf.ThreadPoolExecutor(nw) as ex:
            for k in range(0, len(todo), 200):
                for w in ex.map(one, todo[k:k + 200]):
                    if w: yield w


if __name__ == '__main__':
    import sys
    for f in sys.argv[1:]:
        print(f, json.dumps(parse(open(f, 'rb').read())))
