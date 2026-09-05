#!/usr/bin/env python3
"""When does the KXHIGHNY market actually move, and what moves it?

Minute candlesticks, which are public and need no key. The hourly rows in
price_rows.json already showed that our forecast LEADS the market by about an
hour (correlation of d(market at h) with d(ours at h-1) is 0.29, against 0.06
at every other lag). That is the tradeable claim. This asks the finer question
it cannot: within an hour, WHEN does the market move, and does it cluster
around the moments new weather data lands?

The candles carry yes_bid and yes_ask, so "moved" here is the mid crossing, not
a print -- a market can reprice without a trade and usually does.

Times below are ET. The station reports at :51. Model deliveries are the
approximate wall-clock at which each run becomes fetchable, not its run hour.
"""
import calendar
import collections
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K                                   # noqa: E402
import price_study as PS                                   # noqa: E402

DAYS = 6
# Minute candles for a settled market never change, so they are cached. A rerun
# to ask a different question of the same days costs nothing and, more to the
# point, does not spend another 36 calls against a rate limit that has bitten
# this project before.
CACHE = os.path.join(HERE, 'candle_cache.json')
CFG = [c for c in K.MARKETS if c['key'] == 'ny_high'][0]
TZOFF = 4                                    # ET = UTC-4 in season

# Roughly when each source becomes available, ET. HRRR and NBM land hourly; the
# global runs land once every six or twelve hours, hours after their run time.
DELIVERIES = {
    'HRRR/NBM (hourly)': None,               # every hour, handled separately
    'GFS 06Z':  5.5,   'GFS 12Z': 11.5,  'GFS 18Z': 17.5,
    'ECMWF 00Z': 3.0,  'ECMWF 12Z': 15.0,
}


_CACHE = {}
if os.path.exists(CACHE):
    try:
        _CACHE = json.load(open(CACHE))
    except Exception:
        _CACHE = {}


def minute_candles(ticker, day):
    """[(datetime ET, mid)] for one market across one trading day."""
    ck = '%s|%s' % (ticker, day.isoformat())
    if ck in _CACHE:
        return [(datetime.datetime.fromisoformat(t), m) for t, m in _CACHE[ck]]
    start = calendar.timegm(datetime.datetime(day.year, day.month, day.day).timetuple()) \
        + TZOFF * 3600
    u = ('https://api.elections.kalshi.com/trade-api/v2/series/%s/markets/%s'
         '/candlesticks?period_interval=1&start_ts=%d&end_ts=%d'
         % (CFG['series'], ticker, start, start + 26 * 3600))
    out = []
    try:
        j = K.get_json(u, timeout=60)
    except Exception as e:
        print('   %s: %s' % (ticker, e))
        return out
    for x in j.get('candlesticks') or []:
        b = (x.get('yes_bid') or {}).get('close_dollars')
        a = (x.get('yes_ask') or {}).get('close_dollars')
        if b is None or a is None:
            continue
        t = datetime.datetime.utcfromtimestamp(x['end_period_ts']) \
            - datetime.timedelta(hours=TZOFF)
        out.append((t, (float(b) + float(a)) / 2.0))
    _CACHE[ck] = [(t.isoformat(), m) for t, m in out]
    return out


def main():
    ev = PS.settled_events(CFG)
    days = sorted(ev)[-DAYS:]
    print('%d settled days: %s\n' % (len(days), ', '.join(days)))

    by_hour = collections.defaultdict(float)     # ET hour -> summed |dmid|
    by_min = collections.defaultdict(float)      # minute of hour -> summed |dmid|
    hour_n = collections.defaultdict(int)
    min_n = collections.defaultdict(int)
    series = 0

    for d in days:
        day = datetime.date(*map(int, d.split('-')))
        for m in ev[d]:
            cached = ('%s|%s' % (m['ticker'], day.isoformat())) in _CACHE
            c = minute_candles(m['ticker'], day)
            if not cached:
                time.sleep(0.4)                           # these rate-limit
            if len(c) < 60:
                continue
            series += 1
            for i in range(1, len(c)):
                t0, p0 = c[i - 1]
                t1, p1 = c[i]
                if (t1 - t0).total_seconds() > 300:      # a gap, not a move
                    continue
                dm = abs(p1 - p0)
                by_hour[t1.hour] += dm; hour_n[t1.hour] += 1
                by_min[t1.minute] += dm; min_n[t1.minute] += 1
            time.sleep(0.4)                               # these rate-limit

    try:
        json.dump(_CACHE, open(CACHE, 'w'))
    except Exception as e:
        print('cache not written: %s' % e)
    if not series:
        print('no candles came back'); return 1
    print('%d market-days of minute candles\n' % series)

    print('WHERE THE MOVEMENT IS, BY HOUR (ET)   mean |d mid| per minute, in cents')
    peak = max((by_hour[h] / hour_n[h]) for h in by_hour if hour_n[h] > 30)
    for h in sorted(by_hour):
        if hour_n[h] <= 30:
            continue
        v = by_hour[h] / hour_n[h]
        print('  %2d:00  %5.2f¢  %s' % (h, 100 * v, '#' * int(round(28 * v / peak))))

    print('\nWITHIN THE HOUR   mean |d mid| per minute, in cents')
    pk = max((by_min[m] / min_n[m]) for m in by_min if min_n[m] > 20)
    for m in sorted(by_min):
        if min_n[m] <= 20:
            continue
        v = by_min[m] / min_n[m]
        mark = '  <- station reports' if m in (51, 52, 53, 54, 55) else ''
        print('  :%02d  %5.2f¢  %s%s' % (m, 100 * v, '#' * int(round(26 * v / pk)), mark))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
