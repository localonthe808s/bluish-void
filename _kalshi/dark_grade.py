#!/usr/bin/env python3
"""
DARK FLOW, GRADED (2026-10-02). The worker records every New York burst of one-sided aggressive money live
(kalshi-cron.js darkTick, public at /dark?d=YYYY-MM-DD) and labels it DARK (no public reading behind it) or REACTION.
This grades each settled day once and keeps the record in kalshi_dark.json, which the sheet draws as a scorecard.

The study that motivated it (insider_study.py, 28 days before the watcher existed) found dark bursts +2.7% (se 3.3)
against reactions -5.8%. That was in sample. This is the forward test: only days the watcher saw live count here.

For every burst: did its side win, the return at the price IT paid (the burst's own volume-weighted YES price), and
the return of COPYING it -- the first trade at least 60 s after its minute closed, which is the price anyone watching
could actually get. Fee 0.07 * P * (1 - P) per contract. Returns are stake-weighted, standard errors clustered by day.

ONE RULEBOOK (2026-10-02). The bursts graded here are REBUILT FROM THE TAPE with the study's own rule (dark_lib.py:
adaptive threshold, split orders merged), not taken from the live watcher, which can only use a flat $150 in real
time. The live record supplies what the tape cannot: when TWC's running maximum rose. Central Park reports, climate
reports and NWS forecast issues are joined from IEM as well, so a gap in the live clock cannot make a burst look dark.
Each burst also carries its markouts (+5/15/60 min) and the move across the next Central Park report -- the fast
verdict, measurable within the hour, where settlement takes months.
"""
import bisect, datetime, json, math, os, re, sys, time, urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dark_lib as DL                               # noqa: E402
import insider_study as IS                         # noqa: E402  the study's public clock (IEM)
OUT = os.path.join(HERE, '..', 'kalshi_dark.json')
WORKER = 'https://bluish-void-kalshi-cron.junkyjunkjunkjunkjunk.workers.dev'
KAPI = 'https://api.elections.kalshi.com/trade-api/v2'
START = datetime.date(2026, 10, 3)            # the first full day the live watcher ran
WIN = {'metar': 9, 'cli': 10, 'twc': 6, 'fcst': 10}   # minutes a release covers, as in the worker and the study
UA = {'User-Agent': 'bluishvoid-dark-grade'}
ET = ZoneInfo('America/New_York')


def get_json(url, tries=5):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45))
        except Exception:
            if i == tries - 1: raise
            time.sleep(3 * (2 ** i))


def fee(p):
    return 0.07 * p * (1 - p)


def leg(side, yes_px, won_yes):
    p = yes_px if side == 'yes' else 1 - yes_px
    stake = p + fee(p)
    return stake, (1.0 if (won_yes if side == 'yes' else not won_yes) else 0.0)


def clustered(groups):
    S = sum(s for s, _ in groups.values()); P = sum(p for _, p in groups.values())
    if S <= 0: return None
    r = P / S - 1; n = len(groups)
    se = (math.sqrt(n / (n - 1) * sum((p - (1 + r) * s) ** 2 for s, p in groups.values())) / S) if n > 1 else None
    return {'ret': round(r, 3), 'se': None if se is None else round(se, 3), 'days': n}


def tape(tk, t0, t1):
    rows, cur = [], ''
    while True:
        j = get_json('%s/markets/trades?ticker=%s&min_ts=%d&max_ts=%d&limit=1000%s'
                     % (KAPI, tk, t0.timestamp(), t1.timestamp(), '&cursor=' + cur if cur else ''))
        for t in j.get('trades') or []:
            rows.append((IS.ts(t['created_time']), float(t['yes_price_dollars']), float(t['count_fp']), t['taker_side']))
        cur = j.get('cursor') or ''
        if not cur: break
        time.sleep(0.2)
    return sorted(rows)


def study():
    try:
        ny = json.load(open(os.path.join(HERE, 'insider_study.json')))['cities']['ny_high']
        d = ny['bursts']['dark']; mv = (ny.get('moves') or {}).get('dark') or {}
        return {'ret': d.get('ret'), 'se': d.get('se'), 'days': ny.get('days'), 'n': d.get('n'),
                'mo60': mv.get('60'), 'next_report': mv.get('next_report'), 'rule': ny.get('rule')}
    except Exception:
        return {}


def grade_day(d, rec):
    ev = rec.get('event')
    res = {m['ticker']: m.get('result') for m in get_json('%s/markets?event_ticker=%s' % (KAPI, ev)).get('markets', [])}
    if not res or not all(v in ('yes', 'no') for v in res.values()):
        return None                                                    # not settled yet: try on a later run
    labs = {m['tk']: m['lab'] for m in rec.get('markets') or []}
    c = IS.CITIES['ny_high']
    rel = []
    for r in rec.get('releases') or []:
        t = datetime.datetime.fromisoformat(r['t'].replace('Z', '+00:00')); rel.append((t, t + datetime.timedelta(minutes=WIN.get(r['k'], 9)), r['k']))
    d0, d1 = d - datetime.timedelta(days=1), d + datetime.timedelta(days=1)
    reports = sorted(set(IS.metar_times(c, d0, d1) + [x[0] for x in rel if x[2] == 'metar']))
    rel += [(t, t + datetime.timedelta(minutes=WIN['metar']), 'metar') for t in reports]
    rel += [(t, t + datetime.timedelta(minutes=WIN['cli']), 'cli') for t in IS.cli_times(c, d0, d1)]
    rel += [(t, t + datetime.timedelta(minutes=WIN['fcst']), 'fcst') for t in IS.fcst_times(c, d0, d1)]
    covered = lambda t: any(a <= t <= b for a, b, _ in rel)
    lo = datetime.datetime(d.year, d.month, d.day, 7, tzinfo=ET); hi = datetime.datetime(d.year, d.month, d.day, 20, tzinfo=ET)
    out = []
    for tk, result in res.items():
        tp = tape(tk, lo - datetime.timedelta(hours=1), hi + datetime.timedelta(minutes=90))
        times = [x[0] for x in tp]
        won_yes = result == 'yes'
        _, bl = DL.bursts([x for x in tp if lo <= x[0] < hi])
        for b in bl:
            if b['px'] is None: continue
            s_, p_ = leg(b['side'], b['px'], won_yes)
            g = {'t': b['t0'].isoformat().replace('+00:00', 'Z'), 't1': b['t1'].isoformat().replace('+00:00', 'Z'), 'tk': tk,
                 'lab': labs.get(tk, tk.split('-')[-1]), 'side': b['side'], 'usd': round(b['usd']), 'px': round(b['px'], 3),
                 'minutes': b['minutes'], 'cls': 'reaction' if covered(b['t0']) else 'dark',
                 'won': bool(p_), 'ret': round(p_ / s_ - 1, 3),
                 'mo': DL.markouts(b, times, tp), 'next_report': DL.release_move(b, times, tp, reports)}
            # COPYING: the first trade at least a minute after the burst's last minute closed
            i = bisect.bisect_left(times, b['t1'] + datetime.timedelta(minutes=2))
            if i < len(tp) and tp[i][0] - b['t1'] < datetime.timedelta(minutes=17) and 0.01 < tp[i][1] < 0.99:
                cs, cpay = leg(b['side'], tp[i][1], won_yes)
                g.update(copy_px=tp[i][1], copy_ret=round(cpay / cs - 1, 3))
            out.append(g)
    return {'event': ev, 'bursts': out, 'live_bursts': len(rec.get('bursts') or []), 'releases': len(rel), 'rule': 'dark_lib'}


def main():
    doc = {}
    try:
        with open(OUT) as f: doc = json.load(f)
    except Exception:
        doc = {}
    days = doc.get('days') or {}
    today = datetime.datetime.now(ET).date()
    d = START
    graded_now = 0
    while d < today:
        ds = d.isoformat()
        if (ds not in days or days[ds].get('rule') != 'dark_lib' and days[ds].get('event')) and graded_now < 2:
            try:
                rec = get_json('%s/dark?d=%s' % (WORKER, ds))
                if rec.get('event'):
                    g = grade_day(d, rec)
                    if g:
                        days[ds] = g; graded_now += 1
                        print('dark grade %s: %d bursts (%d dark), %d in the live record'
                              % (ds, len(g['bursts']), sum(1 for b in g['bursts'] if b['cls'] == 'dark'), g['live_bursts']))
                else:
                    days[ds] = {'event': None, 'bursts': [], 'note': 'no live record'}
            except Exception as e:
                print('dark grade %s: skipped (%s)' % (ds, e))
        d += datetime.timedelta(days=1)

    summ = {}
    for cls in ('dark', 'reaction'):
        at, cp = {}, {}
        n = won = 0
        for ds, rec in days.items():
            for b in rec.get('bursts') or []:
                if b.get('cls') != cls: continue
                n += 1; won += 1 if b['won'] else 0
                s, p = leg(b['side'], b['px'], b['won'] if b['side'] == 'yes' else not b['won'])
                a = at.setdefault(ds, [0.0, 0.0]); a[0] += s; a[1] += p
                if b.get('copy_px') is not None:
                    s2, p2 = leg(b['side'], b['copy_px'], b['won'] if b['side'] == 'yes' else not b['won'])
                    c = cp.setdefault(ds, [0.0, 0.0]); c[0] += s2; c[1] += p2
        summ[cls] = {'n': n, 'won': won, 'at_their_price': clustered(at), 'copying': clustered(cp)}
    moves = DL.summarize_moves([(ds, b['cls'], b.get('mo') or {}, b.get('next_report'))
                                for ds, r in days.items() for b in (r.get('bursts') or [])])
    for cls in summ: summ[cls]['moves'] = moves.get(cls)
    recent = sorted(((ds, b) for ds, r in days.items() for b in (r.get('bursts') or []) if b.get('cls') == 'dark'),
                    key=lambda x: x[1]['t'], reverse=True)[:12]
    doc = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'since': START.isoformat(),
           'study': study(), 'rule': {'floor': DL.FLOOR_USD, 'pctl': DL.PCTL, 'merge_min': DL.MERGE_GAP_MIN}, 'summary': summ, 'recent': [dict(b, day=ds) for ds, b in recent], 'days': days}
    with open(OUT, 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('dark grade: %d days graded; dark %s' % (len([1 for r in days.values() if r.get('event')]), summ['dark']))


if __name__ == '__main__':
    main()
