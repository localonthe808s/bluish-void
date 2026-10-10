#!/usr/bin/env python3
"""THE ICE (EARTH SYSTEMS), baked daily (user 2026-09-24: "I want to eventually track glacial loss and polar ice
caps in there" ... "do all the ice stuff").

None of these sources can be read by the page directly (no CORS, or a 2 MB file for one number), so a daily
Action runs this and commits _maplab/ice.json.

  SEA ICE     NSIDC Sea Ice Index G02135 v4.0 daily extent, both hemispheres, 1978 -> ~2 days ago, and its
              1981-2010 climatology (median + 10th/90th percentile by day of year). Public domain (NOAA/NSIDC).
  GREENLAND   DMI Polar Portal surface mass balance, one file per season (Sep 1 -> Aug 31) since 2018, the
              current season's daily running total, and the daily melt-area share. Credit DMI/Polar Portal.
              SURFACE balance only (snow in, melt out); icebergs and melting from below are not in it.
  ICE SHEETS  NASA's GRACE / GRACE-FO net loss rates, 2002-2025, as NASA states them (no open data file since
              climate.nasa.gov moved; re-check the page a few times a year).
  GLACIERS    USGS Benchmark Glacier Project: glacier-wide annual mass balance (m water equivalent), calibrated
              solutions, for the six glaciers with an output series. Public domain.

usage: ice_bake.py
"""
import csv, datetime as dt, io, json, math, re, time, urllib.parse, urllib.request, zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '_maplab' / 'ice.json'
UA = {'User-Agent': 'bluishvoid-bake (+https://bluishvoid.com)'}
NOW = dt.datetime.now(dt.timezone.utc)


def get(url, timeout=120, tries=3):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(10 * (i + 1))


# ── SEA ICE ────────────────────────────────────────────────────────────────────────────────────
NS = 'https://noaadata.apps.nsidc.org/NOAA/G02135/%s/daily/data/%s_seaice_extent_%s_v4.0.csv'

# ── ICE EDGES FOR THE GLOBE (2026-10-09, user: "are there any visuals to add to the map for that?") ──────────
# Three outlines in lat/lon for the SEA ICE globe: where the edge USUALLY sits on this day of year (NSIDC's 1981-2010
# median polyline, published per day of year), the edge on the day of THIS YEAR'S low, and the edge on the record-low
# day (both traced from the daily extent GeoTIFF: the boundary between ice cells (1) and OPEN-WATER cells (0) -- an
# ice-to-land boundary is a coast, not an ice edge). Grid: 25 km polar stereographic (EPSG:3411 north, 3412 south),
# origin from the GeoTIFF tags. Lines are chained from unit segments and thinned (Douglas-Peucker, 0.12 deg) to a
# few KB each. Needs pillow, pyshp and pyproj; a missing library or a 404 leaves that edge out, nothing else fails.
NS_BASE = 'https://noaadata.apps.nsidc.org/NOAA/G02135'
_MON = ['', '01_Jan', '02_Feb', '03_Mar', '04_Apr', '05_May', '06_Jun', '07_Jul', '08_Aug', '09_Sep', '10_Oct', '11_Nov', '12_Dec']

def _to_ll(hemi):
    import pyproj
    tr = pyproj.Transformer.from_crs('EPSG:3411' if hemi == 'N' else 'EPSG:3412', 'EPSG:4326', always_xy=True)
    def f(x, y):
        lo, la = tr.transform(x, y); return [round(la, 2), round(lo, 2)]
    return f

def _rdp(pts, tol):
    if len(pts) < 3: return pts
    def d(p, a, b):
        ax, ay, bx, by, px, py = a[1], a[0], b[1], b[0], p[1], p[0]
        dx, dy = bx - ax, by - ay; L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
    imax, dmax = 0, 0
    for i in range(1, len(pts) - 1):
        dd = d(pts[i], pts[0], pts[-1])
        if dd > dmax: imax, dmax = i, dd
    if dmax > tol: return _rdp(pts[:imax + 1], tol)[:-1] + _rdp(pts[imax:], tol)
    return [pts[0], pts[-1]]

def _median_edge(hemi, doy):
    import shapefile
    H = 'north' if hemi == 'N' else 'south'
    z = zipfile.ZipFile(io.BytesIO(get('%s/%s/daily/shapefiles/dayofyear_median/median_extent_%s_%03d_1981-2010_polyline_v4.0.zip' % (NS_BASE, H, hemi, doy))))
    names = {n.rsplit('.', 1)[1]: n for n in z.namelist() if '.' in n}
    r = shapefile.Reader(shp=io.BytesIO(z.read(names['shp'])), shx=io.BytesIO(z.read(names['shx'])), dbf=io.BytesIO(z.read(names['dbf'])))
    f = _to_ll(hemi); parts = []
    for sh in r.shapes():
        idx = list(sh.parts) + [len(sh.points)]
        for a, b in zip(idx, idx[1:]):
            seg = [f(x, y) for x, y in sh.points[a:b]]
            if len(seg) >= 3: parts.append(seg)
    return {'doy': doy, 'parts': parts}

def _extent_edge(hemi, day):
    from PIL import Image
    H = 'north' if hemi == 'N' else 'south'
    im = Image.open(io.BytesIO(get('%s/%s/daily/geotiff/%d/%s/%s_%s_extent_v4.0.tif' % (NS_BASE, H, day.year, _MON[day.month], hemi, day.strftime('%Y%m%d')))))
    W, Hh = im.size; px = im.load(); t = im.tag_v2; sx, sy = t[33550][0], t[33550][1]; x0, y0 = t[33922][3], t[33922][4]
    ice = lambda x, y: 0 <= x < W and 0 <= y < Hh and px[x, y] == 1
    water = lambda x, y: 0 <= x < W and 0 <= y < Hh and px[x, y] == 0
    segs = []
    for y in range(Hh):
        for x in range(W):
            if not ice(x, y): continue
            if water(x + 1, y): segs.append(((x + 1, y), (x + 1, y + 1)))
            if water(x - 1, y): segs.append(((x, y), (x, y + 1)))
            if water(x, y + 1): segs.append(((x, y + 1), (x + 1, y + 1)))
            if water(x, y - 1): segs.append(((x, y), (x + 1, y)))
    adj = defaultdict(list)
    for i, (a, b) in enumerate(segs): adj[a].append(i); adj[b].append(i)
    used = [False] * len(segs); lines = []
    for i in range(len(segs)):
        if used[i]: continue
        used[i] = True; a, b = segs[i]; line = [a, b]
        for fwd in (True, False):
            cur = line[-1] if fwd else line[0]
            while True:
                nxt = [j for j in adj[cur] if not used[j]]
                if not nxt: break
                j = nxt[0]; used[j] = True; p, q = segs[j]; cur = q if p == cur else p
                if fwd: line.append(cur)
                else: line.insert(0, cur)
        lines.append(line)
    f = _to_ll(hemi); out = []
    for line in lines:
        if len(line) < 4: continue
        pts = _rdp([f(x0 + gx * sx, y0 - gy * sy) for gx, gy in line], 0.12)
        if len(pts) >= 3: out.append(pts)
    return {'date': day.isoformat(), 'parts': out}


def sea_ice(hemi):
    H = 'north' if hemi == 'N' else 'south'
    rows = {}
    for ln in get(NS % (H, hemi, 'daily')).decode('utf-8', 'replace').splitlines()[2:]:
        c = [x.strip() for x in ln.split(',')[:4]]
        try: rows[dt.date(int(c[0]), int(c[1]), int(c[2]))] = float(c[3])
        except Exception: continue
    clim = {}
    for ln in get(NS % (H, hemi, 'climatology_1981-2010')).decode('utf-8', 'replace').splitlines()[2:]:
        c = [x.strip() for x in ln.split(',')]
        try: clim[int(c[0])] = {'avg': float(c[1]), 'p10': float(c[3]), 'p50': float(c[5]), 'p90': float(c[7])}
        except Exception: continue
    last = max(rows); v = rows[last]; doy = last.timetuple().tm_yday
    # the same calendar day in every other year (early years are every other day: take the day either side)
    same = {}
    for y in range(1979, last.year):
        for off in (0, -1, 1):
            try: d = dt.date(y, last.month, last.day) + dt.timedelta(days=off)
            except ValueError: continue
            if d in rows: same[y] = rows[d]; break
    lower = sorted((val, y) for y, val in same.items())
    rank = 1 + sum(1 for val, y in lower if val < v)
    rec = lower[0] if lower else None
    # each complete year's minimum and maximum, on NSIDC's own footing: FIVE-DAY TRAILING MEANS (audit 2026-10-10: the
    # single-day values put 2012's record at 3.34 on Sep 16 where NSIDC publishes 3.39 on Sep 17, and ranked 2026 12th
    # where NSIDC says tied 10th). A day needs all five days present.
    sm = {}
    for d in rows:
        w = [rows.get(d - dt.timedelta(days=k)) for k in range(5)]
        if all(x is not None for x in w): sm[d] = sum(w) / 5
    ymin, ymax = {}, {}
    for d, val in sm.items():
        if d.year < last.year and d.year > 1978 and (d.year not in ymin or val < ymin[d.year][0]): ymin[d.year] = (val, d)
        if d.year < last.year and d.year > 1978 and (d.year not in ymax or val > ymax[d.year][0]): ymax[d.year] = (val, d)
    ry = min(ymin, key=lambda y: ymin[y][0])
    # this year so far: its lowest (N: the September minimum) and highest, five-day means too
    this = sorted((d, val) for d, val in sm.items() if d.year == last.year)
    lo_this = min(this, key=lambda r: r[1]); hi_this = max(this, key=lambda r: r[1])
    series = lambda yr: [[d.timetuple().tm_yday, round(val, 3)] for d, val in sorted(rows.items()) if d.year == yr]
    edges = {}
    for k, fn in (('median', lambda: _median_edge(hemi, doy)), ('min', lambda: _extent_edge(hemi, lo_this[0])), ('record', lambda: _extent_edge(hemi, ymin[ry][1]))):
        try: edges[k] = fn()
        except Exception as e: print('  edge', hemi, k, 'failed', e)
    if 'record' in edges: edges['record']['year'] = ry
    return {'date': last.isoformat(), 'extent': round(v, 3), 'doy': doy,
            'median': clim.get(doy, {}).get('p50'), 'avg': clim.get(doy, {}).get('avg'),
            'rank': rank, 'years': len(same) + 1, 'record': {'extent': round(rec[0], 3), 'year': rec[1]} if rec else None,
            'thisMin': {'extent': round(lo_this[1], 3), 'date': lo_this[0].isoformat()},
            'thisMax': {'extent': round(hi_this[1], 3), 'date': hi_this[0].isoformat()},
            'recordMinYear': {'year': ry, 'extent': round(ymin[ry][0], 3), 'date': ymin[ry][1].isoformat()},
            # EVERY YEAR'S LOW POINT AND PEAK (2026-10-09, user: "can earth systems show sea ice minimums"): [year, extent, date]
            # for each complete year; the page adds this year's from thisMin/thisMax and says whether its season is over
            'edges': edges,
            'mins': [[y, round(ymin[y][0], 3), ymin[y][1].isoformat()] for y in sorted(ymin)],
            'maxs': [[y, round(ymax[y][0], 3), ymax[y][1].isoformat()] for y in sorted(ymax)],
            'clim': [[k, clim[k]['p10'], clim[k]['p50'], clim[k]['p90']] for k in sorted(clim)],
            'series': {str(last.year): series(last.year), str(last.year - 1): series(last.year - 1), str(ry): series(ry)}}


# ── GREENLAND ──────────────────────────────────────────────────────────────────────────────────
DMI = 'https://download.dmi.dk/Research_Projects/polarportal/PP_GSMB/'


def dmi_rows(name):
    out = []
    for ln in get(DMI + name).decode('utf-8', 'replace').splitlines():
        m = re.match(r'\s*(\d{8})\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?', ln)      # date, daily (Gt or melt %), running total
        if m:
            a, b = float(m.group(2)), (float(m.group(3)) if m.group(3) else None)
            # DMI writes -9999 for not-yet-computed values (the new season's running total from Sep 10 on, audit 2026-10-10)
            if a <= -9000: a = None
            if b is not None and b <= -9000: b = None
            out.append((m.group(1), a, b))
    return out


def greenland():
    seasons = []
    for y in range(2018, NOW.year + 2):
        try: r = dmi_rows('GSMB_%d.txt' % y)
        except Exception: continue
        if not r: continue
        valid = [x for x in r if x[2] is not None]
        if not valid: continue
        last = valid[-1]                                               # the last row with a real running total
        complete = last[0][4:6] == '08' and int(last[0][6:]) >= 29      # the 2025-26 file stops at Aug 30
        seasons.append({'season': '%d-%s' % (y - 1, str(y)[2:]), 'end': last[0], 'total': last[2], 'complete': complete,
                        'daily': [[x[0], x[2]] for x in r[::3] if x[2] is not None]})
    melt = []
    try:
        mr = dmi_rows('GSMB_MELTA_%d.txt' % (NOW.year if NOW.month >= 8 else NOW.year - 1))     # the latest summer's melt
        melt = [[x[0], x[1]] for x in mr]
    except Exception: pass
    peak = max(melt, key=lambda x: x[1]) if melt else None
    return {'seasons': seasons, 'meltPeak': {'date': peak[0], 'pct': peak[1]} if peak else None,
            'src': 'https://polarportal.dk/en/greenland/surface-conditions/'}


# ── GLACIERS ───────────────────────────────────────────────────────────────────────────────────
USGS = 'https://www.sciencebase.gov/catalog/file/get/6441de03d34ee8d4ade7d2a5?name=glacier_massBalance_data.zip'
GLACIER = {   # name, state, lat, lon (approx. centre)
    'SouthCascade': ('SOUTH CASCADE', 'WASHINGTON', 48.36, -121.06),
    'Sperry': ('SPERRY', 'MONTANA', 48.62, -113.76),
    'Gulkana': ('GULKANA', 'ALASKA', 63.26, -145.42),
    'Wolverine': ('WOLVERINE', 'ALASKA', 60.41, -148.92),
    'LemonCreek': ('LEMON CREEK', 'ALASKA', 58.38, -134.36),
    'Taku': ('TAKU', 'ALASKA', 58.62, -134.19),
}


def glaciers():
    z = zipfile.ZipFile(io.BytesIO(get(USGS)))
    out = []
    for key, (nm, st, la, lo) in GLACIER.items():
        f = next((n for n in z.namelist() if n.endswith('Output_%s_Glacier_Wide_solutions_calibrated.csv' % key)), None)
        if not f: continue
        rows = [r for r in csv.DictReader(io.TextIOWrapper(z.open(f), 'utf-8')) if r.get('Ba') not in (None, '', 'nan')]
        cum, ser = 0.0, []
        for r in rows:
            cum += float(r['Ba']); ser.append([int(r['Year']), round(float(r['Ba']), 2), round(cum, 2)])
        out.append({'key': key, 'name': nm, 'state': st, 'lat': la, 'lon': lo, 'from': ser[0][0], 'to': ser[-1][0],
                    'cum': round(cum, 2), 'last': ser[-1][1], 'series': ser})
    return out


# ── ICE SHEETS: IMBIE-3 (Otosaka et al.; UK Polar Data Centre, doi 10.5285/77B64C55-7166-4A06-9DEF-2E400398E452, OGL v3) ──
# 45 satellite estimates reconciled; total mass change split into SURFACE (snow minus melt) and DYNAMICS (ice flow to the sea)
IMBIE_DIR = '128c5e33-5224-4197-82f0-19dcc95b80a0'


def imbie():
    import base64
    # the dataset actually read is IMBIE's 2026 release (1970s-2023), not the 2023 IMBIE-3 paper's (audit 2026-10-10)
    out = {'src': 'https://doi.org/10.5285/128c5e33-5224-4197-82f0-19dcc95b80a0', 'cite': 'IMBIE (2026), MASS BALANCE OF THE GREENLAND AND ANTARCTIC ICE SHEETS FROM THE 1970S TO 2023'}
    for key in ('greenland', 'antarctica', 'west_antarctica', 'east_antarctica', 'antarctic_peninsula'):
        name = 'imbie3_%s_Gt_partitioned.csv' % key
        eid = 'synth:%s:%s' % (IMBIE_DIR, base64.b64encode(('/' + name).encode()).decode())
        txt = get('http://ramadda.data.bas.ac.uk/repository/entry/get/%s?entryid=%s' % (name, urllib.parse.quote(eid))).decode('utf-8', 'replace')
        rows = list(csv.reader([ln for ln in txt.splitlines() if ln and not ln.startswith('#')]))[1:]
        yr = {}
        for r in rows:
            try: y, m = int(r[0][:4]), int(r[0][5:7])
            except Exception: continue
            if m == 12 or y not in yr: yr[y] = [y, round(float(r[3])), round(float(r[7])), round(float(r[11])), round(float(r[1]), 1)]   # year, cumulative total, surface, dynamics, rate
        ser = [yr[y] for y in sorted(yr)]
        last = rows[-1]
        rate5 = sum(float(r[1]) for r in rows[-60:]) / len(rows[-60:])
        out[key] = {'series': ser, 'end': last[0][:7], 'total': round(float(last[3])), 'surface': round(float(last[7])), 'dynamics': round(float(last[11])),
                    'rate5': round(rate5), 'start': rows[0][0][:4]}
    return out


# ── SNOW: Rutgers Global Snow Lab, Northern Hemisphere land snow extent (NOAA CDR), weekly since 1966, monthly since 1967 ──
def snow():
    wk = [[int(a), int(b), int(c)] for a, b, c in (ln.split() for ln in get('https://climate.rutgers.edu/snowcover/files/wkcov.nhland.txt').decode().splitlines() if len(ln.split()) == 3)]
    mo = [[int(a), int(b), int(c)] for a, b, c in (ln.split() for ln in get('https://climate.rutgers.edu/snowcover/files/moncov.nhland.txt').decode().splitlines() if len(ln.split()) == 3)]
    clim = {}
    for y, w, a in wk:
        if 1991 <= y <= 2020: clim.setdefault(w, []).append(a)
    clim = {w: round(sum(v) / len(v)) for w, v in clim.items()}
    last = wk[-1]
    same = sorted(a for y, w, a in wk if w == last[1] and y < last[0])
    june = [[y, round(a / 1e6, 2)] for y, m, a in mo if m == 6]
    this = [[w, round(a / 1e6, 2)] for y, w, a in wk if y == last[0]]
    prev = [[w, round(a / 1e6, 2)] for y, w, a in wk if y == last[0] - 1]
    return {'year': last[0], 'week': last[1], 'km2': last[2], 'normal': clim.get(last[1]), 'rank': 1 + sum(1 for a in same if a < last[2]), 'years': len(same) + 1,
            'clim': [[w, round(clim[w] / 1e6, 2)] for w in sorted(clim)], 'this': this, 'prev': prev, 'june': june,
            'src': 'https://climate.rutgers.edu/snowcover/'}


# ── LAKE ICE: NOAA GLERL Great Lakes ice cover, daily % per lake, every winter since 1973 (column = the winter's ending year) ──
def lakes():
    out = {'src': 'https://www.glerl.noaa.gov/data/ice/', 'lakes': {}}
    for k, nm in (('bas', 'ALL FIVE'), ('sup', 'SUPERIOR'), ('mic', 'MICHIGAN'), ('hur', 'HURON'), ('eri', 'ERIE'), ('ont', 'ONTARIO')):
        L = get('https://www.glerl.noaa.gov/data/ice/glicd/daily/%s.txt' % k).decode('utf-8', 'replace').splitlines()
        yrs = [int(x) for x in L[0].split()]
        days, cols = [], {y: [] for y in yrs}
        for ln in L[1:]:
            c = ln.split()
            if len(c) != len(yrs) + 1: continue
            days.append(c[0])
            for y, v in zip(yrs, c[1:]): cols[y].append(None if v == 'NA' else float(v))
        mx = {}
        for y in yrs:
            vals = [(v, i) for i, v in enumerate(cols[y]) if v is not None]
            if vals: v, i = max(vals); mx[y] = [round(v, 1), days[i]]
        done = [y for y in yrs if y in mx]
        avg = [None if not any(cols[y][i] is not None for y in done[:-1]) else round(sum(cols[y][i] or 0 for y in done[:-1] if cols[y][i] is not None) / max(1, sum(1 for y in done[:-1] if cols[y][i] is not None)), 1) for i in range(len(days))]
        last = done[-1]
        rec = {'name': nm, 'max': [[y] + mx[y] for y in done], 'last': last, 'lastMax': mx[last], 'avgMax': round(sum(mx[y][0] for y in done[:-1]) / len(done[:-1]), 1)}
        if k == 'bas': rec.update({'days': days, 'lastCurve': cols[last], 'avgCurve': avg})
        out['lakes'][k] = rec
    return out


def gibs_dates():
    """the latest day GIBS holds for the two satellite skins the ICE globes draw undated, so the page can say the date
    (audit 2026-10-10: the snow composite was 2.5 weeks old and the SMAP map 3 days old, both captioned as today)"""
    xml = get('https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0', timeout=180).decode('utf-8', 'replace')
    out = {}
    for key, layer in (('snow', 'MODIS_Terra_L3_Snow_Extent_8Day'), ('smap', 'SMAP_L3_Passive_Day_Freeze_Thaw'), ('smapNight', 'SMAP_L3_Passive_Night_Freeze_Thaw')):
        i = xml.find('<Name>' + layer + '</Name>')
        if i < 0: continue
        j = xml.find('</Layer>', i); seg = xml[i:j]
        m = re.search(r'<Dimension[^>]*name="time"[^>]*>([^<]*)</Dimension>', seg)
        if not m: continue
        ends = re.findall(r'(\d{4}-\d{2}-\d{2})(?=/P)', m.group(1)) or re.findall(r'\d{4}-\d{2}-\d{2}', m.group(1))
        if ends: out[key] = max(ends)
    return out


def main():
    prev = {}
    try: prev = json.loads(OUT.read_text())
    except Exception: pass
    out = {'built': NOW.strftime('%Y-%m-%dT%H:%MZ'),
           'sheets': {'greenland': -264, 'antarctica': -135, 'period': '2002-2025',
                      'src': 'https://science.nasa.gov/earth/explore/earth-indicators/ice-sheets/'}}
    for key, fn in (('arctic', lambda: sea_ice('N')), ('antarctic', lambda: sea_ice('S')), ('greenland', greenland), ('glaciers', glaciers),
                    ('imbie', imbie), ('snow', snow), ('lakes', lakes), ('gibs', gibs_dates)):
        try: out[key] = fn(); print('ok', key)
        except Exception as e:
            print('FAILED', key, e)
            if key in prev: out[key] = prev[key]
    # the world's glaciers (GlaMBIE per region + label points), made once by rgi_bake.py
    try: out['world'] = json.loads((ROOT / '_maplab' / 'rgi_regions.json').read_text())
    except Exception as e: print('no rgi_regions.json', e)
    OUT.write_text(json.dumps(out, separators=(',', ':')))
    print('wrote', OUT, len(json.dumps(out)), 'bytes')


if __name__ == '__main__':
    main()
