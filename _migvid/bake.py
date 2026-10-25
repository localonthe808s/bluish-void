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
import io, json, math, os, re, shutil, struct, subprocess, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image

DRY = '--dry' in sys.argv
BUCKET = 'bluishvoid-bg'
UA = {'User-Agent': 'bluishvoid.com migration bake'}
STEP = 600                                   # seconds between frames
FILT = 2                                     # the cleaning rules' version (2: daylight + standing clutter); a night baked under another re-bakes
FPS = 10
LOCAL = '/tmp/migvid'
# ffmpeg: on the PATH locally; in CI the static binary pip's imageio-ffmpeg ships (Ubuntu's apt mirror crawled at a minute a
# package on 10-23 and timed the step out twice)
def ffmpeg_bin():
    w = shutil.which('ffmpeg')
    if w: return w
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

R = 6378137.0
def merc(lon, lat):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
def unmerc(x, y):
    return math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)
# THE CONTINENT (2026-10-23, user: "bake in canadian radar ... merge mutual views into full continental"). Frames were the lower
# 48 (-126..-66, 23..50 N) at 1600 px; Canada's radars reach 59 N and from 130 W to 50 W, so the frame grows by whole pixels at
# the SAME scale -- 100 px west, 440 east, 420 north -- and a frame captured before (1600 px wide) is pasted in at (100, 420).
WD0 = 1600
_X0o, _Y0o = merc(-126.0, 23.0); _X1o, _Y1o = merc(-66.0, 50.0)
HD0 = int(round(WD0 * (_Y1o - _Y0o) / (_X1o - _X0o)))
SC = WD0 / (_X1o - _X0o)                                   # px per metre
PADL, PADT = 100, 420
WD, HD = 2140, HD0 + PADT                                  # desktop size; phones get half
X0, Y0 = _X0o - PADL / SC, _Y0o
X1, Y1 = X0 + WD / SC, Y0 + HD / SC
W_LON, S_LAT = unmerc(X0, Y0); E_LON, N_LAT = unmerc(X1, Y1)
BOX = '%.0f,%.0f,%.0f,%.0f' % (X0, Y0, X1, Y1)


def frame_img(path):
    """a stored frame on the continental grid (frames from the lower-48 box padded in)"""
    im = Image.open(path).convert('RGBA')
    if im.size == (WD, HD): return im
    bg = Image.new('RGBA', (WD, HD), (0, 0, 0, 0)); bg.paste(im, (PADL, PADT)); return bg


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
    try:
        ca = canada(ts)
    except Exception as e:
        print('  canada failed: %s' % e); ca = None
    if ca is not None:
        m = ca[:, :, 3] > out[:, :, 3]                          # the radar that sees more birds wins where both do
        out[m] = ca[m]
    buf = io.BytesIO(); Image.fromarray(out).save(buf, 'PNG', optimize=True)
    return buf.getvalue(), float((out[:, :, 3] > 0).mean())


# ---- CANADA (2026-10-23). Environment Canada's ~31 S-band radars see the birds too, but its national composite is a filtered
# rain/snow rate. Each radar's own CAPPI image (dd.weather.gc.ca, every 6 min, 480 x 480 at 1 km a pixel, the radar at (240, 239),
# north up, a fixed 14-step palette) is NOT filtered: on a clear night it is all pale-blue speckle -- birds. Echo pixels are
# placed on the grid by their km east / north of the radar; a grid cell gets the SHARE of its 1 km pixels that are lit (speckle
# stays light, a solid flight goes solid) at the strongest palette step seen; whatever MSC's filtered rain composite
# (RADAR_1KM_RRAI, 3 h of 6-min times, CORS-open) calls precipitation, grown 2 px, is removed.
CA = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'radars_ca.json')))
DD = 'https://dd.weather.gc.ca/today/radar/CAPPI/GIF/'
CA_LEV = {(153, 204, 255): 0, (0, 153, 255): 1}               # 7 and 23 dBZ; every warmer palette colour is "heavy"
CA_ECHO = [(153, 204, 255), (0, 153, 255), (0, 255, 102), (0, 204, 0), (0, 153, 0), (255, 255, 51), (255, 204, 0), (255, 153, 0),
           (255, 102, 0), (255, 0, 0), (255, 0, 153), (153, 51, 204), (102, 0, 153)]
_CA_LIST = {}


def ca_names(site):
    if site not in _CA_LIST:
        try: _CA_LIST[site] = re.findall(r'href="(\d{12}_' + site + r'_CAPPI_1\.5_RAIN\.gif)"', get(DD + site + '/', 30).decode())
        except Exception: _CA_LIST[site] = []
    return _CA_LIST[site]


def canada(ts):
    want = datetime.fromtimestamp(ts, timezone.utc)
    t6 = datetime.fromtimestamp(round(ts / 360) * 360, timezone.utc)
    try:
        rr = Image.open(io.BytesIO(get('https://geo.weather.gc.ca/geomet?service=WMS&version=1.3.0&request=GetMap&layers=RADAR_1KM_RRAI&styles='
                                       '&crs=EPSG:3857&bbox=' + BOX + '&width=%d&height=%d&format=image/png&transparent=true&time=%s' % (WD, HD, t6.strftime('%Y-%m-%dT%H:%M:00Z')), 60))).convert('RGBA')
        rain = np.asarray(rr)[:, :, 3] > 24
    except Exception:
        return None                                                 # no rain picture: cannot tell rain from birds
    m = rain.copy()
    for k in (1, 2):
        m[:, k:] |= rain[:, :-k]; m[:, :-k] |= rain[:, k:]
    rain = m.copy()
    for k in (1, 2):
        rain[k:, :] |= m[:-k, :]; rain[:-k, :] |= m[k:, :]
    lit = np.zeros((HD, WD), np.float32); tot = np.zeros((HD, WD), np.float32); lev = np.zeros((HD, WD), np.int8) - 1
    yy, xx = np.mgrid[2:478, 2:478]; rr2 = (xx - 240) ** 2 + (yy - 239) ** 2; inr = rr2 <= 238 ** 2
    def one(site):
        names = ca_names(site)
        c = [(abs((datetime.strptime(n[:12], '%Y%m%d%H%M').replace(tzinfo=timezone.utc) - want).total_seconds()), n) for n in names]
        c = [q for q in c if q[0] <= 360]
        if not c: return None
        try: im = Image.open(io.BytesIO(get(DD + site + '/' + min(c)[1], 30))).convert('RGB')
        except Exception: return None
        return site, np.asarray(im)[2:478, 2:478]
    for res in POOL.map(one, list(CA)):
        if not res: continue
        site, a = res; lo0, la0 = CA[site]
        dy = 239 - yy; dx = xx - 240
        la = la0 + dy / 111.32; lo = lo0 + dx / (111.32 * np.cos(np.radians(la)))
        gx = ((np.radians(lo) * R - X0) * SC).astype(int); gy = ((Y1 - R * np.log(np.tan(np.pi / 4 + np.radians(la) / 2))) * SC).astype(int)
        ok = inr & (gx >= 0) & (gx < WD) & (gy >= 0) & (gy < HD)
        flat = a.reshape(-1, 3)
        code = np.full(flat.shape[0], -1, np.int8)
        for ci, col in enumerate(CA_ECHO):
            code[(flat[:, 0] == col[0]) & (flat[:, 1] == col[1]) & (flat[:, 2] == col[2])] = min(ci, 2)
        code = code.reshape(a.shape[:2])
        gxo, gyo, cd = gx[ok], gy[ok], code[ok]
        np.add.at(tot, (gyo, gxo), 1)
        e = cd >= 0
        np.add.at(lit, (gyo[e], gxo[e]), 1)
        np.maximum.at(lev, (gyo[e], gxo[e]), cd[e])
    frac = np.where(tot > 0, lit / np.maximum(tot, 1), 0)
    keep = (frac > 0.04) & (lev >= 0) & ~rain
    out = np.zeros((HD, WD, 4), np.uint8)
    L = np.clip(lev, 0, 2)
    out[:, :, 0] = 255; out[:, :, 1] = np.choose(L, [214, 170, 128]); out[:, :, 2] = np.choose(L, [150, 70, 20])
    out[:, :, 3] = np.where(keep, (np.choose(L, [120, 185, 235]) * np.clip(frac * 2.2, 0.35, 1)).astype(np.uint8), 0)
    return out


def capture(work):
    have = set(store_ls('mig/frames/'))
    now = time.time()
    end = math.floor((now - 8 * 60) / STEP) * STEP
    want = [end - k * STEP for k in range(11, -1, -1)]           # the last two hours MRMS can still answer for
    todo = [t for t in want if datetime.fromtimestamp(t, timezone.utc).strftime('%Y%m%dT%H%M') + '.png' not in have]
    qts = qcd_times() if todo else []
    if not todo: print('capture: nothing new')
    if todo: print('capture: %d to fetch, MRMS keeps %s..%s' % (len(todo), iso(qts[0]) if qts else '-', iso(qts[-1]) if qts else '-'))
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
        print('  %s  echo over %.1f%% of the continent' % (name, 100 * fr[1])); n += 1
    # frames captured on the lower-48 box: Canada added while MSC's rain composite still covers them (3 h)
    for nm in sorted(have):
        if not nm.endswith('.png'): continue
        try: t = datetime.strptime(nm[:13], '%Y%m%dT%H%M').replace(tzinfo=timezone.utc).timestamp()
        except ValueError: continue
        if now - t > 2.8 * 3600: continue
        p = os.path.join(work, 'up_' + nm); store_get('mig/frames/' + nm, p)
        if Image.open(p).size == (WD, HD): continue
        try: ca = canada(t)
        except Exception: ca = None
        if ca is None: continue
        a = np.asarray(frame_img(p)).copy(); m = ca[:, :, 3] > a[:, :, 3]; a[m] = ca[m]
        Image.fromarray(a).save(p, 'PNG', optimize=True)
        store_put(p, 'mig/frames/' + nm, 'image/png', 'public, max-age=31536000, immutable')
        print('  %s  Canada added' % nm); n += 1
    return n


# ---- THE BIRDS' OWN DIRECTION (2026-10-22, user: "is there a way to show their overall path?"). Every NEXRAD publishes a VAD
# wind profile (Level III NVW, ~every 9 min, Unidata's public bucket): the speed and direction the echoes aloft are moving,
# by height. On a migration night the echoes ARE the birds, so the profile is their ground track -- the same measurement
# BirdCast's flow maps are built on. Per radar and frame: the newest column of the profile within 12 min, the levels from
# 1,000 to 5,000 ft (where most night migrants fly) averaged as vectors -> [heading TOWARD (deg), knots, levels].
L3 = 'https://unidata-nexrad-level3.s3.amazonaws.com/'
RADARS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'radars.json')))
POOL = ThreadPoolExecutor(24)


def nvw_parse(b):
    o = 20
    while struct.unpack('>h', b[o:o + 2])[0] != 48: o += 1
    sym = struct.unpack('>i', b[o + 18 + 90:o + 18 + 94])[0] * 2 + o
    p = sym
    if struct.unpack('>h', b[p:p + 2])[0] != -1: return None
    nlay = struct.unpack('>h', b[p + 8:p + 10])[0]; p += 10
    barbs, labs = [], []
    for _ in range(nlay):
        p += 2; ln = struct.unpack('>i', b[p:p + 4])[0]; p += 4; end = p + ln
        while p < end:
            code, plen = struct.unpack('>hh', b[p:p + 4]); body = b[p + 4:p + 4 + plen]
            if code == 4:
                for k in range(0, plen - 9, 10):
                    c, x, y, d, sp = struct.unpack('>hhhhh', body[k:k + 10]); barbs.append((x, y, d, sp))
            elif code == 8:
                c, x, y = struct.unpack('>hhh', body[:6]); t = body[6:].decode('ascii', 'replace').strip()
                if x < 60 and re.fullmatch(r'\d{1,2}', t): labs.append((y, int(t)))
            p += 4 + plen
    if not barbs or not labs: return None
    xm = max(q[0] for q in barbs)
    u = v = 0.0; n = 0
    for x, y, d, sp in barbs:
        if x != xm: continue
        kft = min(labs, key=lambda L: abs(L[0] - y))
        if abs(kft[0] - y) > 9 or not (1 <= kft[1] <= 5): continue
        to = math.radians((d + 180) % 360); u += sp * math.sin(to); v += sp * math.cos(to); n += 1
    if not n: return None
    return [int(round(math.degrees(math.atan2(u, v)) % 360)), int(round(math.hypot(u, v) / n)), n]


def nvw_keys(sid, t0, t1):
    out = []
    h = datetime.fromtimestamp(t0, timezone.utc).replace(minute=0, second=0)
    while h.timestamp() <= t1:
        pre = '%s_NVW_%s' % (sid[1:], h.strftime('%Y_%m_%d_%H'))
        try:
            x = get(L3 + '?list-type=2&prefix=' + pre, 30).decode()
            out += re.findall(r'<Key>([^<]+)</Key>', x)
        except Exception:
            pass
        h += timedelta(hours=1)
    return out


def vad_for(times):
    """{frame time: {sid: [toward, kt, n]}} for the given frame times."""
    t0, t1 = min(times) - 900, max(times) + 300
    def one(sid):
        res = {}
        keys = nvw_keys(sid, t0, t1)
        kt = []
        for k in keys:
            try: kt.append((datetime.strptime(k[-19:], '%Y_%m_%d_%H_%M_%S').replace(tzinfo=timezone.utc).timestamp(), k))
            except ValueError: pass
        cache = {}
        for t in times:
            c = [q for q in kt if t - 720 <= q[0] <= t + 120]
            if not c: continue
            k = max(c)[1]
            if k not in cache:
                try: cache[k] = nvw_parse(get(L3 + k, 30))
                except Exception: cache[k] = None
            if cache[k]: res[t] = cache[k]
        return sid, res
    out = {t: {} for t in times}
    for sid, res in POOL.map(one, list(RADARS)):
        for t, v in res.items(): out[t][sid] = v
    return out


def capture_vad(work):
    have = set(store_ls('mig/frames/')); hv = set(store_ls('mig/vad/'))
    need = []
    for nm in have:
        if nm.endswith('.png') and nm[:13] + '.json' not in hv:
            try: need.append(datetime.strptime(nm[:13], '%Y%m%dT%H%M').replace(tzinfo=timezone.utc).timestamp())
            except ValueError: pass
    need = sorted(need)[-48:]                                      # a run catches up at most 8 hours
    if not need:
        print('vad: nothing new'); return
    V = vad_for(need)
    for t in need:
        nm = datetime.fromtimestamp(t, timezone.utc).strftime('%Y%m%dT%H%M') + '.json'
        p = os.path.join(work, 'vad_' + nm); json.dump(V[t], open(p, 'w'), separators=(',', ':'))
        store_put(p, 'mig/vad/' + nm, 'application/json', 'public, max-age=31536000, immutable')
    print('vad: %d frames, %s radars in the newest' % (len(need), len(V[need[-1]])))


# ---- the night on show
def nights(now):
    """[start, end) of the newest finished night and of the night in progress, as UTC seconds."""
    d = datetime.fromtimestamp(now, timezone.utc)
    end = d.replace(hour=14, minute=0, second=0, microsecond=0)
    if end.timestamp() > now: end -= timedelta(days=1)
    fin = (end - timedelta(hours=16)).timestamp(), end.timestamp()
    return fin, (fin[0] + 86400, fin[1] + 86400)


def deflicker(work, fr):
    """ONE-FRAME ECHOES OUT (2026-10-23, user: "is this playing properly?"). Birds build and fade over hours; an echo that is
    in one frame with nothing near it in the frame before or after is a radar glitch -- 10-22's 04:50 UTC frame carried a
    bright wedge of one sweep over the sea south of Nova Scotia, outside the MRMS rain mask, that flashed once a loop.
    Each blob of a frame is weighed against its neighbours no more than 20 minutes away: the echo they hold around it (each
    pixel the strongest neighbour echo within 8 px) must come to a quarter of the blob's own, or the blob goes. A plain
    touch test was not enough -- the 04:40 frame had 34 faint speckles where the wedge would be. A frame with no such
    neighbour (both sides of a capture hole) is left alone. Only the local copies are cleaned: the frames on R2 stay raw,
    so the rule can change and the night be re-baked."""
    from scipy.ndimage import label, maximum_filter, sum as nsum
    al = [np.asarray(frame_img(os.path.join(work, 'src_' + nm)))[:, :, 3].astype(np.float32) for _, nm in fr]
    grown = [None] * len(fr)
    def grow(j):
        if grown[j] is None: grown[j] = maximum_filter(al[j], size=17)
        return grown[j]
    for i, (t, nm) in enumerate(fr):
        nb = [j for j in (i - 1, i + 1) if 0 <= j < len(fr) and abs(fr[j][0] - t) <= 2 * STEP]
        on = al[i] > 0
        if not nb or not on.any(): continue
        near = np.max([grow(j) for j in nb], axis=0)
        lab, n = label(maximum_filter(on.astype(np.uint8), size=5) > 0)
        if not n: continue
        lab = np.where(on, lab, 0); idx = np.arange(1, n + 1)
        mass = np.asarray(nsum(al[i], lab, idx)); sup = np.asarray(nsum(np.minimum(near, al[i]), lab, idx))
        bad = np.zeros(n + 1, bool); bad[1:] = (mass > 20000) & (sup < 0.25 * mass)
        drop = bad[lab]
        k = int(drop.sum())
        if not k: continue
        path = os.path.join(work, 'src_' + nm); a = np.asarray(frame_img(path)).copy(); a[drop] = 0
        Image.fromarray(a).save(path)
        print('deflicker: %s dropped %d px of one-frame echo' % (nm[:13], k))


def sun_alt(t, lat, lon):
    """the sun's altitude in degrees at UTC unix time t over arrays of lat/lon (NOAA's low-precision formulas, ~0.5 deg)"""
    d = t / 86400.0 + 2440587.5 - 2451545.0
    g = math.radians((357.529 + 0.98560028 * d) % 360); q = (280.459 + 0.98564736 * d) % 360
    lam = math.radians(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)); eps = math.radians(23.439 - 0.00000036 * d)
    dec = math.asin(math.sin(eps) * math.sin(lam))
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    gmst = (280.46061837 + 360.98564736629 * d) % 360
    ha = np.radians(gmst + lon - ra); la = np.radians(lat)
    return np.degrees(np.arcsin(np.sin(la) * math.sin(dec) + np.cos(la) * math.cos(dec) * np.cos(ha)))


def daylight(work, fr):
    """NO ECHO IN DAYLIGHT (2026-10-25, user: "yes fix both"). Birds migrate between dusk and dawn, so an echo with the sun up is
    not them: (1) any echo where the sun is above the horizon at that pixel in that frame goes -- the cores that lingered an
    hour past dawn round the Plains radars; (2) ground clutter -- Missoula's mountain echo sat in all 96 frames of 10-24's night, before sunset
    too -- goes from every frame, grown 2 px: a pixel with echo in at least half of its EVENING daylight frames (2 or more,
    before sunset, when no bird is up) and, if it has morning daylight frames, in half of those too. Morning frames alone
    cannot tell: birds landing after dawn left whole rings in them, and a morning-only test erased the East's rings all night. Like deflicker, only the local copies are cleaned; the frames on R2 stay raw."""
    from scipy.ndimage import maximum_filter
    al0 = np.asarray(frame_img(os.path.join(work, 'src_' + fr[0][1])))
    H, W = al0.shape[:2]
    xs = X0 + (np.arange(W) + .5) / W * (X1 - X0); ys = Y1 - (np.arange(H) + .5) / H * (Y1 - Y0)
    lon = np.degrees(xs / R)[None, :].repeat(H, 0); lat = np.degrees(2 * np.arctan(np.exp(ys / R)) - math.pi / 2)[:, None].repeat(W, 1)
    day = []; mid = (fr[0][0] + fr[-1][0]) / 2
    dn = {0: np.zeros((H, W), np.int16), 1: np.zeros((H, W), np.int16)}; hit = {0: np.zeros((H, W), np.int16), 1: np.zeros((H, W), np.int16)}
    for t, nm in fr:
        up = sun_alt(t, lat, lon) > 0; day.append(up); k = 0 if t < mid else 1      # 0 evening, 1 morning
        on = np.asarray(frame_img(os.path.join(work, 'src_' + nm)))[:, :, 3] > 0
        dn[k] += up; hit[k] += up & on
    ev = (dn[0] >= 2) & (hit[0] * 2 >= dn[0]); mo = (dn[1] == 0) | (hit[1] * 2 >= dn[1])
    clutter = maximum_filter((ev & mo).astype(np.uint8), size=5) > 0
    print('daylight: %d px of standing clutter' % int(clutter.sum()))
    for (t, nm), up in zip(fr, day):
        path = os.path.join(work, 'src_' + nm); a = np.asarray(frame_img(path)).copy()
        drop = (up | clutter) & (a[:, :, 3] > 0); k = int(drop.sum())
        if not k: continue
        a[drop] = 0; Image.fromarray(a).save(path)
        print('daylight: %s dropped %d px' % (nm[:13], k))


def bake(work, force=False):
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
    if not force and old and old.get('filt') == FILT and old.get('start') == start and old.get('n') == len(fr) and old.get('flow') and any(old['flow'][-3:]):
        print('bake: %s already baked with %d frames' % (start, len(fr))); return
    fd = os.path.join(work, 'f'); os.makedirs(fd, exist_ok=True)
    for t, nm in fr:
        src = os.path.join(work, 'src_' + nm)
        if not os.path.exists(src): store_get('mig/frames/' + nm, src)
    deflicker(work, fr)
    daylight(work, fr)
    for i, (t, nm) in enumerate(fr):
        src = os.path.join(work, 'src_' + nm)
        im = frame_img(src); bg = Image.new('RGBA', im.size, (0, 0, 0, 255)); bg.alpha_composite(im)
        bg.convert('RGB').save(os.path.join(fd, '%04d.png' % i))
    man = {'start': start, 'night': [iso(night[0]), iso(night[1])], 'n': len(fr), 'fps': FPS, 'step': STEP,
           'times': [iso(t) for t, _ in fr], 'bbox': [W_LON, S_LAT, E_LON, N_LAT], 'at': int(time.time()),
           'finished': night == fin, 'filt': FILT}
    # THE FLOW: each frame's radar vectors, by index into man['radars']
    hv = set(store_ls('mig/vad/'))
    sids = sorted(RADARS); man['radars'] = [[s, RADARS[s][0], RADARS[s][1]] for s in sids]
    flow = []
    for t, nm in fr:
        k = nm[:13] + '.json'; row = []
        if k in hv:
            p = os.path.join(work, 'v_' + k)
            try:
                store_get('mig/vad/' + k, p); V = json.load(open(p))
                row = [[sids.index(s), v[0], v[1]] for s, v in V.items() if s in RADARS]
            except Exception:
                row = []
        flow.append(row)
    man['flow'] = flow
    # THE WHOLE NIGHT (user: "show their overall path"): every frame's birds summed into one soft map, and each radar's
    # average track weighted by how many birds were over it frame by frame
    acc = None; tw = None
    tA, tB = fr[0][0], fr[-1][0]
    for t, nm in fr:
        a = np.asarray(frame_img(os.path.join(work, 'src_' + nm)))[:, :, 3].astype(np.float32) / 255
        f = (t - tA) / max(1, tB - tA)
        acc = a if acc is None else acc + a
        tw = a * f if tw is None else tw + a * f
    from scipy.ndimage import gaussian_filter
    # WHEN THE BIRDS PASSED (2026-10-23, user: "this still looks cheap" of the painted flow): per cell, the bird-weighted mean
    # moment of the night (0 = the first frame, 1 = the last) in red, how many birds in alpha -- data for the page's stipple,
    # not a picture
    accb = gaussian_filter(acc, 2.5); twb = gaussian_filter(tw, 2.5)
    when = np.where(accb > 1e-4, twb / np.maximum(accb, 1e-4), 0)
    qq = np.percentile(accb[accb > 0.002], 99) if (accb > 0.002).any() else 1
    wimg = np.zeros(acc.shape + (4,), np.uint8)
    wimg[..., 0] = (np.clip(when, 0, 1) * 255).astype(np.uint8)
    wimg[..., 3] = (np.clip(accb / max(qq, 1e-6), 0, 1) ** 0.7 * 255).astype(np.uint8)
    wp = os.path.join(work, '%s_%d_%d_when.png' % (start, len(fr), man['at'])); Image.fromarray(wimg).save(wp, 'PNG', optimize=True)
    wk = 'mig/video/' + os.path.basename(wp); store_put(wp, wk, 'image/png', 'public, max-age=31536000, immutable'); man['when'] = wk
    acc = gaussian_filter(acc / max(1, len(fr)), 3)
    q = np.percentile(acc[acc > 0.002], 99) if (acc > 0.002).any() else 1
    lvl = np.clip(acc / max(q, 1e-6), 0, 1) ** 0.7
    tot = np.zeros(acc.shape + (4,), np.uint8)
    tot[..., 0] = 255; tot[..., 1] = (200 - 90 * lvl).astype(np.uint8); tot[..., 2] = (110 - 90 * lvl).clip(0).astype(np.uint8)
    tot[..., 3] = (lvl * 235).astype(np.uint8)
    tp = os.path.join(work, '%s_%d_%d_total.png' % (start, len(fr), man['at'])); Image.fromarray(tot).save(tp, 'PNG', optimize=True)
    tk = 'mig/video/' + os.path.basename(tp); store_put(tp, tk, 'image/png', 'public, max-age=31536000, immutable'); man['total'] = tk
    mean = []
    H_, W_ = acc.shape
    for i, s in enumerate(sids):
        lo, la = RADARS[s]; x, y = merc(lo, la)
        px = int((x - X0) / (X1 - X0) * W_); py = int((Y1 - y) / (Y1 - Y0) * H_)
        if not (0 <= px < W_ and 0 <= py < H_): continue
        u = v = wsum = 0.0
        for j, (t, nm) in enumerate(fr):
            vec = next((r for r in flow[j] if r[0] == i), None)
            if not vec: continue
            a = np.asarray(frame_img(os.path.join(work, 'src_' + nm)))[max(0, py - 20):py + 21, max(0, px - 20):px + 21, 3]
            w = float(a.mean()) / 255
            if w < 0.02: continue
            u += w * vec[2] * math.sin(math.radians(vec[1])); v += w * vec[2] * math.cos(math.radians(vec[1])); wsum += w
        if wsum > 0.05: mean.append([i, int(round(math.degrees(math.atan2(u, v)) % 360)), int(round(math.hypot(u, v) / wsum)), round(wsum, 2)])
    man['mean'] = mean
    for kind, w, crf in (('d', WD, 21), ('m', WD // 2, 23)):
        out = os.path.join(work, '%s_%d_%d_%s.mp4' % (start, len(fr), man['at'], kind))   # a new name every bake: these are cached a year
        subprocess.run([ffmpeg_bin(), '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', os.path.join(fd, '%04d.png'),
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
        keep = {man['d'], man['m'], man.get('total'), man.get('when'), old.get('d'), old.get('m'), old.get('total'), old.get('when')}
        for nm in store_ls('mig/video/'):
            if 'mig/video/' + nm not in keep: store_rm('mig/video/' + nm)


def tidy():
    cut = (datetime.now(timezone.utc) - timedelta(days=3)).strftime('%Y%m%dT%H%M')
    for nm in store_ls('mig/frames/'):
        if nm[:13] < cut: store_rm('mig/frames/' + nm)
    for nm in store_ls('mig/vad/'):
        if nm[:13] < cut: store_rm('mig/vad/' + nm)


if __name__ == '__main__':
    work = tempfile.mkdtemp(prefix='migvid')
    try:
        changed = capture(work)
        capture_vad(work)
        bake(work, force=bool(changed))
        tidy()
    finally:
        shutil.rmtree(work, ignore_errors=True)
