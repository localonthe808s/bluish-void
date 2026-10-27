#!/usr/bin/env python3
"""SARGASSUM BY THE MONTH (2026-10-27, user: "fix 1 2 3" -- 3: "a monthly sargassum view: the Great Atlantic Sargassum Belt growing
each spring and fading each fall"). NOAA AOML serves USF's 7-day AFAI composites back to June 2016 but no monthly product, so this
makes one: for every month, the 7-day composite nearest its 15th, read with the daily bake's own rules (AFAI > 0.0005, coasts masked
25 km, lone pixels dropped).

    sargassum/monthly.json      {"months": [{"m": "2026-09", "t": composite date, "km2": mat area flagged, "seen": share of open
                                 water the satellites saw, "by": {region: km2}}, ... since 2016-07], "maps": ["2024-11", ...]}
    sargassum/m/YYYY-MM.png     the last 24 months as density maps: share of each ~0.25 deg cell flagged, amber -> deep orange,
                                web-mercator rows over the box (as latest.png)

The history reads every 8th pixel (~12 km) and the maps every 4th (~6 km): a sample of the windrows, not all of them. Their area is
the sampled share times the water, so the months compare fairly with each other; it is not the daily bake's full-resolution count.
Months already on R2 are not read again.  python3 _sargbake/monthly.py [--dry] [--maps N]
"""
import io, json, math, os, subprocess, sys, tempfile, time, urllib.request
import numpy as np
from PIL import Image, ImageDraw
from scipy.io import netcdf_file
from scipy.ndimage import binary_dilation, uniform_filter, zoom as nzoom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bake import topo_rings, W0, S0, E0, N0, TH, COAST_KM, BUCKET, REG

DS = 'https://cwcgom.aoml.noaa.gov/erddap/griddap/noaa_aoml_atlantic_oceanwatch_AFAI_7D'
CDN = 'https://cdn.bluishvoid.com/sargassum/'
NMAPS = int(sys.argv[sys.argv.index('--maps') + 1]) if '--maps' in sys.argv else 24


def get(url, timeout=300):
    for k in range(4):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluishvoid.com sargassum monthly'}), timeout=timeout).read()
        except Exception as e: print('  retry', k, str(e)[:80]); time.sleep(20 * (k + 1))
    raise SystemExit('AOML ERDDAP did not answer')


_MASK = {}


def coast_mask(H, Wd):
    if (H, Wd) in _MASK: return _MASK[(H, Wd)]
    land = Image.new('L', (Wd, H), 0); d = ImageDraw.Draw(land)
    X = lambda lo: (lo - W0) / (E0 - W0) * Wd; Y = lambda la: (N0 - la) / (N0 - S0) * H
    for r in topo_rings(os.path.join(HERE, 'land50m.json')):
        if max(q[0] for q in r) < W0 - 2 or min(q[0] for q in r) > E0 + 2 or max(q[1] for q in r) < S0 - 2 or min(q[1] for q in r) > N0 + 2: continue
        d.polygon([(X(q[0]), Y(q[1])) for q in r], fill=255)
    px_km = (E0 - W0) / Wd * 111.32; rad = COAST_KM / px_km; k = int(math.ceil(rad))
    yy, xx = np.ogrid[-k:k + 1, -k:k + 1]
    m = binary_dilation(np.asarray(land) > 0, structure=(xx * xx + yy * yy) <= rad * rad)
    _MASK[(H, Wd)] = (m, px_km); return _MASK[(H, Wd)]


def read(t, stride):
    u = DS + '.nc?AFAI%%5B(%s)%%5D%%5B(%g):%d:(%g)%%5D%%5B(%g):%d:(%g)%%5D' % (t, S0, stride, N0, W0, stride, E0)
    p = os.path.join(tempfile.gettempdir(), 'afai_m.nc'); open(p, 'wb').write(get(u))
    f = netcdf_file(p, 'r', mmap=False); a = f.variables['AFAI'][0].astype(np.float32)[::-1]
    return a


def detect(a):
    H, Wd = a.shape; coast, px_km = coast_mask(H, Wd)
    ok = np.isfinite(a) & ~coast
    hit = ok & (a > TH)
    hit &= uniform_filter(hit.astype(np.float32), size=3) * 9 >= 1.5     # no flagged neighbour: speckle
    seen = float(ok.sum()) / float((~coast).sum())
    lat = N0 - (np.arange(H) + .5) / H * (N0 - S0); cell = (px_km ** 2) * np.cos(np.radians(lat))[:, None]
    by = {}
    for nm, (w, s, e, n) in REG.items():
        r0, r1 = int((N0 - n) / (N0 - S0) * H), int((N0 - s) / (N0 - S0) * H); c0, c1 = int((w - W0) / (E0 - W0) * Wd), int((e - W0) / (E0 - W0) * Wd)
        by[nm] = round(float((hit[r0:r1, c0:c1] * cell[r0:r1]).sum()))
    return hit, ok, round(float((hit * cell).sum())), round(seen, 3), by


def density_png(hit, ok, out):
    """share of each ~0.25 deg cell flagged (of the water seen) -> amber .. deep orange, transparent where none"""
    H, Wd = hit.shape; f = max(1, int(round(0.25 / ((E0 - W0) / Wd))))
    h2, w2 = H // f, Wd // f
    hs = hit[:h2 * f, :w2 * f].reshape(h2, f, w2, f).sum(axis=(1, 3)); os_ = ok[:h2 * f, :w2 * f].reshape(h2, f, w2, f).sum(axis=(1, 3))
    dens = np.where(os_ > 0, hs / np.maximum(os_, 1), 0.0)
    k = np.clip(np.sqrt(dens / 0.08), 0, 1)                            # 8% of a cell's water flagged is a dense belt
    rgba = np.zeros((h2, w2, 4), np.uint8)
    rgba[..., 0] = 255; rgba[..., 1] = (210 - 130 * k).astype(np.uint8); rgba[..., 2] = (60 - 50 * k).astype(np.uint8)
    rgba[..., 3] = np.where(dens > 0, 70 + 185 * k, 0).astype(np.uint8)
    my = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    Hm = int(round(h2 * (my(N0) - my(S0)) / math.radians(N0 - S0)))
    rows = [min(h2 - 1, max(0, int((N0 - math.degrees(2 * math.atan(math.exp(my(N0) - (i + .5) / Hm * (my(N0) - my(S0)))) - math.pi / 2)) / (N0 - S0) * h2))) for i in range(Hm)]
    Image.fromarray(rgba[rows]).resize((w2 * 2, Hm * 2), Image.BILINEAR).save(out, optimize=True)


def put(src, key, ct, cache):
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', src, 's3://%s/%s' % (BUCKET, key), '--content-type', ct, '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', src, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: ' + ct, '--header-upload', 'Cache-Control: ' + cache], check=True)


def main():
    dry = '--dry' in sys.argv; tmp = tempfile.mkdtemp()
    times = [r[0] for r in json.loads(get(DS + '.json?time%5B0:1:last%5D', 120))['table']['rows']]
    ts = {t: time.mktime(time.strptime(t[:10], '%Y-%m-%d')) for t in times}
    old = {}
    if not dry:                                                         # the first run has none: a 404 is not a failure
        try: old = json.loads(urllib.request.urlopen(urllib.request.Request(CDN + 'monthly.json?x=%d' % time.time(), headers={'User-Agent': 'bluishvoid.com'}), timeout=60).read())
        except Exception: old = {}
    have = {m['m']: m for m in old.get('months', [])}; maps_have = set(old.get('maps', []))
    now = time.gmtime(); months = []
    y, mo = 2016, 7
    while (y, mo) <= (now.tm_year, now.tm_mon):
        months.append('%04d-%02d' % (y, mo)); mo += 1
        if mo > 12: y, mo = y + 1, 1
    want_maps = months[-NMAPS:]
    out = []
    for m in months:
        target = time.mktime(time.strptime(m + '-15', '%Y-%m-%d'))
        if m == months[-1]: target = min(target, time.time())
        t = min(times, key=lambda q: abs(ts[q] - target))
        if abs(ts[t] - target) > 12 * 86400: print(m, 'no composite near the 15th'); continue
        cur = m == months[-1]                                           # the running month is read again (its composite moves)
        rec = have.get(m) if not cur else None
        need_map = m in want_maps and (m not in maps_have or cur)
        if rec and not need_map: out.append(rec); continue
        if not rec:
            hit, ok, km2, seen, by = detect(read(t, 8)); rec = {'m': m, 't': t[:10], 'km2': km2, 'seen': seen, 'by': by}
            print(m, t[:10], km2, 'km2 seen', seen, flush=True)
        if need_map:
            hit4, ok4, _, _, _ = detect(read(t, 4)); p = os.path.join(tmp, m + '.png'); density_png(hit4, ok4, p)
            print('  map', m, os.path.getsize(p), 'bytes', flush=True)
            if not dry: put(p, 'sargassum/m/%s.png' % m, 'image/png', 'public, max-age=86400')
            maps_have.add(m)
        out.append(rec)
    meta = {'months': out, 'maps': [m for m in want_maps if m in maps_have], 'box': [W0, S0, E0, N0], 'at': int(time.time())}
    jp = os.path.join(tmp, 'monthly.json'); json.dump(meta, open(jp, 'w'), separators=(',', ':'))
    print(len(out), 'months,', len(meta['maps']), 'maps', os.path.getsize(jp), 'bytes')
    if not dry: put(jp, 'sargassum/monthly.json', 'application/json', 'public, max-age=3600')


if __name__ == '__main__':
    main()
