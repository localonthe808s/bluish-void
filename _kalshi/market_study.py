#!/usr/bin/env python3
"""What the market teaches us, measured against 1,065 hour-rows of real quotes.

price_study.py answers WHEN to bet -- which hour of the day our disagreements
have paid. This answers three questions it does not:

  1. CALIBRATION.  When we say 40%, does it happen 40% of the time? Same for the
     market. A model can beat the market on average and still be systematically
     overconfident in the region where it does most of its betting.

  2. IS A BIG DISAGREEMENT AN EDGE OR A BUG?  The panel's largest edges are the
     ones most likely to be model error: a 50-point gap against a liquid market
     is an extraordinary claim. This bins every rung-hour by how far apart we
     were and asks who ended up closer to the truth.

  3. WHERE the edge lives -- tail rungs ("78 or below") versus interior ones
     ("79 to 80"). An open-ended bracket is a much easier question than a
     two-degree window, and the record should say so rather than hiding it in
     an average.

Read-only. Takes no arguments, writes nothing, touches no network.
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(HERE, 'price_rows.json')


def fee_of(price):
    return min(0.035, math.ceil(0.07 * price * (1 - price) * 100) / 100.0)


def brier(p, hit):
    return (p - (1.0 if hit else 0.0)) ** 2


def bar(frac, width=22):
    n = max(0, min(width, int(round(frac * width))))
    return '#' * n + '.' * (width - n)


def main():
    rows = json.load(open(ROWS))
    print('%d hour-rows\n' % len(rows))

    # ---------------------------------------------------------- calibration --
    # Ten buckets. For each, what we said on average vs how often it happened.
    for who in ('ours', 'mkt'):
        buckets = [[0.0, 0, 0] for _ in range(10)]      # [sum p, n, hits]
        for r in rows:
            for p, t in zip(r[who], r['truth']):
                if p is None:            # a rung with no quote that hour
                    continue
                b = buckets[min(9, int(p * 10))]
                b[0] += p; b[1] += 1; b[2] += 1 if t else 0
        print('CALIBRATION -- %s' % ('BLUISH' if who == 'ours' else 'KALSHI'))
        print('  %-9s %6s %8s %8s  %s' % ('band', 'n', 'said', 'happened', 'gap'))
        for i, (sp, n, hits) in enumerate(buckets):
            if n < 25:
                continue
            said, got = sp / n, hits / n
            print('  %2d-%3d%%   %6d %7.1f%% %7.1f%%  %+5.1f  %s'
                  % (i * 10, i * 10 + 10, n, 100 * said, 100 * got,
                     100 * (got - said), bar(got)))
        print()

    # ------------------------------------- is a big disagreement an edge? ----
    # No prices involved: purely who landed closer to what happened.
    print('WHEN WE DISAGREE, WHO IS RIGHT?')
    print('  %-12s %7s %10s %10s  %s' % ('gap', 'n', 'our brier', 'mkt brier', 'verdict'))
    edges = [(0.02, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.30),
             (0.30, 0.50), (0.50, 1.01)]
    for lo, hi in edges:
        ob = mb = 0.0
        n = 0
        for r in rows:
            for o, m, t in zip(r['ours'], r['mkt'], r['truth']):
                if o is None or m is None:
                    continue
                g = abs(o - m)
                if not (lo <= g < hi):
                    continue
                ob += brier(o, t); mb += brier(m, t); n += 1
        if n < 20:
            continue
        ob /= n; mb /= n
        v = 'WE win by %.0f%%' % (100 * (mb - ob) / mb) if ob < mb else \
            'MARKET wins by %.0f%%' % (100 * (ob - mb) / ob)
        print('  %2.0f-%3.0f pts   %7d %10.4f %10.4f  %s'
              % (100 * lo, 100 * hi, n, ob, mb, v))
    print()

    # ------------------------------------------- what those bets returned ----
    # The realised money version of the same question, on the bet actually
    # chosen each hour, at the price actually quoted.
    print('WHAT THE CHOSEN BET RETURNED, BY THE EDGE IT CLAIMED')
    print('  %-12s %6s %8s %9s  %s' % ('claimed ev', 'bets', 'winrate', 'ret/$1', ''))
    for lo, hi in [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.35), (0.35, 1.01)]:
        sel = [r['best'] for r in rows
               if r.get('best') and lo <= r['best']['ev'] < hi]
        if len(sel) < 15:
            continue
        wins = sum(1 for b in sel if b['wins'])
        ret = sum(b['ret'] for b in sel) / len(sel)
        print('  %2.0f-%3.0f¢      %6d %7.0f%% %+8.2f  %s'
              % (100 * lo, 100 * hi, len(sel), 100 * wins / len(sel), ret,
                 bar(min(1.0, max(0.0, (ret + 1) / 3)))))
    print()

    # --------------------------------------------- tails versus interiors ----
    # Rungs 0 and 5 are open-ended; 1-4 are two-degree windows.
    print('TAIL RUNGS VERSUS INTERIOR ONES')
    print('  %-10s %7s %10s %10s' % ('kind', 'n', 'our brier', 'mkt brier'))
    for kind, idxs in (('tail', (0, 5)), ('interior', (1, 2, 3, 4))):
        ob = mb = 0.0
        n = 0
        for r in rows:
            for i in idxs:
                if i >= len(r['ours']) or r['ours'][i] is None or r['mkt'][i] is None:
                    continue
                ob += brier(r['ours'][i], r['truth'][i])
                mb += brier(r['mkt'][i], r['truth'][i])
                n += 1
        print('  %-10s %7d %10.4f %10.4f' % (kind, n, ob / n, mb / n))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
