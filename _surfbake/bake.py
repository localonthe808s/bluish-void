#!/usr/bin/env python3
"""THE SARGASSO SEA, LIVE (2026-10-26, user: "we need to significantly improve our sargasso sea visual, what real sources can be
used"). Two daily layers for WATER's SARGASSO SEA and OCEAN COLOR switches, both from NOAA CoastWatch's ERDDAP (no CORS, so baked):

    surf/currents.png   the surface currents that wall the sea in -- NOAA/NESDIS blended near-real-time geostrophic currents from
                        satellite altimetry (noaacwBLENDEDNRTcurrentsDaily, 0.25 deg, daily). Plain lat/lon grid, north up:
                        R = east speed, G = north speed, (value - 128) / 127 * VMAX m/s; B = 255 where there is water data
    surf/chl.png        ocean color -- chlorophyll-a, gap-filled (DINEOF) from NOAA-20 / S-NPP VIIRS (noaacwNPPN20VIIRSDINEOFDaily,
                        9 km, daily, no cloud holes), in web-mercator rows over the box, colored on a log scale: the Sargasso's
                        clear "ocean desert" deep blue, through teal, to green where the water is full of plankton
    surf/latest.json    {"cur": {"t", "box", "vmax", "w", "h"}, "chl": {"t", "box"}, "v"}

    python3 _surfbake/bake.py [--dry]
"""
import json, math, os, subprocess, sys, tempfile, time, urllib.request
import numpy as np
from PIL import Image, ImageDraw
from scipy.io import netcdf_file

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '_sargbake'))
from bake import topo_rings          # Natural Earth 1:50m land, the sargassum bake's copy
LAND = os.path.join(HERE, '..', '_sargbake', 'land50m.json')

ERD = 'https://coastwatch.noaa.gov/erddap/griddap/'
BUCKET = 'bluishvoid-bg'
# the North Atlantic gyre with room round it: the Gulf Stream's whole run, the Azores and Canary currents, the equatorial return
CW, CS, CE, CN = -180.0, -70.0, 180.0, 70.0      # global since 2026-10-27 (WATER's OCEAN tab works from any coast)
VMAX = 2.0                                   # m/s; the Gulf Stream's core peaks near 2
# ocean color over the same water, a little tighter
KW, KS, KE, KN = -180.0, -70.0, 180.0, 75.0
KSTRIDE = 3                                   # 9 km -> ~28 km: the world in ~1,440 columns
# log10 chlorophyll (mg/m3) -> color. The open gyre runs 0.02-0.06; shelves and upwelling 1-10. No purple: deep blue to green
RAMP = [(-1.75, (17, 52, 160)), (-1.3, (29, 90, 216)), (-0.9, (14, 150, 220)), (-0.5, (20, 184, 166)), (0.0, (34, 170, 90)),
        (0.5, (132, 204, 22)), (1.0, (202, 206, 40))]


def get(url, path):
    for k in range(4):
        try:
            open(path, 'wb').write(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluishvoid.com sargasso bake'}), timeout=300).read())
            return path
        except Exception as e:
            print('retry', k, e); time.sleep(20 * (k + 1))
    raise SystemExit('CoastWatch ERDDAP did not answer: ' + url)


def land_mask(W0, S0, E0, N0, w, h, ss=4):
    """True where a grid cell is mostly land (rasterized at ss x and averaged)"""
    im = Image.new('L', (w * ss, h * ss), 0); d = ImageDraw.Draw(im)
    X = lambda lo: (lo - W0) / (E0 - W0) * w * ss; Y = lambda la: (N0 - la) / (N0 - S0) * h * ss
    for r in topo_rings(LAND):
        if max(q[0] for q in r) < W0 - 2 or min(q[0] for q in r) > E0 + 2 or max(q[1] for q in r) < S0 - 2 or min(q[1] for q in r) > N0 + 2: continue
        d.polygon([(X(q[0]), Y(q[1])) for q in r], fill=255)
    a = np.asarray(im, np.float32).reshape(h, ss, w, ss).mean(axis=(1, 3))
    return a > 96


def north_up(f, name):
    a = f.variables[name][0].astype(np.float32)
    while a.ndim > 2: a = a[0]
    lat = f.variables['latitude'][:]
    if lat[0] < lat[-1]: a = a[::-1]
    return a, float(f.variables['time'][0])


def currents(tmp):
    q = '[(last)][(%g):1:(%g)][(%g):1:(%g)]' % (CS, CN, CW, CE)
    p = get(ERD + 'noaacwBLENDEDNRTcurrentsDaily.nc?u_current' + q + ',v_current' + q, os.path.join(tmp, 'cur.nc'))
    f = netcdf_file(p, 'r', mmap=False)
    u, t = north_up(f, 'u_current'); v, _ = north_up(f, 'v_current')
    lat = CN - (np.arange(u.shape[0]) + .5) / u.shape[0] * (CN - CS)
    # the equator stays (2026-10-27): NOAA's blend treats it -- measured, the median speed within 1 deg of it (0.34 m/s) matches 5 deg
    # out, so the old +-5 deg cut only hid the equatorial currents. Lone spikes over 3 m/s (seen at every latitude, mostly coastal)
    # are dropped instead: no daily surface current runs that fast
    ok = np.isfinite(u) & np.isfinite(v) & (np.abs(u) < 50) & (np.abs(v) < 50) & (np.hypot(np.nan_to_num(u), np.nan_to_num(v)) <= 3.0)
    # the grid is filled over land too, and altimetry is unreliable within a cell of the coast (a Haitian bay read 2.8 m/s)
    from scipy.ndimage import binary_dilation
    ok &= ~binary_dilation(land_mask(CW - .125, CS - .125, CE + .125, CN + .125, u.shape[1], u.shape[0]), iterations=1)
    enc = lambda a: np.clip(np.round(np.nan_to_num(a) / VMAX * 127 + 128), 1, 255).astype(np.uint8)
    rgb = np.dstack([enc(u), enc(v), np.where(ok, 255, 0).astype(np.uint8)])
    out = os.path.join(tmp, 'currents.png'); Image.fromarray(rgb).save(out, optimize=True)
    sp = np.hypot(u, v)[ok]
    print('currents', time.strftime('%Y-%m-%d', time.gmtime(t)), rgb.shape, 'max %.2f m/s, p99 %.2f' % (sp.max(), np.percentile(sp, 99)), os.path.getsize(out), 'bytes')
    return out, {'t': time.strftime('%Y-%m-%d', time.gmtime(t)), 'box': [CW, CS, CE, CN], 'vmax': VMAX, 'w': rgb.shape[1], 'h': rgb.shape[0]}


# ---- THE MODEL'S CURRENTS (2026-10-28): NOAA RTOFS-Global, the day's mean surface current. Scored against the drifters
# (_surfbake/validate.py, 158 + 157 buoys, Oct 25 and 26): the RTOFS daily mean 57-63 % better than "no current", direction off
# 18-23 deg (median); the satellite currents above 45-46 %, 28-30 deg. A snapshot scores worse than the day's mean (35 %): the
# hour's inertial swirl is real, but a day's drift is what the buoys measure and what the streaks show. Morning bake (after the
# nowcast lands ~06:50 UTC): the LAST 24 HOURS to 00Z; afternoon (the forecast to +24 h lands ~12:50 UTC): TODAY, forecast.
RBOX = (-180.0, -80.0, 180.0, 85.0)          # to 85 N: the Arctic is in the model (the satellites stop at the ice); 90 breaks mercator
RVMAX = 2.5


def rtofs_pick():
    import urllib.request as U
    def have(day, tag):
        try:
            U.urlopen(U.Request('https://noaa-nws-rtofs-pds.s3.amazonaws.com/rtofs.%s/rtofs_glo.t00z.%s.archs.b' % (day, tag), method='HEAD'), timeout=30); return True
        except Exception: return False
    for back in range(3):
        day = time.strftime('%Y%m%d', time.gmtime(time.time() - back * 86400))
        if have(day, 'f24') and have(day, 'n00'): return day, ['n00', 'f06', 'f12', 'f18', 'f24'], 'today', day
        if have(day, 'n00'): return day, ['n-24', 'n-18', 'n-12', 'n-06', 'n00'], 'last24', time.strftime('%Y%m%d', time.gmtime(time.mktime(time.strptime(day, '%Y%m%d')) - 86400))
    raise RuntimeError('no RTOFS run in 3 days')


def currents_rtofs(tmp):
    sys.path.insert(0, HERE); import rtofs
    os.environ.setdefault('RTOFS_CACHE', os.path.join(tmp, 'rtofs'))
    day, tags, kind, valid = rtofs_pick()
    U = V = None; frames = []
    r0 = int((RBOX[1] + 90) / .25); r1 = int((RBOX[3] + 90) / .25)
    enc = lambda a: np.clip(np.round(np.nan_to_num(a) / RVMAX * 127 + 128), 1, 255).astype(np.uint8)
    for t in tags:
        lon, lat, u, v = rtofs.surface(day, t); a, b = rtofs.regrid(lon, lat, u, v)
        U = a if U is None else U + a; V = b if V is None else V + b; print('  rtofs', day, t)
        # THE DAY, HOUR BY HOUR (2026-10-28): each snapshot at half a degree, for the globe's PLAY (cdn surf/fc/<i>.png)
        h = int(t[1:]) if t[0] == 'f' else -int(t[2:]) if t.startswith('n-') else 0
        ua = a[r0:r1][::-1].reshape((r1 - r0) // 2, 2, 720, 2); va = b[r0:r1][::-1].reshape((r1 - r0) // 2, 2, 720, 2)
        with np.errstate(all='ignore'): us = np.nanmean(ua, axis=(1, 3)); vs = np.nanmean(va, axis=(1, 3))
        okf = np.isfinite(us) & np.isfinite(vs)
        fp = os.path.join(tmp, 'fc%d.png' % len(frames)); Image.fromarray(np.dstack([enc(us), enc(vs), np.where(okf, 255, 0).astype(np.uint8)])).save(fp, optimize=True)
        frames.append((fp, __import__('calendar').timegm(time.strptime(day, '%Y%m%d')) + h * 3600))
    U /= len(tags); V /= len(tags)                                         # rows south -> north
    global LAST_UV; LAST_UV = (U, V, kind, valid)
    H = U.shape[0]; r0 = int((RBOX[1] + 90) / .25); r1 = int((RBOX[3] + 90) / .25)
    u = U[r0:r1][::-1]; v = V[r0:r1][::-1]                                 # north up, the box
    sp = np.hypot(u, v); ok = np.isfinite(sp) & (sp <= 3.0)
    enc = lambda a: np.clip(np.round(np.nan_to_num(a) / RVMAX * 127 + 128), 1, 255).astype(np.uint8)
    rgb = np.dstack([enc(u), enc(v), np.where(ok, 255, 0).astype(np.uint8)])
    out = os.path.join(tmp, 'currents.png'); Image.fromarray(rgb).save(out, optimize=True)
    d = '%s-%s-%s' % (valid[:4], valid[4:6], valid[6:])
    print('currents RTOFS', day, kind, rgb.shape, 'max %.2f m/s, p99 %.2f' % (sp[ok].max(), np.percentile(sp[ok], 99)), os.path.getsize(out), 'bytes')
    global FRAMES; FRAMES = frames
    return out, {'t': d, 'box': list(RBOX), 'vmax': RVMAX, 'w': rgb.shape[1], 'h': rgb.shape[0], 'src': 'rtofs', 'kind': kind, 'run': day,
                 'frames': [int(f[1]) for f in frames], 'fw': 720, 'fh': (r1 - r0) // 2}


def chlorophyll(tmp):
    p = get(ERD + 'noaacwNPPN20VIIRSDINEOFDaily.nc?chlor_a[(last)][(0.0)][(%g):%d:(%g)][(%g):%d:(%g)]' % (KS, KSTRIDE, KN, KW, KSTRIDE, KE), os.path.join(tmp, 'chl.nc'))
    f = netcdf_file(p, 'r', mmap=False)
    a, t = north_up(f, 'chlor_a')
    H, W = a.shape
    ok = np.isfinite(a) & (a > 0) & (a < 500) & ~land_mask(KW, KS, KE, KN, W, H, 2)
    lg = np.log10(np.where(ok, a, 1.0))
    xs = [r[0] for r in RAMP]
    rgb = np.zeros((H, W, 3), np.float32)
    for c in range(3): rgb[..., c] = np.interp(lg, xs, [r[1][c] for r in RAMP])
    # the box's edges fade out over ~3 deg instead of ending in a straight cut across the ocean
    fy = np.clip(np.minimum(np.arange(H), H - 1 - np.arange(H)) / (3.0 / (KN - KS) * H), 0, 1)
    fx = np.ones(W) if KE - KW >= 359 else np.clip(np.minimum(np.arange(W), W - 1 - np.arange(W)) / (3.0 / (KE - KW) * W), 0, 1)
    fade = (np.minimum(fy[:, None], fx[None, :]) ** 1.5)
    rgba = np.dstack([rgb.round().astype(np.uint8), (np.where(ok, 255, 0) * fade).round().astype(np.uint8)])
    my = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    Hm = int(round(H * (my(KN) - my(KS)) / math.radians(KN - KS)))
    rows = [min(H - 1, max(0, int((KN - math.degrees(2 * math.atan(math.exp(my(KN) - (i + .5) / Hm * (my(KN) - my(KS)))) - math.pi / 2)) / (KN - KS) * H))) for i in range(Hm)]
    out = os.path.join(tmp, 'chl.png'); Image.fromarray(rgba[rows]).save(out, optimize=True)
    v = a[ok]
    print('chl', time.strftime('%Y-%m-%d', time.gmtime(t)), (H, W), 'median %.3f, p5 %.3f, p95 %.2f mg/m3' % (np.median(v), np.percentile(v, 5), np.percentile(v, 95)), os.path.getsize(out), 'bytes')
    return out, {'t': time.strftime('%Y-%m-%d', time.gmtime(t)), 'box': [KW, KS, KE, KN]}


# SEA TEMPERATURE (2026-10-27, WATER's SEA tab): the world from NOAA OISST v2.1 (0.25 deg, with its anomaly against 1991-2020), and
# North American waters sharp from JPL MUR (1 km, read at 0.05 deg, with its own anomaly). One F ramp for both; the site's colors
TF = [(28, (30, 58, 138)), (39, (37, 99, 235)), (50, (14, 165, 233)), (61, (34, 211, 238)), (68, (34, 197, 94)), (75, (250, 204, 21)),
      (82, (239, 68, 68)), (88, (153, 27, 27))]
AF = [(-7, (29, 78, 216)), (-3.5, (96, 165, 250)), (-1, (226, 232, 240)), (0, (241, 245, 249)), (1, (254, 226, 226)), (3.5, (251, 146, 60)),
      (7, (220, 38, 38)), (10, (127, 29, 29))]
RW, RS, RE, RN = -130.0, 15.0, -50.0, 55.0     # the sharp box


def ramp(v, stops, alpha=235):
    xs = [q[0] for q in stops]; ok = np.isfinite(v)
    rgb = np.zeros(v.shape + (3,), np.float32)
    for c in range(3): rgb[..., c] = np.interp(np.nan_to_num(v), xs, [q[1][c] for q in stops])
    return np.dstack([rgb.round().astype(np.uint8), np.where(ok, alpha, 0).astype(np.uint8)])


def merc(rgba, S0, N0, name, tmp):
    H = rgba.shape[0]; my = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    Hm = int(round(H * (my(N0) - my(S0)) / math.radians(N0 - S0)))
    rows = [min(H - 1, max(0, int((N0 - math.degrees(2 * math.atan(math.exp(my(N0) - (i + .5) / Hm * (my(N0) - my(S0)))) - math.pi / 2)) / (N0 - S0) * H))) for i in range(Hm)]
    out = os.path.join(tmp, name); Image.fromarray(rgba[rows]).save(out, optimize=True); return out


_PFEG = None
def pfeg_up():
    """one quick look at the West Coast ERDDAP: when it is down, its four slow retries per file cost ~10 minutes a run"""
    global _PFEG
    if _PFEG is None:
        try: urllib.request.urlopen('https://coastwatch.pfeg.noaa.gov/erddap/index.html', timeout=20); _PFEG = True
        except Exception as e: print('pfeg ERDDAP down:', e); _PFEG = False
    return _PFEG


def oisst_ncei(tmp):
    """THE SAME OISST, FROM NCEI (2026-10-28: the West Coast ERDDAP was down for a day and the sea went stale): the day's own
    netCDF4 file (~1.5 MB), newest of the last five days. Returns sst, anom north-up over -75..75, lon 0..360, and the time"""
    import h5py, calendar
    for back in range(1, 6):
        d = time.strftime('%Y%m%d', time.gmtime(time.time() - back * 86400))
        for kind in ('_preliminary', ''):
            url = 'https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr/%s/oisst-avhrr-v02r01.%s%s.nc' % (d[:6], d, kind)
            pth = os.path.join(tmp, 'ncei.nc')
            try:
                urllib.request.urlretrieve(url, pth)
            except Exception:
                continue
            h = h5py.File(pth, 'r'); lat = h['lat'][:]
            def g(n):
                v = h[n]; a = v[0, 0].astype(np.float32); fv = v.attrs.get('_FillValue'); sc = v.attrs.get('scale_factor'); of = v.attrs.get('add_offset')
                if fv is not None: a[v[0, 0] == fv[0]] = np.nan
                if sc is not None: a = a * float(sc[0])
                if of is not None: a = a + float(of[0])
                return a
            sst, an = g('sst'), g('anom'); keep = (lat >= -75) & (lat <= 75)
            sst, an = sst[keep], an[keep]
            if lat[0] < lat[-1]: sst, an = sst[::-1], an[::-1]
            print('oisst from NCEI', d, kind or 'final')
            return sst, an, calendar.timegm(time.strptime(d, '%Y%m%d')) + 43200
    raise RuntimeError('no OISST day at NCEI either')


def seatemp(tmp, old=None):
    f2c = lambda c: c * 9 / 5 + 32
    q = '[(last)][(0.0)][(-75):1:(75)][(0):1:(359.875)]'
    try:
        if not pfeg_up(): raise RuntimeError('pfeg down')
        p = get('https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21NrtAgg.nc?sst' + q + ',anom' + q, os.path.join(tmp, 'oisst.nc'))
        f = netcdf_file(p, 'r', mmap=False)
        sst, t = north_up(f, 'sst'); an, _ = north_up(f, 'anom')
    except BaseException as e:
        print('OISST via ERDDAP failed, NCEI instead:', e); sst, an, t = oisst_ncei(tmp)
    sst = np.roll(sst, sst.shape[1] // 2, axis=1); an = np.roll(an, an.shape[1] // 2, axis=1)   # 0..360 -> -180..180
    sst[(sst < -5) | (sst > 45)] = np.nan; an[~np.isfinite(sst)] = np.nan
    F, A = f2c(sst), an * 9 / 5
    # the world picture leaves North America's sharp box empty: its quarter-degree coasts and lakes showed round the sharp ones
    la = 75 - (np.arange(F.shape[0]) + .5) * 150 / F.shape[0]; lo = -180 + (np.arange(F.shape[1]) + .5) * 360 / F.shape[1]
    hole = ((la > RS + .3) & (la < RN - .3))[:, None] & ((lo > RW + .3) & (lo < RE - .3))[None, :]
    gs, ga = ramp(F, TF), ramp(A, AF); gs[hole, 3] = 0; ga[hole, 3] = 0
    out = {'g_sst': merc(gs, -75, 75, 'sst_g.png', tmp), 'g_anom': merc(ga, -75, 75, 'anom_g.png', tmp)}
    # the numbers, for a tap: R,G = F x 100 + 1000 (16 bit), B = anomaly F x 20 + 128; 0,0 = no water
    ok = np.isfinite(F); v = np.where(ok, np.clip(np.round(F * 100 + 1000), 1, 65535), 0).astype(np.uint32)
    b = np.where(ok, np.clip(np.round(np.nan_to_num(A) * 20 + 128), 0, 255), 0).astype(np.uint8)
    dp = os.path.join(tmp, 'sst_data.png'); Image.fromarray(np.dstack([(v >> 8).astype(np.uint8), (v & 255).astype(np.uint8), b])).save(dp, optimize=True); out['data'] = dp
    tg = time.strftime('%Y-%m-%d', time.gmtime(t))
    print('oisst', tg, F.shape, 'F %.0f..%.0f' % (np.nanmin(F), np.nanmax(F)), 'anom p1/p99 %.1f/%.1f F' % tuple(np.nanpercentile(A, [1, 99])))
    # North America, sharp -- kept from the last run when its server is down
    try: return seatemp_na(tmp, out, tg, sst, f2c)
    except BaseException as e:
        print('MUR (North America) kept from the last run:', e); o = (old or {}).get('sst') or {}
        return out, {'t': tg, 'tr': o.get('tr', ''), 'ta': o.get('ta', ''), 'g': [-180, -75, 180, 75], 'r': [RW, RS, RE, RN], 'dw': sst.shape[1], 'dh': sst.shape[0], 'rkept': True}


def seatemp_na(tmp, out, tg, sst, f2c):
    if not pfeg_up(): raise RuntimeError('pfeg down')
    q2 = '[(last)][(%g):5:(%g)][(%g):5:(%g)]' % (RS, RN, RW, RE)
    p2 = get('https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.nc?analysed_sst' + q2, os.path.join(tmp, 'mur.nc'))
    p3 = get('https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41anom1day.nc?sstAnom' + q2, os.path.join(tmp, 'muranom.nc'))
    f2 = netcdf_file(p2, 'r', mmap=False); m, tm = north_up(f2, 'analysed_sst')
    if np.nanmedian(m) > 200: m = m - 273.15            # Kelvin in some versions
    m[(m < -5) | (m > 45)] = np.nan
    f3 = netcdf_file(p3, 'r', mmap=False); ma, ta = north_up(f3, 'sstAnom'); ma[(ma < -20) | (ma > 20)] = np.nan
    out['r_sst'] = merc(ramp(f2c(m), TF), RS, RN, 'sst_r.png', tmp); out['r_anom'] = merc(ramp(ma * 9 / 5, AF), RS, RN, 'anom_r.png', tmp)
    print('mur', time.strftime('%Y-%m-%d', time.gmtime(tm)), m.shape, 'anom', time.strftime('%Y-%m-%d', time.gmtime(ta)))
    return out, {'t': tg, 'tr': time.strftime('%Y-%m-%d', time.gmtime(tm)), 'ta': time.strftime('%Y-%m-%d', time.gmtime(ta)),
                 'g': [-180, -75, 180, 75], 'r': [RW, RS, RE, RN], 'dw': sst.shape[1], 'dh': sst.shape[0]}


def put(src, key, ct, cache):
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', src, 's3://%s/%s' % (BUCKET, key), '--content-type', ct, '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', src, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: ' + ct, '--header-upload', 'Cache-Control: ' + cache], check=True)


LAST_UV = None
FRAMES = []


def score_day(tmp, old_score):
    """THE ACCURACY, KEPT HONEST (2026-10-28): each morning the model's last 24 hours are scored against what the drifting buoys did that
    day (_surfbake/validate.py), and the satellite currents beside it; 60 days kept in surf/score.json, the caption quotes the last 30"""
    sys.path.insert(0, HERE); import validate as VA
    U, V, kind, valid = LAST_UV
    if kind != 'last24': return None
    day = '%s-%s-%s' % (valid[:4], valid[4:6], valid[6:])
    nxt = time.strftime('%Y-%m-%d', time.gmtime(__import__('calendar').timegm(time.strptime(day, '%Y-%m-%d')) + 86400))
    dp = os.path.join(tmp, 'drift.csv')
    t0 = time.strftime('%Y-%m-%dT21:00:00Z', time.gmtime(__import__('calendar').timegm(time.strptime(day, '%Y-%m-%d')) - 86400))
    urllib.request.urlretrieve('https://osmc.noaa.gov/erddap/tabledap/OSMC_30day.csv?platform_code,time,latitude,longitude&platform_type=%22DRIFTING%20BUOYS%20(GENERIC)%22'
                               '&time%3E=' + t0 + '&time%3C=' + nxt + 'T03:00:00Z', dp)
    D = VA.drifters(dp, day)
    def one(F):
        A = VA.score(D, F)
        if len(A) < 30: return None
        la, u, v, fu, fv = A.T; e = np.hypot(fu - u, fv - v); z = np.hypot(u, v); good = z > .15
        ang = np.degrees(np.angle((fu + 1j * fv) / np.where((u + 1j * v) == 0, 1e-9, u + 1j * v)))
        return {'n': int(len(A)), 'skill': round(float(100 * (1 - np.mean(e ** 2) / np.mean(z ** 2))), 1), 'dir': round(float(np.median(np.abs(ang[good]))), 1),
                'rms': round(float(np.sqrt(np.mean(e ** 2))), 3), 'speed': round(float(np.median(np.hypot(fu, fv)[good]) / np.median(z[good])), 2)}
    row = {'d': day, 'rtofs': one((U, V))}
    try:                                                                   # the satellite currents, same day, for comparison
        q = '[(%sT12:00:00Z)][(-89.875):(89.875)][(-179.875):(179.875)]' % day
        pth = get(ERD + 'noaacwBLENDEDNRTcurrentsDaily.nc?u_current' + q + ',v_current' + q, os.path.join(tmp, 'cw_score.nc'))
        f = netcdf_file(pth, 'r', mmap=False); la = f.variables['latitude'][:]
        def g(n):
            v = f.variables[n]; a = v[:][0].astype(np.float32); fv = getattr(v, '_FillValue', None)
            if fv is not None: a[a == fv] = np.nan
            a[np.abs(a) > 10] = np.nan; return a[::-1] if la[0] > la[-1] else a
        row['sat'] = one((g('u_current'), g('v_current')))
    except BaseException as e: print('satellite score skipped:', e)
    days = [r for r in (old_score or {}).get('days', []) if r.get('d') != day] + [row]
    days = sorted(days, key=lambda r: r['d'])[-60:]
    last = [r['rtofs'] for r in days[-30:] if r.get('rtofs')]
    roll = {'days': len(last), 'buoys': sum(x['n'] for x in last), 'skill': round(float(np.median([x['skill'] for x in last])), 0), 'dir': round(float(np.median([x['dir'] for x in last])), 0)} if last else None
    print('score', row, 'rolling', roll)
    return {'days': days, 'roll': roll}


def old_meta():
    """the last published latest.json: a layer whose source is down this run keeps its last picture"""
    try: return json.loads(subprocess.run(['curl', '-s', '-m', '30', 'https://cdn.bluishvoid.com/surf/latest.json?x=%d' % time.time()], capture_output=True, text=True).stdout)
    except Exception: return {}


def main():
    tmp = tempfile.mkdtemp(); old = old_meta(); ups = []
    try: cp, cm = currents_rtofs(tmp)
    except Exception as e:                                                 # the satellite currents stay the fallback
        print('RTOFS failed, satellite currents instead:', e); cp, cm = currents(tmp); cm['src'] = 'altimetry'
    ups.append((cp, 'surf/currents.png'))
    if cm.get('src') == 'rtofs':
        for i, (fp, _) in enumerate(FRAMES): ups.append((fp, 'surf/fc/%d.png' % i))
    sc = None
    try:
        osc = json.loads(subprocess.run(['curl', '-s', '-m', '30', 'https://cdn.bluishvoid.com/surf/score.json?x=%d' % time.time()], capture_output=True, text=True).stdout or '{}')
    except Exception: osc = {}
    if LAST_UV:
        try: sc = score_day(tmp, osc)
        except BaseException as e: print('score skipped:', e)
    if sc:
        scp = os.path.join(tmp, 'score.json'); json.dump(sc, open(scp, 'w')); cm['score'] = sc['roll']
    elif osc.get('roll'): cm['score'] = osc['roll']
    # one slow server no longer sinks the run (2026-10-28: the OISST host timed out and nothing was published)
    try: kp, km = chlorophyll(tmp); ups.append((kp, 'surf/chl.png'))
    except BaseException as e: print('chlorophyll kept from the last run:', e); km = old.get('chl')
    try:
        sp, sm = seatemp(tmp, old)
        for k, key in (('g_sst', 'sst_g'), ('g_anom', 'anom_g'), ('r_sst', 'sst_r'), ('r_anom', 'anom_r'), ('data', 'sst_data')):
            if k in sp: ups.append((sp[k], 'surf/%s.png' % key))
    except BaseException as e: print('sea temperature kept from the last run:', e); sm = old.get('sst')
    v = int(time.time())
    meta = {'cur': cm, 'chl': km, 'sst': sm, 'at': v, 'v': v}
    mp = os.path.join(tmp, 'latest.json'); json.dump(meta, open(mp, 'w'))
    print(meta)
    if '--dry' in sys.argv: print('dry run:', tmp); return
    for src, key in ups: put(src, key, 'image/png', 'public, max-age=3600')
    if sc: put(scp, 'surf/score.json', 'application/json', 'public, max-age=3600')
    put(mp, 'surf/latest.json', 'application/json', 'public, max-age=1800')
    print('uploaded')


if __name__ == '__main__':
    main()
