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
    land_*.png          mountain relief, light and shade only, the same tiers     the same models
    land_index.json
    veg_*.png           what is actually growing, one green weighted by cover     ESA WorldCover 2021
    veg_index.json
    airfields.json      airfields (field, aprons, taxiways, runways, terminals) + beaches   OpenStreetMap

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
    # WHOLE urban areas, not the pull's rectangle of them: the wide tabs (MRMS 3 h / 12 h)
    # look at this map from 500 km up, and a footprint cut on the pull box put a ruled
    # orange edge down the Inland Empire. An area belongs if its centre is in the pull --
    # which keeps the conurbation entire and leaves out San Diego and Santa Barbara, whose
    # corners merely touch it.
    # WHICH URBAN AREAS ARE LOS ANGELES (user, 2026-09-19, pointing at orange islands: "is
    # that accurately considered LA too?"). It was not: the rule had been "any urban area
    # centred in the data rectangle", which is a fact about my rectangle, not about the
    # city, and it painted Oxnard-Ventura, Camarillo, Santa Paula, Fillmore, Palmdale-
    # Lancaster (30 km over the San Gabriels), Victorville, Wrightwood and Avalon orange.
    # The rule now: the Census LOS ANGELES--LONG BEACH--ANAHEIM urban area, plus any urban
    # area within 5 km of it -- the ones you reach without leaving the built-up city:
    # Thousand Oaks and Mission Viejo (touching), Simi Valley (0.4 km), Santa Clarita
    # (3 km, through the Newhall Pass), Riverside--San Bernardino (touching at Pomona).
    # Everything across open country stays the colour of open country.
    name_of = lambda f: f['properties'].get('BASENAME') or f['properties'].get('NAME') or ''     # noqa: E731
    geoms = {name_of(f): shape(f['geometry']).buffer(0) for f in fs}
    core = geoms['Los Angeles--Long Beach--Anaheim, CA']
    keep = sorted(n for n, g in geoms.items() if g.distance(core) <= 0.05)
    print('  Los Angeles = %s' % keep)
    urban = unary_union([geoms[n] for n in keep])
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


def dem_pull(box, step, lock, src=None):
    w, s, e, n = box
    size = (int(round((e - w) / step)), int(round((n - s) / step)))
    q = {'bbox': '%f,%f,%f,%f' % box, 'bboxSR': 4326, 'imageSR': 4326, 'size': '%d,%d' % size,
         'format': 'tiff', 'pixelType': 'F32', 'noData': -9999,
         'interpolation': 'RSP_BilinearInterpolation', 'f': 'image'}
    if lock is not None:
        q['mosaicRule'] = json.dumps({'mosaicMethod': 'esriMosaicLockRaster', 'lockRasterIds': [lock]})
    for k in range(4):
        try:
            return tifffile.imread(io.BytesIO(get((src or DEM_SRC) + '?' + urllib.parse.urlencode(q), 600))).astype('float32')
        except Exception as ex:
            print('    retry %d (%s)' % (k + 1, ex))
    raise RuntimeError('DEM pull failed for %s' % (box,))


def sea_image(a, box, zfac, name, keep=None):
    from PIL import Image
    w, s, e, n = box
    H, W = a.shape
    sea = (a < -0.3) & (a > -9000)                 # outside a locked raster is nodata, not abyss
    # BELOW SEA LEVEL IS NOT THE SEA. The regional grid drew the whole Salton Trough and
    # Death Valley as ocean. Salt water reaches the frame's edge (the Gulf of California
    # does, at the bottom); a basin that never touches it is dry land.
    lab, nlab = ndimage.label(sea)
    if nlab > 1:
        edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
        sea = np.isin(lab, edge[edge > 0])
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
    out[..., 3] = np.where(sea, 255, 0) if keep is None else np.where(sea, np.round(255 * keep), 0)
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


# ------------------------------------------------------------------ land ----
# THE MOUNTAINS (user, 2026-09-19: "LA has a lot of mountains too, add the topography relief
# so its not flat"). The veils in land_relief.json are terraces -- fine for New York's 120 m
# of relief, nothing like enough for a basin walled by 3,000 m. Same models and the same
# tiers as the seafloor, the same locked rasters, but drawn as LIGHT AND SHADE ONLY: a
# pixel is black-with-alpha where the slope faces away from a north-west sun and
# white-with-alpha where it faces it, and fully transparent where the ground is flat. No
# hypsometric colour -- colour on this map belongs to the city, the parks, the water and
# (later) the radar. So the basin floor stays clean orange, the Santa Monicas and the
# Hollywood Hills shade the orange they are built on, and on the black land outside the
# footprint the lit faces are what draw the San Gabriels at all.
# THE LAND COMES FROM USGS 3DEP, NOT THE NOAA MODELS. NOAA's coastal relief model has a
# rectangular hole in it -- nothing east of -118.0 above 34.05, mapped cell by cell -- which
# is the eastern San Gabriels, Mt Baldy included, and its 10 m model stops at 34.2 N. 3DEP
# is seamless at 1/3 arc-second across the whole pull (Baldy reads 3,068 m, every pixel
# distinct), so all three tiers use it and the fine tier covers the full home frame.
LAND_SRC = 'https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage'
HOME_LAND = (-118.85, 33.69, -117.95, 34.346)


def land_image(a, box, zfac, name, keep=None, lite_gain=1.0):
    from PIL import Image
    w, s, e, n = box
    H, W = a.shape
    land = (a > 0.5)
    if land.mean() < 0.002:
        return None
    g = ndimage.gaussian_filter(np.where(a < -9000, 0, np.clip(a, 0, None)), 0.8)
    my = (n - s) / H * 111320.0
    mx = (e - w) / W * 111320.0 * math.cos(math.radians((s + n) / 2))
    gy, gx = np.gradient(g * zfac, my, mx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(gy, -gx)
    alt = math.radians(45)
    # three suns, the north-west one leading: a single light leaves every south-east face
    # one flat black and the ranges read as cut-outs
    hs = np.zeros_like(g)
    for az_deg, wt in ((315, 0.6), (270, 0.2), (0, 0.2)):
        az = math.radians(az_deg)
        hs += wt * (math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(az - math.pi / 2 - aspect))
    sh = hs / math.sin(alt) - 1.0                      # 0 on the flat, negative in shadow
    dark = np.clip(-sh, 0, 1) * 0.62
    lite = np.clip(sh / 0.41, 0, 1) * 0.30 * lite_gain
    alpha = np.where(sh < 0, dark, lite) * land
    if keep is not None:
        alpha = alpha * keep
    alpha = np.round(alpha * 255 / 8) * 8              # 32 steps: invisible, and the file halves
    alpha[alpha < 10] = 0                              # the basin floor carries nothing at all
    out = np.zeros((H, W, 2), 'uint8')
    out[..., 0] = np.where(sh < 0, 0, 255)
    out[..., 0][alpha == 0] = 0
    out[..., 1] = np.clip(alpha, 0, 255)
    Image.fromarray(out).save(os.path.join(HERE, name), optimize=True)
    print('  %-22s %5dx%-5d %6d KB  land %.0f%%  shaded %.0f%%' % (
        name, W, H, os.path.getsize(os.path.join(HERE, name)) // 1024, 100 * land.mean(), 100 * (alpha > 0).mean()))
    return {'img': 'la/' + name, 'w': w, 's': s, 'e': e, 'n': n}


def bake_land():
    """Resumable: an image already on disk is kept (delete it to re-pull). The fine tier
    goes in 4 x 3 pieces -- 3DEP answers a 17-megapixel request with a 500."""
    print('land relief')
    idx = []

    def tier(box, step, zfac, name, extra):
        if os.path.exists(os.path.join(HERE, name)):
            r = {'img': 'la/' + name, 'w': box[0], 's': box[1], 'e': box[2], 'n': box[3]}
        else:
            r = land_image(dem_pull(box, step, None, LAND_SRC), box, zfac, name)
        if r:
            idx.append(dict(r, **extra))

    tier(PULL, 3 / 3600.0, 1.6, 'land_3as.png', {'feather': True})
    for b, tag in grid(PULL, 3, 2):
        tier(b, 1 / 3600.0, 1.25, 'land_1as_%s.png' % tag, {'maxMpp': 60})
    for b, tag in grid(HOME_LAND, 4, 3):
        tier(b, 1 / 10800.0, 1.0, 'land_13as_%s.png' % tag, {'maxMpp': 25})
    write('land_index.json', idx)


# ---------------------------------------------------------------- region ----
# THE WIDE TABS NEED A MAP TOO (user, 2026-09-19: "the weather views dont have the map loaded
# at all"). MRMS 3 h / 12 h and the marine layer look at this map from 500-1,500 km up, and
# everything above was pulled for a 250 km rectangle round the city -- so the West came out as
# flat black with one detailed postage stamp in it. One more tier UNDER the others, for both
# relief lists: ETOPO 2022 at 15 arc-seconds, the only model in the mosaic that is seamless
# across the US, Mexico and the ocean floor alike, over everything the 12-hour box can show.
#
# THE SEAM. The sea is opaque, so the 3" image simply lies on top and its feathered rim
# dissolves into this one (same ramp, same tones). The land is ALPHA, and two alphas stack:
# so this tier's shading is ramped to nothing across the same outer 5% of the pull that the
# 3" image's feather ramps IN across -- complementary, neither a doubled band nor a bare ring.
REGION = (-130.0, 26.5, -112.5, 42.0)
ETOPO_15S = 2527                                  # ETOPO_2022_v1_15s_surface_elev


def bake_region():
    print('regional base (ETOPO 15")')
    a = dem_pull(REGION, 15 / 3600.0, ETOPO_15S)
    print('  grid %s, %.0f to %.0f m' % (a.shape, a[a > -9000].min(), a.max()))
    # knock this tier out where the finer ones take over. For the LAND it stops two alphas
    # stacking. For the SEA it stops something worse: a 450 m cell's idea of the coast,
    # drawn opaque, spilled navy hundreds of metres up the beach beside LAX, and the finer
    # tiers on top are transparent over land so they never covered it.
    H, W = a.shape
    lon = REGION[0] + (np.arange(W) + 0.5) / W * (REGION[2] - REGION[0])
    lat = REGION[3] - (np.arange(H) + 0.5) / H * (REGION[3] - REGION[1])
    fx, fy = 0.05 * (PULL[2] - PULL[0]), 0.05 * (PULL[3] - PULL[1])
    inx = np.clip(np.minimum(lon - PULL[0], PULL[2] - lon) / fx, 0, 1)
    iny = np.clip(np.minimum(lat - PULL[1], PULL[3] - lat) / fy, 0, 1)
    keep = 1.0 - np.minimum.outer(iny, inx)        # 1 outside the pull, 0 well inside it
    rs = sea_image(a, REGION, 7.0, 'sea_15as.png', keep)
    # from 1,000 km up the ranges sit on BLACK land, where only the lit faces can draw them
    rl = land_image(a, REGION, 2.4, 'land_15as.png', keep, lite_gain=1.8)
    for name, first in (('sea_index.json', rs), ('land_index.json', rl)):
        p = os.path.join(HERE, name)
        idx = [r for r in json.load(open(p)) if r['img'] != first['img']]
        write(name, [first] + idx)


# ------------------------------------------------------------------- veg ----
# THE GREEN IS VEGETATION, NOT A LAND DEED (user, 2026-09-19: "im seeing cubed grass can you
# make sure all the green is correct"). The basemap paints green wherever OSM has a park, a
# forest or a nature reserve -- and out here that means NATIONAL FOREST BOUNDARIES, which
# follow survey section lines: squares, staircases and a checkerboard of inholdings where
# Los Padres meets private land. Legally exact and visually nonsense, the same disease as
# the city limit. So outside the city the green now comes from what is actually growing:
# ESA WorldCover 2021, 10 m, global (so Baja has it too), read straight from the
# cloud-optimised files on the Planetary Computer.
#
# ONE GREEN, WEIGHTED BY WHAT IT IS: tree cover full strength, shrubland (chaparral, the
# real colour of these mountains) most of it, grassland a little -- California's grass is
# gold for nine months -- cropland a trace, bare ground and desert none. Each output pixel
# is the MEAN weight of the 10 m cells under it, not the commonest class, so a slope that
# is half oak and half rock comes out half green instead of flickering between the two.
# Same tiers and the same exclusive compositing as the mountain relief.
VEG_GREEN = (0x2A, 0x6A, 0x43)
# ...AND HOW GREEN IT ACTUALLY IS. Land cover says WHAT grows, not how green: WorldCover calls
# Nevada's sagebrush and the San Gabriels' chaparral the same "shrubland", and the first bake
# painted the Great Basin as lush as the Coast Ranges. So everything that is not tree cover is
# scaled by measured greenness -- MODIS NDVI, the greenest of four months of the year (GIBS,
# decoded through its own colormap): nothing below 0.18, full strength from 0.45. Chaparral
# peaks near 0.5-0.6 and keeps its green; sagebrush at 0.2-0.3 keeps a trace; the Mojave at
# 0.1 keeps none. Trees are trusted as mapped.
VEG_TREE = {10: 1.0, 90: 0.8, 95: 0.8}
VEG_OTHER = {20: 0.85, 30: 0.45, 40: 0.30, 100: 0.3}
NDVI_WMS = 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi'
NDVI_CMAP = 'https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_NDVI.xml'
NDVI_MONTHS = ('2025-03-01', '2025-05-01', '2025-07-01', '2025-10-01')
_GREEN = []


def greenness():
    """(factor grid over REGION at 30", 0..1). Peak NDVI of the year, as a multiplier."""
    if _GREEN:
        return _GREEN[0]
    import re
    from PIL import Image
    x = get(NDVI_CMAP).decode('utf-8', 'replace')
    ents = re.findall(r'<ColorMapEntry[^>]*rgb="(\d+),(\d+),(\d+)"[^>]*value="\[?([-\d.]+)', x)
    keys = np.array([[int(r), int(g), int(b)] for r, g, b, _ in ents])
    vals = np.array([float(v) for _, _, _, v in ents])
    W, H = int((REGION[2] - REGION[0]) * 120), int((REGION[3] - REGION[1]) * 120)
    best = np.full((H, W), np.nan, 'float32')
    for day in NDVI_MONTHS:
        u = (NDVI_WMS + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1&LAYERS=MODIS_Terra_L3_NDVI_Monthly&STYLES='
             '&SRS=EPSG:4326&BBOX=%f,%f,%f,%f&WIDTH=%d&HEIGHT=%d&FORMAT=image/png&TIME=%s' % (REGION + (W, H, day)))
        a = np.array(Image.open(io.BytesIO(get(u, 300))).convert('RGB')).reshape(-1, 3)
        v = np.full(a.shape[0], np.nan, 'float32')
        for i in range(0, a.shape[0], 200000):
            ch = a[i:i + 200000].astype('int32')
            d = ((ch[:, None, :] - keys[None, :, :]) ** 2).sum(2)
            v[i:i + 200000] = np.where(d.min(1) == 0, vals[d.argmin(1)], np.nan)
        v = v.reshape(H, W)
        print('  ndvi %s valid %.0f%%  land median %.2f' % (day, 100 * np.isfinite(v).mean(), np.nanmedian(v)))
        best = np.fmax(best, v)
    # the published scale may be 0..1 or 0..10000
    if np.nanmax(best) > 2:
        best = best / 10000.0
    f = np.clip((best - 0.18) / 0.27, 0, 1)
    f = np.where(np.isfinite(f), f, 0.5).astype('float32')
    f = ndimage.gaussian_filter(f, 1.2)
    _GREEN.append(f)
    return f


def green_on(box, W, H):
    """The greenness factor resampled (bilinear) onto a W x H grid over `box`."""
    f = greenness()
    fh, fw = f.shape
    xs = ((box[0] + (np.arange(W) + 0.5) / W * (box[2] - box[0])) - REGION[0]) / (REGION[2] - REGION[0]) * fw - 0.5
    ys = (REGION[3] - (box[3] - (np.arange(H) + 0.5) / H * (box[3] - box[1]))) / (REGION[3] - REGION[1]) * fh - 0.5
    yy, xx = np.meshgrid(np.clip(ys, 0, fh - 1), np.clip(xs, 0, fw - 1), indexing='ij')
    return ndimage.map_coordinates(f, [yy, xx], order=1).astype('float32')
WC_TOKEN = 'https://planetarycomputer.microsoft.com/api/sas/v1/token/esa-worldcover'
WC_TILE = ('https://ai4edataeuwest.blob.core.windows.net/esa-worldcover/v200/2021/map/'
           'ESA_WorldCover_10m_2021_v200_%s%02d%s%03d_Map.tif')


def veg_weights(box, W, H, over, tok):
    """Mean vegetation weight on a W x H plate-carree grid over `box`, from every 3-degree
    WorldCover tile it touches, each read at `over` x the output resolution."""
    import rasterio
    from rasterio.windows import from_bounds
    w, s, e, n = box
    out = np.zeros((H, W), 'float32')
    oth = np.zeros((H, W), 'float32')
    lut = np.zeros(256, 'float32')
    lut2 = np.zeros(256, 'float32')
    for k, v in VEG_TREE.items():
        lut[k] = v
    for k, v in VEG_OTHER.items():
        lut2[k] = v
    for la in range(int(math.floor(s / 3.0)) * 3, int(math.ceil(n)), 3):
        for lo in range(int(math.floor(w / 3.0)) * 3, int(math.ceil(e)), 3):
            tw, ts, te, tn = max(w, lo), max(s, la), min(e, lo + 3), min(n, la + 3)
            if te <= tw or tn <= ts:
                continue
            x0, x1 = int(round((tw - w) / (e - w) * W)), int(round((te - w) / (e - w) * W))
            y0, y1 = int(round((n - tn) / (n - s) * H)), int(round((n - ts) / (n - s) * H))
            if x1 <= x0 or y1 <= y0:
                continue
            url = WC_TILE % ('N' if la >= 0 else 'S', abs(la), 'E' if lo >= 0 else 'W', abs(lo)) + '?' + tok
            try:
                with rasterio.open(url) as ds:
                    a = ds.read(1, window=from_bounds(tw, ts, te, tn, ds.transform),
                                out_shape=((y1 - y0) * over, (x1 - x0) * over))
            except Exception:
                continue                                   # open ocean: no tile
            out[y0:y1, x0:x1] = lut[a].reshape(y1 - y0, over, x1 - x0, over).mean(axis=(1, 3))
            oth[y0:y1, x0:x1] = lut2[a].reshape(y1 - y0, over, x1 - x0, over).mean(axis=(1, 3))
    return np.clip(out + oth * green_on(box, W, H), 0, 1)


def veg_image(wt, box, name, keep=None):
    from PIL import Image
    if keep is not None:
        wt = wt * keep
    if (wt > 0.04).mean() < 0.002:
        return None
    lv = np.clip(np.round(wt * 15), 0, 15).astype('uint8')          # 16 steps of one green
    im = Image.fromarray(lv)
    im = im.convert('P')
    im.putpalette(list(VEG_GREEN) * 16 + [0, 0, 0] * 240)
    im.info['transparency'] = bytes([int(round(i * 255 / 15.0)) for i in range(16)] + [0] * 240)
    im.save(os.path.join(HERE, name), optimize=True, transparency=im.info['transparency'])
    print('  %-22s %5dx%-5d %6d KB  green %.0f%%' % (name, wt.shape[1], wt.shape[0],
          os.path.getsize(os.path.join(HERE, name)) // 1024, 100 * (wt > 0.04).mean()))
    return {'img': 'la/' + name, 'w': box[0], 's': box[1], 'e': box[2], 'n': box[3]}


def bake_veg():
    print('vegetation (ESA WorldCover 2021)')
    tok = json.loads(get(WC_TOKEN))['token']
    idx = []

    def tier(box, step, over, name, extra, keep=None):
        W, H = int(round((box[2] - box[0]) / step)), int(round((box[3] - box[1]) / step))
        p = os.path.join(HERE, name)
        r = ({'img': 'la/' + name, 'w': box[0], 's': box[1], 'e': box[2], 'n': box[3]} if os.path.exists(p)
             else veg_image(veg_weights(box, W, H, over, tok), box, name, keep))
        if r:
            idx.append(dict(r, **extra))

    # the regional tier fades out across the pull's rim, where the 3" tier's feather fades in
    W, H = int(round((REGION[2] - REGION[0]) * 240)), int(round((REGION[3] - REGION[1]) * 240))
    lon = REGION[0] + (np.arange(W) + 0.5) / W * (REGION[2] - REGION[0])
    lat = REGION[3] - (np.arange(H) + 0.5) / H * (REGION[3] - REGION[1])
    fx, fy = 0.05 * (PULL[2] - PULL[0]), 0.05 * (PULL[3] - PULL[1])
    keep = 1.0 - np.minimum.outer(np.clip(np.minimum(lat - PULL[1], PULL[3] - lat) / fy, 0, 1),
                                  np.clip(np.minimum(lon - PULL[0], PULL[2] - lon) / fx, 0, 1))
    tier(REGION, 15 / 3600.0, 4, 'veg_15as.png', {}, keep)
    tier(PULL, 3 / 3600.0, 4, 'veg_3as.png', {'feather': True})
    for b, tag in grid(PULL, 3, 2):
        tier(b, 1 / 3600.0, 2, 'veg_1as_%s.png' % tag, {'maxMpp': 60})
    for b, tag in grid(HOME_LAND, 4, 3):
        tier(b, 1 / 10800.0, 1, 'veg_13as_%s.png' % tag, {'maxMpp': 25})
    write('veg_index.json', idx)


# ------------------------------------------------------------ air + sand ----
# AIRFIELDS AND BEACHES, THE NEW YORK WAY (user, 2026-09-19: "detail the airports and beaches
# like NYC now"). New York's widget draws JFK, LaGuardia and Newark as tarmac -- field, aprons,
# taxiways, hangars, runways, terminals, from OSM's aeroway tags -- and its beaches as sand.
# Same tags, same grammar, every field in the pull: LAX, Burbank, Long Beach, Van Nuys, Santa
# Monica, John Wayne, Ontario and the rest. Beaches are natural=beach, which is also what
# finally paints the strand from Malibu to Newport: it lies outside the urban footprint, so
# it had been coming out as black land against the sea.
OVERPASS = ('https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter')


def overpass(q):
    # the public servers 504 in bursts; three mirrors, five rounds, then give up
    import time
    for rnd_ in range(5):
        for url in OVERPASS:
            try:
                r = urllib.request.urlopen(urllib.request.Request(
                    url, data=urllib.parse.urlencode({'data': q}).encode(), headers=UA), timeout=300).read()
                return json.loads(r)['elements']
            except Exception as ex:
                print('    %s: %s' % (url.split('/')[2], ex))
        time.sleep(30)
    raise RuntimeError('overpass unreachable')


def rings_of(el):
    """Closed rings of a way or a multipolygon relation (outer members), as lon/lat lists."""
    if el['type'] == 'way':
        g = [[p['lon'], p['lat']] for p in el.get('geometry') or []]
        return [g] if len(g) >= 4 else []
    # A big multipolygon's outline arrives in PIECES -- Dockweiler State Beach is several
    # open ways end to end -- and keeping only the members that were already closed dropped
    # exactly the largest beaches. Stitch the outer ways into rings by their shared endpoints.
    segs = []
    for m in el.get('members') or []:
        if m.get('role') in ('outer', '') and m.get('type') == 'way' and m.get('geometry'):
            g = [(p['lon'], p['lat']) for p in m['geometry']]
            if len(g) >= 2:
                segs.append(g)
    out = []
    while segs:
        ring = segs.pop(0)
        grew = True
        while ring[0] != ring[-1] and grew:
            grew = False
            for i, g in enumerate(segs):
                if g[0] == ring[-1]:
                    ring += g[1:]
                elif g[-1] == ring[-1]:
                    ring += g[-2::-1]
                elif g[-1] == ring[0]:
                    ring = g[:-1] + ring
                elif g[0] == ring[0]:
                    ring = g[:0:-1] + ring
                else:
                    continue
                segs.pop(i)
                grew = True
                break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            out.append([list(c) for c in ring])
    return out


def bake_air():
    print('airfields + beaches')
    bb = '%f,%f,%f,%f' % (PULL[1], PULL[0], PULL[3], PULL[2])
    els = overpass('[out:json][timeout:240];(way["aeroway"~"aerodrome|runway|taxiway|taxilane|apron|terminal|hangar"](%s);'
                   'relation["aeroway"~"aerodrome|apron|terminal"](%s);way["natural"="beach"](%s);'
                   'relation["natural"="beach"](%s););out geom;' % (bb, bb, bb, bb))
    KM2 = 111.32 * 111.32 * math.cos(math.radians(34.0))
    fields, parts, beaches = [], [], []
    for e in els:
        t = e.get('tags') or {}
        k = t.get('aeroway')
        if t.get('natural') == 'beach':
            for r in rings_of(e):
                pg = Polygon(r).buffer(0)
                if pg.area * KM2 >= 0.004:
                    beaches.append({'name': t.get('name'), 'r': rnd(pg.simplify(0.00003).exterior.coords)
                                    if pg.geom_type == 'Polygon' else rnd(r)})
        elif k == 'aerodrome':
            rs = [Polygon(r).buffer(0) for r in rings_of(e)]
            rs = [q for q in rs if not q.is_empty]
            if rs:
                pg = unary_union(rs)
                # a field is somewhere an aeroplane lands: hospital pads and rooftop helistops are not
                if pg.area * KM2 >= 0.25:
                    fields.append({'name': t.get('name') or t.get('iata') or t.get('icao'), 'code': t.get('iata') or t.get('icao'),
                                   'pg': pg, 'rw': [], 'tx': [], 'ap': [], 'tm': [], 'hg': []})
        elif k in ('runway', 'taxiway', 'taxilane') and e['type'] == 'way':
            g = [[p['lon'], p['lat']] for p in e.get('geometry') or []]
            if len(g) >= 2:
                parts.append(('rw' if k == 'runway' else 'tx', LineString(g), rnd(g), t))
        elif k in ('apron', 'terminal', 'hangar'):
            for r in rings_of(e):
                parts.append(({'apron': 'ap', 'terminal': 'tm', 'hangar': 'hg'}[k], Polygon(r).buffer(0), rnd(r), t))
    for kind, geom, coords, t in parts:
        c = geom.centroid
        f = next((f for f in fields if f['pg'].buffer(0.002).contains(c)), None)
        if f is not None:
            f[kind].append(coords)
    out = []
    for f in sorted(fields, key=lambda f: -f['pg'].area):
        if not f['rw']:
            continue                                        # a closed or paper field
        big = max(([f['pg']] if f['pg'].geom_type == 'Polygon' else list(f['pg'].geoms)), key=lambda q: q.area)
        out.append({'name': f['name'], 'code': f['code'], 'r': rnd(big.simplify(0.00004).exterior.coords),
                    'rw': f['rw'], 'tx': f['tx'], 'ap': f['ap'], 'tm': f['tm'], 'hg': f['hg']})
    print('  %d fields: %s' % (len(out), ', '.join('%s (%d rw, %d tx)' % (f['code'] or f['name'], len(f['rw']), len(f['tx'])) for f in out[:14])))
    print('  %d beaches, e.g. %s' % (len(beaches), sorted({b['name'] for b in beaches if b['name']})[:10]))
    write('airfields.json', {'fields': out, 'beaches': beaches})


PARTS = {'air': bake_air, 'veg': bake_veg, 'region': bake_region, 'land': bake_land, 'city': bake_city, 'rail': bake_rail, 'faults': bake_faults, 'dem': bake_dem, 'sea': bake_sea}

if __name__ == '__main__':
    print('home box  w %.4f  s %.4f  e %.4f  n %.4f' % home_box())
    for k in (sys.argv[1:] or list(PARTS)):
        PARTS[k]()
