#!/usr/bin/env python3
"""MEASURED COASTAL CURRENTS (user 2026-10-28: "yes do all" -> HF radar for SEA and COAST). The US high-frequency radar network
(IOOS HFRNet) measures the top ~1 m of the sea every hour from shore stations out to ~150-200 km: a measurement, not a model,
6 km cells. NOAA NDBC serves each region's hourly totals as an OPeNDAP aggregation (hfradar_<region>_6km); the HFRNet servers
and CoastWatch's West Coast ERDDAP copies were down when this was built, NDBC was not.

Each run: the last 3 hours per region, averaged cell by cell where measured (an hour often has holes as stations drop out; the
3-hour mean also takes the edge off the tide's swing without hiding it), cells with poor station geometry (HDOP > 1.25, the
IOOS rule) dropped. One PNG per region: R = east, G = north, (value - 128) / 127 * VMAX m/s, B = 255 where measured; plus
hfr/latest.json with each region's box and hours. Hourly (hfr.yml).

    python3 _hfrbake/bake.py [--dry]
"""
import json, os, re, subprocess, sys, tempfile, time, urllib.request
import numpy as np
from PIL import Image

DAP = 'https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_%s_6km'
REGIONS = ['usegc', 'uswc', 'gak', 'ushi', 'prvi', 'glna']   # East + Gulf, West, Gulf of Alaska, Hawaii, Puerto Rico + USVI, Great Lakes
HOURS = 3
LOOP = 12                                                    # the last 12 hours, one frame each, for COAST's PLAY (the tide turning)
VMAX = 2.0
HDOP = 1.25
BUCKET = 'bluishvoid-bg'


def fetch(url, tries=3):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluish-void hfr bake'}), timeout=240).read().decode()
        except Exception as e:
            err = e; time.sleep(5)
    raise RuntimeError('%s: %s' % (url, err))


def arrays(txt):
    """the DAP ascii body -> {name: flat float array} (name 'u.u', 'lat', ...)"""
    out = {}; name = None; vals = []
    body = txt.split('---------------------------------------------', 1)[-1]
    for line in body.splitlines():
        if not line.strip(): continue
        m = re.match(r'^([A-Za-z_][\w.]*)\[', line)
        if m and ',' not in line.split(']')[-1][:2] and not line.startswith('['):
            if name: out[name] = np.array(vals, dtype=np.float64)
            name = m.group(1); vals = []; continue
        if line.startswith('['): line = line.split(',', 1)[1] if ',' in line else ''
        vals.extend(float(x) for x in line.split(',') if x.strip())
    if name: out[name] = np.array(vals, dtype=np.float64)
    return out


def region(k):
    base = DAP % k
    dds = fetch(base + '.dds')
    nt = int(re.search(r'Int32 time\[time = (\d+)\]', dds).group(1)); ny = int(re.search(r'lat\[lat = (\d+)\]', dds).group(1)); nx = int(re.search(r'lon\[lon = (\d+)\]', dds).group(1))
    i0, i1 = nt - LOOP, nt - 1
    sl = '%%5B%d:1:%d%%5D%%5B0:1:%d%%5D%%5B0:1:%d%%5D' % (i0, i1, ny - 1, nx - 1)
    a = arrays(fetch(base + '.ascii?u' + sl + ',v' + sl + ',hdop' + sl + ',lat,lon,time%%5B%d:1:%d%%5D' % (i0, i1)))
    u = a['u.u'].reshape(LOOP, ny, nx); v = a['v.v'].reshape(LOOP, ny, nx); h = a['hdop.hdop'].reshape(LOOP, ny, nx)
    lat, lon, t = a['lat'], a['lon'], a['time']
    good = (u > -32000) & (v > -32000) & (h > -32000) & (h * 0.01 <= HDOP)
    enc = lambda q: np.clip(np.round(np.nan_to_num(q) / VMAX * 127 + 128), 1, 255).astype(np.uint8)
    frames = []
    for i in range(LOOP):                                     # each hour as measured, holes and all
        fu = np.where(good[i], u[i] * 0.01, np.nan); fv = np.where(good[i], v[i] * 0.01, np.nan)
        if lat[0] < lat[-1]: fu, fv = fu[::-1], fv[::-1]
        fo = np.isfinite(fu) & (np.hypot(np.nan_to_num(fu), np.nan_to_num(fv)) <= 2.5)
        frames.append((np.dstack([enc(fu), enc(fv), np.where(fo, 255, 0).astype(np.uint8)]), int(t[i]), int(fo.sum())))
    good, u, v, t = good[-HOURS:], u[-HOURS:], v[-HOURS:], t[-HOURS:]
    n = good.sum(0)
    with np.errstate(invalid='ignore', divide='ignore'):
        U = np.where(n > 0, np.where(good, u * 0.01, 0).sum(0) / n, np.nan); V = np.where(n > 0, np.where(good, v * 0.01, 0).sum(0) / n, np.nan)
    if lat[0] < lat[-1]: U, V = U[::-1], V[::-1]                      # north up
    ok = np.isfinite(U) & (np.hypot(np.nan_to_num(U), np.nan_to_num(V)) <= 2.5)
    rgb = np.dstack([enc(U), enc(V), np.where(ok, 255, 0).astype(np.uint8)])
    dy = abs(lat[1] - lat[0]) / 2; dx = abs(lon[1] - lon[0]) / 2
    lo0, lo1 = float(lon.min() - dx), float(lon.max() + dx)
    if lo0 > 180: lo0 -= 360; lo1 -= 360
    meta = {'k': k, 'box': [round(lo0, 4), round(float(lat.min() - dy), 4), round(lo1, 4), round(float(lat.max() + dy), 4)], 'w': nx, 'h': ny,
            't0': int(t[0]), 't1': int(t[-1]), 'cells': int(ok.sum()), 'loop': [f[1] for f in frames]}
    return rgb, meta, frames


def put(src, key, ct, cache):
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', src, 's3://%s/%s' % (BUCKET, key), '--content-type', ct, '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', src, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: ' + ct, '--header-upload', 'Cache-Control: ' + cache], check=True)


def main():
    tmp = tempfile.mkdtemp(); regs = []; ups = []
    for k in REGIONS:
        try:
            rgb, m, frames = region(k)
        except Exception as e:
            print('skip', k, e); continue
        if not m['cells']: print('skip', k, 'no cells'); continue
        p = os.path.join(tmp, k + '.png'); Image.fromarray(rgb).save(p, optimize=True); ups.append((p, 'hfr/%s.png' % k)); regs.append(m)
        for i, f in enumerate(frames):
            fp = os.path.join(tmp, '%s_%d.png' % (k, i)); Image.fromarray(f[0]).save(fp, optimize=True); ups.append((fp, 'hfr/loop/%s_%d.png' % (k, i)))
        print(k, m['cells'], 'cells', time.strftime('%H:%M', time.gmtime(m['t0'])), '-', time.strftime('%H:%M UTC', time.gmtime(m['t1'])), os.path.getsize(p), 'bytes')
    if not regs: raise SystemExit('no region answered')
    v = int(time.time()); meta = {'regions': regs, 'vmax': VMAX, 'hours': HOURS, 'v': v}
    mp = os.path.join(tmp, 'latest.json'); json.dump(meta, open(mp, 'w'))
    if '--dry' in sys.argv: print('dry run:', tmp); return
    for src, key in ups: put(src, key, 'image/png', 'public, max-age=1800')
    put(mp, 'hfr/latest.json', 'application/json', 'public, max-age=600')
    print('uploaded', len(regs), 'regions')


if __name__ == '__main__':
    main()
