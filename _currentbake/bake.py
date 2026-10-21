#!/usr/bin/env python3
"""TIDAL CURRENTS AND TIDE GAUGES FROM THE CDN (user 2026-10-17: "do 1-4"). The TIDES view asked NOAA CO-OPS for each current
station in view (up to 40 requests a view) and downloaded the full 777 KB water-level station list every session. Both are
fixed tables, so they are baked daily here:

  sea/currents/c_<LAT>_<LON>.json   every current-prediction station in that 2-degree cell (LAT/LON = the cell's south-west
                                    corner): {s:[{i,b,la,lo,n,fd,ed,t0,e:[[minutes after t0, knots], ...]}]}, from yesterday
                                    00:00 UTC for four days; harmonic stations every 30 min, subordinate ones their slack and
                                    maximum events. Positive knots = flood toward fd (degrees), negative = ebb toward ed.
  sea/currents/index.json           the cells that exist
  sea/tide_stations.json            the tidal water-level gauges (Great Lakes excluded): [[id, name, state, lat, lng, shef], ...]

    python3 bake.py OUTDIR
"""
import datetime, json, math, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
CO = 'https://api.tidesandcurrents.noaa.gov/'
def get(u):
    for a in range(4):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluishvoid.com current bake'}), timeout=60).read())
        except Exception:
            if a == 3: return None
            time.sleep(3 * (a + 1))
def main(out):
    os.makedirs(os.path.join(out, 'currents'), exist_ok=True)
    tl = get(CO + 'mdapi/prod/webapi/stations.json?type=waterlevels') or {}
    ts = [[s['id'], s['name'], s.get('state') or '', round(float(s['lat']), 4), round(float(s['lng']), 4), s.get('shefcode') or ''] for s in tl.get('stations', []) if s.get('tidal') and not s.get('greatlakes')]
    # A GAUGE CODE ONLY WHERE THE RIVER SERVICE HAS THE GAUGE (2026-10-20 review): the page asks NWPS for the station's
    # stageflow by its SHEF code, and 50 of 238 codes are not NWPS gauges (Santa Monica's ICAC1: "could not find gauge ID"),
    # one red 404 each time that station is the nearest. NWPS's full list (~13 MB) is read once here; if it fails, the codes stand.
    nw = get('https://api.water.noaa.gov/nwps/v1/gauges')
    lids = {g.get('lid', '').upper() for g in (nw or {}).get('gauges', [])}
    if len(lids) > 5000:
        gone = [r[5] for r in ts if r[5] and r[5].upper() not in lids]
        for r in ts:
            if r[5] and r[5].upper() not in lids: r[5] = ''
        print('gauge codes not in NWPS, dropped', len(gone))
    json.dump(ts, open(os.path.join(out, 'tide_stations.json'), 'w'), separators=(',', ':')); print('tide stations', len(ts))
    cl = get(CO + 'mdapi/prod/webapi/stations.json?type=currentpredictions&units=english') or {}
    st = {}
    for s in cl.get('stations', []):
        if s.get('type') == 'W': continue
        k = s['id']
        if k in st and (st[k]['b'] or 99) <= (s.get('currbin') or 99): continue
        lo = s['lng']
        # NOAA lists the Savannah River stations (SAV23xx) at +80.9 E -- the Himalayas; every CO-OPS station east of 0 is a
        # flipped sign except the western Aleutians, past 170 E (2026-10-20 review)
        if 0 < lo < 170: lo = -lo
        st[k] = {'i': k, 'b': s.get('currbin'), 'la': round(s['lat'], 4), 'lo': round(lo, 4), 'n': s['name'][:48], 'h': s.get('type') == 'H'}
    d0 = datetime.datetime.utcnow().date() - datetime.timedelta(days=1); t0 = datetime.datetime(d0.year, d0.month, d0.day)
    def one(s):
        base = CO + 'api/prod/datagetter?product=currents_predictions&station=%s%s&begin_date=%s&range=96&units=english&time_zone=gmt&format=json&application=bluishvoid' % (s['i'], '&bin=%s' % s['b'] if s['b'] else '', d0.strftime('%Y%m%d'))
        j = get(base + ('&interval=30' if s['h'] else '')) if s['h'] else None
        if not j or 'current_predictions' not in j: j = get(base + '&interval=MAX_SLACK') or get(base)
        cp = ((j or {}).get('current_predictions') or {}).get('cp') or []
        if not cp: return None
        e = []
        for r in cp:
            try: t = datetime.datetime.strptime(r['Time'], '%Y-%m-%d %H:%M')
            except Exception: continue
            e.append([int((t - t0).total_seconds() // 60), round(float(r.get('Velocity_Major') or 0), 2)])
        o = {k: s[k] for k in ('i', 'b', 'la', 'lo', 'n')}; o['fd'] = cp[0].get('meanFloodDir'); o['ed'] = cp[0].get('meanEbbDir'); o['t0'] = t0.strftime('%Y-%m-%dT%H:%MZ'); o['e'] = e
        return o
    with ThreadPoolExecutor(8) as ex: res = [r for r in ex.map(one, list(st.values())) if r]
    cells = {}
    for r in res: cells.setdefault('c_%d_%d' % (math.floor(r['la'] / 2) * 2, math.floor(r['lo'] / 2) * 2), []).append(r)
    for k, v in cells.items(): json.dump({'s': v}, open(os.path.join(out, 'currents', k + '.json'), 'w'), separators=(',', ':'))
    json.dump({'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'cells': sorted(cells)}, open(os.path.join(out, 'currents', 'index.json'), 'w'), separators=(',', ':'))
    print('current stations', len(res), 'of', len(st), 'cells', len(cells))
if __name__ == '__main__': main(sys.argv[1])
