#!/usr/bin/env python3
"""MORE POLLUTION (user 2026-11-20: "do 1 2 3 4 5 6" + "lets add industrial discharge pipes now too").

One bake for the pollution layers that are too slow or too blocked to read live, each to its own small file on R2 pol/:

  hab_v1.json    algal blooms: EPA's national list of state bloom reports (advisories, warnings, closures) for the last
                 18 months, one row per water, plus NOAA HABSOS red-tide cell counts (Karenia brevis, the Gulf) for 45 days
  spill_v1.json  oil and chemical spills NOAA's response office was called to (IncidentNews; no CORS, so baked)
  pfx_v1.json    more PFAS: Superfund sites where PFAS was found, PFAS spills reported to the Coast Guard, federal and military
                 sites with PFAS, and plants that report PFAS in their wastewater (EPA PFAS Analytic Tools)
  tri_v1.json    toxic releases: every Toxics Release Inventory plant, pounds released to air, water and land (latest year)
  snc_v1.json    serious violators: EPA ECHO facilities in significant noncompliance now, by program
  lf_v1.json     landfills: EPA's Landfill Methane Outreach list (2,300 municipal landfills, with waste in place)
  rmp_v1.json    chemical plants that must file a Risk Management Plan (large amounts of toxic or flammable chemicals)

Brownfields (47k) and discharge pipes (300k) are read live by the page, a map view at a time, from zoom 10 in.

Run: python3 _polbake/bake.py OUTDIR [fast]     (no keys; fast = blooms and spills only, a minute; all = several minutes)
"""
import sys, os, re, csv, io, json, math, time, datetime, subprocess, urllib.request, urllib.parse

A = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/'
G = 'https://gispub.epa.gov/arcgis/rest/services/'
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid pollution bake)'}
TODAY = datetime.date.today()


def fetch(u, tries=4, timeout=180):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()
        except Exception:
            try:   # local Python 3.9 cannot shake hands with some EPA hosts; curl can
                return subprocess.run(['curl', '-sS', '-m', str(timeout), '-A', UA['User-Agent'], u], check=True, capture_output=True).stdout
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(6 * (i + 1))


def rows(url, where='1=1', fields='*', geom=False, page=2000):
    """every row of an ArcGIS layer, paged by OBJECTID (oid field name given in url after '#', default OBJECTID)"""
    oid = 'OBJECTID'
    out, last = [], -1
    while True:
        q = {'where': '(%s) AND %s>%d' % (where, oid, last), 'outFields': fields, 'returnGeometry': 'true' if geom else 'false',
             'orderByFields': oid, 'resultRecordCount': page, 'f': 'json'}
        if geom:
            q['outSR'] = 4326
        j = json.loads(fetch(url + '/query?' + urllib.parse.urlencode(q)))
        if 'features' not in j:
            raise RuntimeError(url + ' ' + str(j)[:300])
        F = j['features']
        if not F:
            break
        for f in F:
            a = f['attributes']
            last = max(last, a[oid])
            if geom:
                g = f.get('geometry') or {}
                a['_x'], a['_y'] = g.get('x'), g.get('y')
            out.append(a)
        if len(F) < page and not j.get('exceededTransferLimit'):
            break
        print('  ', url.split('/services/')[1][:50], len(out), flush=True)
    return out


def ll(a, la, lo):
    try:
        y, x = float(a[la]), float(a[lo])
    except (TypeError, ValueError, KeyError):
        return None
    if not (-90 < y < 90 and -180 <= x <= 180) or (abs(y) < .01 and abs(x) < .01):
        return None
    return round(y, 4), round(x, 4)


def ms_day(v):
    try:
        return datetime.datetime.utcfromtimestamp(v / 1000).date().isoformat()
    except Exception:
        return ''


def s(v, n=90):
    v = re.sub(r'\s+', ' ', str(v or '')).strip()
    return v[:n]


def num(v):
    try:
        f = float(v)
        return round(f, 1) if f == f else 0
    except (TypeError, ValueError):
        return 0


def save(outdir, name, doc):
    doc['built'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')
    p = os.path.join(outdir, name)
    json.dump(doc, open(p, 'w'), separators=(',', ':'))
    print(name, os.path.getsize(p) // 1024, 'KB', {k: len(v) for k, v in doc.items() if isinstance(v, (list, dict))}, flush=True)


# ---------- algal blooms ----------
def hab(outdir):
    since = (TODAY - datetime.timedelta(days=548)).isoformat()
    R = rows(A + 'Harmful_Algal_Blooms_in_the_US/FeatureServer/0', "Bloom_Date >= DATE '%s'" % since,
             'OBJECTID,Waterbody_Name,Category,Bloom_Date,State_Abbrev,SourceURL', geom=True)
    W = {}
    for a in R:
        p = ll(a, '_y', '_x')
        if not p:
            continue
        nm = s(a.get('Waterbody_Name'), 80)
        k = (nm.lower(), round(p[0], 2), round(p[1], 2))
        d = ms_day(a.get('Bloom_Date'))
        cat = re.sub(r'(?i)harmful algal bloom\s*', '', s(a.get('Category'), 40)).strip() or 'Bloom'
        w = W.setdefault(k, [p[0], p[1], nm, s(a.get('State_Abbrev'), 2), cat, d, 0, s(a.get('SourceURL'), 160), d])
        w[6] += 1
        if d > w[5]:
            w[4], w[5] = cat, d
        if d and (not w[8] or d < w[8]):
            w[8] = d
    # NOAA HABSOS: red tide cell counts, last 45 days, one row per site (the highest count and its day)
    since2 = (TODAY - datetime.timedelta(days=45)).isoformat()
    T = rows('https://gis.ncdc.noaa.gov/arcgis/rest/services/ms/HABSOS_CellCounts/MapServer/0', "SAMPLE_DATE >= DATE '%s'" % since2,
             'OBJECTID,DESCRIPTION,LATITUDE,LONGITUDE,STATE_ID,SAMPLE_DATE,GENUS,SPECIES,CATEGORY,CELLCOUNT')
    S = {}
    for a in T:
        p = ll(a, 'LATITUDE', 'LONGITUDE')
        if not p:
            continue
        k = (round(p[0], 3), round(p[1], 3))
        c, d = num(a.get('CELLCOUNT')), ms_day(a.get('SAMPLE_DATE'))
        r = S.setdefault(k, [p[0], p[1], s(a.get('DESCRIPTION'), 70), s(a.get('STATE_ID'), 2), d, c, s(a.get('CATEGORY'), 24), 0, d, c])
        r[7] += 1
        if c > r[5]:
            r[5], r[6] = c, s(a.get('CATEGORY'), 24)
        if d >= r[8]:
            r[8], r[9] = d, c            # the newest sample and its count
        r[4] = max(r[4], d)
    save(outdir, 'hab_v1.json', {'since': since, 'rt_since': since2,
                                 'w': sorted(W.values(), key=lambda w: w[5], reverse=True),
                                 'rt': sorted(S.values(), key=lambda r: r[4], reverse=True)})


# ---------- spills ----------
def spill(outdir):
    txt = fetch('https://incidentnews.noaa.gov/raw/incidents.csv').decode('utf-8', 'replace')
    out = []
    for r in csv.DictReader(io.StringIO(txt)):
        p = ll(r, 'lat', 'lon')
        if not p:
            continue
        out.append([int(r['id']), s(r.get('open_date'), 10), s(r.get('name'), 110), p[0], p[1], s(r.get('threat'), 20), s(r.get('commodity'), 70),
                    num(r.get('max_ptl_release_gallons')), s(r.get('description'), 200)])
    out.sort(key=lambda r: r[1], reverse=True)
    save(outdir, 'spill_v1.json', {'s': out})


# ---------- more PFAS ----------
def pfx(outdir):
    P = A + 'PFAS_Analytic_Tools_Layers/FeatureServer/'
    sf = []
    for a in rows(P + '2', fields='OBJECTID,F_Site_Name,City,State,Link,Latitude,Longitude,NPL_Status,Site_Type'):
        p = ll(a, 'Latitude', 'Longitude')
        if p:
            sf.append([p[0], p[1], s(a.get('F_Site_Name')), s(a.get('City'), 40), s(a.get('State'), 2), s(a.get('NPL_Status'), 40), s(a.get('Link'), 200)])
    sp = []
    for a in rows(P + '12', fields='OBJECTID,Date,Year,Amount_of_Material,Unit,Material_Involved,Responsible_Company,Cause,Water_Reached_,Amount_in_Water,Unit_Reached_Water,Latitude,Longitude,City,State,Incident_Description'):
        p = ll(a, 'Latitude', 'Longitude')
        if p:
            d = ms_day(a['Date']) if isinstance(a.get('Date'), (int, float)) else s(a.get('Date') or a.get('Year'), 10)
            sp.append([p[0], p[1], d, s(a.get('Material_Involved'), 70), num(a.get('Amount_of_Material')), s(a.get('Unit'), 16), s(a.get('Responsible_Company'), 70),
                       s(a.get('Water_Reached_'), 6), s(a.get('City'), 40), s(a.get('State'), 2), s(a.get('Cause'), 40), s(a.get('Incident_Description'), 220)])
    fed = []
    F = json.loads(fetch(P + '13?f=json'))
    names = [f['name'] for f in F.get('fields', [])]
    gw = [n for n in names if re.match(r'(PFOA|PFOS)_Maximum_Detected_in_Groundwater', n)]
    for a in rows(P + '13', fields=','.join(['OBJECTID', 'F_Site_Name', 'Federal_Agency', 'State', 'PFAS_Presence', 'Link', 'Property_Type', 'DoW_Reported_Cleanup_Status', 'Latitude', 'Longitude'] + gw)):
        p = ll(a, 'Latitude', 'Longitude')
        if p:
            mx = {n.split('_')[0]: a.get(n) for n in gw}
            fed.append([p[0], p[1], s(a.get('F_Site_Name')), s(a.get('Federal_Agency'), 60), s(a.get('PFAS_Presence'), 40), s(mx.get('PFOA'), 20), s(mx.get('PFOS'), 20),
                        s(a.get('DoW_Reported_Cleanup_Status'), 60), s(a.get('State'), 2), s(a.get('Link'), 200)])
    D = {}
    for a in rows(P + '15', fields='OBJECTID,F_Facility,Year,NPDES_Permit_Number,City,State,Latitude,Longitude,Parameter_Description,Pollutant_Load__kg_yr_,Facility_Type'):
        p = ll(a, 'Latitude', 'Longitude')
        if not p:
            continue
        k = a.get('NPDES_Permit_Number') or (p[0], p[1])
        d = D.setdefault(k, [p[0], p[1], s(a.get('F_Facility')), s(a.get('City'), 40), s(a.get('State'), 2), s(a.get('Facility_Type'), 40), 0, 0, {}, s(a.get('NPDES_Permit_Number'), 12)])
        d[7] = max(d[7], int(num(a.get('Year'))))
        prm = re.sub(r'\s+', ' ', str(a.get('Parameter_Description') or '')).strip()
        if prm:
            try:
                v = float(a.get('Pollutant_Load__kg_yr_') or 0)
            except (TypeError, ValueError):
                v = 0.0
            d[8][prm] = max(d[8].get(prm, 0), round(v, 4))
    dm = []
    for d in D.values():
        prm = sorted([kv for kv in d[8].items() if kv[1] > 0], key=lambda kv: -kv[1])
        if not prm:          # monitored, nothing measured: not a source
            continue
        dm.append([d[0], d[1], d[2], d[3], d[4], d[5], d[7], round(sum(v for k, v in prm), 4), [[k[:50], v] for k, v in prm[:6]], len(prm), d[9]])
    save(outdir, 'pfx_v1.json', {'sf': sf, 'sp': sp, 'fed': fed, 'dm': dm})


# ---------- algae seen from space ----------
# Viridis, as EPA renders CyAN (sampled from matplotlib once; kept here so the bake needs only numpy and Pillow)
VIR = [[68, 1, 84], [71, 13, 96], [72, 24, 106], [72, 35, 116], [71, 46, 124], [69, 56, 130], [66, 65, 134], [62, 74, 137], [58, 84, 140], [54, 93, 141], [50, 101, 142], [46, 109, 142], [43, 117, 142], [40, 125, 142], [37, 132, 142], [34, 140, 141], [31, 148, 140], [30, 156, 137], [32, 163, 134], [37, 171, 130], [46, 179, 124], [58, 186, 118], [72, 193, 110], [88, 199, 101], [108, 205, 90], [127, 211, 78], [147, 215, 65], [168, 219, 52], [192, 223, 37], [213, 226, 26], [234, 229, 26], [253, 231, 37]]
CY_COL = {1: (253, 230, 138, 190), 2: (255, 159, 28, 225), 3: (255, 59, 48, 240), 4: (193, 18, 31, 255)}


def cyan(outdir):
    """ALGAE SEEN FROM SPACE: EPA CyAN's daily picture of the lower 48 (Sentinel-3 OLCI, 300 m, web mercator, its bounds in the
    PNG), the last seven days stacked newest first, each pixel sorted into four levels by the World Health Organization's
    recreational lines (about 20,000 and 100,000 cells per mL), cut into tiles z4-9 under OUT/cyan/ plus cyan_v1.json"""
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    V = np.array(VIR, float)
    # 32 samples of viridis cover 0..255; position on the scale -> level (calibrated against CyAN's own point readings, 2026-11-20:
    # about 20,000 cells/mL near position 70, 100,000 near 135; EPA paints the worst blooms past viridis in gold and orange)
    C, B, days, seen = None, None, [], set()
    for back in range(1, 8):
        d = TODAY - datetime.timedelta(days=back)
        u = 'https://cyan.epa.gov/waterbody/conus_image/?year=%d&day=%d&daily=True' % (d.year, d.timetuple().tm_yday)
        try:
            raw = fetch(u, tries=2, timeout=300)
        except Exception as e:
            print('  cyan', d, 'failed', e, flush=True); continue
        if raw[:4] != b'\x89PNG':
            print('  cyan', d, 'none', flush=True); continue
        h = hash(raw)
        if h in seen:          # the service hands back the nearest day it has when a day is missing
            print('  cyan', d, 'same picture as a later day', flush=True); continue
        seen.add(h)
        im = Image.open(io.BytesIO(raw))
        dd0 = '%s-%s' % (im.info.get('Year', ''), im.info.get('Day', ''))
        try:
            d = datetime.date(int(im.info['Year']), 1, 1) + datetime.timedelta(days=int(im.info['Day']) - 1)
        except Exception:
            pass
        b = eval(im.info.get('Bounds', 'None'), {'__builtins__': {}}) if im.info.get('Bounds') else None
        a = np.asarray(im.convert('RGBA'))
        if b is None or (B is not None and (a.shape[:2] != C.shape or b != B)):
            print('  cyan', d, 'other grid, skipped', flush=True); continue
        m = a[..., 3] > 0
        lv = np.zeros(a.shape[:2], np.uint8)
        px = a[m][:, :3].astype(float)
        dd = ((px[:, None, :] - V[None]) ** 2).sum(-1)
        pos = dd.argmin(1) * (255 / 31.0)
        off = np.sqrt(dd.min(1)) > 30
        lv[m] = np.where(off, 4, np.where(pos < 70, 1, np.where(pos < 135, 2, 3)))
        if C is None:
            C, B = lv, b
        else:
            C = np.where(C == 0, lv, C)
        days.append(d.isoformat())
        print('  cyan', d, int(m.sum()), 'px', flush=True)
    if C is None:
        save(outdir, 'cyan_v1.json', {'days': [], 'tiles': 0}); return
    H, W = C.shape
    my = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    Y0, Y1 = my(B['top']), my(B['bottom'])
    root = os.path.join(outdir, 'cyan')
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    # z9 tiles: every tile holding a level-coded pixel, sampled nearest
    Z = 9; N = 256 * 2 ** Z
    ys, xs = np.nonzero(C)
    lon = B['left'] + (xs + .5) / W * (B['right'] - B['left'])
    yy = Y0 + (ys + .5) / H * (Y1 - Y0)
    gx = ((lon + 180) / 360 * N).astype(int); gy = ((1 - yy / math.pi) / 2 * N).astype(int)
    T = {}
    for tx, ty in set(zip((gx // 256).tolist(), (gy // 256).tolist())):
        jx = np.arange(256) + tx * 256 + .5; jy = np.arange(256) + ty * 256 + .5
        lo = jx / N * 360 - 180; my2 = math.pi * (1 - 2 * jy / N)
        ix = np.floor((lo - B['left']) / (B['right'] - B['left']) * W).astype(int); iy = np.floor((Y0 - my2) / (Y0 - Y1) * H).astype(int)
        okx = (ix >= 0) & (ix < W); oky = (iy >= 0) & (iy < H)
        t = np.zeros((256, 256), np.uint8)
        t[np.ix_(oky, okx)] = C[np.ix_(iy[oky], ix[okx])]
        if t.any():
            T[(tx, ty)] = t
    n = 0
    for z in range(Z, 3, -1):
        if z < Z:     # parents: 2x2 max of the children, so a small lake stays visible zoomed out
            P = {}
            for (tx, ty), t in T.items():
                q = P.setdefault((tx // 2, ty // 2), np.zeros((256, 256), np.uint8))
                h = t.reshape(128, 2, 128, 2).max(axis=(1, 3))
                ox, oy = (tx % 2) * 128, (ty % 2) * 128
                q[oy:oy + 128, ox:ox + 128] = np.maximum(q[oy:oy + 128, ox:ox + 128], h)
            T = P
        for (tx, ty), t in T.items():
            rgba = np.zeros((256, 256, 4), np.uint8)
            for k, c in CY_COL.items():
                rgba[t == k] = c
            pth = os.path.join(root, str(z), str(tx)); os.makedirs(pth, exist_ok=True)
            Image.fromarray(rgba, 'RGBA').save(os.path.join(pth, '%d.png' % ty), optimize=True); n += 1
    save(outdir, 'cyan_v1.json', {'days': days, 'tiles': n, 'levels': [int((C == k).sum()) for k in (1, 2, 3, 4)]})


# ---------- toxic releases ----------
TRI_URL = 'https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/%d_US/csv'


def tri_year(y, tmp):
    """one year's TRI basic file (every chemical at every plant, ~60 MB), streamed to disk and read row by row"""
    p = os.path.join(tmp, 'tri_%d.csv' % y)
    if not os.path.exists(p):
        try:
            with urllib.request.urlopen(urllib.request.Request(TRI_URL % y, headers=UA), timeout=600) as r, open(p + '.part', 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
        except Exception:
            subprocess.run(['curl', '-sS', '-L', '-m', '900', '-A', UA['User-Agent'], '-o', p + '.part', TRI_URL % y], check=True)
        os.replace(p + '.part', p)
    with open(p, encoding='utf-8', errors='replace', newline='') as f:
        R = csv.reader(f)
        H = [h.split('. ', 1)[-1].strip() for h in next(R)]
        ix = {h: i for i, h in enumerate(H)}
        for row in R:
            if len(row) == len(H):
                yield {h: row[i] for h, i in ix.items()}


def tri(outdir):
    """TOXIC RELEASES from the TRI basic files: per plant the latest year's pounds by where they went, its top chemicals with
    the cancer / PBT / PFAS flags, the pounds of cancer-causing chemicals, and the total for each of the four years before"""
    tmp = os.path.join(outdir, '_tri')
    os.makedirs(tmp, exist_ok=True)
    yr = None
    for y in range(TODAY.year - 1, TODAY.year - 4, -1):      # the newest year EPA has published (it lands each summer/fall)
        try:
            if sum(1 for _ in zip(range(20000), tri_year(y, tmp))) >= 20000:
                yr = y
                break
        except Exception as e:
            print('  TRI', y, 'not ready:', e, flush=True)
    if not yr:
        raise RuntimeError('no TRI year')
    lbs = lambda a, k: num(a.get(k)) * (1 / 453.59237 if (a.get('UNIT OF MEASURE') or '').lower().startswith('gram') else 1)
    F = {}
    for a in tri_year(yr, tmp):
        p = ll(a, 'LATITUDE', 'LONGITUDE')
        if not p:
            continue
        k = a['TRIFD']
        f = F.setdefault(k, {'p': p, 'n': s(a.get('FACILITY NAME')), 'c': s(a.get('CITY'), 40), 'st': s(a.get('ST'), 2), 'sec': s(a.get('INDUSTRY SECTOR'), 40),
                             'frs': s(a.get('FRS ID'), 14), 'air': 0.0, 'wat': 0.0, 'lnd': 0.0, 'off': 0.0, 'tot': 0.0, 'carc': 0.0, 'ch': {}})
        air = lbs(a, '5.1 - FUGITIVE AIR') + lbs(a, '5.2 - STACK AIR')
        wat = lbs(a, '5.3 - WATER')
        on = lbs(a, 'ON-SITE RELEASE TOTAL')
        off = lbs(a, 'OFF-SITE RELEASE TOTAL')
        tot = lbs(a, 'TOTAL RELEASES')
        f['air'] += air; f['wat'] += wat; f['lnd'] += max(0.0, on - air - wat); f['off'] += off; f['tot'] += tot
        carc = (a.get('CARCINOGEN') or '').upper() == 'YES'
        if carc:
            f['carc'] += tot
        nm = re.sub(r'\s+', ' ', a.get('CHEMICAL') or '').strip()
        fl = ('C' if carc else '') + ('B' if (a.get('PBT') or '').upper() == 'YES' else '') + ('F' if (a.get('PFAS') or '').upper() == 'YES' else '')
        c = f['ch'].setdefault(nm, [0.0, fl])
        c[0] += tot
    trend = {}
    for y in range(yr - 4, yr):
        T = {}
        try:
            for a in tri_year(y, tmp):
                T[a['TRIFD']] = T.get(a['TRIFD'], 0.0) + lbs(a, 'TOTAL RELEASES')
        except Exception as e:
            print('  TRI trend', y, 'skipped:', e, flush=True)
        trend[y] = T
    out = []
    for k, f in F.items():
        ch = sorted(f['ch'].items(), key=lambda kv: -kv[1][0])
        top = [[n[:44], round(v[0], 1 if v[0] < 10 else 0), v[1]] for n, v in ch[:5] if v[0] > 0]
        cx = [[n[:44], round(v[0], 1 if v[0] < 10 else 0)] for n, v in ch if 'C' in v[1] and v[0] > 0][:3]
        tr = [round(trend[y][k]) if k in trend[y] else None for y in range(yr - 4, yr)] + [round(f['tot'])]
        out.append([f['p'][0], f['p'][1], f['n'][:60], f['c'], f['st'], f['sec'][:30], round(f['air']), round(f['wat']), round(f['lnd']), round(f['off']), round(f['tot']),
                    k, f['frs'], top, round(f['carc']), tr, len(ch), cx])
    out.sort(key=lambda r: r[10])          # smallest first: the big ones paint on top
    save(outdir, 'tri_v1.json', {'year': yr, 'years': list(range(yr - 4, yr + 1)), 'f': out})


# ---------- discharge permits over their limits ----------
def exc(outdir):
    """ECHO: every water permit whose own test results went over a permit limit in the last 13 quarters, with how many times"""
    out = {}
    for a in rows(A + 'ECHO_All_Media_Facilities/FeatureServer/0', 'cwa_13qtrs_efflnt_exceedances > 0', 'OBJECTID,npdes_ids,cwa_13qtrs_efflnt_exceedances,cwa_qtrs_with_nc'):
        n = int(num(a.get('cwa_13qtrs_efflnt_exceedances')))
        if n <= 0:
            continue
        for pid in re.split(r'[\s,]+', str(a.get('npdes_ids') or '')):
            if pid:
                out[pid] = [n, int(num(a.get('cwa_qtrs_with_nc')))]
    save(outdir, 'exc_v1.json', {'p': out})


# ---------- serious violators ----------
def snc(outdir):
    F = 'OBJECTID,registry_id,fac_name,fac_city,fac_state,fac_lat,fac_long,fac_qtrs_with_nc,fac_total_penalties,fac_date_last_formal_action,fac_date_last_inspection,caa_hpv_flag,cwa_snc_flag,rcra_snc_flag,sdwa_snc_flag,caa_compliance_status,cwa_compliance_status,rcra_compliance_status,sdwa_compliance_status,fac_federal_flg,dfr_url'
    out = []
    for a in rows(A + 'ECHO_All_Media_Facilities/FeatureServer/0', "fac_snc_flg='Y'", F):
        p = ll(a, 'fac_lat', 'fac_long')
        if not p:
            continue
        pr = [n for n, f in (('AIR', 'caa_hpv_flag'), ('WATER', 'cwa_snc_flag'), ('HAZARDOUS WASTE', 'rcra_snc_flag'), ('DRINKING WATER', 'sdwa_snc_flag')) if a.get(f) == 'Y']
        st = {n: s(a.get(f), 60) for n, f in (('AIR', 'caa_compliance_status'), ('WATER', 'cwa_compliance_status'), ('HAZARDOUS WASTE', 'rcra_compliance_status'), ('DRINKING WATER', 'sdwa_compliance_status')) if n in pr}
        dl = a.get('fac_date_last_formal_action')
        out.append([p[0], p[1], s(a.get('fac_name')), s(a.get('fac_city'), 40), s(a.get('fac_state'), 2), pr, int(num(a.get('fac_qtrs_with_nc'))), round(num(a.get('fac_total_penalties'))),
                    ms_day(dl) if isinstance(dl, (int, float)) else s(dl, 10), s(a.get('registry_id'), 14), 0, 1 if a.get('fac_federal_flg') == 'Y' else 0])
    save(outdir, 'snc_v1.json', {'f': out})


# ---------- landfills ----------
def lf(outdir):
    out = []
    for a in rows(A + 'New_Landfills/FeatureServer/0', fields='OBJECTID,landfill_name,county_state,landfill_owner_org,year_landfill_opened,landfill_closure_year,current_landfill_status,waste_in_place_tons,waste_in_place_year,lfg_collection_system,lfg_collected_mmscfd,latitude,longitude'):
        p = ll(a, 'latitude', 'longitude')
        if p:
            out.append([p[0], p[1], s(a.get('landfill_name')), s(a.get('county_state'), 50), s(a.get('landfill_owner_org'), 70), s(a.get('year_landfill_opened'), 6), s(a.get('landfill_closure_year'), 6),
                        s(a.get('current_landfill_status'), 20), round(num(a.get('waste_in_place_tons'))), s(a.get('waste_in_place_year'), 6), s(a.get('lfg_collection_system'), 6), num(a.get('lfg_collected_mmscfd'))])
    save(outdir, 'lf_v1.json', {'f': out})


# ---------- chemical plants (RMP) ----------
def rmp(outdir):
    out, seen = [], set()
    for a in rows(A + 'FRS_INTERESTS_RMP/FeatureServer/0', fields='OBJECTID,REGISTRY_ID,PRIMARY_NAME,CITY_NAME,STATE_CODE,LATITUDE83,LONGITUDE83,ACTIVE_STATUS,FAC_URL,PGM_SYS_ID'):
        p = ll(a, 'LATITUDE83', 'LONGITUDE83')
        if not p or a.get('REGISTRY_ID') in seen:
            continue
        seen.add(a.get('REGISTRY_ID'))
        out.append([p[0], p[1], s(a.get('PRIMARY_NAME')), s(a.get('CITY_NAME'), 40), s(a.get('STATE_CODE'), 2), s(a.get('ACTIVE_STATUS'), 12), s(a.get('REGISTRY_ID'), 14)])
    save(outdir, 'rmp_v1.json', {'f': out})


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
    os.makedirs(outdir, exist_ok=True)
    jobs = [hab, spill, cyan] + ([] if len(sys.argv) > 2 and sys.argv[2] == 'fast' else [pfx, tri, exc, snc, lf, rmp])
    bad = 0
    for j in jobs:
        try:
            j(outdir)
        except Exception as e:     # one dead service must not stop the rest
            bad += 1
            print('FAILED', j.__name__, e, flush=True)
    sys.exit(1 if bad == len(jobs) else 0)


if __name__ == '__main__':
    main()
