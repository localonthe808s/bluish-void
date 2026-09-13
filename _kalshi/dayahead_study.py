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


def fetch(name, url, max_age_h=20):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > max_age_h * 3600:
        req = urllib.request.Request(url, headers={'User-Agent': 'bluishvoid.com day-ahead court'})
        data = urllib.request.urlopen(req, timeout=240).read()
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
    return truth


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
    if doc['cities']:
        with open(OUT, 'w') as fh:
            json.dump(doc, fh, indent=0, sort_keys=True)
        print('wrote', OUT)


if __name__ == '__main__':
    main()
