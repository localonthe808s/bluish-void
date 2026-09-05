"""Score candidate daily-max definitions against the bracket that actually PAID.

Candidates:
  IEM      raw IEM daily max_temp_f (today's archive, i.e. post-revision)
  TWCcal   max of TWC's own obs over the local CALENDAR day
  TWCclim  same, but over the NWS CLIMATE day (climate_day_start onward,
           i.e. dropping the midnight hour under DST)
"""
import importlib.util, datetime, json, os, collections
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("kd", "/Users/vvvaa/bluish-void/_kalshi/kalshi_daily.py")
kd = importlib.util.module_from_spec(spec); spec.loader.exec_module(kd)
cache = json.load(open(os.path.join(HERE, 'twc_hist.json')))
today = datetime.date(2026, 9, 5)

def twc_max(icao, d, tz, h0):
    rows = cache.get('%s|%s' % (icao, d.isoformat()))
    if not rows: return None, None
    z = ZoneInfo(tz); cal = []; clim = []
    for v, t in rows:
        lt = datetime.datetime.fromtimestamp(v, datetime.timezone.utc).astimezone(z)
        if lt.date() != d: continue
        cal.append(t)
        if lt.hour >= h0: clim.append(t)
    return (max(cal) if cal else None), (max(clim) if clim else None)

def inb(v, lo, hi):
    if v is None: return None
    return (lo is None or v >= lo - .01) and (hi is None or v <= hi + .01)

tot = collections.Counter(); rows_out = []
for cfg in kd.MARKETS:
    icao = cfg.get('icao') or ('K' + cfg['station'])
    settled = kd.fetch_settled(cfg, limit=400)
    days = [today - datetime.timedelta(days=i) for i in range(1, 46)]
    iem = kd.daily_series(cfg, days[-1], today)
    n = collections.Counter()
    for d in reversed(days):
        ev = settled.get(kd.event_ticker(cfg, d))
        if not ev: continue
        win = [r for r in ev if r['yes']]
        if not win: continue
        lo, hi = win[0]['lo'], win[0]['hi']
        h0 = kd.climate_day_start(cfg, d)
        cal, clim = twc_max(icao, d, cfg['tz'], h0)
        i = iem.get(d.isoformat())
        res = {'IEM': inb(i, lo, hi), 'TWCcal': inb(cal, lo, hi), 'TWCclim': inb(clim, lo, hi)}
        n['n'] += 1
        for k, v in res.items():
            if v: n[k] += 1
            elif v is None: n[k + '_na'] += 1
        rows_out.append((cfg['city'], d.isoformat(), i, cal, clim, win[0]['label'], res))
    print("  %-13s n=%-3d  IEM %2d   TWCcal %2d   TWCclim %2d" %
          (cfg['city'], n['n'], n['IEM'], n['TWCcal'], n['TWCclim']))
    for k in ('n','IEM','TWCcal','TWCclim'): tot[k] += n[k]
print("\n  %-13s n=%-3d  IEM %2d   TWCcal %2d   TWCclim %2d" %
      ('ALL', tot['n'], tot['IEM'], tot['TWCcal'], tot['TWCclim']))
print("  %-13s        IEM %4.1f%% TWCcal %4.1f%% TWCclim %4.1f%%" % ('',
      100*tot['IEM']/tot['n'], 100*tot['TWCcal']/tot['n'], 100*tot['TWCclim']/tot['n']))
json.dump([[c,d,i,a,b,l,{k:(None if v is None else bool(v)) for k,v in r.items()}]
           for c,d,i,a,b,l,r in rows_out], open(os.path.join(HERE,'scored.json'),'w'))
