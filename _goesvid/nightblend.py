"""GEOCOLOR'S NIGHT, SHARPENED WITH THE CLOUD-MICRO CHANNELS (2026-10-24, user: "how can we use geocolor and night cloud micro
together to get the most clarity out of night clouds and fog? we dont need night cloud micro during the day").

NOAA's GeoColor at night is city lights under one muted blue-gray low-cloud layer: thin ice cloud barely shows and valley fog
is faint. The Night Cloud Micro RGB sees both, from three infrared channels of the same scan (3.9, 10.3, 12.3 um). This keeps
GeoColor's lights and ground and redraws the clouds over them, from NOAA's own Level 2 files (the same open-data bucket as
rawbands.py):

  fog / low water cloud   10.3 - 3.9 um > ~0.4 K over warm tops: its own aqua-white, thin valley fog included
  thin ice cloud          10.3 - 3.9 um < ~-0.6 K (the 3.9 sees through ice to the warm ground): a silver veil, lights through it
  thick mid / high cloud  10.3 um from 268 K down to 222 K: gray to white, colder = whiter
  city lights             dim under any of them

Only on the night side: the weight follows GeoColor's own day/night switch (none with the sun 12 deg up, full by 2 deg up), so
daylight frames are untouched and there is no seam at sunrise. Previewed against GeoColor and Cloud Micro for 06:00 and 07:20
EDT 2026-10-24 over the Northeast before it went live.
"""
import math, re
import numpy as np
import fdgeo, rawbands

CH = ('07', '13', '15')
_LL = {}


def _ss(e0, e1, v):
    t = np.clip((v - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def latlon(sat, sector):
    """lat, lon of every output pixel's centre (inverse of the fixed-grid projection, GOES-R PUG 5.1.2.8)"""
    if (sat, sector) in _LL: return _LL[(sat, sector)]
    xs, ys = rawbands.sector_xy(sat, sector)
    x, y = np.meshgrid(xs, ys)
    req, rpol, H = fdgeo.REQ, fdgeo.RPOL, fdgeo.H
    a = np.sin(x) ** 2 + np.cos(x) ** 2 * (np.cos(y) ** 2 + (req ** 2 / rpol ** 2) * np.sin(y) ** 2)
    b = -2 * H * np.cos(x) * np.cos(y); c = H ** 2 - req ** 2
    disc = b * b - 4 * a * c
    rs = (-b - np.sqrt(np.maximum(disc, 0))) / (2 * a)
    sx = rs * np.cos(x) * np.cos(y); sy = -rs * np.sin(x); sz = rs * np.cos(x) * np.sin(y)
    lat = np.degrees(np.arctan((req ** 2 / rpol ** 2) * sz / np.sqrt((H - sx) ** 2 + sy ** 2)))
    lon = fdgeo.LON0[sat] - np.degrees(np.arctan(sy / (H - sx)))
    lat[disc < 0] = np.nan; lon[disc < 0] = np.nan                      # off the disk
    _LL[(sat, sector)] = (lat.astype(np.float32), lon.astype(np.float32))
    return _LL[(sat, sector)]


def night_weight(sat, sector, stamp):
    """0 in daylight .. 1 at night, per pixel, for a scan 'YYYYDDDHHMM'"""
    lat, lon = latlon(sat, sector)
    d, h, m = int(stamp[4:7]), int(stamp[7:9]), int(stamp[9:11])
    g = 2 * math.pi / 365 * (d - 1 + (h - 12) / 24)
    dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
           - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    ha = np.radians((h * 60 + m + eqt + 4 * lon) / 4 - 180)
    la = np.radians(lat)
    cz = np.sin(la) * math.sin(dec) + np.cos(la) * math.cos(dec) * np.cos(ha)
    return np.nan_to_num(_ss(0.21, 0.035, cz), nan=0.0).astype(np.float32)


def blend(gc, c07, c13, c15, night):
    """gc: HxWx3 float GeoColor; channels in K (NaN off the disk); night 0..1 -> blended float image"""
    import cv2
    c13 = np.nan_to_num(c13, nan=300.0); c07 = np.nan_to_num(c07, nan=300.0)
    btd = cv2.GaussianBlur((c13 - c07).astype(np.float32), (0, 0), 1.0)   # + water cloud, - thin ice (3.9 um noise smoothed)
    fog = _ss(0.35, 2.8, btd) * _ss(250, 264, c13)
    cirr = _ss(-0.6, -3.5, btd) * _ss(285, 255, c13)
    cold = _ss(268, 222, c13)
    out = gc * (1 - 0.8 * np.maximum(np.maximum(fog, cold), 0.6 * cirr))[..., None]
    a = (0.9 * fog)[..., None]
    out = out * (1 - a) + np.array([186, 236, 238], np.float32) * (0.5 + 0.5 * fog[..., None]) * a
    a = (0.55 * cirr)[..., None]
    out = out * (1 - a) + np.array([214, 220, 230], np.float32) * a
    hv = 160 + 95 * cold; a = (0.94 * cold ** 0.8)[..., None]
    out = out * (1 - a) + np.dstack([hv, hv, hv * 1.02]) * a
    w = night[..., None]
    return gc * (1 - w) + out * w


def scan_keys(sat, stamp):
    """{channel: key} of the full-disk Level 2 files for one scan, or {} while any is missing"""
    prefix = 'ABI-L2-CMIPF/%s/%s/%s/' % (stamp[:4], stamp[4:7], stamp[7:9])
    x = rawbands.get('https://%s.s3.amazonaws.com/?list-type=2&prefix=%s' % (rawbands.BUCKET[sat], prefix), 30).decode()
    keys = {}
    for k in re.findall(r'<Key>([^<]+)</Key>', x):
        m = rawbands.KEYRE.search(k)
        if m and m.group(2) in CH and ''.join(m.group(3, 4, 5, 6)) == stamp: keys[m.group(2)] = k
    return keys if all(c in keys for c in CH) else {}


def blend_scene(job):
    """job = (sat, stamp, [(sector, jpg path)]): blends every frame of one scan in place. Run in a process (netCDF4).
    Raises when the scan's infrared files are not up yet, so the caller can drop the frames and cut them again next run."""
    from PIL import Image
    sat, stamp, outs = job
    keys = scan_keys(sat, stamp)
    if not keys: raise RuntimeError('infrared not up yet')
    data = {c: rawbands.read(sat, k) for c, k in keys.items()}
    for sector, path in outs:
        night = night_weight(sat, sector, stamp)
        if night.max() <= 0: continue
        xs, ys = rawbands.sector_xy(sat, sector)
        ch = {c: rawbands.sample(v, x0, dx, y0, dy, xs, ys) for c, (v, x0, dx, y0, dy) in data.items()}
        gc = np.asarray(Image.open(path).convert('RGB'), np.float32)
        Image.fromarray(np.clip(blend(gc, ch['07'], ch['13'], ch['15'], night), 0, 255).round().astype(np.uint8)).save(path, quality=92)
    return len(outs)
