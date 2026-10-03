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


def _download(url, ua, timeout):
    """IEM SAYS NO SOMETIMES (2026-10-02): the nightly refit runs eight studies back to back against the Iowa
    Environmental Mesonet, which answers 429 'too many requests' or 503 'server over capacity'. Las Vegas's daily
    file hit that two nights running and the city silently dropped out of kernel.json and dayahead.json. Wait and
    retry the busy answers; anything else raises at once."""
    import re, urllib.error
    # ONE YEAR AT A TIME: a multi-year daily.py request is the one IEM refuses with 503 'server over capacity'
    # (a single year answers in 0.4 s), so split it by year, pause between the pieces, and join them.
    m = re.search(r'year1=(\d{4})&month1=(\d+)&day1=(\d+)&year2=(\d{4})&month2=(\d+)&day2=(\d+)', url)
    if 'daily.py' in url and m and m.group(1) != m.group(4):
        y1, y2, parts = int(m.group(1)), int(m.group(4)), []
        for y in range(y1, y2 + 1):
            a = (m.group(2), m.group(3)) if y == y1 else ('1', '1')
            b = (m.group(5), m.group(6)) if y == y2 else ('12', '31')
            u = url.replace(m.group(0), 'year1=%d&month1=%s&day1=%s&year2=%d&month2=%s&day2=%s' % (y, a[0], a[1], y, b[0], b[1]))
            txt = _download(u, ua, timeout).decode('utf-8', 'replace').splitlines(True)
            parts.extend(txt if not parts else txt[1:])
            time.sleep(3)
        return ''.join(parts).encode('utf-8')
    for i, wait in enumerate((0, 20, 60, 120)):
        if wait: time.sleep(wait)
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': ua}), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == 3: raise
            print('  %s busy (%d), retrying in %ds' % (url.split('/')[2], e.code, (20, 60, 120)[i]), flush=True)


def fetch(name, url):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 20 * 3600:
        try:
            data = _download(url, 'bluishvoid.com afternoon study', 240)
        except Exception as e:
            if not os.path.exists(p):
                raise
            print('  %s: download failed (%s), using the cached copy' % (name, e), flush=True)   # a day-old copy beats dropping the city
            return io.open(p, encoding='utf-8', errors='replace').read()
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
