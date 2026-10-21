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


def listing(sat, sector):
    for base in (EDGE, NESDIS):
        try:
            html = get('%s%s/ABI/SECTOR/%s/%s/' % (base, sat, sector, BAND), 25).decode('utf-8', 'replace')
            names = sorted(set(re.findall(r'href="(\d{11}_%s-ABI-%s-%s-\d+x\d+\.jpg)"' % (sat, sector, BAND), html)))
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
    man = {'at': int(time.time()), 'sat': sat, 'sector': sector, 'band': BAND, 'fps': FPS}
    for k, K in KINDS.items():
        sizes = sorted({re.search(r'-(\d+)x(\d+)\.jpg$', n).group(0)[1:-4] for n in names}, key=lambda z: int(z.split('x')[0]))
        size = K['size'] if K['size'] in sizes else next((z for z in sizes if int(z.split('x')[0]) >= K['min']), sizes[-1] if sizes else None)
        fr = [n for n in names if n.endswith('-%s.jpg' % size)]
        if len(fr) < 2: continue
        t1 = stamp_ms(fr[-1]); fr = [n for n in fr if stamp_ms(n) > t1 - K['hours'] * 3600e3]
        newest = fr[-1][:11]
        if old and (old.get(k) or {}).get('frames', [None])[-1:] == [fr[-1]]:
            man[k] = old[k]; continue                                   # no new frame since the last run: keep that video
        d = os.path.join(work, k); os.makedirs(d, exist_ok=True)
        def dl(ix):
            i, n = ix
            for base in (EDGE, NESDIS):
                try:
                    b = get('%s%s/ABI/SECTOR/%s/%s/%s' % (base, sat, sector, BAND, n))
                    if len(b) > 5000:
                        open(os.path.join(d, '%03d.jpg' % i), 'wb').write(b); return True
                except Exception:
                    pass
            return False
        with ThreadPoolExecutor(8) as ex: ok = list(ex.map(dl, enumerate(fr)))
        got = [n for n, o in zip(fr, ok) if o]
        if len(got) < 2: continue
        # renumber without holes for ffmpeg's image2 pattern
        for j, i in enumerate([i for i, o in enumerate(ok) if o]):
            if i != j: os.replace(os.path.join(d, '%03d.jpg' % i), os.path.join(d, '%03d.jpg' % j))
        out = os.path.join(work, '%s_%s.mp4' % (newest, k))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(FPS), '-i', os.path.join(d, '%03d.jpg'),
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(K['crf']), '-g', str(K['g']), '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart', '-an', out], check=True)
        man[k] = {'mp4': os.path.basename(out), 'frames': got, 'size': size, 'bytes': os.path.getsize(out)}
        if not DRY:
            r2('cp', out, 's3://%s/%s%s' % (BUCKET, key, os.path.basename(out)), '--content-type', 'video/mp4',
               '--cache-control', 'public, max-age=31536000, immutable')
    if not any(k in man for k in KINDS): return 'no frames'
    p = os.path.join(work, 'latest.json'); json.dump(man, open(p, 'w'), separators=(',', ':'))
    if DRY:
        return 'dry: ' + ', '.join('%s %d frames %.1f MB' % (k, len(man[k]['frames']), man[k]['bytes'] / 1e6) for k in KINDS if k in man)
    r2('cp', p, 's3://%s/%slatest.json' % (BUCKET, key), '--content-type', 'application/json', '--cache-control', 'public, max-age=60')
    # two generations kept: the current and the one before (old); anything else of ours under this key goes
    keep = {(man.get(k) or {}).get('mp4') for k in KINDS} | {((old or {}).get(k) or {}).get('mp4') for k in KINDS}
    ls = r2('ls', 's3://%s/%s' % (BUCKET, key), check=False).stdout.split()
    for f in [x for x in ls if x.endswith('.mp4') and x not in keep]:
        r2('rm', 's3://%s/%s%s' % (BUCKET, key, f), check=False)
    return ', '.join('%s %d frames %.1f MB%s' % (k, len(man[k]['frames']), man[k]['bytes'] / 1e6, '' if man[k] is not (old or {}).get(k) else ' (kept)') for k in KINDS if k in man)


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
