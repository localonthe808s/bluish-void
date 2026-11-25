"""SECURITY ESTIMATES (user 2026-11-25: "build the TSA estimates for when theyre not live").

From parse.py's rows (8 weeks of TSA hourly checkpoint counts): for every airport and every checkpoint, the mean people screened in each
weekday-hour (168 numbers, Monday 00:00 first, the airport's local clock -- TSA reports local hours). The page turns that into a RANGE of
minutes, never one number: this hour's share of the checkpoint's busiest hour of the week, times a typical peak wait for an airport that
busy (8 min for a quiet field, up to 23 at the largest hubs, scaled to live readings). It is a shape from counts, not a reading, and the card says ESTIMATE.
Positions and time zones from OurAirports (public domain) + timezonefinder.

    python3 _tsabake/bake.py   -> _tsabake/out/estimates_v1.json  (-> cdn tsa/estimates_v1.json)
"""
import csv, datetime, glob, json, math, os, collections
from timezonefinder import TimezoneFinder

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, 'out')
rows = []
weeks = []
for f in sorted(glob.glob(os.path.join(OUT, 'rows_*.json'))):
    r = json.load(open(f)); rows += r; weeks.append(min(x[0] for x in r))
days = sorted(set(r[0] for r in rows))
# weekday-hour sums and how many of each weekday the data holds
A = collections.defaultdict(lambda: [0.0] * 168); Cp = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0] * 168))
nday = collections.Counter(datetime.date.fromisoformat(d).weekday() for d in days)
for d, h, a, cp, n in rows:
    i = datetime.date.fromisoformat(d).weekday() * 24 + h
    A[a][i] += n; Cp[a][cp][i] += n
mean = lambda v: [round(v[i] / max(1, nday[i // 24])) for i in range(168)]
ap = {}
for row in csv.DictReader(open(os.path.join(HERE, 'ref', 'airports.csv'), encoding='utf-8')):
    c = row['iata_code']
    if c and c in A and (c not in ap or row['type'] in ('large_airport', 'medium_airport')):
        ap[c] = (row['name'], float(row['latitude_deg']), float(row['longitude_deg']), row['municipality'], row['iso_region'])
tf = TimezoneFinder(); out = {}
for a, v in A.items():
    if a not in ap: continue
    m = mean(v); pk = max(m)
    if pk < 20: continue                       # too few people screened to say anything
    name, la, lo, city, reg = ap[a]
    P = round(8 + 15 * min(1.0, math.log10(max(1, pk) / 100) / math.log10(40)))   # peak-hour 100 -> 8 min, 4,000+ -> 23 (fitted 11-25 to 16 airports' live waits: was a third high)
    cps = {}
    for cp, vv in Cp[a].items():
        mm = mean(vv)
        if max(mm) >= max(15, pk * 0.06): cps[cp] = mm
    out[a] = {'n': name, 'c': city, 'r': reg.replace('US-', ''), 'll': [round(la, 4), round(lo, 4)], 'tz': tf.timezone_at(lat=la, lng=lo) or 'America/New_York', 'P': P,
              'a': m, 'k': cps if len(cps) > 1 else {}}
json.dump({'from': days[0], 'to': days[-1], 'weeks': len(weeks), 'note': 'mean people screened per weekday-hour (Mon 00 first, local time); TSA FOIA throughput', 'ap': out},
          open(os.path.join(OUT, 'estimates_v1.json'), 'w'), separators=(',', ':'))
print(len(out), 'airports', days[0], days[-1], os.path.getsize(os.path.join(OUT, 'estimates_v1.json')) // 1024, 'KB')
