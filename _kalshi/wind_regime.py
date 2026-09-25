#!/usr/bin/env python3
"""THE MORNING WIND REGIME (2026-09-25). Nightly; writes _kalshi/wind_regime.json for the bake.

User, after New York went 0 for 4 in the week before a nor'easter, every miss cold: "does the kalshi widget
take intelligence ... is it aware of this happening?" It was not wrong about the storm -- all six models ran
below the truth in east-northeasterly flow and the bake followed them. The question that stood was whether
the models are SYSTEMATICALLY off by wind direction. nyc_regimes.py (09-13) had rejected a wind-sector bias,
but its only split was onshore 120-220 (the summer sea breeze) against everything else, which lumped NE with NW.

Measured here on 919 New York days (2024-03 .. 2026-09), the bake's own recipe (each model's peak less its
EWMA hl-7 bias, equal weights), split by LaGuardia's 8-11 AM vector-mean wind (known before the noon lock;
Central Park's own anemometer sits in the trees):

    sector   n    signed error      sector   n    signed error
    N        62   +0.21             S        79   -0.04
    NE      220   -0.32 (se .08)    SW      100   +0.06
    E        19   -0.45             W        81   +0.65
    SE       25   -0.24             NW      202   +0.39      calm (<4 kt) 111  -0.19

NE-E (30-110 deg) came out -0.38 / -0.30 / -0.30 in 2024 / 2025 / 2026 -- not one season's accident.
A walk-forward correction (each day: the shrunk mean error of PRIOR days in the same sector) took the 2026
holdout from MAE 1.078 to 1.025 and within-1 from 55.6% to 58.6%; with the wind labels shuffled among the
days 200 times the best gain was +0.015 against the real +0.054.

WHAT THIS WRITES, per market:
  by_day  {date: {sec, c}}  the correction each past day WOULD have had, from earlier days only -- so the
          bake's backfill, its residual spread and the tuner's replays see no future information
  table   {sec: c}          today's corrections, from every scored day
The bake applies it only where the market's `wind_regime` setting is on, and that setting is a tuner knob:
it goes live only if it clears the guardrails on the real settled ladders.

    python3 _kalshi/wind_regime.py
"""
import csv, datetime, json, math, os, statistics as st, sys, time, urllib.parse, urllib.request, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'wind_regime.json')
CACHE = os.path.join(HERE, '_study'); os.makedirs(CACHE, exist_ok=True)

MARKETS = {   # key -> the station the market settles on, the airport whose wind classifies the day
    'ny_high': {'lat': 40.7789, 'lon': -73.9692, 'tz': 'America/New_York', 'truth': ('NY_ASOS', 'NYC'), 'wind': 'LGA'},
}
MODELS = ['ncep_hrrr_conus', 'ncep_nbm_conus', 'ecmwf_ifs025', 'gfs_seamless', 'icon_seamless', 'gem_seamless']
START = '2024-03-01'
HL, SPAN = 7, 90          # the bake's EWMA bias (bias_hl 7, BIAS_SPAN 90)
SHRINK, WIN, MIN_N = 20, 120, 10   # shrunk toward 0 by n/(n+20); the last 120 same-sector days; 10 before any
CALM_KT = 4
SECTORS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']


def sector(deg, kt):
    if deg is None or kt is None:
        return None
    if kt < CALM_KT:
        return 'calm'
    return SECTORS[int(((deg + 22.5) % 360) // 45)]


def vmean(pairs):
    """vector mean of (direction the wind comes FROM, speed) -> (deg, speed)"""
    u = sum(-s * math.sin(math.radians(a)) for a, s in pairs)
    v = sum(-s * math.cos(math.radians(a)) for a, s in pairs)
    n = len(pairs)
    return (math.degrees(math.atan2(-u, -v)) + 360) % 360, math.hypot(u, v) / n


def fetch(name, url, max_age=6 * 3600):
    p = os.path.join(CACHE, name)
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > max_age:
        for i in range(3):
            try:
                urllib.request.urlretrieve(url, p)
                break
            except Exception as e:
                print('  %s retry %d (%s)' % (name, i + 1, e), flush=True)
                time.sleep(5 * (i + 1))
        else:
            raise RuntimeError('could not fetch ' + name)
    return p


def build(key, m):
    end = datetime.date.today() - datetime.timedelta(days=1)
    y, mo, d = end.isoformat().split('-')
    tz = urllib.parse.quote(m['tz'])
    arch = json.load(open(fetch('wr_%s_arch.json' % key,
        'https://historical-forecast-api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&start_date=%s&end_date=%s'
        '&hourly=temperature_2m&temperature_unit=fahrenheit&timezone=%s&models=%s'
        % (m['lat'], m['lon'], START, end.isoformat(), tz, ','.join(MODELS)))))['hourly']
    net, stn = m['truth']
    truth = {}
    for r in csv.DictReader(open(fetch('wr_%s_daily.csv' % key,
            'https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?network=%s&stations=%s&year1=%s&month1=%s&day1=%s'
            '&year2=%s&month2=%s&day2=%s&format=comma' % (net, stn, START[:4], int(START[5:7]), int(START[8:]), y, mo, d)))):
        v = r.get('max_temp_f')
        if v not in (None, '', 'M', 'None'):
            truth[r['day']] = float(v)
    ob = collections.defaultdict(list)
    for r in csv.DictReader(open(fetch('wr_%s_wind.csv' % key,
            'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=%s&data=drct&data=sknt&year1=%s&month1=%s&day1=%s'
            '&year2=%s&month2=%s&day2=%s&tz=%s&format=onlycomma&latlon=no&elev=no&missing=M&trace=T&direct=no&report_type=3'
            % (m['wind'], START[:4], int(START[5:7]), int(START[8:]), y, mo, d, tz)))):
        h = int(r['valid'][11:13])
        if 8 <= h <= 11 and r['drct'] not in ('M', '') and r['sknt'] not in ('M', ''):
            ob[r['valid'][:10]].append((float(r['drct']), float(r['sknt'])))
    pk = collections.defaultdict(dict)
    T = arch['time']
    for mm in MODELS:
        col = arch.get('temperature_2m_' + mm) or []
        for t, v in zip(T, col):
            if v is not None and v > pk[t[:10]].get(mm, -999):
                pk[t[:10]][mm] = v
    days = sorted(dd for dd in pk if dd in truth and len(pk[dd]) >= 4)
    err = {dd: {mm: pk[dd][mm] - truth[dd] for mm in pk[dd]} for dd in days}
    lam = 0.5 ** (1.0 / HL)
    E = {}
    for i, dd in enumerate(days):
        if i < 20:
            continue
        xs = []
        for mm in pk[dd]:
            num = den = 0.0
            for j in range(max(0, i - SPAN), i):
                e = err[days[j]].get(mm)
                if e is not None:
                    w = lam ** (i - j); num += w * e; den += w
            if den > 1e-9:
                xs.append(pk[dd][mm] - num / den)
        if len(xs) >= 3:
            E[dd] = st.mean(xs) - truth[dd]
    sec = {dd: sector(*vmean(ob[dd])) for dd in E if len(ob[dd]) >= 3}
    hist = collections.defaultdict(list)
    by_day = {}
    def corr(h):
        h = h[-WIN:]
        return st.mean(h) * len(h) / (len(h) + SHRINK) if len(h) >= MIN_N else 0.0
    for dd in sorted(E):
        s = sec.get(dd)
        if s is None:
            continue
        by_day[dd] = {'sec': s, 'c': round(corr(hist[s]), 3)}      # from EARLIER days only
        hist[s].append(E[dd])
    table = {s: round(corr(hist[s]), 3) for s in SECTORS + ['calm']}
    n_s = {s: len(hist[s]) for s in SECTORS + ['calm']}
    # the gain the correction bought, walk-forward, this year and all told (the nightly log keeps it honest)
    def gain(d0):
        r = [(E[dd], E[dd] - by_day[dd]['c']) for dd in by_day if dd >= d0]
        return {'n': len(r), 'mae_before': round(st.mean(abs(a) for a, _ in r), 3),
                'mae_after': round(st.mean(abs(b) for _, b in r), 3)} if r else None
    return {'wind_station': m['wind'], 'window': '08-11 local, vector mean, calm under %d kt' % CALM_KT,
            'table': table, 'n': n_s, 'by_day': by_day,
            'check': {'since_2024_09': gain('2024-09-01'), 'this_year': gain(end.isoformat()[:4] + '-01-01')},
            'span': [min(E), max(E)]}


def main():
    out = {'built_utc': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'method': 'walk-forward shrunk mean error of the bake-like forecast by morning wind sector (see wind_regime.py)'}
    for key, m in MARKETS.items():
        r = build(key, m)
        out[key] = r
        print('%s: %d days scored, table %s, check %s' % (key, len(r['by_day']), r['table'], r['check']), flush=True)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, os.path.getsize(OUT) // 1024, 'KB')


if __name__ == '__main__':

    main()
