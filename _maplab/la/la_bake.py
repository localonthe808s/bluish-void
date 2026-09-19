#!/usr/bin/env python3
"""
THE BASIN -- the data bake for the Los Angeles lab view (built 2026-09-19).

Everything the `la` view in ../index.html draws, pulled from its publisher and
written next to this file in the shapes the NYC draw functions already read, so
the lab paints Los Angeles with the same code that paints New York:

    la_city.json        the City of Los Angeles boundary (the orange mask)      LA City Planning
    la_hoods.json       its 114 neighbourhoods, traced inside the mask          LA Times Mapping L.A.
    hood_labels.json    one label point per neighbourhood, ranked by area
    rail_lines.json     Metro Rail + Metrolink track, one shape per route       the agencies' own GTFS
    rail_stops.json     every station, with the routes that call there
    rail_colours.json   route -> the agency's published colour
    faults.json         Quaternary faults                                       USGS Qfaults
    land_relief.json    terrain veils at fixed heights                          NOAA NCEI DEM mosaic
    la_bathy.json       seafloor bands at fixed depths                          the same grid

    python3 la_bake.py            # everything
    python3 la_bake.py rail dem   # only those parts (city, rail, faults, dem)

The DEM is ONE pull far wider than the home box (Channel Islands to the San
Gorgonio Pass) so a pan never runs off the terrain. Contours leave here as
lon/lat vectors and are projected at draw time -- nothing raster is resampled
into mercator, which is the trap the New York seafloor fell into twice.
"""
import csv
import io
import json
import math
import os
import sys
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict

import numpy as np
import tifffile
from scipy import ndimage
from shapely.geometry import LineString, Polygon, shape
from shapely.ops import unary_union
from skimage import measure

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'bluishvoid.com map lab'}

# the home framing, at the New York widget's aspect (1.1372 in mercator)
HOME_W, HOME_E, HOME_S = -118.85, -117.95, 33.69
# the DEM pull, and the fault query, reach well past it
PULL = (-119.60, 33.20, -117.30, 34.75)
DEM_SIZE = (2300, 1550)                       # 0.001 deg a pixel, ~100 m

TERRAIN_LEVELS = (150, 300, 600, 1200, 1800, 2400)
BATHY_LEVELS = (10, 25, 50, 100, 200, 400, 600, 800)

CITY_URL = ('https://services1.arcgis.com/tzwalEyxl2rpamKs/arcgis/rest/services/'
            'Los_Angeles_City_Boundary/FeatureServer/0')
HOODS_URL = ('https://services5.arcgis.com/7nsPwEMP38bSkCjy/arcgis/rest/services/'
             'LA_Times_Neighborhoods/FeatureServer/0')
QFAULTS = 'https://earthquake.usgs.gov/arcgis/rest/services/haz/Qfaults/MapServer'
METRO_GTFS = 'https://gitlab.com/LACMTA/gtfs_rail/raw/master/gtfs_rail.zip'
METROLINK_GTFS = 'https://metrolinktrains.com/globalassets/about/gtfs/gtfs.zip'
DEM_SRC = ('https://gis.ngdc.noaa.gov/arcgis/rest/services/DEM_mosaics/DEM_all/'
           'ImageServer/exportImage')


def get(url, timeout=180):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def home_box():
    R = 6378137.0
    y = lambda la: R * math.log(math.tan(math.pi / 4 + math.radians(la) / 2))      # noqa: E731
    h = (math.radians(HOME_E - HOME_W) * R) / 1.1372
    n = math.degrees(2 * math.atan(math.exp((y(HOME_S) + h) / R)) - math.pi / 2)
    return HOME_W, HOME_S, HOME_E, round(n, 4)


def write(name, obj):
    p = os.path.join(HERE, name)
    with open(p, 'w') as f:
        json.dump(obj, f, separators=(',', ':'))
    print('  %-18s %6d KB' % (name, os.path.getsize(p) // 1024))


def rnd(ring, n=5):
    return [[round(x, n), round(y, n)] for x, y in ring]


def arcgis_geojson(layer, where='1=1', extra=''):
    out, off = [], 0
    while True:
        u = ('%s/query?where=%s&outFields=*&outSR=4326&f=geojson&resultOffset=%d%s'
             % (layer, urllib.parse.quote(where), off, extra))
        j = json.loads(get(u))
        fs = j.get('features') or []
        out += fs
        if not fs or not (j.get('exceededTransferLimit') or (j.get('properties') or {}).get('exceededTransferLimit')):
            return out
        off += len(fs)


# ------------------------------------------------------------------ city ----
def flat_rings(geom, tol, min_area=0.0):
    """Every ring of a (multi)polygon as one flat list -- the lab paths each ring
    and fills evenodd, so holes (Beverly Hills, West Hollywood, San Fernando)
    stay holes without any nesting."""
    g = geom.simplify(tol, preserve_topology=True)
    polys = [g] if g.geom_type == 'Polygon' else list(g.geoms)
    rings = []
    for p in polys:
        if p.area < min_area:
            continue
        rings.append(rnd(p.exterior.coords))
        rings += [rnd(i.coords) for i in p.interiors if Polygon(i).area >= min_area]
    return rings


def bake_city():
    print('city + neighbourhoods')
    fs = arcgis_geojson(CITY_URL)
    city = unary_union([shape(f['geometry']).buffer(0) for f in fs])
    print('  city %.0f km2 (published: 1,302)' % (city.area * 111.32 * 111.32 * math.cos(math.radians(34.05))))
    write('la_city.json', {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'name': 'Los Angeles'},
         'geometry': {'type': 'Polygon', 'coordinates': flat_rings(city, 0.00008, 2e-7)}}]})
    hs = arcgis_geojson(HOODS_URL)
    feats, labels = [], []
    rows = []
    for f in hs:
        g = shape(f['geometry']).buffer(0)
        nm = (f['properties'].get('name') or '').strip()
        if nm and not g.is_empty:
            rows.append((g.area, nm, g))
    rows.sort(reverse=True)
    for i, (a, nm, g) in enumerate(rows):
        feats.append({'type': 'Feature', 'properties': {'name': nm, 'boro': 'LA'},
                      'geometry': {'type': 'Polygon', 'coordinates': flat_rings(g, 0.00008, 1e-7)}})
        p = g.representative_point()
        big = max(([g] if g.geom_type == 'Polygon' else list(g.geoms)), key=lambda q: q.area)
        c = big.centroid if big.contains(big.centroid) else p
        labels.append({'type': 'Feature',
                       'properties': {'name': nm, 'rank': 1 if i < 24 else (2 if i < 70 else 3), 'b': 'LA',
                                      'bbox': [round(v, 5) for v in big.bounds]},
                       'geometry': {'type': 'Point', 'coordinates': [round(c.x, 5), round(c.y, 5)]}})
    write('la_hoods.json', {'type': 'FeatureCollection', 'features': feats})
    write('hood_labels.json', {'type': 'FeatureCollection', 'features': labels})


# ------------------------------------------------------------------ rail ----
def gtfs(url):
    z = zipfile.ZipFile(io.BytesIO(get(url)))
    rd = lambda n: list(csv.DictReader(io.TextIOWrapper(z.open(n), 'utf-8-sig'))) if n in z.namelist() else []   # noqa: E731
    return rd


# Metrolink's trips carry no shape_id: its shapes are named for the line instead
# ("AVin" / "AVout"), so the join is written down here rather than guessed
METROLINK_SHAPES = {'Antelope Valley Line': 'AVin', 'Inland Emp.-Orange Co. Line': 'IEOCin',
                    'Orange County Line': 'OCin', 'Riverside Line': 'RIVERin',
                    'San Bernardino Line': 'SBin', 'Ventura County Line': 'VTin', '91 Line': '91in'}


def rail_from(rd, kind, name_of, shape_of=None):
    routes = {r['route_id']: r for r in rd('routes.txt')}
    trips = rd('trips.txt')
    shp = defaultdict(list)
    for r in rd('shapes.txt'):
        shp[r['shape_id']].append((int(r['shape_pt_sequence']), float(r['shape_pt_lon']), float(r['shape_pt_lat'])))
    by_route = defaultdict(Counter)
    trip_route = {}
    for t in trips:
        trip_route[t['trip_id']] = t['route_id']
        sid = t.get('shape_id') or (shape_of or {}).get(t['route_id'])
        if sid:
            by_route[t['route_id']][sid] += 1
    lines, colours = [], {}
    for rid, cnt in by_route.items():
        r = routes[rid]
        label = name_of(r)
        # the LONGEST shape the route runs: short-turns and yard moves are subsets of it
        best = max(cnt, key=lambda s: LineString([(x, y) for _, x, y in sorted(shp[s])]).length if len(shp[s]) > 1 else 0)
        ls = LineString([(x, y) for _, x, y in sorted(shp[best])]).simplify(0.00012)
        col = '#' + (r.get('route_color') or '6b7280').strip('#')
        colours[label] = col
        lines.append({'type': 'Feature',
                      'properties': {'route': label, 'name': (r.get('route_long_name') or label).strip(), 'colour': col,
                                     'kind': kind, 'len_m': int(ls.length * 111320 * math.cos(math.radians(34)))},
                      'geometry': {'type': 'LineString', 'coordinates': rnd(ls.coords)}})
    # stations: a parent where the feed has one, the stop itself where it does not
    stops = {s['stop_id']: s for s in rd('stops.txt')}
    parent = lambda sid: (stops[sid].get('parent_station') or sid) if sid in stops else sid     # noqa: E731
    calls = defaultdict(set)
    plat = defaultdict(set)
    for st in rd('stop_times.txt'):
        rid = trip_route.get(st['trip_id'])
        if rid in by_route:
            p = parent(st['stop_id'])
            calls[p].add(name_of(routes[rid]))
            plat[p].add(st['stop_id'])
    out = []
    for p, rts in calls.items():
        s = stops.get(p)
        if not s or not s.get('stop_lat'):
            continue
        nm = s['stop_name'].replace(' Station', '').replace(' Metrolink', '').strip()
        out.append({'type': 'Feature',
                    'properties': {'name': nm, 'id': p, 'routes': sorted(rts), 'platforms': len(plat[p]), 'kind': kind},
                    'geometry': {'type': 'Point', 'coordinates': [round(float(s['stop_lon']), 5), round(float(s['stop_lat']), 5)]}})
    return lines, out, colours


def bake_rail():
    print('rail')
    # Metro Rail's lines ARE letters (A B C D E K), which is exactly what the
    # station bullets were built to show
    ml, ms, mc = rail_from(gtfs(METRO_GTFS), 'metro',
                           lambda r: (r.get('route_short_name') or r.get('route_long_name') or r['route_id']).replace('Metro ', '').replace(' Line', '').strip())
    kl, ks, kc = rail_from(gtfs(METROLINK_GTFS), 'commuter',
                           lambda r: (r.get('route_short_name') or r.get('route_long_name') or r['route_id']).replace(' Line', '').strip(),
                           METROLINK_SHAPES)
    print('  metro %s | metrolink %s' % (sorted(mc), sorted(kc)))
    mc.update(kc)
    write('rail_lines.json', {'type': 'FeatureCollection', 'features': kl + ml})     # commuter under metro
    write('rail_stops.json', {'type': 'FeatureCollection', 'features': ks + ms})
    write('rail_colours.json', mc)


# ---------------------------------------------------------------- faults ----
def bake_faults():
    print('faults')
    meta = json.loads(get(QFAULTS + '?f=json'))
    ids = [l['id'] for l in meta['layers'] if 'California' in l['name'] and not l.get('subLayerIds')]
    env = '&geometry=%f,%f,%f,%f&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects' % PULL
    feats = []
    for i in ids:
        for f in arcgis_geojson('%s/%d' % (QFAULTS, i), extra=env):
            g = f.get('geometry') or {}
            if g.get('type') not in ('LineString', 'MultiLineString'):
                continue
            p = {k.lower(): v for k, v in f['properties'].items()}
            parts = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates']
            for c in parts:
                ls = LineString([(x[0], x[1]) for x in c]).simplify(0.0002)
                if ls.length < 0.002:
                    continue
                feats.append({'type': 'Feature',
                              'properties': {'name': p.get('fault_name') or p.get('name'), 'section': p.get('section_name'),
                                             'age': p.get('age'), 'slip_rate': p.get('slip_rate'),
                                             'sense': p.get('slip_sense'), 'certainty': p.get('mapped_certainty') or p.get('linetype')},
                              'geometry': {'type': 'LineString', 'coordinates': rnd(ls.coords)}})
    print('  %d traces; %s' % (len(feats), Counter(f['properties']['age'] for f in feats).most_common(6)))
    print('  busiest: %s' % Counter(f['properties']['name'] for f in feats).most_common(8))
    write('faults.json', {'type': 'FeatureCollection', 'features': feats})


# ------------------------------------------------------------------- dem ----
def contour_rings(field, level, above, tol=0.0006, min_pts=14):
    """Closed rings (lon/lat) round the region above/below `level`. The grid is
    padded with a value on the far side of the level so every ring closes on
    the frame instead of running off it."""
    w, s, e, n = PULL
    H, W = field.shape
    pad = np.pad(field, 1, constant_values=(-1e5 if above else 1e5))
    rings = []
    for c in measure.find_contours(pad, level):
        if len(c) < min_pts:
            continue
        lon = w + (c[:, 1] - 1 + 0.5) / W * (e - w)
        lat = n - (c[:, 0] - 1 + 0.5) / H * (n - s)
        ls = LineString(np.column_stack([lon, lat])).simplify(tol)
        if len(ls.coords) >= 4:
            rings.append(rnd(list(ls.coords) + [ls.coords[0]]))
    return rings


def bake_dem():
    print('terrain + seafloor')
    w, s, e, n = PULL
    q = {'bbox': '%f,%f,%f,%f' % PULL, 'bboxSR': 4326, 'imageSR': 4326, 'size': '%d,%d' % DEM_SIZE,
         'format': 'tiff', 'pixelType': 'F32', 'noData': -9999,
         'interpolation': 'RSP_BilinearInterpolation', 'f': 'image'}
    a = tifffile.imread(io.BytesIO(get(DEM_SRC + '?' + urllib.parse.urlencode(q), 300))).astype('float32')
    print('  grid %s, %.0f to %.0f m' % (a.shape, a[a > -9000].min(), a.max()))
    # a veil is a shape to read from across the room, not a survey: soften the
    # grid first so a terrace edge is a line and not a fringe of 100 m teeth
    land = ndimage.gaussian_filter(a, 1.6)
    sea = ndimage.gaussian_filter(a, 2.2)
    write('land_relief.json', {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'h': h},
         'geometry': {'type': 'Polygon', 'coordinates': contour_rings(land, h, True)}} for h in TERRAIN_LEVELS]})
    write('la_bathy.json', {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'d': d},
         'geometry': {'type': 'Polygon', 'coordinates': contour_rings(sea, -d, False)}} for d in BATHY_LEVELS]})


PARTS = {'city': bake_city, 'rail': bake_rail, 'faults': bake_faults, 'dem': bake_dem}

if __name__ == '__main__':
    print('home box  w %.4f  s %.4f  e %.4f  n %.4f' % home_box())
    for k in (sys.argv[1:] or list(PARTS)):
        PARTS[k]()
