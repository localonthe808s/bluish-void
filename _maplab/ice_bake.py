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
import csv, datetime as dt, io, json, re, time, urllib.request, zipfile
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
    # each complete year's minimum: the record-low year for the season's low point
    ymin = {}
    for d, val in rows.items():
        if d.year < last.year and d.year > 1978 and (d.year not in ymin or val < ymin[d.year][0]): ymin[d.year] = (val, d)
    ry = min(ymin, key=lambda y: ymin[y][0])
    # this year so far: its lowest (N: the September minimum) and highest
    this = sorted((d, val) for d, val in rows.items() if d.year == last.year)
    lo_this = min(this, key=lambda r: r[1]); hi_this = max(this, key=lambda r: r[1])
    series = lambda yr: [[d.timetuple().tm_yday, round(val, 3)] for d, val in sorted(rows.items()) if d.year == yr]
    return {'date': last.isoformat(), 'extent': round(v, 3), 'doy': doy,
            'median': clim.get(doy, {}).get('p50'), 'avg': clim.get(doy, {}).get('avg'),
            'rank': rank, 'years': len(same) + 1, 'record': {'extent': round(rec[0], 3), 'year': rec[1]} if rec else None,
            'thisMin': {'extent': round(lo_this[1], 3), 'date': lo_this[0].isoformat()},
            'thisMax': {'extent': round(hi_this[1], 3), 'date': hi_this[0].isoformat()},
            'recordMinYear': {'year': ry, 'extent': round(ymin[ry][0], 3), 'date': ymin[ry][1].isoformat()},
            'clim': [[k, clim[k]['p10'], clim[k]['p50'], clim[k]['p90']] for k in sorted(clim)],
            'series': {str(last.year): series(last.year), str(last.year - 1): series(last.year - 1), str(ry): series(ry)}}


# ── GREENLAND ──────────────────────────────────────────────────────────────────────────────────
DMI = 'https://download.dmi.dk/Research_Projects/polarportal/PP_GSMB/'


def dmi_rows(name):
    out = []
    for ln in get(DMI + name).decode('utf-8', 'replace').splitlines():
        m = re.match(r'\s*(\d{8})\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?', ln)      # date, daily (Gt or melt %), running total
        if m: out.append((m.group(1), float(m.group(2)), float(m.group(3)) if m.group(3) else None))
    return out


def greenland():
    seasons = []
    for y in range(2018, NOW.year + 2):
        try: r = dmi_rows('GSMB_%d.txt' % y)
        except Exception: continue
        if not r: continue
        last = r[-1]
        complete = last[0][4:6] == '08' and int(last[0][6:]) >= 29      # the 2025-26 file stops at Aug 30
        seasons.append({'season': '%d-%s' % (y - 1, str(y)[2:]), 'end': last[0], 'total': last[2], 'complete': complete,
                        'daily': [[x[0], x[2]] for x in r[::3]]})
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


def main():
    prev = {}
    try: prev = json.loads(OUT.read_text())
    except Exception: pass
    out = {'built': NOW.strftime('%Y-%m-%dT%H:%MZ'),
           'sheets': {'greenland': -264, 'antarctica': -135, 'period': '2002-2025',
                      'src': 'https://science.nasa.gov/earth/explore/earth-indicators/ice-sheets/'}}
    for key, fn in (('arctic', lambda: sea_ice('N')), ('antarctic', lambda: sea_ice('S')), ('greenland', greenland), ('glaciers', glaciers)):
        try: out[key] = fn(); print('ok', key)
        except Exception as e:
            print('FAILED', key, e)
            if key in prev: out[key] = prev[key]
    OUT.write_text(json.dumps(out, separators=(',', ':')))
    print('wrote', OUT, len(json.dumps(out)), 'bytes')


if __name__ == '__main__':
    main()
