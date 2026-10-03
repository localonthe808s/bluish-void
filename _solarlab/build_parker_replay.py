#!/usr/bin/env python3
"""Parker Solar Probe encounter replay bake (one-time / rerunnable).

  python3 _solarlab/build_parker_replay.py [--encounter 27] [--days 5] [--no-movie] [--no-upload]

Writes _solarlab/parker/enc<N>.json:
  * perihelion time/distance/speed from JPL Horizons (COMMAND -96, CENTER 500@10, 10-min vectors)
  * SWEAP SPAN-i L3 moments (CDAWeb HAPI, PSP_SWP_SPI_SF00_L3_MOM): DENS, VEL_RTN_SUN -> V_R, |V|
  * FIELDS L2 1-min RTN mag (PSP_FLD_L2_MAG_RTN_1MIN) -> |B|
  all as 10-minute medians over perihelion +-days. Gaps stay null; nothing is filled.
  * WISPR L3 composite movie for the encounter (NRL), transcoded with ffmpeg and
    uploaded to R2 at solar/parker/wispr_enc<N>.mp4 (+ _poster.jpg).
"""
import urllib.parse, argparse, csv, datetime as dt, io, json, math, os, statistics, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'parker')
CACHE = '/tmp/parker_cache'
HAPI = 'https://cdaweb.gsfc.nasa.gov/hapi/data'
HZN = 'https://ssd.jpl.nasa.gov/api/horizons.api'
WISPR = 'https://wispr.nrl.navy.mil/sites/wispr.nrl.navy.mil/files/movies/wispr_l3_composite_enc{n}_hpc.mp4'
CDN = 'https://cdn.bluishvoid.com/'
R_SUN_KM = 695700.0
AU_KM = 149597870.7
BIN = 600  # seconds
# anchor: E22 perihelion 2024-12-24 ~11:53 UTC; mean period of the final orbit ~88.4 d
E22 = dt.datetime(2024, 12, 24, 12, tzinfo=dt.timezone.utc)
PERIOD_D = 88.4


def get(url, timeout=300):
    req = urllib.request.Request(url, headers={'User-Agent': 'bluish-void parker bake'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def iso(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_t(s):
    s = s.rstrip('Z')
    if '.' in s:
        s = s.split('.')[0]
    return dt.datetime.strptime(s, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=dt.timezone.utc)


def horizons_vectors(t0, t1, step='10m'):
    q = {
        'format': 'text', 'COMMAND': "'-96'", 'CENTER': "'500@10'", 'EPHEM_TYPE': 'VECTORS',
        'START_TIME': "'%s'" % t0.strftime('%Y-%m-%d %H:%M'), 'STOP_TIME': "'%s'" % t1.strftime('%Y-%m-%d %H:%M'),
        'STEP_SIZE': "'%s'" % step, 'VEC_TABLE': "'2'", 'CSV_FORMAT': 'YES', 'OUT_UNITS': "'KM-S'",
        'TIME_TYPE': 'UT',
    }
    url = HZN + '?' + urllib.parse.urlencode(q)
    txt = get(url).decode()
    if '$$SOE' not in txt:
        raise RuntimeError('Horizons: ' + txt[:400])
    rows = []
    for l in txt.split('$$SOE')[1].split('$$EOE')[0].strip().splitlines():
        f = [x.strip() for x in l.split(',')]
        t = dt.datetime.strptime(f[1].replace('A.D. ', ''), '%Y-%b-%d %H:%M:%S.%f').replace(tzinfo=dt.timezone.utc)
        x, y, z, vx, vy, vz = map(float, f[2:8])
        rows.append((t, math.sqrt(x * x + y * y + z * z), math.sqrt(vx * vx + vy * vy + vz * vz)))
    return rows, url.split('?')[0]


def find_perihelion(n):
    guess = E22 + dt.timedelta(days=(n - 22) * PERIOD_D)
    coarse, _ = horizons_vectors(guess - dt.timedelta(days=8), guess + dt.timedelta(days=8), '1h')
    tmin = min(coarse, key=lambda r: r[1])[0]
    fine, _ = horizons_vectors(tmin - dt.timedelta(hours=2), tmin + dt.timedelta(hours=2), '1m')
    return min(fine, key=lambda r: r[1])


def hapi_day_bins(ds, params, day, parse_row):
    """Fetch one UTC day from HAPI (cached) and return {bin_start_epoch: [values...]}."""
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, '%s_%s.csv' % (ds, day.strftime('%Y%m%d')))
    if not os.path.exists(fn):
        q = urllib.parse.urlencode({'id': ds, 'parameters': params, 'time.min': iso(day),
                                    'time.max': iso(day + dt.timedelta(days=1)), 'format': 'csv'})
        data = get(HAPI + '?' + q, timeout=600)
        with open(fn, 'wb') as f:
            f.write(data)
    bins = {}
    with open(fn, newline='') as f:
        for row in csv.reader(f):
            if not row or row[0].startswith('#'):
                continue
            try:
                t = parse_t(row[0])
                v = parse_row(row[1:])
            except (ValueError, IndexError):
                continue
            if v is None:
                continue
            k = int(t.timestamp()) // BIN * BIN
            bins.setdefault(k, []).append(v)
    return bins


def finite(x):
    return x is not None and not math.isnan(x) and not math.isinf(x)


def spi_row(r):
    d, vr, vt, vn = (float(x) for x in r[:4])
    out = [None, None, None]
    if finite(d) and d > 0:
        out[0] = d
    if all(finite(v) and abs(v) < 1e4 for v in (vr, vt, vn)):
        out[1] = vr
        out[2] = math.sqrt(vr * vr + vt * vt + vn * vn)
    return out if any(o is not None for o in out) else None


def mag_row(r):
    b = [float(x) for x in r[:3]]
    if not all(finite(v) and abs(v) < 1e7 for v in b):
        return None
    return math.sqrt(sum(v * v for v in b))


def med(vals, nd):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return round(statistics.median(vals), nd)


def sig(x, n=3):
    if x is None or x == 0:
        return x
    return round(x, max(0, n - 1 - int(math.floor(math.log10(abs(x))))))


def sh(cmd):
    print('  $', ' '.join(cmd))
    subprocess.run(cmd, check=True)


def do_movie(n, upload):
    import shutil
    if not shutil.which('ffmpeg'):
        print('ffmpeg not installed -> skipping movie')
        return None, 'ffmpeg not installed'
    os.makedirs(CACHE, exist_ok=True)
    src_url = WISPR.format(n=n)
    src = os.path.join(CACHE, 'wispr_enc%d_src.mp4' % n)
    if not os.path.exists(src):
        print('download', src_url)
        try:
            data = get(src_url, timeout=900)
        except Exception as e:
            return None, 'WISPR movie not available: %s' % e
        with open(src, 'wb') as f:
            f.write(data)
    dur = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                         '-of', 'csv=p=0', src]).decode().strip())
    target = 28.0
    speed = max(1.0, dur / target)
    os.makedirs(OUT, exist_ok=True)
    mp4 = os.path.join(OUT, 'wispr_enc%d.mp4' % n)
    jpg = os.path.join(OUT, 'wispr_enc%d_poster.jpg' % n)
    vf = 'setpts=PTS/%.4f,fps=24,scale=\'min(960,iw)\':-2:flags=lanczos,format=yuv420p' % speed
    for crf in (28, 30, 32, 34):
        sh(['ffmpeg', '-y', '-v', 'error', '-i', src, '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'slow',
            '-crf', str(crf), '-profile:v', 'high', '-movflags', '+faststart', mp4])
        if os.path.getsize(mp4) <= 6 * 1024 * 1024:
            break
    secs = round(float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                                '-of', 'csv=p=0', mp4]).decode().strip()), 1)
    # poster: frame near the middle of the pass (perihelion-ish)
    for q in (5, 8, 11, 14):
        sh(['ffmpeg', '-y', '-v', 'error', '-ss', '%.2f' % (secs * 0.5), '-i', mp4, '-frames:v', '1',
            '-q:v', str(q), jpg])
        if os.path.getsize(jpg) <= 90 * 1024:
            break
    print('movie %.2f MB, %.1f s; poster %d KB' % (os.path.getsize(mp4) / 1048576, secs, os.path.getsize(jpg) // 1024))
    keys = {'mp4': 'solar/parker/wispr_enc%d.mp4' % n, 'jpg': 'solar/parker/wispr_enc%d_poster.jpg' % n}
    if upload:
        for local, key, ctype in ((mp4, keys['mp4'], 'video/mp4'), (jpg, keys['jpg'], 'image/jpeg')):
            sh(['rclone', 'copyto', local, 'r2:bluishvoid-bg/' + key, '--s3-no-check-bucket',
                '--header-upload', 'Cache-Control: public, max-age=31536000, immutable',
                '--header-upload', 'Content-Type: ' + ctype])
    return {'url': CDN + keys['mp4'], 'poster': CDN + keys['jpg'], 'seconds': secs,
            'bytes': os.path.getsize(mp4), 'source': src_url,
            'credit': 'NASA/Naval Research Laboratory/Parker Solar Probe'}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--encounter', type=int, default=27)
    ap.add_argument('--days', type=float, default=5)
    ap.add_argument('--no-movie', action='store_true')
    ap.add_argument('--no-upload', action='store_true')
    a = ap.parse_args()
    n = a.encounter
    notes = []

    tp, rp, vp = find_perihelion(n)
    print('perihelion', iso(tp), '%.3f Rsun' % (rp / R_SUN_KM), '%.1f km/s' % vp)
    t0 = (tp - dt.timedelta(days=a.days)).replace(minute=0, second=0, microsecond=0)
    t1 = (tp + dt.timedelta(days=a.days)).replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    t0 = t0.replace(minute=t0.minute // 10 * 10)

    # distance at every 10-min bin centre
    hz, hzurl = horizons_vectors(t0 + dt.timedelta(seconds=BIN // 2), t1 - dt.timedelta(seconds=BIN // 2), '10m')
    rmap = {int(t.timestamp()) - BIN // 2: r for t, r, _ in hz}

    spi, mag = {}, {}
    day = t0.replace(hour=0, minute=0)
    while day < t1:
        print('HAPI day', day.date())
        for k, v in hapi_day_bins('PSP_SWP_SPI_SF00_L3_MOM', 'DENS,VEL_RTN_SUN', day, spi_row).items():
            spi.setdefault(k, []).extend(v)
        try:
            for k, v in hapi_day_bins('PSP_FLD_L2_MAG_RTN_1MIN', 'psp_fld_l2_mag_RTN_1min', day, mag_row).items():
                mag.setdefault(k, []).extend(v)
        except Exception as e:
            notes.append('MAG %s: %s' % (day.date(), e))
        day += dt.timedelta(days=1)

    S = {'t': [], 'dens': [], 'vr': [], 'vmag': [], 'b': [], 'r_sun': []}
    k = int(t0.timestamp())
    while k < int(t1.timestamp()):
        rows = spi.get(k, [])
        S['t'].append(iso(dt.datetime.fromtimestamp(k, dt.timezone.utc)))
        S['dens'].append(sig(med([r[0] for r in rows], 6), 3))
        S['vr'].append(med([r[1] for r in rows], 0))
        S['vmag'].append(med([r[2] for r in rows], 0))
        S['b'].append(med(mag.get(k, []), 0))
        r = rmap.get(k)
        S['r_sun'].append(round(r / R_SUN_KM, 2) if r else None)
        k += BIN
    for key in ('vr', 'vmag', 'b'):
        S[key] = [int(v) if v is not None else None for v in S[key]]
    if all(v is None for v in S['b']):
        S['b'] = None
        notes.append('no FIELDS |B| in window')

    def peak(key):
        arr = S[key]
        idx = [i for i, v in enumerate(arr or []) if v is not None]
        if not idx:
            return None
        i = max(idx, key=lambda j: arr[j])
        return {'value': arr[i], 'at': S['t'][i], 'r_sun': S['r_sun'][i]}

    n_bins = len(S['t'])
    cov = {key: round(sum(v is not None for v in S[key]) / n_bins, 3) for key in ('dens', 'vr', 'b') if S[key]}
    peaks = {'max_dens': peak('dens'), 'max_vr': peak('vr'), 'max_vmag': peak('vmag'),
             'max_b': peak('b') if S['b'] else None}

    movie, why = (None, 'skipped (--no-movie)') if a.no_movie else do_movie(n, not a.no_upload)
    if why:
        notes.append('movie: ' + why)

    out = {
        'built': iso(dt.datetime.now(dt.timezone.utc)),
        'encounter': n,
        'perihelion': {'time_utc': iso(tp), 'r_sun': round(rp / R_SUN_KM, 3), 'au': round(rp / AU_KM, 5),
                       'km': round(rp), 'speed_kms': round(vp, 1)},
        'window': [iso(t0), iso(t1)],
        'cadence_s': BIN,
        'units': {'dens': 'cm^-3', 'vr': 'km/s', 'vmag': 'km/s', 'b': 'nT', 'r_sun': 'R_sun'},
        'coverage': cov,
        'series': S,
        'peaks': peaks,
        'movie': movie,
        'notes': notes,
        'sources': [
            {'name': 'SWEAP SPAN-i L3 moments (PSP_SWP_SPI_SF00_L3_MOM) via CDAWeb HAPI', 'url': HAPI},
            {'name': 'FIELDS L2 1-min RTN magnetic field (PSP_FLD_L2_MAG_RTN_1MIN) via CDAWeb HAPI', 'url': HAPI},
            {'name': 'JPL Horizons, Parker Solar Probe (-96) heliocentric vectors', 'url': hzurl},
        ] + ([{'name': 'WISPR L3 composite movie, encounter %d (NRL)' % n, 'url': movie['source']}] if movie else []),
        'credit': 'NASA/Johns Hopkins APL/SWEAP (Smithsonian Astrophysical Observatory); FIELDS (UC Berkeley SSL); '
                  'ephemeris JPL Horizons' + ('; WISPR movie NASA/Naval Research Laboratory/Parker Solar Probe' if movie else ''),
    }
    os.makedirs(OUT, exist_ok=True)
    fn = os.path.join(OUT, 'enc%d.json' % n)
    with open(fn, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print('wrote', fn, '%d KB' % (os.path.getsize(fn) // 1024), 'bins', n_bins, 'coverage', cov)
    print('peaks', json.dumps(peaks))
    print('notes', notes)


if __name__ == '__main__':
    import urllib.parse
    main()
