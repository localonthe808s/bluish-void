"""THE WHOLE EARTH, BAKED (2026-10-25, user: "bake the world map in the same way that you smoothed the geocolor video").

LIVE's zoom out ends on the spinning globe. Its world picture used to be built in the viewer's browser every time it opened:
five full disks fetched through the proxy, reprojected pixel by pixel into a 2048 x 1024 latitude / longitude map (seconds of
work on a phone), and the 3-hour loop six more of those at 30-minute steps, which jumped. It is made here instead, every
10 minutes with the other loops (goes-video.yml), the way bake.py makes LIVE's GeoColor:

  - the same five disks the page used (CIRA SLIDER GeoProxy: true color by day, infrared cloud over city lights by night),
    read through our tiles worker (edge-cached a year a frame), each 10-minute scan of the last 3 hours;
  - stitched with the page's own rules (enowCompose): each output pixel goes to every satellite that sees it, weighted by
    (cos of the viewing angle - 0.18)^3, the disks' rims (cos < 0.2) thrown away, near-white near a rim nearly ignored (glare);
  - optical-flow in-betweens between 10-minute scans (bake.inbetweens), so the clouds glide instead of stepping;
  - one MP4 per kind on R2 behind Cloudflare, a poster JPG of the newest, and one ALPHA mask (where some satellite sees the
    ground; the poles fade to the globe's base map), uploaded only when it changes.

    goes/video/WORLD/<newest>_d.mp4  2048 x 1024, every in-between      goes/video/WORLD/<newest>_m.mp4  1024 x 512, one
    goes/video/WORLD/<newest>_p.jpg  the newest frame                   goes/video/WORLD/mask_<hash>.png  the alpha
    goes/video/WORLD/latest.json     the files, each frame's name (its UTC time), the step in minutes

    python3 _goesvid/worldbake.py            (R2 credentials as for bake.py)
    python3 _goesvid/worldbake.py --dry      (no download of the old state, no upload; prints the folder)
"""
import hashlib, io, json, math, os, re, shutil, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake, fdgeo, nightblend, rawbands
import numpy as np
from PIL import Image

EDGE = 'https://tiles.bluishvoid.com/slider/'
PROD = 'cira_geoproxy'
# the page's ESAT: SLIDER name, sub-satellite longitude, the disk's equatorial radius as a share of the image width (measured)
SATS = [('goes-19', -75.0, 0.5), ('goes-18', -137.0, 0.5), ('himawari', 140.7, 0.4942), ('meteosat-12', 0.0, 0.4885), ('gk2a', 128.2, 0.4927)]
# SHARPER (2026-10-26, user: "improve the clarity of the other satellites ... the clouds are grainy"): the frames are made at
# 4096 x 2048 (~10 km a pixel at the equator) from CIRA's zoom-2 disks (4 x 4 tiles, ~2750 px across, ~4.6 km a pixel under the
# satellite) instead of its one-tile overview (~690 px, ~18 km). Measured on one frame: 27x the fine detail over Japan, 55x over
# Europe. The page plays the 2048 cut by default and swaps to the 4096 one ('hd') only when a computer zooms in.
OW, OH = 4096, 2048
CIRA = 'https://slider.cira.colostate.edu/data/'
CIRA_Z = 2
HOURS, STEP_MIN, NEAR_MIN = 3, 10, 6        # a frame every 10 min over 3 h; a satellite's scan within 6 min of the mark joins it
# A SATELLITE MISSING A MARK HOLDS ITS NEAREST SCAN (2026-10-26, user: "the full globe view is choppy"): a mark with no scan within
# 6 min used to leave that satellite out, and the frame went black over its side of the world (Meteosat-12: Europe and Africa
# dropped out of one frame and the optical-flow in-betweens smeared into and out of the hole -- measured 10x a normal frame's
# change). Its nearest scan within 30 min stands in, so that side holds still a moment instead.
HOLD_MIN = 30
KINDS = {'d': {'w': 2048, 'crf': 25, 'g': 12, 'ib': (1, 2, 3)}, 'm': {'w': 1024, 'crf': 28, 'g': 8, 'ib': (2,)},
         'hd': {'w': OW, 'crf': 29, 'g': 12, 'ib': (1, 2, 3)}}
KEY = bake.PREFIX + 'WORLD/'
TAR_KEY = bake.PREFIX + '_frames/WORLD.tar'
BUDGET_S = 420
# LIVE'S COLORS ON THE GLOBE (2026-10-25, user: "do ... the rest" -- the globe was bluer at night than LIVE's East + West): the two GOES
# satellites come from what LIVE uses -- NOAA's full-disk GeoColor (5424 px, through our tiles worker) with nightblend.py's
# infrared night from the scan's own Level 2 files -- and CIRA's picture only for Himawari, GK2A and Meteosat. VER in the frame tar:
# frames made the old way are dropped and made again.
GOES = {'goes-19': 'GOES19', 'goes-18': 'GOES18'}
VER = 'v3'   # v3 (10-26): frames rebuilt with the held scans (v2's had holes)
FD_N = 5424
_DLL = {}


def disk_latlon(sat):
    """lat / lon of every pixel of a 5424 full disk (NaN off the Earth), the fixed-grid inverse (GOES-R PUG 5.1.2.8)"""
    if sat in _DLL: return _DLL[sat]
    d = (2 * fdgeo.Y0) / FD_N
    xs = fdgeo.X0 + (np.arange(FD_N) + 0.5) * d; ys = fdgeo.Y0 - (np.arange(FD_N) + 0.5) * d
    x, y = np.meshgrid(xs.astype(np.float64), ys.astype(np.float64))
    req, rpol, H = fdgeo.REQ, fdgeo.RPOL, fdgeo.H
    a = np.sin(x) ** 2 + np.cos(x) ** 2 * (np.cos(y) ** 2 + (req ** 2 / rpol ** 2) * np.sin(y) ** 2)
    b = -2 * H * np.cos(x) * np.cos(y); c = H ** 2 - req ** 2; disc = b * b - 4 * a * c
    rs = (-b - np.sqrt(np.maximum(disc, 0))) / (2 * a)
    sx = rs * np.cos(x) * np.cos(y); sy = -rs * np.sin(x); sz = rs * np.cos(x) * np.sin(y)
    lat = np.degrees(np.arctan((req ** 2 / rpol ** 2) * sz / np.sqrt((H - sx) ** 2 + sy ** 2)))
    lon = fdgeo.LON0[sat] - np.degrees(np.arctan(sy / (H - sx)))
    lat[disc < 0] = np.nan; lon[disc < 0] = np.nan
    _DLL[sat] = (lat.astype(np.float32), lon.astype(np.float32)); return _DLL[sat]


def disk_night(sat, stamp):
    lat, lon = disk_latlon(sat)
    dd, h, m = int(stamp[4:7]), int(stamp[7:9]), int(stamp[9:11])
    g = 2 * math.pi / 365 * (dd - 1 + (h - 12) / 24)
    dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
           - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    ha = np.radians((h * 60 + m + eqt + 4 * lon) / 4 - 180); la = np.radians(lat)
    cz = np.sin(la) * math.sin(dec) + np.cos(la) * math.cos(dec) * np.cos(ha)
    return np.nan_to_num(nightblend._ss(0.21, 0.035, cz), nan=0.0).astype(np.float32)


def goes_disk(sat, name):
    """NOAA's 5424 GeoColor full disk for one scan, with LIVE's night blend; None if the image or (at night) its infrared is not up"""
    raw = bake.get(bake.EDGE + '%s/ABI/FD/GEOCOLOR/%s' % (sat, name), 90)
    gc = np.asarray(Image.open(io.BytesIO(raw)).convert('RGB'), np.float32)
    if gc.shape[0] != FD_N: return None
    if bake.fd_broken(gc): print('  %s %s: broken scan, skipped' % (sat, name[:11])); return None
    stamp = name[:11]; night = disk_night(sat, stamp)
    if night.max() > 0:
        keys = nightblend.scan_keys(sat, stamp)
        if not keys: return None
        ch = {}
        for c, k in keys.items():
            v, x0, dx, y0, dy = rawbands.read(sat, k)
            ch[c] = v if v.shape == (FD_N, FD_N) else None
        if any(v is None for v in ch.values()): return None
        gc = nightblend.blend(gc, ch['07'], ch['13'], ch['15'], night)
    return np.clip(gc, 0, 255).round().astype(np.uint8)
DRY = '--dry' in sys.argv


def cira_disk(k, t):
    """CIRA's full disk at zoom CIRA_Z, its tiles stitched (straight from CIRA: the tiles worker passes zooms 0-1 only)"""
    from concurrent.futures import ThreadPoolExecutor
    n = 2 ** CIRA_Z; base = CIRA + 'imagery/%s/%s/%s/%s---full_disk/%s/%s/%02d/' % (t[:4], t[4:6], t[6:8], k, PROD, t, CIRA_Z)
    rc = [(r, c) for r in range(n) for c in range(n)]
    with ThreadPoolExecutor(8) as ex:
        tiles = list(ex.map(lambda q: np.asarray(Image.open(io.BytesIO(bake.get(base + '%03d_%03d.png' % q, 60))).convert('RGB')), rc))
    s = tiles[0].shape[0]; im = np.zeros((s * n, s * n, 3), np.uint8)
    for (r, c), a in zip(rc, tiles):
        if a.shape[:2] != (s, s): raise ValueError('tile %d_%d is %s' % (r, c, a.shape))
        im[r * s:(r + 1) * s, c * s:(c + 1) * s] = a
    return im


def tms(t14):
    return time.mktime(time.strptime(t14[:12], '%Y%m%d%H%M')) - time.timezone


def stamp11(sec):
    g = time.gmtime(sec)
    return '%04d%03d%02d%02d' % (g.tm_year, g.tm_yday, g.tm_hour, g.tm_min)


_GEO = {}


def geometry():
    """per satellite: where each output pixel falls on its disk (scan angles in units of the limb) and the cos of its viewing angle"""
    if _GEO: return _GEO
    A, B, HS, rad = 6378.137, 6356.752, 42164.16, math.pi / 180
    LX, LY = math.asin(A / HS), math.asin(B / HS)
    la = (90 - (np.arange(OH) + 0.5) * 180 / OH) * rad
    lo = (-180 + (np.arange(OW) + 0.5) * 360 / OW) * rad
    cp, sp = np.cos(la)[:, None], np.sin(la)[:, None]
    z = B * sp
    for k, lon0, rf in SATS:
        dl = lo[None, :] - lon0 * rad
        x, y = A * cp * np.cos(dl), A * cp * np.sin(dl)
        dx = HS - x
        vis = dx * x - y * y - z * z
        pr = np.sqrt(x * x + y * y + z * z); dr = np.sqrt(dx * dx + y * y + z * z)
        cv = np.where(vis > 0, vis / (pr * dr), 0)
        _GEO[k] = {'cv': cv.astype(np.float32), 'u': (np.arcsin(np.clip(y / dr, -1, 1)) / LX).astype(np.float32),
                   'v': (np.arctan(z / dx) / LY).astype(np.float32), 'rf': rf}
    return _GEO


def compose(disks):
    """disks: {sat: RGB uint8 array} -> (RGB uint8 OH x OW, best cos per pixel), the page's weights"""
    import cv2
    G = geometry()
    acc = np.zeros((OH, OW, 3), np.float32); ws = np.zeros((OH, OW), np.float32); best = np.zeros((OH, OW), np.float32)
    A_, B_, HS_ = 6378.137, 6356.752, 42164.16
    for k, im in disks.items():
        g = G[k]; h, w = im.shape[:2]
        if k in GOES and w == FD_N:   # NOAA's disk spans the fixed grid exactly (+-X0 rad): the limb sits inside the image edge
            rx = w / 2 * math.asin(A_ / HS_) / abs(fdgeo.X0); ry = h / 2 * math.asin(B_ / HS_) / abs(fdgeo.X0)
        else: rx, ry = w * g['rf'], w * g['rf'] * 0.997
        mx = (w / 2 - 0.5 + g['u'] * rx).astype(np.float32); my = (h / 2 - 0.5 - g['v'] * ry).astype(np.float32)
        ok = g['cv'] >= 0.2
        mx[~ok] = -1; my[~ok] = -1
        px = cv2.remap(im, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0).astype(np.float32)
        # the disk, not the brightness: dark night ocean is real data (a sum<30 cut punched holes in it); only what the remap
        # left at its black border (outside the image) is dropped
        inside = (mx >= 0) & (my >= 0) & (mx <= w - 1) & (my <= h - 1)
        use = ok & inside
        e = np.clip(g['cv'] - 0.18, 0, None)
        wt = e * e * e * np.where((g['cv'] < 0.4) & (px.min(2) >= 200), 0.02, 1.0) * use
        acc += px * wt[..., None]; ws += wt
        best = np.maximum(best, np.where(use, g['cv'], 0))
    rgb = np.where(ws[..., None] > 0, acc / np.maximum(ws, 1e-9)[..., None], 0)
    return np.clip(rgb, 0, 255).round().astype(np.uint8), best


def alpha(best):
    a = np.clip((best - 0.2) / 0.12, 0, 1)
    return (a * a * (3 - 2 * a) * 255).round().astype(np.uint8)


def main():
    t0 = time.time()
    work = tempfile.mkdtemp(); fd = os.path.join(work, 'frames'); os.makedirs(fd)
    tar_local = os.path.join(work, 'frames.tar'); old = None
    if not DRY:
        if bake.r2('cp', 's3://%s/%slatest.json' % (bake.BUCKET, KEY), os.path.join(work, 'old.json'), check=False).returncode == 0:
            try: old = json.load(open(os.path.join(work, 'old.json')))
            except Exception: old = None
        if bake.r2('cp', 's3://%s/%s' % (bake.BUCKET, TAR_KEY), tar_local, check=False).returncode == 0:
            subprocess.run(['tar', '-xf', tar_local, '-C', fd], check=False)
    mp = os.path.join(fd, 'mask.png')
    if os.path.exists(mp) and Image.open(mp).mode != 'RGBA':       # a mask from before 2026-10-25 (grayscale): rebuilt with the newest frame
        os.remove(mp); nf = sorted(f for f in os.listdir(fd) if re.match(r'^\d{11}_WORLD\.jpg$', f))
        if nf: os.remove(os.path.join(fd, nf[-1]))
    # frames from before the 4096 switch are scaled up in place: the loop stays whole, and they age out within its 3 hours
    import cv2
    for f in os.listdir(fd):
        if f.endswith('.jpg'):
            fp = os.path.join(fd, f); im = cv2.imread(fp)
            if im is not None and im.shape[1] != OW: cv2.imwrite(fp, cv2.resize(im, (OW, OH), interpolation=cv2.INTER_CUBIC), [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not os.path.exists(os.path.join(fd, VER)):
        for f in os.listdir(fd): os.remove(os.path.join(fd, f))
        open(os.path.join(fd, VER), 'w').write('1')
    lists = {}
    fdn = {}
    for k, s2 in GOES.items():
        try: fdn[k] = {bake.stamp_ms(n) / 1000: n for n in bake.fd_listing(s2, 'GEOCOLOR', '5424x5424')}
        except Exception as e: print('  %s FD listing: %s' % (s2, e)); fdn[k] = {}
    for k, _, _ in SATS:
        try:
            ts = sorted(str(t) for t in json.loads(bake.get(EDGE + 'json/%s/full_disk/%s/latest_times.json' % (k, PROD), 30))['timestamps_int'])
            if ts: lists[k] = ts
        except Exception as e:
            print('  %s times: %s' % (k, e))
    if len(lists) < 3: print('WORLD: only %d satellites listed, kept' % len(lists)); return
    # the marks: every 10 min back from GOES-19's newest scan. A satellite that runs behind (Meteosat-12, ~2 h) plays its OWN
    # last 3 hours, shifted by its lag (rounded to 10 min), so it still fills its side of the world in every frame
    anchor = tms((lists.get('goes-19') or max(lists.values(), key=lambda L: L[-1]))[-1])
    lag = {k: max(0, round((anchor - tms(L[-1])) / 600.0) * 600) for k, L in lists.items()}
    if any(lag.values()): print('  lag (min):', {k: v // 60 for k, v in lag.items() if v})
    marks = [anchor - i * STEP_MIN * 60 for i in range(HOURS * 60 // STEP_MIN, -1, -1)]
    want = {stamp11(m) + '_WORLD.jpg': m for m in marks}
    for f in os.listdir(fd):
        if re.sub(r'_f\d\.jpg$', '.jpg', f) not in want and f not in ('mask.png', VER): os.remove(os.path.join(fd, f))
    newest_fn = max(want, key=lambda f: want[f])
    cache, new = {}, 0
    for fn, m in sorted(want.items(), key=lambda kv: -kv[1]):       # newest first
        p = os.path.join(fd, fn)
        if os.path.exists(p): continue
        if time.time() - t0 > BUDGET_S: break
        disks = {}
        for k in GOES:                                          # NOAA's disk, LIVE's night
            T0 = fdn.get(k) or {}
            if not T0: continue
            # the nearest good scan within the hold (a broken one gives way to the next): NOAA's own product all through the
            # loop -- CIRA's GOES copy is another color, and swapping to it for one frame flashes
            for tt in sorted((t for t in T0 if abs(t - m) <= HOLD_MIN * 60), key=lambda t: abs(t - m))[:3]:
                ck = 'noaa' + T0[tt]
                if ck not in cache:
                    try: cache[ck] = goes_disk(GOES[k], T0[tt])
                    except Exception as e: print('  %s %s: %s' % (k, T0[tt], e)); cache[ck] = None
                if cache[ck] is not None: disks[k] = cache[ck]; break
        for k, L in lists.items():
            if k in disks: continue
            m2 = m - lag[k]
            # the nearest scans first; one that will not download gives way to the next (up to three tries)
            for near in sorted((t for t in L if abs(tms(t) - m2) <= HOLD_MIN * 60), key=lambda t: abs(tms(t) - m2))[:3]:
                ck = k + near
                if ck not in cache:
                    try:
                        cache[ck] = cira_disk(k, near)
                    except Exception as e:
                        print('  %s %s: %s' % (k, near, e)); cache[ck] = None
                if cache[ck] is not None: disks[k] = cache[ck]; break
        if len(disks) < 3: print('  %s: %d disks, skipped' % (fn, len(disks))); continue
        rgb, best = compose(disks)
        for ck in [x for x in cache if x.startswith('noaa')]: del cache[ck]   # 88 MB each: one frame's worth at a time
        # CIRA's sharp disks are 22 MB each: the marks go newest first, so a scan newer than this mark by more than the hold is
        # never wanted again (a full rebuild otherwise held ~45 of them; peak 6.3 GB)
        for ck in [x for x in cache if not x.startswith('noaa')]:
            kk = ck[:-14]
            if kk in lag and tms(ck[-14:]) - (m - lag[kk]) > HOLD_MIN * 60: del cache[ck]
        Image.fromarray(rgb).save(p, quality=90); new += 1
        if fn == newest_fn or not os.path.exists(os.path.join(fd, 'mask.png')):
            am = cv2.resize(alpha(best), (2048, 1024), interpolation=cv2.INTER_AREA); Image.fromarray(np.dstack([np.full_like(am, 255)] * 3 + [am]), 'RGBA').save(os.path.join(fd, 'mask.png'), optimize=True)   # the page masks with destination-in, which reads ALPHA
    got = sorted(f for f in want if os.path.exists(os.path.join(fd, f)))
    if len(got) < 2: print('WORLD: %d frames, nothing to play' % len(got)); return
    made = 0
    for i in range(len(got) - 2, -1, -1):
        if time.time() - t0 > BUDGET_S + 120: break
        try:
            if bake.inbetweens(fd, got[i], got[i + 1]): made += 1
        except Exception as e:
            print('  in-between: %s' % e); break
    if old and (old.get('d') or {}).get('frames', [None])[-1:] == [got[-1]] and not new and not made:
        print('WORLD: no new frame (kept)'); return
    newest = got[-1][:11]
    man = {'at': int(time.time()), 'sat': 'WORLD', 'w': OW, 'h': OH, 'fps': bake.FPS, 'step': STEP_MIN, 'sats': list(lists), 'src': 'CIRA SLIDER GeoProxy (zoom %d)' % CIRA_Z,
           'lag': {k: v // 60 for k, v in lag.items() if v}}
    man['mask'] = 'mask_%s.png' % hashlib.sha1(open(os.path.join(fd, 'mask.png'), 'rb').read()).hexdigest()[:10]
    for kk, K in KINDS.items():
        use = []
        for i, n in enumerate(got):
            use.append(n)
            if i < len(got) - 1:
                ib = [n[:-4] + '_f%d.jpg' % k for k in K['ib']]
                if all(os.path.exists(os.path.join(fd, x)) for x in ib): use += ib
        lst = os.path.join(work, 'list_%s.txt' % kk)
        open(lst, 'w').write(''.join("file '%s'\nduration %.3f\n" % (os.path.join(fd, n), 1.0 / bake.FPS) for n in use) + "file '%s'\n" % os.path.join(fd, use[-1]))
        out = os.path.join(work, '%s_%s.mp4' % (newest, kk))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-vf', 'scale=%d:%d' % (K['w'], K['w'] // 2),
                        '-r', str(bake.FPS), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(K['crf']), '-g', str(K['g']), '-bf', '0',
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', out], check=True)
        kstep = round(STEP_MIN * (len(got) - 1) / max(1, len(use) - 1), 3)
        if kk == 'd': man['step'] = kstep
        man[kk] = {'mp4': os.path.basename(out), 'frames': use, 'real': len(got), 'step': kstep, 'bytes': os.path.getsize(out)}
    poster = os.path.join(work, '%s_p.jpg' % newest)
    Image.open(os.path.join(fd, got[-1])).resize((2048, 1024), Image.LANCZOS).save(poster, quality=85)   # the poster stays the page's default size; man['poster'] = os.path.basename(poster)
    print('WORLD: %d new, %d in-betweens, %.0f s; ' % (new, made, time.time() - t0)
          + ', '.join('%s %d frames %.1f MB' % (kk, len(man[kk]['frames']), man[kk]['bytes'] / 1e6) for kk in KINDS), flush=True)
    if DRY:
        json.dump(man, open(os.path.join(work, 'latest.json'), 'w'))
        print('dry run: files in', work); return
    subprocess.run(['tar', '-cf', tar_local, '-C', fd] + sorted(os.listdir(fd)), check=True)   # (VER rides in the tar)
    bake.r2('cp', tar_local, 's3://%s/%s' % (bake.BUCKET, TAR_KEY), '--content-type', 'application/x-tar', '--cache-control', 'no-store')
    if not old or old.get('mask') != man['mask']:
        bake.r2('cp', os.path.join(fd, 'mask.png'), 's3://%s/%s%s' % (bake.BUCKET, KEY, man['mask']), '--content-type', 'image/png', '--cache-control', 'public, max-age=31536000, immutable')
    for kk in KINDS:
        bake.r2('cp', os.path.join(work, man[kk]['mp4']), 's3://%s/%s%s' % (bake.BUCKET, KEY, man[kk]['mp4']), '--content-type', 'video/mp4', '--cache-control', 'public, max-age=31536000, immutable')
    bake.r2('cp', poster, 's3://%s/%s%s' % (bake.BUCKET, KEY, man['poster']), '--content-type', 'image/jpeg', '--cache-control', 'public, max-age=31536000, immutable')
    p = os.path.join(work, 'latest.json'); json.dump(man, open(p, 'w'), separators=(',', ':'))
    bake.r2('cp', p, 's3://%s/%slatest.json' % (bake.BUCKET, KEY), '--content-type', 'application/json', '--cache-control', 'public, max-age=60')
    keep = {(man.get(kk) or {}).get('mp4') for kk in KINDS} | {((old or {}).get(kk) or {}).get('mp4') for kk in KINDS} \
        | {man['poster'], (old or {}).get('poster'), man['mask'], (old or {}).get('mask')}
    for f in [x for x in bake.r2('ls', 's3://%s/%s' % (bake.BUCKET, KEY), check=False).stdout.split() if re.search(r'\.(mp4|jpg|png)$', x) and x not in keep]:
        bake.r2('rm', 's3://%s/%s%s' % (bake.BUCKET, KEY, f), check=False)
    shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
