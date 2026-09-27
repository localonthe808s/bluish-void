#!/usr/bin/env python3
"""
SELF-TUNING WITH GUARDRAILS (2026-09-07). The per-city settings -- skill-weighted
consensus or the equal mean, the recency window on the bias, the spread
multiplier -- and three constants that were typed by hand (the bias window
length, the warm-up damping, the spread floor) are replayed over the frozen
record with the current model and re-chosen every week. Written to tuned.json
for the bake to apply per city.

COORDINATE SEARCH, not a grid: with six knobs a full grid is hundreds of
replays. Each pass walks the knobs in turn, tries each alternative with the
others held at the incumbent, and keeps the best alternative only if it clears
the guardrails against the incumbent; a second pass catches interactions.
About twenty replays a city, all memoised.

The guardrails are the point, not the search. A candidate wins only when
  * the city has at least 45 scored days in common,
  * its ladder Brier beats the incumbent's by 0.006 or more,
  * it also wins on BOTH halves of the record (the older days and the recent
    days), so a summer fit cannot buy the whole year,
  * and it does not lose more than one bracket hit.
Otherwise the incumbent stands. Every change is logged with its numbers, and
the bake stamps the settings in force on every lock (lock.params), so a
regression is attributable to the week it happened.
"""
import copy, json, os, sys, datetime, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K          # noqa: E402
import rescore as R               # noqa: E402
OUT = os.path.join(HERE, 'tuned.json')
KNOBS = collections.OrderedDict([
    ('skill',      [False, True]),
    ('bias_hl',    [None, 7, 14, 4]),    # 4 added 2026-09-13: Austin ran 1.1 degF cold after a -2.7 correction for eight straight September days; let the guardrails judge a faster window
    ('sd_mult',    [0.75, 1.0, 1.25]),
    ('bias_k',     [21, 30, 45]),        # K.BIAS_K, days in the rolling bias window
    ('swing_damp', [0.0, 0.05, 0.10]),   # K.SWING_DAMP, how much of a warm-up the models overdo
    ('sd_floor',   [0.25, 0.40]),        # K.SD_FLOOR, the least spread the ladder may claim
    ('drop_worst', [0, 2]),              # runs left out of the mean by trailing MAE (New York: 2, measured 2026-09-15)
    ('wind_regime', [False, True]),      # the morning-wind lean (wind_regime.py, 2026-09-25); only where a table exists
])
CFG_KNOBS = ('skill', 'bias_hl', 'sd_mult', 'drop_worst', 'wind_regime')
# THE LISTS GROW ON THEIR OWN (2026-09-07). A knob chosen at the END of its
# list is a knob whose best value may lie beyond it, so the next week's list
# for that city gains one more step in that direction, within a sane bound.
# Kept per city in tuned.json ('lists'); the defaults above are the seed.
STEP = {'bias_hl': (7, 3, 60), 'sd_mult': (0.25, 0.5, 2.0), 'bias_k': (7, 7, 90), 'swing_damp': (0.05, 0.0, 0.30), 'sd_floor': (0.15, 0.10, 1.0)}


def grown_lists(prev_lists, cur):
    lists = {k: list(v) for k, v in KNOBS.items()}
    for k, v in (prev_lists or {}).items():
        if k in lists and isinstance(v, list) and v:
            # the stored list, plus any seed value added since it was written --
            # otherwise a new candidate never reaches a city that already has a list
            lists[k] = v + [x for x in lists[k] if x not in v]
    for k, (step, lo, hi) in STEP.items():
        vals = [x for x in lists[k] if x is not None]
        if not vals or cur.get(k) is None:
            continue
        if cur[k] >= max(vals) and max(vals) + step <= hi + 1e-9:
            lists[k].append(round(max(vals) + step, 2))
        elif cur[k] <= min(vals) and min(vals) - step >= lo - 1e-9:
            lists[k].append(round(min(vals) - step, 2))
    return lists
MIN_DAYS = 45
MIN_GAIN = 0.006
PASSES = 2


def brier(h):
    lad = ((h.get('lock') or {}).get('ladder')) or []
    ab = h.get('actual_bracket')
    if not lad or ab is None:
        return None
    return sum((float(r.get('ours') or 0) - (1.0 if r.get('label') == ab else 0.0)) ** 2 for r in lad)


def score(hist, keys):
    rows = [hist[k] for k in keys if k in hist]
    b = [x for x in (brier(h) for h in rows) if x is not None]
    return {'n': len(rows), 'hits': sum(1 for h in rows if h.get('hit')),
            'brier': (sum(b) / len(b)) if b else None}


def defaults_of(cfg):
    return {'skill': bool(cfg.get('skill', True)), 'bias_hl': cfg.get('bias_hl'), 'sd_mult': float(cfg.get('sd_mult', 1.0)),
            'drop_worst': int(cfg.get('drop_worst') or 0), 'wind_regime': bool(cfg.get('wind_regime')), 'bias_k': K.BIAS_K, 'swing_damp': K.SWING_DAMP, 'sd_floor': K.SD_FLOOR}


def replay_with(cfg, st):
    c = copy.deepcopy(cfg)
    c.update({k: st[k] for k in CFG_KNOBS})
    c['_globals'] = {k: st[k] for k in st if k in K.TUNABLE_GLOBALS}
    if '--backfill' not in sys.argv:
        sys.argv.append('--backfill')
    doc = R.replay(c)
    return {h['date']: h for h in doc.get('history', []) if h.get('actual') is not None and 'lock' in h}


def _wr_keys():
    try:
        return set(k for k in json.load(open(os.path.join(HERE, 'wind_regime.json'))) if k.endswith('_high'))
    except Exception:
        return set()


def key_of(st):
    return json.dumps(st, sort_keys=True)


def beats(cand, base):
    """The guardrails: (passes, gain, table) for a candidate against the incumbent."""
    days = sorted(set(cand) & set(base))
    if len(days) < MIN_DAYS:
        return False, None, {'why': 'only %d days' % len(days)}
    half = len(days) // 2
    old, new = days[:half], days[half:]
    c = {'all': score(cand, days), 'old': score(cand, old), 'new': score(cand, new)}
    b = {'all': score(base, days), 'old': score(base, old), 'new': score(base, new)}
    if c['all']['brier'] is None or b['all']['brier'] is None:
        return False, None, {'why': 'no brier'}
    gain = b['all']['brier'] - c['all']['brier']
    wins_both = c['old']['brier'] < b['old']['brier'] and c['new']['brier'] < b['new']['brier']
    hit_ok = c['all']['hits'] >= b['all']['hits'] - 1
    ok = gain >= MIN_GAIN and wins_both and hit_ok
    why = 'gain %.4f, wins both halves' % gain if ok else 'differs by %.4f (%s%s%s)' % (
        gain, 'small' if gain < MIN_GAIN else '', ' one half only' if not wins_both else '', ' hits' if not hit_ok else '')
    return ok, gain, {'why': why, 'n': len(days), 'cand': c['all'], 'base': b['all']}


# ------------------------------------------------ the live spread court ----
# THE REPLAY DOES NOT GET THE LAST WORD ON THE SPREAD (2026-09-27, user: "do them all").
#
# The replay is kinder than the day was. It scores Las Vegas 55 of 67 where the live noon locks stand
# at 13 of 22, New York 47 of 65 against 13 of 23: its inputs are refetched, its archive has no
# decimals, and it cannot see a late or a missing report. On 2026-09-27 the search narrowed Las
# Vegas from 0.75 to 0.5 on a replay gain of 0.0157 -- and on the 22 live locks that setting scores a
# log-loss near 1.00 against 0.83 for the one it replaced. Every city's live record in fact asks for
# a WIDER ladder than it had (the spread that would have scored best: New York x1.2, Las Vegas
# x1.1, Austin x1.6; Austin's live error ran sd 1.19 against a stated 0.81).
#
# So after the search, the spread multiplier is put to the live locks, which are the only rows that
# were ever priced for real. Each lock carries its forecast, its spread and the multiplier in force
# (lock.params); a normal on those reproduces the bake's own ladder to within 0.001-0.02 a rung, so
# a candidate multiplier is scored by rescaling the spread and reading the settled bracket's log-loss.
#   1. A multiplier the search chose is REFUSED if it scores worse on the live locks than the one
#      those locks were made with.
#   2. Then one step (0.25) either way is taken if it gains LIVE_GAIN of log-loss AND wins both the
#      older and the newer half of the live record.
# Needs LIVE_MIN_N live locks; with fewer the search's choice stands. One step a week at most, so a
# bad month cannot swing the ladder, and everything it did is written into tuned.json (live_court).
LIVE_MIN_N, LIVE_GAIN, LIVE_STEP = 20, 0.02, 0.25


def live_locks(cfg):
    import math
    try:
        doc = json.load(open(os.path.join(HERE, '..', cfg['out'])))
    except Exception:
        return []
    rows = []
    for h in sorted(doc.get('history') or [], key=lambda x: x.get('date') or ''):
        L = h.get('lock') or {}
        lad = L.get('ladder') or []
        if h.get('backtest') or h.get('actual') is None or not lad or not L.get('sd') or L.get('pred') is None:
            continue
        k = [i for i, r in enumerate(lad) if (r.get('lo') is None or h['actual'] >= r['lo'])
             and (r.get('hi') is None or h['actual'] <= r['hi'])]
        if len(k) != 1:
            continue
        rows.append({'date': h['date'], 'pred': float(L['pred']), 'sd': float(L['sd']), 'lad': lad, 'k': k[0],
                     'm': (L.get('params') or {}).get('sd_mult')})
    return rows


def live_ll(rows, mult, made_with):
    """mean log-loss of the settled bracket with every lock's spread rescaled to `mult`"""
    import math
    phi = lambda z: 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    tot = 0.0
    for r in rows:
        sd = max(0.05, r['sd'] * float(mult) / float(r['m'] or made_with))
        ps = []
        for b in r['lad']:
            lo = -1e9 if b.get('lo') is None else b['lo'] - 0.5
            hi = 1e9 if b.get('hi') is None else b['hi'] + 0.5
            ps.append(max(1e-4, phi((hi - r['pred']) / sd) - phi((lo - r['pred']) / sd)))
        tot += -math.log(ps[r['k']] / sum(ps))
    return tot / len(rows)


def live_spread_court(cfg, chosen, cands):
    rows = live_locks(cfg)
    stamped = [r['m'] for r in rows[-14:] if r['m'] is not None]
    made_with = collections.Counter(stamped).most_common(1)[0][0] if stamped else float(cfg.get('sd_mult', 1.0))
    out = {'n': len(rows), 'made_with': made_with, 'asked': chosen, 'ruled': chosen, 'why': 'too few live locks: the search stands'}
    if len(rows) < LIVE_MIN_N:
        return chosen, out
    half = len(rows) // 2
    ll = lambda m, R=rows: live_ll(R, m, made_with)
    grid = sorted(set([round(float(x), 2) for x in cands if x is not None] + [round(float(chosen), 2), round(float(made_with), 2)]))
    out['ll'] = {str(m): round(ll(m), 4) for m in grid}
    ruled, why = float(chosen), []
    if abs(ruled - float(made_with)) > 1e-9 and ll(ruled) > ll(made_with):
        why.append('%s refused: %.3f on the live locks against %.3f for %s, which they were made with'
                   % (ruled, ll(ruled), ll(made_with), made_with))
        ruled = float(made_with)
    near = [m for m in grid if abs(m - ruled) <= LIVE_STEP + 1e-9 and abs(m - ruled) > 1e-9]
    best = min(near, key=ll) if near else None
    if best is not None and ll(ruled) - ll(best) >= LIVE_GAIN \
            and live_ll(rows[:half], best, made_with) < live_ll(rows[:half], ruled, made_with) \
            and live_ll(rows[half:], best, made_with) < live_ll(rows[half:], ruled, made_with):
        why.append('%s -> %s: %.3f against %.3f on %d live locks, and on both halves of them'
                   % (ruled, best, ll(best), ll(ruled), len(rows)))
        ruled = best
    out.update({'ruled': ruled, 'why': '; '.join(why) if why else 'the search\'s %s stands on the live locks' % chosen})
    return ruled, out


def tune(cfg, prev):
    r = _tune(cfg, prev)
    a = r.get('active')
    if a and a.get('sd_mult') is not None:
        ruled, rep_ = live_spread_court(cfg, a['sd_mult'], (r.get('lists') or {}).get('sd_mult') or KNOBS['sd_mult'])
        r['live_court'] = rep_
        if abs(float(ruled) - float(a['sd_mult'])) > 1e-9:
            a['sd_mult'] = ruled
            r['why'] = (r.get('why') or '') + ' | LIVE COURT: ' + rep_['why']
            r['chosen_at'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
        print('  live court: %s' % rep_['why'], flush=True)
    return r


def _tune(cfg, prev):
    key = cfg['key']
    if not os.path.exists(os.path.join(HERE, '..', cfg['out'])):
        return {'active': None, 'why': 'no record'}
    cur = defaults_of(cfg)
    if prev.get(key, {}).get('active'):
        cur.update({k: v for k, v in prev[key]['active'].items() if k in KNOBS})
    memo, tested, changes = {}, {}, []
    lists = grown_lists(prev.get(key, {}).get('lists'), cur)

    def scored(st):
        k = key_of(st)
        if k not in memo:
            try:
                memo[k] = replay_with(cfg, st)
            except Exception as e:
                print('  %s %s failed: %s' % (key, st, e), flush=True)
                memo[k] = None
        return memo[k]

    base = scored(cur)
    if not base:
        return {'active': prev.get(key, {}).get('active'), 'why': 'incumbent replay failed'}
    if len(base) < MIN_DAYS:
        return {'active': prev.get(key, {}).get('active'), 'why': 'only %d days' % len(base), 'n': len(base)}
    for p in range(PASSES):
        moved = False
        for knob, vals in lists.items():
            if knob == 'wind_regime' and key not in _wr_keys():
                continue                 # no fitted table for this city: the replays would be identical
            best = None
            for v in vals:
                if v == cur[knob]:
                    continue
                st = dict(cur); st[knob] = v
                h = scored(st)
                if not h:
                    continue
                ok, gain, info = beats(h, base)
                sc = score(h, sorted(h))
                tested[key_of(st)] = {'brier': round(sc['brier'], 4) if sc['brier'] is not None else None, 'hits': sc['hits'], 'vs': info.get('why')}
                if ok and (best is None or gain > best[2]):
                    best = (st, h, gain, info)
            if best:
                changes.append('%s %r -> %r (%s)' % (knob, cur[knob], best[0][knob], best[3]['why']))
                cur, base = best[0], best[1]
                moved = True
        if not moved:
            break
    sc = score(base, sorted(base))
    tested[key_of(cur)] = {'brier': round(sc['brier'], 4) if sc['brier'] is not None else None, 'hits': sc['hits'], 'vs': 'incumbent'}
    return {'active': cur, 'defaults': defaults_of(cfg), 'lists': grown_lists(lists, cur),
            'why': ('; '.join(changes) if changes else 'current stands'),
            'n': len(base), 'brier': round(sc['brier'], 4) if sc['brier'] is not None else None, 'hits': sc['hits'],
            'replays': len([v for v in memo.values() if v]), 'tested': tested,
            'chosen_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d') if changes else prev.get(key, {}).get('chosen_at')}


def main():
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if '--live-court' in sys.argv:
        # the court alone, on the settings already chosen: no replays (seconds, not the search's half hour)
        for cfg in K.MARKETS:
            r = prev.get(cfg['key']) or {}
            a = r.get('active')
            if not a or a.get('sd_mult') is None:
                continue
            ruled, rep_ = live_spread_court(cfg, a['sd_mult'], (r.get('lists') or {}).get('sd_mult') or KNOBS['sd_mult'])
            r['live_court'] = rep_
            if abs(float(ruled) - float(a['sd_mult'])) > 1e-9:
                a['sd_mult'] = ruled
                r['why'] = (r.get('why') or '') + ' | LIVE COURT: ' + rep_['why']
                r['chosen_at'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
            print('%s live court (%d live locks, made with %s): %s' % (cfg['key'], rep_['n'], rep_['made_with'], rep_['why']))
            print('    log-loss by multiplier: %s' % rep_.get('ll'))
        prev['_built'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
        if '--dry' not in sys.argv:
            json.dump(prev, open(OUT, 'w'), indent=1)
            print('wrote', OUT)
        return
    only = None
    if '--city' in sys.argv:
        only = sys.argv[sys.argv.index('--city') + 1].split(',')
    out = dict(prev)
    for cfg in K.MARKETS:
        if only and not any(cfg['key'].startswith(o) for o in only):
            continue
        print('=== %s' % cfg['key'], flush=True)
        r = tune(cfg, prev)
        out[cfg['key']] = r
        print('  ->', r.get('why'), '| active', r.get('active'), '| %s replays' % r.get('replays'), flush=True)
    out['_built'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
