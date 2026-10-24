"""EAST + WEST AS ONE VIEW (2026-10-24, user: "can we merge goes west and east at the largest" ... "dont frame it, it should launch
at its normal view and then be able to zoom all the way out").

The outermost loop of LIVE CLOUDS, between CONTINENTAL and the EARTH NOW globe. It is drawn as if from an imaginary
geostationary satellite at 106 W ('GOESV' in fdgeo.py, on the same fixed grid as the real ones, so the page zooms across it
like any other loop): every output pixel is turned back into a latitude / longitude, looked up in both real full disks
(GOES-19 at 75 W, GOES-18 at 137 W), and the two are mixed by how squarely each satellite sees that point -- the cosine of its
viewing angle, feathered, so each side comes from the satellite looking down on it and the seam runs where both look equally
well (previewed 2026-10-24 19:40 UTC: no doubled clouds or colour step over the Rockies and Plains).

Each satellite's picture gets its own night blend (nightblend.py) BEFORE the mix, from its own infrared, so the night side reads
exactly like the regional loops it hands over to. The 5424 px full disks (2 km) are plenty: the frame is ~13 km a pixel.
"""
import io, math, re
import numpy as np
import fdgeo, rawbands, nightblend

SAT = 'GOESV'
SECTOR = 'na'
REAL = ('GOES19', 'GOES18')
SIZE = 5424
_GEOM = {}


def _fwd(lat, lon, lon0):
    """lat / lon (deg, arrays) -> scan angles x, y (rad) and cos of the satellite's viewing angle there (0 past the limb)"""
    REQ, RPOL, H = fdgeo.REQ, fdgeo.RPOL, fdgeo.H
    p = np.radians(lat); l = np.radians(((lon - lon0 + 180) % 360) - 180)
    pc = np.arctan((RPOL ** 2 / REQ ** 2) * np.tan(p)); rc = RPOL / np.sqrt(1 - fdgeo.E2 * np.cos(pc) ** 2)
    sx = H - rc * np.cos(pc) * np.cos(l); sy = -rc * np.cos(pc) * np.sin(l); sz = rc * np.sin(pc)
    vis = H * (H - sx) >= sy * sy + (REQ ** 2 / RPOL ** 2) * sz * sz
    x = np.arcsin(-sy / np.sqrt(sx * sx + sy * sy + sz * sz)); y = np.arctan(sz / sx)
    gx, gy, gz = rc * np.cos(pc) * np.cos(l), rc * np.cos(pc) * np.sin(l), rc * np.sin(pc)
    vx, vy, vz = H - gx, -gy, -gz
    cz = (gx * vx + gy * vy + gz * vz) / (np.sqrt(gx * gx + gy * gy + gz * gz) * np.sqrt(vx * vx + vy * vy + vz * vz))
    bad = ~vis | ~np.isfinite(lat)
    x[bad] = np.nan; y[bad] = np.nan; cz[bad] = 0
    return x, y, cz


def geometry():
    """per output pixel: lat / lon, and for each real satellite its 5424-disk pixel (col, row) and blend weight"""
    if _GEOM: return _GEOM
    lat, lon = nightblend.latlon(SAT, SECTOR)
    _GEOM['lat'], _GEOM['lon'] = lat, lon
    for s in REAL:
        x, y, cz = _fwd(lat.astype(np.float64), lon.astype(np.float64), fdgeo.LON0[s])
        col = ((x - fdgeo.X0) / fdgeo.D) * SIZE / fdgeo.N - 0.5; row = ((fdgeo.Y0 - y) / fdgeo.D) * SIZE / fdgeo.N - 0.5
        ok = np.isfinite(col)
        _GEOM[s] = {'x': np.where(ok, x, np.nan), 'y': np.where(ok, y, np.nan),
                    'mx': np.where(ok, col, -1).astype(np.float32), 'my': np.where(ok, row, -1).astype(np.float32),
                    'w': (np.clip((cz - 0.15) / 0.5, 0, 1) ** 2 * ok).astype(np.float32)}
    return _GEOM


def _sample2d(arr, x0, dx, y0, dy, xs, ys):
    """bilinear on a Level 2 array at arbitrary scan angles (2-D), NaN outside"""
    import cv2
    mx = ((xs - x0) / dx).astype(np.float32); my = ((ys - y0) / dy).astype(np.float32)
    mx[~np.isfinite(mx)] = -1; my[~np.isfinite(my)] = -1
    return cv2.remap(np.nan_to_num(arr, nan=np.nan).astype(np.float32), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))


def build(job):
    """job = (stamp, out_path, {sat: full-disk jpg bytes}). Run in a process (netCDF4). Raises when a night side's infrared is
    not up yet, so the caller drops the frame and makes it again next run."""
    import cv2
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    stamp, out, disks = job
    G = geometry()
    night = nightblend.night_weight(SAT, SECTOR, stamp)
    acc = np.zeros(night.shape + (3,), np.float32); wsum = np.zeros(night.shape, np.float32)
    for s in REAL:
        im = np.asarray(Image.open(io.BytesIO(disks[s])).convert('RGB'))
        g = G[s]
        part = cv2.remap(im, g['mx'], g['my'], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0).astype(np.float32)
        nw = night * (g['w'] > 0)
        if nw.max() > 0:
            keys = nightblend.scan_keys(s, stamp)
            if not keys: raise RuntimeError('%s infrared not up yet' % s)
            ch = {}
            for c, k in keys.items():
                v, x0, dx, y0, dy = rawbands.read(s, k)
                ch[c] = _sample2d(v, x0, dx, y0, dy, g['x'], g['y'])
            part = nightblend.blend(part, ch['07'], ch['13'], ch['15'], nw)
        acc += part * g['w'][..., None]; wsum += g['w']
    outim = np.where(wsum[..., None] > 1e-4, acc / np.maximum(wsum, 1e-4)[..., None], 0)
    Image.fromarray(np.clip(outim, 0, 255).round().astype(np.uint8)).save(out, quality=92)
    return out
