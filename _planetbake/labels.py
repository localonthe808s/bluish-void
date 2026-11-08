#!/usr/bin/env python3
"""Globe labels from the IAU Gazetteer of Planetary Nomenclature (USGS; planetarynames.wr.usgs.gov/shapefiles/<BODY>_nomenclature_center_pts.zip):
each body's biggest named features (plus a few chosen by name), as [lat, lon east -180..180, NAME, 'type, N mi across']. The gazetteer's
center_lon is east-positive 0-360 (checked 2026-11-08: Tycho 348.78, Io's Pele 104.72).

    python3 labels.py ZIPDIR > labels.json
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nomdbf import dbf
SKIP = {'Satellite Feature', 'Landing site name', 'Albedo Feature'}
RULES = {   # body: (how many of the biggest, names always in, types also allowed)
    'MERCURY': (11, ['Caloris Planitia', 'Rachmaninoff', 'Beethoven', 'Rembrandt', 'Hokusai', 'Kuiper', 'Carnegie Rupes'], set()),
    'MOON': (7, ['Tycho', 'Copernicus', 'Kepler', 'Aristarchus', 'Plato', 'Clavius', 'Statio Tranquillitatis'], {'Landing site name'}),
    'IO': (6, ['Pele', 'Loki Patera', 'Prometheus', 'Tvashtar Paterae', 'Ra Patera', 'Boosaule Montes'], set()),
    'EUROPA': (9, ['Pwyll', 'Tyre', 'Callanish', 'Conamara Chaos'], set()),
    'GANYMEDE': (9, ['Galileo Regio', 'Osiris', 'Tros', 'Uruk Sulcus'], set()),
    'CALLISTO': (9, ['Valhalla', 'Asgard', 'Bran', 'Heimdall'], set()),
    'TITAN': (8, ['Kraken Mare', 'Ligeia Mare', 'Punga Mare', 'Xanadu', 'Shangri-La', 'Selk', 'Menrva', 'Ontario Lacus'], {'Albedo Feature'}),
}
def lab(r):
    lon = float(r['center_lon']); lon = lon - 360 if lon > 180 else lon; d = float(r['diameter'] or 0)
    t = r['type'].split(',')[0].strip().lower()
    return [round(float(r['center_lat']), 2), round(lon, 2), r['clean_name'].upper(), t + (', %s mi across' % format(int(round(d * 0.621371)), ',') if d >= 1 else '')]
def main(zd):
    out = {}
    for body, (n, names, also) in RULES.items():
        R = [r for r in dbf(os.path.join(zd, body + '.zip')) if r['approval'].startswith('Adopted')]
        pick = [r for r in R if r['clean_name'] in names]
        rest = sorted([r for r in R if r['type'] not in (SKIP - also) and r not in pick], key=lambda r: -float(r['diameter'] or 0))
        for r in rest:
            if sum(1 for q in pick if q not in [x for x in R if x['clean_name'] in names]) >= n: break
            pick.append(r)
        out[body.lower()] = [lab(r) for r in pick]
        missing = [x for x in names if x not in [r['clean_name'] for r in R]]
        if missing: print(body, 'not found:', missing, file=sys.stderr)
    json.dump(out, sys.stdout, ensure_ascii=False, separators=(',', ':'))
if __name__ == '__main__':
    main(sys.argv[1])
