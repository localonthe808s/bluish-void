#!/usr/bin/env python3
"""
THE REPORT (2026-09-27, user: "build an evolving report that addresses daily summaries but also
summarizes our overall progress"). One file, kalshi_report.json, rebuilt at the end of every bake
from what the bakes have already published -- no fetches, under a second -- and drawn by
/report/index.html.

WHAT IS IN IT
  today     the six calls as they stand, locked or still a draft
  days      one entry per settled day, newest first: every market's call against the settlement
            and against the market's own pick, the bet that was named or withheld and how it
            graded, and the day said in sentences
  overall   the live record since launch: by market, by week, a rolling week, stated confidence
            against what happened, our ladder against the market's, the bets, the edge courts
  eras      the same record cut at each change that was meant to move it (report_log.json), so
            "did that help" has a number under it
  log       what was changed, when and why -- typed by hand into report_log.json

WHAT IS NOT IN IT. Nothing of the account: no fills, no positions, no balance, no stake. The
files this reads have already been through redact_money(), and the bets scored here are the
sheet's own, one contract each at the price and fee the bake recorded.

IT KEEPS ITS OWN DAYS. A settled day is merged into the previous report rather than rebuilt from
nothing, so a day survives even if a bake file ever stops carrying it.
"""
import json, math, os, sys, datetime, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
OUT = os.path.join(ROOT, 'kalshi_report.json')
LOG = os.path.join(HERE, 'report_log.json')

MARKETS = [
    ('ny_high',  'kalshi_ny.json',      'New York high',  'high', 'New York'),
    ('las_high', 'kalshi_las.json',     'Las Vegas high', 'high', 'Las Vegas'),
    ('aus_high', 'kalshi_aus.json',     'Austin high',    'high', 'Austin'),
    ('ny_low',   'kalshi_low_ny.json',  'New York low',   'low',  'New York'),
    ('las_low',  'kalshi_low_las.json', 'Las Vegas low',  'low',  'Las Vegas'),
    ('aus_low',  'kalshi_low_aus.json', 'Austin low',     'low',  'Austin'),
]
# the leg a bet is made on: a high at the noon lock, a low the evening before
BET_LEGS = {'high': ('lock', 'eve'), 'low': ('eve', 'lock')}
LEG_NAME = {('high', 'lock'): 'noon', ('high', 'eve'): 'evening before',
            ('low', 'lock'): '8 AM', ('low', 'eve'): 'evening before'}


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def bare(label):
    return str(label or '').replace('°', '')


def fee_of(price):
    # the bake's own (kalshi_daily.fee_of); used only for a bet that was stored without its fee
    return min(0.035, math.ceil(0.07 * price * (1 - price) * 100) / 100.0)


def grade(bet, bracket):
    """(won, return per contract in dollars) for one contract at the recorded price and fee"""
    if not isinstance(bet, dict) or bet.get('price') is None or not bet.get('label') or bracket is None:
        return None
    won = (bet['label'] == bracket) if bet.get('dir') == 'for' else (bet['label'] != bracket)
    p = float(bet['price'])
    fee = float(bet['fee']) if bet.get('fee') is not None else fee_of(p)
    return bool(won), round(((1.0 - p) if won else -p) - fee, 4)


def settled_prob(ladder, bracket, field):
    """the probability a ladder gave the bracket that settled, the ladder renormalised"""
    vals = [max(1e-4, float(r.get(field) or 0)) for r in ladder]
    k = [i for i, r in enumerate(ladder) if r.get('label') == bracket]
    if len(k) != 1 or any(r.get(field) is None for r in ladder):
        return None
    return vals[k[0]] / sum(vals)


def market_day(key, label, kind, h):
    """one market on one settled day"""
    L = h.get('lock') or {}
    out = {'key': key, 'label': label, 'kind': kind,
           'pick': L.get('pick'), 'said': L.get('p'), 'pred': L.get('pred'), 'at': L.get('at'),
           'actual': h.get('actual'), 'bracket': h.get('actual_bracket'), 'err': h.get('err'),
           'hit': bool(h.get('hit')),
           'mkt_pick': L.get('market_pick'), 'mkt_said': L.get('market_p'),
           'mkt_hit': (bool(h.get('market_hit')) if L.get('market_pick') else None),
           'agree': (L.get('pick') == L.get('market_pick')) if L.get('market_pick') else None,
           'bets': []}
    lad = L.get('ladder') or []
    if lad and h.get('actual_bracket'):
        out['p_ours'] = settled_prob(lad, h['actual_bracket'], 'ours')
        out['p_mkt'] = settled_prob(lad, h['actual_bracket'], 'market')
    if h.get('eve'):
        out['eve_pick'] = h['eve'].get('pick')
        out['eve_hit'] = (h['eve'].get('pick') == h.get('actual_bracket'))
    if h.get('final'):
        out['final_pick'] = h['final'].get('pick')
        out['final_hit'] = (h['final'].get('pick') == h.get('actual_bracket'))
    for leg in BET_LEGS[kind]:
        blk = h.get(leg) or {}
        for named, b in ((True, blk.get('bet')), (False, blk.get('shadow'))):
            g = grade(b, h.get('actual_bracket'))
            if g:
                out['bets'].append({'leg': LEG_NAME[(kind, leg)], 'named': named, 'dir': b.get('dir'),
                                    'label': b.get('label'), 'price': b.get('price'), 'q': b.get('q'),
                                    'won': g[0], 'ret': g[1]})
    return out


def money(x):
    return ('+' if x >= 0 else '−') + ('%d¢' % round(abs(x) * 100))


def say_day(day):
    """the day in sentences"""
    ms = day['markets']
    n, hits = len(ms), sum(1 for m in ms if m['hit'])
    priced = [m for m in ms if m['mkt_hit'] is not None]
    mh = sum(1 for m in priced if m['mkt_hit'])
    lines = ['%d of %d calls landed%s.' % (hits, n, ('; the market’s own picks landed %d of %d' % (mh, len(priced))) if priced else '')]
    for m in ms:
        if m['hit'] or m['pick'] is None:
            continue
        e = m.get('err')
        how = ''
        if e is not None and m.get('pred') is not None:
            how = ' The forecast was %.1f°, %.1f° too %s.' % (m['pred'], abs(e), ('warm' if e > 0 else 'cold'))
        mk = ''
        if m['mkt_hit'] is True:
            mk = ' The market had it (%s%s).' % (bare(m['mkt_pick']), (' at %d%%' % round(100 * m['mkt_said'])) if m.get('mkt_said') is not None else '')
        elif m['mkt_hit'] is False:
            mk = ' The market missed too.' if m['agree'] else ' The market missed as well, on %s.' % bare(m['mkt_pick'])
        lines.append('%s settled %d°, in %s. The call was %s at %d%%.%s%s' % (
            m['label'], round(m['actual']), bare(m['bracket']), bare(m['pick']), round(100 * (m['said'] or 0)), how, mk))
    won_alone = [m for m in ms if m['hit'] and m['mkt_hit'] is False]
    if won_alone:
        lines.append('Ahead of the market on %s.' % ', '.join('%s (%s against its %s)' % (m['label'], bare(m['pick']), bare(m['mkt_pick'])) for m in won_alone))
    big = [m for m in ms if not m['hit'] and (m['said'] or 0) >= 0.85]
    if big:
        lines.append('Confidently wrong on %s: said %s.' % (
            ', '.join(m['label'] for m in big), ', '.join('%d%%' % round(100 * m['said']) for m in big)))
    bets = [b for m in ms for b in m['bets']]
    for named, word in ((True, 'named'), (False, 'withheld by the edge court')):
        bs = [b for b in bets if b['named'] == named]
        if bs:
            stake = sum(b['price'] for b in bs)
            lines.append('%d bet%s %s: %d won, %s per $1 staked.' % (
                len(bs), '' if len(bs) == 1 else 's', word, sum(1 for b in bs if b['won']),
                money(sum(b['ret'] for b in bs) / stake)))
    return lines


def tally(ms):
    """the record over a list of market-days"""
    n = len(ms)
    if not n:
        return {'n': 0}
    priced = [m for m in ms if m['mkt_hit'] is not None]
    errs = [m['err'] for m in ms if m.get('err') is not None]
    said = [m['said'] for m in ms if m.get('said') is not None]
    both = [m for m in ms if m.get('p_ours') is not None and m.get('p_mkt') is not None]
    out = {'n': n, 'hits': sum(1 for m in ms if m['hit']),
           'said': round(sum(said) / len(said), 3) if said else None,
           'mkt_n': len(priced), 'mkt_hits': sum(1 for m in priced if m['mkt_hit']),
           'mkt_said': round(sum(m['mkt_said'] for m in priced if m.get('mkt_said') is not None) / max(1, len([m for m in priced if m.get('mkt_said') is not None])), 3) if priced else None,
           'mae': round(sum(abs(e) for e in errs) / len(errs), 2) if errs else None,
           'bias': round(sum(errs) / len(errs), 2) if errs else None,
           'differ': len([m for m in priced if m['agree'] is False]),
           'differ_ours': len([m for m in priced if m['agree'] is False and m['hit']]),
           'differ_mkt': len([m for m in priced if m['agree'] is False and m['mkt_hit']])}
    if both:
        out['ll_n'] = len(both)
        out['ll_ours'] = round(sum(-math.log(m['p_ours']) for m in both) / len(both), 3)
        out['ll_mkt'] = round(sum(-math.log(m['p_mkt']) for m in both) / len(both), 3)
    out['bets'] = bet_tally([b for m in ms for b in m['bets']])
    legs = collections.OrderedDict()
    for m in ms:
        for b in m['bets']:
            legs.setdefault((m['kind'], b['leg']), []).append(b)
    out['bets_by_leg'] = [dict(bet_tally(v), kind=k[0], leg=k[1]) for k, v in legs.items()]
    return out


def bet_tally(bs):
    n = len(bs)
    if not n:
        return {'n': 0}
    stake = sum(b['price'] for b in bs)
    ret = sum(b['ret'] for b in bs) / stake
    var = sum((b['ret'] - ret * b['price']) ** 2 for b in bs) / max(1, n - 1)
    qs = [b['q'] for b in bs if b.get('q') is not None]
    return {'n': n, 'won': sum(1 for b in bs if b['won']), 'ret': round(ret, 3),
            'se': round(math.sqrt(var / n) / (stake / n), 3),
            'said': round(sum(qs) / len(qs), 3) if qs else None,
            'named': len([b for b in bs if b['named']]), 'withheld': len([b for b in bs if not b['named']])}


def monday(d):
    x = datetime.date.fromisoformat(d)
    return (x - datetime.timedelta(days=x.weekday())).isoformat()


def main():
    prev = load(OUT) or {}
    days = {d['date']: d for d in (prev.get('days') or []) if d.get('date')}
    today, gates = [], []
    built = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    fresh = collections.defaultdict(dict)
    for key, fn, label, kind, city in MARKETS:
        doc = load(os.path.join(ROOT, fn))
        if not doc:
            print('report: %s unreadable, its days are kept as they were' % fn)
            continue
        for h in doc.get('history') or []:
            if h.get('backtest') or h.get('actual') is None or not h.get('actual_bracket') or not (h.get('lock') or {}).get('pick'):
                continue
            fresh[h['date']][key] = market_day(key, label, kind, h)
        T = doc.get('today') or {}
        L = T.get('locked') or {}
        tm = T.get('tomorrow') or {}
        today.append({'key': key, 'label': label, 'kind': kind, 'date': T.get('date'), 'updated': doc.get('updated'),
                      'locked': bool(L), 'pick': L.get('pick') or T.get('pick'), 'said': L.get('p') if L else T.get('p'),
                      'pred': L.get('pred') if L else T.get('pred'), 'at': L.get('at'),
                      'mkt_pick': L.get('market_pick') or T.get('market_pick'),
                      'mkt_said': L.get('market_p') if L else T.get('market_p'),
                      'now_pick': T.get('pick'), 'now_said': T.get('p'), 'so_far': T.get('obs_so_far'),
                      'over': bool(T.get('day_over')), 'decided': bool(T.get('day_decided')),
                      'tomorrow': ({'date': tm.get('date'), 'pick': tm.get('pick'), 'said': tm.get('p'), 'pred': tm.get('pred'),
                                    'mkt_pick': tm.get('market_pick')} if tm.get('pick') else None)})
        for leg, g in (('today', T.get('edge_gate')), ('evening plan', tm.get('edge_gate'))):
            if isinstance(g, dict):
                gates.append({'key': key, 'label': label, 'leg': leg, 'open': bool(g.get('open')), 'n': g.get('n'),
                              'won': g.get('won'), 'ret': g.get('ret'), 'se': g.get('se'),
                              'need_n': g.get('need_n'), 'window': g.get('window')})

    order = [m[0] for m in MARKETS]
    for d, by in fresh.items():
        old = {m['key']: m for m in (days.get(d) or {}).get('markets', [])}
        old.update(by)                       # what the bakes say now wins; what they no longer carry is kept
        days[d] = {'date': d, 'markets': [old[k] for k in order if k in old]}
    for d in days.values():
        ms = d['markets']
        d.update({'n': len(ms), 'hits': sum(1 for m in ms if m['hit']),
                  'mkt_n': len([m for m in ms if m['mkt_hit'] is not None]),
                  'mkt_hits': sum(1 for m in ms if m['mkt_hit']),
                  'lines': say_day(d)})
    dates = sorted(days)
    allm = [m for d in dates for m in days[d]['markets']]

    # by week, and a rolling seven days
    weeks = collections.OrderedDict()
    for d in dates:
        weeks.setdefault(monday(d), []).extend(days[d]['markets'])
    week_rows = [dict(tally(ms), week=w, days=len(set(x for x in dates if monday(x) == w))) for w, ms in weeks.items()]
    rolling = []
    for i, d in enumerate(dates):
        win = [m for x in dates[max(0, i - 6):i + 1] for m in days[x]['markets']]
        pr = [m for m in win if m['mkt_hit'] is not None]
        if len(win) >= 12:
            rolling.append({'date': d, 'n': len(win), 'ours': round(sum(1 for m in win if m['hit']) / len(win), 3),
                            'mkt': round(sum(1 for m in pr if m['mkt_hit']) / len(pr), 3) if pr else None})

    # stated confidence against what happened, on the call itself
    calib = []
    for lo, hi in ((0, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
        c = [m for m in allm if m.get('said') is not None and lo <= m['said'] < hi]
        k = [m for m in allm if m.get('mkt_said') is not None and m['mkt_hit'] is not None and lo <= m['mkt_said'] < hi]
        calib.append({'lo': lo, 'hi': min(hi, 1.0), 'n': len(c),
                      'said': round(sum(m['said'] for m in c) / len(c), 3) if c else None,
                      'hit': round(sum(1 for m in c if m['hit']) / len(c), 3) if c else None,
                      'mkt_n': len(k), 'mkt_said': round(sum(m['mkt_said'] for m in k) / len(k), 3) if k else None,
                      'mkt_hit': round(sum(1 for m in k if m['mkt_hit']) / len(k), 3) if k else None})

    last7 = [m for d in dates[-7:] for m in days[d]['markets']]
    prior7 = [m for d in dates[-14:-7] for m in days[d]['markets']]
    overall = {'since': dates[0] if dates else None, 'through': dates[-1] if dates else None, 'days': len(dates),
               'all': tally(allm),
               'highs': tally([m for m in allm if m['kind'] == 'high']),
               'lows': tally([m for m in allm if m['kind'] == 'low']),
               'by_market': [dict(tally([m for m in allm if m['key'] == k]), key=k, label=lab) for k, _, lab, _, _ in MARKETS],
               'last7': dict(tally(last7), frm=dates[-7] if len(dates) >= 7 else (dates[0] if dates else None), to=dates[-1] if dates else None),
               'prior7': dict(tally(prior7), frm=dates[-14] if len(dates) >= 14 else None, to=dates[-8] if len(dates) >= 8 else None),
               'weeks': week_rows, 'rolling': rolling, 'calibration': calib, 'gates': gates}

    # the log, and the record cut at each change that was meant to move it
    log = (load(LOG) or {}).get('entries') or []
    cuts = sorted(set(e['date'] for e in log if e.get('era')))
    eras = []
    for i, c in enumerate(cuts):
        nxt = cuts[i + 1] if i + 1 < len(cuts) else '9999'
        # a change made on day D first shows in the calls locked on D+1
        ms = [m for d in dates if c < d <= nxt for m in days[d]['markets']]
        eras.append(dict(tally(ms), frm=c, to=(nxt if nxt != '9999' else None),
                         label='; '.join(e['title'] for e in log if e.get('era') and e['date'] == c),
                         days=len([d for d in dates if c < d <= nxt])))
    if cuts and dates and dates[0] <= cuts[0]:
        ms = [m for d in dates if d <= cuts[0] for m in days[d]['markets']]
        eras.insert(0, dict(tally(ms), frm=None, to=cuts[0], label='From launch', days=len([d for d in dates if d <= cuts[0]])))

    tuned = load(os.path.join(HERE, 'tuned.json')) or {}
    settings = [{'key': k, 'label': lab, 'sd_mult': ((tuned.get(k) or {}).get('active') or {}).get('sd_mult'),
                 'why': (tuned.get(k) or {}).get('why'), 'chosen_at': (tuned.get(k) or {}).get('chosen_at'),
                 'live_court': ((tuned.get(k) or {}).get('live_court') or {}).get('why')}
                for k, _, lab, kind, _ in MARKETS if kind == 'high' and tuned.get(k)]

    doc = {'built': built, 'today': today, 'overall': overall, 'eras': eras, 'log': sorted(log, key=lambda e: e['date'], reverse=True),
           'settings': settings, 'days': [days[d] for d in sorted(days, reverse=True)]}
    if '--dry' in sys.argv:
        print(json.dumps({'built': built, 'days': len(days), 'overall': overall['all'], 'last7': overall['last7'],
                          'eras': eras, 'newest': doc['days'][0]['lines'] if doc['days'] else None}, indent=1)[:3000])
        return
    with open(OUT, 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('report: %d settled days, %d calls, %d right (market %d of %d); written' % (
        len(days), overall['all'].get('n', 0), overall['all'].get('hits', 0),
        overall['all'].get('mkt_hits', 0), overall['all'].get('mkt_n', 0)))


if __name__ == '__main__':
    main()
