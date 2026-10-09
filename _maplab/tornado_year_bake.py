#!/usr/bin/env python3
"""Tornado year-to-date count (HAZARDS -> TORNADOES), baked nightly.

The tornado tab's "<year>: N" figure is the sum of SPC's per-day storm reports since Jan 1. The page used to
fetch one CSV per elapsed day on a visitor's first visit (280 requests by October, cached in localStorage
afterwards). This bake does that fetching once a night on a runner and commits _maplab/tornado_year.json;
the page merges it into its per-day cache and only fetches the last three days live (SPC revises recent
days for a while), so a first visit costs one JSON plus three CSVs.

The JSON holds exactly the records the page caches per day, keyed the way the page keys them (yymmdd):

  {"year": 2026, "generated": "...Z", "through": "261008",
   "days": {"260101": {"count": 0, "tops": []}, ...}}

  tops = up to five reports of the day ranked by EF scale, fields the page's tornYearCache uses.

Source: https://www.spc.noaa.gov/climo/reports/YYMMDD_rpts_torn.csv (public domain, NOAA). A day that fails
to download keeps its record from the previous bake, so one bad night never zeroes a day.

usage: tornado_year_bake.py
"""
import datetime as dt, json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '_maplab' / 'tornado_year.json'
UA = {'User-Agent': 'bluishvoid-bake (+https://bluishvoid.com)'}
BASE = 'https://www.spc.noaa.gov/climo/reports/'
EF = {'EF5': 6, 'EF4': 5, 'EF3': 4, 'EF2': 3, 'EF1': 2, 'EF0': 1}


def get(url, timeout=60, tries=3):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode('utf-8', 'replace')
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def parse(csv_text):
    """Mirror of parseTornadoCSV in index.html: Time,F_Scale,Location,County,State,Lat,Lon,Comments."""
    out = []
    for line in csv_text.strip().split('\n')[1:]:
        if not line.strip():
            continue
        parts = line.split(',')
        if len(parts) < 7:
            continue
        try:
            lat, lon = float(parts[5]), float(parts[6])
        except ValueError:
            continue
        out.append({'scale': parts[1].strip(), 'location': parts[2].strip(), 'state': parts[4].strip(),
                    'lat': lat, 'lon': lon})
    return out


def bake_day(day):
    key = day.strftime('%y%m%d')
    label = f'{day.month}/{day.day}/{day.year}'
    reports = parse(get(BASE + key + '_rpts_torn.csv'))
    tops = sorted(reports, key=lambda r: -EF.get(r['scale'], 0))[:5]
    for r in tops:
        r['dateLabel'] = label
    return key, {'count': len(reports), 'tops': tops}


def main():
    # SPC's report day is 12Z-12Z and the page keys by the visitor's calendar date; both land on the same
    # yymmdd for the count. Bake through yesterday (UTC): today's file is still filling in.
    today = dt.datetime.now(dt.timezone.utc).date()
    year = today.year
    days = [dt.date(year, 1, 1) + dt.timedelta(n) for n in range((today - dt.date(year, 1, 1)).days)]
    previous = {}
    try:
        p = json.loads(OUT.read_text())
        if p.get('year') == year:
            previous = p.get('days') or {}
    except Exception:
        pass

    result, failed = {}, []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for day, fut in [(d, pool.submit(bake_day, d)) for d in days]:
            try:
                key, rec = fut.result()
                result[key] = rec
            except Exception as e:
                key = day.strftime('%y%m%d')
                failed.append(key)
                if key in previous:
                    result[key] = previous[key]
    if days and len(failed) > len(days) // 4:
        raise SystemExit(f'too many days failed ({len(failed)} of {len(days)}): SPC down? keeping the old file')

    out = {'year': year, 'generated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'through': days[-1].strftime('%y%m%d') if days else None, 'days': result}
    OUT.write_text(json.dumps(out, separators=(',', ':')))
    total = sum(r['count'] for r in result.values())
    print(f'{len(result)} days, {total} tornado reports in {year}, {len(failed)} days kept from the previous bake, {OUT.stat().st_size} bytes')


if __name__ == '__main__':
    main()
