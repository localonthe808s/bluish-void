"""
DARK FLOW, ONE RULEBOOK (2026-10-02). insider_study.py (in sample, nightly) and dark_grade.py (forward, from the live
watcher's days) score bursts with exactly these functions, so the two numbers measure the same thing. Before this
the study used an adaptive threshold and the live watcher a flat $150, and neither merged one trader's order sliced
across consecutive minutes -- the forward test was grading a different set of bursts than the study had scored.

  bursts()        the study's rule: a minute whose signed aggressive money clears max($50, that market's 95th
                  percentile minute that day), then same-side minutes on one range within MERGE_GAP_MIN merged
                  into one burst (one decision, one data point).
  markouts()      where the price went 5 / 15 / 60 minutes after the burst ended, in the burst's own direction, in
                  cents of its side. Informed buying leaves the price moved; noise drifts back. Every burst is its
                  own data point within the hour -- the settlement verdict needs months, this needs weeks.
  release_move()  the sharp test of "they see the reading early" (KNYC's 1-minute data is government-only): the
                  price move ACROSS the next Central Park report, from the last trade before the observation time to
                  the trades 4-12 minutes after it, in the burst's direction. A crowd reacting to a public reading
                  cannot have known it; the control is the reaction bursts, judged the same way.
Fills are (t: aware UTC datetime, p: YES price 0-1, n: contracts, side: 'yes'|'no'), sorted by t.
"""
import bisect, datetime, math

FLOOR_USD, PCTL = 50.0, 0.95
MERGE_GAP_MIN = 3
MARKS = (5, 15, 60)
RELEASE_PRE_MAX_MIN, RELEASE_POST = 15, (4, 12)     # minutes
NEXT_REPORT_MAX_MIN = 60
MIN = datetime.timedelta(minutes=1)


def minute_of(t):
    return t.replace(second=0, microsecond=0)


def bursts(fills):
    """fills of ONE market inside the scored window -> (threshold, merged bursts)"""
    mins = {}
    for t, p, n, side in fills:
        e = mins.setdefault(minute_of(t), {'net': 0.0, 'ys': 0.0, 'yn': 0.0, 'ns': 0.0, 'nn': 0.0, 'fills': []})
        if side == 'yes':
            e['net'] += n * p; e['ys'] += n * p; e['yn'] += n
        else:
            e['net'] -= n * (1 - p); e['ns'] += n * (1 - p); e['nn'] += n
        e['fills'].append((p, n, side))
    if not mins:
        return None, []
    mags = sorted(abs(v['net']) for v in mins.values())
    thr = max(FLOOR_USD, mags[int(PCTL * (len(mags) - 1))])
    raw = []
    for k in sorted(mins):
        v = mins[k]
        if abs(v['net']) < thr:
            continue
        side = 'yes' if v['net'] > 0 else 'no'
        raw.append({'t0': k, 't1': k, 'side': side, 'usd': abs(v['net']),
                    'fills': [f for f in v['fills'] if f[2] == side]})
    out = []
    for b in raw:
        last = out[-1] if out else None
        if last and last['side'] == b['side'] and b['t0'] - last['t1'] <= MERGE_GAP_MIN * MIN:
            last['t1'] = b['t0']; last['usd'] += b['usd']; last['fills'] += b['fills']; last['minutes'] += 1
        else:
            b['minutes'] = 1; out.append(b)
    for b in out:
        n = sum(f[1] for f in b['fills'])
        b['px'] = (sum(f[0] * f[1] for f in b['fills']) / n) if n else None        # the YES price they traded at
    return thr, out


def px_near(times, fills, t, half_min=2, back_min=30):
    """the YES price at t: VWAP of the trades within +-half_min, else the last trade in the back_min before it"""
    a = bisect.bisect_left(times, t - half_min * MIN); b = bisect.bisect_right(times, t + half_min * MIN)
    if b > a:
        n = sum(fills[i][2] for i in range(a, b))
        if n: return sum(fills[i][1] * fills[i][2] for i in range(a, b)) / n
    i = bisect.bisect_left(times, t) - 1
    if i >= 0 and t - times[i] <= back_min * MIN:
        return fills[i][1]
    return None


def signed(side, d):
    return d if side == 'yes' else -d


def markouts(b, times, fills):
    """cents in the burst's direction at each mark after its last minute closed (None when nothing traded)"""
    if b.get('px') is None: return {}
    end = b['t1'] + MIN
    out = {}
    for m in MARKS:
        p = px_near(times, fills, end + m * MIN)
        out[str(m)] = None if p is None else round(100 * signed(b['side'], p - b['px']), 2)
    return out


def release_move(b, times, fills, reports):
    """the price move across the next Central Park report after the burst, in its direction (cents), and the lead"""
    end = b['t1'] + MIN
    i = bisect.bisect_left(reports, end)
    if i >= len(reports): return None
    r = reports[i]
    lead = (r - b['t0']).total_seconds() / 60
    if lead > NEXT_REPORT_MAX_MIN: return None
    j = bisect.bisect_left(times, r) - 1
    if j < 0 or r - times[j] > RELEASE_PRE_MAX_MIN * MIN: return None
    pre = fills[j][1]
    a = bisect.bisect_left(times, r + RELEASE_POST[0] * MIN); z = bisect.bisect_right(times, r + RELEASE_POST[1] * MIN)
    n = sum(fills[k][2] for k in range(a, z))
    if not n: return None
    post = sum(fills[k][1] * fills[k][2] for k in range(a, z)) / n
    return {'cents': round(100 * signed(b['side'], post - pre), 2), 'lead_min': round(lead, 1), 'report': r.isoformat()}


def clustered_mean(groups):
    """mean of per-burst values with a day-clustered standard error. groups: {day: [values]}"""
    vals = [v for g in groups.values() for v in g]
    N, G = len(vals), len(groups)
    if not N: return None
    m = sum(vals) / N
    se = None
    if G >= 2:
        se = math.sqrt(G / (G - 1) * sum((sum(g) - m * len(g)) ** 2 for g in groups.values())) / N
    return {'mean': round(m, 2), 'se': None if se is None else round(se, 2), 'n': N, 'days': G,
            'pos': round(sum(1 for v in vals if v > 0) / N, 3)}


def summarize_moves(rows):
    """rows: [(day, cls, markouts{}, release_move|None)] -> {cls: {'5': cm, '15': cm, '60': cm, 'next_report': cm}}"""
    out = {}
    for cls in ('dark', 'reaction'):
        res = {}
        for m in MARKS:
            g = {}
            for day, c, mo, _ in rows:
                if c == cls and mo.get(str(m)) is not None: g.setdefault(day, []).append(mo[str(m)])
            res[str(m)] = clustered_mean(g)
        g = {}
        for day, c, _, rm in rows:
            if c == cls and rm: g.setdefault(day, []).append(rm['cents'])
        res['next_report'] = clustered_mean(g)
        out[cls] = res
    return out
