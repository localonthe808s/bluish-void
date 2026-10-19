#!/usr/bin/env python3
"""National coastal + Great Lakes + tidal-river bathymetry tiles (user 2026-10-16: "add coastal and river bathymetry to the
national map, bake it in to a high detail").

Per web-mercator tile: NOAA NCEI DEM_all (CUDEM 1/9" where it exists, else the Coastal Relief Models; Great Lakes included)
pulled for the tile's own box at 512 px, masked to WATER by our own basemap's water polygons for the same tile (so land below
sea level -- New Orleans behind its levees -- is never painted as sea), colored by depth in the site's navy family with a
soft hillshade and faint isobaths. Inland rivers have no depth in this source (Memphis/St. Louis read the water SURFACE).
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

PAD = 2
# THE MOSAIC'S HOLES (2026-10-19). DEM_all mosaics at most 100 rasters per request (maxMosaicImageCount) and puts its global
# background, ETOPO 2022, last. A wide tile over a coast dense with surveys (the Louisiana shelf at z6, Florida's at z5-8)
# touches more than 100, ETOPO is dropped, and the pixels no surviving raster covers come back as exactly 0 m -- not NaN.
# Those read as dry, so the bake left them clear: rectangles of the basemap's lighter water inside the depth ramp. They are
# filled from ETOPO 2022 15" bed elevation, the mosaic's own background, asked for alone (lock raster) over the same box.
ETOPO_BED = 2530
def fetch_dem(z, x, y, lock=None):
    b = tile_bounds(z, x, y); px = (b[2] - b[0]) / N
    b = (b[0] - PAD * px, b[1] - PAD * px, b[2] + PAD * px, b[3] + PAD * px)
    q = dict(bbox=','.join('%.3f' % v for v in b), bboxSR=3857, imageSR=3857, size='%d,%d' % (N + 2 * PAD, N + 2 * PAD), format='tiff',
             pixelType='F32', interpolation='RSP_BilinearInterpolation', f='image')
    if lock: q['mosaicRule'] = '{"mosaicMethod":"esriMosaicLockRaster","lockRasterIds":[%d]}' % lock
    raw = urllib.request.urlopen(SRC + '?' + urllib.parse.urlencode(q), timeout=120).read()
    a = tifffile.imread(io.BytesIO(raw)).astype(np.float32)
    a[(a < -1e5) | (a > 1e5)] = np.nan
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

def render(z, x, y, want_shelf=False):
    A = fetch_dem(z, x, y)
    w = water_mask(z, x, y)
    hole = np.zeros(A.shape, bool); hole[PAD:-PAD, PAD:-PAD] = w
    hole &= ~np.isfinite(A) | (np.abs(A) < 1e-3)
    if z <= 9 and hole.sum() >= 20:                     # only wide tiles reach the 100-raster limit; one exact 0 is not a hole
        E = fetch_dem(z, x, y, lock=ETOPO_BED)
        g = np.zeros(A.shape, bool); g[PAD:-PAD, PAD:-PAD] = True
        fill = (~np.isfinite(A) | (np.abs(A) < 1e-3)) & np.isfinite(E) & ~(g & ~hole)   # the holes, and the pad ring for the hillshade
        A = np.where(fill, E, A)
    a = A[PAD:-PAD, PAD:-PAD]
    depth = -a
    ok = w & np.isfinite(depth) & (depth > 0.05)        # only water the model says has a floor below the surface (inland lakes read their surface)
    lon0, lat0, lon1, lat1 = tile_lonlat(z, x, y)
    if lon1 > -116.2 and lon0 < -115.4 and lat1 > 32.9 and lat0 < 33.6: return (None, False) if want_shelf else None   # the Salton Sea's surface is -69 m
    if ok.sum() < 20: return (None, False) if want_shelf else None
    shelf = bool((depth[ok] < 200).any())
    d = np.where(ok, np.clip(depth, 0, None), 0)
    rgb = ramp(d)
    # hillshade of the floor (sun NW, 40 deg), exaggerated by zoom so shelves still read
    mpp = 2 * math.pi * R / (2 ** z) / N
    zf = np.where(np.isfinite(A), A, 0).astype(float)
    gy, gx = np.gradient(zf, mpp); gy, gx = gy[PAD:-PAD, PAD:-PAD], gx[PAD:-PAD, PAD:-PAD]
    ex = 6.0 if z < 10 else 3.0
    slope = np.arctan(ex * np.hypot(gx, gy)); asp = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(40)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - asp)
    rgb = rgb * (0.78 + 0.32 * np.clip(hs, 0, 1))[..., None]
    # isobaths: thin lighter lines where the depth crosses a contour
    DP = np.clip(-np.where(np.isfinite(A), A, 0), 0, None)
    for lv in ISO:
        B = DP >= lv
        edge = (B[PAD:-PAD, PAD:-PAD] ^ B[PAD - 1:-PAD - 1, PAD:-PAD]) | (B[PAD:-PAD, PAD:-PAD] ^ B[PAD:-PAD, PAD - 1:-PAD - 1])
        edge = ok & edge
        rgb[edge] = rgb[edge] * 0.62 + np.array([110, 160, 205]) * 0.38
    alpha = np.where(ok, 255, 0).astype(np.uint8)
    im = Image.fromarray(np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha]), 'RGBA')
    # soften the shoreline by one pixel so the mask edge is not a stair
    al = im.getchannel('A').filter(ImageFilter.GaussianBlur(0.8)); im.putalpha(al)
    im = im.resize((256, 256), Image.LANCZOS)
    return (im, shelf) if want_shelf else im

if __name__ == '__main__':
    z, x, y, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    im = render(z, x, y)
    if im is None: print('no water'); sys.exit(0)
    im.save(out, 'WEBP', quality=82, method=6); print('ok', out)
