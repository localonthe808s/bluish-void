#!/usr/bin/env python3
"""BEACHES, nationwide (user 2026-11-19: "lets do beaches").

Where: EPA's BEACH Act program list of monitoring stations (ArcGIS, public).
What the water tested: the Water Quality Portal (EPA + USGS), every enterococcus and E. coli result those stations'
organizations uploaded in the last 18 months. Each station keeps its NEWEST sampling day (the worst sample that day),
plus how many days it was sampled in those 18 months and how many of those were over the swimming threshold
(18, not 12: most states upload a season only after it ends, so the newest season on file is often last year's).

Out: beaches_v1.json  { built, n, st: [[lat, lon, name, org name, date|null, value|null, 'e'|'c'|null, days, over], ...] }
Run: python3 _beachbake/bake.py [out.json]      (no keys; about 10-20 minutes, the portal is slow)
"""
import sys, os, json, csv, io, time, datetime, urllib.request, urllib.parse, concurrent.futures as cf

UA = {'User-Agent': 'Mozilla/5.0 (beach-bake)'}
EPA = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/ArcGIS/rest/services/epa_beaches_program/FeatureServer/0/query'
WQP = 'https://www.waterqualitydata.us/data/Result/search'
TODAY = datetime.date.today()
SINCE = TODAY - datetime.timedelta(days=548)
YEAR = TODAY - datetime.timedelta(days=365)
LIMIT = {'e': 104.0, 'c': 235.0}          # single-sample swimming thresholds, per 100 ml: enterococci, E. coli


def get(url, timeout=300, tries=3):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def stations():
    out, off = [], 0
    while True:
        q = urllib.parse.urlencode({'where': '1=1', 'outFields': 'org_id,org_name,mloc_id,mloc_name,mloc_latitude,mloc_longitude',
                                    'returnGeometry': 'false', 'orderByFields': 'OBJECTID', 'resultOffset': off, 'resultRecordCount': 2000, 'f': 'json'})
        F = json.loads(get(EPA + '?' + q)).get('features', [])
        out += [f['attributes'] for f in F]
        if len(F) < 2000:
            return out
        off += 2000


def results(org, sites=None):
    """{site id: {day: [worst value, kind]}} for one organization, or for a list of site ids"""
    q = ([('siteid', x) for x in sites] if sites else [('organization', org)]) + [('characteristicName', 'Enterococcus'), ('characteristicName', 'Escherichia coli'),
         ('startDateLo', SINCE.strftime('%m-%d-%Y')), ('mimeType', 'csv'), ('dataProfile', 'narrowResult')]
    try:
        raw = get(WQP + '?' + urllib.parse.urlencode(q), timeout=900).decode('utf-8', 'replace')
    except Exception as e:
        print('  FAILED', org, e, flush=True)
        return org, None
    by = {}
    for r in csv.DictReader(io.StringIO(raw)):
        try:
            v = float(str(r.get('ResultMeasureValue') or '').replace('<', '').replace('>', '').strip())
        except ValueError:
            continue
        unit = (r.get('ResultMeasure/MeasureUnitCode') or '').lower()
        if unit and '100' not in unit:          # only counts per 100 ml compare with the thresholds
            continue
        d = (r.get('ActivityStartDate') or '')[:10]
        if len(d) != 10 or d > TODAY.isoformat():
            continue
        k = 'e' if 'nterococc' in (r.get('CharacteristicName') or '') else 'c'
        s = by.setdefault(r.get('MonitoringLocationIdentifier') or '', {})
        if d not in s or v / LIMIT[k] > s[d][0] / LIMIT[s[d][1]]:
            s[d] = [v, k]
    return org, by


def near_sites(job):
    """the portal's own sites (any organization) with bacteria results inside one box: [[id, lat, lon], ...]"""
    org, box = job
    q = [('bBox', '%.4f,%.4f,%.4f,%.4f' % box), ('characteristicName', 'Enterococcus'), ('characteristicName', 'Escherichia coli'),
         ('startDateLo', SINCE.strftime('%m-%d-%Y')), ('mimeType', 'csv')]
    try:
        raw = get('https://www.waterqualitydata.us/data/Station/search?' + urllib.parse.urlencode(q), timeout=600).decode('utf-8', 'replace')
    except Exception as e:
        print('  FAILED sites', org, e, flush=True)
        return org, []
    out = []
    for r in csv.DictReader(io.StringIO(raw)):
        try:
            out.append([r['MonitoringLocationIdentifier'], float(r['LatitudeMeasure']), float(r['LongitudeMeasure'])])
        except (KeyError, ValueError):
            pass
    return org, out


def meters(a, b, c, d):
    import math
    return math.hypot((a - c) * 111320.0, (b - d) * 111320.0 * math.cos(math.radians(a)))


def by_place(S, R):
    """A STATION WITH NO RESULT UNDER ITS OWN NAME (user 2026-11-19: half the map was gray). The EPA list and the portal do not
    always agree on who a station belongs to (EPA: 'NJDEP'; the portal: 'NJDEP_BFBM') or what it is called. So a station
    with nothing under its EPA id borrows the portal site standing within NEAR meters of it, the nearest one.
    Returns {index in S: {day: [value, kind]}}."""
    NEAR = 150.0
    own = lambda s: (R.get(s['org_id']) or {}).get('%s-%s' % (s['org_id'], s['mloc_id']))
    lone = [i for i, s in enumerate(S) if not own(s)]
    boxes = {}
    for i in lone:
        s = S[i]
        b = boxes.setdefault(s['org_id'], [180.0, 90.0, -180.0, -90.0])
        b[0] = min(b[0], s['mloc_longitude']); b[1] = min(b[1], s['mloc_latitude']); b[2] = max(b[2], s['mloc_longitude']); b[3] = max(b[3], s['mloc_latitude'])
    jobs = [(o, (b[0] - .01, b[1] - .01, b[2] + .01, b[3] + .01)) for o, b in boxes.items() if b[2] - b[0] < 40]      # a box round the world is a bad coordinate
    grid = {}
    with cf.ThreadPoolExecutor(4) as ex:
        for org, sites in ex.map(near_sites, jobs):
            print('  near %-22s %5d portal sites in its box' % (org, len(sites)), flush=True)
            for sid, la, lo in sites:
                grid.setdefault((int(la * 200), int(lo * 200)), {})[sid] = (la, lo)
    want = {}
    for i in lone:
        s = S[i]; la, lo = s['mloc_latitude'], s['mloc_longitude']; best = None; bd = NEAR
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for sid, (a, b) in (grid.get((int(la * 200) + dy, int(lo * 200) + dx)) or {}).items():
                    d = meters(la, lo, a, b)
                    if d <= bd:
                        bd = d; best = sid
        if best:
            want[i] = best
    ids = sorted(set(want.values()))
    print('  %d lone stations, %d have a portal site within %d m (%d sites to read)' % (len(lone), len(want), NEAR, len(ids)), flush=True)
    got = {}
    chunks = [ids[k:k + 40] for k in range(0, len(ids), 40)]
    with cf.ThreadPoolExecutor(4) as ex:
        for _, by in ex.map(lambda c: results('by place', c), chunks):
            got.update(by or {})
    return {i: got[sid] for i, sid in want.items() if got.get(sid)}


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'beaches_v1.json')
    S = [s for s in stations() if s.get('mloc_latitude') and s.get('mloc_longitude')]
    orgs = sorted({s['org_id'] for s in S})
    print(len(S), 'stations,', len(orgs), 'organizations', flush=True)
    R, failed = {}, []
    with cf.ThreadPoolExecutor(4) as ex:
        for org, by in ex.map(results, orgs):
            if by is None:
                failed.append(org)
                continue
            R[org] = by
            print('  %-22s %5d sites with results' % (org, len(by)), flush=True)
    rows = []
    P = by_place(S, R)
    print('  matched by place:', len(P), flush=True)
    for i, s in enumerate(S):
        days = (R.get(s['org_id']) or {}).get('%s-%s' % (s['org_id'], s['mloc_id'])) or P.get(i) or {}
        name = (s.get('mloc_name') or '').strip()
        if not name or name.upper() == 'UNKNOWN':
            name = s['mloc_id']
        row = [round(s['mloc_latitude'], 5), round(s['mloc_longitude'], 5), name, (s.get('org_name') or s['org_id']).strip(), None, None, None, 0, 0]
        if days:
            last = max(days)
            row[4], row[5], row[6] = last, days[last][0], days[last][1]
            row[7] = len(days)                                                             # sampling days in the 18 months
            row[8] = sum(1 for d in days if days[d][0] > LIMIT[days[d][1]])                # ... of them over the limit
        rows.append(row)
    if len(failed) > len(orgs) * 0.25:
        print('TOO MANY FAILED (%d of %d): not writing' % (len(failed), len(orgs)))
        sys.exit(1)
    json.dump({'built': TODAY.isoformat(), 'n': len(rows), 'failed': failed, 'st': rows}, open(out_path, 'w'), separators=(',', ':'))
    have = [r for r in rows if r[4]]
    age = lambda r: (TODAY - datetime.date.fromisoformat(r[4])).days
    print('wrote', out_path, os.path.getsize(out_path) // 1024, 'KB')
    print('stations', len(rows), '| with a result in 18 months', len(have), '| within 14 days', sum(1 for r in have if age(r) <= 14),
          '| within 60 days', sum(1 for r in have if age(r) <= 60), '| this year', sum(1 for r in have if r[4][:4] == str(TODAY.year)), '| failed orgs', failed)


if __name__ == '__main__':
    main()
