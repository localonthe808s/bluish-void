#!/usr/bin/env python3
"""
THE DARK TREND (2026-10-12, user: "review how the dark flow is working, is there further insight you can build from this
trend?"). The burst-level tests (insider_study.py, dark_grade.py) ask whether ONE dark burst beat its price. This asks
whether the ACCUMULATION does: the net dark money on each range by a moment of the day (8 AM, noon, 2 PM, 6 PM), YES
dollars minus NO dollars, against where the day settled -- measured against the PRICE at that moment, so a range the
market already favours earns nothing for being the favourite.
  residual  = settled (1/0) - last YES price at the moment          (what the price had not yet priced)
  lean      = the range with the most net dark YES money by the moment
  tests     : mean residual of ranges dark money leans YES vs NO on; the lean's hit rate vs the market favourite's;
              buying the lean at the moment's price (after fee), return on stake with a day-clustered error.
Reaction flow (bursts inside a public release window) is scored the same way as the control.
Same rulebook and cache as insider_study.py (dark_lib bursts, the release clock). Offline by default.
    python3 dark_trend_study.py [--online]
Writes dark_trend_study.json.
"""
import sys, os, json, math, collections, datetime, bisect
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if '--online' not in sys.argv: sys.argv.append('--offline')
import insider_study as S          # noqa: E402
import dark_lib as DL              # noqa: E402

MOMENTS = (8, 12, 14, 18)
key, c = 'ny_high', S.CITIES['ny_high']
z = ZoneInfo(c['tz'])
evs = S.cached('events_%s.json' % c['series'], lambda: S.settled_events(c['series']), max_age_h=6) or {}
evs = {e: m for e, m in evs.items() if S.event_day(e) >= S.SINCE and any(x['result'] == 'yes' for x in m)}
days = sorted(S.event_day(e) for e in evs); d0, d1 = days[0], days[-1]
rel = [(t, t + datetime.timedelta(minutes=S.METAR_WIN), 'metar') for t in S.metar_times(c, d0, d1 + datetime.timedelta(days=1))]
rel += [(t, t + datetime.timedelta(minutes=S.CLI_WIN), 'cli') for t in S.cli_times(c, d0, d1)]
rel += [(t, t + datetime.timedelta(minutes=S.FCST_WIN), 'fcst') for t in S.fcst_times(c, d0, d1)]
rel += [(a, b + datetime.timedelta(minutes=S.TWC_WIN), 'twc') for a, b in S.twc_bumps(key)]
rel.sort(); starts = [r[0] for r in rel]
def public_at(t):
    i = bisect.bisect_right(starts, t)
    return any(rel[j][0] <= t <= rel[j][1] for j in range(max(0, i - 40), i))

rows = []          # (day, moment, cls, ticker, net_usd, price, won)
used = 0
for ev, mk in sorted(evs.items()):
    day = S.event_day(ev)
    per = []
    for m in mk:
        tr = S.trades(m['ticker'])
        if tr is None: per = None; break
        tape = sorted((S.ts(t), p, n, sd) for t, p, n, sd in tr)
        fills = [(tt, p, n, sd) for tt, p, n, sd in tape if tt.astimezone(z).date() == day and S.WINDOW_H[0] <= tt.astimezone(z).hour < S.WINDOW_H[1]]
        _, bl = DL.bursts(fills)
        per.append((m, tape, bl))
    if not per: continue
    used += 1
    for M in MOMENTS:
        cut = datetime.datetime(day.year, day.month, day.day, M, 0, tzinfo=z)
        for m, tape, bl in per:
            px = None
            for tt, p, n, sd in tape:
                if tt <= cut: px = p
                else: break
            if px is None: continue
            net = {'dark': 0.0, 'reaction': 0.0}
            for b in bl:
                if b['t0'] >= cut: continue
                cls = 'reaction' if public_at(b['t0']) else 'dark'
                net[cls] += b['usd'] * (1 if b['side'] == 'yes' else -1)
            for cls in net:
                rows.append((day.isoformat(), M, cls, m['ticker'], net[cls], px, 1 if m['result'] == 'yes' else 0))

def clustered_mean(vals):          # vals: {day: [x...]} -> mean, day-clustered se
    allx = [x for v in vals.values() for x in v]
    if len(allx) < 2: return None
    mu = sum(allx) / len(allx); n = len(vals)
    if n < 2: return {'mean': round(mu, 4), 'n': len(allx), 'days': n}
    sums = [sum(x - mu for x in v) for v in vals.values()]
    se = math.sqrt(n / (n - 1) * sum(s * s for s in sums)) / len(allx)
    return {'mean': round(mu, 4), 'se': round(se, 4), 'n': len(allx), 'days': n}

out = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'days': used, 'since': str(d0), 'until': str(d1), 'moments': {}}
for M in MOMENTS:
    res = {}
    for cls in ('dark', 'reaction'):
        R = [r for r in rows if r[1] == M and r[2] == cls]
        yes = collections.defaultdict(list); no = collections.defaultdict(list); quiet = collections.defaultdict(list)
        for d, _, _, tk, net, px, won in R:
            (yes if net > 0 else no if net < 0 else quiet)[d].append(won - px)
        byday = collections.defaultdict(list)
        for r in R: byday[r[0]].append(r)
        lean_hit = fav_hit = nlean = 0; ret = {}
        for d, rr in byday.items():
            fav = max(rr, key=lambda r: r[5])
            ld = max(rr, key=lambda r: r[4])
            if ld[4] <= 0: continue
            nlean += 1; lean_hit += ld[6]; fav_hit += fav[6]
            p = ld[5]; fee = math.ceil(0.07 * p * (1 - p) * 100) / 100
            ret[d] = (p + fee, float(ld[6]))
        # THE CONTROL (favourites are underpriced on their own): the favourite's residual on days this flow backed it
        # (its biggest net YES range was the favourite) against days it did not
        fb = collections.defaultdict(list); fn = collections.defaultdict(list)
        for d, rr in byday.items():
            fav = max(rr, key=lambda r: r[5]); ld = max(rr, key=lambda r: r[4])
            (fb if (ld[4] > 0 and ld[3] == fav[3]) else fn)[d].append(fav[6] - fav[5])
        res[cls + '_fav'] = {'backed': clustered_mean(fb), 'not_backed': clustered_mean(fn)}
        res[cls] = {'resid_yes_lean': clustered_mean(yes), 'resid_no_lean': clustered_mean(no), 'resid_quiet': clustered_mean(quiet),
                    'lean_days': nlean, 'lean_hit': lean_hit, 'fav_hit_same_days': fav_hit,
                    'buy_lean': S.clustered(ret) if ret else None}
    out['moments'][str(M)] = res
json.dump(out, open(os.path.join(HERE, 'dark_trend_study.json'), 'w'), indent=1)
print(json.dumps(out, indent=1))
