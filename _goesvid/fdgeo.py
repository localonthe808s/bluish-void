"""WHERE A PLACE LANDS ON NOAA'S FULL-DISK PICTURE, and the sector crops cut from it (2026-10-23).

The LIVE CLOUDS loop used NESDIS's sector JPGs, which carry NESDIS's own white state lines in the pixels. Their full-disk
GeoColor (cdn.star.nesdis.noaa.gov/<sat>/ABI/FD/GEOCOLOR/, 10848 px = 1 km at nadir, every 10 min) carries none, so the
sectors are cut from it here and our own map is drawn over them by the page from /satmaps/<sat>-<sector>.png, baked from
the SAME crop rectangles by satmaps_bake.py. Both import this module, so the lines cannot drift from the imagery.

The full disk is the ABI fixed grid: scan angles x, y in radians, pixel centres 28 urad apart, 10848 across, centred on
the satellite's sub-point (GOES-R PUG vol 4, 5.1.2.8). Verified against the coastline in a clear daytime frame (see
FIT below); a 5424 or 1808 copy is the same grid at 2x / 6x the spacing.
"""
import math

REQ, RPOL, H = 6378137.0, 6356752.31414, 42164160.0
E2 = 0.0066943800229
LON0 = {'GOES19': -75.0, 'GOES18': -137.0, 'GOESV': -106.0}   # the grid's own reference (goes_imager_projection in NOAA's files), not the -75.2 the craft sits at
N = 10848
D = 0.000028                             # 28 urad: the 10848 grid's pixel spacing
X0 = -0.151872                           # left EDGE of the full disk (pixel 0's left side), radians
Y0 = 0.151872                            # top edge
FIT = {'GOES19': (0.0, 0.0), 'GOES18': (0.0, 0.0), 'GOESV': (0.0, 0.0)}   # (dx, dy) in 10848 px: coastline fit on clear daytime disks 10-23, 0 for both once LON0 is the grid's own -75.0 (with -75.2 it read a uniform -16 px)


def geos(lat, lon, sat):
    """scan angles (x, y) of a lat/lon seen from the satellite, or None past the limb"""
    p = math.radians(lat); l = math.radians(((lon - LON0[sat] + 180) % 360) - 180)
    pc = math.atan((RPOL ** 2 / REQ ** 2) * math.tan(p))
    rc = RPOL / math.sqrt(1 - E2 * math.cos(pc) ** 2)
    sx = H - rc * math.cos(pc) * math.cos(l)
    sy = -rc * math.cos(pc) * math.sin(l)
    sz = rc * math.sin(pc)
    if H * (H - sx) < sy * sy + (REQ ** 2 / RPOL ** 2) * sz * sz:
        return None
    return math.asin(-sy / math.sqrt(sx * sx + sy * sy + sz * sz)), math.atan(sz / sx)


def px(lat, lon, sat, n=N):
    """pixel (col, row) on an n x n copy of the full disk; None past the limb"""
    r = geos(lat, lon, sat)
    if r is None: return None
    s = n / N
    return ((r[0] - X0) / D + FIT[sat][0]) * s, ((Y0 - r[1]) / D + FIT[sat][1]) * s


# THE SECTORS: the ones index.html's areaToGoes opens on, as lat/lon boxes close to what NESDIS's own sectors showed.
# Each is cut as the bounding rectangle of its box on the disk, widened to OUT_W x OUT_H's shape.
SECTORS = {
    ('GOES19', 'conus'): (-125.0, -66.0, 23.5, 50.5),   # CONTINENTAL (user 2026-10-24: "can you make a continental geocolor view?")
    ('GOES19', 'ne'):  (-84.0, -64.5, 36.0, 48.0),
    ('GOES19', 'se'):  (-92.0, -74.0, 24.0, 37.0),
    ('GOES19', 'cgl'): (-95.0, -77.0, 37.0, 49.0),
    ('GOES19', 'umv'): (-103.0, -85.0, 37.0, 49.5),
    ('GOES19', 'smv'): (-100.0, -83.0, 28.0, 40.0),
    ('GOES19', 'sp'):  (-109.0, -91.0, 25.0, 38.0),
    ('GOES19', 'nr'):  (-118.0, -100.0, 40.0, 49.5),
    ('GOES19', 'sr'):  (-117.0, -99.0, 31.0, 42.5),
    ('GOES19', 'eus'): (-100.0, -64.0, 24.0, 48.5),
    ('GOES19', 'taw'): (-90.0, -20.0, 5.0, 35.0),
    ('GOES19', 'pr'):  (-73.0, -59.0, 13.0, 22.5),
    ('GOES18', 'pnw'): (-131.0, -112.0, 40.0, 50.5),
    ('GOES18', 'psw'): (-127.0, -109.0, 30.0, 42.5),
    ('GOES18', 'np'):  (-180.0, -125.0, 40.0, 66.0),
    ('GOES18', 'ep'):  (-165.0, -110.0, 10.0, 35.0),
    # EAST + WEST (user 2026-10-24: "can we merge goes west and east at the largest" ... "zoom all the way out"): an imaginary
    # satellite halfway between them, at 106 W, on the same fixed grid -- every point drawn from whichever real one sees it more
    # squarely (mergedisk.py). Alaska and Hawaii lie past GOES-East's horizon, so no real satellite's own view can hold both.
    ('GOESV', 'na'):   (-178.0, -34.0, 0.0, 70.0),
}
OUT_W, OUT_H = 1600, 1000


_CROPS = {}


def crop(sat, sector, n=N):
    """(left, top, right, bottom) on an n x n disk, the sector box's bounding rect widened to OUT_W:OUT_H"""
    if (sat, sector, n) in _CROPS: return _CROPS[(sat, sector, n)]
    w, e, s, nn = SECTORS[(sat, sector)]
    pts = []
    for i in range(41):
        f = i / 40.0
        for la, lo in ((s + (nn - s) * f, w), (s + (nn - s) * f, e), (s, w + (e - w) * f), (nn, w + (e - w) * f)):
            p = px(la, lo, sat, n)
            if p: pts.append(p)
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    cx, cy, bw, bh = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
    a = OUT_W / OUT_H
    if bw / bh < a: bw = bh * a
    else: bh = bw / a
    _CROPS[(sat, sector, n)] = r = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
    return r


def to_out(lat, lon, sat, sector, scale=1.0):
    """a lat/lon's pixel on the sector's OUT_W x OUT_H frame (times scale), or None"""
    p = px(lat, lon, sat)
    if p is None: return None
    l, t, r, b = crop(sat, sector)
    return (p[0] - l) / (r - l) * OUT_W * scale, (p[1] - t) / (b - t) * OUT_H * scale
