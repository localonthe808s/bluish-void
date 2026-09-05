#!/usr/bin/env python3
"""Snapshot every candidate reading of today's high, every few minutes.

WHY THIS EXISTS.  On 2026-09-05 Central Park peaked at 79 degF at 2:33 PM. The
2:51 METAR read 25.0C = 77.0F -- the temperature had already fallen back, so the
peak was simply absent from the hourly stream. The market repriced "78 or below"
from 84c to 2c at about 4:25 PM. The preliminary climate report carrying the 79
was not issued until 4:43 PM, and the ASOS six-hour group covering that window
does not land until 7:51 PM. Something told the market first, and nothing here
could say what.

The one field that HAD the number early is TWC's temperatureMaxSince7Am: a
running maximum including intra-hour peaks. It read 79 while every hourly source
read 77. But it is a CURRENT-ONLY field -- there is no archive of it -- so its
reliability cannot be backtested, only recorded going forward. And it has
already been caught misbehaving once: 2026-09-05 Chicago reported max7 86 while
its own observation history peaked at 83 and the market sat at 99% on 83-84.
That is why it is not in the floor, and why this exists instead of a guess.

WHAT THIS ANSWERS, once it has run for a couple of weeks:

  1. Does max7 lead IEM daily, and by how many minutes?
  2. When max7 and IEM disagree, which one does the settlement side with?
  3. Are the Chicago-style spikes transient (they retract within a tick or two)
     or persistent? A transient spike is filterable; a persistent one is not.
  4. Is the lead worth anything -- does max7 move BEFORE the market does?

Nothing is inferred here and nothing is corrected. It writes down what each
source said and when it was asked, and leaves the arguing to later.

RUN: python3 obs_log.py            (one snapshot, all markets, appends a row each)
Wire it to a timer -- see obs_log.plist for the macOS agent, five minutes apart.
"""

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import kalshi_daily as kd            # MARKETS, get/get_json, the six-hourly reader

TRAIL = os.path.join(HERE, 'obs_trail')

# The station key that matters, and the trap that cost a whole study.
#
#   v3 /wx/observations/current?icaoCode=KNYC   -> Central Park   (right)
#   v1 /location/KNYC:9:US/observations/...     -> LaGuardia      (WRONG)
#
# Same ICAO, two endpoints, two different stations. LaGuardia runs a degree or
# three warmer than the park, which read as "TWC is biased high" across 45 days
# and produced a finding that had to be reverted. Verified 2026-09-05 21:00Z:
# icaoCode=KNYC returned now=76 against Central Park's own 75.9, while
# icaoCode=KLGA returned 78 against LaGuardia's 79.0.
#
# So: only the v3 current endpoint is used here, and `language` is REQUIRED --
# without it the answer is HTTP 400 with every field null, which reads exactly
# like a station outage rather than a malformed request.
def twc_current(cfg):
    icao = cfg.get('icao') or ('K' + cfg['station'])
    j = kd.get_json('https://api.weather.com/v3/wx/observations/current'
                    '?icaoCode=%s&units=e&language=en-US&format=json&apiKey=%s'
                    % (icao, kd.TWC_KEY), timeout=30)
    if not isinstance(j, dict):
        return {}
    out = {}
    for src, dst in (('temperatureMaxSince7Am', 'max7'),
                     ('temperature', 'now'),
                     ('temperatureMax24Hour', 'max24')):
        v = j.get(src)
        if isinstance(v, (int, float)):
            out[dst] = float(v)
    return out


def iem_daily_today(cfg, day):
    """IEM's running daily max for `day`, or None.

    The date-ranged form, not daily.json with no date: that returns the whole
    archive back to 1943, which is 8.8 MB a station and absurd at this cadence.
    """
    u = ('https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py'
         '?network=%s&stations=%s&year1=%d&month1=%d&day1=%d'
         '&year2=%d&month2=%d&day2=%d&format=comma'
         % (cfg['network'], cfg['station'], day.year, day.month, day.day,
            day.year, day.month, day.day))
    import csv, io
    for r in csv.DictReader(io.StringIO(kd.get(u, timeout=60).decode())):
        v = r.get('max_temp_f')
        if v not in (None, '', 'M', 'None'):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def latest_metar(cfg):
    """(iso timestamp, degF) of the newest report, or (None, None).

    The hourly spot value -- the thing that missed the peak. Logged so the lead
    can be measured against it and not just asserted.
    """
    icao = cfg.get('icao') or ('K' + cfg['station'])
    j = kd.get_json('https://aviationweather.gov/api/data/metar?ids=%s&format=json&hours=3'
                    % icao, timeout=30)
    best = None
    for m in (j or []):
        t = m.get('temp')
        rt = m.get('reportTime')
        if t is None or not rt:
            continue
        if best is None or rt > best[0]:
            best = (rt, round(float(t) * 9.0 / 5.0 + 32.0, 1))
    return best or (None, None)


def snapshot():
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    os.makedirs(TRAIL, exist_ok=True)
    path = os.path.join(TRAIL, now.strftime('%Y-%m') + '.jsonl')
    wrote = 0
    with open(path, 'a') as fh:
        for cfg in kd.MARKETS:
            # every source is optional; one city's outage must not cost the rest
            row = {'t': now.isoformat().replace('+00:00', 'Z'), 'key': cfg['key']}
            try:
                day = kd.local_now(cfg).date()
                row['day'] = day.isoformat()
            except Exception as e:
                row['err_day'] = str(e)[:80]
                day = now.date()
                row['day'] = day.isoformat()
            for name, fn in (('twc', lambda: twc_current(cfg)),
                             ('iem', lambda: iem_daily_today(cfg, day)),
                             ('metar', lambda: latest_metar(cfg)),
                             ('six', lambda: kd.metar_six_max(cfg, day))):
                try:
                    v = fn()
                except Exception as e:
                    row['err_' + name] = '%s: %s' % (type(e).__name__, str(e)[:60])
                    continue
                if name == 'twc' and v:
                    row.update(v)
                elif name == 'iem':
                    row['iem'] = v
                elif name == 'metar':
                    row['metar_at'], row['metar'] = v
                elif name == 'six':
                    row['six'] = v
            fh.write(json.dumps(row, sort_keys=True) + '\n')
            wrote += 1
            # the interesting line, printed so a tail of the log is readable
            print('  %-9s max7=%-5s iem=%-5s metar=%-5s six=%-5s%s'
                  % (cfg['key'], row.get('max7'), row.get('iem'), row.get('metar'),
                     row.get('six'),
                     '  LEAD +%.1f' % (row['max7'] - row['iem'])
                     if row.get('max7') is not None and row.get('iem') is not None
                     and row['max7'] > row['iem'] else ''))
    print('%s  wrote %d rows -> %s' % (now.strftime('%H:%M:%SZ'), wrote,
                                       os.path.relpath(path, HERE)))
    return 0


if __name__ == '__main__':
    sys.exit(snapshot())
