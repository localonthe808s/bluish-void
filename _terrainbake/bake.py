#!/usr/bin/env python3
"""THE GROUND AND THE WEATHER, for the whole lower 48 (user 2026-10-16: "we feature geological features that influence
the weather in ny, those features technically work for more than ny ... fill out the national map with all geological
features and their effects on the weather so wherever the user is they can see these on their local map").

THE RIDGES' method, national: the landforms are the USGS physiographic sections (Fenneman & Johnson 1946,
water.usgs.gov/GIS/dsdl/physio_shp.zip), each given its typical height (median of a 0.025 deg 3DEP grid) and ONE line on
what it does to the weather -- where snow piles up, where cold air gets stuck, where storms tend to fire (the user's rule
from 2026-10-11: weather effects, never rock ages). Only well-established patterns are written here.

The EDGES are the boundaries that drive the weather (the Allegheny Front, the Blue Ridge, the Rocky Mountain Front, the
Sierra and Cascade faces, the Mogollon Rim, the Balcones and Caprock escarpments, the Wasatch). Each starts as the shared
border of the named sections, with its uphill side read off the elevation grid, so the page can say whether the wind right
now is pushing air up it or pouring down it. SPOTS are the few named effects that are not a province: the Great Lakes snow
belts, the Great Salt Lake, the Columbia Gorge, the Puget Sound Convergence Zone, the Palmer Divide.

v3 (user 2026-10-18: "crudely drawn and not cleanly outlining features and its text unhelpful sometimes" ... "A real fix
means rebuilding that data file at finer detail and rewriting the notes so each one describes what that edge does to the
weather now ... do this"):
  - every edge is moved off the 1:7M Fenneman line onto the real step in the ground (snap.py: the steepest face, the foot
    of a mountain front or the lip of a rim, traced on ~230 m terrain tiles within +-15 km, Viterbi-continuous), flat
    stretches dropped, then smoothed and simplified at ~200 m (`c`) and ~1 km (`c6`, for zoom 6 and out);
  - the edges carry no canned sentences any more: the page writes the live note from the wind, humidity and temperature at
    the edge's level right now (up it / down it / along it). Per edge only `dg`, the strong-downslope line where a named
    wind is well established (the Chinook, the Wasatch canyon winds, the Sierra and Cascade east winds);
  - each section carries ONE line (`w`) about its weather, shown only for the ground under the place.

    python3 bake.py physio.shp dem.tif TILE_CACHE_DIR OUT.json
dem.tif: 3DEP exportImage bbox=-125,24,-66,50 bboxSR=4326 imageSR=4326 size=2360,1040 F32. Terrain tiles: AWS open
elevation-tiles-prod terrarium z9, fetched into TILE_CACHE_DIR as needed (~600 tiles).
"""
import json, math, os, sys
import numpy as np, shapefile, tifffile
from PIL import Image, ImageDraw
from shapely.geometry import shape, Point
from shapely.ops import unary_union, polylabel, linemerge
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snap

# section -> (shown name, the one line about its weather). Sections not listed carry their own name and no line.
# ONE HELPFUL LINE (user 2026-10-18: "its text unhelpful sometimes"): what this ground does to the air above it, ~25 chars
SEC = {
 ('CENTRAL LOWLAND', 'WESTERN LAKE'): ('WESTERN LAKE COUNTRY', 'ARCTIC AIR ARRIVES UNSLOWED'),
 ('CENTRAL LOWLAND', 'EASTERN LAKE'): ('GREAT LAKES LOWLANDS', 'LAKES TEMPER HEAT AND COLD'),
 ('CENTRAL LOWLAND', 'WISCONSIN DRIFTLESS'): ('DRIFTLESS AREA', 'COLD AIR POOLS IN VALLEYS'),
 ('CENTRAL LOWLAND', 'DISSECTED TILL PLAINS'): ('DISSECTED TILL PLAINS', 'FLAT: FRONTS CROSS UNSLOWED'),
 ('CENTRAL LOWLAND', 'TILL PLAINS'): ('TILL PLAINS', 'FLAT: STORM LINES RUN FREE'),
 ('CENTRAL LOWLAND', 'OSAGE PLAINS'): ('OSAGE PLAINS', 'GULF AIR FEEDS SPRING STORMS'),
 ('GREAT PLAINS', 'MISSOURI PLATEAU, GLACIATED'): ('MISSOURI PLATEAU', 'OPEN GROUND: BLIZZARDS'),
 ('GREAT PLAINS', 'MISSOURI PLATEAU, UNGLACIATED'): ('MISSOURI PLATEAU', 'CHINOOKS MELT SNOW FAST'),
 ('GREAT PLAINS', 'BLACK HILLS'): ('BLACK HILLS', 'AFTERNOON STORMS FIRE HERE'),
 ('GREAT PLAINS', 'HIGH PLAINS'): ('HIGH PLAINS', 'DRYLINE: HAIL, TORNADOES'),
 ('GREAT PLAINS', 'COLORADO PIEDMONT'): ('COLORADO PIEDMONT', 'EAST WINDS: UPSLOPE SNOW'),
 ('GREAT PLAINS', 'PLAINS BORDER'): ('PLAINS BORDER', 'NIGHT STORMS ON THE LOW JET'),
 ('GREAT PLAINS', 'RATON'): ('RATON MESAS', 'EAST WINDS: UPSLOPE SNOW'),
 ('GREAT PLAINS', 'PECOS VALLEY'): ('PECOS VALLEY', 'HOT, DRY LEE LOWLAND'),
 ('GREAT PLAINS', 'EDWARDS PLATEAU'): ('EDWARDS PLATEAU', 'FAST RUNOFF: FLASH FLOODS'),
 ('GREAT PLAINS', 'CENTRAL TEXAS'): ('CENTRAL TEXAS HILLS', 'STALLED FRONTS: FLOOD RAIN'),
 ('APPALACHIAN PLATEAUS', 'MOHAWK'): ('MOHAWK VALLEY', 'ONTARIO SNOW BANDS REACH IN'),
 ('APPALACHIAN PLATEAUS', 'SOUTHERN NEW YORK'): ('ALLEGHENY PLATEAU', 'LAKE AND UPSLOPE SNOW'),
 ('APPALACHIAN PLATEAUS', 'CATSKILL'): ('THE CATSKILLS', 'EAST WINDS WRING OUT SNOW'),
 ('APPALACHIAN PLATEAUS', 'KANAWHA'): ('KANAWHA PLATEAU', 'VALLEY FOG, FLASH FLOODS'),
 ('APPALACHIAN PLATEAUS', 'ALLEGHENY MOUNTAIN'): ('ALLEGHENY MOUNTAINS', 'WEST WINDS: UPSLOPE SNOW'),
 ('APPALACHIAN PLATEAUS', 'CUMBERLAND PLATEAU'): ('CUMBERLAND PLATEAU', 'COOLER, FOGGIER THAN VALLEYS'),
 ('APPALACHIAN PLATEAUS', 'CUMBERLAND MOUNTAIN'): ('CUMBERLAND MOUNTAINS', 'NORTHWEST WINDS: SNOW'),
 ('VALLEY AND RIDGE', 'HUDSON VALLEY'): ('HUDSON VALLEY', 'TRAPS COLD: FREEZING RAIN'),
 ('VALLEY AND RIDGE', 'MIDDLE'): ('RIDGE AND VALLEY', 'VALLEYS STEER WIND, POOL FOG'),
 ('VALLEY AND RIDGE', 'TENNESSEE'): ('GREAT VALLEY OF TENNESSEE', 'THE VALLEY STEERS THE WIND'),
 ('BLUE RIDGE', 'NORTHERN'): ('BLUE RIDGE', 'COLD AIR WEDGES EAST OF IT'),
 ('BLUE RIDGE', 'SOUTHERN'): ('SOUTHERN BLUE RIDGE', 'SOUTH WINDS: HEAVY RAIN'),
 ('PIEDMONT', 'PIEDMONT UPLAND'): ('PIEDMONT', 'COLD WEDGE: ICE, LOW CLOUD'),
 ('PIEDMONT', 'PIEDMONT LOWLANDS'): ('PIEDMONT LOWLANDS', 'COLD WEDGE: ICE, LOW CLOUD'),
 ('NEW ENGLAND', 'NEW ENGLAND UPLAND'): ('NEW ENGLAND UPLAND', 'SNOW WHILE THE COAST RAINS'),
 ('NEW ENGLAND', 'WHITE MOUNTAIN'): ('WHITE MOUNTAINS', 'EXTREME SUMMIT WINDS'),
 ('NEW ENGLAND', 'GREEN MOUNTAIN'): ('GREEN MOUNTAINS', 'WEST-FACE UPSLOPE SNOW'),
 ('NEW ENGLAND', 'TACONIC'): ('TACONIC HILLS', 'SNOW WHILE THE VALLEY RAINS'),
 ('NEW ENGLAND', 'SEABOARD LOWLAND'): ('NEW ENGLAND COAST', 'THE RAIN–SNOW LINE SITS HERE'),
 ('ST. LAWRENCE VALLEY', 'CHAMPLAIN'): ('CHAMPLAIN VALLEY', 'FUNNELS ARCTIC NORTH WINDS'),
 ('ADIRONDACK', ''): ('ADIRONDACKS', 'COLDEST NIGHTS IN THE EAST'),
 ('SUPERIOR UPLAND', ''): ('SUPERIOR UPLAND', 'SOUTH-SHORE SNOW BELTS'),
 ('INTERIOR LOW PLATEAUS', 'HIGHLAND RIM'): ('HIGHLAND RIM', 'SLOW STORMS: HEAVY RAIN'),
 ('INTERIOR LOW PLATEAUS', 'LEXINGTON PLAIN'): ('BLUEGRASS', 'STORM LINES CROSS UNBROKEN'),
 ('INTERIOR LOW PLATEAUS', 'NASHVILLE BASIN'): ('NASHVILLE BASIN', 'COLD AIR POOLS: NIGHT FOG'),
 ('OZARK PLATEAUS', 'SPRINGFIELD-SALEM PLATEAUS'): ('OZARK PLATEAU', 'HEAVY RAIN, FLASHY VALLEYS'),
 ('OZARK PLATEAUS', 'BOSTON "MOUNTAINS"'): ('BOSTON MOUNTAINS', 'SOUTH WINDS: HEAVY RAIN'),
 ('OUACHITA', 'ARKANSAS VALLEY'): ('ARKANSAS VALLEY', 'FUNNELS WIND EAST–WEST'),
 ('OUACHITA', 'OUACHITA MOUNTAINS'): ('OUACHITA MOUNTAINS', 'WETTEST GROUND IN ARKANSAS'),
 ('COASTAL PLAIN', 'EMBAYED'): ('COASTAL PLAIN', 'SEA BREEZE FIRES STORMS'),
 ('COASTAL PLAIN', 'SEA ISLAND'): ('SEA ISLANDS', 'SEA-BREEZE STORMS INLAND'),
 ('COASTAL PLAIN', 'EAST GULF COASTAL PLAIN'): ('EAST GULF COASTAL PLAIN', 'GULF DOWNPOURS, TORNADOES'),
 ('COASTAL PLAIN', 'MISSISSIPPI ALLUVIAL PLAIN'): ('MISSISSIPPI DELTA', 'STICKY DEW POINTS ALL SUMMER'),
 ('COASTAL PLAIN', 'FLORIDIAN'): ('FLORIDA PENINSULA', 'SEA BREEZES COLLIDE: STORMS'),
 ('COASTAL PLAIN', 'WEST GULF COASTAL PLAIN'): ('WEST GULF COASTAL PLAIN', 'GULF AIR ON SOUTH WINDS'),
 ('PACIFIC BORDER', 'PUGET TROUGH'): ('PUGET–WILLAMETTE LOWLAND', 'LIGHT, STEADY RAIN'),
 ('PACIFIC BORDER', 'OLYMPIC MOUNTAINS'): ('OLYMPIC MOUNTAINS', 'WETTEST IN THE LOWER 48'),
 ('PACIFIC BORDER', 'OREGON COAST RANGE'): ('OREGON COAST RANGE', 'FIRST LIFT: HEAVY RAIN'),
 ('PACIFIC BORDER', 'CALIFORNIA COAST RANGES'): ('CALIFORNIA COAST RANGES', 'HOLDS THE MARINE LAYER'),
 ('PACIFIC BORDER', 'KLAMATH MOUNTAINS'): ('KLAMATH MOUNTAINS', 'HEAVY RAIN AND SNOW'),
 ('PACIFIC BORDER', 'CALIFORNIA TROUGH'): ('CENTRAL VALLEY', 'WINTER TULE FOG'),
 ('PACIFIC BORDER', 'LOS ANGELES RANGES'): ('TRANSVERSE RANGES', 'SANTA ANAS THROUGH PASSES'),
 ('LOWER CALIFORNIAN', ''): ('PENINSULAR RANGES', 'SANTA ANAS THROUGH PASSES'),
 ('CASCADE-SIERRA MOUNTAINS', 'NORTHERN CASCADE MOUNTAINS'): ('NORTH CASCADES', 'DEEP SNOW WEST, DRY EAST'),
 ('CASCADE-SIERRA MOUNTAINS', 'MIDDLE CASCADE MOUNTAINS'): ('CASCADES', 'DEEP SNOW WEST, DRY EAST'),
 ('CASCADE-SIERRA MOUNTAINS', 'SOUTHERN CASCADE MOUNTAINS'): ('SOUTHERN CASCADES', 'DEEP SNOW WEST, DRY EAST'),
 ('CASCADE-SIERRA MOUNTAINS', 'SIERRA NEVADA'): ('SIERRA NEVADA', 'DEEP SNOW WEST, DRY EAST'),
 ('COLUMBIA PLATEAU', 'WALLA WALLA PLATEAU'): ('COLUMBIA BASIN', 'RAIN SHADOW, WINTER FOG'),
 ('COLUMBIA PLATEAU', 'BLUE MOUNTAIN'): ('BLUE MOUNTAINS', 'SNOW ON THE HIGH GROUND'),
 ('COLUMBIA PLATEAU', 'PAYETTE'): ('PAYETTE', 'WINTER INVERSIONS: FOG, HAZE'),
 ('COLUMBIA PLATEAU', 'SNAKE RIVER PLAIN'): ('SNAKE RIVER PLAIN', 'DRY; WINDS FUNNEL ACROSS'),
 ('COLUMBIA PLATEAU', 'HARNEY'): ('HARNEY HIGH DESERT', 'FROST EVEN IN SUMMER'),
 ('NORTHERN ROCKY MOUNTAINS', ''): ('NORTHERN ROCKIES', 'HOLDS ARCTIC AIR TO THE EAST'),
 ('MIDDLE ROCKY MOUNTAINS', ''): ('MIDDLE ROCKIES', 'DEEP SNOW, SUMMER STORMS'),
 ('SOUTHERN ROCKY MOUNTAINS', ''): ('SOUTHERN ROCKIES', 'SUMMER STORMS ON THE PEAKS'),
 ('WYOMING BASIN', ''): ('WYOMING BASIN', 'FIERCE WEST WINDS'),
 ('COLORADO PLATEAUS', 'UINTA BASIN'): ('UINTA BASIN', 'WINTER INVERSIONS, HAZE'),
 ('COLORADO PLATEAUS', 'HIGH PLATEAUS OF UTAH'): ('HIGH PLATEAUS OF UTAH', 'SNOW, MONSOON STORMS'),
 ('COLORADO PLATEAUS', 'CANYON LANDS'): ('CANYON LANDS', 'SLOT-CANYON FLASH FLOODS'),
 ('COLORADO PLATEAUS', 'NAVAJO'): ('NAVAJO SECTION', 'BIG DAY–NIGHT SWINGS'),
 ('COLORADO PLATEAUS', 'GRAND CANYON'): ('GRAND CANYON SECTION', 'RIM SNOW, GORGE HEAT'),
 ('COLORADO PLATEAUS', 'DATIL'): ('DATIL–MOGOLLON', 'MONSOON STORMS FIRE HERE'),
 ('BASIN AND RANGE', 'GREAT BASIN'): ('GREAT BASIN', 'SIERRA RAIN SHADOW: DRY'),
 ('BASIN AND RANGE', 'SONORAN DESERT'): ('SONORAN DESERT', 'EXTREME HEAT, HABOOBS'),
 ('BASIN AND RANGE', 'MEXICAN HIGHLAND'): ('MEXICAN HIGHLAND', 'SKY-ISLAND MONSOON STORMS'),
 ('BASIN AND RANGE', 'SACRAMENTO'): ('SACRAMENTO SECTION', 'MONSOON STORMS ON PEAKS'),
 ('BASIN AND RANGE', 'SALTON TROUGH'): ('SALTON TROUGH', 'BELOW SEA LEVEL: EXTREME HEAT'),
}
# edges: (name, high side sections, low side sections, lev, the trace (snap.snap keywords), strong-downslope line or '').
# lev: the pressure level the page reads the wind, humidity and temperature at (hPa).
# mode (snap.py): 'foot' for a mountain front seen from its lowland, 'rim' for a plateau's lip, 'face' for a cliff band.
EDGE = [
 ('ALLEGHENY FRONT', [('APPALACHIAN PLATEAUS', 'ALLEGHENY MOUNTAIN'), ('APPALACHIAN PLATEAUS', 'SOUTHERN NEW YORK'), ('APPALACHIAN PLATEAUS', 'KANAWHA')],
  [('VALLEY AND RIDGE', 'MIDDLE')], 850, {}, ''),
 ('BLUE RIDGE FRONT', [('BLUE RIDGE', 'NORTHERN'), ('BLUE RIDGE', 'SOUTHERN')], [('PIEDMONT', 'PIEDMONT UPLAND'), ('PIEDMONT', 'PIEDMONT LOWLANDS')], 850,
  {'mode': 'foot'}, ''),
 ('ROCKY MOUNTAIN FRONT', [('SOUTHERN ROCKY MOUNTAINS', ''), ('MIDDLE ROCKY MOUNTAINS', ''), ('NORTHERN ROCKY MOUNTAINS', '')],
  [('GREAT PLAINS', 'COLORADO PIEDMONT'), ('GREAT PLAINS', 'HIGH PLAINS'), ('GREAT PLAINS', 'RATON'), ('GREAT PLAINS', 'MISSOURI PLATEAU, UNGLACIATED'), ('GREAT PLAINS', 'MISSOURI PLATEAU, GLACIATED')], 700,
  # THE FOOT, NOT THE SECTION SEAM (user 2026-10-18: "jog near Cañon City (it follows Fenneman's section border west around
  # the Royal Gorge area)"): from Colorado Springs the trace is seeded along the mountain foot -- Cheyenne Mountain, Cañon
  # City, then down the Wet Mountains' east face past Florence, Wetmore, Beulah and Rye -- before rejoining the border
  {'mode': 'foot', 'seeds': [[(-104.86, 38.86), (-104.88, 38.74), (-104.97, 38.62), (-105.08, 38.52), (-105.20, 38.46), (-105.13, 38.37),
                              (-105.08, 38.23), (-104.99, 38.08), (-104.95, 37.93), (-104.98, 37.86)]]}, 'CHINOOK: WARM GUSTS BELOW'),
 ('SIERRA WEST SLOPE', [('CASCADE-SIERRA MOUNTAINS', 'SIERRA NEVADA')], [('PACIFIC BORDER', 'CALIFORNIA TROUGH')], 700,
  {'mode': 'foot'}, 'DRY EAST WINDS: FIRE WEATHER'),
 ('SIERRA ESCARPMENT', [('CASCADE-SIERRA MOUNTAINS', 'SIERRA NEVADA')], [('BASIN AND RANGE', 'GREAT BASIN')], 700,
  {'mode': 'foot'}, 'GUSTS AND WAVE CLOUDS BELOW'),
 ('CASCADE WEST SLOPE', [('CASCADE-SIERRA MOUNTAINS', 'NORTHERN CASCADE MOUNTAINS'), ('CASCADE-SIERRA MOUNTAINS', 'MIDDLE CASCADE MOUNTAINS'), ('CASCADE-SIERRA MOUNTAINS', 'SOUTHERN CASCADE MOUNTAINS')],
  [('PACIFIC BORDER', 'PUGET TROUGH'), ('PACIFIC BORDER', 'KLAMATH MOUNTAINS'), ('PACIFIC BORDER', 'CALIFORNIA TROUGH')], 850,
  {'mode': 'foot'}, 'DRY EAST WINDS: FIRE WEATHER'),
 ('CASCADE EAST SLOPE', [('CASCADE-SIERRA MOUNTAINS', 'NORTHERN CASCADE MOUNTAINS'), ('CASCADE-SIERRA MOUNTAINS', 'MIDDLE CASCADE MOUNTAINS'), ('CASCADE-SIERRA MOUNTAINS', 'SOUTHERN CASCADE MOUNTAINS')],
  [('COLUMBIA PLATEAU', 'WALLA WALLA PLATEAU'), ('COLUMBIA PLATEAU', 'HARNEY'), ('BASIN AND RANGE', 'GREAT BASIN')], 850,
  {'mode': 'foot'}, ''),
 ('MOGOLLON RIM', [('COLORADO PLATEAUS', 'DATIL'), ('COLORADO PLATEAUS', 'NAVAJO'), ('COLORADO PLATEAUS', 'GRAND CANYON')],
  [('BASIN AND RANGE', 'MEXICAN HIGHLAND'), ('BASIN AND RANGE', 'SONORAN DESERT')], 700,
  {'mode': 'rim', 'minstep': 10}, ''),
 ('BALCONES ESCARPMENT', [('GREAT PLAINS', 'EDWARDS PLATEAU')], [('COASTAL PLAIN', 'WEST GULF COASTAL PLAIN')], 850,
  # ON TO WACO (user 2026-10-18: "the line stops at Fenneman's Edwards Plateau border so the Austin-Waco stretch is
  # missing"): north of Austin the Balcones Fault Zone divides the Lampasas Cut Plain from the Blackland Prairie, which
  # Fenneman files under other sections; a seed through Georgetown, Salado, Belton and Moody, snapped to the steepest face
  {'corr': 20, 'minstep': 5, 'seeds': [[(-97.15, 31.55), (-97.30, 31.38), (-97.40, 31.20), (-97.49, 31.03), (-97.57, 30.86), (-97.68, 30.64),
                                        (-97.73, 30.46), (-97.79, 30.30)]]}, ''),
 # the Fenneman Caprock line runs 25-35 km east of the real lip of the Llano Estacado: a wider corridor, a weaker pull
 ('CAPROCK ESCARPMENT', [('GREAT PLAINS', 'HIGH PLAINS')], [('CENTRAL LOWLAND', 'OSAGE PLAINS')], 850,
  # ...and its lip wraps the canyons (user 2026-10-18: "cut across canyon country instead of wrapping the escarpment around
  # the canyons"): the long stretch is the tableland's own outline (snap.lip), seeded at Lubbock, from where the old trace
  # began south of the Canadian breaks (-100.15, 35.45: north of it the outline wanders the breaks) to Big Spring
  {'corr': 40, 'minstep': 7, 'mode': 'rim', 'pull': 0.25, 'lip': {'seed': (-101.85, 33.58), 'T': 45, 'close': 2.5, 'opn': 1.5, 'a': (-100.15, 35.45)}}, ''),
 ('WASATCH FRONT', [('MIDDLE ROCKY MOUNTAINS', ''), ('COLORADO PLATEAUS', 'HIGH PLATEAUS OF UTAH')], [('BASIN AND RANGE', 'GREAT BASIN')], 700,
  {'mode': 'foot'}, 'CANYON WINDS GUST BELOW'),
]
# SPOTS THAT READ THE WIND (user 2026-10-18: "SPOT NOTES react to the current wind ... make their notes live like the edges";
# "Only well-established patterns"). Each spot: kind `k`, the level its wind is read at (`lev`: 850 / 700 hPa, or 10 for the
# 10 m wind, since the Gorge gap wind and the Front Range upslope are shallow), and `dir` -- the wind directions (FROM, deg,
# clockwise from a to b) that set it off, each with where it acts. The page writes the note (index.html, OV.liveRead):
#   lake   : wind across the lake toward the belt and air cold enough to steam off it (850 hPa -8 C or colder; the Great
#            Salt Lake sits high, so its 700 hPa -12 C) -> 'WIND ACROSS THE LAKE · SNOW BANDS LIKELY' + the belt;
#   gorge  : the gap wind either way (east: dry gusts, ice where it rains on frozen ground; west: marine air pushing inland);
#   pscz   : onshore west-northwest flow split by the Olympics, meeting north of Seattle -> a shower (or snow) band;
#   upslope: north to east winds climbing the Palmer Divide -> more snow, or storms and hail when unstable.
# `min` is the least wind (mph) that counts. Otherwise the name alone, dim. `l` stays for pages still on the old reader.
SPOT = [
 ('LAKE SUPERIOR', -87.5, 47.6, ['SNOW BELTS: SOUTH, EAST SHORES'], 'lake', 850, 10, [[290, 30, 'BANDS ON THE SOUTH SHORE'], [240, 289, 'BANDS INTO THE EAST END']]),
 ('LAKE MICHIGAN', -87.0, 43.8, ['WEST WINDS: EAST-SHORE SNOW'], 'lake', 850, 10, [[240, 330, 'BANDS ON THE MICHIGAN SHORE'], [331, 20, 'BANDS INTO NW INDIANA'], [21, 70, 'BANDS ON THE CHICAGO SHORE']]),
 ('LAKE HURON', -82.4, 44.8, ['WEST WINDS: EAST-SHORE SNOW'], 'lake', 850, 10, [[240, 340, 'BANDS ON THE ONTARIO SHORE']]),
 ('LAKE ERIE', -81.2, 42.2, ['SNOW BELTS: EAST, SOUTHEAST'], 'lake', 850, 10, [[220, 255, 'BANDS INTO BUFFALO'], [256, 340, 'BANDS: OHIO–PENNSYLVANIA SNOW BELT']]),
 ('LAKE ONTARIO', -77.8, 43.6, ['HEAVIEST BANDS: TUG HILL'], 'lake', 850, 10, [[240, 285, 'BANDS INTO TUG HILL'], [286, 340, 'BANDS INTO OSWEGO, SYRACUSE']]),
 ('GREAT SALT LAKE', -112.5, 41.1, ['LAKE-EFFECT SNOW SOUTH, EAST'], 'lake', 700, 10, [[290, 360, 'BANDS INTO THE SALT LAKE VALLEY']]),
 ('COLUMBIA RIVER GORGE', -121.9, 45.65, ['SEA-LEVEL GAP IN THE CASCADES', 'EAST WINDS: ICE STORMS WEST'], 'gorge', 10, 15, [[45, 135, 'EAST'], [225, 315, 'WEST']]),
 ('PUGET SOUND CONVERGENCE ZONE', -122.25, 47.95, ['WINDS SPLIT BY OLYMPICS MEET', 'A BAND OF SHOWERS OR SNOW'], 'pscz', 850, 10, [[230, 320, '']]),
 ('PALMER DIVIDE', -104.65, 39.15, ['HIGHER RIDGE: MORE SNOW, HAIL'], 'upslope', 10, 8, [[340, 120, '']]),
]
W0, S0, DX = -125.0, 24.0, 59.0 / 2360

def main(shp, dem, cache, dst):
    os.makedirs(cache, exist_ok=True)
    Z = tifffile.imread(dem).astype(np.float32); Z[Z < -500] = np.nan
    Hh, Ww = Z.shape
    def zat(lon, lat):
        i, j = int((50 - lat) / (26.0 / Hh)), int((lon - W0) / DX)
        return Z[i, j] if 0 <= i < Hh and 0 <= j < Ww else np.nan
    groups = {}
    for sr in shapefile.Reader(shp).iterShapeRecords():
        d = sr.record.as_dict(); k = (d['PROVINCE'].strip(), d['SECTION'].strip())
        if not k[0]: continue
        groups.setdefault(k, []).append(shape(sr.shape.__geo_interface__).buffer(0))
    secs, geo = [], {}
    for k, gs in groups.items():
        g = unary_union(gs); geo[k] = g
        nm, w = SEC.get(k, ((k[1] or k[0]).title().upper(), ''))
        # typical height: median of the grid inside the section
        m = Image.new('L', (Ww, Hh), 0); dr = ImageDraw.Draw(m)
        for p in (g.geoms if g.geom_type == 'MultiPolygon' else [g]):
            dr.polygon([((x - W0) / DX, (50 - y) / (26.0 / Hh)) for x, y in p.exterior.coords], fill=1)
        v = Z[np.array(m, bool)]; v = v[np.isfinite(v)]
        ft = int(round(float(np.median(v)) * 3.28084 / 100) * 100) if v.size else None
        # label anchors: the pole of the biggest piece, plus a half-degree lattice of points well inside
        big = max(g.geoms, key=lambda p: p.area) if g.geom_type == 'MultiPolygon' else g
        pts = [list(polylabel(big, 0.02).coords[0])]
        inner = g.buffer(-0.12)
        for lo in np.arange(math.floor(g.bounds[0]) + 0.25, g.bounds[2], 0.5):
            for la in np.arange(math.floor(g.bounds[1]) + 0.25, g.bounds[3], 0.5):
                if inner.contains(Point(lo, la)): pts.append([float(lo), float(la)])
        # the rings only find the section a place sits in now (they are no longer drawn), so they stay coarse
        simp = g.simplify(0.02, preserve_topology=True)
        rings = [[[round(x, 3), round(y, 3)] for x, y in p.exterior.coords] for p in (simp.geoms if simp.geom_type == 'MultiPolygon' else [simp]) if p.area > 0.01]
        secs.append({'n': nm, 'p': k[0], 'ft': ft, 'w': w, 'a': [[round(x, 2), round(y, 2)] for x, y in pts], 'r': rings})
    edges = []
    for nm, hi, lo, lev, prm, dg in EDGE:
        H = unary_union([geo[k] for k in hi]); Lw = unary_union([geo[k] for k in lo])
        shared = H.boundary.intersection(Lw.buffer(0.03))
        if shared.is_empty: print('NO EDGE', nm); continue
        lines = [shared] if shared.geom_type == 'LineString' else [g for g in getattr(shared, 'geoms', []) if g.geom_type == 'LineString'] + \
                [q for g in getattr(shared, 'geoms', []) if g.geom_type == 'MultiLineString' for q in g.geoms]
        ln = lines[0] if len(lines) == 1 else linemerge(lines)
        parts = [p for p in (ln.geoms if ln.geom_type == 'MultiLineString' else [ln]) if p.length > 0.4]
        out = []
        for p in parts:
            p = p.simplify(0.03)
            # which side is the high one: probe 0.15 deg either side along the normal at a dozen points
            score = 0
            for t in np.linspace(0.05, 0.95, 12):
                q = p.interpolate(t, normalized=True); q2 = p.interpolate(min(1, t + 0.02), normalized=True)
                dx, dy = q2.x - q.x, q2.y - q.y; L = math.hypot(dx, dy) or 1
                nx, ny = -dy / L, dx / L
                a1, a2 = zat(q.x + nx * 0.15, q.y + ny * 0.15), zat(q.x - nx * 0.15, q.y - ny * 0.15)
                if np.isfinite(a1) and np.isfinite(a2): score += 1 if a1 > a2 else -1
            up = 1 if score >= 0 else -1
            rise = []
            for t in np.linspace(0.05, 0.95, 20):
                q = p.interpolate(t, normalized=True); q2 = p.interpolate(min(1, t + 0.02), normalized=True)
                dx, dy = q2.x - q.x, q2.y - q.y; L = math.hypot(dx, dy) or 1
                nx, ny = -dy / L * up, dx / L * up
                a1, a2 = zat(q.x + nx * 0.1, q.y + ny * 0.1), zat(q.x - nx * 0.1, q.y - ny * 0.1)
                if np.isfinite(a1) and np.isfinite(a2): rise.append(a1 - a2)
            if not rise or float(np.median(rise)) * 3.28084 < 150: continue   # no real step (a valley seam): not this edge
            # ON THE REAL GROUND: the trace off the terrain tiles, then two simplifications
            kw = {a: b for a, b in prm.items() if a not in ('seeds', 'lip')}; cs = list(p.coords)
            for sd in prm.get('seeds', []):
                cs, hit = snap.splice(cs, sd); print('   seed', nm, hit)
            if 'lip' in prm and p.length > 2:
                L = dict(prm['lip']); a, b = L.pop('a', cs[0]), L.pop('b', cs[-1]); print('   lip', nm, cs[0], cs[-1], '->', a, b)
                P = snap.lip(a, b, H, cache=cache, **L)
                pcs, st = [P], {'pts': float(len(P))}
            else:
                pcs, st = snap.snap(cs, up, cache, **kw)
            print('  ', nm, {a: round(b, 1) for a, b in st.items()}, [len(q) for q in pcs])
            for P in pcs:
                c = snap.simp(P, 0.002); c6 = snap.simp(P, 0.01)
                c6 = [[round(x, 3), round(y, 3)] for x, y in c6]
                out.append({'c': c, 'c6': c6, 'up': up})
        edges.append({'n': nm, 'lev': lev, 'dg': dg, 'parts': out})
        print(nm, len(out), 'parts', sum(len(o['c']) for o in out), 'points')
    J = {'v': 3, 'src': 'USGS Physiographic Divisions of the Conterminous U.S. (Fenneman & Johnson 1946); edges traced on AWS Terrain Tiles (USGS 3DEP); heights USGS 3DEP',
         'sec': secs, 'edge': edges, 'spot': [{'n': n, 'c': [lo, la], 'l': l, 'k': k, 'lev': lev, 'min': mn, 'dir': dr} for n, lo, la, l, k, lev, mn, dr in SPOT]}
    json.dump(J, open(dst, 'w'), separators=(',', ':'), ensure_ascii=False)
    print(len(secs), 'sections', os.path.getsize(dst), 'bytes')

if __name__ == '__main__':
    main(*sys.argv[1:5])
