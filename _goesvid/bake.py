#!/usr/bin/env python3
"""LIVE CLOUDS AS VIDEO (2026-10-20, user: "yes build it"), CUT FROM THE FULL DISK (2026-10-23, user: "do the same for the
satellite loop" -> "NOAA full disk").

Every sector's loop is baked into one MP4 every 10 minutes (goes-video.yml, started by the Kalshi cron worker at :03/:13/...):

    goes/video/<sat>/<sector>/GEOCOLOR/<newest>_d.mp4   desktop: the last 6 h, 1600 x 1000, a keyframe every 4th frame
    goes/video/<sat>/<sector>/GEOCOLOR/<newest>_m.mp4   phones:  the last 2 h, 800 x 500, every frame a keyframe
    goes/video/<sat>/<sector>/GEOCOLOR/<newest>_p.jpg   the newest frame alone: the page shows it while the video downloads
    goes/video/<sat>/<sector>/GEOCOLOR/latest.json      which files are current, each frame's name (its UTC time), the source

THE SOURCE. The sector JPGs NESDIS publishes carry NESDIS's white state lines in the pixels. Its full-disk GeoColor does not,
so each sector is now cut from the full disk (10848 px = 1 km at nadir, every 10 min; fdgeo.py holds the crops) and the page
draws OUR map over it from /satmaps/<sat>-<sector>.png (satmaps_bake.py, the same crops). One full disk per satellite per
run serves every sector of that satellite. Frames are 10 minutes apart (the sectors were 5), so a 6 h loop is 36 frames; the
page slows its flipbook to suit (latest.json `step`).

Frames come through tiles.bluishvoid.com/goes/ (our edge cache of NESDIS; the runner cannot reach NESDIS directly). The cut
sector frames of the last 6 h are one tar per sector on R2 between runs, so a run downloads only the new full disks.

DISPOSAL: after a new latest.json is up, files two generations old are deleted (the previous generation stays, for a viewer
who read the old latest.json a moment ago); an R2 lifecycle rule deletes anything under goes/video/ older than a day.

    python3 _goesvid/bake.py            # all sectors (needs ffmpeg, Pillow, the aws cli and the R2 env: R2_ACCOUNT_ID, AWS_* keys)
    python3 _goesvid/bake.py --dry ne   # one sector, no upload: writes the videos to /tmp/goesvid
"""
import io, json, math, os, re, shutil, subprocess, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fdgeo, rawbands, glm

Image.MAX_IMAGE_PIXELS = None
FPS, STEP = 10, 10
# THE BANDS BAKED (user 2026-10-23: "add B13 and air mass"), each with the full-disk size it is read at: GeoColor at 10848
# (its daytime visible is 1 km); band 13 and Air Mass are 2 km data, so their 5424 copy holds all of it at a quarter of the
# pixels. The other bands stay on NESDIS's sector frames in the page.
BANDS = {'GEOCOLOR': '10848x10848'}
# B13 and Air Mass: NESDIS's full-disk pictures of these carry its state lines, so they are rendered from NOAA's own data
# instead (rawbands.py): CONUS/PACUS every 5 min for the sectors inside them, the full disk every 10 for the rest
RAW = ['13', 'AirMass']
# GLM lightning (user 2026-10-23): our GeoColor frame with the flashes of the 10 minutes its full disk took drawn over it (glm.py)
GLM_BAND = 'EXTENT3'
BUDGET_S = 420         # a run renders newest-first and stops starting new scans after this; the next run fills the rest
BAND_ONLY = sys.argv[sys.argv.index('--band') + 1] if '--band' in sys.argv else None
# GEOCOLOR CAN FREEZE ON ITS OWN (10-20: every sector's stopped at 15:11 UTC while the ABI bands kept coming): over an hour old,
# and with NESDIS's Day Night Cloud Micro Combo fresher, the run is baked from that and latest.json says which band it is
FB_BAND = 'DayNightCloudMicroCombo'
EDGE, NESDIS = 'https://tiles.bluishvoid.com/goes/', 'https://cdn.star.nesdis.noaa.gov/'
BUCKET, PREFIX = 'bluishvoid-bg', 'goes/video/'
# keyframe spacing: the page PLAYS the video now (2026-10-24) instead of seeking every frame, so keyframes can sit further
# apart (smaller files with 4x the frames); still close enough that a zoom swap or the seek fallback lands quickly
KINDS = {'d': {'hours': 6, 'crf': 25, 'g': 12, 'w': fdgeo.OUT_W},   # crf 25: ~13 MB for 6 h with in-betweens (22 was ~18)
         'm': {'hours': 2, 'crf': 23, 'g': 8, 'w': fdgeo.OUT_W // 2}}
OVERLAY_V = 5          # /satmaps/<sat>-<sector>.png?v= -- bump with satmaps_bake.py
UA = {'User-Agent': 'bluishvoid.com satellite loop bake'}
DRY = '--dry' in sys.argv
ONLY = sys.argv[sys.argv.index('--dry') + 1] if DRY and len(sys.argv) > sys.argv.index('--dry') + 1 else None
SECTORS = [k for k in fdgeo.SECTORS if not ONLY or k[1] == ONLY]


def get(url, timeout=60):
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception:
            if i == 2: raise
            time.sleep(3)


def stamp_ms(name):
    y, d, h, m = int(name[:4]), int(name[4:7]), int(name[7:9]), int(name[9:11])
    return (time.mktime((y, 1, 1, 0, 0, 0, 0, 0, 0)) - time.timezone + (d - 1) * 86400 + h * 3600 + m * 60) * 1000


def fd_listing(sat, band, size):
    for base in (EDGE, NESDIS):
        try:
            html = get('%s%s/ABI/FD/%s/' % (base, sat, band), 40).decode('utf-8', 'replace')
            names = sorted(set(re.findall(r'href="(\d{11}_%s-ABI-FD-%s-%s\.jpg)"' % (sat, band, size), html)))
            if names: return names
        except Exception as e:
            print('  %s FD %s listing via %s failed: %s' % (sat, band, base, e))
    return []


def r2(*args, check=True):
    # (`s3 ls` rejects --only-show-errors: with it the disposal's listing failed silently and old videos piled up to the
    #  bucket's one-day rule -- 34.6 GB under goes/video on 2026-10-24)
    cmd = ['aws', 's3'] + list(args) + ['--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID']] \
        + ([] if args[0] == 'ls' else ['--only-show-errors'])
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


INTERP = 3              # computed frames between each pair of real GEOCOLOR frames (user 2026-10-24: "make it run smoother")


def _sharp(g):
    import cv2
    return cv2.Laplacian(g, cv2.CV_32F).var()


def inbetweens(fd, a, b):
    """computed frames between real frames a and b, saved as <a>_f1.._f3.jpg next to them. Named with a's time, so the page's
    clock only ever shows real frame times.
    OPTICAL FLOW (2026-10-24, user: "the video transitions oddly"): ffmpeg's minterpolate matched 8-px blocks, which smeared fine
    cloud fields into streaks and left the middle frame ~40% softer than the scans, so the loop pulsed soft-sharp every step.
    Now: dense flow both ways (OpenCV DIS), smoothed (clouds move coherently), each scan warped toward the moment and blended;
    then a light unsharp mask picked per frame so its sharpness matches the two scans around it. ~0.5 s a pair."""
    import cv2, numpy as np
    outs = [os.path.join(fd, a[:-4] + '_f%d.jpg' % k) for k in range(1, INTERP + 1)]
    if all(os.path.exists(o) for o in outs): return False
    A = cv2.imread(os.path.join(fd, a)); B = cv2.imread(os.path.join(fd, b))
    if A is None or B is None or A.shape != B.shape: raise ValueError('unreadable pair')
    ga = cv2.cvtColor(A, cv2.COLOR_BGR2GRAY); gb = cv2.cvtColor(B, cv2.COLOR_BGR2GRAY)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    fab = cv2.GaussianBlur(dis.calc(ga, gb, None), (0, 0), 6); fba = cv2.GaussianBlur(dis.calc(gb, ga, None), (0, 0), 6)
    h, w = ga.shape; gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    target = (_sharp(ga.astype(np.float32)) + _sharp(gb.astype(np.float32))) / 2
    for k in range(1, INTERP + 1):
        t = k / (INTERP + 1.0)
        wa = cv2.remap(A, gx - t * fab[..., 0], gy - t * fab[..., 1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        wb = cv2.remap(B, gx - (1 - t) * fba[..., 0], gy - (1 - t) * fba[..., 1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        m = cv2.addWeighted(wa, 1 - t, wb, t, 0); bl = cv2.GaussianBlur(m, (0, 0), 1.0)
        best, bd = m, 1e18
        for amt in (0, .08, .16, .24, .32, .4):
            c = cv2.addWeighted(m, 1 + amt, bl, -amt, 0) if amt else m
            d = abs(_sharp(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY).astype(np.float32)) - target)
            if d < bd: best, bd = c, d
        tmp = outs[k - 1] + '.tmp.jpg'
        cv2.imwrite(tmp, best, [cv2.IMWRITE_JPEG_QUALITY, 92]); os.replace(tmp, outs[k - 1])
    return True


def frame_name(stamp, sat, sector, band):
    return '%s_%s-%s-%s.jpg' % (stamp, sat, sector, band)


def _glm_one(a):
    try: return glm.composite(*a)
    except Exception as e: print('  GLM %s %s: %s' % (a[2], a[3], e)); return 0


def main():
    root = '/tmp/goesvid' if DRY else tempfile.mkdtemp()
    os.makedirs(root, exist_ok=True)
    sats = sorted({s for s, _ in SECTORS})
    # 1. what each satellite's full disk offers per band over the longest window (and GeoColor's freeze fallback)
    plan = {}
    for sat in sats:
        for BAND, size in BANDS.items():
            if BAND_ONLY and BAND != BAND_ONLY: continue
            names, band = fd_listing(sat, BAND, size), BAND
            if BAND == 'GEOCOLOR' and names and time.time() * 1000 - stamp_ms(names[-1]) > 3600e3:
                fb = fd_listing(sat, FB_BAND, size)
                if fb and stamp_ms(fb[-1]) > stamp_ms(names[-1]) + 1800e3: names, band = fb, FB_BAND
            if not names: print('%s %s: no full-disk listing' % (sat, BAND)); continue
            t1 = stamp_ms(names[-1])
            plan[(sat, BAND)] = (band, [n for n in names if stamp_ms(n) > t1 - KINDS['d']['hours'] * 3600e3], int(size.split('x')[0]))
    # 2. each sector's frames from the last run (one tar per sector on R2), and its last manifest
    state = {}
    def mkstate(sat, sector, BAND, band, want, step, src):
        work = os.path.join(root, '%s_%s_%s' % (sat, sector, BAND)); fd = os.path.join(work, 'frames'); os.makedirs(fd, exist_ok=True)
        key = '%s%s/%s/%s/' % (PREFIX, sat, sector, BAND)
        tar_key = '%s_frames/%s_%s_fd.tar' % (PREFIX, sat, sector) if BAND == 'GEOCOLOR' else '%s_frames/%s_%s_%s_fd.tar' % (PREFIX, sat, sector, BAND)
        tar_local = os.path.join(work, 'frames.tar')
        old = None
        if not DRY:
            p = os.path.join(work, 'old.json')
            if r2('cp', 's3://%s/%slatest.json' % (BUCKET, key), p, check=False).returncode == 0:
                try: old = json.load(open(p))
                except Exception: old = None
            if r2('cp', 's3://%s/%s' % (BUCKET, tar_key), tar_local, check=False).returncode == 0:
                subprocess.run(['tar', '-xf', tar_local, '-C', fd], check=False)
        wset = set(want)
        for f in os.listdir(fd):
            if f not in wset and re.sub(r'_f\d\.jpg$', '.jpg', f) not in wset: os.remove(os.path.join(fd, f))   # an in-between lives as long as its frame
        state[(sat, sector, BAND)] = {'work': work, 'fd': fd, 'key': key, 'tar_key': tar_key, 'tar_local': tar_local, 'old': old,
                                      'want': want, 'band': band, 'new': 0, 'step': step, 'src': src}
    pending = []           # every loop's state is fetched from R2 in parallel below (one by one it took ~2.5 min of a run)
    for (sat, BAND) in plan:
        band, fds, _n = plan[(sat, BAND)]
        for s2, sector in SECTORS:
            if s2 == sat: pending.append((sat, sector, BAND, band, [frame_name(n[:11], sat, sector, band) for n in fds], STEP, 'fd'))
    raw_plan = []
    for sat in sats:
        bands = [b for b in RAW if not BAND_ONLY or b == BAND_ONLY]
        if not bands: continue
        try: bounds = rawbands.grid_bounds(sat, 'C')
        except Exception as e: print('%s: no CONUS grid (%s)' % (sat, e)); bounds = None
        for prod in ('C', 'F'):
            secs = [sc for s2, sc in SECTORS if s2 == sat and bool(bounds and rawbands.fits(sat, sc, bounds)) == (prod == 'C')]
            if not secs: continue
            for band in bands:
                try: sc = rawbands.scenes(sat, prod, band, KINDS['d']['hours'] + 0.3)
                except Exception as e: print('%s %s %s: no listing (%s)' % (sat, prod, band, e)); continue
                if not sc: continue
                t1 = stamp_ms(max(sc))
                stamps = sorted(st for st in sc if stamp_ms(st) > t1 - KINDS['d']['hours'] * 3600e3)
                for sector in secs: pending.append((sat, sector, band, band, [frame_name(st, sat, sector, band) for st in stamps], 5 if prod == 'C' else 10, 'raw'))
                raw_plan.append((sat, band, secs, sc, stamps))
    want_glm = (not BAND_ONLY or BAND_ONLY == GLM_BAND)
    if want_glm:
        for sat in sats:
            if (sat, 'GEOCOLOR') not in plan: continue
            stamps = [n[:11] for n in plan[(sat, 'GEOCOLOR')][1]]
            for s2, sector in SECTORS:
                if s2 == sat: pending.append((sat, sector, GLM_BAND, GLM_BAND, [frame_name(st, sat, sector, GLM_BAND) for st in stamps], STEP, 'raw'))
    with ThreadPoolExecutor(12) as ex: list(ex.map(lambda a: mkstate(*a), pending))
    raw_jobs = []
    for sat, band, secs, sc, stamps in raw_plan:
        for st in stamps:
            outs = [(sector, os.path.join(state[(sat, sector, band)]['fd'], frame_name(st, sat, sector, band))) for sector in secs]
            outs = [o for o in outs if not os.path.exists(o[1])]
            if outs: raw_jobs.append((st, (sat, band, sc[st], outs)))
    if not state: sys.exit(1)
    # 3. the full disks any sector still lacks, each downloaded once and cut for every sector of its satellite
    def cut(job):
        sat, BAND, n = job
        band, _f, N = plan[(sat, BAND)]
        mine = [k for k in state if k[0] == sat and k[2] == BAND and not os.path.exists(os.path.join(state[k]['fd'], frame_name(n[:11], sat, k[1], band)))]
        if not mine: return 0
        raw = None
        for base in (EDGE, NESDIS):
            try:
                raw = get('%s%s/ABI/FD/%s/%s' % (base, sat, band, n), 120)
                if len(raw) > 100000: break
            except Exception:
                raw = None
        if not raw: print('  %s %s: full disk did not download' % (sat, n)); return 0
        im = Image.open(io.BytesIO(raw)); im.load(); im = im.convert('RGB')
        for k in mine:
            try:
                l, t, r, b = fdgeo.crop(sat, k[1], N)
                if l < 0 or t < 0 or r > im.width or b > im.height:
                    # a wide sector (np, ep, taw) runs past the edge of the disk: cut with black beyond it, then scale
                    L, T = math.floor(l), math.floor(t)
                    fr = im.crop((L, T, int(r) + 1, int(b) + 1)).resize((fdgeo.OUT_W, fdgeo.OUT_H), Image.LANCZOS,
                                                                      box=(l - L, t - T, r - L, b - T))
                else:
                    fr = im.resize((fdgeo.OUT_W, fdgeo.OUT_H), Image.LANCZOS, box=(l, t, r, b))
                fr.save(os.path.join(state[k]['fd'], frame_name(n[:11], sat, k[1], band)), quality=92)
                state[k]['new'] += 1
            except Exception as e:
                print('  %s %s %s: cut failed: %s' % (sat, k[1], n[:11], e))
        return 1
    jobs = sorted({(k[0], k[1], n) for k in plan for n in plan[k][1]}, key=lambda j: j[2], reverse=True)   # newest first
    if os.environ.get('GV_MAXFD'): jobs = jobs[:int(os.environ['GV_MAXFD'])]   # a quick local test: only the newest few
    t_start = time.time()
    with ThreadPoolExecutor(3) as ex: got = sum(ex.map(cut, jobs))
    print('full disks downloaded: %d' % got, flush=True)
    # 3b. the raw scans (B13, Air Mass), newest first, in processes (netCDF4 is not thread-safe), within the time budget
    raw_jobs.sort(key=lambda j: j[0], reverse=True)
    if os.environ.get('GV_MAXFD'): raw_jobs = raw_jobs[:int(os.environ['GV_MAXFD'])]
    from concurrent.futures import ProcessPoolExecutor, as_completed
    done_n = skipped = 0
    with ProcessPoolExecutor(4) as px:
        futs = {px.submit(rawbands.cut_scene, j[1]): j[1] for j in raw_jobs}
        for f in as_completed(futs):
            sat, band, _k, outs = futs[f]
            if f.cancelled(): continue
            try:
                f.result(); done_n += 1
                for sector, _p in outs: state[(sat, sector, band)]['new'] += 1
            except Exception as e:
                print('  raw %s %s: %s' % (sat, band, e))
            if time.time() - t_start > BUDGET_S:
                for g in futs:
                    if g.cancel(): skipped += 1
    print('raw scans rendered: %d, left for the next run: %d' % (done_n, skipped), flush=True)
    # 3c. lightning: for each GeoColor frame some sector still lacks a lightning frame for, the flashes of its 10 minutes
    if want_glm:
        g_done = 0
        for sat in sats:
            if (sat, 'GEOCOLOR') not in plan or time.time() - t_start > BUDGET_S: continue
            band = plan[(sat, 'GEOCOLOR')][0]
            todo = {}
            for st in sorted({n[:11] for n in plan[(sat, 'GEOCOLOR')][1]}, reverse=True):
                if glm.stamp_s(st) + glm.WINDOW_S > time.time() - 60: continue      # its 10 minutes not over yet
                outs = []
                for k in state:
                    if k[0] != sat or k[2] != GLM_BAND: continue
                    base = os.path.join(state[(sat, k[1], 'GEOCOLOR')]['fd'], frame_name(st, sat, k[1], band))
                    out = os.path.join(state[k]['fd'], frame_name(st, sat, k[1], GLM_BAND))
                    if os.path.exists(base) and not os.path.exists(out): outs.append((k[1], base, out))
                if outs: todo[st] = outs
            if not todo: continue
            t0 = min(glm.stamp_s(st) for st in todo); t1 = max(glm.stamp_s(st) for st in todo) + glm.WINDOW_S
            try: fl = glm.files(sat, t0, t1)
            except Exception as e: print('  %s GLM listing failed: %s' % (sat, e)); continue
            for st, outs in todo.items():
                if time.time() - t_start > BUDGET_S: break
                a = glm.stamp_s(st)
                keys = [(sat, k) for k, ts in fl.items() if a <= ts < a + glm.WINDOW_S]
                if len(keys) < 20: continue                                          # a window with files missing: wait
                with ProcessPoolExecutor(6) as px: res = [r for r in px.map(glm.read, keys) if r]
                if not res: continue
                lat, lon, area = (np.concatenate([r[i] for r in res]) for i in range(3))
                with ProcessPoolExecutor(4) as px:
                    list(px.map(_glm_one, [(o[1], o[2], sat, o[0], lat, lon, area) for o in outs]))
                for sector, _b, out in outs:
                    if os.path.exists(out): state[(sat, sector, GLM_BAND)]['new'] += 1
                g_done += 1
        print('lightning windows drawn: %d' % g_done, flush=True)
    # 4. per sector: the tar for next time, the videos, the poster, the manifest
    def finish(k):
        S = state[k]; sat, sector, BAND = k; work, fd, key, old = S['work'], S['fd'], S['key'], S['old']
        got = [f for f in S['want'] if os.path.exists(os.path.join(fd, f))]
        if len(got) < 2: return 'no frames'
        # SMOOTHER (2026-10-24): GeoColor's real frames are 10 min apart; three computed in-betweens per pair, newest pairs first,
        # within the run's time budget (a pair left for later just plays without them)
        made = 0
        if BAND == 'GEOCOLOR' and S['src'] == 'fd':
            for i in range(len(got) - 2, -1, -1):
                if time.time() - t_start > BUDGET_S + 120: break
                try:
                    if inbetweens(fd, got[i], got[i + 1]): made += 1
                except Exception as e:
                    print('  %s %s in-between failed: %s' % (sat, sector, e)); break
        def seq(names):
            out = []
            for i, n in enumerate(names):
                out.append(n)
                if i < len(names) - 1:
                    ib = [n[:-4] + '_f%d.jpg' % k for k in range(1, INTERP + 1)]
                    if all(os.path.exists(os.path.join(fd, x)) for x in ib): out += ib
            return out
        if old and old.get('src') == S['src'] and (old.get('d') or {}).get('frames', [None])[-1:] == [got[-1]] and old.get('m') and not S['new'] and not made:
            return 'no new frame (kept)'
        if (S['new'] or made) and not DRY:
            subprocess.run(['tar', '-cf', S['tar_local'], '-C', fd] + sorted(os.listdir(fd)), check=True)
            r2('cp', S['tar_local'], 's3://%s/%s' % (BUCKET, S['tar_key']), '--content-type', 'application/x-tar', '--cache-control', 'no-store')
        newest = got[-1][:11]
        man = {'at': int(time.time()), 'sat': sat, 'sector': sector, 'band': S['band'], 'fps': FPS, 'src': S['src'], 'step': S['step'],
               'overlay': '/satmaps/%s-%s.png?v=%d' % (sat, sector, OVERLAY_V), 'w': fdgeo.OUT_W, 'h': fdgeo.OUT_H,
               # where the loop sits on its satellite's full-disk grid (10848 px): the page zooms across loops with it
               'crop': [round(v, 1) for v in fdgeo.crop(sat, sector)]}
        for kk, K in KINDS.items():
            real = [n for n in got if stamp_ms(n) > stamp_ms(got[-1]) - K['hours'] * 3600e3]
            if len(real) < 2: continue
            use = seq(real)
            lst = os.path.join(work, 'list_%s.txt' % kk)
            open(lst, 'w').write(''.join("file '%s'\nduration %.3f\n" % (os.path.join(fd, n), 1.0 / FPS) for n in use) + "file '%s'\n" % os.path.join(fd, use[-1]))
            vf = ['-vf', 'scale=%d:-2' % K['w']] if K['w'] != fdgeo.OUT_W else []
            out = os.path.join(work, '%s_%s.mp4' % (newest, kk))
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst] + vf +
                           ['-r', str(FPS), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(K['crf']), '-g', str(K['g']), '-bf', '0', '-pix_fmt', 'yuv420p',   # -bf 0: B-frames are stored softer, the fine cloud texture flickered every other frame
                           
                            '-movflags', '+faststart', '-an', out], check=True)
            man['step'] = round(S['step'] * (len(real) - 1) / max(1, len(use) - 1), 3)   # minutes a video frame stands for
            man[kk] = {'mp4': os.path.basename(out), 'frames': use, 'real': len(real), 'size': '%dx%d' % (K['w'], K['w'] * fdgeo.OUT_H // fdgeo.OUT_W),
                       'bytes': os.path.getsize(out), 'fetched': S['new']}
            if not DRY:
                r2('cp', out, 's3://%s/%s%s' % (BUCKET, key, os.path.basename(out)), '--content-type', 'video/mp4',
                   '--cache-control', 'public, max-age=31536000, immutable')
        if not any(kk in man for kk in KINDS): return 'no frames'
        # the poster: the newest frame at phone size, shown at once while the video downloads
        poster = os.path.join(work, '%s_p.jpg' % newest)
        Image.open(os.path.join(fd, got[-1])).resize((fdgeo.OUT_W // 2, fdgeo.OUT_H // 2), Image.LANCZOS).save(poster, quality=82)
        man['poster'] = os.path.basename(poster)
        if not DRY:
            r2('cp', poster, 's3://%s/%s%s' % (BUCKET, key, man['poster']), '--content-type', 'image/jpeg', '--cache-control', 'public, max-age=31536000, immutable')
        p = os.path.join(work, 'latest.json'); json.dump(man, open(p, 'w'), separators=(',', ':'))
        if DRY:
            for f in [man[kk]['mp4'] for kk in KINDS if kk in man] + [man['poster'], 'latest.json']:
                os.replace(os.path.join(work, f), os.path.join(root, '%s_%s_%s_%s' % (sat, sector, BAND, f)))
            return 'dry, %d new; ' % S['new'] + ', '.join('%s %d frames %.1f MB' % (kk, len(man[kk]['frames']), man[kk]['bytes'] / 1e6) for kk in KINDS if kk in man)
        r2('cp', p, 's3://%s/%slatest.json' % (BUCKET, key), '--content-type', 'application/json', '--cache-control', 'public, max-age=60')
        keep = {(man.get(kk) or {}).get('mp4') for kk in KINDS} | {((old or {}).get(kk) or {}).get('mp4') for kk in KINDS} \
             | {man.get('poster'), (old or {}).get('poster')}
        ls = r2('ls', 's3://%s/%s' % (BUCKET, key), check=False).stdout.split()
        for f in [x for x in ls if (x.endswith('.mp4') or x.endswith('_p.jpg')) and x not in keep]:
            r2('rm', 's3://%s/%s%s' % (BUCKET, key, f), check=False)
        return '%d new; ' % S['new'] + ', '.join('%s %d frames %.1f MB' % (kk, len(man[kk]['frames']), man[kk]['bytes'] / 1e6) for kk in KINDS if kk in man)
    def one(k):
        t = time.time()
        try: r = finish(k)
        except Exception as e: r = 'FAILED %s' % e
        print('%s %-4s %-8s %s (%.0f s)' % (k[0], k[1], k[2], r, time.time() - t), flush=True)
        return r
    with ThreadPoolExecutor(6) as ex: res = list(ex.map(one, list(state)))
    # EVERY LOOP'S PLACE ON THE DISK (2026-10-24, zoom while playing): the page picks the sharpest loop holding the view from this
    sj = {}
    for (sat, sector) in fdgeo.SECTORS: sj.setdefault(sat, {})[sector] = [round(v, 1) for v in fdgeo.crop(sat, sector)]
    p = os.path.join(root, 'sectors.json'); json.dump({'grid': fdgeo.N, 'sectors': sj}, open(p, 'w'), separators=(',', ':'))
    if not DRY:
        r2('cp', p, 's3://%s/%ssectors.json' % (BUCKET, PREFIX), '--content-type', 'application/json', '--cache-control', 'public, max-age=3600')
    if all(str(r).startswith('FAILED') or r == 'no frames' for r in res): sys.exit(1)


if __name__ == '__main__':
    main()
