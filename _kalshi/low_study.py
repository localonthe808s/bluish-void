#!/usr/bin/env python3
"""NY LOW, MEASURED EVERY NIGHT (2026-11-13, user: "does NY low have the same reports and testing done daily as NY
high?" -> "yes wire them in").

The low bake (kalshi_lows.py) was built on the highs' rules, copied, with a note to measure them "once ~30 live days
exist". Sixty-one live days later nothing had. This is the low's own nightly study, on the low's own model (the
negation lens and the gap table, through kalshi_lows.snapshot), in two parts:

  1. THE PRICE STUDY. Every settled low day Kalshi still lists, replayed hour by hour with only what existed then,
     next to the market's real bid/ask at the same hour (the public candlestick endpoint, as price_study.py reads it).
     Two windows: the EVENING BEFORE (6-11 PM on the next day's ladder, no floor -- where a low is bet; stored as
     hours -6..-1) and the day itself (its climate-day hours, floor and gap table on). From those rows, with
     price_study's own functions: Brier by hour (ours and the market's), the best +EV bet each hour and what it
     returned, and the EDGE FLOOR and DISAGREEMENT CAP measured per window. The bake reads them (best_line) only
     where they are measured, and keeps the typed values otherwise.

  2. THE TUNER. A guarded coordinate search over the low's knobs -- the bias recency (bias_hl), the spread multiplier,
     the bias window (BIAS_K) and the spread floor -- replaying the 8 AM lock and the evening-before view of every
     settled day. tune.py's guardrails, unchanged (45 days, a Brier gain of 0.006 that holds on both halves of the
     record, no more than one hit lost), on the EVENING leg, and the 8 AM leg may not get worse by more than 0.003;
     or the other way round. Otherwise the incumbent stands. The bake applies `tune.active` once n >= 45.

Writes _kalshi/low_study.json. Candles for settled days never change: cached in _kalshi/_study/low_candles.json
(the nightly workflow carries it between runs).

    python3 _kalshi/low_study.py            # both parts
    python3 _kalshi/low_study.py --no-tune  # the price study alone
"""
import collections, datetime, json, math, os, statistics, sys
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K                  # noqa: E402
import kalshi_lows as L                   # noqa: E402
import price_study as PS                  # noqa: E402
import tune as TU                         # noqa: E402
from active import ACTIVE                 # noqa: E402

OUT = os.path.join(HERE, 'low_study.json')
CANDLE_CACHE = os.path.join(HERE, '_study', 'low_candles.json')
DAYS = 120                                # settled days considered
EVE_HOURS = range(18, 24)                 # the evening before, local, on the next day's ladder
EVE_WIN, LOCK_WIN = (-6, -1), (6, 10)     # the two betting windows, in study hours
KNOBS = collections.OrderedDict([
    ('bias_hl',  [None, 4, 7, 14]),
    ('sd_mult',  [0.75, 1.0, 1.25, 1.5]),
    ('bias_k',   [21, 30, 45]),
    ('sd_floor', [0.25, 0.40]),
])
DEFAULTS = {'bias_hl': 7, 'sd_mult': 1.0, 'bias_k': 30, 'sd_floor': 0.25}    # what the bake ran before this study
OTHER_LEG_SLACK = 0.003


def day_of(k):
    return datetime.date(*map(int, k.split('-')))


# ------------------------------------------------------------------ inputs ----
def inputs(cfg):
    """Everything kalshi_lows.run_market builds, once: forecasts, daily minima, hourly minima, all negated."""
    today = K.local_now(cfg).date()
    span = K.RESID_M + max(KNOBS['bias_k']) + 6
    fcm_raw = {m: v for m, v in K.forecast_runs(cfg, span + 40, K.models_for(cfg)).items() if v}
    if not fcm_raw:
        raise RuntimeError('no forecast')
    h0_of = lambda k: K.climate_day_start(cfg, day_of(k))           # noqa: E731
    for m in fcm_raw:
        L.fold_midnight(fcm_raw[m], h0_of)
    daily_raw = K.daily_series(cfg, today - datetime.timedelta(days=span + 60), today)
    obh_raw = L.obs_hourly_min(cfg, today - datetime.timedelta(days=span + 60), today + datetime.timedelta(days=1))
    L.fold_midnight(obh_raw, h0_of)
    I = {'cfg': cfg, 'today': today, 'h0_of': h0_of, 'fcm': L.neg_fcm(fcm_raw),
         'daily_raw': daily_raw, 'daily': {d: -v for d, v in daily_raw.items()},
         'obh_raw': obh_raw, 'obh': {d: {h: -v for h, v in hrs.items()} for d, hrs in obh_raw.items()}}
    off = K.measure_offset(cfg, I['obh'], I['daily'], h0_of)
    if off and off[2] >= 40:
        K.HOURLY_PEAK_OFFSET, K.OFFSET_SD = round(off[0], 3), round(max(off[1], 0.3), 3)
    else:
        K.HOURLY_PEAK_OFFSET, K.OFFSET_SD = K.OFFSET_DEFAULT, K.OFFSET_SD_DEFAULT
    return I


def settled_days(cfg, today):
    """{date: {'lad': positive ladder sorted by lo, with ticker and won, 'value': settled low}}"""
    out = {}
    since = (today - datetime.timedelta(days=DAYS)).isoformat()
    for d, ms in PS.settled_events(cfg).items():
        if d < since or d >= today.isoformat():
            continue
        lad = []
        for m in ms:
            lo, hi = PS.bounds(m)
            lad.append({'label': m.get('yes_sub_title') or m['ticker'].split('-')[-1], 'lo': lo, 'hi': hi,
                        'ticker': m['ticker'], 'won': m.get('result') == 'yes'})
        if not any(r['won'] for r in lad):
            continue
        lad.sort(key=lambda r: (r['lo'] if r['lo'] is not None else -999))
        val = next((m.get('expiration_value') for m in ms if m.get('expiration_value') not in (None, '')), None)
        out[d] = {'lad': lad, 'value': float(val) if val is not None else None}
    return out


# --------------------------------------------------------------- settings ----
class settings(object):
    """The knobs on the model's module globals for a block, restored after."""
    def __init__(self, st):
        self.st = st

    def __enter__(self):
        self.saved = (K.BIAS_K, K.SD_MULT, K.SD_FLOOR)
        K.BIAS_K, K.SD_MULT, K.SD_FLOOR = int(self.st['bias_k']), float(self.st['sd_mult']), float(self.st['sd_floor'])
        return self

    def __exit__(self, *a):
        K.BIAS_K, K.SD_MULT, K.SD_FLOOR = self.saved


def bias_of_for(I, st):
    return K.biases_factory(I['fcm'], I['daily'], False, st['bias_hl'])


def ours_positive(lad, rows_neg, ps):
    out = [None] * len(lad)
    for r, p in zip(rows_neg, ps):
        out[r['_src']] = p
    return out


def lock_snap(I, bias_of, d, rows_neg, hour):
    return L.snapshot(I['fcm'], bias_of, I['daily'], I['obh'], I['h0_of'], d, hour, rows_neg,
                      gaps=(I['obh_raw'], I['daily_raw']))


def eve_snap(I, bias_of, d, rows_neg):
    return L.snapshot(I['fcm'], bias_of, I['daily'], I['obh'], I['h0_of'], d, 0, rows_neg, floor_on=False)


# --------------------------------------------------------- 1. price study ----
def load_cache():
    try:
        return json.load(open(CANDLE_CACHE))
    except Exception:
        return {}


def candles_cached(cache, cfg, ticker, day, newest_settled):
    """price_study.candles, keyed by ticker and local day; the hours of a settled day are kept for good."""
    k = '%s|%s' % (ticker, day.isoformat())
    if k in cache:
        return {int(h): tuple(v) for h, v in cache[k].items()}
    tz = ZoneInfo(cfg['tz'])
    tzoff = -int(datetime.datetime(day.year, day.month, day.day, 12, tzinfo=tz).utcoffset().total_seconds() // 3600)
    got = PS.candles(cfg, ticker, day, tzoff)
    if got and day.isoformat() <= newest_settled:
        cache[k] = {str(h): list(v) for h, v in got.items()}
    return got


def best_bet(lad, ps, quote):
    """price_study's best +EV line at the quoted prices, either side of any rung, and what it returned."""
    best = None
    for i, (r, p, q) in enumerate(zip(lad, ps, quote)):
        if not q:
            continue
        bid, ask = q[0], q[1]
        for side, price, prob_, wins in (('yes', ask, p, r['won']),
                                         ('no', None if bid is None else round(1 - bid, 2), 1 - p, not r['won'])):
            if price is None or not (0 < price < 1):
                continue
            e = prob_ - price - K.fee_of(price)
            if best is None or e > best['ev']:
                cost = price + K.fee_of(price)
                best = {'ev': e, 'price': price, 'side': side, 'wins': wins,
                        'ret': ((1 - cost) / cost) if wins else -1.0, 'i': i}
    return best


def row_of(cfg, d, hour, lad, ps, quote):
    if sum(1 for q in quote if q and q[1] is not None) < 3:
        return None
    mids = [((q[0] + q[1]) / 2) if q and q[0] is not None and q[1] is not None else None for q in quote]
    tot = sum(x for x in mids if x is not None) or 1.0
    return {'city': cfg['key'], 'date': d, 'hour': hour,
            'pool': round(sum((q[2] if q and len(q) > 2 and q[2] else 0) for q in quote), 1),
            'ours': [round(x, 4) for x in ps], 'mkt': [None if x is None else round(x / tot, 4) for x in mids],
            'truth': [bool(r['won']) for r in lad], 'best': best_bet(lad, ps, quote),
            'q': [[None, None] if not q else [q[0], q[1]] for q in quote]}


def price_rows(I, days, st):
    cfg = I['cfg']
    cache = load_cache()
    newest = (I['today'] - datetime.timedelta(days=2)).isoformat()
    rows = []
    with settings(st):
        bias_of = bias_of_for(I, st)
        for n, d in enumerate(sorted(days)):
            lad = days[d]['lad']
            rows_neg = L.neg_rows(lad)
            dd = day_of(d)
            px = {r['ticker']: candles_cached(cache, cfg, r['ticker'], dd, newest) for r in lad}
            pxe = {r['ticker']: candles_cached(cache, cfg, r['ticker'], dd - datetime.timedelta(days=1), newest) for r in lad}
            se = eve_snap(I, bias_of, d, rows_neg)
            if se:
                ps = ours_positive(lad, rows_neg, se['ps'])
                for h in EVE_HOURS:
                    r = row_of(cfg, d, h - 24, lad, ps, [pxe[x['ticker']].get(h) for x in lad])
                    if r:
                        rows.append(r)
            h0 = I['h0_of'](d)
            for h in range(h0, 24):
                s = lock_snap(I, bias_of, d, rows_neg, h)
                if not s:
                    continue
                r = row_of(cfg, d, h, lad, ours_positive(lad, rows_neg, s['ps']), [px[x['ticker']].get(h) for x in lad])
                if r:
                    rows.append(r)
            if (n + 1) % 20 == 0:
                print('  %d/%d days, %d hour-rows' % (n + 1, len(days), len(rows)), flush=True)
    try:
        os.makedirs(os.path.dirname(CANDLE_CACHE), exist_ok=True)
        json.dump(cache, open(CANDLE_CACHE, 'w'), separators=(',', ':'))
    except Exception as e:
        print('candle cache not saved (%s)' % e)
    return rows


def price_report(rows):
    def win(a, b):
        return {'floor': PS.edge_floor(rows, hours=(a, b)), 'cap': PS.disagree_cap(rows, hours=(a, b)),
                'calib': PS.calibration_bands(rows, hours=(a, b)),
                'bets': summary_bets([r for r in rows if a <= r['hour'] <= b])}
    return {'hour_rows': len(rows), 'days': len(set(r['date'] for r in rows)),
            'by_hour': PS.summarise(rows), 'eve': win(*EVE_WIN), 'lock': win(*LOCK_WIN)}


def summary_bets(rows):
    """The window's best lines, all of them and those that clear the bake's typed floor, with what they returned."""
    allb = [r['best'] for r in rows if r.get('best') and r['best']['ev'] > 0.005]
    typed = [b for b in allb if (b['ev'] >= L.EDGE_MIN or (b['ev'] >= L.EDGE_PRICED and b['price'] >= L.EDGE_PRICE))
             and b['price'] >= L.MIN_PRICE]

    def s(v):
        return {'n': len(v), 'won': sum(1 for b in v if b['wins']),
                'ret': round(statistics.mean(b['ret'] for b in v), 3) if v else None}
    return {'any_edge': s(allb), 'typed_floor': s(typed)}


# --------------------------------------------------------------- 2. tuner ----
def replay(I, days, st):
    """{leg: {date: hist-shaped row}} for the 8 AM lock and the evening before, under settings `st`."""
    out = {'lock': {}, 'eve': {}}
    with settings(st):
        bias_of = bias_of_for(I, st)
        for d in sorted(days):
            lad = days[d]['lad']
            rows_neg = L.neg_rows(lad)
            ab = next(r['label'] for r in lad if r['won'])
            for leg, s in (('lock', lock_snap(I, bias_of, d, rows_neg, L.LOCK_HOUR)), ('eve', eve_snap(I, bias_of, d, rows_neg))):
                if not s:
                    continue
                ps = ours_positive(lad, rows_neg, s['ps'])
                pick = lad[max(range(len(lad)), key=lambda i: ps[i] or 0)]['label']
                out[leg][d] = {'lock': {'ladder': [{'label': r['label'], 'ours': p} for r, p in zip(lad, ps)]},
                               'actual_bracket': ab, 'hit': pick == ab}
    return out


def leg_score(h):
    s = TU.score(h, sorted(h))
    return {'n': s['n'], 'hits': s['hits'], 'brier': round(s['brier'], 4) if s['brier'] is not None else None}


def accepts(cand, base):
    """A candidate wins on one leg under tune.py's guardrails and does not lose the other by more than the slack."""
    for main_leg, other in (('eve', 'lock'), ('lock', 'eve')):
        ok, gain, info = TU.beats(cand[main_leg], base[main_leg])
        if not ok:
            continue
        days = sorted(set(cand[other]) & set(base[other]))
        c, b = TU.score(cand[other], days)['brier'], TU.score(base[other], days)['brier']
        if c is not None and b is not None and c > b + OTHER_LEG_SLACK:
            continue
        return True, gain, '%s leg: %s; %s leg %+.4f' % (main_leg, info['why'], other, (b - c) if c is not None and b is not None else 0)
    return False, None, None


def tune_low(I, days, prev):
    cur = dict(DEFAULTS)
    cur.update({k: v for k, v in ((prev or {}).get('active') or {}).items() if k in KNOBS})
    memo = {}

    def scored(st):
        k = json.dumps(st, sort_keys=True)
        if k not in memo:
            memo[k] = replay(I, days, st)
        return memo[k]

    base = scored(cur)
    if len(base['eve']) < TU.MIN_DAYS:
        return {'active': (prev or {}).get('active'), 'why': 'only %d days' % len(base['eve']), 'n': len(base['eve'])}
    changes, tested = [], {}
    for _ in range(TU.PASSES):
        moved = False
        for knob, vals in KNOBS.items():
            best = None
            for v in vals:
                if v == cur[knob]:
                    continue
                st = dict(cur); st[knob] = v
                h = scored(st)
                ok, gain, why = accepts(h, base)
                tested[json.dumps(st, sort_keys=True)] = {'eve': leg_score(h['eve']), 'lock': leg_score(h['lock']), 'won': bool(ok)}
                if ok and (best is None or gain > best[2]):
                    best = (st, h, gain, why)
            if best:
                changes.append('%s %r -> %r (%s)' % (knob, cur[knob], best[0][knob], best[3]))
                cur, base = best[0], best[1]
                moved = True
        if not moved:
            break
    return {'active': cur, 'defaults': DEFAULTS, 'why': '; '.join(changes) if changes else 'current stands',
            'n': len(base['eve']), 'eve': leg_score(base['eve']), 'lock': leg_score(base['lock']),
            'replays': len(memo), 'tested': tested,
            'chosen_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d') if changes else (prev or {}).get('chosen_at')}


# ------------------------------------------------------------------- main ----
def main():
    prev = {}
    try:
        prev = json.load(open(OUT))
    except Exception:
        pass
    doc = {'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'markets': {}}
    for cfg in L.MARKETS:
        base_key = cfg['key'].replace('_low', '_high')
        if base_key not in ACTIVE:
            continue
        key = cfg['key']
        pk = (prev.get('markets') or {}).get(key) or {}
        try:
            I = inputs(cfg)
            days = settled_days(cfg, I['today'])
            print('%s: %d settled days in the window, offset %.2f' % (key, len(days), K.HOURLY_PEAK_OFFSET), flush=True)
            entry = {}
            if '--no-tune' not in sys.argv:
                entry['tune'] = tune_low(I, days, pk.get('tune'))
                t = entry['tune']
                print('  tune: %s | active %s | eve %s lock %s | %s replays' % (t['why'], t['active'], t.get('eve'), t.get('lock'), t.get('replays')), flush=True)
            else:
                entry['tune'] = pk.get('tune')
            st = dict(DEFAULTS)
            if entry.get('tune') and entry['tune'].get('active') and (entry['tune'].get('n') or 0) >= TU.MIN_DAYS:
                st.update(entry['tune']['active'])
            rows = price_rows(I, days, st)
            entry['price'] = price_report(rows)
            entry['price']['settings'] = st
            doc['markets'][key] = entry
            P = entry['price']
            for w in ('eve', 'lock'):
                f, c, b = P[w]['floor'], P[w]['cap'], P[w]['bets']
                print('  %s window: floor cheap %.2f%s priced %.2f%s (n %d) | cap %.1f (n %d) | best lines %s, at the typed floor %s'
                      % (w, f['cheap'], '' if f['cheap_measured'] else ' (typed)', f['priced'], '' if f['priced_measured'] else ' (typed)',
                         f['n'], c['cap'], c['n'], b['any_edge'], b['typed_floor']))
            print('\n hour  days   ours   market    bets   edge   return   win%')
            for e in P['by_hour']:
                print('  %3d  %4d  %.4f  %s   %4d  %s  %s  %s' % (
                    e['h'], e['days'], e['ours_brier'] or 0, ('%.4f' % e['mkt_brier']) if e['mkt_brier'] else '   -  ',
                    e['bets'], ('%+.3f' % e['edge']) if e['edge'] is not None else '  -   ',
                    ('%+.3f' % e['ret']) if e['ret'] is not None else '  -   ',
                    ('%.0f%%' % (100 * e['winrate'])) if e['winrate'] is not None else '-'))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print('%s FAILED (%s); last night\'s study kept' % (key, e))
            if pk:
                doc['markets'][key] = dict(pk, carried=pk.get('carried') or prev.get('built'))
    if doc['markets']:
        with open(OUT, 'w') as fh:
            json.dump(doc, fh, indent=1)
        print('wrote', OUT)


if __name__ == '__main__':
    main()
