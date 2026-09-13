#!/usr/bin/env python3
"""
DAILY LOWS (built 2026-09-13). New York, Las Vegas and Austin: KXLOWTNYC,
KXLOWTLV, KXLOWTAUS -- the same three stations the highs settle on, and the
same climate report (its MINIMUM line). Verified before a line of model was
written: Kalshi's expiration_value equals the IEM daily minimum on 67 of 67
settled days in every one of the three (2026-07-07..09-11).

ONE TRICK, NOT A SECOND MODEL. Every temperature is NEGATED on the way in and
un-negated on the way out. A daily low is then a daily high of -T: the running
minimum can only fall, which is exactly the "floor can only rise" logic the
highs bake has trusted for months -- its consensus, per-model bias, regime
spread, floor offset and bracket arithmetic run unchanged on the negated
numbers. What does NOT carry over is set here explicitly: the warm-up damping
is off (damping a forecast cool-down is not a measured claim), the floor
offset is measured on this station's own hourly-minimum gap, and none of the
high-shaped extras (six-hour group, TWC max7, 5-minute sensors, the afternoon
table) are used. They can be added once this record has spoken.

TWO LOCKS A DAY, because the low's information arrives at the other end of the
clock. The EVE lock is written the evening before (20:00 local, tomorrow's
ladder, no floor): that is where a low bet is actually placed. The MORNING
lock (08:00 local, the first bake the cron can reach) is mostly a test of
whether the pre-dawn floor holds through the evening. Both are scored.

    python3 _kalshi/kalshi_lows.py            # the three cities, kalshi_low_*.json
    BV_LOWS_OUT=/path python3 ... --dry       # write there instead, commit nothing
"""
import collections
import csv
import datetime
import io
import json
import math
import os
import statistics
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K                                   # noqa: E402

# damping a forecast COOL-DOWN was never measured; the highs' warm-up damping is
# a different physical claim, so it is off here
K.SWING_DAMP = 0.0
LOCK_HOUR = 8            # local; the first bake the cron reaches after dawn in every city
EVE_HOUR = 20            # local, the evening before, on tomorrow's ladder
EDGE_MIN, EDGE_PRICED, EDGE_PRICE = 0.20, 0.10, 0.30   # the highs' measured floor, mirrored
MIN_PRICE, MAX_DISAGREE = 0.10, 0.50
SPAN = K.RESID_M + K.BIAS_K + 6
BACKFILL_DAYS = 70


def low_cfg(base_key, series, out, label, slug):
    b = next(m for m in K.MARKETS if m['key'] == base_key)
    c = dict(b)
    c.update({'key': base_key.replace('_high', '_low'), 'series': series, 'out': out,
              'label': label, 'field': 'min_temp_f', 'kind': 'low', 'skill': False,
              'bias_hl': 7, 'sd_mult': 1.0,
              'url': 'https://kalshi.com/markets/%s/%s' % (series.lower(), slug)})
    return c


MARKETS = [
    low_cfg('ny_high',  'KXLOWTNYC', 'kalshi_low_ny.json',  'New York daily low',  'lowest-temperature-in-nyc'),
    low_cfg('las_high', 'KXLOWTLV',  'kalshi_low_las.json', 'Las Vegas daily low', 'las-vegas-daily-low-temperature'),
    low_cfg('aus_high', 'KXLOWTAUS', 'kalshi_low_aus.json', 'Austin daily low',    'lowest-temperature-in-austin'),
]


# ------------------------------------------------------------ the lens ----
def neg_fcm(fcm):
    return {m: {d: {h: -v for h, v in hrs.items()} for d, hrs in days.items()} for m, days in fcm.items()}


def neg_rows(rows):
    """Ladder rows with negated bounds, re-sorted, each remembering its source row."""
    out = []
    for i, r in enumerate(rows):
        lo = -r['hi'] if r.get('hi') is not None else None
        hi = -r['lo'] if r.get('lo') is not None else None
        out.append(dict(r, lo=lo, hi=hi, _src=i))
    out.sort(key=lambda r: (r['lo'] if r['lo'] is not None else -999))
    return out


def obs_hourly_min(cfg, start, end, sink=None):
    """Hourly obs -> {'YYYY-MM-DD': {hour: degF}}, each hour its MINIMUM reading."""
    u = ('https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=%s'
         '&data=tmpf&year1=%d&month1=%d&day1=%d&year2=%d&month2=%d&day2=%d'
         '&tz=%s&format=onlycomma&missing=empty&trace=empty'
         % (cfg['station'], start.year, start.month, start.day,
            end.year, end.month, end.day, urllib.parse.quote(cfg.get('tz', 'America/New_York'))))
    out = collections.defaultdict(dict)
    last = None
    for r in csv.DictReader(io.StringIO(K.get(u, timeout=180).decode())):
        if r.get('tmpf'):
            d, hh = r['valid'][:10], int(r['valid'][11:13])
            out[d][hh] = min(out[d].get(hh, 999.0), float(r['tmpf']))
            last = (r['valid'], float(r['tmpf']))
    if sink is not None and last:
        sink.append(last)
    return out


# ----------------------------------------------------------- the model ----
def gap_table(obh_raw, daily_raw, h0_of, hour, before=None, min_n=40):
    """THE SETTLED LOW AGAINST THE RUNNING MINIMUM AT `hour` (positive space):
    {k: share} for k = settled - running_min, measured on this station's own
    days before `before`. The first New York backfill showed why a normal
    cannot do this job: at 8 AM the pre-dawn minimum is in hand on 84% of
    days and the only question left is whether the report dips a whole degree
    under the hourly stream, which is a coin with measured weights (0 / -1 /
    -2), not a bell curve. A normal centred 0.4 under the reading spread over
    two brackets and said 74% while hitting 61%."""
    cnt = collections.Counter()
    for k, hrs in obh_raw.items():
        if before is not None and k >= before:
            continue
        a = daily_raw.get(k)
        if a is None:
            continue
        h0 = h0_of(k)
        vals = [v for h, v in hrs.items() if h0 <= h <= hour]
        if len(vals) < max(3, hour - h0 - 1):
            continue
        g = int(round(a - min(vals)))
        if -6 <= g <= 1:
            cnt[g] += 1
    n = sum(cnt.values())
    if n < min_n:
        return None
    return {g: c / float(n) for g, c in cnt.items()}, n


def empirical_ps(rows_neg, run_neg, table):
    """Bracket probabilities from the gap table: the settled low is the running
    minimum plus k, with the table's weight on each k."""
    run = -run_neg
    ps = []
    for r in rows_neg:
        lo = -r['hi'] if r['hi'] is not None else None      # back to positive bounds
        hi = -r['lo'] if r['lo'] is not None else None
        ps.append(sum(w for g, w in table.items()
                      if (lo is None or run + g >= lo) and (hi is None or run + g <= hi)))
    s = sum(ps) or 1.0
    return [p / s for p in ps]


def snapshot(fcm, bias_of, daily, obh, h0_of, k, hour, rows_neg, floor_on=True, gaps=None):
    """One decision in negated space: (pred, sd, floor, pf, binding, ps) or None.
    `gaps` = (obh_raw, daily_raw) enables the empirical gap distribution when
    the floor binds."""
    fc = fcm.get(K.MODELS[0]) or list(fcm.values())[0]
    prior = sorted(x for x in fc if x < k and x in daily and len(fc[x]) >= 20)[-K.BIAS_K:]
    if len(prior) < K.BIAS_MIN:
        return None
    biases = bias_of(prior)
    yk = (datetime.date(*map(int, k.split('-'))) - datetime.timedelta(days=1)).isoformat()
    r = K.running_max(obh, k, hour, h0_of(k)) if floor_on else None
    fl = (r + K.HOURLY_PEAK_OFFSET) if r is not None else None
    pf = K.point_forecast(fcm, biases, k, hour, daily.get(yk))
    cand = [x for x in (fl, pf) if x is not None]
    if not cand:
        return None
    pred = max(cand)
    day = fc.get(k) or {}
    over = bool(day) and not [h for h in day if h >= hour]
    bind = fl is not None and ((pf is not None and fl >= pf) or over)
    sd, _ = K.spread(K.residuals(fcm, bias_of, daily, obh, hour, k, h0_of), hour, bind)
    if bind:
        sd = min(sd, K.OFFSET_SD)
    ps = K.distribution(rows_neg, pred, sd, fl)
    emp = None
    if bind and gaps and r is not None:
        t = gap_table(gaps[0], gaps[1], h0_of, hour, before=k)
        if t:
            ps = empirical_ps(rows_neg, r, t[0])
            emp = {'n': t[1], 'table': {str(g): round(w, 3) for g, w in sorted(t[0].items())}}
    return {'pred': pred, 'sd': sd, 'fl': fl, 'run': r, 'pf': pf, 'bind': bind, 'over': over,
            'ps': ps, 'emp': emp, 'biases': {m: biases.get(m) for m in fcm}}


def ladder_out(rows, rows_neg, ps):
    """The original (positive) rows in their own order, each with our probability
    and the market mid attached."""
    ours = [None] * len(rows)
    for r, p in zip(rows_neg, ps):
        ours[r['_src']] = round(p, 4)
    out = []
    for r, p in zip(rows, ours):
        out.append({'label': r.get('label'), 'lo': r.get('lo'), 'hi': r.get('hi'),
                    'ticker': r.get('ticker'), 'bid': r.get('bid'), 'ask': r.get('ask'),
                    'nbid': r.get('nbid'), 'nask': r.get('nask'),
                    'ysize': r.get('ysize'), 'nsize': r.get('nsize'),
                    'market': r.get('mid'), 'ours': p, 'vol': r.get('vol'), 'oi': r.get('oi')})
    return out


def best_line(lad):
    """The plan: one line, by edge after the fee, under the highs' rules."""
    best, book = None, []
    for r in lad:
        if r.get('ours') is None:
            continue
        for dirn, price, q in (('for', r.get('ask'), r['ours']),
                               ('against', (None if r.get('bid') is None else round(1 - r['bid'], 2)), 1 - r['ours'])):
            if price is None or not (MIN_PRICE <= price < 1):
                continue
            if r.get('market') is not None and abs(r['ours'] - r['market']) > MAX_DISAGREE:
                continue
            fee = K.fee_of(price)
            ev = q - price - fee
            if ev < EDGE_MIN and not (ev >= EDGE_PRICED and price >= EDGE_PRICE):
                continue
            line = {'dir': dirn, 'label': r['label'], 'price': price, 'q': round(q, 4),
                    'ev': round(ev, 4), 'fee': round(fee, 4), 'ticker': r.get('ticker')}
            book.append(line)
            if best is None or ev > best['ev']:
                best = line
    return best, book


def grade(bet, truth_label):
    if not bet:
        return None
    won = (bet['label'] == truth_label) if bet['dir'] == 'for' else (bet['label'] != truth_label)
    return {'won': bool(won)}


# ---------------------------------------------------------- the record ----
def tally(rows):
    e = [h['err'] for h in rows if h.get('err') is not None]
    ps = [h['lock']['p'] for h in rows if (h.get('lock') or {}).get('p') is not None]
    mk = [h for h in rows if (h.get('lock') or {}).get('market_p') is not None]
    return {'n': len(rows), 'hits': sum(1 for h in rows if h.get('hit')),
            'mae': round(statistics.mean(abs(x) for x in e), 2) if e else None,
            'bias': round(statistics.mean(e), 2) if e else None,
            'said': round(statistics.mean(ps), 3) if ps else None,
            'market_n': len(mk), 'market_hits': sum(1 for h in mk if h.get('market_hit')),
            'market_said': round(statistics.mean(h['lock']['market_p'] for h in mk), 3) if mk else None}


def calibration(rows):
    cells = []
    for h in rows:
        ab = h.get('actual_bracket')
        for r in ((h.get('lock') or {}).get('ladder') or []):
            if r.get('ours') is None or ab is None:
                continue
            cells.append((r['ours'], 1.0 if r['label'] == ab else 0.0))
    if not cells:
        return None
    bins = []
    for i in range(10):
        lo = i / 10.0
        xs = [c for c in cells if lo <= c[0] < lo + 0.1 or (i == 9 and c[0] >= 0.9)]
        if xs:
            bins.append({'lo': lo, 'n': len(xs), 'said': round(statistics.mean(x[0] for x in xs), 3),
                         'happened': round(statistics.mean(x[1] for x in xs), 3)})
    n = sum(b['n'] for b in bins)
    gap = sum(abs(b['said'] - b['happened']) * b['n'] for b in bins) / n if n else None
    brier = statistics.mean((p - o) ** 2 for p, o in cells)
    ll = statistics.mean(-math.log(max(1e-6, p if o else 1 - p)) for p, o in cells)
    return {'bins': bins, 'gap': round(gap, 3) if gap is not None else None,
            'brier': round(brier, 4), 'logloss': round(ll, 3), 'cells': len(cells)}


# ------------------------------------------------------------ one market ----
def run_market(cfg, dry_dir=None):
    now = K.local_now(cfg)
    today = now.date()
    tkey = today.isoformat()
    out_path = os.path.join(HERE, '..', cfg['out'])
    prev = K.load_log(out_path) if os.path.exists(out_path) else {'history': []}
    hist = {h['date']: h for h in (prev.get('history') or []) if h.get('date')}

    # ---- inputs, negated
    fcm_raw = {m: v for m, v in K.forecast_runs(cfg, SPAN + 40, K.models_for(cfg)).items() if v}
    if not fcm_raw:
        raise RuntimeError('no forecast')
    fcm = neg_fcm(fcm_raw)
    daily_raw = K.daily_series(cfg, today - datetime.timedelta(days=SPAN + 60), today)
    daily = {d: -v for d, v in daily_raw.items()}
    sink = []
    obh_raw = obs_hourly_min(cfg, today - datetime.timedelta(days=SPAN + 60), today + datetime.timedelta(days=1), sink)
    live = K.metar_today(cfg, today) or {}
    for h, v in live.items():
        obh_raw.setdefault(tkey, {})
        obh_raw[tkey][h] = min(obh_raw[tkey].get(h, 999.0), v)
    obh = {d: {h: -v for h, v in hrs.items()} for d, hrs in obh_raw.items()}
    h0_of = lambda k: K.climate_day_start(cfg, datetime.date(*map(int, k.split('-'))))   # noqa: E731
    bias_of = K.biases_factory(fcm, daily, cfg.get('skill', False), cfg.get('bias_hl'))

    # the floor offset for THIS station's minima, measured; the highs' 0.70 is a fallback
    off = K.measure_offset(cfg, obh, daily, h0_of)
    if off and off[2] >= 40:
        K.HOURLY_PEAK_OFFSET, K.OFFSET_SD = round(off[0], 3), round(max(off[1], 0.3), 3)
    else:
        K.HOURLY_PEAK_OFFSET, K.OFFSET_SD = K.OFFSET_DEFAULT, K.OFFSET_SD_DEFAULT
    offset = {'mean': K.HOURLY_PEAK_OFFSET, 'sd': K.OFFSET_SD, 'n': (off[2] if off else 0)}

    # ---- settled days: the truth, and the ladder each traded
    settled = K.fetch_settled(cfg)
    by_date = {}
    for evt, rows in settled.items():
        try:
            d = datetime.datetime.strptime(evt.split('-')[1], '%y%b%d').date().isoformat()
        except Exception:
            continue
        val = next((r['value'] for r in rows if r.get('value') is not None), None)
        if val is None:
            continue
        by_date[d] = {'event': evt, 'rows': rows, 'value': val}

    # ---- backfill: a decision for every settled day that has none, from the archive
    for d in sorted(by_date):
        if d in hist or d >= tkey:
            continue
        if d < (today - datetime.timedelta(days=BACKFILL_DAYS)).isoformat():
            continue
        rows = by_date[d]['rows']
        rows_neg = neg_rows(rows)
        s = snapshot(fcm, bias_of, daily, obh, h0_of, d, LOCK_HOUR, rows_neg, gaps=(obh_raw, daily_raw))
        if not s:
            continue
        lad = ladder_out(rows, rows_neg, s['ps'])
        best = max(range(len(lad)), key=lambda i: lad[i]['ours'] or 0)
        hist[d] = {'date': d, 'event': by_date[d]['event'], 'backtest': True,
                   'lock': {'at': '%sT%02d:00 %s' % (d, LOCK_HOUR, cfg['tzlabel']), 'pick': lad[best]['label'],
                            'p': lad[best]['ours'], 'pred': round(-s['pred'], 2), 'sd': round(s['sd'], 3),
                            'obs_at_lock': (round(-s['run'], 2) if s['run'] is not None else None),
                            'binding': s['bind'], 'emp': bool(s.get('emp')), 'ladder': lad,
                            'market_pick': None, 'market_p': None}}
        # the evening-before view of the same day, no floor
        se = snapshot(fcm, bias_of, daily, obh, h0_of, d, 0, rows_neg, floor_on=False)
        if se:
            lad_e = ladder_out(rows, rows_neg, se['ps'])
            be = max(range(len(lad_e)), key=lambda i: lad_e[i]['ours'] or 0)
            hist[d]['eve'] = {'pick': lad_e[be]['label'], 'p': lad_e[be]['ours'], 'pred': round(-se['pred'], 2),
                              'sd': round(se['sd'], 3)}

    # ---- score everything settled
    for d, h in hist.items():
        if d not in by_date or 'lock' not in h:
            continue
        val = by_date[d]['value']
        rows_neg = neg_rows(by_date[d]['rows'])
        i = K.which(rows_neg, -val)
        ab = rows_neg[i]['label'] if i is not None else None
        if ab is None:
            continue
        h['actual'] = val
        h['actual_bracket'] = ab
        h['truth_source'] = 'settlement'
        h['hit'] = (h['lock'].get('pick') == ab)
        h['market_hit'] = (h['lock'].get('market_pick') == ab) if h['lock'].get('market_pick') else None
        h['err'] = round(h['lock']['pred'] - val, 2) if h['lock'].get('pred') is not None else None
        g = grade(h['lock'].get('bet'), ab)
        if g:
            h['bet_result'] = g
        if h.get('eve'):
            h['eve_hit'] = (h['eve'].get('pick') == ab)
            ge = grade(h['eve'].get('bet'), ab)
            if ge:
                h['eve_result'] = ge

    # ---- today
    rows = []
    try:
        rows = K.fetch_market(cfg, K.event_ticker(cfg, today))
    except Exception as e:
        print('%s market unavailable (%s)' % (cfg['key'], e))
    rows_neg = neg_rows(rows) if rows else []
    s = snapshot(fcm, bias_of, daily, obh, h0_of, tkey, now.hour, rows_neg, gaps=(obh_raw, daily_raw)) if rows else None
    T = {'date': tkey, 'event': K.event_ticker(cfg, today), 'kind': 'low', 'key': cfg['key'],
         'label': cfg['label'], 'city': cfg.get('city'), 'station': cfg['station'],
         'as_of': now.strftime('%H:%M ') + cfg['tzlabel'], 'tz': cfg['tz'],
         'state': K.market_state(cfg, rows, now) if rows else {'status': 'not_open'},
         'offset': offset, 'lock_hour': LOCK_HOUR, 'eve_hour': EVE_HOUR,
         'obs_hours': [[h, round(v, 2)] for h, v in sorted((obh_raw.get(tkey) or {}).items())],
         'now_temp': (round(sink[-1][1], 2) if sink else None), 'now_at': (sink[-1][0][11:16] if sink else None)}
    run_today = K.running_max(obh, tkey, now.hour, h0_of(tkey))
    T['obs_so_far'] = round(-run_today, 2) if run_today is not None else None
    if s:
        lad = ladder_out(rows, rows_neg, s['ps'])
        best = max(range(len(lad)), key=lambda i: lad[i]['ours'] or 0)
        mbest = max(range(len(lad)), key=lambda i: lad[i]['market'] or 0)
        T.update({'pred': round(-s['pred'], 2), 'sd': round(s['sd'], 3), 'fc_low': (round(-s['pf'], 2) if s['pf'] is not None else None),
                  'binding': s['bind'], 'gap_table': s.get('emp'),
                  'day_over': bool(s['over']) or now.hour >= 23, 'day_decided': False,
                  'pick': lad[best]['label'], 'p': lad[best]['ours'],
                  'market_pick': lad[mbest]['label'], 'market_p': lad[mbest]['market'],
                  'agree': best == mbest, 'ours': [r['ours'] for r in lad], 'ladder': lad,
                  'models': {m: (round(-(max(fcm[m][tkey].values()) - b), 1) if fcm[m].get(tkey) and b is not None else None)
                             for m, b in s['biases'].items()},
                  'bias': {m: (round(-b, 2) if b is not None else None) for m, b in s['biases'].items()}})
        bet, book = (None, []) if T['day_over'] else best_line(lad)
        T['bet'], T['book'] = bet, book
        # the morning lock, once, at the first bake at or after LOCK_HOUR
        h = hist.setdefault(tkey, {'date': tkey, 'event': T['event']})
        if now.hour >= LOCK_HOUR and 'lock' not in h:
            h['lock'] = {'at': now.strftime('%Y-%m-%dT%H:%M ') + cfg['tzlabel'], 'pick': T['pick'], 'p': T['p'],
                         'pred': T['pred'], 'sd': T['sd'], 'obs_at_lock': T['obs_so_far'], 'binding': s['bind'],
                         'ladder': [{'label': r['label'], 'lo': r['lo'], 'hi': r['hi'], 'ours': r['ours'], 'market': r['market']} for r in lad],
                         'market_pick': T['market_pick'], 'market_p': T['market_p'], 'bet': bet, 'book': book,
                         'priced_at': now.hour}
            print('%s LOCKED %s: %s (%.0f%%), market %s (%.0f%%)' % (cfg['key'], tkey, T['pick'], 100 * (T['p'] or 0),
                                                                    T['market_pick'], 100 * (T['market_p'] or 0)))
        T['locked'] = h.get('lock')
    else:
        T.update({'pred': None, 'sd': None, 'pick': None, 'p': None, 'ladder': [], 'bet': None, 'book': [],
                  'day_over': now.hour >= 23, 'locked': (hist.get(tkey) or {}).get('lock')})

    # ---- tomorrow: the evening plan, on tomorrow's ladder, no floor
    tom = None
    try:
        tdate = today + datetime.timedelta(days=1)
        tkey2 = tdate.isoformat()
        trows = K.fetch_market(cfg, K.event_ticker(cfg, tdate))
        trows_neg = neg_rows(trows) if trows else []
        st = snapshot(fcm, bias_of, daily, obh, h0_of, tkey2, 0, trows_neg, floor_on=False) if trows else None
        if st:
            tl = ladder_out(trows, trows_neg, st['ps'])
            tb = max(range(len(tl)), key=lambda i: tl[i]['ours'] or 0)
            tm = max(range(len(tl)), key=lambda i: tl[i]['market'] or 0)
            tbet, tbook = best_line(tl)
            tom = {'date': tkey2, 'event': K.event_ticker(cfg, tdate), 'state': K.market_state(cfg, trows, now),
                   'pred': round(-st['pred'], 2), 'sd': round(st['sd'], 3), 'pick': tl[tb]['label'], 'p': tl[tb]['ours'],
                   'market_pick': tl[tm]['label'], 'market_p': tl[tm]['market'], 'ladder': tl, 'bet': tbet, 'book': tbook,
                   'models': {m: (round(-(max(fcm[m][tkey2].values()) - b), 1) if fcm[m].get(tkey2) and b is not None else None)
                              for m, b in st['biases'].items()}}
            # the EVE lock for tomorrow, once, from EVE_HOUR on
            h2 = hist.setdefault(tkey2, {'date': tkey2, 'event': tom['event']})
            if now.hour >= EVE_HOUR and 'eve' not in h2:
                h2['eve'] = {'at': now.strftime('%Y-%m-%dT%H:%M ') + cfg['tzlabel'], 'pick': tom['pick'], 'p': tom['p'],
                             'pred': tom['pred'], 'sd': tom['sd'], 'market_pick': tom['market_pick'],
                             'market_p': tom['market_p'], 'bet': tbet, 'book': tbook}
                print('%s EVE %s: %s (%.0f%%), market %s' % (cfg['key'], tkey2, tom['pick'], 100 * (tom['p'] or 0), tom['market_pick']))
        elif trows:
            tom = {'date': tkey2, 'event': K.event_ticker(cfg, tdate), 'state': K.market_state(cfg, trows, now)}
    except Exception as e:
        print('%s tomorrow: %s' % (cfg['key'], e))
    T['tomorrow'] = tom

    # ---- the record
    scored = [h for h in hist.values() if h.get('actual') is not None and 'lock' in h]
    live = [h for h in scored if not h.get('backtest')]
    record = tally(scored)
    record['live'] = tally(live)
    record['backtest'] = tally([h for h in scored if h.get('backtest')])
    record['calibration'] = calibration(scored)
    eves = [h for h in scored if h.get('eve') and h.get('eve_hit') is not None]
    record['eve'] = {'n': len(eves), 'hits': sum(1 for h in eves if h.get('eve_hit')),
                     'wins': sum(1 for h in eves if (h.get('eve_result') or {}).get('won')),
                     'bets': sum(1 for h in eves if h.get('eve_result'))}
    vm = [h for h in scored if h.get('market_hit') is not None]
    record['vs_market'] = {'n': len(vm), 'ours': sum(1 for h in vm if h.get('hit')), 'market': sum(1 for h in vm if h.get('market_hit'))}
    if scored:
        ds = sorted(h['date'] for h in scored)
        c = record['calibration'] or {}
        record['measured'] = {'brier': c.get('brier'), 'logloss': c.get('logloss'),
                              'bracket': '%d/%d' % (record['hits'], record['n']), 'mae': record['mae'],
                              'window': '%s..%s' % (ds[0], ds[-1]), 'lock_hour': LOCK_HOUR,
                              'offset': offset['mean'], 'offset_sd': offset['sd'], 'offset_n': offset['n']}
    bets = [h for h in scored if h.get('bet_result')]
    record['plan'] = {'n': len(bets), 'won': sum(1 for h in bets if h['bet_result'].get('won'))}

    doc = {'key': cfg['key'], 'kind': 'low', 'label': cfg['label'], 'series': cfg['series'], 'url': cfg.get('url'),
           'updated': now.strftime('%Y-%m-%d %H:%M ') + cfg['tzlabel'],
           'updated_utc': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'today': T, 'record': record,
           'history': sorted(hist.values(), key=lambda h: h['date'], reverse=True)}
    if dry_dir:
        p = os.path.join(dry_dir, cfg['out'])
    else:
        p = out_path
    with open(p, 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('%s: %d scored (%d/%d), live %d/%d, offset %.2f (n=%d), today %s %s%% | %s'
          % (cfg['key'], record['n'], record['hits'], record['n'], record['live']['hits'], record['live']['n'],
             offset['mean'], offset['n'], T.get('pick'), round(100 * (T.get('p') or 0)), K.timing_report()))
    return doc


def main():
    dry = '--dry' in sys.argv
    dry_dir = os.environ.get('BV_LOWS_OUT') if dry else None
    if dry and not dry_dir:
        dry_dir = os.path.join(HERE, '_lows_dry')
        os.makedirs(dry_dir, exist_ok=True)
    only = None
    if '--city' in sys.argv:
        only = sys.argv[sys.argv.index('--city') + 1].split(',')
    for cfg in MARKETS:
        if only and not any(cfg['key'].startswith(o) for o in only):
            continue
        try:
            run_market(cfg, dry_dir)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print('%s FAILED: %s: %s' % (cfg['key'], type(e).__name__, e))


if __name__ == '__main__':
    main()
