#!/usr/bin/env python3
"""WHERE THE WATER WENT (user 2026-10-04: "do both" -- newer gravity than the 2013 SVS video).

GRACE (2002-17) and GRACE-FO (2018-) weigh the planet every month; the month-to-month change in gravity is almost
all water moving -- ice sheets shedding, aquifers draining, wet and dry years. UT Austin's Center for Space Research
publishes its RL06.3 mascon solution as one public NetCDF (no login; NASA open data policy), updated each month a
couple of months behind. This bakes, for EARTH SYSTEMS -> GRAVITY:

  trend.webp    the change per year over the whole record (cm of water a year), the headline picture
  y2003.webp .. one per complete year, the yearly mean against the 2004-2009 average, for the loop
  last12.webp   the newest twelve months
  water.json    the index, plus Greenland's and Antarctica's mass change (Gt/yr) as a check on the arithmetic

Ocean pixels are drawn as the site's navy: the story is land and ice. Writes to OUT (default _grace_out); the
workflow uploads that folder to R2 at earth/gravity/water/.
usage: grace_bake.py [OUT] [local.nc]
"""
import datetime, json, os, sys, urllib.request
import numpy as np
import netCDF4
from PIL import Image, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else '_grace_out'
SRC = 'https://download.csr.utexas.edu/outgoing/grace/RL0603_mascons/'
NC = SRC + 'CSR_GRACE_GRACE-FO_RL0603_Mascons_all-corrections.nc'
LAND = SRC + 'CSR_GRACE_GRACE-FO_RL06_Mascons_v02_LandMask.nc'
UA = {'User-Agent': 'bluishvoid.com GRACE bake (contact via site)'}
os.makedirs(OUT, exist_ok=True)


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(path, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)
    return path


nc = sys.argv[2] if len(sys.argv) > 2 else fetch(NC, os.path.join(OUT, '_csr.nc'))
lm = fetch(LAND, os.path.join(OUT, '_land.nc'))

d = netCDF4.Dataset(nc)
lwe = np.asarray(d.variables['lwe_thickness'][:], dtype=np.float32)        # (t, 720 lat S->N, 1440 lon 0->360), cm
days = np.asarray(d.variables['time'][:], dtype=np.float64)
dates = [datetime.datetime(2002, 1, 1) + datetime.timedelta(days=float(x)) for x in days]
yr = np.array([x.year + (x.timetuple().tm_yday - 0.5) / 365.25 for x in dates])
lat = np.asarray(d.variables['lat'][:]); lon = np.asarray(d.variables['lon'][:])
L = netCDF4.Dataset(lm); lk = [k for k in L.variables if L.variables[k].ndim == 2][0]
land = np.asarray(L.variables[lk][:]) > 0.5
if land.shape != lwe.shape[1:]:
    raise SystemExit('land mask %s does not match the grid %s' % (land.shape, lwe.shape[1:]))

# --- per-pixel trend: mean + slope + annual + semiannual, least squares over the whole record
A = np.stack([np.ones_like(yr), yr - yr.mean(), np.sin(2 * np.pi * yr), np.cos(2 * np.pi * yr), np.sin(4 * np.pi * yr), np.cos(4 * np.pi * yr)], 1)
P = np.linalg.pinv(A)                                                       # (6, t)
Y = lwe.reshape(len(yr), -1)
trend = (P[1] @ Y).reshape(lwe.shape[1:])                                   # cm / yr

# --- regional mass: cm of water over each cell's area -> Gt (CSR converted with 1025 kg/m^3)
R = 6378136.3
cell = (np.radians(0.25) * R) ** 2 * np.cos(np.radians(lat))[:, None] * np.ones((1, len(lon)))
def region(mask):
    s = (lwe * (cell * mask)[None]).reshape(len(yr), -1).sum(1) * 0.01 * 1025 / 1e12   # Gt, against 2004-09
    k = P @ s
    return {'gt_per_yr': round(float(k[1]), 1), 'series': [[dates[i].strftime('%Y-%m'), round(float(s[i]), 1)] for i in range(len(s))]}
lon180 = np.where(lon > 180, lon - 360, lon)
GL = land & (lat[:, None] > 59) & (lon180[None, :] > -75) & (lon180[None, :] < -10)
AN = land & (lat[:, None] < -60)
greenland, antarctica = region(GL), region(AN)

# --- drawing
NAVY = np.array([11, 16, 32], np.float32)
STOPS = [(-1.0, (127, 39, 4)), (-0.55, (217, 95, 2)), (-0.2, (253, 184, 99)), (0.0, (238, 236, 228)), (0.2, (146, 197, 222)), (0.55, (33, 102, 172)), (1.0, (8, 40, 100))]
def cmap(v):
    v = np.clip(v, -1, 1); out = np.zeros(v.shape + (3,), np.float32)
    for (a, ca), (b, cb) in zip(STOPS[:-1], STOPS[1:]):
        m = (v >= a) & (v <= b); f = ((v - a) / (b - a))[m][:, None]
        out[m] = np.array(ca, np.float32) * (1 - f) + np.array(cb, np.float32) * f
    return out
coast = np.zeros_like(land)
coast[1:, :] |= land[1:, :] != land[:-1, :]; coast[:, 1:] |= land[:, 1:] != land[:, :-1]
def render(field, scale, name, gamma=0.5):
    v = np.sign(field) * (np.abs(field) / scale) ** gamma                   # a power stretch: small signals show
    rgb = cmap(v); rgb[~land] = NAVY; rgb[coast] = rgb[coast] * 0.4 + np.array([200, 205, 220], np.float32) * 0.6   # a pale coastline
    img = rgb[::-1]                                                         # north up
    img = np.roll(img, img.shape[1] // 2, axis=1)                           # 0..360 -> -180..180
    Image.fromarray(img.astype(np.uint8)).save(os.path.join(OUT, name), 'WEBP', quality=84, method=6)
    return name

ANOM = 50.0      # cm, the yearly maps' colour range
TREND = 12.0     # cm/yr. With a square root at 6, Greenland's interior (+1..3 cm/yr of snow) read as a strong blue beside
                 # margins losing 30-45 cm/yr -- "Greenland gaining" when it loses ~290 Gt/yr. 12 and a 0.6 power keep +2 pale.
out = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'source': 'CSR GRACE/GRACE-FO RL06.3 mascons',
       'first': dates[0].strftime('%Y-%m'), 'last': dates[-1].strftime('%Y-%m'), 'months': len(dates),
       'baseline': '2004-2009', 'scale': {'anom_cm': ANOM, 'trend_cm_yr': TREND},
       'trend': render(trend, TREND, 'trend.webp', 0.6), 'frames': [],
       'greenland': greenland, 'antarctica': antarctica}
years = sorted(set(x.year for x in dates))
for y in years:
    ix = [i for i, x in enumerate(dates) if x.year == y]
    if len(ix) >= 8:
        out['frames'].append({'label': str(y), 'img': render(lwe[ix].mean(0), ANOM, 'y%d.webp' % y), 'months': len(ix)})
tail = [i for i, x in enumerate(dates) if (dates[-1] - x).days < 365]
out['last12'] = {'label': dates[tail[0]].strftime('%b %Y').upper() + ' – ' + dates[-1].strftime('%b %Y').upper(), 'img': render(lwe[tail].mean(0), ANOM, 'last12.webp')}
json.dump(out, open(os.path.join(OUT, 'water.json'), 'w'), separators=(',', ':'))
print('months', len(dates), dates[0].date(), '->', dates[-1].date(), '| frames', len(out['frames']),
      '| Greenland', greenland['gt_per_yr'], 'Gt/yr | Antarctica', antarctica['gt_per_yr'], 'Gt/yr')
