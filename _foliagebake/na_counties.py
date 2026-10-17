#!/usr/bin/env python3
"""THE COUNTIES FOR THE NATIONAL FOLIAGE MAP (2026-10-17). The Northeast bake's county_shapes() (_maplab/foliage_bake.py)
for every US county: the Census outlines from plotly's GeoJSON mirror (2010 cartographic boundaries), simplified and
written in the Northeast file's own shape, {fips: {n: name, s: state, r: [[[lon, lat], ...], ...]}}, coordinates to three
decimals (~100 m) so the whole country stays near 1 MB. Run once; uploaded to foliage/na/counties.json.

    python3 na_counties.py OUT/counties.json [geojson]
"""
import json, sys, urllib.request
import shapely.geometry as sg

SRC = 'https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json'
STATE = {'01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA', '08': 'CO', '09': 'CT', '10': 'DE', '11': 'DC',
         '12': 'FL', '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN', '19': 'IA', '20': 'KS', '21': 'KY',
         '22': 'LA', '23': 'ME', '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS', '29': 'MO', '30': 'MT',
         '31': 'NE', '32': 'NV', '33': 'NH', '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND', '39': 'OH',
         '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI', '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT',
         '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI', '56': 'WY', '72': 'PR'}
TOL = 0.01


def main():
    out_path = sys.argv[1]
    if len(sys.argv) > 2:
        j = json.load(open(sys.argv[2]))
    else:
        j = json.loads(urllib.request.urlopen(urllib.request.Request(SRC, headers={'User-Agent': 'bluishvoid.com foliage bake'}), timeout=120).read())
    out = {}
    for f in j.get('features', []):
        fid = str(f.get('id') or '')
        st = STATE.get(fid[:2])
        if not st or st in ('HI', 'PR'):        # the forest grid stops at 24 N
            continue
        g = sg.shape(f['geometry']).simplify(TOL, preserve_topology=True)
        polys = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
        rings = []
        for pg in polys:
            if pg.is_empty:
                continue
            r = []
            for x, y in pg.exterior.coords:
                pt = [round(x, 3), round(y, 3)]
                if not r or r[-1] != pt:
                    r.append(pt)
            if len(r) >= 4:
                rings.append(r)
        if rings:
            out[fid] = {'n': (f.get('properties') or {}).get('NAME'), 's': st, 'r': rings}
    with open(out_path, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'))
    print('counties:', len(out))


if __name__ == '__main__':
    main()
