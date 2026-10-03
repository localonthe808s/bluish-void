#!/usr/bin/env python3
"""
THE INFORMED-FLOW STUDY (2026-10-02). User: "some insiders have it and kalshi does not have a good method at
detecting it ... are there trends in the bets that would hint at the group of betters we can lean on for insight,
or would it be easier to identify the general blind betting public".

Kalshi's public trade tape gives every fill (time to the microsecond, size, price, which side crossed the spread)
but no account. So the question is asked of the BETS, not the bettors:

  1. INFORMED FLOW. A burst of one-sided aggressive buying that lands when NO public reading has just come out
     ("dark") and still beats the price it paid would be someone trading on data the public lacks (the 1-minute
     ASOS stream MADIS keeps for government users, a private sensor, a feed ahead of ours). A burst inside a
     release window ("reaction") is the crowd catching up and is the control.
  2. THE BLIND PUBLIC. Taker returns by size, price and hour: who reliably loses, i.e. whose flow is worth fading.

Everything is scored as RETURN ON STAKE AT THE PRICE PAID, after Kalshi's taker fee -- never "did the flow point at
the winner", which late in the day is just the price already knowing. Standard errors are clustered by day (bursts
in one day are not independent). Read-only: it reads Kalshi's public API, IEM, and the local obs trail.

    python3 insider_study.py            # fetch what is not cached, then score
    python3 insider_study.py --offline  # score from the cache only

Writes insider_study.json (committed summary) and caches raw trades in insider_cache/ (gitignored).
"""
import bisect, collections, datetime, json, math, os, re, sys, time, urllib.request
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dark_lib as DL                          # noqa: E402  the rulebook shared with dark_grade.py

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'insider_cache')
API = 'https://api.elections.kalshi.com/trade-api/v2'
UA = {'User-Agent': 'bluishvoid-insider-study'}
CITIES = {
    'ny_high':  {'series': 'KXHIGHNY',  'station': 'NYC', 'network': 'NY_ASOS', 'cli': 'CLINYC', 'fcst': 'ZFPOKX,AFDOKX', 'tz': 'America/New_York',    'five_min_public': False},
    'las_high': {'series': 'KXHIGHTLV', 'station': 'LAS', 'network': 'NV_ASOS', 'cli': 'CLILAS', 'fcst': 'ZFPVEF,AFDVEF', 'tz': 'America/Los_Angeles', 'five_min_public': True},
    'aus_high': {'series': 'KXHIGHAUS', 'station': 'AUS', 'network': 'TX_ASOS', 'cli': 'CLIAUS', 'fcst': 'ZFPEWX,AFDEWX', 'tz': 'America/Chicago',     'five_min_public': True},
}
SINCE = datetime.date(2026, 9, 4)            # the live record starts here
WINDOW_H = (7, 20)                           # local hours scored: the trading day, before the climate report decides it
METAR_WIN = 9                                # minutes after an observation that count as "reaction"
CLI_WIN = 10
FCST_WIN = 10                                # an NWS zone forecast or discussion issued (2026-10-02): its high is public
TWC_WIN = 6
FIVE_MIN_LAG = 12                            # api.weather.gov publishes the 5-minute rows ~10-15 min late
OFFLINE = '--offline' in sys.argv


def get_json(url, tries=6):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(3 * (2 ** i)); continue
            raise
        except Exception:
            if i < tries - 1: time.sleep(3 * (2 ** i)); continue
            raise


def get_text(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read().decode('utf-8', 'replace')


def ts(s):
    m = re.match(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)', s)
    return datetime.datetime.fromisoformat(m.group(1) + '+00:00')


def cached(name, fn, max_age_h=None):
    p = os.path.join(CACHE, name)
    # the settled-event list grows every day: re-read it once it is older than max_age_h (the nightly re-run,
    # 2026-10-02); trades, METAR and CLI files are keyed by settled ticker or date range and never change
    if os.path.exists(p) and not (max_age_h and not OFFLINE and time.time() - os.path.getmtime(p) > max_age_h * 3600):
        with open(p) as f: return json.load(f)
    if OFFLINE: return None
    v = fn()
    os.makedirs(CACHE, exist_ok=True)
    with open(p, 'w') as f: json.dump(v, f)
    return v


# ---------------------------------------------------------------- the tape ----
def settled_events(series):
    out = {}
    cur = ''
    while True:
        j = get_json('%s/markets?series_ticker=%s&status=settled&limit=1000%s' % (API, series, '&cursor=' + cur if cur else ''))
        for m in j.get('markets', []):
            out.setdefault(m['event_ticker'], []).append({'ticker': m['ticker'], 'result': m.get('result'),
                                                          'value': m.get('expiration_value')})
        cur = j.get('cursor') or ''
        if not cur: break
    return out


def trades(ticker):
    def fetch():
        rows, cur = [], ''
        while True:
            j = get_json('%s/markets/trades?ticker=%s&limit=1000%s' % (API, ticker, '&cursor=' + cur if cur else ''))
            for t in j.get('trades', []):
                rows.append([t['created_time'], float(t['yes_price_dollars']), float(t['count_fp']), t['taker_side']])
            cur = j.get('cursor') or ''
            time.sleep(0.25)
            if not cur: break
        return rows
    return cached('trades_%s.json' % ticker, fetch)


def event_day(ev):
    m = re.search(r'-(\d\d)([A-Z]{3})(\d\d)$', ev)
    return datetime.datetime.strptime('20%s %s %s' % (m.group(1), m.group(2), m.group(3)), '%Y %b %d').date()


# ------------------------------------------------------- the public clock ----
def metar_times(c, d0, d1):
    """Every routine AND special observation (UTC), from IEM."""
    def fetch():
        u = ('https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=%s&data=tmpf&year1=%d&month1=%d&day1=%d'
             '&year2=%d&month2=%d&day2=%d&tz=Etc/UTC&format=onlycomma&latlon=no&missing=M&report_type=3&report_type=4'
             % (c['station'], d0.year, d0.month, d0.day, d1.year, d1.month, d1.day))
        out = []
        for line in get_text(u).splitlines()[1:]:
            p = line.split(',')
            if len(p) >= 2: out.append(p[1].strip().replace(' ', 'T') + ':00')
        return out
    return [ts(x) for x in cached('metar_%s_%s_%s.json' % (c['station'], d0, d1), fetch) or []]


def cli_times(c, d0, d1):
    """Issue time of every climate report for the station (UTC), from the NOAAPort archive at IEM."""
    def fetch():
        txt = get_text('https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=%s&sdate=%s&edate=%s&limit=9999&fmt=text'
                       % (c['cli'], d0, d1 + datetime.timedelta(days=2)))
        out = []
        for m in re.finditer(r'(?m)^CDUS\d+ K[A-Z]{3} (\d\d)(\d\d)(\d\d)\s*$', txt):
            dd, hh, mi = int(m.group(1)), int(m.group(2)), int(m.group(3))
            for base in (d0 + datetime.timedelta(days=k) for k in range(-1, (d1 - d0).days + 3)):
                if base.day == dd:
                    out.append(datetime.datetime(base.year, base.month, dd, hh, mi).isoformat() + '+00:00'); break
        return sorted(set(out))
    return [datetime.datetime.fromisoformat(x) for x in cached('cli_%s_%s_%s.json' % (c['cli'], d0, d1), fetch) or []]


def fcst_times(c, d0, d1):
    """Issue time of every NWS zone forecast and forecast discussion for the office (UTC), same archive as the CLI."""
    def fetch():
        txt = get_text('https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=%s&sdate=%s&edate=%s&limit=9999&fmt=text'
                       % (c['fcst'], d0, d1 + datetime.timedelta(days=2)))
        out = []
        for m in re.finditer(r'(?m)^(?:FPUS|FXUS)\d+ K[A-Z]{3} (\d\d)(\d\d)(\d\d)\s*$', txt):
            dd, hh, mi = int(m.group(1)), int(m.group(2)), int(m.group(3))
            for base in (d0 + datetime.timedelta(days=k) for k in range(-1, (d1 - d0).days + 3)):
                if base.day == dd:
                    out.append(datetime.datetime(base.year, base.month, dd, hh, mi).isoformat() + '+00:00'); break
        return sorted(set(out))
    return [datetime.datetime.fromisoformat(x) for x in cached('fcst_%s_%s_%s.json' % (c['fcst'].replace(',', '_'), d0, d1), fetch) or []]


def twc_bumps(key):
    """Windows in which TWC's public running maximum went up (from the local 5-10 minute obs trail)."""
    rows = []
    for f in ('2026-09.jsonl', '2026-10.jsonl'):
        p = os.path.join(HERE, 'obs_trail', f)
        if not os.path.exists(p): continue
        for l in open(p):
            try: r = json.loads(l)
            except Exception: continue
            if r.get('key') == key and isinstance(r.get('max7'), (int, float)): rows.append((ts(r['t']), r['day'], r['max7']))
    rows.sort(); out = []
    for a, b in zip(rows, rows[1:]):
        if b[1] == a[1] and b[2] > a[2]: out.append((a[0], b[0]))       # it rose somewhere in (a, b]
    return out


# ------------------------------------------------------------- scoring ----
def fee(p, n):
    return 0.07 * n * p * (1 - p)


def taker_leg(price_yes, n, side, won_yes):
    """Stake and payoff of one taker fill, from the taker's side."""
    p = price_yes if side == 'yes' else 1 - price_yes
    stake = n * p + fee(p, n)
    win = won_yes if side == 'yes' else (not won_yes)
    return stake, (n if win else 0.0)


def clustered(groups):
    """Return on stake with a day-clustered standard error. groups: {day: (stake, payoff)}"""
    S = sum(s for s, _ in groups.values()); P = sum(p for _, p in groups.values())
    if S <= 0: return None
    r = P / S - 1
    n = len(groups)
    if n < 2: return {'ret': round(r, 3), 'days': n, 'se': None, 'stake': round(S, 2)}
    resid = [(p - (1 + r) * s) for s, p in groups.values()]
    se = math.sqrt(n / (n - 1) * sum(x * x for x in resid)) / S
    return {'ret': round(r, 3), 'se': round(se, 3), 'days': n, 'stake': round(S, 2)}


def main():
    out = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'cities': {}}
    for key, c in CITIES.items():
        z = ZoneInfo(c['tz'])
        evs = cached('events_%s.json' % c['series'], lambda: settled_events(c['series']), max_age_h=6) or {}
        evs = {e: m for e, m in evs.items() if event_day(e) >= SINCE and any(x['result'] == 'yes' for x in m)}
        if not evs: continue
        days = sorted(event_day(e) for e in evs)
        d0, d1 = days[0], days[-1]
        print('%s: %d settled days %s..%s' % (key, len(evs), d0, d1), flush=True)
        releases = [(t, t + datetime.timedelta(minutes=METAR_WIN), 'metar') for t in metar_times(c, d0, d1 + datetime.timedelta(days=1))]
        releases += [(t, t + datetime.timedelta(minutes=CLI_WIN), 'cli') for t in cli_times(c, d0, d1)]
        releases += [(t, t + datetime.timedelta(minutes=FCST_WIN), 'fcst') for t in fcst_times(c, d0, d1)]
        reports = sorted(t for t in metar_times(c, d0, d1 + datetime.timedelta(days=1)))
        releases += [(a, b + datetime.timedelta(minutes=TWC_WIN), 'twc') for a, b in twc_bumps(key)]
        releases.sort()
        starts = [r[0] for r in releases]
        import bisect
        def public_at(t):
            if c['five_min_public']: return 'five_min'          # in LV/AUS a public 5-minute reading is never far off
            i = bisect.bisect_right(starts, t)
            for j in range(max(0, i - 40), i):
                if releases[j][0] <= t <= releases[j][1]: return releases[j][2]
            return None
        bursts = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
        blind = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
        allflow = collections.defaultdict(lambda: [0.0, 0.0])
        nb = collections.Counter(); leads = []; moves = []
        for ev, mk in sorted(evs.items()):
            day = event_day(ev)
            for m in mk:
                won = m['result'] == 'yes'
                tr = trades(m['ticker']) or []
                fills = []
                for t, p, n, side in tr:
                    tt = ts(t); lt = tt.astimezone(z)
                    if lt.date() != day or not (WINDOW_H[0] <= lt.hour < WINDOW_H[1]): continue
                    fills.append((tt, lt, p, n, side))
                    s, pay = taker_leg(p, n, side, won)
                    a = allflow[day]; a[0] += s; a[1] += pay
                    dol = n * (p if side == 'yes' else 1 - p)
                    pc = p if side == 'yes' else 1 - p
                    for name, b in (('size', '<$2' if dol < 2 else '$2-10' if dol < 10 else '$10-50' if dol < 50 else '$50-250' if dol < 250 else '$250+'),
                                    ('price', '1-5c' if pc <= .05 else '6-20c' if pc <= .20 else '21-50c' if pc <= .5 else '51-80c' if pc <= .8 else '81-95c' if pc <= .95 else '96-99c'),
                                    ('hour', '%02d' % lt.hour)):
                        g = blind[name + ':' + b][day]; g[0] += s; g[1] += pay
                # THE SHARED RULEBOOK (dark_lib): the study's threshold, split orders merged, markouts and the
                # move across the next report scored on the whole tape (a 7:55 PM burst still has its 60 minutes)
                tape = sorted((ts(t), p, n, side) for t, p, n, side in tr)
                times = [x[0] for x in tape]
                _, bl = DL.bursts([(tt, p, n, side) for tt, lt, p, n, side in fills])
                for b in bl:
                    S = P = 0.0
                    for p, n, sd in b['fills']:
                        s_, pay = taker_leg(p, n, sd, won); S += s_; P += pay
                    pub = public_at(b['t0'])
                    cls = 'reaction' if pub else 'dark'
                    g = bursts[cls][day]; g[0] += S; g[1] += P
                    nb[cls] += 1
                    moves.append((day, cls, DL.markouts(b, times, tape), DL.release_move(b, times, tape, reports)))
                    if cls == 'dark' and (P > S):          # a dark burst that won: how long before the next release?
                        i = bisect.bisect_right(starts, b['t0'])
                        if i < len(starts): leads.append((starts[i] - b['t0']).total_seconds() / 60)
        res = {
            'days': len(evs),
            'all_taker_flow': clustered(allflow),
            'bursts': {cls: dict(clustered(bursts[cls]) or {}, n=nb[cls]) for cls in ('dark', 'reaction')},
            'moves': DL.summarize_moves(moves),
            'rule': 'max($%d, p%d minute) per market-day; same side within %d min merged' % (DL.FLOOR_USD, DL.PCTL * 100, DL.MERGE_GAP_MIN),
            'dark_winner_lead_min': (round(sorted(leads)[len(leads) // 2], 1) if leads else None),
            'blind': {k: clustered(v) for k, v in sorted(blind.items())},
            'note': ('5-minute readings are public here, so almost no minute is dark: the burst split is not a test'
                     if c['five_min_public'] else 'hourly public cadence: the clean test'),
        }
        out['cities'][key] = res
        print(json.dumps(res['bursts']), flush=True)
        print('  moves', json.dumps(res['moves']), flush=True)
    with open(os.path.join(HERE, 'insider_study.json'), 'w') as f:
        json.dump(out, f, indent=1)
    return out


if __name__ == '__main__':
    main()
