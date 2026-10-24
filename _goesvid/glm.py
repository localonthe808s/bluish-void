"""GLM LIGHTNING OVER OUR GEOCOLOR (2026-10-23, user: "add GLM lightning too").

NESDIS's GLM picture (EXTENT3) is flash-extent density drawn over its GeoColor -- with its state lines in it. NOAA publishes
the lightning itself as data: GLM-L2-LCFA on the open-data bucket, one file every 20 s per satellite (~0.5 MB) listing every
flash with its centroid and the area it lit. So the lightning loop is our own GeoColor frame (cut clean from the full disk,
bake.py) with the flashes of the 10 minutes that full disk took to scan drawn over it:

  each flash a soft disk the size of the area it lit (radius sqrt(area / pi)), summed into a flash density, then coloured
  like NESDIS's legend -- dim orange for one flash, through amber and yellow to white where they pile up.

Frames sit on the same sector crops as every other loop (fdgeo.py), so /satmaps overlays fit them unchanged.
"""
import math, re, time, urllib.request
import numpy as np
import fdgeo

BUCKET = {'GOES19': 'noaa-goes19', 'GOES18': 'noaa-goes18'}
UA = {'User-Agent': 'bluishvoid.com satellite loop bake'}
KEYRE = re.compile(r'OR_GLM-L2-LCFA_G\d\d_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})\d_e\d+_c\d+\.nc')
WINDOW_S = 600


def get(url, timeout=60):
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception:
            if i == 2: raise
            time.sleep(2)


def stamp_s(stamp):
    """'YYYYDDDHHMM' -> unix seconds (UTC)"""
    y, d, h, m = int(stamp[:4]), int(stamp[4:7]), int(stamp[7:9]), int(stamp[9:11])
    return int(time.mktime((y, 1, 1, 0, 0, 0, 0, 0, 0)) - time.timezone) + (d - 1) * 86400 + h * 3600 + m * 60


def files(sat, t0, t1):
    """{key: start unix s} for LCFA files starting in [t0, t1)"""
    out = {}
    hrs = sorted({time.gmtime(t)[:4] for t in range(int(t0) - 3600, int(t1) + 3600, 1800)})
    for (Y, Mo, D, H) in hrs:
        yd = time.gmtime(time.mktime((Y, Mo, D, H, 0, 0, 0, 0, 0)) - time.timezone).tm_yday
        prefix = 'GLM-L2-LCFA/%04d/%03d/%02d/' % (Y, yd, H)
        tok = None
        while True:
            q = 'https://%s.s3.amazonaws.com/?list-type=2&prefix=%s%s' % (BUCKET[sat], prefix, '&continuation-token=' + urllib.request.quote(tok) if tok else '')
            x = get(q, 30).decode()
            for k in re.findall(r'<Key>([^<]+)</Key>', x):
                m = KEYRE.search(k)
                if not m: continue
                ts = int(time.mktime((int(m.group(1)), 1, 1, 0, 0, 0, 0, 0, 0)) - time.timezone) + (int(m.group(2)) - 1) * 86400 \
                     + int(m.group(3)) * 3600 + int(m.group(4)) * 60 + int(m.group(5))
                if t0 <= ts < t1: out[k] = ts
            m2 = re.search(r'<NextContinuationToken>([^<]+)</NextContinuationToken>', x)
            if not m2: break
            tok = m2.group(1)
    return out


def read(job):
    """one LCFA file -> (lat, lon, area m2) arrays. Run in a process: netCDF4 is not thread-safe."""
    import netCDF4
    sat, key = job
    try:
        d = netCDF4.Dataset('mem', memory=get('https://%s.s3.amazonaws.com/%s' % (BUCKET[sat], key)))
        r = tuple(np.ma.filled(d[v][:].astype(np.float32), np.nan) for v in ('flash_lat', 'flash_lon', 'flash_area'))
        d.close()
        return r
    except Exception:
        return None


# colour by flash density (flashes covering a pixel in the 10 min): NESDIS's legend, dim orange -> amber -> yellow -> white
_STOPS = [(0.0, (90, 51, 0, 0)), (1.0, (190, 80, 10, 140)), (3.0, (255, 130, 0, 200)), (10.0, (255, 190, 30, 230)),
          (30.0, (255, 240, 150, 248)), (80.0, (255, 255, 255, 255))]
# (an active cluster puts ~10,000 flashes in 10 minutes into one sector: the scale runs to 80 so only the cores go white)


def colour(dens):
    xs = [s[0] for s in _STOPS]
    out = np.zeros(dens.shape + (4,), np.float32)
    for c in range(4):
        out[..., c] = np.interp(dens, xs, [s[1][c] for s in _STOPS])
    out[dens < 0.3] = 0
    return out.astype(np.uint8)


def density(sat, sector, lat, lon, area):
    """flash-extent density on the sector's OUT_W x OUT_H frame"""
    W, H = fdgeo.OUT_W, fdgeo.OUT_H
    l, t, r, b = fdgeo.crop(sat, sector)
    w0, e0, s0, n0 = fdgeo.SECTORS[(sat, sector)]
    pad = max(e0 - w0, n0 - s0) * 0.3
    lo = ((lon - w0 + 180) % 360) - 180 + w0
    m = np.isfinite(lat) & (lat > s0 - pad) & (lat < n0 + pad) & (lo > w0 - pad) & (lo < e0 + pad)
    dens = np.zeros((H, W), np.float32)
    kmpx = (r - l) / W                 # ~km per output pixel (1 km per 10848-grid pixel near nadir)
    for la, lg, ar in zip(lat[m], lo[m], area[m]):
        p = fdgeo.to_out(float(la), float(lg), sat, sector)
        if p is None: continue
        rad = max(1.2, 0.6 * math.sqrt(max(float(ar), 1e6) / math.pi) / 1000.0 / kmpx)   # 0.6: the lit area is the cloud's glow, wider than the channel
        R = int(rad * 1.6) + 1
        x0, y0 = int(p[0]), int(p[1])
        if x0 + R < 0 or y0 + R < 0 or x0 - R >= W or y0 - R >= H: continue
        ys = np.arange(max(0, y0 - R), min(H, y0 + R + 1)); xs = np.arange(max(0, x0 - R), min(W, x0 + R + 1))
        dy = (ys[:, None] - p[1]) / rad; dx = (xs[None, :] - p[0]) / rad
        dens[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1] += np.clip(1.25 - (dx * dx + dy * dy), 0, 1)   # a soft-edged disk, 1 inside
    return dens


def composite(base_path, out_path, sat, sector, lat, lon, area):
    from PIL import Image, ImageFilter
    base = Image.open(base_path).convert('RGB')
    dens = density(sat, sector, lat, lon, area)
    ov = Image.fromarray(colour(dens), 'RGBA')
    glow = ov.filter(ImageFilter.GaussianBlur(2.5))
    glow.putalpha(glow.getchannel('A').point(lambda a: a * 0.55))
    img = base.convert('RGBA')
    img.alpha_composite(glow); img.alpha_composite(ov)
    img.convert('RGB').save(out_path, quality=90)
    return int((dens > 0.5).sum())
