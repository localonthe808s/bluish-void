"""Cache TWC observation history per (station, day) so the scoring below is
cheap to re-run with different windows."""
import importlib.util, datetime, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("kd", "/Users/vvvaa/bluish-void/_kalshi/kalshi_daily.py")
kd = importlib.util.module_from_spec(spec); spec.loader.exec_module(kd)

CACHE = os.path.join(HERE, 'twc_hist.json')
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
today = datetime.date(2026, 9, 5)
NDAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 45

got = new = fail = 0
for cfg in kd.MARKETS:
    icao = cfg.get('icao') or ('K' + cfg['station'])
    for i in range(1, NDAYS + 1):
        d = today - datetime.timedelta(days=i)
        key = '%s|%s' % (icao, d.isoformat())
        if key in cache:
            got += 1; continue
        try:
            j = kd.get_json('https://api.weather.com/v1/location/%s:9:US/observations/'
                            'historical.json?apiKey=%s&units=e&startDate=%s'
                            % (icao, kd.TWC_KEY, d.strftime('%Y%m%d')), timeout=45)
            rows = []
            for o in (j or {}).get('observations') or []:
                t, v = o.get('temp'), o.get('valid_time_gmt')
                if isinstance(t, (int, float)) and isinstance(v, (int, float)):
                    rows.append([int(v), float(t)])
            cache[key] = rows; new += 1
        except Exception as e:
            cache[key] = None; fail += 1
    json.dump(cache, open(CACHE, 'w'))
    print('  %s cached (%d new, %d already, %d failed)' % (icao, new, got, fail))
json.dump(cache, open(CACHE, 'w'))
print('total keys:', len(cache))
