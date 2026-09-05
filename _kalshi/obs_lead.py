#!/usr/bin/env python3
"""Read the obs_log trail and answer the questions it was started to answer.

Run it any time; it says how much record exists and reports only what that much
record can support. The interesting numbers need a couple of weeks -- a lead
measured on one afternoon is an anecdote with a decimal point.

  python3 obs_lead.py            all cities
  python3 obs_lead.py ny_high    one
"""

import collections
import datetime
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIL = os.path.join(HERE, 'obs_trail')


def pull():
    """Fold the worker's trail into the local one, if it is configured.

    The Mac's agent and the Cloudflare worker write the same row shape, so both
    land in the same files and neither is authoritative. Rows are de-duplicated
    on (t, key), which is exactly the identity of a snapshot, so pulling twice
    costs nothing and a laptop tick that overlaps a worker tick is not counted
    twice.

    Configure with, e.g.:
        export BV_OBS_URL=https://bluish-void-kalshi-cron.<sub>.workers.dev/obs
        export BV_OBS_TOKEN=<the PANEL_TOKEN>
    """
    url, tok = os.environ.get('BV_OBS_URL'), os.environ.get('BV_OBS_TOKEN')
    if not url:
        return 0
    import urllib.request
    have = set()
    for r in load():
        have.add((r.get('t'), r.get('key')))
    since = max((t for t, _ in have if t), default='')
    req = urllib.request.Request(
        url + ('&' if '?' in url else '?') + 'since=' + since,
        headers={'Authorization': 'Bearer %s' % (tok or '')})
    try:
        body = urllib.request.urlopen(req, timeout=60).read().decode()
    except Exception as e:
        print('  (worker pull failed: %s)' % str(e)[:80])
        return 0
    add = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if (r.get('t'), r.get('key')) in have:
            continue
        have.add((r.get('t'), r.get('key')))
        add.append(r)
    if not add:
        return 0
    os.makedirs(TRAIL, exist_ok=True)
    by_month = collections.defaultdict(list)
    for r in add:
        by_month[str(r.get('t', ''))[:7] or 'unknown'].append(r)
    for month, rs in by_month.items():
        with open(os.path.join(TRAIL, month + '.jsonl'), 'a') as fh:
            for r in sorted(rs, key=lambda x: (x.get('t', ''), x.get('key', ''))):
                fh.write(json.dumps(r, sort_keys=True) + '\n')
    print('  pulled %d new rows from the worker' % len(add))
    return len(add)


def load(only=None):
    rows = []
    for p in sorted(glob.glob(os.path.join(TRAIL, '*.jsonl'))):
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if only and r.get('key') != only:
                    continue
                rows.append(r)
    return rows


def ts(r):
    return datetime.datetime.fromisoformat(r['t'].replace('Z', '+00:00'))


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    pull()
    rows = load(only)
    if not rows:
        print('no trail yet -- is the agent loaded?  launchctl list | grep obslog')
        return 1

    by = collections.defaultdict(list)
    for r in rows:
        by[(r.get('key'), r.get('day'))].append(r)
    span = (ts(max(rows, key=ts)) - ts(min(rows, key=ts)))
    print('%d rows, %d city-days, spanning %s\n'
          % (len(rows), len(by), str(span).split('.')[0]))

    # 1 & 4. WHO GETS THERE FIRST.  For each city-day, the day's eventual peak is
    # the largest value any source ever showed; the lead is how long one source
    # sat at that value before another reached it. Only closed days count -- on a
    # day still running, "eventual" is a guess.
    print('  FIRST TO THE DAY\'S EVENTUAL MAX  (closed city-days only)')
    print('  %-9s %-11s %6s   %-16s %-16s %s'
          % ('city', 'day', 'peak', 'max7 first at', 'iem first at', 'lead'))
    leads = collections.defaultdict(list)
    for (key, day), rs in sorted(by.items()):
        rs.sort(key=ts)
        vals = [v for r in rs for v in (r.get('max7'), r.get('iem'), r.get('six'))
                if v is not None]
        if not vals:
            continue
        peak = max(vals)
        first = {}
        for src in ('max7', 'iem', 'six'):
            hit = next((r for r in rs if r.get(src) is not None
                        and r[src] >= peak - 0.01), None)
            first[src] = ts(hit) if hit else None
        # a day is only closed if the last row is well after local dark; without
        # that, whoever is merely EARLIEST looks like whoever is RIGHT
        closed = (ts(rs[-1]) - ts(rs[0])) > datetime.timedelta(hours=6)
        if not closed:
            continue
        lead = ''
        if first['max7'] and first['iem']:
            d = (first['iem'] - first['max7']).total_seconds() / 60.0
            lead = '%+.0f min' % d
            leads[key].append(d)
        print('  %-9s %-11s %6.1f   %-16s %-16s %s'
              % (key, day, peak,
                 first['max7'].strftime('%H:%M:%SZ') if first['max7'] else '-',
                 first['iem'].strftime('%H:%M:%SZ') if first['iem'] else '-', lead))
    if leads:
        print('\n  median lead of max7 over IEM daily, per city:')
        for k, v in sorted(leads.items()):
            v = sorted(v)
            print('    %-9s %+6.0f min over %d day(s)' % (k, v[len(v) // 2], len(v)))
    else:
        print('  (none closed yet)')

    # 2 & 3. THE SPIKES.  2026-09-05 Chicago read max7 86 against IEM 83 with the
    # market at 99% on 83-84, and it had NOT retracted hours later. Transient
    # spikes are filterable; persistent ones are not, and the difference decides
    # whether max7 can ever be trusted in the floor.
    print('\n  max7 ABOVE iem  (how long each excursion lasted)')
    print('  %-9s %-11s %6s %6s %6s   %s' % ('city', 'day', 'max7', 'iem', 'gap', 'held for'))
    n = 0
    for (key, day), rs in sorted(by.items()):
        rs.sort(key=ts)
        run = None
        for r in rs + [None]:
            hot = (r is not None and r.get('max7') is not None
                   and r.get('iem') is not None and r['max7'] > r['iem'] + 0.01)
            if hot and run is None:
                run = [r, r]
            elif hot:
                run[1] = r
            elif run is not None:
                held = ts(run[1]) - ts(run[0])
                print('  %-9s %-11s %6.1f %6.1f %+6.1f   %s%s'
                      % (key, day, run[0]['max7'], run[0]['iem'],
                         run[0]['max7'] - run[0]['iem'], str(held).split('.')[0],
                         '  (still open)' if run[1] is rs[-1] else ''))
                n += 1
                run = None
    if not n:
        print('  (none seen yet)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
