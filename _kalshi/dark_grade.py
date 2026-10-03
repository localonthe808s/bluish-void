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
"""
import datetime, json, math, os, re, sys, time, urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'kalshi_dark.json')
WORKER = 'https://bluish-void-kalshi-cron.junkyjunkjunkjunkjunk.workers.dev'
KAPI = 'https://api.elections.kalshi.com/trade-api/v2'
START = datetime.date(2026, 10, 3)            # the first full day the live watcher ran
STUDY = {'ret': 0.027, 'se': 0.033, 'days': 28, 'note': 'in-sample study, 09-04..10-01'}
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


def copy_price(tk, t_iso):
    t0 = datetime.datetime.fromisoformat(t_iso.replace('Z', '+00:00')) + datetime.timedelta(seconds=120)
    j = get_json('%s/markets/trades?ticker=%s&min_ts=%d&max_ts=%d&limit=1000' % (KAPI, tk, t0.timestamp(), t0.timestamp() + 900))
    tr = sorted(j.get('trades') or [], key=lambda t: t['created_time'])
    return float(tr[0]['yes_price_dollars']) if tr else None


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
        if ds not in days and graded_now < 4:                  # a few per run: the bake is every five minutes
            try:
                rec = get_json('%s/dark?d=%s' % (WORKER, ds))
                ev = rec.get('event')
                if ev:
                    res = {m['ticker']: m.get('result') for m in get_json('%s/markets?event_ticker=%s' % (KAPI, ev)).get('markets', [])}
                    if res and all(v in ('yes', 'no') for v in res.values()):
                        out = []
                        for b in rec.get('bursts') or []:
                            if b.get('px') is None or b['tk'] not in res: continue
                            won_yes = res[b['tk']] == 'yes'
                            s, p = leg(b['side'], b['px'], won_yes)
                            cp = copy_price(b['tk'], b['t'])
                            g = dict(b, won=bool(p), ret=round(p / s - 1, 3))
                            if cp is not None and 0.01 < cp < 0.99:
                                cs, cpay = leg(b['side'], cp, won_yes)
                                g.update(copy_px=cp, copy_ret=round(cpay / cs - 1, 3))
                            out.append(g)
                        days[ds] = {'event': ev, 'bursts': out, 'releases': len(rec.get('releases') or [])}
                        graded_now += 1
                        print('dark grade %s: %d bursts (%d dark)' % (ds, len(out), sum(1 for b in out if b['cls'] == 'dark')))
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
    recent = sorted(((ds, b) for ds, r in days.items() for b in (r.get('bursts') or []) if b.get('cls') == 'dark'),
                    key=lambda x: x[1]['t'], reverse=True)[:12]
    doc = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'since': START.isoformat(),
           'study': STUDY, 'summary': summ, 'recent': [dict(b, day=ds) for ds, b in recent], 'days': days}
    with open(OUT, 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('dark grade: %d days graded; dark %s' % (len([1 for r in days.values() if r.get('event')]), summ['dark']))


if __name__ == '__main__':
    main()
