#!/usr/bin/env python3
"""WHEN FALL COLOR USUALLY PEAKS (user 2026-10-29, TREES improvement 5). USA National Phenology Network observations (public, cite the
network): volunteers and staff check marked trees through the season and record 'Colored leaves' (phenophase 498) with how much of the
crown has turned. For every tree and fall (Aug 15 - Dec 31), the first check with half or more of the leaves colored; the site's
typical date is the median of its trees' dates over 2009-2025. Out: [[lat, lon, median day of year, years, tree-falls], ...]
    python3 peak.py WORKDIR OUT.json"""
import datetime, json, os, statistics, sys, time, urllib.request
STATES = 'AL AZ AR CA CO CT DE DC FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split()
HALF = {'50-74%', '75-94%', '95% or more'}
def fetch(st, work):
    p = os.path.join(work, st + '.json')
    if os.path.exists(p) and os.path.getsize(p) > 2: return json.load(open(p))
    u = ('https://services.usanpn.org/npn_portal/observations/getObservations.json?start_date=2009-08-01&end_date=2025-12-31&state%%5B0%%5D=%s'
         '&phenophase_id%%5B0%%5D=498&request_src=bluish-void' % st)
    for k in range(4):
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluish-void bake'}), timeout=600)); break
        except Exception as e: print(st, 'retry', e, flush=True); time.sleep(10)
    else: return []
    keep = [[x['individual_id'], x['site_id'], x['latitude'], x['longitude'], x['observation_date'], x['intensity_value']] for x in d
            if x.get('intensity_value') in HALF and x.get('phenophase_status') == 1]
    json.dump(keep, open(p, 'w')); return keep
def main(work, out):
    first = {}; where = {}
    for st in STATES:
        rows = fetch(st, work); print(st, len(rows), flush=True)
        for ind, site, la, lo, dt, iv in rows:
            d = datetime.date.fromisoformat(dt)
            if (d.month, d.day) < (8, 15): continue
            k = (ind, d.year); doy = d.timetuple().tm_yday
            if k not in first or doy < first[k][1]: first[k] = (site, doy)
            where[site] = (round(la, 4), round(lo, 4))
    sites = {}
    for (ind, yr), (site, doy) in first.items(): sites.setdefault(site, []).append((yr, doy))
    res = []
    for site, v in sites.items():
        yrs = len(set(y for y, _ in v))
        if yrs < 2 or len(v) < 3: continue
        la, lo = where[site]; res.append([la, lo, int(round(statistics.median(d for _, d in v))), yrs, len(v)])
    json.dump(res, open(out, 'w'), separators=(',', ':')); print('sites', len(res), flush=True)
if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
