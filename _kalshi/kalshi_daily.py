#!/usr/bin/env python3
"""Daily NYC-high forecast scored against the Kalshi KXHIGHNY market.

Writes /kalshi_ny.json for the Belvedere Castle popup on the CITY map.

Why a scheduled job rather than a browser fetch: Kalshi answers 403 to any
request carrying an Origin header, and our proxy worker is 403'd too, so the
page cannot reach the market live. It reads our own repo instead.

THE MODEL

    pred = max( observed_high_so_far,  damped( day_ahead_peak - bias ) )

  * bias is the mean (forecast peak - actual) over the previous 21 days,
    using only days that had already been scored.  Open-Meteo runs warm at
    Central Park; removing that is most of the skill.
  * the observed-so-far term is a hard physical floor.  It is one-sided, so it
    deliberately introduces a positive bias (+0.79 degF at noon) -- without it
    the forecast is near-unbiased at -0.15 but MAE is far worse, 2.64 vs 1.98.
    Do NOT "correct" that bias away; the floor is a constraint, not an error,
    and the distribution is truncated at it instead.
  * the spread is measured from the last 45 days of this model's own residuals
    at the current hour, recomputed every run.  A fixed table cannot work: the
    spread is strongly seasonal, SD 3.79 in March against 2.06 in August.
  * REJECTED, do not re-add: an intraday nudge carrying the morning's forecast
    error into the afternoon (MAE 3.07 -> 3.54; the morning error does not
    persist to the peak), and a second-stage mean correction on the residuals
    (worse in 4 of 5 months at full strength).

  * warm-ups are damped -- see point_forecast(), the strongest usable signal.

  Verified by replaying this exact model on the 68 real Kalshi ladders and
  scoring against the settlements themselves (2026-06-28..09-03):
  39/68 brackets, Brier 0.559 against 0.833 for a uniform guess.  Each fix
  compounded: the spread alone took Brier 0.628 -> 0.592 and log loss
  1.309 -> 1.134, putting reliability on the diagonal (stated 38% -> 38%
  actual, 70% -> 71%); damping warm-ups then took MAE 1.83 -> 1.66,
  bias +0.78 -> +0.20 and Brier -> 0.559.

SETTLEMENT: Central Park (CLINYC), reported in WHOLE degrees -- 1096 of 1114
observations are integers.  So "84 to 85" means the reported integer is 84 or
85, i.e. the true temperature lies in [83.5, 85.5).  Bracket edges are offset
by half a degree accordingly; getting this wrong shifts every probability.

Kalshi prices live in the *_dollars fields.  The legacy integer-cent fields
(yes_bid, last_price) are present but always null -- do not read them.
"""

import json, math, os, statistics, sys, urllib.request, urllib.error
import io, csv, collections, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, '..', 'kalshi_ny.json')

CP_LAT, CP_LON = 40.7789, -73.9692        # Belvedere Castle / Central Park
SERIES  = 'KXHIGHNY'
BIAS_K  = 21                              # days in the rolling bias window
BIAS_MIN = 7                              # need this many before trusting it
LOCK_HOUR = 12                            # noon ET: morning obs in hand, peak ahead

SWING_DAMP = 0.25         # see point_forecast(): models overdo warm-ups
RESID_M = 45              # days of recent residuals behind the spread estimate
SD_FLOOR = 0.25
# Fallback only, for the first runs before enough residuals accumulate. These
# came from a 173-day fit; the live model prefers its own rolling estimate
# because the spread is strongly seasonal (SD 3.8 in March, 2.1 in August), so
# any fixed table is wrong for half the year.
SD_FALLBACK = {8:3.06, 9:3.02, 10:2.99, 11:2.83, 12:2.64, 13:2.33, 14:2.11,
               15:1.93, 16:1.83, 17:1.58, 18:1.25, 19:1.03, 20:0.89, 21:0.89, 22:0.89}


def get(url, timeout=90, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'bluishvoid/1.0'})
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:
            last = e
    raise last


def get_json(url, **kw):
    return json.loads(get(url, **kw))


def et_now():
    """America/New_York without a tz database dependency (EDT Mar-Nov)."""
    u = datetime.datetime.utcnow()
    off = 4 if 3 <= u.month <= 11 else 5
    return u - datetime.timedelta(hours=off)


# ---------------------------------------------------------------- market ----
def event_ticker(d):
    return '%s-%s' % (SERIES, d.strftime('%y%b%d').upper())


def fetch_market(ev):
    d = get_json('https://api.elections.kalshi.com/trade-api/v2/markets'
                 '?series_ticker=%s&status=open&limit=60' % SERIES)
    out = []
    for m in d.get('markets', []):
        if m.get('event_ticker') != ev:
            continue
        f, c = m.get('floor_strike'), m.get('cap_strike')
        st = m.get('strike_type')
        # Kalshi states the OPEN bounds as strict: cap_strike 82 on a `less`
        # market is "below 82", i.e. the integer 81 or under; floor_strike 89
        # on `greater` is "above 89", i.e. 90 or over.  Reading those strikes
        # literally shifts both tails a whole degree.
        if st == 'between':
            lo, hi = float(f), float(c)
        elif st in ('less', 'less_or_equal'):
            hi = float(c if c is not None else f)
            lo, hi = None, hi - (1.0 if st == 'less' else 0.0)
        else:                                     # greater / greater_or_equal
            lo = float(f)
            lo, hi = lo + (1.0 if st == 'greater' else 0.0), None
        bid = float(m.get('yes_bid_dollars') or 0)
        ask = float(m.get('yes_ask_dollars') or 0)
        out.append({
            'ticker': m['ticker'], 'label': m.get('yes_sub_title') or '',
            'lo': lo, 'hi': hi, 'bid': bid, 'ask': ask,
            'mid': round((bid + ask) / 2, 4),
            'vol': float(m.get('volume_fp') or 0),
            'close': m.get('close_time'),
        })
    out.sort(key=lambda r: (r['lo'] if r['lo'] is not None else -999))
    return out


# ------------------------------------------------------------- observed ----
# TRUTH SOURCE.  IEM's daily.json max_tmpf, rounded, landed in the bracket
# Kalshi actually settled on **68 of 68** settled markets (2026-06-28..09-03).
# It is also a RUNNING max during the current day, so the same field serves as
# both the settlement truth and today's floor.
#
# Do NOT compute the max from the hourly asos.py stream: the routine METAR
# misses the intra-hour peak and reads 1-2 degF LOW on 22 of 34 days (adding
# report_type=1..4 does not fix it).  An earlier calibration built on that
# stream reported MAE 1.54 / 56% when the truth was really MAE 1.93 / 49%.
HOURLY_PEAK_OFFSET = 1.0     # median(daily.json - max hourly), for historic floors


def daily_max_series():
    """Every Central Park daily max IEM holds -> {'YYYY-MM-DD': degF}.

    One call returns the whole archive (back to 1943), so history, the bias
    window and scoring all come from a single request.
    """
    d = get_json('https://mesonet.agron.iastate.edu/api/1/daily.json'
                 '?station=NYC&network=NY_ASOS', timeout=180)
    return {r['date']: float(r['max_tmpf'])
            for r in (d.get('data') or []) if r.get('max_tmpf') is not None}


def obs_hourly_range(start, end):
    """Hourly obs -> {'YYYY-MM-DD': {hour: degF}}, for historic running maxima."""
    u = ('https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=NYC'
         '&data=tmpf&year1=%d&month1=%d&day1=%d&year2=%d&month2=%d&day2=%d'
         '&tz=America%%2FNew_York&format=onlycomma&missing=empty&trace=empty'
         % (start.year, start.month, start.day, end.year, end.month, end.day))
    out = collections.defaultdict(dict)
    for r in csv.DictReader(io.StringIO(get(u, timeout=180).decode())):
        if r.get('tmpf'):
            d, hh = r['valid'][:10], int(r['valid'][11:13])
            out[d][hh] = max(out[d].get(hh, -99.0), float(r['tmpf']))
    return out


# ------------------------------------------------------------- forecast ----
def forecast_runs(past_days):
    """Day-ahead run, hourly, degF, local time -> {'YYYY-MM-DD': {hour: F}}.

    previous_day1 = the run issued ~24 h earlier.  The calibration used this
    product, so the live model uses it too; swapping in a fresher run would
    invalidate the measured SD.
    """
    u = ('https://previous-runs-api.open-meteo.com/v1/forecast'
         '?latitude=%.4f&longitude=%.4f&hourly=temperature_2m_previous_day1'
         '&past_days=%d&forecast_days=1&temperature_unit=fahrenheit'
         '&timezone=America%%2FNew_York' % (CP_LAT, CP_LON, past_days))
    h = get_json(u, timeout=120)['hourly']
    out = collections.defaultdict(dict)
    for t, v in zip(h['time'], h['temperature_2m_previous_day1']):
        if v is not None:
            out[t[:10]][int(t[11:13])] = v
    return out


def rolling_bias(fc, daily, today_key):
    """mean(forecast peak - actual) over prior scored days. None if too few."""
    keys = sorted(k for k in fc if k < today_key)[-BIAS_K:]
    errs = []
    for k in keys:
        if len(fc[k]) < 20:
            continue
        a = daily.get(k)
        if a is None:
            continue
        errs.append(max(fc[k].values()) - a)
    if len(errs) < BIAS_MIN:
        return None, len(errs)
    return statistics.mean(errs), len(errs)


def point_forecast(day_fc, hour, bias, yday):
    """Bias-corrected peak of the remaining hours, with warm-ups damped.

    The single strongest usable predictor of a bust is how big a day-to-day
    RISE the run is calling for: on days forecast to climb more than 4 degF
    above yesterday the error runs MAE 2.68 / bias +1.43, against 1.26-1.96
    elsewhere (r = +0.22 with |error|, beating cloud, rain and wind at
    0.05-0.18). The model overdoes warm advection, so a quarter of the
    forecast rise is taken back. Damping 0.15-0.40 all help, so this is not a
    knife-edge: at 0.25, MAE 1.83 -> 1.66, bias +0.78 -> +0.20, brackets
    37/68 -> 39/68, Brier 0.591 -> 0.559.
    """
    rest = [v for h, v in day_fc.items() if h >= hour]
    if not rest:
        return None
    p = max(rest) - bias
    if yday is not None:
        p -= SWING_DAMP * max(0.0, p - yday)
    return p


def residuals(fc, daily, obh, hour, today_key):
    """Replay the model on past days at `hour` -> [(date, pred - actual)].

    This is what the spread is measured from, so it is recomputed every run and
    tracks the season on its own.  Historic floors come from the hourly stream
    plus HOURLY_PEAK_OFFSET, since that stream reads low against the daily max
    the model is actually scored on.
    """
    keys = sorted(k for k in fc if k < today_key and k in daily
                  and len(fc[k]) >= 20 and len(obh.get(k, {})) >= 18)
    out = []
    for i, k in enumerate(keys):
        prior = keys[max(0, i - BIAS_K):i]
        if len(prior) < BIAS_MIN:
            continue
        b = statistics.mean(max(fc[p].values()) - daily[p] for p in prior)
        p = point_forecast(fc[k], hour, b, daily.get(keys[i - 1]) if i else None)
        if p is None:
            continue
        run = max([v for h, v in obh[k].items() if h <= hour] or [-99.0])
        floor = run + HOURLY_PEAK_OFFSET if run > -90 else -99.0
        out.append((k, max(floor, p) - daily[k]))
    return out


def spread(res, hour):
    """Standard deviation of the recent residuals; fallback until enough exist."""
    v = [e for _, e in res[-RESID_M:]]
    if len(v) < 20:
        return SD_FALLBACK.get(hour, 3.06 if hour < 8 else 0.89), len(v)
    return max(statistics.stdev(v), SD_FLOOR), len(v)


# ---------------------------------------------------------- probability ----
def _phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def distribution(rows, pred, sd, obs_floor):
    """P(reported integer high lands in each bracket).

    Brackets are integer-valued, so a bracket [lo, hi] covers the real
    interval [lo-0.5, hi+0.5).  Mass below the observed-so-far high is
    impossible; truncate there and renormalise.
    """
    sd = max(sd, 0.15)
    cut = (obs_floor - 0.5) if obs_floor is not None else None
    base = 1.0 - _phi((cut - pred) / sd) if cut is not None else 1.0
    if base < 1e-6:                     # obs already past everything the model knew
        base, cut = 1.0, None
    ps = []
    for r in rows:
        lo = (r['lo'] - 0.5) if r['lo'] is not None else -1e9
        hi = (r['hi'] + 0.5) if r['hi'] is not None else 1e9
        if cut is not None:
            lo, hi = max(lo, cut), max(hi, cut)
        ps.append(max(0.0, (_phi((hi - pred) / sd) - _phi((lo - pred) / sd)) / base))
    s = sum(ps) or 1.0
    return [p / s for p in ps]


# --------------------------------------------------------------- scoring ----
def which(rows, t):
    """Index of the bracket a reported temperature falls in."""
    r = math.floor(t + 0.5)
    for i, b in enumerate(rows):
        if (b['lo'] is None or r >= b['lo']) and (b['hi'] is None or r <= b['hi']):
            return i
    return None


def load_log():
    try:
        with open(OUT) as f:
            return json.load(f)
    except Exception:
        return {'history': []}


def fetch_settled(limit=400):
    """Past events -> their own bracket ladder plus which bracket settled yes.

    The ladder is re-centred by Kalshi every day (Sep 3 ran 83-84/85-86/87-88,
    Sep 4 ran 84-85/86-87/88-89), so a past day must be scored against the
    ladder it actually traded, never today's.
    """
    d = get_json('https://api.elections.kalshi.com/trade-api/v2/markets'
                 '?series_ticker=%s&status=settled&limit=%d' % (SERIES, limit))
    ev = collections.defaultdict(list)
    for m in d.get('markets', []):
        f, c, st = m.get('floor_strike'), m.get('cap_strike'), m.get('strike_type')
        if st == 'between':
            lo, hi = float(f), float(c)
        elif st in ('less', 'less_or_equal'):
            hi = float(c if c is not None else f)
            lo, hi = None, hi - (1.0 if st == 'less' else 0.0)
        else:
            lo = float(f)
            lo, hi = lo + (1.0 if st == 'greater' else 0.0), None
        ev[m['event_ticker']].append({'label': m.get('yes_sub_title') or '',
                                      'lo': lo, 'hi': hi,
                                      'yes': m.get('result') == 'yes'})
    for k in ev:
        ev[k].sort(key=lambda r: (r['lo'] if r['lo'] is not None else -999))
    return ev


def backfill(fc, daily, obh, settled, sd_lock):
    """What we WOULD have locked at noon on each past day, scored.

    Uses only information available at noon that day: the day-ahead run and a
    bias from days already scored.  Flagged backtest=true so it is never shown
    as a live lock.  Contemporaneous market prices are not recoverable (the
    candlestick endpoint 404s), so these days score us only.
    """
    by_date = {}
    for evk, lad in settled.items():
        try:
            d = datetime.datetime.strptime(evk.split('-')[1], '%y%b%d').date()
        except Exception:
            continue
        by_date[d.isoformat()] = lad

    def act(k):
        return daily.get(k)

    keys = sorted(k for k in by_date if k in fc and len(fc[k]) >= 20)
    out = []
    for k in keys:
        a = act(k)
        if a is None:
            continue
        prior = [p for p in sorted(x for x in fc if x < k)[-BIAS_K:] if len(fc[p]) >= 20]
        errs = [max(fc[p].values()) - act(p) for p in prior if act(p) is not None]
        if len(errs) < BIAS_MIN:
            continue
        b = statistics.mean(errs)
        oh = obh.get(k) or {}
        run = max([v for h, v in oh.items() if h <= LOCK_HOUR] or [-99.0])
        obs = run + HOURLY_PEAK_OFFSET if run > -90 else None
        yk = (datetime.date(*map(int, k.split('-'))) - datetime.timedelta(days=1)).isoformat()
        fp = point_forecast(fc[k], LOCK_HOUR, b, daily.get(yk))
        if fp is None:
            continue
        pred = max([x for x in (obs, fp) if x is not None])
        lad = by_date[k]
        ps = distribution(lad, pred, sd_lock, obs)
        bi = max(range(len(lad)), key=lambda i: ps[i])
        ai = which(lad, a)
        truth = next((r['label'] for r in lad if r['yes']), None) \
            or (lad[ai]['label'] if ai is not None else None)
        out.append({
            'date': k, 'event': 'KXHIGHNY', 'backtest': True,
            'actual': a, 'actual_bracket': truth,
            'hit': lad[bi]['label'] == truth,
            'err': round(pred - a, 2),
            'lock': {'at': k + 'T12:00 ET (backtest)', 'pick': lad[bi]['label'],
                     'p': round(ps[bi], 4), 'pred': round(pred, 2),
                     'sd': round(sd_lock, 2), 'bias': round(b, 2),
                     'obs_at_lock': obs, 'market_pick': None, 'market_p': None,
                     'ladder': [{'label': r['label'], 'lo': r['lo'], 'hi': r['hi'],
                                 'ours': round(p, 4), 'market': None}
                                for r, p in zip(lad, ps)]},
        })
    return out


def main():
    dry = '--dry' in sys.argv
    now = et_now()
    today = now.date()
    tkey = today.isoformat()

    rows = fetch_market(event_ticker(today))
    if not rows:
        print('no open market for %s' % event_ticker(today))
        return 0

    span = RESID_M + BIAS_K + 6
    fc = forecast_runs(span)
    daily = daily_max_series()
    obh = obs_hourly_range(today - datetime.timedelta(days=span), today)

    bias, nb = rolling_bias(fc, daily, tkey)
    if bias is None:
        print('not enough scored history for a bias (%d days)' % nb)
        return 0

    # today's floor comes straight from the running daily max -- the same field
    # the market settles on, so no offset is needed here
    obs_far = daily.get(tkey)
    obs_hr = max(obh.get(tkey) or {0: 0}) if obh.get(tkey) else None
    yday = daily.get((today - datetime.timedelta(days=1)).isoformat())
    hr0 = obs_hr if obs_hr is not None else 0
    rest = [v for h, v in (fc.get(tkey) or {}).items() if h >= hr0]
    fpeak = max(rest) if rest else None
    fadj = point_forecast(fc.get(tkey) or {}, hr0, bias, yday)

    cands = [x for x in (obs_far, fadj) if x is not None]
    if not cands:
        print('no forecast and no observations yet')
        return 0
    pred = max(cands)
    res = residuals(fc, daily, obh, now.hour, tkey)
    sd, nsd = spread(res, now.hour)
    res_lock = residuals(fc, daily, obh, LOCK_HOUR, tkey)
    sd_lock, _ = spread(res_lock, LOCK_HOUR)

    ps = distribution(rows, pred, sd, obs_far)
    best = max(range(len(rows)), key=lambda i: ps[i])
    mbest = max(range(len(rows)), key=lambda i: rows[i]['mid'])

    log = load_log()
    hist = {h['date']: h for h in log.get('history', [])}

    if '--backfill' in sys.argv:
        added = 0
        for h in backfill(fc, daily, obh, fetch_settled(), sd_lock):
            if h['date'] not in hist:
                hist[h['date']] = h
                added += 1
        print('backfilled %d day(s)' % added)

    # ---- lock one decision per day, at or after noon ET, never overwritten
    entry = hist.get(tkey)
    if entry is None:
        entry = {'date': tkey, 'event': event_ticker(today)}
        hist[tkey] = entry
    if 'lock' not in entry and now.hour >= LOCK_HOUR:
        entry['lock'] = {
            'at': now.strftime('%Y-%m-%dT%H:%M') + ' ET',
            'pick': rows[best]['label'], 'ticker': rows[best]['ticker'],
            'p': round(ps[best], 4), 'pred': round(pred, 2), 'sd': sd,
            'bias': round(bias, 2), 'obs_at_lock': obs_far,
            'market_pick': rows[mbest]['label'], 'market_p': rows[mbest]['mid'],
            # bounds are stored with the lock so a past day can be scored even
            # if the live ladder has since changed shape
            'ladder': [{'label': r['label'], 'lo': r['lo'], 'hi': r['hi'],
                        'ours': round(p, 4), 'market': r['mid']}
                       for r, p in zip(rows, ps)],
        }
        print('LOCKED %s: %s (%.0f%%), market %s (%.0f%%)'
              % (tkey, rows[best]['label'], 100 * ps[best],
                 rows[mbest]['label'], 100 * rows[mbest]['mid']))

    # ---- score any past locked day whose actual has since been published
    for k, h in hist.items():
        if k >= tkey or 'lock' not in h or h.get('actual') is not None:
            continue
        a = daily.get(k)
        if a is None:
            continue
        lad = h['lock'].get('ladder') or []
        if not lad or lad[0].get('lo', 'x') == 'x':
            continue                       # pre-bounds lock; nothing to score against
        ai = which(lad, a)
        h['actual'] = a
        h['actual_bracket'] = lad[ai]['label'] if ai is not None else None
        h['hit'] = (h['lock']['pick'] == h['actual_bracket'])
        h['market_hit'] = (h['lock']['market_pick'] == h['actual_bracket'])
        h['err'] = round(h['lock']['pred'] - a, 2)
        print('scored %s: actual %.0f -> %s | ours %s %s | market %s %s'
              % (k, a, h['actual_bracket'], h['lock']['pick'],
                 'HIT' if h['hit'] else 'miss', h['lock']['market_pick'],
                 'HIT' if h['market_hit'] else 'miss'))

    scored = [h for h in hist.values() if h.get('actual') is not None and 'lock' in h]

    def is_interior(h):
        """Did the day settle in a bounded 2-degree bracket rather than an
        open-ended tail?  Tails are far easier to hit and flatter the score,
        so they are counted separately."""
        for r in (h.get('lock', {}).get('ladder') or []):
            if r['label'] == h.get('actual_bracket'):
                return r.get('lo') is not None and r.get('hi') is not None
        return False

    def tally(rows):
        e = [h['err'] for h in rows if h.get('err') is not None]
        inner = [h for h in rows if is_interior(h)]
        return {'n': len(rows), 'hits': sum(1 for h in rows if h.get('hit')),
                'mae': round(statistics.mean(abs(x) for x in e), 2) if e else None,
                'bias': round(statistics.mean(e), 2) if e else None,
                'interior_n': len(inner),
                'interior_hits': sum(1 for h in inner if h.get('hit'))}

    live = [h for h in scored if not h.get('backtest')]
    record = tally(scored)
    # live days are the honest score: a decision written down before the fact.
    # backtested days reconstruct what the same model would have picked, from
    # the day-ahead run and a bias fitted only on days already past.
    record['live'] = tally(live)
    record['backtest'] = tally([h for h in scored if h.get('backtest')])
    # head-to-head only exists where a contemporaneous market price was captured
    h2h = [h for h in live if h.get('market_hit') is not None]
    record['vs_market'] = {'n': len(h2h),
                           'ours': sum(1 for h in h2h if h.get('hit')),
                           'market': sum(1 for h in h2h if h.get('market_hit'))}
    # measured by replaying this exact model on the 68 real Kalshi ladders,
    # scored against the settlements themselves (2026-06-28..09-03)
    record['calibrated'] = {'mae': 1.66, 'bracket': '39/68', 'brier': 0.559,
                            'window': '2026-06-28..2026-09-03',
                            'lock_hour': LOCK_HOUR}

    doc = {
        'updated': now.strftime('%Y-%m-%dT%H:%M') + ' ET',
        'today': {
            'date': tkey, 'event': event_ticker(today),
            'close': rows[0]['close'], 'settles': 'Central Park (CLINYC), whole degrees',
            'pred': round(pred, 2), 'sd': sd, 'bias': round(bias, 2),
            'bias_days': nb, 'sd_days': nsd,
            'obs_so_far': obs_far, 'obs_through': obs_hr,
            'fc_peak': round(fpeak, 2) if fpeak is not None else None,
            'ours': [round(p, 4) for p in ps],
            'pick': rows[best]['label'], 'p': round(ps[best], 4),
            'market_pick': rows[mbest]['label'], 'market_p': rows[mbest]['mid'],
            'agree': best == mbest,
            'ladder': [{'label': r['label'], 'lo': r['lo'], 'hi': r['hi'],
                        'bid': r['bid'], 'ask': r['ask'], 'market': r['mid'],
                        'ours': round(p, 4), 'vol': r['vol']}
                       for r, p in zip(rows, ps)],
            'locked': entry.get('lock'),
        },
        'record': record,
        'history': sorted(hist.values(), key=lambda h: h['date'], reverse=True)[:120],
    }

    if dry:
        print(json.dumps(doc['today'], indent=2)[:2600])
        print('\nrecord:', json.dumps(record))
        return 0
    with open(OUT, 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('wrote %s (%d scored days)' % (OUT, record['n']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
