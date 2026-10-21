#!/usr/bin/env python3
"""National coastal + Great Lakes + tidal-river bathymetry tiles (user 2026-10-16: "add coastal and river bathymetry to the
national map, bake it in to a high detail").

Per web-mercator tile: NOAA NCEI DEM_all (CUDEM 1/9" where it exists, else the Coastal Relief Models; Great Lakes included)
pulled for the tile's own box at 512 px, masked to WATER by our own basemap's water polygons for the same tile (so land below
sea level -- New Orleans behind its levees -- is never painted as sea), colored by depth in the site's navy family,
shaded with a multidirectional hillshade of the floor (v2) and faint isobaths. Inland rivers have no depth in this source (Memphis/St. Louis read the water SURFACE).
Output: 256 px WebP, transparent off the water.
"""
import io, math, sys, urllib.parse, urllib.request
import numpy as np, tifffile, mapbox_vector_tile as mvt
from PIL import Image, ImageDraw, ImageFilter

SRC = 'https://gis.ngdc.noaa.gov/arcgis/rest/services/DEM_mosaics/DEM_all/ImageServer/exportImage'
MVT = 'https://tiles.bluishvoid.com/bluish-basemap-20260829/{z}/{x}/{y}.mvt'
R = 6378137.0
N = 512

def tile_lonlat(z, x, y):
    n = 2 ** z; la = lambda t: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t / n))))
    return x / n * 360 - 180, la(y + 1), (x + 1) / n * 360 - 180, la(y)

def tile_bounds(z, x, y):
    n = 2 ** z; s = 2 * math.pi * R / n; x0 = -math.pi * R + x * s; y1 = math.pi * R - y * s
    return x0, y1 - s, x0 + s, y1

PAD = 8   # v2: 8 px at 512 (the hillshade's smoothing reads past the tile edge, so neighbours shade the same pixels the same)
# THE MOSAIC'S HOLES (2026-10-19). DEM_all mosaics at most 100 rasters per request (maxMosaicImageCount) and puts its global
# background, ETOPO 2022, last. A wide tile over a coast dense with surveys (the Louisiana shelf at z6, Florida's at z5-8)
# touches more than 100, ETOPO is dropped, and the pixels no surviving raster covers come back as exactly 0 m -- not NaN.
# Those read as dry, so the bake left them clear: rectangles of the basemap's lighter water inside the depth ramp. They are
# filled from ETOPO 2022 15" bed elevation, the mosaic's own background, asked for alone (lock raster) over the same box.
ETOPO_BED = 2530
# v2 (2026-10-19): fetched as LERC (max error 5 cm) instead of a float TIFF -- a fifth of the bytes for the same floor, which
# is what bounds the rate at z13 -- and for a BLOCK of B x B tiles in one request at z12-13 (the block's footprint stays at
# most a z11 tile, so it never reaches the 100-raster limit the wide tiles hit).
LERC_TOL = 0.05
INTERP = 'RSP_CubicConvolution'   # bilinear facets a coarse source (ETOPO 15", the 3" CRM) into flat-lit triangles past z10
def block_bounds(z, bx, by, B):
    x0, _, _, y1 = tile_bounds(z, bx * B, by * B)
    _, y0, x1, _ = tile_bounds(z, bx * B + B - 1, by * B + B - 1)
    return x0, y0, x1, y1

def fetch_dem(z, bx, by, B=1, lock=None):
    """float32 elevations (m) for the B x B block of 512 px tiles, PAD px all round; NaN off the data"""
    import imagecodecs
    b = block_bounds(z, bx, by, B); px = (b[2] - b[0]) / (B * N)
    b = (b[0] - PAD * px, b[1] - PAD * px, b[2] + PAD * px, b[3] + PAD * px); n = B * N + 2 * PAD
    q = dict(bbox=','.join('%.3f' % v for v in b), bboxSR=3857, imageSR=3857, size='%d,%d' % (n, n), format='lerc',
             compressionTolerance=LERC_TOL, pixelType='F32', interpolation=INTERP, f='image')
    if lock: q['mosaicRule'] = '{"mosaicMethod":"esriMosaicLockRaster","lockRasterIds":[%d]}' % lock
    req = urllib.request.Request(SRC + '?' + urllib.parse.urlencode(q), headers={'User-Agent': 'bluishvoid.com bathymetry bake'})
    raw = urllib.request.urlopen(req, timeout=180).read()
    if not raw.startswith(b'CntZImage'): raise IOError('not LERC: %r' % raw[:120])
    a = imagecodecs.lerc_decode(raw)
    if isinstance(a, tuple): a = a[0]
    a = np.asarray(a, np.float32)
    if a.shape != (n, n): raise IOError('shape %r' % (a.shape,))
    a = a.copy(); a[(a < -1e5) | (a > 1e5)] = np.nan
    return a

def water_mask(z, x, y):
    """our basemap's water polygons for this tile (z14 data overzoomed past 14), rasterised at N px"""
    zz = min(z, 14); k = 2 ** (z - zz); px, py = x // k, y // k
    req = urllib.request.Request(MVT.format(z=zz, x=px, y=py), headers={'Origin': 'https://bluishvoid.com', 'User-Agent': 'bluish-bathy-bake'})
    try: raw = urllib.request.urlopen(req, timeout=60).read()
    except Exception: raw = b''
    im = Image.new('L', (N * k, N * k), 0)
    if raw:
        t = mvt.decode(raw)
        ext = 4096; sc = N * k / ext; d = ImageDraw.Draw(im)
        for f in t.get('water', {}).get('features', []):
            g = f['geometry']
            if g['type'] not in ('Polygon', 'MultiPolygon'): continue
            polys = [g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']
            for poly in polys:
                for i, ring in enumerate(poly):
                    pts = [(p[0] * sc, (ext - p[1]) * sc) for p in ring]   # MVT y is flipped by the decoder
                    if len(pts) > 2: d.polygon(pts, fill=255 if i == 0 else 0)
    if k > 1:   # crop the sub-tile out of the parent's mask
        ox, oy = (x - px * k) * N, (y - py * k) * N
        im = im.crop((ox, oy, ox + N, oy + N))
    return np.asarray(im) > 127

# depth (m, positive down) -> colour; shallow light, deep dark, in the site's navy (no purple)
# 200 m and deeper sits on the basemap's own water (#13294a) so where the shelf tiles stop nothing shows
STOPS = [(0, (42, 92, 134)), (2, (36, 82, 124)), (5, (31, 72, 112)), (10, (27, 63, 102)), (20, (24, 55, 92)),
         (50, (21, 48, 83)), (100, (20, 44, 78)), (200, (19, 41, 74)), (1000, (17, 37, 68)), (4000, (14, 31, 60))]
def ramp(d):
    ds = np.array([s[0] for s in STOPS], float); cs = np.array([s[1] for s in STOPS], float)
    ld = np.log1p(np.clip(d, 0, 6000)); lds = np.log1p(ds)
    return np.stack([np.interp(ld, lds, cs[:, c]) for c in range(3)], -1)

ISO = [2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 3000]

# THE FLOOR'S SHAPE (v2, 2026-10-19, user: the bathymetry read "nearly flat" and, now over the whole Gulf, hid the seafloor
# relief below it). The same multidirectional hillshade as the land and seafloor relief (_reliefbake/render.py shade()),
# from this layer's own DEM: the depth ramp darkens toward black in shadow and lifts toward a pale blue on sunlit flanks,
# exaggerated more as the zoom falls. From z5 to z8 the page draws the coarser seafloor relief ABOVE this layer, so the shading
# here is held back there (STRENGTH) and does not double up; from z9 in it is this layer's job alone. Pilot: bv2w/pilot.py.
P = dict(e0=2.6, k=1.35, emin=2.0, emax=12.0, lit=0.42, dark=0.70, Ls=0.18, Ds=0.32, sig=0.8)
SIGZ = {11: 1.8, 12: 2.4, 13: 3.0}                     # x sig: the smoothing grows with the zoom (PAD 8 > 3 sigma)
STRENGTH = {5: 0.45, 6: 0.45, 7: 0.5, 8: 0.7}
LIT = np.array([168, 204, 238], np.float32); DARK = np.array([2, 6, 18], np.float32)
def exaggeration(z, p=None):
    p = p or P; return float(np.clip(p['e0'] * p['k'] ** (12 - z), p['emin'], p['emax']))

# THE SURVEY-PATCH EDGES (v2.1, 2026-10-20). The Coastal Relief Model is itself a mosaic of surveys, and where a better one
# sits inside a coarser one the floor steps by a few metres along the patch's edge -- a straight line exactly along the tile
# axes (its box is in lat/lon, which mercator keeps straight). v1's flat light hid them; v2's hillshade drew the rectangles
# (the Louisiana shelf at z9: 8-10 m over 3-4 px, ~200 px long). NOAA's service will not blend the mosaic (mosaicOperator is
# fixed at First), and its catalog footprints do not show them (one CRM raster covers the tile), so they are found here: an
# UNBROKEN straight run (>= L px) of slope anomaly that the parallel lines 10-20 px away do not share, joined across gaps and
# followed while it stays above the background. There the slope is replaced by the median across the line. Measured on
# 9/125/214: 98% of the rectangle's top edge caught, 2.7% of the tile touched; Hudson Canyon's near-vertical wall, 0.27%.
# A wider net (no unbroken-run test) took 40-46% of the tile and flattened the salt domes; an FFT notch on the axes rang.
def deseam(g, axis, L=61, ratio=3.0, pct=85, win=15, grow=4, gap=41, pct_follow=75, follow=200, offs=(10, 15, 20)):
    """g: one (smoothed) slope component; axis=1 -> gx, seams are columns; axis=0 -> gy, rows."""
    from scipy.ndimage import median_filter, uniform_filter, maximum_filter, minimum_filter
    across, along = ((1, win), (L, 1)) if axis == 1 else ((win, 1), (1, L))
    thin = (1, 3) if axis == 1 else (3, 1)
    base = median_filter(g, size=across, mode='nearest')
    s = uniform_filter(np.abs(g - base), thin, mode='nearest')                    # 3 px across: the edge is 3-4 px wide
    run = maximum_filter(minimum_filter(s, along, mode='nearest'), along, mode='nearest')   # opening: runs >= L survive
    mean = uniform_filter(s, along, mode='nearest')
    nb = [np.roll(mean, (0, sg * o) if axis == 1 else (sg * o, 0), axis=(0, 1)) for o in offs for sg in (-1, 1)]
    ref = np.median(np.stack(nb), axis=0) + 1e-9
    m = (run / ref > ratio) & (run > np.percentile(s, pct))
    gl = (gap, 1) if axis == 1 else (1, gap)
    m = minimum_filter(maximum_filter(m, gl, mode='nearest'), gl, mode='nearest')
    weak = s > np.percentile(s, pct_follow); ax = 0 if axis == 1 else 1
    for _ in range(follow):
        grown = m | ((np.roll(m, 1, ax) | np.roll(m, -1, ax)) & weak)
        if (grown == m).all(): break
        m = grown
    m = maximum_filter(m, size=(1, 2 * grow + 1) if axis == 1 else (2 * grow + 1, 1))
    return np.where(m, base, g)

def shade_block(A, z, bx, by, B, p=None):
    """A: padded DEM block. Returns (lit alpha, dark alpha) for the unpadded block, 0..1"""
    from scipy.ndimage import gaussian_filter
    p = p or P
    Z = np.where(np.isfinite(A), np.minimum(A, 0.0), 0.0).astype(np.float64)   # land flattened to the shore: no cliff at the coast
    sig = p['sig'] * SIGZ.get(z, 1.0)                                          # survey ripple, LERC steps and the 90 m Coastal Relief
    if sig > 0: Z = gaussian_filter(Z, sig, mode='nearest')                    # Model's pixel steps (blocky from z11), not landforms
    b = block_bounds(z, bx, by, B); px = (b[2] - b[0]) / (B * N); n = A.shape[0]
    ym = b[3] + PAD * px - (np.arange(n) + 0.5) * px                            # each row's mercator y: ground metres per row,
    ground = px * np.cos(np.arctan(np.sinh(ym / R)))[:, None]                   # so a tile's top and bottom match its neighbours
    gy, gx = np.gradient(Z); ex = exaggeration(z, p)
    gx, gy = deseam(gx, 1), deseam(gy, 0)                                       # v2.1: the survey-patch edges (see deseam)
    gx = gx / ground * ex; gy = gy / ground * ex
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy); alt = math.radians(45)
    hs = 0.0; ws = 0.0
    for az, w in ((315, .5), (270, .2), (360, .2), (225, .1)):
        a = math.radians(az); hs = hs + w * (math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(a - aspect)); ws += w
    d = (hs / ws - math.sin(alt))[PAD:-PAD, PAD:-PAD]
    st = STRENGTH.get(z, 1.0)
    a_lit = st * p['lit'] * np.clip(d / p['Ls'], 0, 1) ** 0.85
    a_dark = st * p['dark'] * np.clip(-d / p['Ds'], 0, 1) ** 0.8
    return a_lit, a_dark

def render_block(z, bx, by, B=1, want=None, p=None):
    """{(x, y): (image or None, shelf)} for the block's tiles (only those in want, when given)"""
    A = fetch_dem(z, bx, by, B)
    tiles = [(bx * B + i, by * B + j) for i in range(B) for j in range(B)]
    if want is not None: tiles = [t for t in tiles if t in want]
    W = np.zeros((B * N, B * N), bool)
    for (x, y) in tiles:
        i, j = x - bx * B, y - by * B; W[j * N:(j + 1) * N, i * N:(i + 1) * N] = water_mask(z, x, y)
    near0 = lambda v: ~np.isfinite(v) | (np.abs(v) < 0.06)       # a hole is exactly 0 m; LERC keeps it within its 5 cm
    hole = np.zeros(A.shape, bool); hole[PAD:-PAD, PAD:-PAD] = W
    hole &= near0(A)
    if z <= 9 and hole.sum() >= 20:                     # only wide tiles reach the 100-raster limit; one exact 0 is not a hole
        E = fetch_dem(z, bx, by, B, lock=ETOPO_BED)
        g = np.zeros(A.shape, bool); g[PAD:-PAD, PAD:-PAD] = True
        fill = near0(A) & np.isfinite(E) & ~(g & ~hole)   # the holes, and the pad ring for the hillshade
        A = np.where(fill, E, A)
    a_lit, a_dark = shade_block(A, z, bx, by, B, p)
    DP = np.clip(-np.where(np.isfinite(A), A, 0), 0, None)
    out = {}
    for (x, y) in tiles:
        i, j = x - bx * B, y - by * B
        sl = (slice(j * N, (j + 1) * N), slice(i * N, (i + 1) * N))
        a = A[PAD:-PAD, PAD:-PAD][sl]; w = W[sl]
        depth = -a
        ok = w & np.isfinite(depth) & (depth > 0.05)        # only water the model says has a floor below the surface (inland lakes read their surface)
        lon0, lat0, lon1, lat1 = tile_lonlat(z, x, y)
        # the Salton Sea's surface is -69 m: its pixels are dropped. (Until 2026-10-19 this returned the WHOLE tile empty, so the z5
        # tile holding it, 5/5/12, came back empty and nothing under it was ever baked: no bathymetry on the California coast from
        # 32 to 41 N at any zoom, and a hard tone edge off northern California where the neighbouring tiles' depth ramp stopped.)
        if lon1 > -116.2 and lon0 < -115.4 and lat1 > 32.9 and lat0 < 33.6:
            n = 2 ** z; plon = lon0 + (np.arange(N) + 0.5) / N * (lon1 - lon0)
            plat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + (np.arange(N) + 0.5) / N) / n))))
            ok &= ~(((plat > 32.9) & (plat < 33.6))[:, None] & ((plon > -116.2) & (plon < -115.4))[None, :])
        if ok.sum() < 20: out[(x, y)] = (None, False); continue
        shelf = bool((depth[ok] < 200).any())
        rgb = ramp(np.where(ok, np.clip(depth, 0, None), 0))
        al, ad = a_lit[sl][..., None], a_dark[sl][..., None]
        rgb = rgb * (1 - ad) + DARK * ad
        rgb = rgb * (1 - al) + LIT * al
        # isobaths: thin lighter lines where the depth crosses a contour
        r0, c0 = PAD + j * N, PAD + i * N
        for lv in ISO:
            Bm = DP >= lv
            cur = Bm[r0:r0 + N, c0:c0 + N]
            edge = (cur ^ Bm[r0 - 1:r0 - 1 + N, c0:c0 + N]) | (cur ^ Bm[r0:r0 + N, c0 - 1:c0 - 1 + N])
            edge = ok & edge
            rgb[edge] = rgb[edge] * 0.62 + np.array([110, 160, 205]) * 0.38
        alpha = np.where(ok, 255, 0).astype(np.uint8)
        im = Image.fromarray(np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha]), 'RGBA')
        # soften the shoreline by one pixel so the mask edge is not a stair
        im.putalpha(im.getchannel('A').filter(ImageFilter.GaussianBlur(0.8)))
        out[(x, y)] = (im.resize((256, 256), Image.LANCZOS), shelf)
    return out

def block_size(z):
    return 4 if z >= 13 else 2 if z == 12 else 1

def render(z, x, y, want_shelf=False, p=None):
    im, shelf = render_block(z, x, y, 1, None, p)[(x, y)]
    return (im, shelf) if want_shelf else im

if __name__ == '__main__':
    z, x, y, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    im = render(z, x, y)
    if im is None: print('no water'); sys.exit(0)
    im.save(out, 'WEBP', quality=82, method=6); print('ok', out)
