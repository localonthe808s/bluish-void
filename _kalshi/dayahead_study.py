#!/usr/bin/env python3
"""THE DAY-AHEAD COURT (2026-09-13). Per city: how each model's run from the day
before missed the official high, over the trailing window, and the residuals
of their bias-corrected mean. Writes _kalshi/dayahead.json, read by the bake's
TOMORROW block.

Why it exists. TOMORROW_SD in kalshi_daily.py is 2.19, measured on 601 New
York days, and it priced every city's overnight ladder. Measured here on the
same ~105 days per city, walk-forward (Open-Meteo previous-runs archive, the
run from the day before, against the settlement station's IEM daily max):

    city   corrected-mean SD   MAE   P(|err| <= 1)
    NY          2.11          1.68      0.34
    LAS         1.73          1.10      0.66
    AUS         1.62          1.28      0.48

Las Vegas days land within a degree of the call twice as often as New York's,
and a normal at New York's width put a 35% on a Vegas bracket that lands two
days in three -- which is exactly the bracket the panel then told the user to
bet AGAINST at 36c. The residual list, not a normal, prices tomorrow.

Also found here and used: the live forecast's ncep_hrrr_conus column for
tomorrow is the GFS (identical on 74/74 days, as it is in the archive), so the
six-model mean was five with GFS twice; the court carries five models and the
bake takes only those.

Method, walk-forward. For each day d in the window, each model's bias is the
mean of (actual - the previous day's run's peak) over the up-to-45 days
before d (at least 14); the residual is actual_d minus the mean of the five
corrected peaks. The bias published for tomorrow is the trailing 45 days
through the newest scored day.

Spread bins (2026-09-13, idea 2). The five runs' disagreement is the one bust
flag that survived: day-ahead miss 1.3 degF when the peaks sit within 5 degF,
1.9 when they are 5 or more apart (n 106). Each residual is stored with its
day's spread; the study scores, walk-forward, pricing from the same-bin
residuals against the pooled list (mean log score of the settled integer
through the bake's kernel) and rules `spread_use` only when the bin pricing
wins AND both bins hold SPREAD_MIN days. The bake then takes the bin's
residuals for tomorrow's ladder. Until the ruling flips, the log just grows.

Offline: python3 _kalshi/dayahead_study.py [--days 120]
"""
import csv, io, json, math, os, sys, time, datetime, statistics, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K                                   # noqa: E402
OUT = os.path.join(HERE, 'dayahead.json')
CACHE = os.path.join(HERE, '_study')
MODELS = ['ncep_nbm_conus', 'ecmwf_ifs025', 'gfs_seamless', 'icon_seamless', 'gem_seamless']
WINDOW = 45          # days of bias memory
MIN_BIAS_N = 14      # fewer scored days than this and a day is not graded
DAYS = 120           # how far back the archive is asked for
SPREAD_SPLIT = 5.0   # degF between the warmest and coldest corrected peak
SPREAD_MIN = 40      # days in EACH bin before the bin pricing can rule
KERNEL = 0.5         # the bake's DAYAHEAD_KERNEL


def _download(url, ua, timeout):
    """IEM SAYS NO SOMETIMES (2026-10-02): the nightly refit runs eight studies back to back against the Iowa
    Environmental Mesonet, which answers 429 'too many requests' or 503 'server over capacity'. Las Vegas's daily
    file hit that two nights running and the city silently dropped out of kernel.json and dayahead.json. Wait and
    retry the busy answers; anything else raises at once."""
    import re, urllib.error
    # ONE YEAR AT A TIME: a multi-year daily.py request is the one IEM refuses with 503 'server over capacity'
    # (a single year answers in 0.4 s), so split it by year, pause between the pieces, and join them.
    m = re.search(r'year1=(\d{4})&month1=(\d+)&day1=(\d+)&year2=(\d{4})&month2=(\d+)&day2=(\d+)', url)
    if 'daily.py' in url and m and m.group(1) != m.group(4):
        y1, y2, parts = int(m.group(1)), int(m.group(4)), []
        for y in range(y1, y2 + 1):
            a = (m.group(2), m.group(3)) if y == y1 else ('1', '1')
            b = (m.group(5), m.group(6)) if y == y2 else ('12', '31')
            u = url.replace(m.group(0), 'year1=%d&month1=%s&day1=%s&year2=%d&month2=%s&day2=%s' % (y, a[0], a[1], y, b[0], b[1]))
            txt = _download(u, ua, timeout).decode('utf-8', 'replace').splitlines(True)
            parts.extend(txt if not parts else txt[1:])
            time.sleep(3)
        return ''.join(parts).encode('utf-8')
    for i, wait in enumerate((0, 20, 60, 120)):
        if wait: time.sleep(wait)
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': ua}), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == 3: raise
            print('  %s busy (%d), retrying in %ds' % (url.split('/')[2], e.code, (20, 60, 120)[i]), flush=True)


def fetch(name, url, max_age_h=20):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > max_age_h * 3600:
        try:
            data = _download(url, 'bluishvoid.com day-ahead court', 240)
        except Exception as e:
            if not os.path.exists(p):
                raise
            print('  %s: download failed (%s), using the cached copy' % (name, e), flush=True)   # a day-old copy beats dropping the city
            return io.open(p, encoding='utf-8', errors='replace').read()
        with open(p, 'wb') as fh:
            fh.write(data)
    return io.open(p, encoding='utf-8', errors='replace').read()


def truth_of(cfg, since):
    y, m, d = time.strftime('%Y-%m-%d').split('-')
    st, net = cfg['station'], cfg['network']
    txt = fetch('%s_daily.csv' % st,
                'https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?network=%s&stations=%s'
                '&year1=2025&month1=1&day1=1&year2=%s&month2=%s&day2=%s&format=comma' % (net, st, y, m, d))
    today = time.strftime('%Y-%m-%d')
    truth = {}
    for r in csv.DictReader(io.StringIO(txt)):
        v = r.get('max_temp_f')
        # IEM's daily row for today is the running max, not the day: skip it
        if v not in (None, '', 'M', 'None') and since <= r['day'] < today:
            truth[r['day']] = float(v)
    return K.overlay_cli(truth, cfg, CACHE)       # the climate report, not the hourly maximum (2026-11-01; see K.cli_highs)


def peaks_of(cfg, since, until):
    """{date: {model: the previous day's run's peak for that date}}, local days."""
    url = ('https://previous-runs-api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f'
           '&hourly=temperature_2m_previous_day1&models=%s&temperature_unit=fahrenheit'
           '&timezone=%s&start_date=%s&end_date=%s'
           % (cfg['lat'], cfg['lon'], ','.join(MODELS), urllib.parse.quote(cfg['tz']), since, until))
    h = json.loads(fetch('%s_prev1_%s.json' % (cfg['station'], until), url, max_age_h=6)).get('hourly') or {}
    T = h.get('time') or []
    days = {}
    for i, t in enumerate(T):
        r = days.setdefault(t[:10], {m: [] for m in MODELS})
        for m in MODELS:
            v = (h.get('temperature_2m_previous_day1_' + m) or [None] * len(T))[i]
            if v is not None:
                r[m].append(v)
    return {d: {m: max(v) for m, v in r.items() if len(v) >= 12} for d, r in days.items()}


# ------------------------------------------------------------- THE LOWS ----
# THE DAY-AHEAD COURT FOR A LOW (2026-11-13, user: "yes wire them in"). A low is bet the evening before, on
# tomorrow's ladder, and the bake prices that view from its own same-day machinery with the floor off. This court
# asks whether the previous-day runs priced the way the highs' TOMORROW block is priced -- the bias-corrected mean of
# the five runs' TROUGHS over the climate day, plus the trailing residual list through the kernel -- would have scored
# better on the settled integer than the bake's own evening view did (history[].eve: pred and sd, a normal). Truth is
# the exchange's own expiration_value where the bake recorded it, IEM's min_temp_f otherwise (identical on 67/67 days
# when the lows were built). `eve_use` is ruled only on EVE_MIN common days, winning on both halves.
EVE_MIN = 40


def low_truth_of(cfg, since):
    y, m, d = time.strftime('%Y-%m-%d').split('-')
    txt = fetch('%s_daily.csv' % cfg['station'],
                'https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?network=%s&stations=%s'
                '&year1=2025&month1=1&day1=1&year2=%s&month2=%s&day2=%s&format=comma' % (cfg['network'], cfg['station'], y, m, d))
    today = time.strftime('%Y-%m-%d')
    truth = {}
    for r in csv.DictReader(io.StringIO(txt)):
        v = r.get('min_temp_f')
        if v not in (None, '', 'M', 'None') and since <= r['day'] < today:
            truth[r['day']] = float(v)
    try:
        for h in json.load(open(os.path.join(HERE, '..', 'kalshi_low_%s.json' % cfg['key'].split('_')[0]))).get('history', []):
            if h.get('actual') is not None and h.get('date', '') >= since:
                truth[h['date']] = float(h['actual'])
    except Exception:
        pass
    return truth


def troughs_of(cfg, since, until):
    """{date: {model: the previous day's run's minimum over that CLIMATE day}} -- under daylight time the climate day
    runs 1 AM to 1 AM local, and a low can sit in that last hour."""
    url = ('https://previous-runs-api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f'
           '&hourly=temperature_2m_previous_day1&models=%s&temperature_unit=fahrenheit'
           '&timezone=%s&start_date=%s&end_date=%s'
           % (cfg['lat'], cfg['lon'], ','.join(MODELS), urllib.parse.quote(cfg['tz']), since, until))
    h = json.loads(fetch('%s_prev1_%s.json' % (cfg['station'], until), url, max_age_h=6)).get('hourly') or {}
    T = h.get('time') or []
    days = {}
    for i, t in enumerate(T):
        d0 = datetime.date(*map(int, t[:10].split('-')))
        hr = int(t[11:13])
        if hr < K.climate_day_start(cfg, d0):
            d0 -= datetime.timedelta(days=1)             # the 00:xx hour belongs to yesterday's climate day
        r = days.setdefault(d0.isoformat(), {m: [] for m in MODELS})
        for m in MODELS:
            v = (h.get('temperature_2m_previous_day1_' + m) or [None] * len(T))[i]
            if v is not None:
                r[m].append(v)
    return {d: {m: min(v) for m, v in r.items() if len(v) >= 12} for d, r in days.items()}


def _phi_n(x, mu, sd):
    return 0.5 * (1.0 + math.erf((x - mu) / (sd * math.sqrt(2.0))))


def low_eve_court(cfg, c, truth, troughs):
    """The court's walk-forward log score on each graded day against the bake's evening view on the same days."""
    try:
        hist = {h['date']: h for h in json.load(open(os.path.join(HERE, '..', 'kalshi_low_%s.json' % cfg['key'].split('_')[0]))).get('history', [])}
    except Exception:
        hist = {}
    days = sorted(d for d in troughs if d in truth and len(troughs[d]) == len(MODELS))
    graded = []
    for i, d in enumerate(days):
        prior = days[max(0, i - WINDOW):i]
        if len(prior) < MIN_BIAS_N:
            continue
        bias = {m: statistics.mean(truth[p] - troughs[p][m] for p in prior) for m in MODELS}
        pred = statistics.mean(troughs[d][m] + bias[m] for m in MODELS)
        graded.append((d, truth[d] - pred))
    rows = []
    for i, (d, r) in enumerate(graded):
        pool = [x for _, x in graded[max(0, i - 90):i]]
        ours = _logscore(pool, r)
        e = (hist.get(d) or {}).get('eve') or {}
        if ours is None or e.get('pred') is None or not e.get('sd'):
            continue
        v = math.floor(truth[d] + 0.5)
        pb = _phi_n(v + 0.5, e['pred'], e['sd']) - _phi_n(v - 0.5, e['pred'], e['sd'])
        rows.append((d, ours, math.log(max(pb, 1e-6))))
    if not rows:
        return {'eve_use': False, 'eve_n': 0}
    half = len(rows) // 2
    def m(rs, j):
        return statistics.mean(x[j] for x in rs) if rs else None
    old, new = rows[:half], rows[half:]
    gain = m(rows, 1) - m(rows, 2)
    both = bool(old) and bool(new) and m(old, 1) > m(old, 2) and m(new, 1) > m(new, 2)
    return {'eve_use': bool(gain > 0 and both and len(rows) >= EVE_MIN), 'eve_n': len(rows),
            'eve_score': [round(m(rows, 2), 4), round(m(rows, 1), 4)], 'eve_gain': round(gain, 4),
            'eve_halves': [[round(m(old, 2), 4), round(m(old, 1), 4)], [round(m(new, 2), 4), round(m(new, 1), 4)]] if old and new else None}


def court(truth, peaks):
    days = sorted(d for d in peaks if d in truth and len(peaks[d]) == len(MODELS))
    resid, graded, spread = [], [], []
    for i, d in enumerate(days):
        prior = days[max(0, i - WINDOW):i]
        if len(prior) < MIN_BIAS_N:
            continue
        bias = {m: statistics.mean(truth[p] - peaks[p][m] for p in prior) for m in MODELS}
        corr = [peaks[d][m] + bias[m] for m in MODELS]
        pred = statistics.mean(corr)
        resid.append(round(truth[d] - pred, 2))
        spread.append(round(max(corr) - min(corr), 2))
        graded.append(d)
    tail = days[-WINDOW:]
    bias_now = {m: round(statistics.mean(truth[p] - peaks[p][m] for p in tail), 2) for m in MODELS} if tail else {}
    out = {'models': MODELS, 'window': WINDOW, 'bias': bias_now, 'bias_n': len(tail),
           'n': len(resid), 'from': graded[0] if graded else None, 'to': graded[-1] if graded else None,
           'resid': resid, 'spread': spread, 'spread_split': SPREAD_SPLIT, 'spread_min': SPREAD_MIN}
    out.update(spread_ruling(resid, spread))
    if resid:
        out.update({'sd': round(statistics.pstdev(resid), 3), 'mae': round(statistics.mean(abs(r) for r in resid), 3),
                    'bias_resid': round(statistics.mean(resid), 3),
                    'p_within1': round(sum(1 for r in resid if abs(r) <= 1.0) / len(resid), 3),
                    'sd_last30': round(statistics.pstdev(resid[-30:]), 3) if len(resid) >= 10 else None})
    return out


def _phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _logscore(pool, r):
    """log P(the settled integer) when residual r is priced from `pool` through the kernel."""
    if len(pool) < 10:
        return None
    p = statistics.mean(_phi((r + 0.5 - e) / KERNEL) - _phi((r - 0.5 - e) / KERNEL) for e in pool)
    return math.log(max(p, 1e-6))


def spread_ruling(resid, spread):
    """Walk-forward: for each graded day, price from the pooled prior residuals
    and from the prior residuals in the same spread bin; mean log score of each."""
    pooled, binned, n_lo, n_hi = [], [], 0, 0
    for i in range(len(resid)):
        prior = list(range(max(0, i - 90), i))
        hi = spread[i] >= SPREAD_SPLIT
        same = [resid[j] for j in prior if (spread[j] >= SPREAD_SPLIT) == hi]
        a = _logscore([resid[j] for j in prior], resid[i]); b = _logscore(same, resid[i])
        if a is None or b is None:
            continue
        pooled.append(a); binned.append(b)
        if hi: n_hi += 1
        else: n_lo += 1
    if not pooled:
        return {'spread_use': False, 'spread_n': [n_lo, n_hi]}
    gain = statistics.mean(binned) - statistics.mean(pooled)
    use = gain > 0 and n_lo >= SPREAD_MIN and n_hi >= SPREAD_MIN
    return {'spread_use': use, 'spread_gain': round(gain, 4), 'spread_n': [n_lo, n_hi],
            'spread_score': [round(statistics.mean(pooled), 4), round(statistics.mean(binned), 4)]}


def main():
    days = DAYS
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    today = datetime.date.today()
    since = (today - datetime.timedelta(days=days)).isoformat()
    doc = {'built': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime()), 'since': since, 'cities': {}}
    for cfg in K.MARKETS:
        try:
            truth = truth_of(cfg, since)
            peaks = peaks_of(cfg, since, today.isoformat())
            c = court(truth, peaks)
            doc['cities'][cfg['key']] = c
            print('%-9s n %3d (%s..%s)  SD %.2f  MAE %.2f  within 1: %.2f  bias now %s'
                  % (cfg['key'], c['n'], c['from'], c['to'], c.get('sd') or 0, c.get('mae') or 0,
                     c.get('p_within1') or 0, c['bias']))
            print('          spread bins <%g / >=%g: n %s  log score pooled/binned %s  gain %s  -> %s'
                  % (SPREAD_SPLIT, SPREAD_SPLIT, c.get('spread_n'), c.get('spread_score'), c.get('spread_gain'),
                     'BINNED' if c.get('spread_use') else 'pooled'))
        except Exception as e:
            print('%s: day-ahead court failed (%s)' % (cfg['key'], e))
    from active import ACTIVE
    for cfg in K.MARKETS:
        if cfg['key'] not in ACTIVE:
            continue
        lkey = cfg['key'].replace('_high', '_low')
        try:
            truth = low_truth_of(cfg, since)
            tr = troughs_of(cfg, since, today.isoformat())
            c = court(truth, tr)
            c.update(low_eve_court(cfg, c, truth, tr))
            c['kind'] = 'low'
            doc['cities'][lkey] = c
            print('%-9s n %3d (%s..%s)  SD %.2f  MAE %.2f  within 1: %.2f  bias now %s'
                  % (lkey, c['n'], c['from'], c['to'], c.get('sd') or 0, c.get('mae') or 0, c.get('p_within1') or 0, c['bias']))
            print('          against the bake\'s evening view on %s days: log score bake/court %s, gain %s, halves %s -> %s'
                  % (c.get('eve_n'), c.get('eve_score'), c.get('eve_gain'), c.get('eve_halves'), 'COURT' if c.get('eve_use') else 'the bake stands'))
        except Exception as e:
            print('%s: day-ahead court failed (%s)' % (lkey, e))
    # A CITY THAT FAILED KEEPS LAST NIGHT'S RULING (2026-10-02): dropping it left the bake with no ruling at all for
    # that city (Las Vegas, 10-01 and 10-02, an IEM 503). Marked 'carried' with the night it was really made.
    try:
        old = json.load(open(OUT))
        for k, v in (old.get('cities') or {}).items():
            if k not in doc['cities'] and isinstance(v, dict) and (k in {m['key'] for m in K.MARKETS} or k in {m['key'].replace('_high', '_low') for m in K.MARKETS}):  # cities dropped from active.py are not carried (2026-10-22)
                doc['cities'][k] = dict(v, carried=v.get('carried') or old.get('built'))
                print('%s: kept the ruling from %s' % (k, doc['cities'][k]['carried']))
    except Exception:
        pass
    if doc['cities']:
        with open(OUT, 'w') as fh:
            json.dump(doc, fh, indent=0, sort_keys=True)
        print('wrote', OUT)


if __name__ == '__main__':
    main()
