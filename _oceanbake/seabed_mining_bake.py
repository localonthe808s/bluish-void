#!/usr/bin/env python3
"""DEEP-SEA MINING (user 2026-11-08: "is there data tracking the clarion clipperton zone and its mining & research focus" -> "yes").

One GeoJSON of the seabed's mining claims beyond national jurisdiction:
  nod   ISA polymetallic-nodule exploration contract areas (GEOMAR's compilation of ISA documents, Feb 2022, CC BY 4.0)
  sul   ISA polymetallic-sulphide exploration blocks (GEOMAR 2023, CC BY 4.0)
  cru   ISA cobalt-rich crust exploration blocks (GEOMAR 2023, CC BY 4.0)
  apei  ISA Areas of Particular Environmental Interest, the CCZ's no-mining zones (GEOMAR 2022, from ISA decisions)
  us    US NOAA DSHMRA application areas (TMC USA and others): an UNOFFICIAL compilation (Esri, from NOAA dockets), labelled so
Out: R2 ocean/seabed_mining_v1.json     python3 seabed_mining_bake.py OUT.json [--upload]
"""
import json, subprocess, sys, urllib.request
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com seabed mining bake)'}
G = 'https://services3.arcgis.com/2LJ6Q6yCIIUOP8qx/arcgis/rest/services/%s/FeatureServer/%d/query?where=1%%3D1&outFields=*&outSR=4326&f=geojson&geometryPrecision=3'
US = 'https://services.arcgis.com/xfNoiwYbWwrd3CKg/arcgis/rest/services/US_Deep_Seabed_Mining_Application_Areas/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson&geometryPrecision=3'
SRC = [('nod', 'PN_AllExplorationAreas_Feb22', 0), ('sul', 'PS_All_Licenses2023', None), ('cru', 'PC_AllLicenses2023', None), ('apei', 'APEI_2022_Web', None)]


def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=180))


def lid(svc):
    return get('https://services3.arcgis.com/2LJ6Q6yCIIUOP8qx/arcgis/rest/services/%s/FeatureServer?f=json' % svc)['layers'][0]['id']


def main(out, up):
    F = []
    for k, svc, l in SRC:
        for f in get(G % (svc, lid(svc) if l is None else l))['features']:
            p = f['properties']; g = lambda *ks: next((p[x] for x in ks if p.get(x) not in (None, '', 'n_a', 'nn')), None)
            q = {'k': k, 'inv': g('Investor'), 'ty': g('TypeOfArea'), 'doc': g('ISA_Doc', 'DocOfAppr'), 'st': g('ContrStart'), 'ex': g('ExpirDate', 'ExpDate', 'ExpiryDate'),
                 'cl': g('Cluster'), 'nm': g('Area_ID', 'Remarks'), 'km2': g('SizeKm2Cal', 'SizeKm2', 'CompleteContractArea_km2')}
            try: q['km2'] = round(float(q['km2'])) if q['km2'] is not None else None
            except Exception: q['km2'] = None
            F.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': {a: b for a, b in q.items() if b is not None}})
        print(k, sum(1 for x in F if x['properties']['k'] == k))
    for f in get(US)['features']:
        p = f['properties']
        F.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': {'k': 'us', 'inv': p.get('applicant'), 'nm': p.get('area_name'), 'ty': p.get('program'), 'st8': p.get('status'),
                                                                           'doc': p.get('docket'), 'km2': round(p['computed_km2']) if p.get('computed_km2') else None}})
    print('us', sum(1 for x in F if x['properties']['k'] == 'us'))
    json.dump({'type': 'FeatureCollection', 'features': F}, open(out, 'w'), separators=(',', ':'))
    if up: subprocess.run(['rclone', 'copyto', out, 'r2:bluishvoid-bg/ocean/seabed_mining_v1.json', '--s3-no-check-bucket', '--header-upload', 'Content-Type: application/json',
                           '--header-upload', 'Cache-Control: public, max-age=86400'], check=True)


if __name__ == '__main__':
    main(sys.argv[1], '--upload' in sys.argv)
