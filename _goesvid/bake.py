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
import io, json, os, re, subprocess, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fdgeo

Image.MAX_IMAGE_PIXELS = None
BAND, FPS, STEP = 'GEOCOLOR', 10, 10
# GEOCOLOR CAN FREEZE ON ITS OWN (10-20: every sector's stopped at 15:11 UTC while the ABI bands kept coming): over an hour old,
# and with NESDIS's Day Night Cloud Micro Combo fresher, the run is baked from that and latest.json says which band it is
FB_BAND = 'DayNightCloudMicroCombo'
EDGE, NESDIS = 'https://tiles.bluishvoid.com/goes/', 'https://cdn.star.nesdis.noaa.gov/'
BUCKET, PREFIX = 'bluishvoid-bg', 'goes/video/'
SIZE = '10848x10848'
KINDS = {'d': {'hours': 6, 'crf': 22, 'g': 4, 'w': fdgeo.OUT_W},
         'm': {'hours': 2, 'crf': 23, 'g': 1, 'w': fdgeo.OUT_W // 2}}
OVERLAY_V = 1          # /satmaps/<sat>-<sector>.png?v= -- bump with satmaps_bake.py
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


def fd_listing(sat, band):
    for base in (EDGE, NESDIS):
        try:
            html = get('%s%s/ABI/FD/%s/' % (base, sat, band), 40).decode('utf-8', 'replace')
            names = sorted(set(re.findall(r'href="(\d{11}_%s-ABI-FD-%s-%s\.jpg)"' % (sat, band, SIZE), html)))
            if names: return names
        except Exception as e:
            print('  %s FD %s listing via %s failed: %s' % (sat, band, base, e))
    return []


def r2(*args, check=True):
    cmd = ['aws', 's3'] + list(args) + ['--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors']
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def frame_name(stamp, sat, sector, band):
    return '%s_%s-%s-%s.jpg' % (stamp, sat, sector, band)


def main():
    root = '/tmp/goesvid' if DRY else tempfile.mkdtemp()
    os.makedirs(root, exist_ok=True)
    sats = sorted({s for s, _ in SECTORS})
    # 1. what each satellite's full disk offers over the longest window, and which band (the freeze fallback)
    plan = {}
    for sat in sats:
        names, band = fd_listing(sat, BAND), BAND
        if names and time.time() * 1000 - stamp_ms(names[-1]) > 3600e3:
            fb = fd_listing(sat, FB_BAND)
            if fb and stamp_ms(fb[-1]) > stamp_ms(names[-1]) + 1800e3: names, band = fb, FB_BAND
        if not names: print('%s: no full-disk listing' % sat); continue
        t1 = stamp_ms(names[-1])
        plan[sat] = (band, [n for n in names if stamp_ms(n) > t1 - KINDS['d']['hours'] * 3600e3])
    if not plan: sys.exit(1)
    # 2. each sector's frames from the last run (one tar per sector on R2), and its last manifest
    state = {}
    for sat, sector in SECTORS:
        if sat not in plan: continue
        band, fds = plan[sat]
        work = os.path.join(root, '%s_%s' % (sat, sector)); fd = os.path.join(work, 'frames'); os.makedirs(fd, exist_ok=True)
        key = '%s%s/%s/%s/' % (PREFIX, sat, sector, BAND)
        tar_key = '%s_frames/%s_%s_fd.tar' % (PREFIX, sat, sector)
        tar_local = os.path.join(work, 'frames.tar')
        old = None
        if not DRY:
            p = os.path.join(work, 'old.json')
            if r2('cp', 's3://%s/%slatest.json' % (BUCKET, key), p, check=False).returncode == 0:
                try: old = json.load(open(p))
                except Exception: old = None
            if r2('cp', 's3://%s/%s' % (BUCKET, tar_key), tar_local, check=False).returncode == 0:
                subprocess.run(['tar', '-xf', tar_local, '-C', fd], check=False)
        want = [frame_name(n[:11], sat, sector, band) for n in fds]
        for f in os.listdir(fd):
            if f not in set(want): os.remove(os.path.join(fd, f))
        state[(sat, sector)] = {'work': work, 'fd': fd, 'key': key, 'tar_key': tar_key, 'tar_local': tar_local, 'old': old,
                                'want': want, 'band': band, 'new': 0}
    # 3. the full disks any sector still lacks, each downloaded once and cut for every sector of its satellite
    def cut(job):
        sat, n = job
        band = plan[sat][0]
        mine = [k for k in state if k[0] == sat and not os.path.exists(os.path.join(state[k]['fd'], frame_name(n[:11], sat, k[1], band)))]
        if not mine: return 0
        raw = None
        for base in (EDGE, NESDIS):
            try:
                raw = get('%s%s/ABI/FD/%s/%s' % (base, sat, band, n), 120)
                if len(raw) > 200000: break
            except Exception:
                raw = None
        if not raw: print('  %s %s: full disk did not download' % (sat, n)); return 0
        im = Image.open(io.BytesIO(raw)); im.load(); im = im.convert('RGB')
        for k in mine:
            l, t, r, b = fdgeo.crop(*k)
            fr = im.resize((fdgeo.OUT_W, fdgeo.OUT_H), Image.LANCZOS, box=(l, t, r, b))
            fr.save(os.path.join(state[k]['fd'], frame_name(n[:11], sat, k[1], band)), quality=92)
            state[k]['new'] += 1
        return 1
    jobs = sorted({(sat, n) for sat in plan for n in plan[sat][1]}, key=lambda j: j[1], reverse=True)   # newest first
    if os.environ.get('GV_MAXFD'): jobs = jobs[:int(os.environ['GV_MAXFD'])]   # a quick local test: only the newest few
    with ThreadPoolExecutor(3) as ex: got = sum(ex.map(cut, jobs))
    print('full disks downloaded: %d' % got, flush=True)
    # 4. per sector: the tar for next time, the videos, the poster, the manifest
    def finish(k):
        S = state[k]; sat, sector = k; work, fd, key, old = S['work'], S['fd'], S['key'], S['old']
        got = [f for f in S['want'] if os.path.exists(os.path.join(fd, f))]
        if len(got) < 2: return 'no frames'
        if old and old.get('src') == 'fd' and (old.get('d') or {}).get('frames', [None])[-1:] == [got[-1]] and old.get('m') and not S['new']:
            return 'no new frame (kept)'
        if S['new'] and not DRY:
            subprocess.run(['tar', '-cf', S['tar_local'], '-C', fd] + got, check=True)
            r2('cp', S['tar_local'], 's3://%s/%s' % (BUCKET, S['tar_key']), '--content-type', 'application/x-tar', '--cache-control', 'no-store')
        newest = got[-1][:11]
        man = {'at': int(time.time()), 'sat': sat, 'sector': sector, 'band': S['band'], 'fps': FPS, 'src': 'fd', 'step': STEP,
               'overlay': '/satmaps/%s-%s.png?v=%d' % (sat, sector, OVERLAY_V), 'w': fdgeo.OUT_W, 'h': fdgeo.OUT_H}
        for kk, K in KINDS.items():
            use = [n for n in got if stamp_ms(n) > stamp_ms(got[-1]) - K['hours'] * 3600e3]
            if len(use) < 2: continue
            lst = os.path.join(work, 'list_%s.txt' % kk)
            open(lst, 'w').write(''.join("file '%s'\nduration %.3f\n" % (os.path.join(fd, n), 1.0 / FPS) for n in use) + "file '%s'\n" % os.path.join(fd, use[-1]))
            vf = ['-vf', 'scale=%d:-2' % K['w']] if K['w'] != fdgeo.OUT_W else []
            out = os.path.join(work, '%s_%s.mp4' % (newest, kk))
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst] + vf +
                           ['-r', str(FPS), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(K['crf']), '-g', str(K['g']), '-pix_fmt', 'yuv420p',
                            '-movflags', '+faststart', '-an', out], check=True)
            man[kk] = {'mp4': os.path.basename(out), 'frames': use, 'size': '%dx%d' % (K['w'], K['w'] * fdgeo.OUT_H // fdgeo.OUT_W),
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
                os.replace(os.path.join(work, f), os.path.join(root, '%s_%s_%s' % (sat, sector, f)))
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
        print('%s %-4s %s (%.0f s)' % (k[0], k[1], r, time.time() - t), flush=True)
        return r
    with ThreadPoolExecutor(4) as ex: res = list(ex.map(one, list(state)))
    if all(str(r).startswith('FAILED') or r == 'no frames' for r in res): sys.exit(1)


if __name__ == '__main__':
    main()
