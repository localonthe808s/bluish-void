#!/usr/bin/env python3
"""DID THE SKY MAKE A RAINBOW? (user 2026-11-07: "how can you track whether a rainbow has occurred or not?" -> "do 1 but every 5
minutes feels excessive for something we havent been able to confirm yet this year").

Once a day, after sunset, this looks back over the day's low-sun hours in 10-minute steps and asks the three things a rainbow needs,
each from an archive that records what really happened (not a forecast):
  1. the sun low enough: altitude 0.5-42 deg (a primary bow's top sits 42 deg from the antisolar point);
  2. rain on the far side: radar echoes >= 20 dBZ covering >= 6% of a 3-40 km wedge (+-35 deg) toward the antisolar azimuth --
     IEM's 5-minute US NEXRAD mosaic (n0q, 0.005 deg, dBZ = value * 0.5 - 32.5);
  3. the sun out: no rain within 12 km toward the sun, and a sun-side airport reporting no broken or overcast deck below 8,000 ft
     (IEM's archive of the METARs).
A step meeting all three is a "rainbow-capable minute"; the day's row lists them. It cannot see a bow, only that the sky could make one
for a person in the city -- the user's sightings and (later) east-facing webcams are the check on it.

    python3 rainbow_truth.py [YYYY-MM-DD] [OUT.jsonl]      (default: today in New York)
"""
import datetime as dt, io, json, math, os, sys, urllib.request
from PIL import Image

UA = {'User-Agent': 'bluishvoid.com rainbow check'}
PLACE = {'name': 'New York', 'lat': 40.7789, 'lon': -73.9692, 'tz_off': None}
STATIONS = {'EWR': (40.6925, -74.1687), 'NYC': (40.7789, -73.9692), 'LGA': (40.7794, -73.8803), 'JFK': (40.6398, -73.7789)}

def get(u, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()

def sun(t, lat, lon):
    """altitude, azimuth (deg) of the sun at UTC datetime t -- NOAA's approximation, good to ~0.1 deg"""
    n = (t - dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)).total_seconds() / 86400.0
    L = (280.46 + 0.9856474 * n) % 360; g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)); eps = math.radians(23.439 - 4e-7 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam)); dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24; ha = math.radians(gmst * 15 + lon) - ra
    la = math.radians(lat)
    alt = math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.sin(ha), math.tan(dec) * math.cos(la) - math.sin(la) * math.cos(ha))
    return math.degrees(alt), (math.degrees(az) + 360) % 360

def dest(lat, lon, az, km):
    d = km / 6371.0; a = math.radians(az); la = math.radians(lat); lo = math.radians(lon)
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(a))
    lo2 = lo + math.atan2(math.sin(a) * math.sin(d) * math.cos(la), math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)

def radar(t):
    """the n0q mosaic nearest t (5-minute files), as a function lat,lon -> dBZ (None off the grid)"""
    t5 = t.replace(minute=t.minute - t.minute % 5, second=0)
    u = 'https://mesonet.agron.iastate.edu/archive/data/%s/GIS/uscomp/n0q_%s.png' % (t5.strftime('%Y/%m/%d'), t5.strftime('%Y%m%d%H%M'))
    im = Image.open(io.BytesIO(get(u))); W, H = im.size; px = im.load()
    def dbz(lat, lon):
        x = int((lon + 126.0) / 0.005); y = int((50.0 - lat) / 0.005)
        if x < 0 or y < 0 or x >= W or y >= H: return None
        v = px[x, y]; return None if v == 0 else v * 0.5 - 32.5
    return dbz

def metars(day0, day1):
    u = ('https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?' + '&'.join('station=' + s for s in STATIONS) +
         '&data=skyc1&data=skyl1&data=skyc2&data=skyl2&data=skyc3&data=skyl3&year1=%d&month1=%d&day1=%d&hour1=0&year2=%d&month2=%d&day2=%d&hour2=23'
         % (day0.year, day0.month, day0.day, day1.year, day1.month, day1.day) + '&tz=Etc/UTC&format=onlycomma&latlon=no&report_type=3&report_type=4')
    rows = []
    for ln in get(u).decode().splitlines()[1:]:
        c = ln.split(',')
        try: t = dt.datetime.strptime(c[1], '%Y-%m-%d %H:%M').replace(tzinfo=dt.timezone.utc)
        except Exception: continue
        low = 99999
        for i in (2, 4, 6):
            if c[i] in ('BKN', 'OVC', 'VV'):
                try: low = min(low, float(c[i + 1]))
                except Exception: low = min(low, 0)
        rows.append((c[0], t, low))
    return rows

def sun_out(rows, t, az):
    """a station on the sun's side (bearing from the city within 70 deg of the sun) reporting no BKN/OVC below 8,000 ft
    in its latest report of the hour before t"""
    best = {}
    for st, rt, low in rows:
        if rt <= t and (t - rt).total_seconds() <= 75 * 60 and (st not in best or rt > best[st][0]): best[st] = (rt, low)
    for st, (rt, low) in best.items():
        la, lo = STATIONS[st]
        b = math.degrees(math.atan2((lo - PLACE['lon']) * math.cos(math.radians(la)), la - PLACE['lat'])) % 360
        side = abs((b - az + 180) % 360 - 180) <= 70 or st == 'NYC'
        if side and low >= 8000: return st
    return None

def day_check(date):
    # the local day in UTC (New York: UTC-5 / -4); the sun's low hours fall inside 10:00-23:59 UTC + 00:00-01:30 next day
    t0 = dt.datetime(date.year, date.month, date.day, 10, 0, tzinfo=dt.timezone.utc); t1 = t0 + dt.timedelta(hours=16)
    rows = metars(t0, t1); steps = []; t = t0; frames = 0
    while t <= t1:
        alt, az = sun(t, PLACE['lat'], PLACE['lon'])
        if 0.5 <= alt <= 42:
            st = sun_out(rows, t, az)
            if st:
                try: f = radar(t); frames += 1
                except Exception as e: f = None; print('radar', t, e)
                if f:
                    anti = (az + 180) % 360; wet = tot = 0
                    for km in range(3, 41, 3):
                        for da in range(-35, 36, 7):
                            v = f(*dest(PLACE['lat'], PLACE['lon'], anti + da, km)); tot += 1
                            if v is not None and v >= 20: wet += 1
                    sunside = [f(*dest(PLACE['lat'], PLACE['lon'], az, km)) for km in range(0, 13, 2)]
                    clear = all(v is None or v < 15 for v in sunside)
                    frac = wet / tot if tot else 0
                    if frac >= 0.06 and clear:
                        steps.append({'utc': t.strftime('%H:%MZ'), 'sun_alt': round(alt, 1), 'sun_az': round(az), 'rain_frac': round(frac, 3), 'sun_out_by': st})
        t += dt.timedelta(minutes=10)
    return {'city': 'nyc', 'date': date.isoformat(), 'rainbow_capable': bool(steps), 'minutes': len(steps) * 10, 'steps': steps, 'radar_frames': frames}

if __name__ == '__main__':
    import zoneinfo
    d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.datetime.now(zoneinfo.ZoneInfo('America/New_York')).date()
    r = day_check(d); print(json.dumps(r))
    if len(sys.argv) > 2:
        with open(sys.argv[2], 'a') as fo: fo.write(json.dumps(r) + '\n')
