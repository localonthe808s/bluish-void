#!/usr/bin/env python3
"""LAST NIGHT'S MIGRATION AS VIDEO (2026-10-22, user: "lets make it its own tab next foliage and map geology / show the night
before on loop - maybe make this as a video in cloudflare like you did for clouds").

Birds aloft show on the weather radars after dusk as rings of echo round each site. NOAA's MRMS mosaic is quality-controlled
and REMOVES them; Iowa State's national N0Q mosaic does not. A bird-only frame is the N0Q mosaic with everything MRMS calls
rain taken out (grown 2 px so no rain fringe survives), redrawn in amber by strength -- the same recipe as the radar's live
MIGRATION loop in index.html (R.migPaint).

MRMS's map service keeps only the last ~2 hours, so a night cannot be baked after the fact: every run (migration.yml, every
30 minutes) CAPTURES the frames of the last two hours that are not on R2 yet, then BAKES the most recent night into MP4s:

    mig/frames/<YYYYMMDDTHHMM>.png      one bird-only frame per 10 minutes, the lower 48 in web mercator (kept 3 days)
    mig/video/<start>_<n>_d.mp4         desktop, 1600 px wide, birds on black (the page blends it onto the map with `screen`)
    mig/video/<start>_<n>_m.mp4         phones, 800 px wide
    mig/latest.json                     the night on show: its frame times, the box, the two videos

A night runs 22:00 to 14:00 UTC (6 PM to 10 AM Eastern, 3 PM to 7 AM Pacific): dusk to dawn across the lower 48. The night on
show is the newest finished one; until a finished night has frames (the first day), the night in progress.

    python3 _migvid/bake.py              # capture + bake (aws cli + R2 env in CI; the local rclone remote `r2:` otherwise)
    python3 _migvid/bake.py --dry        # capture into /tmp/migvid and bake there, nothing uploaded
"""
import io, json, math, os, shutil, subprocess, sys, tempfile, time, urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image

DRY = '--dry' in sys.argv
BUCKET = 'bluishvoid-bg'
UA = {'User-Agent': 'bluishvoid.com migration bake'}
STEP = 600                                   # seconds between frames
W_LON, E_LON, S_LAT, N_LAT = -126.0, -66.0, 23.0, 50.0
WD = 1600                                    # desktop width; phones get half
FPS = 10
LOCAL = '/tmp/migvid'

R = 6378137.0
def merc(lon, lat):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
X0, Y0 = merc(W_LON, S_LAT)
X1, Y1 = merc(E_LON, N_LAT)
HD = int(round(WD * (Y1 - Y0) / (X1 - X0)))
BOX = '%.0f,%.0f,%.0f,%.0f' % (X0, Y0, X1, Y1)


def get(url, timeout=60):
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception:
            if i == 2: raise
            time.sleep(3)


# ---- storage: R2 through the aws cli in CI, the rclone remote locally, a folder for --dry
def store_ls(prefix):
    if DRY:
        d = os.path.join(LOCAL, prefix)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []
    if os.environ.get('R2_ACCOUNT_ID'):
        r = subprocess.run(['aws', 's3', 'ls', 's3://%s/%s' % (BUCKET, prefix), '--endpoint-url',
                            'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID']], capture_output=True, text=True)
        return sorted(l.split()[-1] for l in r.stdout.splitlines() if l.strip() and not l.strip().startswith('PRE'))
    r = subprocess.run(['rclone', 'lsf', 'r2:%s/%s' % (BUCKET, prefix), '--s3-no-check-bucket'], capture_output=True, text=True)
    return sorted(l.strip() for l in r.stdout.splitlines() if l.strip())


def store_put(path, key, ctype, cache):
    if DRY:
        d = os.path.join(LOCAL, os.path.dirname(key)); os.makedirs(d, exist_ok=True); shutil.copy(path, os.path.join(LOCAL, key)); return
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', path, 's3://%s/%s' % (BUCKET, key), '--content-type', ctype, '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
        return
    subprocess.run(['rclone', 'copyto', path, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                    '--header-upload', 'Content-Type: ' + ctype, '--header-upload', 'Cache-Control: ' + cache], check=True)


def store_get(key, path):
    if DRY:
        shutil.copy(os.path.join(LOCAL, key), path); return
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', 's3://%s/%s' % (BUCKET, key), path, '--endpoint-url',
                        'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
        return
    subprocess.run(['rclone', 'copyto', 'r2:%s/%s' % (BUCKET, key), path, '--s3-no-check-bucket'], check=True)


def store_rm(key):
    if DRY:
        try: os.remove(os.path.join(LOCAL, key))
        except OSError: pass
        return
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'rm', 's3://%s/%s' % (BUCKET, key), '--endpoint-url',
                        'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'])
        return
    subprocess.run(['rclone', 'deletefile', 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket'])


# ---- one bird-only frame
def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def qcd_times():
    x = get('https://opengeo.ncep.noaa.gov/geoserver/conus/ows?service=WMS&request=GetCapabilities', 90).decode('utf-8', 'replace')
    i = x.find('<Name>conus_bref_qcd</Name>'); d = x.find('<Dimension name="time"', i); e = x.find('</Dimension>', d)
    if i < 0 or d < 0: return []
    out = []
    for t in x[x.find('>', d) + 1:e].split(','):
        try: out.append(datetime.strptime(t.strip()[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc).timestamp())
        except ValueError: pass
    return sorted(out)


def wms(base, layer, ts):
    return (base + '?service=WMS&version=1.1.1&request=GetMap&layers=' + layer + '&styles=&format=image/png&transparent=true'
            '&srs=EPSG:3857&bbox=' + BOX + '&width=%d&height=%d' % (WD, HD) + ('&time=' + iso(ts) if ts else ''))


def bird_frame(ts, qts):
    near = min(qts, key=lambda q: abs(q - ts)) if qts else None
    if near is None or abs(near - ts) > 240: return None          # no rain picture to take out: try again next run
    raw = Image.open(io.BytesIO(get(wms('https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi', 'nexrad-n0q-wmst', ts)))).convert('RGBA')
    qc = Image.open(io.BytesIO(get(wms('https://opengeo.ncep.noaa.gov/geoserver/conus/ows', 'conus_bref_qcd', near)))).convert('RGBA')
    a = np.asarray(raw).astype(np.int16); q = np.asarray(qc)
    rain = q[:, :, 3] > 24
    m = rain.copy()                                             # grown 2 px each way
    for k in (1, 2):
        m[:, k:] |= rain[:, :-k]; m[:, :-k] |= rain[:, k:]
    m2 = m.copy()
    for k in (1, 2):
        m2[k:, :] |= m[:-k, :]; m2[:-k, :] |= m[k:, :]
    keep = (a[:, :, 3] > 0) & ~m2
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mx = np.maximum(np.maximum(r, g), b); mn = np.minimum(np.minimum(r, g), b); dl = np.maximum(mx - mn, 1)
    h = np.where(mx == r, ((g - b) / dl) % 6, np.where(mx == g, (b - r) / dl + 2, (r - g) / dl + 4)) * 60
    lev = np.where(h > 205, 0, np.where(h > 185, 1, 2))
    out = np.zeros((HD, WD, 4), np.uint8)
    out[:, :, 0] = 255
    out[:, :, 1] = np.choose(lev, [214, 170, 128])
    out[:, :, 2] = np.choose(lev, [150, 70, 20])
    out[:, :, 3] = np.where(keep, np.choose(lev, [120, 185, 235]), 0)
    buf = io.BytesIO(); Image.fromarray(out).save(buf, 'PNG', optimize=True)
    return buf.getvalue(), float(keep.mean())


def capture(work):
    have = set(store_ls('mig/frames/'))
    now = time.time()
    end = math.floor((now - 8 * 60) / STEP) * STEP
    want = [end - k * STEP for k in range(11, -1, -1)]           # the last two hours MRMS can still answer for
    todo = [t for t in want if datetime.fromtimestamp(t, timezone.utc).strftime('%Y%m%dT%H%M') + '.png' not in have]
    if not todo:
        print('capture: nothing new'); return 0
    qts = qcd_times()
    print('capture: %d to fetch, MRMS keeps %s..%s' % (len(todo), iso(qts[0]) if qts else '-', iso(qts[-1]) if qts else '-'))
    n = 0
    for t in todo:
        name = datetime.fromtimestamp(t, timezone.utc).strftime('%Y%m%dT%H%M') + '.png'
        try:
            fr = bird_frame(t, qts)
        except Exception as e:
            print('  %s failed: %s' % (name, e)); continue
        if not fr:
            print('  %s: no MRMS frame within 4 min' % name); continue
        p = os.path.join(work, name); open(p, 'wb').write(fr[0])
        store_put(p, 'mig/frames/' + name, 'image/png', 'public, max-age=31536000, immutable')
        print('  %s  echo over %.1f%% of the lower 48' % (name, 100 * fr[1])); n += 1
    return n


# ---- the night on show
def nights(now):
    """[start, end) of the newest finished night and of the night in progress, as UTC seconds."""
    d = datetime.fromtimestamp(now, timezone.utc)
    end = d.replace(hour=14, minute=0, second=0, microsecond=0)
    if end.timestamp() > now: end -= timedelta(days=1)
    fin = (end - timedelta(hours=16)).timestamp(), end.timestamp()
    return fin, (fin[0] + 86400, fin[1] + 86400)


def bake(work):
    have = store_ls('mig/frames/')
    def stamps(a, b):
        out = []
        for nm in have:
            try: t = datetime.strptime(nm[:13], '%Y%m%dT%H%M').replace(tzinfo=timezone.utc).timestamp()
            except ValueError: continue
            if a <= t < b: out.append((t, nm))
        return out
    fin, cur = nights(time.time())
    fr = stamps(*fin)
    night = fin
    if len(fr) < 12:
        fr = stamps(*cur); night = cur
    if len(fr) < 6:
        print('bake: only %d frames for any night yet' % len(fr)); return
    start = datetime.fromtimestamp(night[0], timezone.utc).strftime('%Y%m%dT%H%M')
    old = None
    if not DRY:
        p = os.path.join(work, 'old.json')
        try:
            store_get('mig/latest.json', p); old = json.load(open(p))
        except Exception:
            old = None
    elif os.path.exists(os.path.join(LOCAL, 'mig/latest.json')):
        old = json.load(open(os.path.join(LOCAL, 'mig/latest.json')))
    if old and old.get('start') == start and old.get('n') == len(fr):
        print('bake: %s already baked with %d frames' % (start, len(fr))); return
    fd = os.path.join(work, 'f'); os.makedirs(fd, exist_ok=True)
    for i, (t, nm) in enumerate(fr):
        src = os.path.join(work, 'src_' + nm)
        if not os.path.exists(src): store_get('mig/frames/' + nm, src)
        im = Image.open(src).convert('RGBA'); bg = Image.new('RGBA', im.size, (0, 0, 0, 255)); bg.alpha_composite(im)
        bg.convert('RGB').save(os.path.join(fd, '%04d.png' % i))
    man = {'start': start, 'night': [iso(night[0]), iso(night[1])], 'n': len(fr), 'fps': FPS, 'step': STEP,
           'times': [iso(t) for t, _ in fr], 'bbox': [W_LON, S_LAT, E_LON, N_LAT], 'at': int(time.time()),
           'finished': night == fin}
    for kind, w, crf in (('d', WD, 21), ('m', WD // 2, 23)):
        out = os.path.join(work, '%s_%d_%s.mp4' % (start, len(fr), kind))
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', os.path.join(fd, '%04d.png'),
                        '-vf', 'scale=%d:-2:flags=area' % w, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', str(crf),
                        '-g', '10', '-movflags', '+faststart', out], check=True)
        key = 'mig/video/' + os.path.basename(out)
        store_put(out, key, 'video/mp4', 'public, max-age=31536000, immutable')
        man[kind] = key
        print('bake: %s %.1f MB' % (key, os.path.getsize(out) / 1e6))
    mp = os.path.join(work, 'latest.json'); json.dump(man, open(mp, 'w'), separators=(',', ':'))
    store_put(mp, 'mig/latest.json', 'application/json', 'public, max-age=120')
    # disposal: the previous generation stays (a viewer may have just read the old latest.json); older ones go
    if old:
        keep = {man['d'], man['m'], old.get('d'), old.get('m')}
        for nm in store_ls('mig/video/'):
            if 'mig/video/' + nm not in keep: store_rm('mig/video/' + nm)


def tidy():
    cut = (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%Y%m%dT%H%M')
    for nm in store_ls('mig/frames/'):
        if nm[:13] < cut: store_rm('mig/frames/' + nm)


if __name__ == '__main__':
    work = tempfile.mkdtemp(prefix='migvid')
    try:
        capture(work)
        bake(work)
        tidy()
    finally:
        shutil.rmtree(work, ignore_errors=True)
