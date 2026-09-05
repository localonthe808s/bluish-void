#!/usr/bin/env python3
"""Would today's model have done better on the days already scored?

THE RECORD IS FROZEN ON PURPOSE.  Each day's decision is written once and never
rewritten, and the scheduled job never runs backfill -- that is what makes the
record a forecast score instead of hindsight. A model that quietly re-marks its
own homework every time it changes will always look excellent.

But frozen also means the record answers a question about a model version that
may no longer exist. After a change, "did that help?" is unanswerable from it.

So: this replays the CURRENT model over the same historical days, in a scratch
file, and diffs it against what is stored. It writes nothing to the record and
is not wired into any schedule. Run it after a change; keep the number it gives
you next to the frozen one, never in place of it.

    python3 _kalshi/rescore.py            # New York
    python3 _kalshi/rescore.py --all      # all seven markets

WHAT IT CANNOT TELL YOU.  The historical days are the days the model was tuned
on -- bias windows, the peak offset, the spread. A backtest over them is
in-sample and flatters itself, and this diff inherits that. It answers "is the
new version better than the old ON THESE DAYS", which is worth knowing and is
not the same as "is it better".
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K                                   # noqa: E402

SCRATCH = os.path.join(HERE, '_rescore')


def replay(cfg):
    """Run the current model over every settled day, into a scratch file."""
    os.makedirs(SCRATCH, exist_ok=True)
    c = copy.deepcopy(cfg)
    c['out'] = os.path.join('_kalshi', '_rescore', os.path.basename(cfg['out']))
    # a clean slate, so backfill recomputes every day rather than filling gaps
    real_load = K.load_log
    K.load_log = lambda out: {'history': []}
    try:
        K.run_market(c)
    finally:
        K.load_log = real_load
    return json.load(open(os.path.join(HERE, '..', c['out'])))


def line(tag, t):
    if not t or not t.get('n'):
        return '  %-9s --' % tag
    return ('  %-9s %3d days  %3d hit  %5.1f%%   mae %s'
            % (tag, t['n'], t['hits'], 100.0 * t['hits'] / t['n'],
               ('%.2f' % t['mae']) if t.get('mae') is not None else ' -  '))


def compare(cfg):
    out = os.path.join(HERE, '..', cfg['out'])
    if not os.path.exists(out):
        print('%s: no stored record' % cfg['key']); return
    frozen = json.load(open(out))
    print('\n=== %s ===' % cfg.get('city', cfg['key']))
    fresh = replay(cfg)

    fh = {h['date']: h for h in frozen.get('history', [])
          if h.get('actual') is not None and 'lock' in h}
    nh = {h['date']: h for h in fresh.get('history', [])
          if h.get('actual') is not None and 'lock' in h}
    both = sorted(set(fh) & set(nh))
    if not both:
        print('  no overlapping scored days'); return

    def tal(src, keys):
        rows = [src[k] for k in keys]
        e = [h['err'] for h in rows if h.get('err') is not None]
        return {'n': len(rows), 'hits': sum(1 for h in rows if h.get('hit')),
                'mae': (sum(abs(x) for x in e) / len(e)) if e else None}

    print('  on the %d days both versions scored:' % len(both))
    print(line('STORED', tal(fh, both)))
    print(line('TODAY', tal(nh, both)))

    flips = [(k, fh[k], nh[k]) for k in both if bool(fh[k].get('hit')) != bool(nh[k].get('hit'))]
    gained = [f for f in flips if f[2].get('hit')]
    lost = [f for f in flips if not f[2].get('hit')]
    print('  %d days changed verdict: %d gained, %d lost' % (len(flips), len(gained), len(lost)))
    for k, o, n in flips[:12]:
        print('    %s  actual %-5s  was %-14s -> now %-14s  %s'
              % (k, o.get('actual'), o['lock'].get('pick'), n['lock'].get('pick'),
                 'GAINED' if n.get('hit') else 'lost'))
    if len(flips) > 12:
        print('    ... and %d more' % (len(flips) - 12))

    # the picks that did not flip a verdict can still have moved
    moved = sum(1 for k in both if fh[k]['lock'].get('pick') != nh[k]['lock'].get('pick'))
    print('  %d of %d picks differ at all' % (moved, len(both)))


def main():
    keys = [c for c in K.MARKETS] if '--all' in sys.argv else \
           [c for c in K.MARKETS if c['key'] == 'ny_high']
    print('REPLAYING TODAY\'S MODEL OVER THE FROZEN RECORD')
    print('nothing here is written back; the record stays as it was decided.')
    for cfg in keys:
        try:
            compare(cfg)
        except Exception as e:
            print('  %s failed: %s: %s' % (cfg['key'], type(e).__name__, e))
    return 0


if __name__ == '__main__':
    if '--backfill' not in sys.argv:
        sys.argv.append('--backfill')          # the whole point of this script
    raise SystemExit(main())
