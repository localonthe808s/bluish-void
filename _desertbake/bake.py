#!/usr/bin/env python3
"""THE DESERT IS GROUND, NOT A HOLE -- the national version (user 2026-10-19: "all deserts in the new map should be properly
colored"). THE BASIN learned this first (_maplab/index.html, 2026-09-19): a map that paints green where things grow and
nothing where they do not leaves the driest third of the West on the bare night ground, and it reads as missing data.

WHAT LOCAL DOES NOW (measured 2026-10-19 by rasterizing the live tiles.bluishvoid.com z7 / z9 tiles in the paint order of
_bvVectorBase + _bvPaintPlus, with the relief/v1 hillshade over them; mean luminance of land, 0-255):

    Mojave 36 / 44     Sonoran 38 / 35     Great Basin 31 / 28     Chihuahuan 31 / 35     Colorado Plateau 35 / 33
    White Sands 28 / 33     Bonneville 32 / 33     Death Valley 36 / 36     (z7 / z9)
    vegetated, for scale: Ohio 26 / 19, Iowa 22 / 20, the Palouse 32 / 21

The desert rule from 2026-10-16 (the archive's own z7 landcover, barren / scrub, filled #2a2319 / #211d16 at 0.88) is there,
but its browns sit 10-15 levels above the ink ground: the West reads as mud a shade off black, not as the brightest ground on
the continent. And the landcover is coarse and literal -- the Great Basin tile is 49% "grassland" (sagebrush steppe), White
Sands' 64%, so half the basin-and-range stays black, and z7 polygons hold hard staircase edges at z10-12. THE BASIN's
answer was a desert at luminance ~85 against ~69 for its vegetated hills: the desert really is the brighter ground.

THE SAME RULE, AS A RASTER. One tan, rgb(140,120,90), in 16 alpha steps, as THE BASIN's veg bake is one green in 16 steps.
The weight is "what is on the ground, and how un-green it is":

    ESA WorldCover 2021 v200, 10 m (CC BY 4.0, (c) ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data
    (2021) processed by ESA WorldCover consortium), read from the public cloud-optimized files on AWS
    (s3://esa-worldcover, over https) through their overviews (~80-115 m), each output pixel the MEAN of the cells under it:
        60 bare / sparse vegetation     1.0 x (0.5 + 0.5 x dry)    playas, dunes, rock, the Mojave floor
        20 shrubland                    1.0 x dry                  creosote, sagebrush -- and chaparral, which dry spares
        30 grassland                    0.8 x dry                  desert grassland vs. the Palouse and the prairie
        100 moss / lichen               0.5 x dry
        everything else (trees, crops, built, water, snow, wetland, mangrove)  0
    dry = 1 - clip((peak NDVI - 0.18) / 0.27, 0, 1): THE BASIN's greenness ramp inverted. Peak NDVI is the greenest of five
    months of NASA's MODIS Terra monthly NDVI (GIBS WMS, public domain), decoded through GIBS' own colormap, so a
    monsoon-green Sonoran August or a spring-green Mojave counts as it should; chaparral (0.5-0.6) keeps none of the tan,
    sagebrush (0.2-0.3) most of it, the Mojave (0.1) all of it. Cropland is never desert -- the Palouse stays the color it is.

Water is spared by class (80) rather than by color, and the sea has no WorldCover tile at all, so the tint is zero on both.

OUTPUT: 256 px palette PNG tiles z4-9 (z9 = ~240 m a pixel at 37N; the grid is 15", a touch coarser, kept there so the
whole box fits in ~1 GB of memory -- a tint this soft does not need more), in web mercator,
skipping any tile with no tint; cover.json lists the z7 tiles that hold one (the client's index, as relief/v1's is z8);
preview.png is the whole box. The box is the arid West and northern Mexico (Sonoran, Chihuahuan, Baja, Great Basin,
Colorado Plateau, Mojave, the high plains to -93).

    python3 bake.py --out OUT [--cache CACHE] [--workers 2]
    then: rclone copy OUT r2:bluishvoid-bg/desert/v1 ...      (see the upload commands in the report / README of the run)
"""
import argparse, io, json, math, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
from scipy import ndimage

BOX = (-125.0, 22.0, -93.0, 49.5)                # W, S, E, N
STEP = 1 / 240.0                                 # 15 arc-seconds: ~460 m N-S, ~370 m E-W at 37N
OVER = 4                                         # WorldCover samples per output pixel, each way (~115 m)
TAN = (140, 120, 90)                             # THE BASIN's sand
MINZ, MAXZ, COVZ = 4, 9, 7
WC_TILE = ('https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/'
           'ESA_WorldCover_10m_2021_v200_%s%02d%s%03d_Map.tif')
NDVI_WMS = 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi'
NDVI_CMAP = 'https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_NDVI.xml'
NDVI_MONTHS = ('2025-03-01', '2025-05-01', '2025-07-01', '2025-08-01', '2025-10-01')
W = int(round((BOX[2] - BOX[0]) / STEP))
H = int(round((BOX[3] - BOX[1]) / STEP))


def get(url, timeout=120, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluishvoid-desertbake'}), timeout=timeout) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(3 * (k + 1))


# ------------------------------------------------------------------ greenness ----
def dryness(cache):
    """1 - THE BASIN's greenness factor, on the output grid (bilinear from a 30" peak-NDVI grid)."""
    p = os.path.join(cache, 'dry.npy')
    if os.path.exists(p):
        return np.load(p)
    x = get(NDVI_CMAP).decode('utf-8', 'replace')
    ents = re.findall(r'<ColorMapEntry[^>]*rgb="(\d+),(\d+),(\d+)"[^>]*value="\[?([-\d.]+)', x)
    pack = lambda r, g, b: (np.asarray(r, 'int64') << 16) | (np.asarray(g, 'int64') << 8) | np.asarray(b, 'int64')
    keys = pack(*np.array([[int(r), int(g), int(b)] for r, g, b, _ in ents]).T)
    vals = np.array([float(v) for _, _, _, v in ents], 'float32')
    o = np.argsort(keys); keys, vals = keys[o], vals[o]
    gw, gh = int(round((BOX[2] - BOX[0]) * 120)), int(round((BOX[3] - BOX[1]) * 120))
    best = np.full((gh, gw), np.nan, 'float32')
    for day in NDVI_MONTHS:
        u = (NDVI_WMS + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1&LAYERS=MODIS_Terra_L3_NDVI_Monthly&STYLES='
             '&SRS=EPSG:4326&BBOX=%f,%f,%f,%f&WIDTH=%d&HEIGHT=%d&FORMAT=image/png&TIME=%s' % (BOX + (gw, gh, day)))
        a = np.array(Image.open(io.BytesIO(get(u, 300))).convert('RGBA')).reshape(-1, 4)
        k = pack(a[:, 0], a[:, 1], a[:, 2])
        i = np.clip(np.searchsorted(keys, k), 0, len(keys) - 1)
        v = np.where((keys[i] == k) & (a[:, 3] > 0), vals[i], np.nan).reshape(gh, gw)
        v[v < -0.15] = np.nan                                   # the colormap's own no-data entry
        print('  ndvi %s  valid %.0f%%  median %.2f' % (day, 100 * np.isfinite(v).mean(), np.nanmedian(v)), flush=True)
        best = np.fmax(best, v)
    if np.nanmax(best) > 2:                                    # the published scale may be 0..1 or 0..10000
        best = best / 10000.0
    g = np.clip((best - 0.18) / 0.27, 0, 1)
    g = np.where(np.isfinite(g), g, 0.5).astype('float32')
    g = ndimage.gaussian_filter(g, 1.2)
    ys = (np.arange(H) + 0.5) * gh / H - 0.5
    xs = (np.arange(W) + 0.5) * gw / W - 0.5
    dry = np.empty((H, W), 'float32')
    for r0 in range(0, H, 1024):                               # in bands: one full meshgrid is 1.4 GB
        yy, xx = np.meshgrid(ys[r0:r0 + 1024], xs, indexing='ij')
        dry[r0:r0 + 1024] = 1.0 - ndimage.map_coordinates(g, [yy, xx], order=1, mode='nearest')
    np.save(p, dry)
    return dry


# ------------------------------------------------------------ land cover ----
LUT_BARE = np.zeros(256, 'float32'); LUT_BARE[60] = 1.0
LUT_DRY = np.zeros(256, 'float32'); LUT_DRY[20] = 1.0; LUT_DRY[30] = 0.8; LUT_DRY[100] = 0.5


def wc_tile(la, lo, cache):
    """(bare, dry-able) mean weights for one 3-degree WorldCover tile on the output grid, or None (sea: no tile)."""
    p = os.path.join(cache, 'wc_%d_%d.npz' % (la, lo))
    if os.path.exists(p):
        z = np.load(p)
        return (z['b'], z['d']) if z['b'].size else None
    import rasterio
    from rasterio.windows import from_bounds
    tw, ts, te, tn = max(BOX[0], lo), max(BOX[1], la), min(BOX[2], lo + 3), min(BOX[3], la + 3)
    ow, oh = int(round((te - tw) / STEP)), int(round((tn - ts) / STEP))
    url = WC_TILE % ('N' if la >= 0 else 'S', abs(la), 'E' if lo >= 0 else 'W', abs(lo))
    try:
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_MAX_RETRY='4', GDAL_HTTP_RETRY_DELAY='3'):
            with rasterio.open(url) as ds:
                a = ds.read(1, window=from_bounds(tw, ts, te, tn, ds.transform), out_shape=(oh * OVER, ow * OVER))
    except Exception as e:
        if '404' in str(e) or 'not recognized' in str(e) or 'No such file' in str(e) or 'does not exist' in str(e):
            np.savez(p, b=np.zeros(0), d=np.zeros(0))
            return None
        raise
    b = LUT_BARE[a].reshape(oh, OVER, ow, OVER).mean(axis=(1, 3)).astype('float32')
    d = LUT_DRY[a].reshape(oh, OVER, ow, OVER).mean(axis=(1, 3)).astype('float32')
    np.savez(p, b=b, d=d)
    return b, d


def weights(cache, workers):
    p = os.path.join(cache, 'weight.npy')
    if os.path.exists(p):
        return np.load(p)
    print('greenness (MODIS NDVI, GIBS)', flush=True)
    dry = dryness(cache)
    print('land cover (ESA WorldCover 2021)', flush=True)
    jobs = [(la, lo) for la in range(int(math.floor(BOX[1] / 3)) * 3, int(math.ceil(BOX[3])), 3)
            for lo in range(int(math.floor(BOX[0] / 3)) * 3, int(math.ceil(BOX[2])), 3)]
    wt = np.zeros((H, W), 'float32')

    def one(j):
        la, lo = j
        r = wc_tile(la, lo, cache)
        return j, r
    with ThreadPoolExecutor(workers) as ex:
        for n, ((la, lo), r) in enumerate(ex.map(one, jobs)):
            if r is None:
                continue
            b, d = r
            tw, tn = max(BOX[0], lo), min(BOX[3], la + 3)
            x0, y0 = int(round((tw - BOX[0]) / STEP)), int(round((BOX[3] - tn) / STEP))
            sl = (slice(y0, y0 + b.shape[0]), slice(x0, x0 + b.shape[1]))
            dr = dry[sl]
            wt[sl] = b * (0.5 + 0.5 * dr) + d * dr
            print('  %3d/%d  N%02d W%03d  tint %.0f%%' % (n + 1, len(jobs), la, -lo, 100 * (wt[sl] > 0.1).mean()), flush=True)
    wt = np.clip(ndimage.gaussian_filter(wt, 0.7), 0, 1)
    np.save(p, wt)
    return wt


# ------------------------------------------------------------------ tiles ----
def palette_png(wt):
    lv = np.clip(np.round(wt * 15), 0, 15).astype('uint8')     # 16 steps of one tan
    im = Image.fromarray(lv, 'P')
    im.putpalette(list(TAN) * 16 + [0, 0, 0] * 240)
    tr = bytes([int(round(i * 255 / 15.0)) for i in range(16)])
    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True, transparency=tr)
    return buf.getvalue()


def lonlat_tile(lon, lat, z):
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def tiles(wt, out):
    cover, total = set(), 0
    for z in range(MINZ, MAXZ + 1):
        n = 2 ** z
        x0, y0 = lonlat_tile(BOX[0], BOX[3], z)
        x1, y1 = lonlat_tile(BOX[2] - 1e-9, BOX[1] + 1e-9, z)
        cnt, kb = 0, 0
        for ty in range(y0, y1 + 1):
            py = ty * 256 + np.arange(256) + 0.5
            lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * py / (256.0 * n)))))
            gy = (BOX[3] - lat) / STEP - 0.5
            for tx in range(x0, x1 + 1):
                px = tx * 256 + np.arange(256) + 0.5
                lon = px / (256.0 * n) * 360 - 180
                gx = (lon - BOX[0]) / STEP - 0.5
                yy, xx = np.meshgrid(gy, gx, indexing='ij')
                inside = (yy >= -0.5) & (yy <= H - 0.5) & (xx >= -0.5) & (xx <= W - 0.5)
                if not inside.any():
                    continue
                if z < MAXZ:                                   # area-average below native: no shimmer at z4-8
                    k = 2 ** (MAXZ - z)
                    sig = 0.42 * k * 0.5
                    src = wt if sig < 0.6 else _blurred(wt, sig)
                else:
                    src = wt
                v = ndimage.map_coordinates(src, [np.clip(yy, 0, H - 1), np.clip(xx, 0, W - 1)], order=1) * inside
                if (v > 0.04).mean() < 0.0005:
                    continue
                d = os.path.join(out, str(z), str(tx))
                os.makedirs(d, exist_ok=True)
                b = palette_png(v)
                open(os.path.join(d, '%d.png' % ty), 'wb').write(b)
                cnt += 1; kb += len(b)
                if z >= COVZ:
                    s = z - COVZ
                    cover.add('%d/%d' % (tx >> s, ty >> s))
        total += kb
        print('  z%d  %5d tiles  %7.1f MB' % (z, cnt, kb / 1e6), flush=True)
    json.dump(sorted(cover), open(os.path.join(out, 'cover.json'), 'w'), separators=(',', ':'))
    print('  all  %.1f MB, cover.json %d z%d tiles' % (total / 1e6, len(cover), COVZ), flush=True)


_BL = {}


def _blurred(wt, sig):
    k = round(sig, 2)
    if k not in _BL:
        _BL.clear()
        _BL[k] = ndimage.gaussian_filter(wt, sig)
    return _BL[k]


def preview(wt, out):
    """The whole box, plate carree at 1/40 degree, the tint at THE BASIN's 0.6 over the ink ground (#0f1116)."""
    k = 8
    s = wt[:H // k * k, :W // k * k].reshape(H // k, k, W // k, k).mean(axis=(1, 3))
    a = (np.round(s * 15) / 15 * 0.6)[..., None]
    img = np.array([15, 17, 22], 'float32') * (1 - a) + np.array(TAN, 'float32') * a
    Image.fromarray(img.astype('uint8')).save(os.path.join(out, 'preview.png'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--cache')
    ap.add_argument('--workers', type=int, default=2)
    a = ap.parse_args()
    cache = a.cache or os.path.join(a.out, '_cache')
    os.makedirs(cache, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    print('grid %d x %d at 1/%d degree' % (W, H, round(1 / STEP)), flush=True)
    wt = weights(cache, a.workers)
    preview(wt, a.out)
    print('tiles z%d-%d' % (MINZ, MAXZ), flush=True)
    tiles(wt, a.out)


if __name__ == '__main__':
    main()
