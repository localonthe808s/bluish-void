#!/usr/bin/env python3
"""
THE OIL AND GAS UNDER THE EARTHQUAKE TAB (2026-10-03; user: "bake all 50 and add the basins"). us_energy.json held 8 of
EIA's 50 tight-oil / shale-gas plays (hand-picked in September) and an empty basin list. This bakes all of them straight
from the EIA Energy Atlas (public, keyless ArcGIS feature services):

    plays   TightOil_ShaleGas_Plays_Lower48_EIA   50 polygons: play, basin, lithology
    basins  SedimentaryBasins_US_EIA               the sedimentary basins they sit in

Geometry is simplified server-side (maxAllowableOffset, degrees) -- a play outline only has to read at the hazard map's
national zooms -- and each ring becomes its own entry, [lat, lon] pairs to 3 decimals, as the map already reads them.

    python3 _maplab/us_energy_bake.py        # writes us_energy.json at the repo root
"""
import json, os, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'us_energy.json')
SVC = 'https://services7.arcgis.com/FGr1D95XCGALKXqM/arcgis/rest/services/%s/FeatureServer/%d/query'


def query(service, fields, offset, layer=0):
    q = {'where': '1=1', 'outFields': fields, 'returnGeometry': 'true', 'outSR': 4326, 'f': 'json',
         'maxAllowableOffset': offset, 'geometryPrecision': 3}
    req = urllib.request.Request(SVC % (service, layer) + '?' + urllib.parse.urlencode(q), headers={'User-Agent': 'bluishvoid.com energy bake'})
    d = json.load(urllib.request.urlopen(req, timeout=120))
    if 'error' in d:
        raise RuntimeError('%s: %s' % (service, d['error']))
    return d['features']


def rings(geom, min_pts=4):
    out = []
    for r in (geom or {}).get('rings') or []:
        pts = [[round(y, 3), round(x, 3)] for x, y in r]
        if len(pts) >= min_pts:
            out.append(pts)
    return out


def area(r):
    return abs(sum(r[i][1] * r[i + 1][0] - r[i + 1][1] * r[i][0] for i in range(len(r) - 1))) / 2


def main():
    plays, basins = [], []
    for f in query('TightOil_ShaleGas_Plays_Lower48_EIA', 'Shale_play,Basin,Lithology,Area_sq_mi', 0.01):
        a = f['attributes']
        name = ' '.join((a.get('Shale_play') or '').split()).replace(' -', '-').replace('- ', '-')
        for r in rings(f.get('geometry')):
            if area(r) < 0.02:
                continue                                   # slivers left by simplification
            plays.append({'n': name, 'b': (a.get('Basin') or '').strip(), 'l': (a.get('Lithology') or '').strip(), 'p': r})
    try:
        bf = query('SedimentaryBasins_US_EIA', '*', 0.03, 109)   # the service's one layer is 109, not 0
    except Exception as e:
        raise SystemExit('basins: %s' % e)
    key = None
    for f in bf:
        a = f['attributes']
        if key is None:
            key = next((k for k in a if k.lower() in ('name', 'basin_name', 'basin', 'province')), None)
        for r in rings(f.get('geometry'), 6):
            if area(r) < 0.3:
                continue
            basins.append({'n': (a.get(key) or '').strip().title() if key else '', 'p': r})
    doc = {'plays': plays, 'basins': basins,
           'source': 'EIA Energy Atlas: TightOil_ShaleGas_Plays_Lower48_EIA, SedimentaryBasins_US_EIA',
           'names': sorted(set(p['n'] for p in plays))}
    with open(OUT, 'w') as fh:
        json.dump(doc, fh, separators=(',', ':'))
    print('plays: %d rings, %d named plays; basins: %d rings (name field %r); %d KB'
          % (len(plays), len(doc['names']), len(basins), key, os.path.getsize(OUT) // 1024))


if __name__ == '__main__':
    main()
