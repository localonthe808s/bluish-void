#!/usr/bin/env python3
"""
THE LIVE HOUR CURVE (2026-11-01). The sheet's hour bars come from price_study.py, which replays TODAY'S model over
past days against the quotes of each hour -- a replay, which flatters the model at every hour (its noon Brier reads
0.07 where the live record's is 0.52). This grades the real thing: the ladder the live bake actually published at
each hour (the day's trail in kalshi_ny.json, ladders since 2026-10-07) against the quotes price_study saved for
that hour (price_rows.json, committed nightly since 11-01), the bet the sheet's own rules would have named, graded
at settlement. The bake publishes it as today.by_hour_live once it rests on LIVE_HOURS_MIN_DAYS days, and the sheet
draws it in place of the replay.

    python3 _kalshi/live_hours.py          # writes _kalshi/live_hours.json
"""
import collections, datetime, json, math, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K                                   # noqa: E402
OUT = os.path.join(HERE, 'live_hours.json')


def floor_ok(price, ev):
    return ev >= (K.EDGE_FLOOR_PRICED if price >= K.EDGE_PRICE else K.EDGE_FLOOR)


def se_by_boot(rets, n_boot=400):
    if len(rets) < 3:
        return None
    random.seed(7)
    means = []
    for _ in range(n_boot):
        s = [random.choice(rets) for _ in rets]
        means.append(sum(s) / len(s))
    m = sum(means) / len(means)
    return round((sum((v - m) ** 2 for v in means) / len(means)) ** 0.5, 3)


def study(cfg):
    try:
        rows = json.load(open(os.path.join(HERE, 'price_rows.json')))
    except Exception:
        return None
    quotes = {(r['date'], r['hour']): r for r in rows if r.get('city') == cfg['key']}
    try:
        doc = json.load(open(os.path.join(HERE, '..', cfg['out'])))
    except Exception:
        return None
    bets = collections.defaultdict(list)
    dates = set()
    for h in doc.get('history') or []:
        d = h.get('date')
        L = h.get('lock') or {}
        lad = L.get('ladder') or []
        if h.get('backtest') or h.get('actual') is None or not lad or not h.get('trail'):
            continue
        k = [i for i, r in enumerate(lad) if (r.get('lo') is None or h['actual'] >= r['lo'])
             and (r.get('hi') is None or h['actual'] <= r['hi'])]
        if len(k) != 1:
            continue
        ai = k[0]
        for t in h['trail']:
            hh, o = t.get('h'), t.get('ours')
            q = quotes.get((d, hh))
            if hh is None or not o or not q or len(q.get('q') or []) != len(o):
                continue
            dates.add(d)
            best = None
            for i, (bid, ask) in enumerate(q['q']):
                if ask is not None and 0 < ask < 1:
                    ev = o[i] - ask - K.fee_of(ask)
                    if best is None or ev > best[0]:
                        best = (ev, 'yes', ask, i)
                if bid is not None and 0 < bid < 1:
                    nask = round(1 - bid, 2)
                    ev = (1 - o[i]) - nask - K.fee_of(nask)
                    if best is None or ev > best[0]:
                        best = (ev, 'no', nask, i)
            if not best or not floor_ok(best[2], best[0]):
                continue
            ev, side, price, i = best
            won = (i == ai) if side == 'yes' else (i != ai)
            cost = price + K.fee_of(price)
            bets[hh].append({'date': d, 'ret': ((1 - cost) / cost) if won else -1.0, 'won': won, 'price': price, 'pool': q.get('pool')})
    if not dates:
        return None
    by_hour = []
    for hh in range(0, 24):
        b = bets.get(hh) or []
        if not b:
            continue
        rets = [x['ret'] for x in b]
        by_hour.append({'h': hh, 'bets': len(b), 'won': sum(1 for x in b if x['won']), 'ret': round(sum(rets) / len(rets), 3),
                        'se': se_by_boot(rets), 'winrate': round(sum(1 for x in b if x['won']) / float(len(b)), 3),
                        'pool': round(sum((x['pool'] or 0) for x in b) / len(b), 1)})
    return {'days': len(dates), 'from': min(dates), 'to': max(dates), 'by_hour': by_hour}


def main():
    doc = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'min_days': K.LIVE_HOURS_MIN_DAYS, 'cities': {}}
    for cfg in K.MARKETS:
        if not cfg['key'].endswith('_high'):
            continue
        r = study(cfg)
        if r:
            doc['cities'][cfg['key']] = r
            print('%s: %d live days with quotes (%s..%s); %s' % (cfg['key'], r['days'], r['from'], r['to'],
                  ', '.join('%dh %+.2f/%d' % (e['h'], e['ret'], e['bets']) for e in r['by_hour'] if 7 <= e['h'] <= 14)))
        else:
            print('%s: no overlap yet' % cfg['key'])
    with open(OUT, 'w') as fh:
        json.dump(doc, fh, indent=0, sort_keys=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
