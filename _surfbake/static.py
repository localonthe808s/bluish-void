#!/usr/bin/env python3
"""THE SARGASSO SEA AND THE GARBAGE PATCHES FROM REAL DATA (2026-10-26, user: "what real sources can be used, garbage patches are weak
too"). Run by hand when a source updates (the microplastics database is refreshed quarterly); writes to R2 surf/:

    surf/static.json  {"sea": the Sargasso Sea EBSA -- the area the Convention on Biological Diversity described in 2012
                               (Wider Caribbean and Western Mid-Atlantic workshop, GLOBAL_ID WC_13, 4.18 M km2), [[lat, lon], ...]
                               simplified to ~0.05 deg; from the CBD / UNEP-WCMC global EBSA layer (source.coop cboettig/high-seas),
                       "gpgp": The Ocean Cleanup's Great Pacific Garbage Patch contours (Lebreton et al. 2018, Scientific Reports,
                               figshare 5873142, CC BY 4.0): 10, 1 and 0.1 kg/km2, the 10 kg ring being the patch's 1.6 M km2,
                       "gpgpBox": the concentration grid's bounds,
                       "mp": NOAA NCEI's Global Marine Microplastics Database, ocean-surface samples (public domain), as
                             [lat, lon, pieces per m3, year, study index], "mpRefs": [short reference, DOI] per study}
    surf/gpgp.png     the same study's mass concentration grid (0.2 deg), web-mercator rows, colored, transparent below
                      0.1 kg/km2

    python3 _surfbake/static.py [--dry]
"""
import io, json, math, os, subprocess, sys, tempfile, time, urllib.parse, urllib.request, zipfile
import numpy as np
from PIL import Image

BUCKET = 'bluishvoid-bg'
EBSA = 'https://data.source.coop/cboettig/high-seas/ebsa.parquet'
GPGP_ZIP = 'https://ndownloader.figshare.com/files/44299727'
GPGP_TIF = 'https://ndownloader.figshare.com/files/44299730'
MP = 'https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/Ocean_Surface_Microplastics_(PS)/FeatureServer/0/query'
UA = {'User-Agent': 'bluishvoid.com ocean bake'}


def get(url, timeout=180):
    for k in range(4):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e: print('retry', k, e); time.sleep(10 * (k + 1))
    raise SystemExit('no answer: ' + url)


def sargasso():
    import pyarrow.parquet as pq
    from shapely import wkb
    t = pq.read_table(io.BytesIO(get(EBSA))).to_pylist()
    r = [x for x in t if x.get('GLOBAL_ID') == 'WC_13'][0]
    g = wkb.loads(r['geom']).simplify(0.05, preserve_topology=True)
    ring = [[round(y, 3), round(x, 3)] for x, y in g.exterior.coords]
    holes = [[[round(y, 3), round(x, 3)] for x, y in h.coords] for h in g.interiors]     # Bermuda's waters are left out of it
    print('sargasso EBSA', r['NAME'], r['Area_sqKm_EBSA'], 'km2,', len(ring), 'points after simplifying,', len(holes), 'hole')
    return ring, holes, r['Area_sqKm_EBSA']


def gpgp(tmp):
    import shapefile, tifffile
    zipfile.ZipFile(io.BytesIO(get(GPGP_ZIP))).extractall(os.path.join(tmp, 'gpgp'))
    r = shapefile.Reader(os.path.join(tmp, 'gpgp', 'GPGP_contours'))
    kg = {1: 0.1, 2: 1, 3: 10}           # the grid is log10 g/km2; its rings sit at 2.18 / 3.18 / 4.18 (measured), ~0.15 / 1.5 / 15
    rings = []
    for s, rec in zip(r.shapes(), r.records()):
        if len(s.points) < 9: continue   # specks a pixel or two across
        pts = s.points[::2] if len(s.points) > 200 else s.points
        rings.append({'kg': kg[int(rec[1])], 'p': [[round(y, 2), round(x, 2)] for x, y in pts]})
    tp = os.path.join(tmp, 'gpgp.tif'); open(tp, 'wb').write(get(GPGP_TIF))
    tf = tifffile.TiffFile(tp); pg = tf.pages[0]
    sx, sy = pg.tags['ModelPixelScaleTag'].value[:2]; x0, y0 = pg.tags['ModelTiepointTag'].value[3:5]
    a = pg.asarray().astype(np.float64); a[a < -1000] = np.nan
    H, W = a.shape; box = [x0, y0 - H * sy, x0 + W * sx, y0]
    # color: 0.1 kg/km2 (log 2) faint slate -> 10 kg/km2 (log 4) bright pale amber -> 100+ near white; alpha with it
    k = np.clip((a - 2.0) / 3.0, 0, 1); ok = np.isfinite(a) & (a >= 2.0)
    # faint below 1 kg/km2 (the grid's floor filled its whole box as a grey slab) and feathered at the grid's edges
    lo = np.clip((np.nan_to_num(a, nan=0) - 2.3) / 0.9, 0, 1)
    fy = np.clip(np.minimum(np.arange(a.shape[0]), a.shape[0] - 1 - np.arange(a.shape[0])) / 8.0, 0, 1)
    fx = np.clip(np.minimum(np.arange(a.shape[1]), a.shape[1] - 1 - np.arange(a.shape[1])) / 8.0, 0, 1)
    edge = np.minimum(fy[:, None], fx[None, :])
    stops = [(0, (148, 163, 184)), (.5, (253, 230, 138)), (1, (255, 251, 235))]
    rgb = np.zeros((H, W, 3), np.float32)
    for c in range(3): rgb[..., c] = np.interp(np.nan_to_num(k), [s[0] for s in stops], [s[1][c] for s in stops])
    al = np.where(ok, (40 + 200 * np.nan_to_num(k)) * lo * edge, 0)
    rgba = np.dstack([rgb, al]).round().astype(np.uint8)
    my = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    S0, N0 = box[1], box[3]; Hm = int(round(H * 4 * (my(N0) - my(S0)) / math.radians(N0 - S0)))
    rows = [min(H - 1, max(0, int((N0 - math.degrees(2 * math.atan(math.exp(my(N0) - (i + .5) / Hm * (my(N0) - my(S0)))) - math.pi / 2)) / (N0 - S0) * H))) for i in range(Hm)]
    im = Image.fromarray(rgba[rows]).resize((W * 4, Hm), Image.BILINEAR)      # 4x across, smoothed: a model grid, not pixels
    out = os.path.join(tmp, 'gpgp.png'); im.save(out, optimize=True)
    print('gpgp', len(rings), 'rings, grid', (H, W), box, os.path.getsize(out), 'bytes')
    return rings, [round(b, 3) for b in box], out


def microplastics():
    rows, refs, rix, off = [], [], {}, 0
    while True:
        q = urllib.parse.urlencode({'where': '1=1', 'outFields': 'Latitude__degree_,Longitude_degree_,Microplastics_measurement,Unit,Date__MM_DD_YYYY_,Short_Reference,DOI',
                                    'resultOffset': off, 'resultRecordCount': 1000, 'orderByFields': 'ObjectId', 'f': 'json'})
        j = json.loads(get(MP + '?' + q, 120)); fs = j.get('features', [])
        for f in fs:
            a = f['attributes']; la, lo, v = a['Latitude__degree_'], a['Longitude_degree_'], a['Microplastics_measurement']
            if la is None or lo is None or v is None or a.get('Unit') != 'pieces/m3': continue
            ref = (a.get('Short_Reference') or '').strip(); key = ref + '|' + (a.get('DOI') or '')
            if key not in rix: rix[key] = len(refs); refs.append([ref, a.get('DOI') or ''])
            yr = time.gmtime(a['Date__MM_DD_YYYY_'] / 1000).tm_year if a.get('Date__MM_DD_YYYY_') else 0
            rows.append([round(la, 2), round(lo, 2), float('%.3g' % v), yr, rix[key]])
        off += len(fs)
        if not fs or not j.get('exceededTransferLimit'): break
    print('microplastics', len(rows), 'surface samples,', len(refs), 'studies')
    return rows, refs


MZ = ['https://www.weather.gov/source/gis/Shapefiles/WSOM/mz16ap26.zip', 'https://www.weather.gov/source/gis/Shapefiles/WSOM/oz16ap26.zip']


def marine_zones(tmp):
    """NWS coastal + offshore marine forecast zones (WATER's SEA tab, MARINE FORECAST), simplified ~0.02 deg -> surf/marine.json
    {id: [name, wfo, [[[lat, lon], ...] rings]]}"""
    import shapefile
    from shapely.geometry import shape
    out = {}
    for u in MZ:
        d = os.path.join(tmp, os.path.basename(u)[:-4]); zipfile.ZipFile(io.BytesIO(get(u))).extractall(d)
        shp = [f for f in os.listdir(d) if f.endswith('.shp')][0]
        r = shapefile.Reader(os.path.join(d, shp)); names = [f[0] for f in r.fields[1:]]
        for sr in r.iterShapeRecords():
            a = dict(zip(names, sr.record)); zid = a.get('ID') or a.get('Id'); 
            if not zid: continue
            g = shape(sr.shape.__geo_interface__).simplify(0.02, preserve_topology=True)
            polys = [g] if g.geom_type == 'Polygon' else list(getattr(g, 'geoms', []))
            rings = [[[round(y, 3), round(x, 3)] for x, y in pg.exterior.coords] for pg in polys if pg.area > 1e-5]
            if rings: out[zid] = [a.get('NAME') or a.get('Name') or '', a.get('WFO') or '', rings]
    p = os.path.join(tmp, 'marine.json'); json.dump(out, open(p, 'w'), separators=(',', ':'))
    print('marine zones', len(out), os.path.getsize(p), 'bytes')
    return p


def put(src, key, ct, cache):
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', src, 's3://%s/%s' % (BUCKET, key), '--content-type', ct, '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', src, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: ' + ct, '--header-upload', 'Cache-Control: ' + cache], check=True)


def main():
    tmp = tempfile.mkdtemp()
    sea, holes, area = sargasso()
    rings, box, png = gpgp(tmp)
    mp, refs = microplastics()
    v = int(time.time())
    out = {'sea': sea, 'seaHoles': holes, 'seaKm2': area, 'gpgp': rings, 'gpgpBox': box, 'mp': mp, 'mpRefs': refs, 'at': v, 'v': v}
    jp = os.path.join(tmp, 'static.json'); json.dump(out, open(jp, 'w'), separators=(',', ':'))
    mzp = marine_zones(tmp)
    print('static.json', os.path.getsize(jp), 'bytes')
    if '--dry' in sys.argv: print('dry run:', tmp); return
    put(png, 'surf/gpgp.png', 'image/png', 'public, max-age=86400')
    put(jp, 'surf/static.json', 'application/json', 'public, max-age=86400')
    put(mzp, 'surf/marine.json', 'application/json', 'public, max-age=86400')
    print('uploaded')


if __name__ == '__main__':
    main()
