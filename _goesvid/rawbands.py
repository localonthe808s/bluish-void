"""B13 AND AIR MASS FROM NOAA'S OWN DATA (2026-10-23, user: "add B13 and air mass").

NESDIS's full-disk pictures of these two bands carry its white (B13) and yellow (Air Mass) state lines in the pixels, so
unlike GeoColor they cannot be cut clean. They are rendered here instead, from the ABI Level 2 Cloud and Moisture Imagery on
NOAA's open-data bucket (noaa-goes19 / noaa-goes18 on AWS, keyless, built for bulk use): CONUS / PACUS every 5 minutes for
the sectors inside them, the full disk every 10 for the rest. The files land ~3 minutes after the scan, so these loops
are FRESHER than the NESDIS pictures were.

  B13      the 10.3 um brightness temperature through NESDIS's own colour table (fitted 10-23 from their 5424 px B13 full
           disk against the same scan's temperatures, 1 K steps: gray for warm ground, cyan -> blue -> green -> yellow ->
           red -> black for colder and colder cloud tops)
  AirMass  the standard RGB (EUMETSAT / CIRA): R = C08 - C10 over -26.2..0.6 K, G = C12 - C13 over -43.2..6.7 K,
           B = C08 over 243.9..208.5 K, no gamma

Frames are sampled onto the same sector crops as the GeoColor loop (fdgeo.py), so /satmaps overlays fit them unchanged.
"""
import io, os, re, time, urllib.request
import numpy as np
import fdgeo

BUCKET = {'GOES19': 'noaa-goes19', 'GOES18': 'noaa-goes18'}
CHANNELS = {'13': ['13'], 'AirMass': ['08', '10', '12', '13']}
UA = {'User-Agent': 'bluishvoid.com satellite loop bake'}
KEYRE = re.compile(r'OR_ABI-L2-CMIP([CF])-M\dC(\d\d)_G\d\d_s(\d{4})(\d{3})(\d{2})(\d{2})\d{3}_e\d+_c\d+\.nc')

# NESDIS's B13 table, K -> RGB, every 1 K where the fit had 200+ pixels; colder clamps to the first, warmer runs on to 330 K
_B13 = {192: (33, 19, 19), 193: (32, 4, 3), 194: (48, 1, 2), 195: (74, 2, 1), 196: (98, 1, 1), 197: (123, 1, 1), 
        198: (150, 1, 2), 199: (176, 2, 2), 200: (203, 2, 1), 201: (226, 4, 1), 202: (240, 12, 1), 203: (247, 32, 2), 
        204: (248, 56, 2), 205: (249, 82, 2), 206: (249, 106, 3), 207: (250, 133, 3), 208: (250, 158, 4), 
        209: (249, 183, 4), 210: (249, 210, 6), 211: (248, 233, 7), 212: (243, 250, 8), 213: (228, 253, 7), 
        214: (208, 254, 7), 215: (175, 253, 7), 216: (147, 253, 6), 217: (122, 253, 6), 218: (97, 252, 7), 
        219: (74, 252, 8), 220: (52, 250, 9), 221: (33, 247, 11), 222: (19, 238, 17), 223: (12, 218, 25), 
        224: (9, 192, 36), 225: (8, 163, 47), 226: (6, 135, 59), 227: (5, 108, 70), 228: (4, 83, 80), 
        229: (3, 59, 90), 230: (1, 41, 99), 231: (1, 30, 107), 232: (1, 30, 114), 233: (1, 40, 125), 
        234: (3, 55, 137), 235: (4, 72, 148), 236: (6, 91, 160), 237: (8, 110, 170), 238: (10, 129, 180), 
        239: (13, 144, 188), 240: (21, 156, 195), 241: (34, 180, 202), 242: (61, 193, 207), 243: (105, 196, 206), 
        244: (145, 192, 198), 245: (160, 190, 193), 246: (169, 187, 189), 247: (173, 185, 186), 248: (175, 184, 185), 
        249: (174, 180, 181), 250: (174, 178, 178), 251: (172, 176, 176), 252: (171, 173, 173), 253: (170, 172, 172), 
        254: (168, 170, 170), 255: (165, 167, 167), 256: (164, 165, 165), 257: (163, 164, 164), 258: (159, 160, 160), 
        259: (158, 158, 158), 260: (156, 156, 156), 261: (153, 153, 153), 262: (153, 153, 153), 263: (150, 151, 151), 
        264: (147, 147, 147), 265: (146, 146, 146), 266: (145, 145, 145), 267: (140, 140, 140), 268: (138, 138, 138), 
        269: (136, 136, 136), 270: (133, 133, 133), 271: (133, 133, 133), 272: (131, 131, 131), 273: (126, 126, 126), 
        274: (126, 126, 126), 275: (122, 122, 122), 276: (121, 121, 121), 277: (121, 121, 121), 278: (116, 116, 116), 
        279: (114, 114, 114), 280: (114, 114, 114), 281: (110, 110, 110), 282: (108, 108, 108), 283: (108, 108, 108), 
        284: (103, 103, 103), 285: (101, 101, 101), 286: (100, 100, 100), 287: (95, 95, 95), 288: (95, 95, 95), 
        289: (94, 94, 94), 290: (89, 89, 89), 291: (89, 89, 89), 292: (88, 88, 88), 293: (82, 82, 82), 
        294: (82, 82, 82), 295: (82, 82, 82), 296: (76, 76, 76), 297: (76, 76, 76), 298: (75, 75, 75), 
        299: (70, 70, 70), 330: (12, 12, 12)}


def _lut():
    ks = sorted(_B13)
    t = np.arange(150, 351)
    out = np.zeros((len(t), 3), np.uint8)
    for c in range(3):
        out[:, c] = np.interp(t, ks, [_B13[k][c] for k in ks]).round().astype(np.uint8)
    return t[0], out
LUT0, LUT = _lut()


def get(url, timeout=90):
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception:
            if i == 2: raise
            time.sleep(3)


def scenes(sat, prod, band, hours):
    """{stamp 'YYYYDDDHHMM': {channel: key}} for scans in the last `hours` that have every channel the band needs"""
    need = CHANNELS[band]
    out = {}
    now = time.time()
    for h in range(int(hours) + 2):
        t = time.gmtime(now - h * 3600)
        prefix = 'ABI-L2-CMIP%s/%04d/%03d/%02d/' % (prod, t.tm_year, t.tm_yday, t.tm_hour)
        tok = None
        while True:
            q = 'https://%s.s3.amazonaws.com/?list-type=2&prefix=%s%s' % (BUCKET[sat], prefix, '&continuation-token=' + urllib.request.quote(tok) if tok else '')
            x = get(q, 30).decode()
            for k in re.findall(r'<Key>([^<]+)</Key>', x):
                m = KEYRE.search(k)
                if not m or m.group(2) not in need: continue
                out.setdefault(''.join(m.group(3, 4, 5, 6)), {})[m.group(2)] = k
            m2 = re.search(r'<NextContinuationToken>([^<]+)</NextContinuationToken>', x)
            if not m2: break
            tok = m2.group(1)
    return {s: v for s, v in out.items() if all(c in v for c in need)}


def read(sat, key):
    """(values, x0, dx, y0, dy): the CMI array (K) as float32 with NaN off the disk, and its scan-angle grid"""
    import netCDF4
    raw = get('https://%s.s3.amazonaws.com/%s' % (BUCKET[sat], key))
    d = netCDF4.Dataset('mem', memory=raw)
    v = np.ma.filled(d['CMI'][:].astype(np.float32), np.nan)
    x, y = d['x'][:], d['y'][:]
    r = (v, float(x[0]), float(x[1] - x[0]), float(y[0]), float(y[1] - y[0]))
    d.close()
    return r


def grid_bounds(sat, prod):
    """the scan-angle box a product covers (read off one recent file)"""
    sc = scenes(sat, prod, '13', 1)
    if not sc: return None
    v, x0, dx, y0, dy = read(sat, sc[max(sc)]['13'])
    return (x0, x0 + dx * (v.shape[1] - 1), y0 + dy * (v.shape[0] - 1), y0)   # xmin, xmax, ymin, ymax


def sector_xy(sat, sector):
    """scan angles of every output pixel's centre, from the sector's crop on the 10848 grid"""
    l, t, r, b = fdgeo.crop(sat, sector)
    W, H = fdgeo.OUT_W, fdgeo.OUT_H
    cx = l + (np.arange(W) + 0.5) * (r - l) / W - fdgeo.FIT[sat][0]
    cy = t + (np.arange(H) + 0.5) * (b - t) / H - fdgeo.FIT[sat][1]
    return fdgeo.X0 + cx * fdgeo.D, fdgeo.Y0 - cy * fdgeo.D


def fits(sat, sector, bounds):
    xs, ys = sector_xy(sat, sector)
    return bounds and xs.min() >= bounds[0] and xs.max() <= bounds[1] and ys.min() >= bounds[2] and ys.max() <= bounds[3]


def sample(arr, x0, dx, y0, dy, xs, ys):
    """bilinear, NaN outside"""
    fi = (xs - x0) / dx; fj = (ys - y0) / dy
    J, I = np.meshgrid(fi, fj)
    i0 = np.floor(I).astype(int); j0 = np.floor(J).astype(int)
    a = I - i0; b = J - j0
    h, w = arr.shape
    ok = (i0 >= 0) & (j0 >= 0) & (i0 < h - 1) & (j0 < w - 1)
    i0c = np.clip(i0, 0, h - 2); j0c = np.clip(j0, 0, w - 2)
    v = (arr[i0c, j0c] * (1 - a) * (1 - b) + arr[i0c + 1, j0c] * a * (1 - b) +
         arr[i0c, j0c + 1] * (1 - a) * b + arr[i0c + 1, j0c + 1] * a * b)
    v[~ok] = np.nan
    return v


def render(band, ch):
    """ch: {channel: sampled K array} -> uint8 RGB"""
    if band == '13':
        t = ch['13']
        idx = np.clip(np.nan_to_num(np.round(t), nan=LUT0) - LUT0, 0, len(LUT) - 1).astype(int)
        rgb = LUT[idx]
        rgb[~np.isfinite(t)] = 0
        return rgb
    c08, c10, c12, c13 = ch['08'], ch['10'], ch['12'], ch['13']
    R = np.clip(((c08 - c10) + 26.2) / (0.6 + 26.2), 0, 1)
    G = np.clip(((c12 - c13) + 43.2) / (6.7 + 43.2), 0, 1)
    B = np.clip((c08 - 243.9) / (208.5 - 243.9), 0, 1)
    rgb = (np.dstack([R, G, B]) * 255).round()
    rgb[~np.isfinite(rgb)] = 0
    return rgb.astype(np.uint8)


def cut_scene(job):
    """one scan, every sector that needs it: job = (sat, band, keys {ch: key}, [(sector, out_path)]). Run in a process:
    netCDF4 is not thread-safe."""
    from PIL import Image
    sat, band, keys, outs = job
    data = {c: read(sat, k) for c, k in keys.items()}
    n = 0
    for sector, path in outs:
        xs, ys = sector_xy(sat, sector)
        ch = {c: sample(v, x0, dx, y0, dy, xs, ys) for c, (v, x0, dx, y0, dy) in data.items()}
        Image.fromarray(render(band, ch)).save(path, quality=90)
        n += 1
    return n
