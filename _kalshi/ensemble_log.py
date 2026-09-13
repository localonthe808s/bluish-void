#!/usr/bin/env python3
"""THE SPREAD LOG (2026-09-13, idea 3). Nightly, per city, one row per date:
two spreads nobody has archived for these stations, kept so they can be
graded in a few months against the settlement --

  * ecmwf: the ECMWF ensemble's (51 members, Open-Meteo ensemble API) daily
    max for the date -- mean, sd, 10/90th, from the run in hand at ~08 UTC
    (the 00Z cycle, so a night-before call);
  * nbm: the NBM station bulletin's MaxT and its own sd (xnd) for the date,
    the last run issued by 02Z, via the Iowa State MOS archive; and
  * ours: the court's corrected five-model mean and spread for the same
    date, so the three can be scored on the same days.

Why. The GFS ensemble (31 members) was judged underdispersive on 5 days and
dropped; nothing said whether the ECMWF's is. On 620 New York days the NBM's
xnd predicts ITS OWN miss strongly (1.3 degF at xnd 1, 4.2 at xnd 4+) and
ours only weakly (day-ahead 1.6 at 2, 1.9 at 3+); with the ECMWF spread
beside it and a few months of rows the question can be settled here rather
than argued. The grade is the actual (IEM daily max) joined later by date.

Appends to _kalshi/ensemble_log.json {city: {date: row}}; a date already
logged is left alone. Offline: python3 _kalshi/ensemble_log.py
"""
import csv, io, json, os, sys, time, datetime, statistics, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kalshi_daily as K                                   # noqa: E402
OUT = os.path.join(HERE, 'ensemble_log.json')
MODELS = ['ncep_nbm_conus', 'ecmwf_ifs025', 'gfs_seamless', 'icon_seamless', 'gem_seamless']


def get(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': 'bluishvoid.com spread log'})
    return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'replace')


def ecmwf(cfg, date):
    u = ('https://ensemble-api.open-meteo.com/v1/ensemble?latitude=%.4f&longitude=%.4f&hourly=temperature_2m'
         '&models=ecmwf_ifs025&temperature_unit=fahrenheit&timezone=%s&start_date=%s&end_date=%s'
         % (cfg['lat'], cfg['lon'], urllib.parse.quote(cfg['tz']), date, date))
    h = json.loads(get(u)).get('hourly') or {}
    peaks = []
    for k, v in h.items():
        if k.startswith('temperature_2m') and isinstance(v, list):
            vals = [x for x in v if x is not None]
            if len(vals) >= 12:
                peaks.append(max(vals))
    if len(peaks) < 5:
        return None
    peaks.sort()
    return {'n': len(peaks), 'mean': round(statistics.mean(peaks), 2), 'sd': round(statistics.pstdev(peaks), 2),
            'p10': round(peaks[int(0.1 * (len(peaks) - 1))], 1), 'p90': round(peaks[int(0.9 * (len(peaks) - 1))], 1),
            'min': round(peaks[0], 1), 'max': round(peaks[-1], 1)}


def nbm(cfg, date):
    icao = cfg.get('icao') or ('K' + cfg['station'])
    d0 = datetime.date.fromisoformat(date)
    u = ('https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py?station=%s&model=NBS&sts=%sT00:00Z&ets=%sT03:00Z&format=csv'
         % (icao, (d0 - datetime.timedelta(days=1)).isoformat(), date))
    best = None
    for r in csv.DictReader(io.StringIO(get(u))):
        if r.get('txn') in (None, '', 'M'):
            continue
        ft = r['ftime']
        # the 00Z row of the next day carries the date's daytime max
        if ft[:10] != (d0 + datetime.timedelta(days=1)).isoformat() or ft[11:13] != '00':
            continue
        rt = r['runtime']
        if rt > date + ' 02:00:00':
            continue
        if best is None or rt > best['run']:
            best = {'run': rt, 'max': float(r['txn']), 'sd': float(r['xnd']) if r.get('xnd') not in (None, '', 'M') else None}
    return best


def ours(cfg, date, court):
    u = ('https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f&hourly=temperature_2m&models=%s'
         '&temperature_unit=fahrenheit&timezone=%s&start_date=%s&end_date=%s'
         % (cfg['lat'], cfg['lon'], ','.join(MODELS), urllib.parse.quote(cfg['tz']), date, date))
    h = json.loads(get(u)).get('hourly') or {}
    bias = (court or {}).get('bias') or {}
    corr = {}
    for m in MODELS:
        v = [x for x in (h.get('temperature_2m_' + m) or []) if x is not None]
        if len(v) >= 12 and m in bias:
            corr[m] = round(max(v) + bias[m], 2)
    if not corr:
        return None
    return {'mean': round(statistics.mean(corr.values()), 2), 'spread': round(max(corr.values()) - min(corr.values()), 2), 'models': corr}


def main():
    try:
        log = json.load(open(OUT))
    except Exception:
        log = {}
    try:
        courts = json.load(open(os.path.join(HERE, 'dayahead.json'))).get('cities') or {}
    except Exception:
        courts = {}
    date = datetime.date.today().isoformat()
    for cfg in K.MARKETS:
        rows = log.setdefault(cfg['key'], {})
        if date in rows:
            print('%s %s: already logged' % (cfg['key'], date))
            continue
        row = {'logged': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}
        for name, fn in (('ecmwf', ecmwf), ('nbm', nbm)):
            try:
                row[name] = fn(cfg, date)
            except Exception as e:
                row[name] = None
                print('%s %s: %s failed (%s)' % (cfg['key'], date, name, e))
        try:
            row['ours'] = ours(cfg, date, courts.get(cfg['key']))
        except Exception as e:
            row['ours'] = None
            print('%s %s: ours failed (%s)' % (cfg['key'], date, e))
        rows[date] = row
        e, n, o = row.get('ecmwf') or {}, row.get('nbm') or {}, row.get('ours') or {}
        print('%-9s %s  ecmwf %s sd %s (%s members)  nbm %s sd %s  ours %s spread %s'
              % (cfg['key'], date, e.get('mean'), e.get('sd'), e.get('n'), n.get('max'), n.get('sd'), o.get('mean'), o.get('spread')))
    with open(OUT, 'w') as fh:
        json.dump(log, fh, indent=0, sort_keys=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
