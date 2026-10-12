"""THE GROUND'S SHAPE for the CITY MAP's GEOLOGY tab (2026-10-12, user: "the geology tab in CITY MAP has no geological
topography baked in to show the hills and remnants"). The ink basemap's lidar shading was baked faint for the street map
and mostly draws built edges (highways, embankments); this is the LANDFORM: USGS 3DEP bare-earth DEM, 1/3 arc-second
(~10 m, public domain, elevation.nationalmap.gov 3DEPElevation ImageServer), smoothed and exaggerated so the moraine, the
Manhattan and Bronx ridges, Fort Greene, Forest Park and Staten Island's serpentinite hills read.
Output: the same LA tile grid the page already draws (index {w0,s0,levels:[{base,d,minMpp,maxMpp,tiles}]}): L = 255 lit /
0 shaded, A = how much. Two levels: 0.32 deg tiles at ~40 m for the city-wide view, 0.08 deg tiles at ~10 m for zooms.
python3 bake.py fetch <dir>            48 DEM tiles, lon -74.32..-73.68, lat 40.48..40.96, 864 px each
python3 bake.py bake <dir> <out_dir>   tiles + <out_dir>/index.json (copy to the repo as city_landform_index.json)"""
import sys, os, json, math, urllib.request, numpy as np, tifffile
from PIL import Image   # tifffile reads the DEM: these are 128 px TILED TIFFs and PIL decodes the part-tiles at the edges as noise
W0, S0, D, N, NX, NY = -74.32, 40.48, 0.08, 864, 8, 6
def fetch(d):
    os.makedirs(d, exist_ok=True)
    for r in range(NY):
        for c in range(NX):
            f = '%s/r%02dc%02d.tif' % (d, r, c)
            if os.path.exists(f):
                try: tifffile.imread(f); continue           # a whole tile; a truncated one is fetched again
                except Exception: os.remove(f)
            w, s = W0 + c * D, S0 + r * D
            u = ('https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage?bbox=%f,%f,%f,%f'
                 '&bboxSR=4326&imageSR=4326&size=%d,%d&format=tiff&pixelType=F32&interpolation=RSP_NearestNeighbor&f=image') % (w, s, w + D, s + D, N, N)
            for k in range(3):
                try:
                    open(f, 'wb').write(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluishvoid.com map bake'}), timeout=120).read())
                    tifffile.imread(f); break
                except Exception as e: print('retry', f, e)
            print(f)
def mosaic(d):
    Z = np.zeros((NY * N, NX * N), np.float32)
    for r in range(NY):
        for c in range(NX):
            try: a = tifffile.imread('%s/r%02dc%02d.tif' % (d, r, c)).astype(np.float32)
            except Exception:      # the service sends an unreadable stub for an all-water box (r00c07: open sea off the Rockaways)
                print('no data, sea level:', r, c); a = np.zeros((N, N), np.float32)
            a[~np.isfinite(a) | (a < -50) | (a > 400)] = 0           # NoData is a huge float (nearest-neighbour fetch keeps it unblended); nothing real here tops ~270 m
            Z[(NY - 1 - r) * N:(NY - r) * N, c * N:(c + 1) * N] = a     # row 0 of the mosaic is the NORTH edge
    return Z
def shade(Z, px_deg, zf, sig):
    from scipy.ndimage import gaussian_filter
    Zs = gaussian_filter(Z, sig)
    lat = S0 + NY * D / 2
    dx = px_deg * 111320 * math.cos(math.radians(lat)); dy = px_deg * 111320
    gy, gx = np.gradient(Zs * zf, dy, dx)          # gy: per row (southward), gx: per column (eastward)
    slope = np.arctan(np.hypot(gx, gy)); asp = np.arctan2(-gx, gy)   # aspect, downslope direction measured from north
    alt = math.radians(45); hs = 0
    for az, wgt in ((315, .6), (270, .2), (0, .2)):
        a = math.radians(az)
        hs = hs + wgt * (math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(a - asp - math.pi))
    flat = math.sin(alt)
    dlt = hs - flat
    L = np.where(dlt > 0, 255, 0).astype(np.uint8)
    A = np.clip(np.abs(dlt) * np.where(dlt > 0, 260, 520), 0, 190).astype(np.uint8)   # shadows stronger than highlights
    A[Z <= 0.3] = 0                                                                  # the water is flat; leave it alone
    A = (A // 6 * 6).astype(np.uint8)                                                # 32 steps: invisible as an overlay, a third the bytes
    return L, A
def bake(d, out):
    Z = mosaic(d)
    os.makedirs(out + '/l1', exist_ok=True); os.makedirs(out + '/l0', exist_ok=True)
    idx = {'w0': W0, 's0': S0, 'note': 'USGS 3DEP 1/3 arc-second bare earth, landform shading for the GEOLOGY tab (_maplab/geo_relief/bake.py)', 'levels': []}
    L, A = shade(Z, D / N, 5.0, 1.4)
    t1 = []
    for r in range(NY):
        for c in range(NX):
            sl = (slice((NY - 1 - r) * N, (NY - r) * N), slice(c * N, (c + 1) * N))
            if A[sl].max() < 8: continue
            Image.merge('LA', (Image.fromarray(L[sl]), Image.fromarray(A[sl]))).save('%s/l1/r%02dc%02d.png' % (out, r, c), optimize=True)
            t1.append('r%02dc%02d' % (r, c))
    # the city-wide level: the mosaic at a quarter, in 0.32 deg tiles (2 x 2, the north row partly empty)
    Zq = Z.reshape(NY * N // 4, 4, NX * N // 4, 4).mean(axis=(1, 3))
    Lq, Aq = shade(Zq, D * 4 / N, 5.0, 0.8)
    Q = N   # a 0.32 deg tile is 4 source tiles = 864 px at a quarter
    t0 = []
    for r in range(2):
        for c in range(2):
            rows = slice(max(0, Zq.shape[0] - (r + 1) * Q), Zq.shape[0] - r * Q); cols = slice(c * Q, (c + 1) * Q)
            l, a = Lq[rows, cols], Aq[rows, cols]
            if a.size == 0 or a.max() < 8: continue
            pl = Image.new('L', (Q, Q), 0); pa = Image.new('L', (Q, Q), 0)
            pl.paste(Image.fromarray(l), (0, Q - l.shape[0])); pa.paste(Image.fromarray(a), (0, Q - a.shape[0]))
            Image.merge('LA', (pl, pa)).save('%s/l0/r%02dc%02d.png' % (out, r, c), optimize=True)
            t0.append('r%02dc%02d' % (r, c))
    CDN = 'https://cdn.bluishvoid.com/nyc/landform/v1/'   # rclone copy <out>/l0 and l1 to r2:bluishvoid-bg/nyc/landform/v1/
    idx['levels'] = [{'base': CDN + 'l0/', 'd': D * 4, 'minMpp': 12, 'maxMpp': 1e9, 'tiles': t0},
                     {'base': CDN + 'l1/', 'd': D, 'minMpp': 0, 'maxMpp': 12, 'tiles': t1}]
    json.dump(idx, open(out + '/index.json', 'w'))
    print('l0', t0, 'l1', len(t1), 'max elev', float(Z.max()))
if __name__ == '__main__':
    if sys.argv[1] == 'fetch': fetch(sys.argv[2])
    else: bake(sys.argv[2], sys.argv[3])
