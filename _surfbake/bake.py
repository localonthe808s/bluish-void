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
CW, CS, CE, CN = -100.0, 0.0, -5.0, 56.0
VMAX = 2.0                                   # m/s; the Gulf Stream's core peaks near 2
# ocean color over the same water, a little tighter
KW, KS, KE, KN = -98.0, 2.0, -8.0, 54.0
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
    # geostrophy fails near the equator (the Coriolis term goes to zero): the altimetry speeds there are not currents
    ok = np.isfinite(u) & np.isfinite(v) & (np.abs(u) < 50) & (np.abs(v) < 50) & (np.abs(lat) >= 5)[:, None]
    # the grid is filled over land too, and altimetry is unreliable within a cell of the coast (a Haitian bay read 2.8 m/s)
    from scipy.ndimage import binary_dilation
    ok &= ~binary_dilation(land_mask(CW - .125, CS - .125, CE + .125, CN + .125, u.shape[1], u.shape[0]), iterations=1)
    enc = lambda a: np.clip(np.round(np.nan_to_num(a) / VMAX * 127 + 128), 1, 255).astype(np.uint8)
    rgb = np.dstack([enc(u), enc(v), np.where(ok, 255, 0).astype(np.uint8)])
    out = os.path.join(tmp, 'currents.png'); Image.fromarray(rgb).save(out, optimize=True)
    sp = np.hypot(u, v)[ok]
    print('currents', time.strftime('%Y-%m-%d', time.gmtime(t)), rgb.shape, 'max %.2f m/s, p99 %.2f' % (sp.max(), np.percentile(sp, 99)), os.path.getsize(out), 'bytes')
    return out, {'t': time.strftime('%Y-%m-%d', time.gmtime(t)), 'box': [CW, CS, CE, CN], 'vmax': VMAX, 'w': rgb.shape[1], 'h': rgb.shape[0]}


def chlorophyll(tmp):
    p = get(ERD + 'noaacwNPPN20VIIRSDINEOFDaily.nc?chlor_a[(last)][(0.0)][(%g):1:(%g)][(%g):1:(%g)]' % (KS, KN, KW, KE), os.path.join(tmp, 'chl.nc'))
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
    fx = np.clip(np.minimum(np.arange(W), W - 1 - np.arange(W)) / (3.0 / (KE - KW) * W), 0, 1)
    fade = (np.minimum(fy[:, None], fx[None, :]) ** 1.5)
    rgba = np.dstack([rgb.round().astype(np.uint8), (np.where(ok, 255, 0) * fade).round().astype(np.uint8)])
    my = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    Hm = int(round(H * (my(KN) - my(KS)) / math.radians(KN - KS)))
    rows = [min(H - 1, max(0, int((KN - math.degrees(2 * math.atan(math.exp(my(KN) - (i + .5) / Hm * (my(KN) - my(KS)))) - math.pi / 2)) / (KN - KS) * H))) for i in range(Hm)]
    out = os.path.join(tmp, 'chl.png'); Image.fromarray(rgba[rows]).save(out, optimize=True)
    v = a[ok]
    print('chl', time.strftime('%Y-%m-%d', time.gmtime(t)), (H, W), 'median %.3f, p5 %.3f, p95 %.2f mg/m3' % (np.median(v), np.percentile(v, 5), np.percentile(v, 95)), os.path.getsize(out), 'bytes')
    return out, {'t': time.strftime('%Y-%m-%d', time.gmtime(t)), 'box': [KW, KS, KE, KN]}


def put(src, key, ct, cache):
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', src, 's3://%s/%s' % (BUCKET, key), '--content-type', ct, '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', src, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: ' + ct, '--header-upload', 'Cache-Control: ' + cache], check=True)


def main():
    tmp = tempfile.mkdtemp()
    cp, cm = currents(tmp)
    kp, km = chlorophyll(tmp)
    v = int(time.time())
    meta = {'cur': cm, 'chl': km, 'at': v, 'v': v}
    mp = os.path.join(tmp, 'latest.json'); json.dump(meta, open(mp, 'w'))
    print(meta)
    if '--dry' in sys.argv: print('dry run:', tmp); return
    put(cp, 'surf/currents.png', 'image/png', 'public, max-age=3600')
    put(kp, 'surf/chl.png', 'image/png', 'public, max-age=3600')
    put(mp, 'surf/latest.json', 'application/json', 'public, max-age=1800')
    print('uploaded')


if __name__ == '__main__':
    main()
