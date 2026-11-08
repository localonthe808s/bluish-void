#!/usr/bin/env python3
"""EASTERN SEISMIC ZONES for GEOLOGY › EARTHQUAKES' NAMED FAULTS (user 2026-11-07: "do we have the madrid fault visualized along arkansas
mississippi missouri tennessee for earthquakes / named faults"). East of the Rockies the faults are buried, so the USGS Quaternary Fault and
Fold Database maps them as fault AREAS (MapServer layer 22), not lines: this pulls the named eastern areas, simplified, into one GeoJSON.
Source: https://earthquake.usgs.gov/arcgis/rest/services/haz/Qfaults/MapServer/22 (public domain).

    python3 east_zones.py OUT.json
"""
import json, sys, urllib.request, urllib.parse
QF = 'https://earthquake.usgs.gov/arcgis/rest/services/haz/Qfaults/MapServer/22/query'
KEEP = {'Reelfoot scarp and New Madrid seismic zone': 'NEW MADRID SEISMIC ZONE', 'Wabash Valley liquefaction features': 'WABASH VALLEY',
        'Charleston liquefaction features': 'CHARLESTON', 'Central Virginia seismic zone': 'CENTRAL VIRGINIA',
        'Western Lowlands liquefaction features': 'WESTERN LOWLANDS', 'St. Louis-Cape Girardeau liquefaction features': 'ST. LOUIS–CAPE GIRARDEAU',
        'Fluorspar Area fault complex': 'FLUORSPAR AREA FAULTS'}
def main(out):
    q = {'f': 'geojson', 'where': '1=1', 'geometry': '-100,24,-66,50', 'geometryType': 'esriGeometryEnvelope', 'inSR': 4326, 'outSR': 4326,
         'outFields': 'fault_area_name,age,slipsense', 'returnGeometry': 'true', 'maxAllowableOffset': 0.004, 'geometryPrecision': 4}
    j = json.loads(urllib.request.urlopen(urllib.request.Request(QF + '?' + urllib.parse.urlencode(q), headers={'User-Agent': 'bluishvoid.com bake'}), timeout=120).read())
    F = []
    for f in j.get('features', []):
        p = f['properties']; nm = p.get('fault_area_name')
        if nm in KEEP and f.get('geometry'): F.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': {'n': KEEP[nm], 'src': nm, 'age': (p.get('age') or '').strip()}})
    json.dump({'type': 'FeatureCollection', 'features': F}, open(out, 'w'), separators=(',', ':'))
    print('zones', len(F), sorted(set(x['properties']['n'] for x in F)))
if __name__ == '__main__': main(sys.argv[1])
