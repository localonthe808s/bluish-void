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
import bake
import numpy as np
from PIL import Image

EDGE = 'https://tiles.bluishvoid.com/slider/'
PROD = 'cira_geoproxy'
# the page's ESAT: SLIDER name, sub-satellite longitude, the disk's equatorial radius as a share of the image width (measured)
SATS = [('goes-19', -75.0, 0.5), ('goes-18', -137.0, 0.5), ('himawari', 140.7, 0.4942), ('meteosat-12', 0.0, 0.4885), ('gk2a', 128.2, 0.4927)]
OW, OH = 2048, 1024
HOURS, STEP_MIN, NEAR_MIN = 3, 10, 6        # a frame every 10 min over 3 h; a satellite's scan within 6 min of the mark joins it
KINDS = {'d': {'w': OW, 'crf': 25, 'g': 12, 'ib': (1, 2, 3)}, 'm': {'w': OW // 2, 'crf': 28, 'g': 8, 'ib': (2,)}}
KEY = bake.PREFIX + 'WORLD/'
TAR_KEY = bake.PREFIX + '_frames/WORLD.tar'
BUDGET_S = 300
DRY = '--dry' in sys.argv


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
    for k, im in disks.items():
        g = G[k]; h, w = im.shape[:2]
        rx, ry = w * g['rf'], w * g['rf'] * 0.997
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
    lists = {}
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
        if re.sub(r'_f\d\.jpg$', '.jpg', f) not in want and f != 'mask.png': os.remove(os.path.join(fd, f))
    newest_fn = max(want, key=lambda f: want[f])
    cache, new = {}, 0
    for fn, m in sorted(want.items(), key=lambda kv: -kv[1]):       # newest first
        p = os.path.join(fd, fn)
        if os.path.exists(p): continue
        if time.time() - t0 > BUDGET_S: break
        disks = {}
        for k, L in lists.items():
            m2 = m - lag[k]
            near = min(L, key=lambda t: abs(tms(t) - m2))
            if abs(tms(near) - m2) > NEAR_MIN * 60: continue
            ck = k + near
            if ck not in cache:
                try:
                    raw = bake.get(EDGE + 'imagery/%s/%s/%s/%s---full_disk/%s/%s/00/000_000.png' % (near[:4], near[4:6], near[6:8], k, PROD, near), 60)
                    cache[ck] = np.asarray(Image.open(io.BytesIO(raw)).convert('RGB'))
                except Exception as e:
                    print('  %s %s: %s' % (k, near, e)); cache[ck] = None
            if cache[ck] is not None: disks[k] = cache[ck]
        if len(disks) < 3: print('  %s: %d disks, skipped' % (fn, len(disks))); continue
        rgb, best = compose(disks)
        Image.fromarray(rgb).save(p, quality=90); new += 1
        if fn == newest_fn or not os.path.exists(os.path.join(fd, 'mask.png')):
            am = alpha(best); Image.fromarray(np.dstack([np.full_like(am, 255)] * 3 + [am]), 'RGBA').save(os.path.join(fd, 'mask.png'), optimize=True)   # the page masks with destination-in, which reads ALPHA
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
    man = {'at': int(time.time()), 'sat': 'WORLD', 'w': OW, 'h': OH, 'fps': bake.FPS, 'step': STEP_MIN, 'sats': list(lists), 'src': 'CIRA SLIDER GeoProxy',
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
    Image.open(os.path.join(fd, got[-1])).save(poster, quality=85); man['poster'] = os.path.basename(poster)
    print('WORLD: %d new, %d in-betweens, %.0f s; ' % (new, made, time.time() - t0)
          + ', '.join('%s %d frames %.1f MB' % (kk, len(man[kk]['frames']), man[kk]['bytes'] / 1e6) for kk in KINDS), flush=True)
    if DRY:
        json.dump(man, open(os.path.join(work, 'latest.json'), 'w'))
        print('dry run: files in', work); return
    subprocess.run(['tar', '-cf', tar_local, '-C', fd] + sorted(os.listdir(fd)), check=True)
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
