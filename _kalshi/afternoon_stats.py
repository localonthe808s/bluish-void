#!/usr/bin/env python3
"""
THE AFTERNOON TABLE -- with the latest hourly report in hand, how much higher
does the official daily maximum end up?  Per city, season and local hour, from
the hourly observation archive (IEM ASOS, since 2025-01-01) against the IEM
daily maximum (the settlement quantity, verified against Kalshi 112/112).

    after 1:51 PM, New York, all seasons: 60% of days still climb a degree and
    35% two; after 2:51 PM 46% / 20% -- 50% / 21% in summer, 29% / 13% in autumn.

Written to afternoon.json nightly; the bake stamps today's row on the document
(today.climb) and the panel prints it in the CONFIDENCE block and the BAIL line,
so a held position knows what a "2 degree climb from here" is actually worth.
Measured 2026-09-13 on 612 Central Park days (_kalshi/nyc_regimes.py).

Also split by whether the last hour was still rising: that only separates days
before 2 PM (12:51 PM rising 81% vs flat 61%); by 3 PM the trend says nothing.
"""
import csv, io, json, os, sys, time, collections, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K                                   # noqa: E402
OUT = os.path.join(HERE, 'afternoon.json')
CACHE = os.path.join(HERE, '_study')
SINCE = '2025-01-01'
HOURS = range(10, 18)
SEASON = {12: 'DJF', 1: 'DJF', 2: 'DJF', 3: 'MAM', 4: 'MAM', 5: 'MAM',
          6: 'JJA', 7: 'JJA', 8: 'JJA', 9: 'SON', 10: 'SON', 11: 'SON'}


def fetch(name, url):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 20 * 3600:
        req = urllib.request.Request(url, headers={'User-Agent': 'bluishvoid.com afternoon study'})
        data = urllib.request.urlopen(req, timeout=240).read()
        with open(p, 'wb') as fh:
            fh.write(data)
    return io.open(p, encoding='utf-8', errors='replace').read()


def inputs(cfg):
    y, m, d = time.strftime('%Y-%m-%d').split('-')
    st, net, tz = cfg['station'], cfg['network'], cfg['tz']
    daily = fetch('%s_daily.csv' % st,
                  'https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?network=%s&stations=%s'
                  '&year1=2025&month1=1&day1=1&year2=%s&month2=%s&day2=%s&format=comma' % (net, st, y, m, d))
    hourly = fetch('%s_hourly.csv' % st,
                   'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=%s&data=tmpf'
                   '&year1=2025&month1=1&day1=1&year2=%s&month2=%s&day2=%s&tz=%s&format=onlycomma'
                   '&latlon=no&elev=no&missing=M&trace=T&direct=no&report_type=3'
                   % (st, y, m, d, urllib.parse.quote(tz)))
    truth = {}
    for r in csv.DictReader(io.StringIO(daily)):
        v = r.get('max_temp_f')
        if v not in (None, '', 'M', 'None'):
            truth[r['day']] = float(v)
    obs = collections.defaultdict(dict)
    for r in csv.DictReader(io.StringIO(hourly)):
        if r.get('tmpf') in ('M', '', None):
            continue
        h, mn = int(r['valid'][11:13]), int(r['valid'][14:16])
        if 45 <= mn <= 59:                      # the routine report (:51 NYC, :53 AUS, :56 LAS)
            obs[r['valid'][:10]][h] = float(r['tmpf'])
    return truth, obs


def table(truth, obs):
    days = [d for d in sorted(truth) if d >= SINCE and len(obs.get(d, {})) >= 20]
    out = {'n_days': len(days), 'by_season': {}}
    for se in ('DJF', 'MAM', 'JJA', 'SON', 'ALL'):
        rows = {}
        for h in HOURS:
            g, rise, flat = [], [], []
            for d in days:
                if se != 'ALL' and SEASON[int(d[5:7])] != se:
                    continue
                o = obs[d]
                if h not in o or (h - 1) not in o:
                    continue
                run = max(v for k, v in o.items() if k <= h)
                gap = truth[d] - run
                g.append(gap)
                (rise if o[h] > o[h - 1] else flat).append(gap)
            if len(g) < 20:
                continue

            def pc(xs, t):
                return round(sum(1 for x in xs if x >= t) / float(len(xs)), 3) if xs else None
            rows[str(h)] = {'n': len(g), 'p0': round(sum(1 for x in g if x < 0.5) / float(len(g)), 3),
                            'p1': pc(g, 0.5), 'p2': pc(g, 1.5), 'p3': pc(g, 2.5),
                            'rise': {'n': len(rise), 'p1': pc(rise, 0.5), 'p2': pc(rise, 1.5), 'p3': pc(rise, 2.5)},
                            'flat': {'n': len(flat), 'p1': pc(flat, 0.5), 'p2': pc(flat, 1.5), 'p3': pc(flat, 2.5)}}
        out['by_season'][se] = rows
    return out


def main():
    doc = {'built': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime()), 'since': SINCE, 'cities': {}}
    for cfg in K.MARKETS:
        try:
            truth, obs = inputs(cfg)
            doc['cities'][cfg['key']] = table(truth, obs)
            t = doc['cities'][cfg['key']]['by_season'].get('ALL', {})
            print('%-9s %4d days  after 13h: +1 %s  +2 %s | after 14h: +1 %s  +2 %s'
                  % (cfg['key'], doc['cities'][cfg['key']]['n_days'],
                     t.get('13', {}).get('p1'), t.get('13', {}).get('p2'), t.get('14', {}).get('p1'), t.get('14', {}).get('p2')))
        except Exception as e:
            print('%s: afternoon table failed (%s)' % (cfg['key'], e))
    if doc['cities']:
        with open(OUT, 'w') as fh:
            json.dump(doc, fh, indent=0, sort_keys=True)
        print('wrote', OUT)


if __name__ == '__main__':
    main()
