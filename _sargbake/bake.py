#!/usr/bin/env python3
"""SARGASSUM, LAST 7 DAYS (2026-10-25, user: "can the water tab also highlight ... sargassum seaweed blobs location"). NOAA AOML's
CoastWatch node serves USF's Alternative Floating Algae Index (AFAI, Hu et al. 2015) from MODIS / VIIRS / OLCI as 7-day composites
over 0-38 N, 98-38 W, ~1.6 km; floating mats read as AFAI above the open-water background. No CORS, so baked daily:

    sargassum/latest.png   the mats in web mercator over the box (transparent elsewhere), amber -> orange-red by AFAI
    sargassum/latest.json  {"t": composite date, "box": [w, s, e, n], "seen": share of the box the satellites saw clear,
                            "km2": mat-covered area flagged, "by": {region: km2}}

Coastal water is masked (25 km from Natural Earth 1:50m land): shallow bottoms, river plumes and beached weed all read high on AFAI.
The threshold (0.0005) keeps the long windrows and drops the speckle; it flags where mats are, not how much weed is in them.
    python3 _sargbake/bake.py [--dry]
"""
import io, json, math, os, subprocess, sys, tempfile, time, urllib.request
import numpy as np
from PIL import Image, ImageDraw
from scipy.io import netcdf_file
from scipy.ndimage import binary_dilation, uniform_filter

HERE = os.path.dirname(os.path.abspath(__file__))
URL = ('https://cwcgom.aoml.noaa.gov/erddap/griddap/noaa_aoml_atlantic_oceanwatch_AFAI_7D.nc?AFAI%5Blast%5D%5B(0):2:(38)%5D%5B(-98):2:(-38)%5D')
W0, S0, E0, N0 = -98.0, 0.0, -38.0, 38.0
TH = 0.0005; COAST_KM = 25
BUCKET = 'bluishvoid-bg'
REG = {'GULF OF MEXICO': (-98, 18, -80.5, 31), 'CARIBBEAN': (-89, 8, -60, 21.5), 'TROPICAL ATLANTIC': (-60, 0, -38, 21.5),
       'SARGASSO SEA AND THE BAHAMAS': (-80.5, 21.5, -38, 38)}


def topo_rings(path):
    t = json.load(open(path)); sc, tr = t['transform']['scale'], t['transform']['translate']; arcs = []
    for a in t['arcs']:
        x = y = 0; pts = []
        for dx, dy in a: x += dx; y += dy; pts.append((x * sc[0] + tr[0], y * sc[1] + tr[1]))
        arcs.append(pts)
    def ring(ix):
        out = []
        for i in ix:
            p = arcs[i] if i >= 0 else arcs[~i][::-1]
            out += p[1:] if out else p
        return out
    rings = []
    for g in t['objects']['land']['geometries']:
        polys = g['arcs'] if g['type'] == 'MultiPolygon' else [g['arcs']]
        for poly in polys:
            for r in poly: rings.append(ring(r))
    return rings


def main():
    p = os.path.join(tempfile.gettempdir(), 'afai7d.nc')
    for k in range(4):
        try: open(p, 'wb').write(urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'bluishvoid.com sargassum bake'}), timeout=300).read()); break
        except Exception as e: print('retry', k, e); time.sleep(30 * (k + 1))
    else: raise SystemExit('AOML ERDDAP did not answer')
    f = netcdf_file(p, 'r', mmap=False); a = f.variables['AFAI'][0].astype(np.float32)[::-1]   # north up
    tday = time.strftime('%Y-%m-%d', time.gmtime(float(f.variables['time'][0])))
    H, Wd = a.shape
    # land, rasterized on the same grid, grown by COAST_KM
    land = Image.new('L', (Wd, H), 0); d = ImageDraw.Draw(land)
    X = lambda lo: (lo - W0) / (E0 - W0) * Wd; Y = lambda la: (N0 - la) / (N0 - S0) * H
    for r in topo_rings(os.path.join(HERE, 'land50m.json')):
        if max(q[0] for q in r) < W0 - 2 or min(q[0] for q in r) > E0 + 2 or max(q[1] for q in r) < S0 - 2 or min(q[1] for q in r) > N0 + 2: continue
        d.polygon([(X(q[0]), Y(q[1])) for q in r], fill=255)
    px_km = (E0 - W0) / Wd * 111.32
    yy, xx = np.ogrid[-12:13, -12:13]; rad = COAST_KM / px_km
    coast = binary_dilation(np.asarray(land) > 0, structure=(xx * xx + yy * yy) <= rad * rad)
    ok = np.isfinite(a) & ~coast
    hit = ok & (a > TH)
    hit &= uniform_filter(hit.astype(np.float32), size=5) * 25 >= 2.5   # a lone pixel with no neighbour within ~6 km is speckle
    seen = float(ok.sum()) / float((~coast).sum())
    lat = N0 - (np.arange(H) + .5) / H * (N0 - S0); cell = (px_km ** 2) * np.cos(np.radians(lat))[:, None]
    km2 = float((hit * cell).sum())
    by = {}
    for nm, (w, s, e, n) in REG.items():
        r0, r1 = int(Y(n)), int(Y(s)); c0, c1 = int(X(w)), int(X(e))
        by[nm] = round(float((hit[r0:r1, c0:c1] * cell[r0:r1]).sum()))
    # colors: amber at the threshold to orange-red at 0.003, a 1 px soft halo so a windrow reads at a continent's zoom
    k = np.nan_to_num(np.clip((a - TH) / (0.003 - TH), 0, 1))
    rgba = np.zeros((H, Wd, 4), np.uint8)
    rgba[..., 0] = 255; rgba[..., 1] = (200 - 140 * k).astype(np.uint8); rgba[..., 2] = (40 - 30 * k).astype(np.uint8)
    halo = binary_dilation(hit) & ~hit
    rgba[..., 3] = np.where(hit, 235, np.where(halo, 90, 0)).astype(np.uint8)
    # to web mercator rows
    my = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    Hm = int(round(H * (my(N0) - my(S0)) / math.radians(N0 - S0)))
    rows = []
    for i in range(Hm):
        m = my(N0) - (i + .5) / Hm * (my(N0) - my(S0)); la = math.degrees(2 * math.atan(math.exp(m)) - math.pi / 2)
        rows.append(min(H - 1, max(0, int((N0 - la) / (N0 - S0) * H))))
    merc = rgba[rows]
    out = os.path.join(tempfile.gettempdir(), 'sargassum.png'); Image.fromarray(merc).save(out, optimize=True)
    meta = {'t': tday, 'box': [W0, S0, E0, N0], 'seen': round(seen, 3), 'km2': round(km2), 'by': by, 'at': int(time.time()), 'v': int(time.time())}
    mp = os.path.join(tempfile.gettempdir(), 'sargassum.json'); json.dump(meta, open(mp, 'w'))
    print(meta, os.path.getsize(out), 'bytes')
    if '--dry' in sys.argv: return
    for src, key, ct in ((out, 'sargassum/latest.png', 'image/png'), (mp, 'sargassum/latest.json', 'application/json')):
        if os.environ.get('R2_ACCOUNT_ID'):
            subprocess.run(['aws', 's3', 'cp', src, 's3://%s/%s' % (BUCKET, key), '--content-type', ct, '--cache-control', 'public, max-age=3600',
                            '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
        else:
            subprocess.run(['rclone', 'copyto', src, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                            '--header-upload', 'Content-Type: ' + ct, '--header-upload', 'Cache-Control: public, max-age=3600'], check=True)
    print('uploaded')


if __name__ == '__main__':
    main()
