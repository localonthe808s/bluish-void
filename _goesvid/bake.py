#!/usr/bin/env python3
"""LIVE CLOUDS AS VIDEO (2026-10-20, user: "yes build it").

The LIVE CLOUDS loop was 72 separate 1200 px NESDIS frames on desktop (~64 MB, 6 h) and 24 at 600 px on phones (2 h). This
bakes each loop into one MP4 every 10 minutes (goes-video.yml, started by the Kalshi cron worker at :03/:13/...):

    goes/video/<sat>/<sector>/GEOCOLOR/<newest>_d.mp4   desktop: the last 6 h of 1200 px frames, a keyframe every 4th frame
    goes/video/<sat>/<sector>/GEOCOLOR/<newest>_m.mp4   phones:  the last 2 h of 600 px frames, every frame a keyframe
    goes/video/<sat>/<sector>/GEOCOLOR/latest.json      which videos are current, and each frame's name (its UTC time)

The page plays the video as the same flipbook it played the frames as, seeking to frame i at (i + 0.5) / FPS, so the time
label, the map overlay, the zoom and the hold at the end are unchanged. Keyframes keep those seeks cheap.

A video's name carries its newest frame's time and never changes: cached for a year. latest.json is cached 60 s (and the page
asks for it by the minute). DISPOSAL: after a new latest.json is up, the videos two generations old are deleted (the previous
generation stays, for a viewer who read the old latest.json a moment ago); an R2 lifecycle rule deletes anything under
goes/video/ older than a day, should a run die between the two. Storage stays at two generations: ~15 sectors x ~11 MB x 2.

Frames come through tiles.bluishvoid.com/goes/ (our edge cache of NESDIS, a year per frame), NESDIS directly as the fallback.

    python3 _goesvid/bake.py            # all sectors (needs ffmpeg, the aws cli and the R2 env: R2_ACCOUNT_ID, AWS_* keys)
    python3 _goesvid/bake.py --dry ne   # one sector, no upload: writes the videos to /tmp/goesvid
"""
import json, os, re, subprocess, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

SECTORS = [('GOES19', s) for s in ('ne', 'se', 'cgl', 'umv', 'smv', 'sp', 'nr', 'sr', 'eus', 'taw', 'pr')] + \
          [('GOES18', s) for s in ('pnw', 'psw', 'np', 'ep')]          # the sectors index.html's areaToGoes and LOCATION open on
BAND, FPS = 'GEOCOLOR', 10
# GEOCOLOR CAN FREEZE ON ITS OWN (10-20: every sector's stopped at 15:11 UTC while the ABI bands kept coming): over an hour old,
# and with NESDIS's Day Night Cloud Micro Combo fresher, the video is baked from that (the page falls back the same way) and
# latest.json says which band it is
FB_BAND = 'DayNightCloudMicroCombo'
EDGE, NESDIS = 'https://tiles.bluishvoid.com/goes/', 'https://cdn.star.nesdis.noaa.gov/'
BUCKET, PREFIX = 'bluishvoid-bg', 'goes/video/'
# the size per kind: the square the page prefers when the sector has it, else the smallest at least `min` px wide (eus is
# 250-4000 px squares, taw and np 450x270-7200x4320 wide frames)
KINDS = {'d': {'size': '1200x1200', 'min': 900, 'hours': 6, 'crf': 22, 'g': 4},
         'm': {'size': '600x600', 'min': 500, 'hours': 2, 'crf': 23, 'g': 1}}
UA = {'User-Agent': 'bluishvoid.com satellite loop bake'}
DRY = '--dry' in sys.argv


def get(url, timeout=20):
    for i in range(2):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception:
            if i == 1: raise
            time.sleep(2)


def stamp_ms(name):
    y, d, h, m = int(name[:4]), int(name[4:7]), int(name[7:9]), int(name[9:11])
    return (time.mktime((y, 1, 1, 0, 0, 0, 0, 0, 0)) - time.timezone + (d - 1) * 86400 + h * 3600 + m * 60) * 1000


def listing(sat, sector, band=BAND):
    for base in (EDGE, NESDIS):
        try:
            html = get('%s%s/ABI/SECTOR/%s/%s/' % (base, sat, sector, band), 25).decode('utf-8', 'replace')
            names = sorted(set(re.findall(r'href="(\d{11}_%s-ABI-%s-%s-\d+x\d+\.jpg)"' % (sat, sector, band), html)))
            if names: return names
        except Exception as e:
            print('  %s %s listing via %s failed: %s' % (sat, sector, base, e))
    return []


def r2(*args, check=True):
    cmd = ['aws', 's3'] + list(args) + ['--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors']
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def bake(sat, sector, work):
    names = listing(sat, sector)
    if not names: return 'no listing'
    key = '%s%s/%s/%s/' % (PREFIX, sat, sector, BAND)
    old = None
    if not DRY:
        p = os.path.join(work, 'old.json')
        if r2('cp', 's3://%s/%slatest.json' % (BUCKET, key), p, check=False).returncode == 0:
            try: old = json.load(open(p))
            except Exception: old = None
    band = BAND
    if names and time.time() * 1000 - stamp_ms(names[-1]) > 3600e3:
        fb = listing(sat, sector, FB_BAND)
        if fb and stamp_ms(fb[-1]) > stamp_ms(names[-1]) + 1800e3: names, band = fb, FB_BAND
    man = {'at': int(time.time()), 'sat': sat, 'sector': sector, 'band': band, 'fps': FPS}
    D = KINDS['d']
    sizes = sorted({re.search(r'-(\d+x\d+)\.jpg$', n).group(1) for n in names}, key=lambda z: int(z.split('x')[0]))
    size = D['size'] if D['size'] in sizes else next((z for z in sizes if int(z.split('x')[0]) >= D['min']), sizes[-1] if sizes else None)
    fr = [n for n in names if n.endswith('-%s.jpg' % size)]
    if len(fr) < 2: return 'no frames'
    t1 = stamp_ms(fr[-1]); fr = [n for n in fr if stamp_ms(n) > t1 - D['hours'] * 3600e3]
    if old and (old.get('d') or {}).get('frames', [None])[-1:] == [fr[-1]] and old.get('m'):
        return 'no new frame (kept)'                                # nothing new since the last run: the videos stand
    # THE FRAMES BETWEEN RUNS (2026-10-20, user: "how can we downsize its cost"): the last run's frames are one tar per
    # sector on R2 (read and written over the S3 API, not through the tiles worker), so a run fetches only the frames that
    # are new -- one or two per sector -- instead of all 72 (~1,000 worker reads a run, ~4.5 M a month, down to ~30).
    fd = os.path.join(work, 'frames'); os.makedirs(fd, exist_ok=True)
    tar_key = '%s_frames/%s_%s.tar' % (PREFIX, sat, sector)
    tar_local = os.path.join('/tmp/goesvid/_frames', '%s_%s.tar' % (sat, sector)) if DRY else os.path.join(work, 'frames.tar')
    if DRY: os.makedirs(os.path.dirname(tar_local), exist_ok=True)
    if (os.path.exists(tar_local) if DRY else r2('cp', 's3://%s/%s' % (BUCKET, tar_key), tar_local, check=False).returncode == 0):
        subprocess.run(['tar', '-xf', tar_local, '-C', fd], check=False)
    want = set(fr)
    for f in os.listdir(fd):
        if f not in want: os.remove(os.path.join(fd, f))       # out of the 6 h window, or another size
    miss = [n for n in fr if not os.path.exists(os.path.join(fd, n))]
    def dl(n):
        for base in (EDGE, NESDIS):
            try:
                b = get('%s%s/ABI/SECTOR/%s/%s/%s' % (base, sat, sector, band, n))
                if len(b) > 5000:
                    open(os.path.join(fd, n), 'wb').write(b); return True
            except Exception:
                pass
        return False
    with ThreadPoolExecutor(8) as ex: fetched = sum(ex.map(dl, miss))
    got = [n for n in fr if os.path.exists(os.path.join(fd, n))]
    if len(got) < 2: return 'no frames'
    if fetched:
        subprocess.run(['tar', '-cf', tar_local, '-C', fd] + got, check=True)
        if not DRY: r2('cp', tar_local, 's3://%s/%s' % (BUCKET, tar_key), '--content-type', 'application/x-tar', '--cache-control', 'no-store')
    newest = got[-1][:11]
    # the phone video is the last 2 h of the SAME frames, made smaller (no second set of 600 px downloads)
    w0 = int(size.split('x')[0])
    for k, K in KINDS.items():
        use = [n for n in got if stamp_ms(n) > stamp_ms(got[-1]) - K['hours'] * 3600e3]
        if len(use) < 2: continue
        lst = os.path.join(work, 'list_%s.txt' % k)
        open(lst, 'w').write(''.join("file '%s'\nduration %.3f\n" % (os.path.join(fd, n), 1.0 / FPS) for n in use) + "file '%s'\n" % os.path.join(fd, use[-1]))
        vf = ['-vf', 'scale=600:-2'] if k == 'm' and w0 > 700 else []
        out = os.path.join(work, '%s_%s.mp4' % (newest, k))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst] + vf +
                       ['-r', str(FPS), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(K['crf']), '-g', str(K['g']), '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart', '-an', out], check=True)
        man[k] = {'mp4': os.path.basename(out), 'frames': use, 'size': size if not vf else '600', 'bytes': os.path.getsize(out), 'fetched': fetched}
        if not DRY:
            r2('cp', out, 's3://%s/%s%s' % (BUCKET, key, os.path.basename(out)), '--content-type', 'video/mp4',
               '--cache-control', 'public, max-age=31536000, immutable')
    if not any(k in man for k in KINDS): return 'no frames'
    p = os.path.join(work, 'latest.json'); json.dump(man, open(p, 'w'), separators=(',', ':'))
    if DRY:
        return ('dry, fetched %d; ' % fetched) + ', '.join('%s %d frames %.1f MB' % (k, len(man[k]['frames']), man[k]['bytes'] / 1e6) for k in KINDS if k in man)
    r2('cp', p, 's3://%s/%slatest.json' % (BUCKET, key), '--content-type', 'application/json', '--cache-control', 'public, max-age=60')
    # two generations kept: the current and the one before (old); anything else of ours under this key goes
    keep = {(man.get(k) or {}).get('mp4') for k in KINDS} | {((old or {}).get(k) or {}).get('mp4') for k in KINDS}
    ls = r2('ls', 's3://%s/%s' % (BUCKET, key), check=False).stdout.split()
    for f in [x for x in ls if x.endswith('.mp4') and x not in keep]:
        r2('rm', 's3://%s/%s%s' % (BUCKET, key, f), check=False)
    return ('fetched %d new; ' % fetched) + ', '.join('%s %d frames %.1f MB' % (k, len(man[k]['frames']), man[k]['bytes'] / 1e6) for k in KINDS if k in man)


def main():
    only = sys.argv[sys.argv.index('--dry') + 1] if DRY and len(sys.argv) > sys.argv.index('--dry') + 1 else None
    secs = [s for s in SECTORS if not only or s[1] == only]
    def one(ss):
        sat, sector = ss; t = time.time()
        with tempfile.TemporaryDirectory(dir='/tmp/goesvid' if DRY and os.makedirs('/tmp/goesvid', exist_ok=True) is None else None) as work:
            try:
                r = bake(sat, sector, work)
                if DRY:
                    for f in os.listdir(work):
                        if f.endswith('.mp4') or f == 'latest.json': os.replace(os.path.join(work, f), os.path.join('/tmp/goesvid', f))
            except Exception as e:
                r = 'FAILED %s' % e
        print('%s %-4s %s (%.0f s)' % (sat, sector, r, time.time() - t), flush=True)
        return r
    # five at a time: one slow sector (ep's listing hung 285 s on the first run) no longer holds up the rest
    with ThreadPoolExecutor(5) as ex: res = list(ex.map(one, secs))
    fails = sum(1 for r in res if str(r).startswith('FAILED') or r in ('no listing', 'no frames'))
    if fails == len(secs): sys.exit(1)


if __name__ == '__main__':
    main()
