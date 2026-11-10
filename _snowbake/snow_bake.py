#!/usr/bin/env python3
"""THE SNOW BAKE (user 2026-11-08: "we're going to need to track snowfall this winter and relate that to ski mountains in the
northeast and west coast" -> "start the snow tab ... snow accumulation / 72 hour / week accumulation / predictions").

Twice a day, after NOHRSC's 12Z analysis and again in the evening, this writes to R2 snow/v1/:
  depth.png    snow on the ground now: NOAA SNODAS (NSIDC G02158, masked CONUS, 30 arc-second, millimeters), the 05Z model day
  24h.png      snowfall in the last 24 hours ending 12Z  \
  72h.png      ... the last 72 hours                       > NOHRSC National Snowfall Analysis v2 (sfav2, 0.04 deg, inches):
  7d.png       ... the last 7 days (seven 24-hour grids)  /  station reports blended with radar and the model first guess
  season.png   ... since September 30 12Z
  latest.json  the dates, each picture's bounds, the color stops, and every resort's numbers (resorts_v1.json beside this script)
Each picture is warped from its latitude/longitude grid to web mercator rows so it lies true on the map (the bathymetry trap).
Colors run dim blue to white: more snow reads brighter on the dark map. Under 0.1 in (snowfall) or 0.5 in (depth) is clear.

Per resort: snowfall at the resort's own 4-km cell; depth two ways, at the base point and the deepest 1-km cell within ~2 km
(the upper mountain). Both are analyses, not the resort's own report.

    python3 snow_bake.py [--dry]
"""
import datetime as dt, gzip, io, json, math, os, subprocess, sys, tarfile, tempfile, time, urllib.request
import numpy as np
from PIL import Image

UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com snow bake)'}
BUCKET = 'bluishvoid-bg'; PREFIX = 'snow/v1/'
HERE = os.path.dirname(os.path.abspath(__file__))
SF = 'https://www.nohrsc.noaa.gov/snowfall/data/{ym}/sfav2_CONUS_{name}.tif'
SN = 'https://noaadata.apps.nsidc.org/NOAA/G02158/masked/{y}/{m:02d}_{mon}/SNODAS_{ymd}.tar'
SF_GEO = (-126.0, 55.0, 0.04)            # west, north, cell (deg) of the 1500 x 850 sfav2 grid
STOPS_SF = [[0.1, '#24406e', .50], [1, '#2f5d9e', .62], [2, '#3b78c9', .70], [4, '#4f93e6', .76], [6, '#6eaaf0', .80], [8, '#8fc0f5', .84],
            [12, '#b3d6fa', .88], [18, '#d2e8fd', .91], [24, '#e8f3ff', .93], [36, '#f6faff', .95], [48, '#ffffff', .97]]
STOPS_D = [[0.5, '#24406e', .45], [1, '#2f5d9e', .55], [3, '#3b78c9', .64], [6, '#4f93e6', .72], [12, '#6eaaf0', .78], [24, '#8fc0f5', .84],
           [36, '#b3d6fa', .88], [48, '#d2e8fd', .91], [72, '#e8f3ff', .94], [96, '#ffffff', .97]]

def get(url, timeout=120):
    for a in range(4):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(10 * (a + 1))
        except Exception: time.sleep(10 * (a + 1))
    return None

def tif(b):
    import tifffile
    a = tifffile.imread(io.BytesIO(b)).astype(np.float32)
    a[a < -1] = np.nan
    return a

def merc_y(la): return math.log(math.tan(math.pi / 4 + math.radians(la) / 2))

def warp(a, west, north, cell, out_w):
    """lat/lon grid -> web-mercator image rows, BILINEAR (2026-11-08: the nearest-cell picture drew hard 4-km squares; an analysis is an
    estimate, so it reads as a soft field), and the bounds [[s, w], [n, e]]"""
    h, w = a.shape; south = north - h * cell; east = west + w * cell
    y0, y1 = merc_y(north), merc_y(south); out_h = int(round(out_w * (y0 - y1) / math.radians(east - west)))
    ys = y0 + (y1 - y0) * (np.arange(out_h) + 0.5) / out_h
    lats = np.degrees(2 * np.arctan(np.exp(ys)) - math.pi / 2)
    fr = np.clip((north - lats) / cell - 0.5, 0, h - 1.001); fc = np.clip((np.arange(out_w) + 0.5) / out_w * w - 0.5, 0, w - 1.001)
    r0 = fr.astype(int); c0 = fc.astype(int); ry = (fr - r0)[:, None]; cx = (fc - c0)[None, :]
    nanm = np.isnan(a); b = np.where(nanm, 0, a)
    def lerp(g):
        return (g[r0][:, c0] * (1 - ry) * (1 - cx) + g[r0][:, c0 + 1] * (1 - ry) * cx + g[r0 + 1][:, c0] * ry * (1 - cx) + g[r0 + 1][:, c0 + 1] * ry * cx)
    v = lerp(b); m = lerp(nanm.astype(np.float32))
    v[m > 0.5] = np.nan
    return v, [[round(south, 4), round(west, 4)], [round(north, 4), round(east, 4)]]

def paint(a, stops):
    """a continuous ramp between the stops (color and alpha interpolated on a log scale), clear under the first stop"""
    v = np.nan_to_num(a, nan=-1); lo = np.array([s[0] for s in stops], float)
    C = np.array([[int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16), al * 255] for _, c, al in stops], float)
    x = np.interp(np.log(np.maximum(v, 1e-3)), np.log(lo), np.arange(len(lo)))
    i0 = np.clip(np.floor(x).astype(int), 0, len(lo) - 1); i1 = np.clip(i0 + 1, 0, len(lo) - 1); t = (x - i0)[..., None]
    rgba = (C[i0] * (1 - t) + C[i1] * t).astype(np.uint8)
    rgba[v < lo[0]] = 0
    return rgba

def png(rgba):
    b = io.BytesIO(); Image.fromarray(rgba).save(b, 'PNG', optimize=True); return b.getvalue()

def sample(a, west, north, cell, la, lo, r=0):
    h, w = a.shape; i = int((north - la) / cell); j = int((lo - west) / cell)
    if i < 0 or j < 0 or i >= h or j >= w: return None
    win = a[max(0, i - r):i + r + 1, max(0, j - r):j + r + 1]
    if np.all(np.isnan(win)): return None
    return float(np.nanmax(win))

def put(path, key, ctype, cache):
    if '--dry' in sys.argv: return
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', path, 's3://%s/%s' % (BUCKET, key), '--content-type', ctype, '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', path, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: ' + ctype, '--header-upload', 'Cache-Control: ' + cache], check=True)


def r2_get(key):
    """a file we published before, read from the bucket itself (the CDN copy can be a cached one)"""
    fd, tmpf = tempfile.mkstemp(); os.close(fd)
    try:
        if os.environ.get('R2_ACCOUNT_ID'):
            r = subprocess.run(['aws', 's3', 'cp', 's3://%s/%s' % (BUCKET, key), tmpf, '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'])
        else:
            r = subprocess.run(['rclone', 'copyto', 'r2:%s/%s' % (BUCKET, key), tmpf, '--s3-no-check-bucket'])
        if r.returncode != 0 or not os.path.getsize(tmpf): return None
        return open(tmpf, 'rb').read()
    except Exception: return None

def km(la1, lo1, la2, lo2):
    D = math.pi / 180
    return 6371 * 2 * math.asin(math.sqrt(math.sin((la2 - la1) * D / 2) ** 2 + math.cos(la1 * D) * math.cos(la2 * D) * math.sin((lo2 - lo1) * D / 2) ** 2))

AWDB = 'https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/'
def snotel(R, day):
    """the nearest USDA NRCS SNOTEL station to each West Coast resort (within 40 km, scored by distance plus how far its elevation sits
    outside the resort's base-summit span), and its snow water today against that date's 1991-2020 median"""
    west = [r for r in R if r.get('region') == 'west']
    if not west: return {}
    try: st = json.loads(get(AWDB + 'stations?stateCds=WA,OR,CA,NV&networkCds=SNTL&elements=WTEQ&activeOnly=true', 120))
    except Exception: return {}
    st = [x for x in st if x.get('networkCode') == 'SNTL' and x.get('latitude') is not None]
    pick = {}
    for r in west:
        lo_e = (r.get('base_ft') or 0) - 1000; hi_e = (r.get('summit_ft') or r.get('base_ft') or 9e9) + 500; best = None
        for x in st:
            d = km(r['lat'], r['lon'], x['latitude'], x['longitude'])
            if d > 40: continue
            e = x.get('elevation') or 0; off = max(0, lo_e - e, e - hi_e)
            sc = d + off / 300.0
            if best is None or sc < best[0]: best = (sc, d, x)
        if best: pick[r['id']] = best
    if not pick: return {}
    trip = sorted(set(b[2]['stationTriplet'] for b in pick.values()))
    b0 = (day - dt.timedelta(days=4)).isoformat(); b1 = day.isoformat(); vals = {}
    for i in range(0, len(trip), 40):
        try: j = json.loads(get(AWDB + 'data?stationTriplets=' + ','.join(trip[i:i + 40]) + '&elements=WTEQ,SNWD&duration=DAILY&beginDate=%s&endDate=%s&centralTendencyType=MEDIAN' % (b0, b1), 120))
        except Exception: continue
        for stn in j:
            for el in stn.get('data', []):
                code = el['stationElement']['elementCode']; vv = [v for v in el.get('values', []) if v.get('value') is not None]
                if vv: vals.setdefault(stn['stationTriplet'], {})[code] = vv[-1]
    out = {}
    for rid, (sc, d, x) in pick.items():
        v = vals.get(x['stationTriplet'], {}); w = v.get('WTEQ')
        if not w: continue
        o = {'n': x['name'], 'e': int(x.get('elevation') or 0), 'km': round(d, 1), 'swe': w.get('value'), 'on': w.get('date')}
        if w.get('median') is not None: o['med'] = w['median']
        if v.get('SNWD'): o['snwd'] = v['SNWD'].get('value')
        out[rid] = o
    return out

def main():
    now = dt.datetime.now(dt.timezone.utc)
    # the newest 12Z analysis that exists (today's lands ~16Z)
    day = None
    for back in range(0, 4):
        d = (now - dt.timedelta(days=back)).date()
        if get(SF.format(ym=d.strftime('%Y%m'), name='24h_%s12' % d.strftime('%Y%m%d')), 60) is not None: day = d; break
    if day is None: raise SystemExit('no recent snowfall analysis')
    ymd = lambda d: d.strftime('%Y%m%d')
    grids = {}
    grids['24h'] = tif(get(SF.format(ym=day.strftime('%Y%m'), name='24h_%s12' % ymd(day))))
    b72 = get(SF.format(ym=day.strftime('%Y%m'), name='72h_%s12' % ymd(day))); grids['72h'] = tif(b72) if b72 else None
    wk = [];
    for k in range(7):
        d = day - dt.timedelta(days=k); b = get(SF.format(ym=d.strftime('%Y%m'), name='24h_%s12' % ymd(d)))
        if b: wk.append(tif(b))
    grids['7d'] = np.nansum(np.stack(wk), axis=0) if len(wk) == 7 else None
    if grids['7d'] is not None: grids['7d'][np.all(np.isnan(np.stack(wk)), axis=0)] = np.nan
    sy = day.year if day.month >= 10 or (day.month == 9 and day.day == 30) else day.year - 1
    bs = get(SF.format(ym=day.strftime('%Y%m'), name='%d093012_to_%s12' % (sy, ymd(day)))); grids['season'] = tif(bs) if bs else None
    # snow on the ground: SNODAS (yesterday's model day is the newest NSIDC usually has by morning)
    depth = None; dday = None
    for back in range(0, 4):
        d = (now - dt.timedelta(days=back)).date()
        b = get(SN.format(y=d.year, m=d.month, mon=d.strftime('%b'), ymd=ymd(d)), 180)
        if not b: continue
        with tarfile.open(fileobj=io.BytesIO(b)) as t:
            mem = [m for m in t.getmembers() if '11036tS' in m.name and m.name.endswith('.dat.gz')]
            if not mem: continue
            raw = gzip.decompress(t.extractfile(mem[0]).read())
        a = np.frombuffer(raw, '>i2').reshape(3351, 6935).astype(np.float32); a[a < 0] = np.nan
        depth = a / 25.4; dday = d; break      # mm -> inches
    SN_GEO = (-124.733333333328, 52.8749999999979, 1 / 120.0)
    out = {'at': int(time.time()), 'day': day.isoformat(), 'depth_day': dday.isoformat() if dday else None, 'p': {},
           'stops': {'sf': STOPS_SF, 'd': STOPS_D},
           'src': {'sf': 'NOAA NOHRSC National Snowfall Analysis v2', 'd': 'NOAA SNODAS (NSIDC G02158)'}}
    tmp = tempfile.mkdtemp()
    for k, a in list(grids.items()) + [('depth', depth)]:
        if a is None: continue
        geo = SN_GEO if k == 'depth' else SF_GEO
        img, bounds = warp(a, geo[0], geo[1], geo[2], 2000 if k == 'depth' else 1500)
        p = os.path.join(tmp, k + '.png'); open(p, 'wb').write(png(paint(img, STOPS_D if k == 'depth' else STOPS_SF)))
        put(p, PREFIX + k + '.png', 'image/png', 'public, max-age=1800')
        out['p'][k] = {'b': bounds, 'max': round(float(np.nanmax(a)), 1), 'kb': os.path.getsize(p) // 1024}
        print(k, bounds, 'max', out['p'][k]['max'], out['p'][k]['kb'], 'KB', flush=True)
    # every resort
    rp = os.path.join(HERE, 'resorts_v1.json'); R = json.load(open(rp)) if os.path.exists(rp) else []
    rs = {}
    for r in R:
        la, lo = r.get('lat'), r.get('lon')
        if la is None or lo is None: continue
        v = {}
        for k in ('24h', '72h', '7d', 'season'):
            if grids.get(k) is not None:
                x = sample(grids[k], SF_GEO[0], SF_GEO[1], SF_GEO[2], la, lo)
                if x is not None: v[k] = round(x, 1)
        if depth is not None:
            x = sample(depth, SN_GEO[0], SN_GEO[1], SN_GEO[2], la, lo); y = sample(depth, SN_GEO[0], SN_GEO[1], SN_GEO[2], la, lo, 2)
            if x is not None: v['db'] = round(x, 1)
            if y is not None: v['du'] = round(y, 1)
        rs[r['id']] = v
    # THE SEASON, DAY BY DAY: each resort's 24-hour snowfall for every analysis day since Sept 30 (backfilled once from NOHRSC's archive)
    s0 = dt.date(sy, 10, 1); H = None
    hb = r2_get(PREFIX + 'history.json')
    if hb:
        try: H = json.loads(hb)
        except Exception: H = None
    ids = [r['id'] for r in R if r.get('lat') is not None]
    if not H or H.get('start') != s0.isoformat() or any(i not in H.get('r', {}) for i in ids): H = {'start': s0.isoformat(), 'days': [], 'r': {i: [] for i in ids}}
    have = set(H['days']); d = s0; added = 0
    while d <= day:
        k = d.isoformat()
        if k not in have:
            g = grids['24h'] if d == day else None
            if g is None:
                b2 = get(SF.format(ym=d.strftime('%Y%m'), name='24h_%s12' % ymd(d)), 60); g = tif(b2) if b2 else None
            H['days'].append(k)
            for r in R:
                if r['id'] not in H['r']: continue
                x = sample(g, SF_GEO[0], SF_GEO[1], SF_GEO[2], r['lat'], r['lon']) if g is not None else None
                H['r'][r['id']].append(None if x is None else round(x, 1))
            added += 1
        d += dt.timedelta(days=1)
    order = sorted(range(len(H['days'])), key=lambda i: H['days'][i])
    H['days'] = [H['days'][i] for i in order]; H['r'] = {k2: [v2[i] for i in order] for k2, v2 in H['r'].items()}
    hp = os.path.join(tmp, 'history.json'); json.dump(H, open(hp, 'w'), separators=(',', ':'))
    put(hp, PREFIX + 'history.json', 'application/json', 'public, max-age=900')
    print('history', len(H['days']), 'days,', added, 'added,', os.path.getsize(hp), 'bytes', flush=True)
    # THE SNOWPACK AGAINST NORMAL, West Coast: the nearest SNOTEL
    try:
        sn = snotel(R, day)
        for rid, o in sn.items(): rs.setdefault(rid, {})['sn'] = o
        print('snotel', len(sn), 'resorts matched', flush=True)
    except Exception as e: print('snotel failed', e, flush=True)
    out['r'] = rs
    # the page's copy of the resort list: only what the map and cards use (the sources stay in the repo's file)
    KEEP = ('id', 'name', 'region', 'state', 'lat', 'lon', 'summit_ft', 'base_ft', 'vertical_ft', 'trails', 'lifts', 'acres', 'website', 'tickets', 'lift_status',
            'passes', 'hours', 'hours_note', 'hours_src', 'season', 'night_skiing', 'status')
    if R:
        slim = [{k: r[k] for k in KEEP if r.get(k) not in (None, '', [])} for r in R]
        sp = os.path.join(tmp, 'resorts_v1.json'); json.dump(slim, open(sp, 'w'), separators=(',', ':'))
        put(sp, 'snow/resorts_v1.json', 'application/json', 'public, max-age=3600')
        print('resorts file', os.path.getsize(sp), 'bytes')
    jp = os.path.join(tmp, 'latest.json'); json.dump(out, open(jp, 'w'), separators=(',', ':'))
    put(jp, PREFIX + 'latest.json', 'application/json', 'public, max-age=900')
    print('resorts', len(rs), 'json', os.path.getsize(jp), 'bytes; day', out['day'], 'depth day', out['depth_day'])

if __name__ == '__main__':
    main()
