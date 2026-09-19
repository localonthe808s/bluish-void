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
    rail_sched.json     every station's departures by line, headsign and service day   the same GTFS (TIMETABLE, not live)
    faults.json         Quaternary faults                                       USGS Qfaults
    land_relief.json    terrain veils at fixed heights                          NOAA NCEI DEM mosaic
    sea_*.png           seafloor shaded relief, 3 / 1 / 1/3 arc-second tiers     NOAA CRM v2 + Santa Monica DEM
    sea_index.json      where each image sits and the scale it is for
    land_*.png          mountain relief, light and shade only, the same tiers     the same models
    land_index.json
    veg_*.png           what is actually growing, one green weighted by cover     ESA WorldCover 2021
    veg_index.json
    weather_geo.json    the weather machinery: traced ranges, wind gaps, passes, the cold edge   ETOPO 15" + hand-set
    airfields.json      airfields (field, aprons, taxiways, runways, terminals) + beaches   OpenStreetMap

    python3 la_bake.py            # everything
    python3 la_bake.py rail dem   # only those parts (city, rail, faults, dem, sea)

The DEM is ONE pull far wider than the home box (Channel Islands to the San
Gorgonio Pass) so a pan never runs off the terrain. Contours leave here as
lon/lat vectors and are projected at draw time -- nothing raster is resampled
into mercator, which is the trap the New York seafloor fell into twice.
"""
import csv
import datetime
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
# THE TWO CALIFORNIA LAYERS DO NOT SPEAK THE SAME LANGUAGE. Layer 4 (onshore) names its
# columns in lower case and layer 5 (offshore) in upper, with different words for the same
# facts -- `age` against `FLT_AGE`, `linetype` against `LINE_TYPE`. Reading only the onshore
# names shipped every offshore fault with no age and no certainty, so the whole San Pedro
# shelf drew in the fallback weight, one flat colour, when the survey in fact dates half of
# those traces to the latest Quaternary. Both schemas are normalised here into one.
#
# And `linetype` is NOT `mapped_certainty`. The first says how the trace is expressed --
# well constrained, inferred, concealed -- and the second how well its position is known.
# Taking `mapped_certainty or linetype` let "Good" win for almost every onshore trace and
# threw the expression away, so 44 of the 124 traces off Long Beach were marked inferred by
# the survey and drawn as solid fact. They are separate properties now: `trace` is what the
# dash means, `certainty` and `scale` are how precisely it was located.
FAULT_SENSE = {'D': 'Right lateral', 'S': 'Left lateral', 'N': 'Normal', 'R': 'Reverse',
               'DR': 'Right lateral-reverse', 'RD': 'Reverse-right lateral',
               'DN': 'Right lateral-normal', 'ND': 'Normal-right lateral',
               'SR': 'Left lateral-reverse', 'RS': 'Reverse-left lateral',
               'SN': 'Left lateral-normal', 'NS': 'Normal-left lateral'}
FAULT_RATE = {'<0.2': 'Less than 0.2 mm/yr', '0.2-1': 'Between 0.2 and 1.0 mm/yr',
              '1-5': 'Between 1.0 and 5.0 mm/yr', '>5': 'Greater than 5.0 mm/yr'}


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
            blank = lambda v: None if v in (None, '', 'unspecified', 'Unspecified') else v
            sense = blank(p.get('slip_sense'))
            rate = blank(p.get('slip_rate'))
            props = {'name': blank(p.get('fault_name')) or blank(p.get('name')),
                     'section': blank(p.get('section_name')) or blank(p.get('section_na')),
                     'age': blank(p.get('age')) or blank(p.get('flt_age')),
                     'slip_rate': FAULT_RATE.get(rate, rate),
                     'sense': FAULT_SENSE.get(sense, sense),
                     # how the survey draws it: this is what the dash means
                     'trace': blank(p.get('linetype')) or blank(p.get('line_type')),
                     # how well it is located: a separate question
                     'certainty': blank(p.get('mapped_certainty')),
                     'scale': blank(p.get('mapped_scale')) or blank(p.get('mapped_sca'))}
            parts = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates']
            for c in parts:
                if len(c) < 2:
                    continue
                # 0.00005 deg is about 5.5 m -- under a pixel at any zoom this map reaches.
                # The old 0.0002 strayed up to 22 m, nearly 3 px once the card is zoomed in.
                ls = LineString([(x[0], x[1]) for x in c]).simplify(0.00005)
                # and only degenerate slivers are dropped. The old 200 m floor cut 939 of the
                # 1922 traces over the home box -- 626 of them on the Sierra Madre front, which
                # the survey delivers as hundreds of short segments -- and left it dotted.
                if ls.length < 0.0002:
                    continue
                feats.append({'type': 'Feature', 'properties': props,
                              'geometry': {'type': 'LineString', 'coordinates': rnd(ls.coords)}})
    print('  %d traces; %s' % (len(feats), Counter(f['properties']['age'] for f in feats).most_common(6)))
    print('  trace:    %s' % Counter(f['properties']['trace'] for f in feats).most_common(8))
    print('  busiest:  %s' % Counter(f['properties']['name'] for f in feats).most_common(8))
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


# ----------------------------------------------------------- machinery ----
# THE WEATHER MACHINERY (user, 2026-09-19: "can you add the weather intelligence now ... we
# havent made any geological weather features for those views"). New York's wide views carry
# a layer that says what the landforms DO -- the snowbelt uplands, the lake-effect gate, the
# Appalachian gaps, the Gulf Stream's north wall. Los Angeles has its own machine, and it is
# a different one:
#
#   THE WALL.      The Transverse Ranges run east-west, square across the flow of every
#                  Pacific storm, and wring two and three times the basin's rain out of the
#                  same cloud. A range carries `face`: the bearing the wind must come FROM to
#                  climb it. The lab lights a range when the 850 mb flow does.
#   THE GAPS.      Santa Ana winds are Great Basin air falling to the sea, and it falls
#                  through four doors: Cajon, San Gorgonio, Soledad-Newhall and the Santa
#                  Clara River valley (Tejon is the fifth, the Grapevine's). Hand-set, dashed,
#                  soft -- where air runs is a tendency, not a survey.
#   THE COLD EDGE. Point Conception is where the coast turns east and the upwelled water of
#                  the California Current stops: cold sea to the west, the warm Bight to the
#                  east -- the marine layer's supply and Los Angeles' Gulf Stream wall.
#   THE PASSES.    Where the freezing level meets a road: Tejon (the Grapevine), Cajon, Donner.
#
# Ranges are TRACED, not drawn: the largest connected block above a level inside a box, on
# the same ETOPO grid the relief uses -- mask closed then opened so the contour describes the
# massif rather than its gullies, marching squares, simplified TO THE VIEW (0.006 deg for the
# 3-hour box, 0.02 deg for the 12-hour). A block that runs out of its box is a spine, not an
# island: the vertices on the box are dropped and it is kept OPEN.
RANGES = [  # name, (w, s, e, n), level m, face (wind FROM), crest note, view
    ('SAN GABRIEL MOUNTAINS',    (-118.50, 34.12, -117.45, 34.52), 1200, 200, 'near'),
    ('SAN BERNARDINO MOUNTAINS', (-117.42, 33.98, -116.55, 34.42), 1500, 215, 'near'),
    ('SANTA MONICA MOUNTAINS',   (-119.12, 34.00, -118.38, 34.20),  330, 190, 'near'),
    ('SANTA YNEZ MOUNTAINS',     (-120.50, 34.38, -119.25, 34.64),  620, 180, 'near'),
    ('TOPATOPA MOUNTAINS',       (-119.65, 34.44, -118.72, 34.88), 1300, 200, 'near'),
    ('TEHACHAPI MOUNTAINS',      (-118.95, 34.78, -118.15, 35.32), 1400, 255, 'near'),
    ('SANTA ANA MOUNTAINS',      (-117.78, 33.52, -117.32, 33.92),  720, 240, 'near'),
    ('SAN JACINTO MOUNTAINS',    (-116.98, 33.52, -116.45, 33.92), 1600, 250, 'near'),
    ('SIERRA NEVADA',            (-121.20, 35.40, -117.80, 40.20), 2300, 250, 'far'),
    ('TRANSVERSE RANGES',        (-120.60, 33.95, -116.40, 34.95), 1150, 200, 'far'),
    ('PENINSULAR RANGES',        (-117.30, 32.30, -116.10, 33.95), 1250, 250, 'far'),
    ('SANTA LUCIA RANGE',        (-121.95, 35.50, -120.80, 36.60),  800, 230, 'far'),
    ('WHITE MOUNTAINS',          (-118.45, 36.90, -117.95, 37.95), 2900, 250, 'far'),
    ('SPRING MOUNTAINS',         (-115.98, 35.95, -115.35, 36.55), 2200, 215, 'far'),
    ('SIERRA SAN PEDRO MARTIR',  (-116.00, 30.45, -115.10, 31.35), 1800, 250, 'far'),
]
# THE GAPS ARE TRACED, NOT DRAWN (user, 2026-09-19: "make sure these dashed lines are as accurate as
# possible, they cant be generalized"). The first cut was four hand-placed points a pass. Now each
# is the LEAST-COST PATH through the elevation grid between a point on the desert side and a
# point on the coastal side, with height as the cost (1 + (m/150)^2, eight-connected, true
# lengths): the line the terrain itself offers air that is falling to the sea -- it finds the
# lowest saddle and then keeps to the canyon floor. On USGS 3DEP at 3 arc-seconds (~90 m); the
# Gulf surge, 400 km of it, on ETOPO 15". Each trace is CHECKED against the pass it is named for
# (how near it runs to the summit's published position) and the bake prints the miss.
GAP_BOX = (-119.40, 33.60, -116.20, 35.10)
CORRIDORS = [  # name, (lon, lat) desert end, (lon, lat) coastal end, view, (check name, lon, lat)
    ('CAJON PASS',               (-117.37, 34.47), (-117.42, 34.14), 'near', ('Cajon Summit', -117.446, 34.349)),
    ('SAN GORGONIO PASS',        (-116.55, 33.92), (-117.12, 33.97), 'near', ('Banning', -116.876, 33.925)),
    ('SOLEDAD \u00b7 NEWHALL',  (-118.13, 34.50), (-118.50, 34.31), 'near', ('Newhall Pass', -118.507, 34.339)),
    ('SANTA CLARA RIVER VALLEY', (-118.60, 34.42), (-119.25, 34.24), 'near', ('Santa Paula', -119.059, 34.354)),
    ('TEJON PASS',               (-118.88, 34.96), (-118.62, 34.48), 'near', ('Tejon Pass', -118.877, 34.803)),
]
GULF_SURGE = ('GULF SURGE', (-114.80, 31.85), (-116.30, 33.75), ('Salton Sea', -115.83, 33.30))


def trace_gap(grid, box, a, b, eps):
    from skimage import graph
    w, s, e, n = box
    H, W = grid.shape
    rc = lambda p: (int(min(H - 1, max(0, (n - p[1]) / (n - s) * H))), int(min(W - 1, max(0, (p[0] - w) / (e - w) * W))))   # noqa: E731
    cost = 1.0 + (np.clip(np.where(grid < -9000, 4000, grid), 0, None) / 150.0) ** 2
    path, _ = graph.route_through_array(cost, rc(a), rc(b), fully_connected=True, geometric=True)
    pts = [(w + (c + 0.5) / W * (e - w), n - (r + 0.5) / H * (n - s)) for r, c in path]
    return pts, list(LineString(pts).simplify(eps).coords)


PASSES = [  # name, lon, lat, elevation ft, view
    ('TEJON PASS \u00b7 THE GRAPEVINE', -118.877, 34.803, 4144, 'near'),
    ('CAJON SUMMIT', -117.446, 34.349, 4190, 'near'),
    ('DONNER PASS', -120.327, 39.316, 7056, 'far'), ('TEJON PASS', -118.877, 34.803, 4144, 'far'),
]


def dp_open(pts, eps):
    return list(LineString(pts).simplify(eps).coords)


def bake_geo():
    print('weather machinery')
    a = dem_pull(REGION, 15 / 3600.0, ETOPO_15S)
    H, W = a.shape
    w0, s0, e0, n0 = REGION
    out = {'upland': [], 'corridor': [], 'pass': []}       # the cold edge is found LIVE by the lab, not drawn here
    for name, (w, s, e, n), level, face, view in RANGES:
        x0, x1 = int((w - w0) / (e0 - w0) * W), int((e - w0) / (e0 - w0) * W)
        y0, y1 = int((n0 - n) / (n0 - s0) * H), int((n0 - s) / (n0 - s0) * H)
        sub = a[y0:y1, x0:x1]
        k = 5 if view == 'near' else 9
        m = ndimage.binary_opening(ndimage.binary_closing(np.pad(sub >= level, k), np.ones((k, k))), np.ones((3, 3)))[k:-k, k:-k]
        m = ndimage.binary_fill_holes(m)
        lab, nl = ndimage.label(m)
        if not nl:
            print('  %-26s nothing above %d m' % (name, level)); continue
        big = lab == (1 + np.argmax(ndimage.sum(m, lab, range(1, nl + 1))))
        cs = measure.find_contours(np.pad(big.astype('float32'), 1), 0.5)
        c = max(cs, key=len) - 1
        hh, ww = big.shape
        pts = [(w + (x + 0.5) / ww * (e - w), n - (y + 0.5) / hh * (n - s)) for y, x in c]
        edge = [(x < w + 0.02 or x > e - 0.02 or y < s + 0.02 or y > n - 0.02) for x, y in pts]
        opened = any(edge)
        if opened:
            # keep the longest natural run; the straight box edges are not the range
            runs, cur = [], []
            for pt, on in list(zip(pts, edge)) * 2:
                if on:
                    if cur: runs.append(cur)
                    cur = []
                else:
                    cur.append(pt)
            if cur: runs.append(cur)
            pts = max(runs, key=len) if runs else pts
        eps = 0.006 if view == 'near' else 0.02
        ring = dp_open(pts, eps)
        crest = float(sub[big].max())
        ys, xs = np.nonzero(big)
        ctr = [round(w + (xs.mean() + 0.5) / ww * (e - w), 4), round(n - (ys.mean() + 0.5) / hh * (n - s), 4)]
        out['upland'].append({'n': name, 'r': rnd(ring, 4), 'open': bool(opened), 'crest': int(round(crest)),
                              'face': face, 'c': ctr, 'v': view})
        print('  %-26s %3d pts  %s  crest %d m' % (name, len(ring), 'open' if opened else 'closed', crest))
    g3 = dem_pull(GAP_BOX, 3 / 3600.0, None, LAND_SRC)
    km = lambda p, q: math.hypot((p[0] - q[0]) * 111.32 * math.cos(math.radians(q[1])), (p[1] - q[1]) * 111.32)   # noqa: E731
    for name, a_, b_, view, chk in CORRIDORS:
        raw, line = trace_gap(g3, GAP_BOX, a_, b_, 0.0012)
        if min(km(p, (chk[1], chk[2])) for p in raw) > 3.0:
            # THE CHEAPEST WAY IS NOT ALWAYS THE NAMED ONE. Left alone, the Tejon trace ran 87 km
            # round by a lower saddle and missed Tejon Pass by 6.5 km. A line labelled with a
            # pass's name goes THROUGH that pass: two legs, joined at the summit's position.
            r1, _ = trace_gap(g3, GAP_BOX, a_, (chk[1], chk[2]), 0.0012)
            r2, _ = trace_gap(g3, GAP_BOX, (chk[1], chk[2]), b_, 0.0012)
            raw = r1 + r2[1:]
            line = list(LineString(raw).simplify(0.0012).coords)
            print('    (%s: routed through the summit)' % name)
        miss = min(km(p, (chk[1], chk[2])) for p in raw)
        print('  %-26s %3d pts, %.0f km, passes %.1f km from %s' % (name, len(line), sum(km(raw[i], raw[i + 1]) for i in range(len(raw) - 1)), miss, chk[0]))
        out['corridor'].append({'n': name, 'l': rnd(line, 4), 'v': view})
        # the far view shows the same traces, unlabelled but for one name
        out['corridor'].append({'n': 'SANTA ANA WIND GAPS' if name == 'CAJON PASS' else '', 'l': rnd(list(LineString(raw).simplify(0.006).coords), 4), 'v': 'far', 'kind': 'gap'})
    raw, line = trace_gap(a, REGION, GULF_SURGE[1], GULF_SURGE[2], 0.004)
    print('  %-26s %3d pts, passes %.1f km from %s' % (GULF_SURGE[0], len(line), min(km(p, (GULF_SURGE[3][1], GULF_SURGE[3][2])) for p in raw), GULF_SURGE[3][0]))
    out['corridor'].append({'n': GULF_SURGE[0], 'l': rnd(line, 3), 'v': 'far'})
    for name, lo, la, ft, view in PASSES:
        out['pass'].append({'n': name, 'c': [lo, la], 'ft': ft, 'v': view})
    write('weather_geo.json', out)


# ----------------------------------------------------------------- trains ----
# THE TRAIN TIMES (user, 2026-09-19: "add the train times like we did for NYC, use 17th street
# SMC as the default"). New York's board is LIVE -- the MTA's GTFS-realtime feeds are keyless and
# CORS-open. Los Angeles is not there: Metro's API (api.metro.net, v2.1.38) has dropped its
# trip_updates and vehicle_positions routes (404), and the one realtime route left,
# /LACMTA_Rail/trip_detail/route_code/<n>, answered [] for every rail line AND for the 24-hour
# 720 bus when this was written; Swiftly's feed wants a key; UmoIQ no longer lists the agency.
# So the board is built on what Metro does publish without conditions: the TIMETABLE, from the
# same GTFS the lines are drawn from -- and it SAYS it is the timetable. The preview asks the
# live route first and uses it if it ever answers.
#
# Shape: per station, per line and headsign, the day's departures as minutes after midnight,
# for three service days (weekday / Saturday / Sunday). GTFS times run past 24:00 for the trips
# after midnight, which belong to the service day before -- kept as they are (1,475 = 12:35 AM)
# so the reader can look in yesterday's list too. A trip's last stop is an arrival, not a
# departure, and is left out. Holiday exceptions in calendar_dates are NOT applied.
def sched_from(rd, name_of, kind):
    # METRO'S CALENDAR IS PER DATE, NOT PER WEEKDAY. Read 2026-09-19: the feed carries a
    # separate service_id for almost every day of the coming fortnight ("801-1_Weekday-07" for
    # the 21st alone, "-13" for the 22nd ...) -- track work changes the timetable daily -- plus
    # calendar_dates removals on top. A weekday/Saturday/Sunday table cannot hold that: it
    # printed 12:21 and 12:22 as two trains (two calendars, same flag) and then, filtered to
    # "in force today", lost Sunday entirely. So the bake resolves each of the NEXT EIGHT DATES
    # (yesterday, for its after-midnight tail, through six days on) to its own service_ids the
    # way the spec says -- range and weekday flag, minus type-2 exceptions, plus type-1 -- and
    # stores each row's departures per date. Identical days share one list. It is good for a
    # week: the widget needs a nightly bake.
    from zoneinfo import ZoneInfo
    routes = {r['route_id']: r for r in rd('routes.txt')}
    la_today = datetime.datetime.now(ZoneInfo('America/Los_Angeles')).date()
    dates = [la_today + datetime.timedelta(days=k) for k in range(-1, 7)]
    flags = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
    cal = rd('calendar.txt')
    exc = defaultdict(dict)
    for x in rd('calendar_dates.txt'):
        exc[x['date']][x['service_id']] = x['exception_type']
    active = {}
    for d in dates:
        ds = d.strftime('%Y%m%d')
        on = {c['service_id'] for c in cal if c['start_date'] <= ds <= c['end_date'] and c[flags[d.weekday()]] == '1'}
        on -= {sid for sid, t in exc[ds].items() if t == '2'}
        on |= {sid for sid, t in exc[ds].items() if t == '1'}
        active[ds] = on
    svc_dates = defaultdict(list)
    for ds, on in active.items():
        for sid in on:
            svc_dates[sid].append(ds)
    trips = {t['trip_id']: t for t in rd('trips.txt')}
    stops = {x['stop_id']: x for x in rd('stops.txt')}
    parent = lambda sid: (stops[sid].get('parent_station') or sid) if sid in stops else sid     # noqa: E731
    by_trip = defaultdict(list)
    for st in rd('stop_times.txt'):
        by_trip[st['trip_id']].append((int(st['stop_sequence']), st['stop_id'], st.get('departure_time') or st.get('arrival_time')))
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    heads = defaultdict(Counter)
    for tid, rows in by_trip.items():
        t = trips.get(tid)
        if not t or t['route_id'] not in routes or t['service_id'] not in svc_dates:
            continue
        rows.sort()
        head = (t.get('trip_headsign') or stops.get(rows[-1][1], {}).get('stop_name') or '').replace(' Station', '').strip()
        line = name_of(routes[t['route_id']])
        # BY DIRECTION, not by headsign: the A Line alone signs its northbound trains three
        # ways (APU / Citrus College, Pomona North, one Monrovia short-turn a day), and a
        # rider on the platform wants "the next train that way". The commonest sign names it.
        dirn = t.get('direction_id') or '0'
        for seq, sid, tm in rows[:-1]:
            if not tm:
                continue
            h, m = int(tm[:-6]), int(tm[-5:-3])
            for ds in svc_dates[t['service_id']]:
                out[parent(sid)][(line, dirn)][ds].add(h * 60 + m)
            heads[(parent(sid), line, dirn)][head] += 1
    res = {}
    for pid, rows in out.items():
        rr = []
        for (l, d), per in sorted(rows.items()):
            lists, idx = [], {}
            for ds in sorted(per):
                v = sorted(per[ds])
                if v not in lists:
                    lists.append(v)
                idx[ds] = lists.index(v)
            rr.append({'r': l, 'h': heads[(pid, l, d)].most_common(1)[0][0], 'd': idx, 't': lists})
        res[pid] = {'kind': kind, 'rows': rr}
    return res


def bake_sched():
    print('train times (published timetable)')
    m = sched_from(gtfs(METRO_GTFS), lambda r: (r.get('route_short_name') or r.get('route_long_name') or r['route_id']).replace('Metro ', '').replace(' Line', '').strip(), 'metro')
    k = sched_from(gtfs(METROLINK_GTFS), lambda r: (r.get('route_short_name') or r.get('route_long_name') or r['route_id']).replace(' Line', '').strip(), 'commuter')
    m.update(k)
    names = {f['properties']['id']: f['properties']['name'] for f in json.load(open(os.path.join(HERE, 'rail_stops.json')))['features']}
    smc = [i for i, n in names.items() if '17th' in n]
    print('  %d stations; default candidates: %s' % (len(m), [(i, names[i]) for i in smc]))
    for i in smc:
        for r in m.get(i, {}).get('rows', []):
            print('    %s to %-26s %s' % (r['r'], r['h'], ', '.join('%s:%d' % (ds[4:], len(r['t'][ix])) for ds, ix in sorted(r['d'].items()))))
    write('rail_sched.json', m)


# ------------------------------------------------------------ swell mask ----
# THE ISLANDS, FOR THE SWELL SHADOW. The surf layer draws the swell as moving crests and fades
# them where land stands between a patch of sea and the open ocean the swell is coming from.
# The islands that do that to Los Angeles are mostly OUTSIDE the map's frame -- Catalina, San
# Clemente, San Nicolas, Santa Barbara Island, the northern Channel Islands -- so the lab cannot
# use the view's own water mask. This is the land/sea mask of the whole Bight, 0.01 degree
# (~1 km) cells, from ETOPO: land opaque, sea clear, a 12 KB PNG the page reads into an array.
SWELL_BOX = (-121.0, 32.2, -117.0, 34.8)


def bake_swell():
    from PIL import Image
    print('swell shadow mask')
    a = dem_pull(SWELL_BOX, 0.01, ETOPO_15S)
    land = (a > 0) & (a > -9000)
    # the same rule as the seafloor: below sea level but cut off from the ocean is land
    lab, nl = ndimage.label(~land)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    sea = np.isin(lab, edge[edge > 0])
    out = np.zeros(a.shape + (2,), 'uint8')
    out[..., 1] = np.where(sea, 0, 255)
    Image.fromarray(out).save(os.path.join(HERE, 'swell_land.png'), optimize=True)
    print('  swell_land.png  %dx%d  land %.0f%%  %d KB' % (a.shape[1], a.shape[0], 100 * (~sea).mean(), os.path.getsize(os.path.join(HERE, 'swell_land.png')) // 1024))
    for nm, lo, la in (('Catalina', -118.42, 33.39), ('San Clemente I.', -118.49, 32.90), ('San Nicolas I.', -119.50, 33.25),
                       ('Santa Cruz I.', -119.75, 34.02), ('open sea', -119.0, 33.0), ('Santa Monica Bay', -118.60, 33.90)):
        x = int((lo - SWELL_BOX[0]) / 0.01); y = int((SWELL_BOX[3] - la) / 0.01)
        print('    %-18s %s' % (nm, 'LAND' if not sea[y, x] else 'sea'))


# ------------------------------------------------------------ swell depth ----
# THE DEPTH THE SWELL FEELS. A swell turns toward shallow water -- that is why crests arrive
# nearly square to every beach whatever their direction offshore, and how a south swell wraps
# into Malibu. The lab computes that bending from the seafloor itself (an eikonal solve: the
# wave's speed at each cell follows from its period and the depth there), so it needs depth as
# NUMBERS, not as a shaded picture. NOAA Coastal Relief Model, 250 m cells over the surf map's
# reach; depth in DECIMETRES packed into a PNG's red and green bytes (R*256+G), land = 0,
# lossless, ~200 KB. Blue carries nothing; alpha is opaque so no browser premultiplies it away.
DEPTH_BOX = (-119.30, 33.30, -117.80, 34.20)
DEPTH_STEP = 0.0025


def bake_depth():
    from PIL import Image
    print('swell depth grid')
    a = dem_pull(DEPTH_BOX, DEPTH_STEP, RASTER['1as'])
    a = np.where(a < -9000, 0, a)
    d = np.clip(np.round(-a * 10), 0, 65535).astype('uint16')          # decimetres of water; land 0
    out = np.zeros(a.shape + (3,), 'uint8')
    out[..., 0] = d >> 8
    out[..., 1] = d & 255
    Image.fromarray(out).save(os.path.join(HERE, 'swell_depth.png'), optimize=True)
    print('  swell_depth.png  %dx%d  sea %.0f%%  deepest %.0f m  %d KB' % (a.shape[1], a.shape[0], 100 * (d > 0).mean(), d.max() / 10.0,
                                                                        os.path.getsize(os.path.join(HERE, 'swell_depth.png')) // 1024))
    for nm, lo, la in (('Redondo Canyon head', -118.42, 33.83), ('Santa Monica Bay mid', -118.60, 33.90), ('off Malibu 1 km', -118.68, 34.025), ('San Pedro Basin', -118.45, 33.55)):
        x = int((lo - DEPTH_BOX[0]) / DEPTH_STEP); y = int((DEPTH_BOX[3] - la) / DEPTH_STEP)
        print('    %-22s %6.1f m' % (nm, d[y, x] / 10.0))


# ------------------------------------------------------------- earthquakes ----
# WHAT THE GROUND HAS ACTUALLY DONE (user 2026-09-19: "since LA is earthquake prone, can
# you add earthquake hazard data to that geology view"). The USGS catalogue, keyless and
# CORS-open, so the RECENT swarm is fetched live by the map; this bakes only the record
# that does not change -- every M4.5 and over since 1900. Fourteen of them reached M5.5:
# Northridge 1994, San Fernando 1971, Long Beach 1933.
FDSN = 'https://earthquake.usgs.gov/fdsnws/event/1/query'


def bake_quakes():
    print('earthquakes')
    w, s, e, n = PULL
    q = {'format': 'geojson', 'starttime': '1900-01-01', 'minmagnitude': 4.5, 'orderby': 'time',
         'minlatitude': s, 'maxlatitude': n, 'minlongitude': w, 'maxlongitude': e}
    d = json.loads(get(FDSN + '?' + urllib.parse.urlencode(q)))
    feats = []
    for f in d['features']:
        p = f['properties']
        c = f['geometry']['coordinates']
        if p.get('mag') is None:
            continue
        feats.append({'type': 'Feature',
                      'properties': {'mag': round(p['mag'], 1), 'place': p.get('place'),
                                     'time': p['time'], 'type': p.get('magType'),
                                     'depth': None if c[2] is None else round(c[2], 1),
                                     'url': p.get('url')},
                      'geometry': {'type': 'Point', 'coordinates': [round(c[0], 4), round(c[1], 4)]}})
    feats.sort(key=lambda f: -f['properties']['mag'])
    print('  %d since 1900 at M4.5+; %d reached M5.5' % (len(feats), sum(1 for f in feats if f['properties']['mag'] >= 5.5)))
    for f in feats[:4]:
        p = f['properties']
        print('    M%.1f  %s  %s' % (p['mag'], datetime.datetime.utcfromtimestamp(p['time'] / 1000).strftime('%Y-%m-%d'), (p['place'] or '')[:40]))
    write('quakes.json', {'type': 'FeatureCollection', 'features': feats})


# ------------------------------------------------------------ shaking ----
# HOW HARD THE GROUND WILL SHAKE, which on a geology map is the geology's own doing.
#
# The obvious layer is the hazard itself -- CGS MS48 gives Modified Mercalli from peak
# ground acceleration at 2% in 50 years -- but MEASURED over the home frame it is a flat
# wash: 74.6% of the basin sits in one half-unit band (MMI 9.0 to 9.5) and none of it
# falls below 8.7. All of Los Angeles is in the top bracket. That is worth SAYING, and it
# is in the tap readout, but drawn as a map it is one colour and tells you nothing.
#
# What does vary, sharply, is how the ground under you answers: Vs30, the shear-wave speed
# in the top 30 m. Over the same frame it runs 228 m/s in the deep basin fill to 626 in the
# hills -- soft ground amplifies, hard rock does not -- and it follows the Macrostrat units
# already on the card, which is the point of putting it here. So the SOFT GROUND is drawn,
# by the NEHRP classes, and the hazard number is reported on tap.
CGS_IMG = 'https://gis.conservation.ca.gov/server/rest/services/CGS/%s/ImageServer/exportImage'
VS30_SRC = 'MS48_Vs30_ShearWaveVelocity2022'
MMI_SRC = 'MS48_MMI_PGA_2pc50'
SOFT_LEVELS = ((180, 'E'), (360, 'D'))        # NEHRP: E soft soil, D stiff soil
TAP_STEP = 0.004                              # ~440 m, the readout grid over the home frame


def _cgs(src, box, size):
    q = {'bbox': '%f,%f,%f,%f' % box, 'bboxSR': 4326, 'imageSR': 4326, 'size': '%d,%d' % size,
         'format': 'tiff', 'pixelType': 'F32', 'noData': -9999,
         'interpolation': 'RSP_BilinearInterpolation', 'f': 'image'}
    return tifffile.imread(io.BytesIO(get((CGS_IMG % src) + '?' + urllib.parse.urlencode(q), 300))).astype('float32')


def bake_shake():
    print('shaking')
    vs = _cgs(VS30_SRC, PULL, (1150, 775))
    sea = ~np.isfinite(vs) | (vs < 80)
    print('  Vs30 grid %s, %.0f to %.0f m/s over land (%.0f%% of the frame)'
          % (vs.shape, vs[~sea].min(), vs[~sea].max(), 100 * (~sea).mean()))
    # the ocean and everything outside California read -9999, which is "softer than soft":
    # push it the other way so the rings close on the coast instead of swallowing the sea
    vs = np.where(sea, 9999.0, vs)
    soft = ndimage.gaussian_filter(vs, 1.0)
    feats = []
    for lvl, cls in SOFT_LEVELS:
        rings = contour_rings(soft, lvl, False)
        print('  under %4d m/s (NEHRP %s): %d rings' % (lvl, cls, len(rings)))
        if not rings:      # class E does not occur here: the softest ground measures 176 m/s
            continue
        feats.append({'type': 'Feature', 'properties': {'cls': cls, 'vs30': lvl},
                      'geometry': {'type': 'Polygon', 'coordinates': rings}})

    hw, hs, he, hn = home_box()
    cols = int(round((he - hw) / TAP_STEP))
    rows = int(round((hn - hs) / TAP_STEP))
    gv = _cgs(VS30_SRC, (hw, hs, he, hn), (cols, rows))
    gm = _cgs(MMI_SRC, (hw, hs, he, hn), (cols, rows))
    q = lambda a, k: [(-1 if (not np.isfinite(v) or v < -100) else int(round(v * k))) for v in a.ravel()]  # noqa: E731
    live = np.isfinite(gm) & (gm > 3)
    print('  tap grid %dx%d at %.3f deg; MMI %.1f to %.1f over the home frame'
          % (cols, rows, TAP_STEP, gm[live].min(), gm[live].max()))
    write('shake.json', {'soft': {'type': 'FeatureCollection', 'features': feats},
                         'grid': {'w': hw, 's': hs, 'e': he, 'n': hn, 'step': TAP_STEP,
                                  'cols': cols, 'rows': rows,
                                  'vs30': q(gv, 1), 'mmi': q(gm, 10)}})


PARTS = {'depth': bake_depth, 'swell': bake_swell, 'sched': bake_sched, 'geo': bake_geo, 'air': bake_air, 'veg': bake_veg, 'region': bake_region, 'land': bake_land, 'city': bake_city, 'rail': bake_rail, 'faults': bake_faults, 'dem': bake_dem, 'sea': bake_sea,
         'quakes': bake_quakes, 'shake': bake_shake}

if __name__ == '__main__':
    print('home box  w %.4f  s %.4f  e %.4f  n %.4f' % home_box())
    for k in (sys.argv[1:] or list(PARTS)):
        PARTS[k]()
