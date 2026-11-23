"""EUROPE'S MIGRATION ON RADAR (2026-11-23; user: "add more birds and radar from tonight for europe").

Aloft (aloftdata.eu; CC0) publishes vertical profiles of birds from ~200 European weather radars (OPERA/BALTRAD, processed with
vol2bird). The daily CSVs land on a public S3 bucket about two days after the night, so "tonight" is not available anywhere openly:
this bake takes the LATEST COMPLETE NIGHT (civil dusk to civil dawn at each radar, from the sun) and writes, per radar:

  tr   birds that crossed each km of front over the night (sum of migration traffic rate x time)
  mtr  mean migration traffic rate over the night, birds per km per hour
  vid  peak vertically integrated density, birds per km^2 (the most birds aloft at once)
  hd   mean heading, degrees clockwise from north, the direction the birds flew TOWARD (density-weighted u, v)
  ff   mean ground speed, m/s
  h    density-weighted mean height above the radar, m
  hr   hourly vid through the night (for the card's curve)

Integrated from 200 m to 5,000 m (the lowest bin is ground clutter); rows flagged gap are skipped. These are model estimates from
radar reflectivity, not counts: the page draws them soft.

Run: python3 -I _birds/aloft_bake.py out [max_radars]   -> out/aloft/latest.json
"""
import concurrent.futures as cf, csv, datetime as dt, io, json, math, os, sys, urllib.request

S3 = 'https://aloftdata.s3-eu-west-1.amazonaws.com/'
RADARS_DB = 'https://raw.githubusercontent.com/aloftdata/aloftdata.eu/main/_data/OPERA_RADARS_DB.json'
UA = {'User-Agent': 'bluishvoid-bake/1.0 (birds)'}
H0, H1 = 200, 5000

def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()

def radars():
    xml = get(S3 + '?list-type=2&prefix=baltrad/daily/&delimiter=/&max-keys=1000').decode()
    return sorted(set(p.split('/')[2] for p in xml.split('<Prefix>')[1:] if p.count('/') >= 3 and p.split('/')[2]))

def newest_day(code):
    """the newest daily file for a radar (the bucket's lag varies by radar)"""
    y = dt.date.today().year
    for yy in (y, y - 1):
        xml = get(S3 + '?list-type=2&prefix=baltrad/daily/%s/%d/&max-keys=1000' % (code, yy)).decode()
        keys = [k.split('</Key>')[0] for k in xml.split('<Key>')[1:]]
        if keys:
            return dt.datetime.strptime(keys[-1].rsplit('_', 1)[1][:8], '%Y%m%d').date()
    return None

def sun_alt(t, lat, lon):
    """solar elevation in degrees (NOAA approximation; plenty for dusk/dawn)"""
    d = (t - dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)).total_seconds() / 86400.0
    g = math.radians((357.529 + 0.98560028 * d) % 360); q = (280.459 + 0.98564736 * d) % 360
    L = math.radians((q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360); e = math.radians(23.439 - 0.00000036 * d)
    ra = math.atan2(math.cos(e) * math.sin(L), math.cos(L)); dec = math.asin(math.sin(e) * math.sin(L))
    gmst = (18.697374558 + 24.06570982441908 * d) % 24; ha = math.radians((gmst * 15 + lon) % 360) - ra
    la = math.radians(lat)
    return math.degrees(math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha)))

def fnum(x):
    try:
        v = float(x); return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None

def night(code, day):
    """the night that starts on `day` evening and ends the next morning"""
    rows = []
    for d in (day, day + dt.timedelta(days=1)):
        url = S3 + 'baltrad/daily/%s/%d/%s_vpts_%s.csv' % (code, d.year, code, d.strftime('%Y%m%d'))
        try:
            rows += list(csv.DictReader(io.StringIO(get(url).decode('utf-8', 'replace'))))
        except Exception:
            return None
    if not rows: return None
    lat, lon = fnum(rows[0]['radar_latitude']), fnum(rows[0]['radar_longitude'])
    if lat is None or lon is None: return None
    prof = {}; seen = set()
    for r in rows:   # some radars list several rows per height per time (one per scan file): count each height once
        k = (r['datetime'], r['height'])
        if k in seen: continue
        seen.add(k); prof.setdefault(r['datetime'], []).append(r)
    times = sorted(prof)
    tr = 0.0; vids = []; su = sv = sw = sh = 0.0; n = 0; hr = {}; dark0 = None
    for i, ts in enumerate(times):
        t = dt.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
        if t.date() == day and t.hour < 10: continue            # the morning before this night
        if t.date() > day + dt.timedelta(days=1): continue
        if sun_alt(t, lat, lon) > -6: continue                 # civil dusk to civil dawn
        if dark0 is None: dark0 = t
        dtm = 5 / 60.0
        if i + 1 < len(times):
            t2 = dt.datetime.strptime(times[i + 1], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
            dtm = max(1, min(30, (t2 - t).total_seconds() / 60.0)) / 60.0
        vid = mtr = 0.0
        for r in prof[ts]:
            h = fnum(r['height'])
            if h is None or h < H0 or h >= H1 or r.get('gap', '').upper() == 'TRUE': continue
            de, ff, u, v = fnum(r['dens']), fnum(r['ff']), fnum(r['u']), fnum(r['v'])
            if not de or de <= 0: continue
            w = de * 0.2                                         # birds/km^2 in this 200 m bin
            vid += w
            if ff is not None: mtr += w * ff * 3.6               # birds per km of front per hour
            if u is not None and v is not None: su += w * u; sv += w * v
            sw += w; sh += w * (h + 100)
        vids.append(vid); tr += mtr * dtm; n += 1
        k = int((t - dark0).total_seconds() // 3600); hr.setdefault(k, []).append(vid)
    if n < 24: return None                                       # less than two hours of dark profiles
    hd = (math.degrees(math.atan2(su, sv)) + 360) % 360 if sw > 0 else None
    ff = math.hypot(su, sv) / sw if sw > 0 else None
    hours = [round(sum(hr[k]) / len(hr[k]), 1) for k in sorted(hr)]
    hrs = n * 5 / 60.0
    # q = 1 trusted; q = 0: the echoes drifted slower than birds fly (a night-mean ground speed under 5 m/s), more likely insects or clutter
    # q = 2: faster than birds travel over a whole night (mean over 20 m/s, ~70 km/h): more likely weather moving through
    q = 0 if (ff is not None and ff < 5 and tr > 500) else 2 if (ff is not None and ff > 20 and tr > 500) else 1
    return dict(c=code, lat=round(lat, 4), lon=round(lon, 4), tr=round(tr), mtr=round(tr / max(hrs, 0.1)), vid=round(max(vids), 1),
                hd=None if hd is None else round(hd), ff=None if ff is None else round(ff, 1), h=round(sh / sw) if sw > 0 else None, hr=hours, q=q)

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'out'; lim = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    meta = {}
    try:
        for r in json.loads(get(RADARS_DB)):
            if r.get('odimcode'): meta.setdefault(r['odimcode'], r)
    except Exception as e:
        print('radar names unavailable:', e)
    codes = radars()
    if lim: codes = codes[:lim]
    with cf.ThreadPoolExecutor(16) as ex:
        newest = dict(zip(codes, ex.map(lambda c: (lambda: newest_day(c))() if True else None, codes)))
    recent = [d for d in newest.values() if d and (dt.date.today() - d).days <= 10]
    if not recent: sys.exit('no recent Aloft files')
    from collections import Counter
    last = Counter(recent).most_common(1)[0][0]                 # the day most radars have reached
    day = last - dt.timedelta(days=1)                            # the night of day -> last
    todo = [c for c in codes if newest.get(c) and newest[c] >= last]
    with cf.ThreadPoolExecutor(16) as ex:
        res = list(ex.map(lambda c: night(c, day), todo))
    R = []
    for r in res:
        if not r: continue
        m = meta.get(r['c'])
        if not m:   # renamed codes (Spain's): the nearest listed radar within 15 km
            best = None
            for mm in meta.values():
                try: d = math.hypot((float(mm['latitude']) - r['lat']) * 111, (float(mm['longitude']) - r['lon']) * 111 * math.cos(math.radians(r['lat'])))
                except (TypeError, ValueError, KeyError): continue
                if d < 15 and (not best or d < best[0]): best = (d, mm)
            m = best[1] if best else {}
        r['n'] = m.get('location') or r['c'].upper(); r['cc'] = m.get('country') or ''
        R.append(r)
    R.sort(key=lambda r: -r['tr'])
    os.makedirs(os.path.join(out, 'aloft'), exist_ok=True)
    doc = dict(night=day.isoformat(), made=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), n=len(R),
               source='Aloft (aloftdata.eu), BALTRAD vertical profiles of birds, CC0', heights='%d-%d m' % (H0, H1), radars=R)
    json.dump(doc, open(os.path.join(out, 'aloft', 'latest.json'), 'w'), separators=(',', ':'))
    print('night of', day, '->', last, ':', len(R), 'radars of', len(todo), '; busiest', [(r['n'], r['tr']) for r in R[:5]])

if __name__ == '__main__':
    main()
