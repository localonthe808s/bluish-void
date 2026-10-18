#!/usr/bin/env python3
"""THE KELVIN WAVE AND THE WEST COAST'S WATER (user 2026-10-17: "can you track the kelvin wave from the el nino and coastal
flooding on the west coast"). One daily bake -> OUT/kelvin.json for the EL NIÑO view:

  eq     NOAA CoastWatch blended altimetry (noaacwBLENDEDsshDaily: Sentinel-3, CryoSat-2, Jason, SARAL; near real time,
         0.25 deg, daily) -- sea-level anomaly averaged 2 S to 2 N, 120 E to 80 W at 1 deg, the last 180 days. A downwelling
         Kelvin wave is a hump of raised sea (5-15 cm) running east at ~2.5 m/s; it shows as a band slanting right.
  coast  the same anomaly along the Americas' coast, 5 S to 50 N, at the sea cell nearest shore each degree of latitude: the
         wave turns north at Ecuador as a coastally trapped wave and raises the sea along Mexico and California weeks later.
  wave   the newest crest tracked across the basin: where it is, how fast it moved, when it reaches the coast at that pace.
  tao    TAO/TRITON 20 C isotherm depth on the equator (pmelTaoDyIso, daily, ~3 weeks behind): the thermocline the wave
         pushes down, the moorings' last 120 days.
  gauges NOAA CO-OPS tide gauges San Diego to Neah Bay: the daily mean of observed minus predicted water (the sea standing
         above the tide table -- El Nino's share, plus storms), the last 90 days; the highest observed water of the last week
         against the gauge's NOS minor flood level; the highest predicted tide of the next 30 days plus the current
         30-day anomaly against that level (the king tide this winter, with the extra water on top).

    python3 kelvin.py OUT
"""
import csv, datetime, io, json, math, os, sys, time, urllib.parse, urllib.request
OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
SSH = 'https://coastwatch.noaa.gov/erddap/griddap/noaacwBLENDEDsshDaily'
TAO = 'https://coastwatch.pfeg.noaa.gov/erddap/tabledap/pmelTaoDyIso'
CO = 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'
MD = 'https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/'
GAUGES = [('9410170', 'San Diego'), ('9410660', 'Los Angeles'), ('9410840', 'Santa Monica'), ('9412110', 'Port San Luis'),
          ('9413450', 'Monterey'), ('9414290', 'San Francisco'), ('9416841', 'Arena Cove'), ('9419750', 'Crescent City'),
          ('9432780', 'Charleston, OR'), ('9435380', 'South Beach, OR'), ('9439040', 'Astoria'), ('9443090', 'Neah Bay'),
          ('9447130', 'Seattle')]

def get(u, timeout=120, tries=6):
    for a in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluishvoid.com enso bake'}), timeout=timeout).read()
        except Exception as e:
            if a == tries - 1: raise
            time.sleep(4 * (a + 1))

def rows(u):
    r = list(csv.reader(io.StringIO(get(u).decode())))
    return r[2:]

today = datetime.datetime.utcnow().date()
t0 = (today - datetime.timedelta(days=185)).isoformat()
doc = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'src': {'ssh': SSH, 'tao': TAO, 'gauges': 'NOAA CO-OPS'}}

# ---- eq: two requests (the grid is -180..180), mean over the 2S-2N rows
def strip(lo0, lo1):
    q = 'sla[(%s):1:(last)][(-2):1:(2)][(%s):4:(%s)]' % (t0, lo0, lo1)
    return rows(SSH + '.csv?' + urllib.parse.quote(q, safe='[]():,'))
acc = {}
for lo0, lo1 in ((120.125, 179.875), (-179.875, -80.0)):
    for t, la, lo, v in strip(lo0, lo1):
        if v in ('', 'NaN'): continue
        lon = round(float(lo)); lon = lon + 360 if lon < 0 else lon
        k = (t[:10], lon); s = acc.setdefault(k, [0.0, 0]); s[0] += float(v); s[1] += 1
dates = sorted(set(k[0] for k in acc)); lons = sorted(set(k[1] for k in acc))
grid = [[(round(acc[(d, l)][0] / acc[(d, l)][1] * 100, 1) if (d, l) in acc else None) for l in lons] for d in dates]
# THE PULSES: each longitude against its own trailing 45 days. A strong El Nino stands the east Pacific 40-55 cm high for
# months, which saturates any color scale and hides the 1-2 month Kelvin pulses riding on it; this takes the standing tilt out.
def hpass(G, w=45):
    n2, m2 = len(G), len(G[0]) if G else 0; out = [[None] * m2 for _ in range(n2)]
    for j in range(m2):
        for d in range(n2):
            v = G[d][j]
            if v is None: continue
            win = [G[k][j] for k in range(max(0, d - w), d + 1) if G[k][j] is not None]
            if len(win) >= 10: out[d][j] = round(v - sum(win) / len(win), 1)
    return out
doc['eq'] = {'dates': dates, 'lons': lons, 'cm': grid, 'hp': hpass(grid), 'band': '2S-2N', 'hp_window': 45}
print('eq', len(dates), 'days x', len(lons), 'lons; newest', dates[-1])

# ---- coast: the sea cell nearest shore each degree, 5S..50N, read off the newest day, then its series
newest = dates[-1]
q = 'sla[(%s)][(-5):4:(50)][(-130):2:(-76)]' % newest
box = {}
for t, la, lo, v in rows(SSH + '.csv?' + urllib.parse.quote(q, safe='[]():,')):
    if v not in ('', 'NaN'): box.setdefault(round(float(la) * 4) / 4, []).append(float(lo))
cells = []
for la in sorted(box):
    if abs(la - round(la)) > 0.2: continue
    lo = max(box[la])                      # the easternmost sea cell = against the coast
    cells.append((la, lo))
coast = {'lats': [], 'lons': [], 'cm': []}
cdates = dates
for la, lo in cells:
    q = 'sla[(%s):1:(last)][(%s)][(%s)]' % (t0, la, lo)
    try: r = rows(SSH + '.csv?' + urllib.parse.quote(q, safe='[]():,'))
    except Exception as e: print('coast skip', la, e); continue
    m = {x[0][:10]: (None if x[3] in ('', 'NaN') else round(float(x[3]) * 100, 1)) for x in r}
    coast['lats'].append(la); coast['lons'].append(lo); coast['cm'].append([m.get(d) for d in cdates])
coast['cm'] = [list(x) for x in zip(*coast['cm'])] if coast['cm'] else []   # [date][lat]
coast['dates'] = cdates
coast['hp'] = hpass(coast['cm']) if coast['cm'] else []
doc['coast'] = coast
print('coast', len(coast['lats']), 'latitudes')

# ---- wave: the crest's track. For each of the last 70 days the longitude of the strongest anomaly east of 160E (smoothed
# 7 days); the newest run of eastward movement gives its position and speed, extrapolated to the coast (80 W = 280 E).
def smooth(col, k=3):
    out = []
    for i in range(len(col)):
        w = [col[j] for j in range(max(0, i - k), min(len(col), i + k + 1)) if col[j] is not None]
        out.append(sum(w) / len(w) if w else None)
    return out
HP = doc['eq']['hp']
# THE PULSE, FOLLOWED PEAK TO PEAK (the daily highest point jumped between pulses). At each longitude 180 E..80 W every 5 deg
# the dates where the 5-day-smoothed pulse field peaks above 3 cm; a pulse is followed east from its 180 E peak, each step
# taking the peak nearest where a 1.5-3.5 m/s wave would be. The newest pulse that left 180 E is reported: where its front
# is, its speed (fit over the steps), and when it reaches 80 W at that speed -- or when it got there.
def col(lon):
    j = lons.index(lon) if lon in lons else None
    return smooth([HP[d][j] for d in range(len(dates))], 2) if j is not None else None
D0 = datetime.date.fromisoformat(dates[0]); dn = lambda i: (D0 + datetime.timedelta(days=i))
peaks = {}
for lon in range(180, 281, 5):
    c = col(lon); pk = []
    if not c: continue
    for i in range(3, len(c) - 1):
        if c[i] is not None and c[i] > 3 and all(c[k] is None or c[i] >= c[k] for k in range(max(0, i - 6), min(len(c), i + 7))): pk.append((i, c[i]))
    peaks[lon] = pk
def follow(lon0, i0):
    path = [(lon0, i0)]; miss = 0
    for lon in range(lon0 + 5, 281, 5):
        prev_lon, prev_i = path[-1]; dk = (lon - prev_lon) * 111.32e3
        lo_i, hi_i = prev_i + dk / 4.5 / 86400 - 3, prev_i + dk / 1.2 / 86400 + 3
        cand = [p for p in peaks.get(lon, []) if lo_i <= p[0] <= hi_i]
        if not cand:
            miss += 1
            if miss > 1: break
            continue
        miss = 0
        path.append((lon, min(cand, key=lambda p: abs(p[0] - (prev_i + dk / 2.8 / 86400)))[0]))
    return path
wave = None; track = []
starts = sorted([(p[0], lon) for lon in range(180, 201, 5) for p in peaks.get(lon, []) if p[0] >= len(dates) - 110], reverse=True)
for i0, lon0 in starts:
    path = follow(lon0, i0)
    if len(path) < 5 or path[-1][0] - path[0][0] < 35: continue
    n2 = len(path); xs = [p[1] for p in path]; ys = [p[0] for p in path]
    mx, my = sum(xs) / n2, sum(ys) / n2; sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0: continue
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx            # degrees per day
    ms = slope * 111.32e3 / 86400
    if not (1.0 < ms < 4.5): continue
    front_lon, front_i = path[-1]
    arrived = front_lon >= 275
    eta_i = front_i + (280 - front_lon) / slope if not arrived else front_i
    wave = {'from': [dn(path[0][1]).isoformat(), path[0][0]], 'now': [dn(front_i).isoformat(), front_lon], 'ms': round(ms, 2),
            'cm': round(max(v for (ii, v) in peaks[front_lon] if ii == front_i), 1), 'arrived': arrived,
            'coast_eta': dn(round(eta_i)).isoformat(), 'days_to_coast': max(0, round(eta_i - (len(dates) - 1))),
            'path': [[p[0], dn(p[1]).isoformat()] for p in path]}
    track = wave['path']
    break
doc['wave'] = wave; doc['track'] = track
print('wave', wave)

# ---- tao: 20C isotherm depth on the equator
try:
    q = 'station,longitude,time,ISO_6&latitude>=-0.5&latitude<=0.5&time>=now-120days'
    tr = rows(TAO + '.csv?' + q.replace('>', '%3E').replace('<', '%3C'))
    by = {}
    for st, lo, t, v in tr:
        if v in ('', 'NaN'): continue
        lo = float(lo)
        if lo < 130 or lo > 280: continue
        by.setdefault(round(lo), {})[t[:10]] = round(float(v))
    tl = sorted(by); td = sorted(set(d for m in by.values() for d in m))
    doc['tao'] = {'lons': tl, 'dates': td, 'm': [[by[l].get(d) for l in tl] for d in td]}
    print('tao', len(tl), 'moorings,', len(td), 'days, newest', td[-1] if td else None)
except Exception as e:
    print('tao failed', e); doc['tao'] = None

# ---- gauges
def co(params):
    return json.loads(get(CO + '?' + urllib.parse.urlencode(params)))
gs = []
for sid, nm in GAUGES:
    g = {'id': sid, 'name': nm}
    try:
        meta = json.loads(get(MD + sid + '.json'))['stations'][0]; g['lat'] = meta['lat']; g['lon'] = meta['lng']
        fl = json.loads(get(MD + sid + '/floodlevels.json'))
        # the flood levels are in feet on the station datum (STND); the gauges' levels below are on MHHW -- convert
        dt = {d['name']: d['value'] for d in json.loads(get(MD + sid + '/datums.json')).get('datums', [])}
        mn = fl.get('nos_minor') if fl.get('nos_minor') is not None else fl.get('nws_minor')
        g['minor_mhhw'] = round(mn - dt['MHHW'], 2) if (mn is not None and dt.get('MHHW') is not None) else None
        b = (today - datetime.timedelta(days=90)).strftime('%Y%m%d'); e = today.strftime('%Y%m%d')
        common = {'station': sid, 'datum': 'MHHW', 'units': 'english', 'time_zone': 'gmt', 'format': 'json', 'application': 'bluishvoid'}
        obs = co(dict(common, product='hourly_height', begin_date=b, end_date=e)).get('data', [])
        # the verified hourly series runs ~3 weeks behind: the preliminary 6-minute levels fill the last 30 days, on the hour
        b30 = (today - datetime.timedelta(days=30)).strftime('%Y%m%d')
        try:
            wl = co(dict(common, product='water_level', begin_date=b30, end_date=e)).get('data', [])
            have = set(o['t'] for o in obs)
            obs += [o for o in wl if o['t'].endswith(':00') and o['t'] not in have]
            obs.sort(key=lambda o: o['t'])
            g['wl_newest'] = wl[-1]['t'] if wl else None
            wk6 = [o for o in wl if o.get('v') not in (None, '') and o['t'] >= (today - datetime.timedelta(days=7)).isoformat()]
            if wk6: top6 = max(wk6, key=lambda o: float(o['v'])); g['week_max'] = [top6['t'], round(float(top6['v']), 2)]
        except Exception as e3:
            print('gauge', nm, 'no preliminary levels', e3)
        prd = co(dict(common, product='predictions', interval='h', begin_date=b, end_date=e)).get('predictions', [])
        pm = {p['t']: float(p['v']) for p in prd if p.get('v') not in (None, '')}
        day = {}
        for o in obs:
            if o.get('v') in (None, '') or o['t'] not in pm: continue
            s = day.setdefault(o['t'][:10], [0.0, 0]); s[0] += float(o['v']) - pm[o['t']]; s[1] += 1
        g['days'] = sorted(day); g['anom_ft'] = [round(day[d][0] / day[d][1], 2) for d in g['days']]
        last30 = g['anom_ft'][-30:]; g['anom30_ft'] = round(sum(last30) / len(last30), 2) if last30 else None
        if 'week_max' not in g:
            wk = [o for o in obs[-24 * 7:] if o.get('v') not in (None, '')]
            if wk: top = max(wk, key=lambda o: float(o['v'])); g['week_max'] = [top['t'], round(float(top['v']), 2)]
        fut = co(dict(common, product='predictions', interval='hilo', begin_date=e, end_date=(today + datetime.timedelta(days=30)).strftime('%Y%m%d'))).get('predictions', [])
        hi = [p for p in fut if p.get('type') == 'H']
        if hi:
            k = max(hi, key=lambda p: float(p['v'])); g['next_king'] = [k['t'], round(float(k['v']), 2)]
            if g.get('anom30_ft') is not None: g['king_plus'] = round(float(k['v']) + g['anom30_ft'], 2)
        print('gauge', nm, 'anom30', g.get('anom30_ft'), 'minor', mn, 'king', g.get('next_king'))
    except Exception as e2:
        print('gauge', nm, 'failed', e2)
    gs.append(g)
doc['gauges'] = gs
json.dump(doc, open(os.path.join(OUT, 'kelvin.json'), 'w'), separators=(',', ':'))
print('wrote', os.path.getsize(os.path.join(OUT, 'kelvin.json')), 'bytes')
