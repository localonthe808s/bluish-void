"""HIMAWARI-9 AND METEOSAT-12 GEOCOLOR AS SMOOTH LOOPS (2026-10-24, user: "see what you can bake/cache and do on cloudflare to make
the forecast videos and these new cloud videos play smoothly").

FORECASTS plays CIRA SLIDER's frames for Himawari-9 and Meteosat-12, 10 minutes apart: a flipbook that jumps. Their GeoColor
(the view they open on) is baked here the way LIVE's GOES loops are (bake.py): SLIDER's whole-sector frame (one 688 px tile,
read through our tiles worker, which caches it), optical-flow in-betweens between 10-minute scans, an MP4 per kind on R2 behind
Cloudflare. Japan scans every 2.5 minutes, so its real frames are already close enough and get none. The other views stay
frames, cached a year at the edge.

    python3 _goesvid/sliderbake.py           (run after bake.py in goes-video.yml; R2 credentials as for bake.py)
"""
import io, json, os, re, shutil, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake                         # its R2, in-between and download helpers (bake.main() does not run on import)
from PIL import Image

EDGE = 'https://tiles.bluishvoid.com/slider/'
BAND = 'geocolor'
LOOPS = [  # (name on R2, SLIDER satellite, sector, hours, in-betweens?)
    ('HIMAWARI', 'himawari', 'full_disk', 6, True),
    ('HIMAWARI', 'himawari', 'japan', 3, False),
    ('METEOSAT12', 'meteosat-12', 'full_disk', 6, True),
]
KINDS = {'d': {'crf': 26, 'g': 12, 'ib': (1, 2, 3)}, 'm': {'crf': 28, 'g': 8, 'ib': (2,)}}
BUDGET_S = 240


def stamp11(t14):
    """'YYYYMMDDHHMMSS' -> 'YYYYDDDHHMM', the name prefix the page's clock reads"""
    doy = time.strptime(t14[:8], '%Y%m%d').tm_yday
    return '%s%03d%s' % (t14[:4], doy, t14[8:12])


def ms(t14):
    return time.mktime(time.strptime(t14[:12], '%Y%m%d%H%M')) - time.timezone


def one(name, sat, sec, hours, interp, t_start):
    key = '%s%s/%s/%s/' % (bake.PREFIX, name, sec, BAND)
    tar_key = '%s_frames/%s_%s_%s_fd.tar' % (bake.PREFIX, name, sec, BAND)
    work = tempfile.mkdtemp(); fd = os.path.join(work, 'frames'); os.makedirs(fd)
    tar_local = os.path.join(work, 'frames.tar'); old = None
    if bake.r2('cp', 's3://%s/%slatest.json' % (bake.BUCKET, key), os.path.join(work, 'old.json'), check=False).returncode == 0:
        try: old = json.load(open(os.path.join(work, 'old.json')))
        except Exception: old = None
    if bake.r2('cp', 's3://%s/%s' % (bake.BUCKET, tar_key), tar_local, check=False).returncode == 0:
        subprocess.run(['tar', '-xf', tar_local, '-C', fd], check=False)
    ts = sorted(str(t) for t in json.loads(bake.get(EDGE + 'json/%s/%s/%s/latest_times.json' % (sat, sec, BAND), 30))['timestamps_int'])
    if not ts: return 'no times'
    ts = [t for t in ts if ms(t) > ms(ts[-1]) - hours * 3600]
    want = {stamp11(t) + '_%s-%s-%s.jpg' % (name, sec, BAND): t for t in ts}
    for f in os.listdir(fd):                                    # out of the window: gone (an in-between with its frame)
        if f not in want and re.sub(r'_f\d\.jpg$', '.jpg', f) not in want: os.remove(os.path.join(fd, f))
    new = 0
    for fn, t in sorted(want.items(), reverse=True):            # newest first
        p = os.path.join(fd, fn)
        if os.path.exists(p): continue
        if time.time() - t_start > BUDGET_S: break
        try:
            raw = bake.get(EDGE + 'imagery/%s/%s/%s/%s---%s/%s/%s/00/000_000.png' % (t[:4], t[4:6], t[6:8], sat, sec, BAND, t), 60)
            Image.open(io.BytesIO(raw)).convert('RGB').save(p, quality=92); new += 1
        except Exception as e:
            print('  %s %s %s: %s' % (name, sec, t, e))
    got = sorted(f for f in want if os.path.exists(os.path.join(fd, f)))
    if len(got) < 2: return 'no frames'
    made = 0
    if interp:
        for i in range(len(got) - 2, -1, -1):
            if time.time() - t_start > BUDGET_S: break
            try:
                if bake.inbetweens(fd, got[i], got[i + 1]): made += 1
            except Exception as e:
                print('  %s %s in-between: %s' % (name, sec, e)); break
    if old and (old.get('d') or {}).get('frames', [None])[-1:] == [got[-1]] and not new and not made:
        return 'no new frame (kept)'
    subprocess.run(['tar', '-cf', tar_local, '-C', fd] + sorted(os.listdir(fd)), check=True)
    bake.r2('cp', tar_local, 's3://%s/%s' % (bake.BUCKET, tar_key), '--content-type', 'application/x-tar', '--cache-control', 'no-store')
    step0 = (ms(ts[-1]) - ms(ts[0])) / 60.0 / max(1, len(ts) - 1)     # minutes between real frames
    newest = got[-1][:11]
    man = {'at': int(time.time()), 'sat': name, 'sector': sec, 'band': BAND, 'fps': bake.FPS, 'src': 'slider', 'step': round(step0, 3)}
    for kk, K in KINDS.items():
        use = []
        for i, n in enumerate(got):
            use.append(n)
            if interp and i < len(got) - 1:
                ib = [n[:-4] + '_f%d.jpg' % k for k in K['ib']]
                if all(os.path.exists(os.path.join(fd, x)) for x in ib): use += ib
        lst = os.path.join(work, 'list_%s.txt' % kk)
        open(lst, 'w').write(''.join("file '%s'\nduration %.3f\n" % (os.path.join(fd, n), 1.0 / bake.FPS) for n in use) + "file '%s'\n" % os.path.join(fd, use[-1]))
        out = os.path.join(work, '%s_%s.mp4' % (newest, kk))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                        '-r', str(bake.FPS), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(K['crf']), '-g', str(K['g']), '-bf', '0',
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', out], check=True)
        kstep = round(step0 * (len(got) - 1) / max(1, len(use) - 1), 3)
        if kk == 'd': man['step'] = kstep
        man[kk] = {'mp4': os.path.basename(out), 'frames': use, 'real': len(got), 'step': kstep, 'bytes': os.path.getsize(out)}
        bake.r2('cp', out, 's3://%s/%s%s' % (bake.BUCKET, key, os.path.basename(out)), '--content-type', 'video/mp4', '--cache-control', 'public, max-age=31536000, immutable')
    poster = os.path.join(work, '%s_p.jpg' % newest)
    Image.open(os.path.join(fd, got[-1])).save(poster, quality=82); man['poster'] = os.path.basename(poster)
    bake.r2('cp', poster, 's3://%s/%s%s' % (bake.BUCKET, key, man['poster']), '--content-type', 'image/jpeg', '--cache-control', 'public, max-age=31536000, immutable')
    p = os.path.join(work, 'latest.json'); json.dump(man, open(p, 'w'), separators=(',', ':'))
    bake.r2('cp', p, 's3://%s/%slatest.json' % (bake.BUCKET, key), '--content-type', 'application/json', '--cache-control', 'public, max-age=60')
    keep = {(man.get(kk) or {}).get('mp4') for kk in KINDS} | {((old or {}).get(kk) or {}).get('mp4') for kk in KINDS} | {man['poster'], (old or {}).get('poster')}
    for f in [x for x in bake.r2('ls', 's3://%s/%s' % (bake.BUCKET, key), check=False).stdout.split() if (x.endswith('.mp4') or x.endswith('_p.jpg')) and x not in keep]:
        bake.r2('rm', 's3://%s/%s%s' % (bake.BUCKET, key, f), check=False)
    shutil.rmtree(work, ignore_errors=True)
    return '%d new, %d in-betweens; ' % (new, made) + ', '.join('%s %d frames %.1f MB' % (kk, len(man[kk]['frames']), man[kk]['bytes'] / 1e6) for kk in KINDS)


def main():
    t_start = time.time()
    for name, sat, sec, hours, interp in LOOPS:
        t = time.time()
        try: r = one(name, sat, sec, hours, interp, t_start)
        except Exception as e: r = 'FAILED %s' % e
        print('%s %-9s %s (%.0f s)' % (name, sec, r, time.time() - t), flush=True)


if __name__ == '__main__':
    main()
