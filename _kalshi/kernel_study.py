#!/usr/bin/env python3
"""KERNEL VS NORMAL FOR THE SAME-DAY LADDER (2026-09-13). Nightly; writes
_kalshi/kernel.json, the per-city ruling the bake's ladder_probs() reads.

The noon ladder is a normal around the forecast, its width the standard
deviation of the last 45 residuals (regime-split on whether the observed
floor binds). The audit of 09-07 found the tails too fat: outcomes we call
20-35% land 0-20% in every city. A normal has one width for the centre and
the tails; the residual list itself does not. This replays ~600 archive days
per city (six-model archive, IEM daily max and :51 hourly reports), mirrors
the bake's lock (bias-corrected consensus of each run's remaining peak, the
observed floor plus the hourly offset, truncation at the running max), and
scores the normal against a kernel over the same residuals at 9 AM, noon and
3 PM local: multi-rung Brier and log loss on a six-rung Kalshi-shaped ladder
(both parities averaged) and the calibration of every 20-35% cell.

Ruling: a city uses the kernel when its best kernel variant beats the normal
on noon ladder Brier by at least 1% overall, in both halves of the record and
on the open (floor not binding) days -- the only days the bake applies it to.
First run: New York yes (.531 -> .489), Las Vegas no (.364 -> .374), Austin
no (a wash, .513 -> .513).

    python3 _kalshi/kernel_study.py            # all three cities, writes kernel.json
    python3 _kalshi/kernel_study.py --city ny  # one, prints only
"""
import os, sys, csv, io, json, math, time, statistics as st, collections, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K                                   # noqa: E402
D = os.path.join(HERE, '_study')
M = ['ncep_hrrr_conus', 'ncep_nbm_conus', 'ecmwf_ifs025', 'gfs_seamless', 'icon_seamless', 'gem_seamless']
CITIES = {c['key'].split('_')[0]: c for c in K.MARKETS}
OFFSET, RESID_M, SD_FLOOR, HOURS = 0.70, 45, 0.25, (9, 12)
SINCE = '2025-01-01'


def fetch(name, url):
    """Cached a day in _study/ (gitignored); the daily/hourly files are the
    same names and URLs afternoon_stats.py uses, so CI fetches each once."""
    os.makedirs(D, exist_ok=True)
    p = os.path.join(D, name)
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 20 * 3600:
        req = urllib.request.Request(url, headers={'User-Agent': 'bluishvoid.com kernel study'})
        data = urllib.request.urlopen(req, timeout=300).read()
        with open(p, 'wb') as fh:
            fh.write(data)
    return p
VARIANTS = [('normal45', 'normal', 45, None), ('normal45_ctr', 'normal_c', 45, None), ('normal90_ctr', 'normal_c', 90, None),
            ('kern45_k.4', 'kernel', 45, 0.4), ('kern45_k.6', 'kernel', 45, 0.6), ('kern90_k.5', 'kernel', 90, 0.5)]


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def load(city):
    cfg = CITIES[city]
    stn, net, tz = cfg['station'], cfg['network'], cfg['tz']
    y, m, d = time.strftime('%Y-%m-%d').split('-')
    scheme = 'ewma' if cfg.get('bias_hl') else 'flat'
    arch = fetch('%s_arch.json' % stn,
                 'https://historical-forecast-api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f&start_date=%s&end_date=%s-%s-%s'
                 '&hourly=temperature_2m&temperature_unit=fahrenheit&timezone=%s&models=%s'
                 % (cfg['lat'], cfg['lon'], SINCE, y, m, d, urllib.parse.quote(tz), ','.join(M)))
    dcsv = fetch('%s_daily.csv' % stn,
                 'https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?network=%s&stations=%s'
                 '&year1=2025&month1=1&day1=1&year2=%s&month2=%s&day2=%s&format=comma' % (net, stn, y, m, d))
    hcsv = fetch('%s_hourly.csv' % stn,
                 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=%s&data=tmpf'
                 '&year1=2025&month1=1&day1=1&year2=%s&month2=%s&day2=%s&tz=%s&format=onlycomma'
                 '&latlon=no&elev=no&missing=M&trace=T&direct=no&report_type=3'
                 % (stn, y, m, d, urllib.parse.quote(tz)))
    A = json.load(open(arch))['hourly']
    fc = collections.defaultdict(lambda: {m: {} for m in M})
    for i, t in enumerate(A['time']):
        for m in M:
            v = A['temperature_2m_' + m][i]
            if v is not None:
                fc[t[:10]][m][int(t[11:13])] = v
    truth = {}
    for r in csv.DictReader(open(dcsv)):
        v = r.get('max_temp_f')
        if v not in (None, '', 'M', 'None'):
            truth[r['day']] = float(v)
    obh = collections.defaultdict(dict)
    for r in csv.DictReader(open(hcsv)):
        if r['tmpf'] in ('M', ''):
            continue
        mn = int(r['valid'][14:16])
        if 45 <= mn <= 59:
            obh[r['valid'][:10]][int(r['valid'][11:13])] = float(r['tmpf'])
    days = sorted(d for d in fc if d in truth and len(obh.get(d, {})) >= 18
                  and all(len(fc[d][m]) >= 20 for m in M))
    return fc, truth, obh, days, scheme


def replay(fc, truth, obh, days, scheme):
    """-> {hour: [(day, pred, run, resid, binding)]} walk-forward."""
    peak = {d: {m: max(fc[d][m].values()) for m in M} for d in days}
    err = {d: {m: peak[d][m] - truth[d] for m in M} for d in days}
    out = {h: [] for h in HOURS}
    for i, d in enumerate(days):
        prior = days[max(0, i - 90):i]
        if len(prior) < 14:
            continue
        bias = {}
        for m in M:
            if scheme == 'ewma':
                num = den = 0.0
                for j, p in enumerate(prior):
                    w = 0.5 ** ((len(prior) - j) / 7.0)
                    num += w * err[p][m]; den += w
                bias[m] = num / den
            else:
                bias[m] = st.mean(err[p][m] for p in prior[-30:])
        for h in HOURS:
            p = st.mean(max(v for hh, v in fc[d][m].items() if hh >= h) - bias[m] for m in M)
            # the newest ROUTINE report in hand at h:00 is the (h-1):51 one; `hh <= h`
            # handed the noon replay the 12:51 reading, a 51-minute look-ahead that
            # doubled the binding share (26% vs 14%) -- fixed 2026-09-15
            run = max((v for hh, v in obh[d].items() if hh <= h - 1), default=None)
            floor = run + OFFSET if run is not None else -99.0
            pred = max(floor, p)
            out[h].append((d, pred, run, pred - truth[d], floor >= p))
    return out


def integer_probs(pred, ts, cut, kind, pool, k):
    """P(official max = t) for each integer t, truncated below cut."""
    if kind in ('normal', 'normal_c'):
        sd = max(st.pstdev(pool) if len(pool) > 1 else 1.0, SD_FLOOR)
        ctr = pred - (st.mean(pool) if kind == 'normal_c' else 0.0)   # normal_c: recentred on the residual mean
        f = lambda x: phi((x - ctr) / sd)
    else:
        f = lambda x: st.mean(phi((x - pred + r) / k) for r in pool)
    ps = []
    for t in ts:
        lo, hi = t - 0.5, t + 0.5
        if cut is not None:
            lo, hi = max(lo, cut), max(hi, cut)
        ps.append(max(0.0, f(hi) - f(lo)))
    s = sum(ps) or 1.0
    return [x / s for x in ps]


def ladder(ts, ps, c):
    """Six Kalshi-shaped rungs from the integer probabilities: <=c-1, c..c+1, c+2..c+3, c+4..c+5, c+6..c+7, >=c+8."""
    rungs = [(None, c - 1), (c, c + 1), (c + 2, c + 3), (c + 4, c + 5), (c + 6, c + 7), (c + 8, None)]
    out = []
    for lo, hi in rungs:
        out.append(sum(p for t, p in zip(ts, ps) if (lo is None or t >= lo) and (hi is None or t <= hi)))
    return rungs, out


OUT = os.path.join(HERE, 'kernel.json')
MIN_GAIN = 0.01


def score(city, rep):
    print('\n== %s' % city.upper())
    ruling = None
    for h in HOURS:
        rows = rep[h]
        res = {v[0]: {'brier': [], 'll': [], 'cells': collections.defaultdict(lambda: [0, 0]), 'n': 0, 'open': [], 'bind': [], 'ymd': []} for v in VARIANTS}
        for i, (d, pred, run, r, binding) in enumerate(rows):
            if i < 60:
                continue
            hist = rows[max(0, i - 120):i]
            truth_t = int(round(pred - r))
            ts = list(range(int(math.floor(pred)) - 8, int(math.floor(pred)) + 9))
            cut = (run - 0.5) if run is not None else None
            for name, kind, n, k in VARIANTS:
                same = [x for x in hist if x[4] == binding]
                pool = [x[3] for x in (same if len(same) >= 20 else hist)][-n:]
                if len(pool) < 20:
                    continue
                ps = integer_probs(pred, ts, cut, kind, pool, k)
                R = res[name]; R['n'] += 1
                for parity in (0, 1):
                    c = int(math.floor(pred)) - 2
                    c += (c + parity) % 2
                    rungs, lp = ladder(ts, ps, c)
                    hit = [1.0 if (lo is None or truth_t >= lo) and (hi is None or truth_t <= hi) else 0.0 for lo, hi in rungs]
                    R['brier'].append(sum((p - y) ** 2 for p, y in zip(lp, hit)))
                    (R['bind'] if binding else R['open']).append(R['brier'][-1]); R['ymd'].append(d)
                    pt = sum(p for p, y in zip(lp, hit) if y)
                    R['ll'].append(-math.log(max(pt, 1e-6)))
                    for p, y in zip(lp, hit):
                        b = min(int(p * 10), 9)
                        R['cells'][b][0] += 1; R['cells'][b][1] += y
        print('  %2d h  %-12s %5s %8s %8s | said 20-35%%: n, happened | said 10-20%%: n, happened' % (h, 'variant', 'n', 'Brier', 'logloss'))
        summary = {}
        for name, kind, n, k in VARIANTS:
            R = res[name]
            if not R['n']:
                continue
            c23 = [R['cells'][2], R['cells'][3]]; n23 = sum(x[0] for x in c23); h23 = sum(x[1] for x in c23)
            c1 = R['cells'][1]
            hh = len(R['brier']) // 2
            summary[name] = {'kind': kind, 'pool': n, 'k': k, 'n': R['n'], 'brier': round(st.mean(R['brier']), 4),
                             'logloss': round(st.mean(R['ll']), 4), 'halves': [round(st.mean(R['brier'][:hh]), 4), round(st.mean(R['brier'][hh:]), 4)],
                             'open': round(st.mean(R['open']), 4) if R['open'] else None, 'open_n': len(R['open']) // 2,
                             'bind': round(st.mean(R['bind']), 4) if R['bind'] else None}
            print('        %-12s %5d %8.4f %8.4f | %5d  %.3f            | %5d  %.3f | halves %.4f/%.4f open %.4f (n%d) bind %.4f (n%d)'
                  % (name, R['n'], st.mean(R['brier']), st.mean(R['ll']), n23, h23 / n23 if n23 else float('nan'),
                     c1[0], c1[1] / c1[0] if c1[0] else float('nan'), st.mean(R['brier'][:hh]), st.mean(R['brier'][hh:]),
                     st.mean(R['open']) if R['open'] else float('nan'), len(R['open']) // 2, st.mean(R['bind']) if R['bind'] else float('nan'), len(R['bind']) // 2))
        if h == 12 and 'normal45' in summary:
            base = summary['normal45']
            kern = [v for v in summary.values() if v['kind'] == 'kernel']
            best = min(kern, key=lambda v: v['brier']) if kern else None
            ok = bool(best) and base['brier'] > 0 and all([
                best['brier'] <= base['brier'] * (1 - MIN_GAIN),
                best['halves'][0] <= base['halves'][0] * (1 - MIN_GAIN),
                best['halves'][1] <= base['halves'][1] * (1 - MIN_GAIN),
                (best['open'] or 9) <= (base['open'] or 0) * (1 - MIN_GAIN)])
            ruling = {'use': ok, 'hour': h, 'n': base['n'], 'k': best['k'] if best else None, 'pool': best['pool'] if best else None,
                      'normal': base, 'kernel': best, 'min_gain': MIN_GAIN}
            print('  RULING: %s (%s)' % ('KERNEL k=%s pool=%d' % (best['k'], best['pool']) if ok else 'NORMAL', 'Brier %.4f vs %.4f' % (best['brier'], base['brier']) if best else '-'))
    return ruling

def main():
    import time
    only = '--city' in sys.argv
    cities = sys.argv[sys.argv.index('--city') + 1].split(',') if only else list(CITIES)
    doc = {'built': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime()), 'cities': {}}
    for c in cities:
        try:
            fc, truth, obh, days, scheme = load(c)
            print('%s: %d days %s..%s (%s bias)' % (c, len(days), days[0], days[-1], scheme))
            r = score(c, replay(fc, truth, obh, days, scheme))
            if r:
                r['days'] = [days[0], days[-1]]
                doc['cities'][c + '_high'] = r
        except Exception as e:
            print('%s: kernel study failed (%s)' % (c, e))
    if doc['cities'] and not only:
        with open(OUT, 'w') as fh:
            json.dump(doc, fh, indent=0, sort_keys=True)
        print('wrote', OUT)


if __name__ == '__main__':
    main()
