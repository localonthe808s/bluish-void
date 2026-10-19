#!/usr/bin/env python3
"""LOS ANGELES NEIGHBORHOODS FOR THE NATIONAL MAP (2026-10-19).

LOCAL names the neighborhood the place stands in ("SILVER LAKE · LOS ANGELES"). New York's come from the city's own
2020 NTAs (../nta2020_bake.py -> city_nta2020.json); this is the same lookup for the Los Angeles box, with the same
names THE BASIN's hood_labels.json carries (la_bake.py bake_city) -- but as POLYGONS, and NOT clipped to the urban
footprint: the labels only need the built-up part of a place, a lookup needs all of it, or a point in the hills above
Brentwood finds nothing.

The naming rules are bake_city's, so the header and THE BASIN's labels agree:
  - LA County's Countywide Statistical Areas: a COMMUNITY name only inside the City of Los Angeles and in
    unincorporated land; every other city is its city name. Long Beach's rows are planning districts ("Eastside",
    "Downtown" -- and its Downtown is not LA's), so they collapse to Long Beach, as every other city's would.
    RENAME as in la_bake.py. Unlike the labels, the water, pier and breakwater rows are KEPT, under the same rule:
    every one carries its place's name (San Pedro's harbor, Marina del Rey's basin, the Santa Monica Pier), so a
    point on the Port of Los Angeles finds San Pedro instead of nothing.
  - beyond the County line (Orange, Ventura, San Bernardino, Riverside), Census incorporated places and census
    designated places, taken only where the County layer is silent. Unincorporated land that is in no CDP stays
    nameless: nothing found is shown as nothing, never a guess.

The PARENT (the page shows "NAME · PARENT"):
  - a City of Los Angeles community        -> "Los Angeles"
  - any other LA County city, Long Beach,
    and unincorporated LA County            -> "Los Angeles County"
  - a Census place                          -> its county ("Orange County"), by the county holding the place's
                                               representative point

Input:  fetched on the first run into CACHE (one GeoJSON per source), reused after that
          CSA      public.gis.lacounty.gov .../LACounty_Dynamic/Political_Boundaries/MapServer/23
          places   tigerweb.geo.census.gov .../TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4 and /5
          counties tigerweb.geo.census.gov .../TIGERweb/State_County/MapServer/1
Output: hoods.json  {"src": ..., "box": [w, s, e, n], "a": [[name, parent, bbox, polys], ...]}
          bbox:  [w, s, e, n] of that place's (clipped) polygons
          polys: [[ring, ...], ...] -- outer ring then its holes, rings of [lon, lat], simplified 0.0002 deg (~20 m),
                 rounded to 1e-5; tested even-odd per polygon, the way NB.inside tests the NTAs
          every place is clipped to the box padded 0.02 deg, so a ring reaching far out of the frame (Angeles
          National Forest, Riverside) does not carry its far edge. Neighbors are simplified independently, so a
          shared edge can open a gap or overlap of up to ~20 m.

  python3 _maplab/la/hoods_bake.py CACHE_DIR [_maplab/la/hoods.json]
"""
import json
import os
import sys
import urllib.parse
import urllib.request

from shapely.geometry import Polygon, box as shp_box, shape
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'bluishvoid.com map lab'}
BOX = (-119.00, 33.60, -117.60, 34.50)
PAD = 0.02
TOL = 0.0002
CSA_URL = ('https://public.gis.lacounty.gov/public/rest/services/LACounty_Dynamic/'
           'Political_Boundaries/MapServer/23')
PLACES_URL = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer'
PLACE_LAYERS = (4, 5)                          # incorporated places, census designated places
COUNTY_URL = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1'
RENAME = {'Silverlake': 'Silver Lake', 'Mid-city': 'Mid-City'}      # la_bake.py's, kept in step by hand


def get(url, timeout=180):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def arcgis_geojson(layer, extra=''):
    out, off = [], 0
    while True:
        u = ('%s/query?where=1%%3D1&outFields=*&outSR=4326&f=geojson&resultOffset=%d%s' % (layer, off, extra))
        j = json.loads(get(u))
        fs = j.get('features') or []
        out += fs
        if not fs or not (j.get('exceededTransferLimit') or (j.get('properties') or {}).get('exceededTransferLimit')):
            return out
        off += len(fs)


def cached(cache, name, layer, extra):
    p = os.path.join(cache, name)
    if not os.path.exists(p):
        print('  fetching %s' % name)
        with open(p, 'w') as f:
            json.dump({'type': 'FeatureCollection', 'features': arcgis_geojson(layer, extra)}, f)
    return json.load(open(p))['features']


def polys_of(g):
    if g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    return [q for q in getattr(g, 'geoms', []) if q.geom_type == 'Polygon'] + \
        [r for q in getattr(g, 'geoms', []) if q.geom_type in ('MultiPolygon', 'GeometryCollection') for r in polys_of(q)]


def rnd(coords):
    return [[round(x, 5), round(y, 5)] for x, y in coords]


def main(cache, out):
    os.makedirs(cache, exist_ok=True)
    clip = shp_box(BOX[0] - PAD, BOX[1] - PAD, BOX[2] + PAD, BOX[3] + PAD)
    env = ('&geometry=%f,%f,%f,%f&geometryType=esriGeometryEnvelope&inSR=4326'
           '&spatialRel=esriSpatialRelIntersects&maxAllowableOffset=0.00005' % clip.bounds)

    rows, county = {}, []
    for f in cached(cache, 'csa.geojson', CSA_URL, '&maxAllowableOffset=0.00005'):
        a = f['properties']
        if not f.get('geometry'):
            continue
        g = shape(f['geometry']).buffer(0)
        county.append(g)
        city = (a.get('LCITY') or '').strip()
        nm = (a.get('COMMUNITY') or '').strip() if city in ('Los Angeles', 'Unincorporated') else city
        nm = RENAME.get(nm, nm)
        if not nm:
            continue
        pa = 'Los Angeles' if city == 'Los Angeles' else 'Los Angeles County'
        k = (nm, pa)
        rows[k] = g if k not in rows else rows[k].union(g)
    la_county = unary_union(county).buffer(0.002)
    print('  CSA: %d names' % len(rows))

    counties = [(f['properties'].get('NAME') or f['properties'].get('BASENAME'), shape(f['geometry']).buffer(0))
                for f in cached(cache, 'counties.geojson', COUNTY_URL, env) if f.get('geometry')]
    n0 = len(rows)
    for lyr in PLACE_LAYERS:
        for f in cached(cache, 'places_%d.geojson' % lyr, '%s/%d' % (PLACES_URL, lyr), env):
            nm = (f['properties'].get('BASENAME') or '').strip()
            if not nm or not f.get('geometry'):
                continue
            g = shape(f['geometry']).buffer(0)
            rp = g.representative_point()
            if la_county.contains(rp):
                continue
            pa = next((c for c, cg in counties if cg.contains(rp)), '')
            k = (nm, pa)
            if any(r[0] == nm for r in rows) and k not in rows:
                print('  note: %s also outside the County (%s)' % (nm, pa))
            rows[k] = g if k not in rows else rows[k].union(g)
    print('  Census places: %d' % (len(rows) - n0))

    A = []
    for (nm, pa), g in sorted(rows.items()):
        g = g.intersection(clip)
        if g.is_empty:
            continue
        g = g.simplify(TOL, preserve_topology=True)
        ps = []
        for p in polys_of(g):
            if len(p.exterior.coords) < 4:
                continue
            ps.append([rnd(p.exterior.coords)] + [rnd(i.coords) for i in p.interiors if len(i.coords) >= 4])
        if not ps:
            continue
        b = g.bounds
        A.append([nm, pa, [round(v, 5) for v in b], ps])
    src = ('LA County Countywide Statistical Areas (public.gis.lacounty.gov Political_Boundaries/23) inside the County; '
           'Census TIGERweb incorporated places + CDPs and counties beyond it. Built by _maplab/la/hoods_bake.py.')
    with open(out, 'w') as f:
        json.dump({'src': src, 'box': list(BOX), 'a': A}, f, separators=(',', ':'))
    print('  %d places -> %s (%d KB)' % (len(A), out, os.path.getsize(out) // 1024))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'hoods.json'))
