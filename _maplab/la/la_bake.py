#!/usr/bin/env python3
"""
THE BASIN -- the data bake for the Los Angeles lab view (built 2026-09-19).

Everything the `la` view in ../index.html draws, pulled from its publisher and
written next to this file in the shapes the NYC draw functions already read, so
the lab paints Los Angeles with the same code that paints New York:

    la_urban.json       the built-up basin (the orange mask), no city limits    Census 2020 urban areas
    hood_labels.json    one name per city / neighbourhood / community           LA County CSA layer
    rail_lines.json     Metro Rail + Metrolink track, one shape per route       the agencies' own GTFS
    rail_stops.json     every station, with the routes that call there
    rail_colours.json   route -> the agency's published colour
    faults.json         Quaternary faults                                       USGS Qfaults
    land_relief.json    terrain veils at fixed heights                          NOAA NCEI DEM mosaic
    sea_*.png           seafloor shaded relief, 3 / 1 / 1/3 arc-second tiers     NOAA CRM v2 + Santa Monica DEM
    sea_index.json      where each image sits and the scale it is for

    python3 la_bake.py            # everything
    python3 la_bake.py rail dem   # only those parts (city, rail, faults, dem, sea)

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
from shapely.geometry import box as shp_box
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

URBAN_URL = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Urban/MapServer/6'
PLACES_URL = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer'
PLACE_LAYERS = (4, 5)                          # incorporated places, census designated places
CSA_URL = ('https://public.gis.lacounty.gov/public/rest/services/LACounty_Dynamic/'
           'Political_Boundaries/MapServer/23')
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


# Area is a poor guide to which names matter -- by area the first twelve are Santa
# Clarita, Lancaster, Palmdale -- so the names a map of Los Angeles is expected to carry
# at arm's length are listed. Everything else earns its tier by size.
MARQUEE = {'Downtown', 'Hollywood', 'Santa Monica', 'Beverly Hills', 'West Hollywood', 'Venice', 'Koreatown',
           'Long Beach', 'Pasadena', 'Burbank', 'Glendale', 'Inglewood', 'Culver City', 'Compton', 'San Pedro',
           'Malibu', 'Westwood', 'Silver Lake', 'Echo Park', 'Boyle Heights', 'East Los Angeles', 'Watts',
           'Van Nuys', 'North Hollywood', 'Sherman Oaks', 'Torrance', 'Westchester', 'Highland Park', 'Encino',
           'Northridge', 'Pacific Palisades', 'Brentwood', 'Marina del Rey', 'El Segundo', 'Manhattan Beach',
           'Redondo Beach', 'Downey', 'Whittier', 'Alhambra', 'Pomona', 'El Monte', 'Studio City', 'Mid-City',
           'Los Feliz', 'Crenshaw District', 'Santa Clarita', 'Woodland Hills', 'Calabasas', 'Carson',
           'Anaheim', 'Fullerton', 'Huntington Beach', 'Santa Ana', 'Irvine', 'Newport Beach', 'Garden Grove',
           'Thousand Oaks', 'Simi Valley', 'Oxnard', 'Ontario', 'Riverside', 'San Bernardino', 'Seal Beach'}
HOLE_KM2 = 25.0
RENAME = {'Silverlake': 'Silver Lake', 'Mid-city': 'Mid-City'}


def bake_city():
    """THE ORANGE IS THE BUILT-UP BASIN, NOT A JURISDICTION (user, 2026-09-19: "its all
    LA, properly highlight LA without any of the pretentious borders"). The first pass
    used the City of Los Angeles limit, which is legally exact and reads as nonsense:
    Beverly Hills, West Hollywood, Santa Monica and Culver City came out as black holes
    and Pasadena, Long Beach and East L.A. as not-Los-Angeles. New York's legal city and
    its lived city are the same five boroughs; here they are not.

    So the mask is the Census 2020 urban footprint -- every urban area touching the
    frame, merged -- which stops at the mountains on its own and knows no city limits.
    Closed by 150 m and with holes under 25 km2 filled, because the raw footprint is
    built from census blocks and is pitted with golf courses, rail yards and one naval
    weapons station that came out as a black rectangle beside Long Beach. Filling is
    safe for green space -- the lab repaints parks OVER the mask -- and the big voids
    (the Santa Monicas, the Verdugos, the Puente Hills) stay open, which is the
    terrain reading through. No inner boundary lines at all: the places
    are NAMES inside the shape, from the County's community layer (88 cities, the
    City's neighbourhoods, the unincorporated communities) with the jurisdiction
    dropped from each -- "West Hollywood", never "City of"."""
    print('urban footprint + place names')
    env = ('&geometry=%f,%f,%f,%f&geometryType=esriGeometryEnvelope&inSR=4326'
           '&spatialRel=esriSpatialRelIntersects&maxAllowableOffset=0.0002' % PULL)
    fs = arcgis_geojson(URBAN_URL, extra=env)
    print('  urban areas: %s' % sorted((f['properties'].get('BASENAME') or f['properties'].get('NAME') or '?') for f in fs))
    frame = shp_box(*PULL)
    urban = unary_union([shape(f['geometry']).buffer(0) for f in fs]).intersection(frame)
    urban = urban.buffer(0.0015).buffer(-0.0015)
    KM2 = 111.32 * 111.32 * math.cos(math.radians(34.05))
    parts = []
    for poly in ([urban] if urban.geom_type == 'Polygon' else list(urban.geoms)):
        if poly.area * KM2 < 0.5:
            continue
        parts.append(Polygon(poly.exterior, [h for h in poly.interiors if Polygon(h).area * KM2 >= HOLE_KM2]))
    urban = unary_union(parts)
    print('  footprint %.0f km2 in %d pieces' % (urban.area * KM2, len(parts)))
    write('la_urban.json', {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'name': 'Los Angeles'},
         'geometry': {'type': 'Polygon', 'coordinates': flat_rings(urban, 0.00012)}}]})

    rows = {}
    county = []
    for f in arcgis_geojson(CSA_URL):
        a = f['properties']
        if f.get('geometry'):
            county.append(shape(f['geometry']).buffer(0))
        # a community name only where the County names PLACES with it: inside the City of
        # Los Angeles and in unincorporated land. Long Beach's rows are "Eastside",
        # "Downtown", "Pier" -- planning districts, and its Downtown is not LA's.
        city = (a.get('LCITY') or '').strip()
        nm = (a.get('COMMUNITY') or '').strip() if city in ('Los Angeles', 'Unincorporated') else city
        nm = RENAME.get(nm, nm)
        if not nm or not f.get('geometry') or (a.get('Feat_Type') or 'Land') != 'Land':
            continue
        g = shape(f['geometry']).buffer(0).intersection(urban)       # the part of it that is city
        if g.is_empty or g.area * KM2 < 0.6:
            continue
        rows[nm] = g if nm not in rows else rows[nm].union(g)
    # BEYOND THE COUNTY LINE the County's layer has nothing, and the frame's south-east
    # corner is Orange County: orange, and nameless. Census places (incorporated + CDP)
    # name everything else in the pull -- one national source, so Ventura and the Inland
    # Empire come with it -- and a place is taken only where the County did not speak.
    la_county = unary_union(county).buffer(0.002)
    for lyr in PLACE_LAYERS:
        for f in arcgis_geojson('%s/%d' % (PLACES_URL, lyr), extra=env.replace('0.0002', '0.0003')):
            nm = (f['properties'].get('BASENAME') or '').strip()
            if not nm or nm in rows or not f.get('geometry'):
                continue
            g0 = shape(f['geometry']).buffer(0)
            if la_county.contains(g0.representative_point()):
                continue
            g = g0.intersection(urban)
            if not g.is_empty and g.area * KM2 >= 0.6:
                rows[nm] = g
    ranked = sorted(rows.items(), key=lambda kv: -kv[1].area)
    labels = []
    for i, (nm, g) in enumerate(ranked):
        big = max(([g] if g.geom_type == 'Polygon' else [q for q in g.geoms if q.geom_type == 'Polygon']), key=lambda q: q.area)
        c = big.centroid if big.contains(big.centroid) else big.representative_point()
        labels.append({'type': 'Feature',
                       'properties': {'name': nm, 'rank': 1 if (nm in MARQUEE or i < 12) else (2 if i < 150 else 3), 'b': 'LA',
                                      'bbox': [round(v, 5) for v in big.bounds]},
                       'geometry': {'type': 'Point', 'coordinates': [round(c.x, 5), round(c.y, 5)]}})
    print('  %d places; first: %s' % (len(labels), [l['properties']['name'] for l in labels[:12]]))
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
    write('land_relief.json', {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'h': h},
         'geometry': {'type': 'Polygon', 'coordinates': contour_rings(land, h, True)}} for h in TERRAIN_LEVELS]})


# ------------------------------------------------------------------- sea ----
# THE SEAFLOOR AT THE BEST RESOLUTION THAT EXISTS (user, 2026-09-19: "make sure the pacific
# bathymetry is the best detail we can get"). The first pass contoured one 100 m grid into
# eight flat bands. NOAA's mosaic holds far more than that here -- read from its own
# catalogue, not assumed:
#
#     santa_monica_ca_navd_88   1/3 arc-second (~10 m)   -119.14..-117.80, 33.20..34.20
#     socal_1as (CRM v2)        1 arc-second   (~30 m)   the whole borderland
#
# so the 10 m model covers the ENTIRE home frame out past Catalina: Redondo and Santa
# Monica canyons, the Palos Verdes shelf, the San Pedro escarpment, the harbour channels.
# Three tiers, each drawn only when the view is close enough to use it (`maxMpp`):
#
#     3 arc-second   the whole pull, one image      always
#     1 arc-second   the whole pull, 3 x 2 images   below 60 m/px
#     1/3 arc-second the home frame's sea, 4 images below 25 m/px
#
# LOCK THE RASTER, MEASURED. Asked for 1/3 arc-second with the service's default mosaic
# rule, it answered with something coarse resampled into blocks: on the Redondo Canyon
# slope only 2.2% of horizontally adjacent pixels differed. The same request locked to
# the Santa Monica model: 97.5%. The default order is not "finest on top", so every tier
# names the raster it wants (OBJECTIDs from the service's own catalogue).
RASTER = {'13as': 173, '1as': 196, '3as': 197}     # santa_monica_ca_navd_88, socal_1as, socal_3as
#
# ONE COLOUR PER PIXEL: a depth ramp that starts AT the map's own water colour and walks
# down into the navy, times a hillshade of the depth field -- never stacked veils. Land is
# transparent. Because the shallowest tone IS the water colour, the DEM's coastline never
# has to agree with the vector coast: where they differ the pixel is water-coloured either
# way. The images stay plate carree; the lab's drawRelief projects them strip by strip.
SEA_RAMP = [(0, (0x17, 0x45, 0x7F)), (50, (0x15, 0x40, 0x78)), (200, (0x11, 0x38, 0x69)),
            (500, (0x0D, 0x2E, 0x59)), (900, (0x09, 0x24, 0x4A)), (2000, (0x06, 0x1A, 0x38))]
HOME_SEA = (-118.85, 33.69, -117.95, 34.05)        # the home frame, south of the last salt water


def dem_pull(box, step, lock):
    w, s, e, n = box
    size = (int(round((e - w) / step)), int(round((n - s) / step)))
    q = {'bbox': '%f,%f,%f,%f' % box, 'bboxSR': 4326, 'imageSR': 4326, 'size': '%d,%d' % size,
         'format': 'tiff', 'pixelType': 'F32', 'noData': -9999,
         'interpolation': 'RSP_BilinearInterpolation', 'f': 'image',
         'mosaicRule': json.dumps({'mosaicMethod': 'esriMosaicLockRaster', 'lockRasterIds': [lock]})}
    for k in range(4):
        try:
            return tifffile.imread(io.BytesIO(get(DEM_SRC + '?' + urllib.parse.urlencode(q), 600))).astype('float32')
        except Exception as ex:
            print('    retry %d (%s)' % (k + 1, ex))
    raise RuntimeError('DEM pull failed for %s' % (box,))


def sea_image(a, box, zfac, name):
    from PIL import Image
    w, s, e, n = box
    H, W = a.shape
    sea = (a < -0.3) & (a > -9000)                 # outside a locked raster is nodata, not abyss
    if sea.mean() < 0.002:
        return None
    d = np.clip(-a, 0, None)
    xs = [r[0] for r in SEA_RAMP]
    rgb = np.stack([np.interp(d, xs, [r[1][c] for r in SEA_RAMP]) for c in range(3)], -1)
    # hillshade in true metres; the field is eased first so a survey's track lines do not
    # become the texture, and the relief fades in over the first metres so surf is flat
    g = ndimage.gaussian_filter(np.where(a > 0, 0, a), 1.0)
    my = (n - s) / H * 111320.0
    mx = (e - w) / W * 111320.0 * math.cos(math.radians((s + n) / 2))
    gy, gx = np.gradient(g * zfac, my, mx)
    az, alt = math.radians(315), math.radians(45)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(gy, -gx)
    hs = math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(az - math.pi / 2 - aspect)
    shade = np.clip(hs / math.sin(alt), 0.58, 1.14)
    shade = 1 + (shade - 1) * np.clip(d / 6.0, 0, 1)
    out = np.zeros((H, W, 4), 'uint8')
    out[..., :3] = np.clip(rgb * shade[..., None], 0, 255)
    out[..., 3] = np.where(sea, 255, 0)
    im = Image.fromarray(out)
    # a single-hue ramp survives 96 colours untouched, and the file drops ~5x
    al = im.getchannel('A')
    pim = im.convert('RGB').quantize(96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert('RGB')
    pim.putalpha(al)
    pim.save(os.path.join(HERE, name), optimize=True)
    print('  %-22s %5dx%-5d %6d KB  sea %.0f%%' % (name, W, H, os.path.getsize(os.path.join(HERE, name)) // 1024, 100 * sea.mean()))
    return {'img': 'la/' + name, 'w': w, 's': s, 'e': e, 'n': n}


def grid(box, nx, ny):
    w, s, e, n = box
    for j in range(ny):
        for i in range(nx):
            yield (w + (e - w) * i / nx, s + (n - s) * j / ny, w + (e - w) * (i + 1) / nx, s + (n - s) * (j + 1) / ny), '%d%d' % (j, i)


def bake_sea():
    print('seafloor relief')
    idx = []
    r = sea_image(dem_pull(PULL, 3 / 3600.0, RASTER['3as']), PULL, 5.0, 'sea_3as.png')
    idx.append(dict(r, feather=True))
    for b, tag in grid(PULL, 3, 2):
        r = sea_image(dem_pull(b, 1 / 3600.0, RASTER['1as']), b, 3.5, 'sea_1as_%s.png' % tag)
        if r:
            idx.append(dict(r, maxMpp=60))
    for b, tag in grid(HOME_SEA, 4, 1):
        r = sea_image(dem_pull(b, 1 / 10800.0, RASTER['13as']), b, 2.2, 'sea_13as_%s.png' % tag)
        if r:
            idx.append(dict(r, maxMpp=25))
    write('sea_index.json', idx)


PARTS = {'city': bake_city, 'rail': bake_rail, 'faults': bake_faults, 'dem': bake_dem, 'sea': bake_sea}

if __name__ == '__main__':
    print('home box  w %.4f  s %.4f  e %.4f  n %.4f' % home_box())
    for k in (sys.argv[1:] or list(PARTS)):
        PARTS[k]()
