#!/usr/bin/env python3
"""THE GROUND AND THE WEATHER, for the whole lower 48 (user 2026-10-16: "we feature geological features that influence
the weather in ny, those features technically work for more than ny ... fill out the national map with all geological
features and their effects on the weather so wherever the user is they can see these on their local map").

THE RIDGES' method, national: the landforms are the USGS physiographic sections (Fenneman & Johnson 1946,
water.usgs.gov/GIS/dsdl/physio_shp.zip), each given its typical height (median of a 0.025 deg 3DEP grid) and two lines on
what it does to the weather -- where snow piles up, where cold air gets stuck, where storms tend to fire (the user's rule
from 2026-10-11: weather effects, never rock ages). Only well-established patterns are written here.

The EDGES are the boundaries that drive the weather (the Allegheny Front, the Blue Ridge, the Rocky Mountain Front, the
Sierra and Cascade faces, the Mogollon Rim, the Balcones and Caprock escarpments, the Wasatch). Each is the shared
border of the named sections, NOT hand-drawn, with its uphill side read off the elevation grid, so the page can say
whether the wind right now is pushing air up it or pouring down it. SPOTS are the few named effects that are not a
province: the Great Lakes snow belts, the Great Salt Lake, the Columbia Gorge, the Puget Sound Convergence Zone, the
Palmer Divide.

    python3 bake.py physio.shp dem.tif OUT.json
dem.tif: 3DEP exportImage bbox=-125,24,-66,50 bboxSR=4326 size=2360,1040 F32 (see README in this folder's docstring).
"""
import json, math, sys
import numpy as np, shapefile, tifffile
from PIL import Image, ImageDraw
from shapely.geometry import shape, Point, LineString, MultiLineString
from shapely.ops import unary_union, polylabel, linemerge

# section -> (shown name, effect, effect). Sections not listed carry their own name and no lines.
SEC = {
 # SAID SHORTER (user 2026-10-16: "can you say less but still be as specific"): each line ~25 characters, the same facts
 ('CENTRAL LOWLAND', 'WESTERN LAKE'): ('WESTERN LAKE COUNTRY', 'OPEN TO ARCTIC AIR', 'STILL NIGHTS: LAKE FOG'),
 ('CENTRAL LOWLAND', 'EASTERN LAKE'): ('GREAT LAKES LOWLANDS', 'LAKES TEMPER SPRING, FALL', 'LAKE BREEZES FIRE STORMS'),
 ('CENTRAL LOWLAND', 'WISCONSIN DRIFTLESS'): ('DRIFTLESS AREA', 'COLD AIR POOLS IN VALLEYS', 'DAWN VALLEY FOG'),
 ('CENTRAL LOWLAND', 'DISSECTED TILL PLAINS'): ('DISSECTED TILL PLAINS', 'FRONTS CROSS UNSLOWED', 'CROPS RAISE DEW POINTS'),
 ('CENTRAL LOWLAND', 'TILL PLAINS'): ('TILL PLAINS', 'STORM LINES RUN FREE', 'CROPS RAISE DEW POINTS'),
 ('CENTRAL LOWLAND', 'OSAGE PLAINS'): ('OSAGE PLAINS', 'GULF MOISTURE FLOWS NORTH', 'SPRING SUPERCELLS'),
 ('GREAT PLAINS', 'MISSOURI PLATEAU, GLACIATED'): ('MISSOURI PLATEAU', 'ARCTIC AIR SLIDES SOUTH', 'OPEN-GROUND BLIZZARDS'),
 ('GREAT PLAINS', 'MISSOURI PLATEAU, UNGLACIATED'): ('MISSOURI PLATEAU', 'CHINOOKS MELT SNOW FAST', 'STORMS ROLL OFF THE ROCKIES'),
 ('GREAT PLAINS', 'BLACK HILLS'): ('BLACK HILLS', 'AFTERNOON STORMS FIRE HERE', 'WETTER, COOLER THAN PLAINS'),
 ('GREAT PLAINS', 'HIGH PLAINS'): ('HIGH PLAINS', 'SPRING DRYLINE', 'HAIL AND TORNADOES'),
 ('GREAT PLAINS', 'COLORADO PIEDMONT'): ('COLORADO PIEDMONT', 'EAST WINDS: UPSLOPE SNOW', 'DENVER CYCLONE TORNADOES'),
 ('GREAT PLAINS', 'PLAINS BORDER'): ('PLAINS BORDER', 'LOW-LEVEL JET AT NIGHT', 'NIGHT STORM CLUSTERS'),
 ('GREAT PLAINS', 'RATON'): ('RATON MESAS', 'EAST WINDS: UPSLOPE SNOW', 'SUMMER AFTERNOON STORMS'),
 ('GREAT PLAINS', 'PECOS VALLEY'): ('PECOS VALLEY', 'HOT, DRY LEE LOWLAND', ''),
 ('GREAT PLAINS', 'EDWARDS PLATEAU'): ('EDWARDS PLATEAU', 'THIN SOIL, FAST RUNOFF', 'FLASH FLOOD ALLEY EDGE'),
 ('GREAT PLAINS', 'CENTRAL TEXAS'): ('CENTRAL TEXAS HILLS', 'STALLED FRONTS: FLOOD RAIN', ''),
 ('APPALACHIAN PLATEAUS', 'MOHAWK'): ('MOHAWK VALLEY', 'WIND FUNNELS EAST–WEST', 'ONTARIO SNOW BANDS REACH IN'),
 ('APPALACHIAN PLATEAUS', 'SOUTHERN NEW YORK'): ('ALLEGHENY PLATEAU', 'UPSLOPE SNOW ON WEST WINDS', 'ERIE SNOW BANDS CROSS IT'),
 ('APPALACHIAN PLATEAUS', 'CATSKILL'): ('THE CATSKILLS', 'NOR’EASTER EAST WINDS', 'WRING OUT HEAVY SNOW'),
 ('APPALACHIAN PLATEAUS', 'KANAWHA'): ('KANAWHA PLATEAU', 'MORNING VALLEY FOG', 'SLOW STORMS FLASH-FLOOD'),
 ('APPALACHIAN PLATEAUS', 'ALLEGHENY MOUNTAIN'): ('ALLEGHENY MOUNTAINS', 'UPSLOPE SNOW ON WEST WINDS', 'SNOWIEST IN THE MID-ATLANTIC'),
 ('APPALACHIAN PLATEAUS', 'CUMBERLAND PLATEAU'): ('CUMBERLAND PLATEAU', 'COOLER, FOGGIER THAN VALLEYS', 'HEAVY RAIN ON ITS FACE'),
 ('APPALACHIAN PLATEAUS', 'CUMBERLAND MOUNTAIN'): ('CUMBERLAND MOUNTAINS', 'NORTHWEST-WIND SNOW', 'HOLLOWS FLASH-FLOOD'),
 ('VALLEY AND RIDGE', 'HUDSON VALLEY'): ('HUDSON VALLEY', 'WIND FUNNELS NORTH–SOUTH', 'TRAPS COLD: FREEZING RAIN'),
 ('VALLEY AND RIDGE', 'MIDDLE'): ('RIDGE AND VALLEY', 'VALLEYS STEER THE WIND', 'COLD POOLS: FOG, FROST'),
 ('VALLEY AND RIDGE', 'TENNESSEE'): ('GREAT VALLEY OF TENNESSEE', 'THE VALLEY STEERS WIND', 'LESS SNOW THAN THE RIDGES'),
 ('BLUE RIDGE', 'NORTHERN'): ('BLUE RIDGE', 'SUMMER STORMS ON CRESTS', 'COLD AIR WEDGES EAST'),
 ('BLUE RIDGE', 'SOUTHERN'): ('SOUTHERN BLUE RIDGE', 'SOUTH WINDS: HEAVY RAIN', 'NORTHWEST WINDS: PEAK SNOW'),
 ('PIEDMONT', 'PIEDMONT UPLAND'): ('PIEDMONT', 'COLD WEDGE: ICE, LOW CLOUD', 'LEE TROUGH FIRES STORMS'),
 ('PIEDMONT', 'PIEDMONT LOWLANDS'): ('PIEDMONT LOWLANDS', 'COLD WEDGE: ICE, LOW CLOUD', 'LEE TROUGH FIRES STORMS'),
 ('NEW ENGLAND', 'NEW ENGLAND UPLAND'): ('NEW ENGLAND UPLAND', 'COLDER THAN THE COAST', 'SNOW WHILE THE COAST RAINS'),
 ('NEW ENGLAND', 'WHITE MOUNTAIN'): ('WHITE MOUNTAINS', 'EXTREME SUMMIT WINDS', 'NORTHWEST-WIND SNOW'),
 ('NEW ENGLAND', 'GREEN MOUNTAIN'): ('GREEN MOUNTAINS', 'WEST-FACE UPSLOPE SNOW', 'COLD-AIR VALLEYS AT NIGHT'),
 ('NEW ENGLAND', 'TACONIC'): ('TACONIC HILLS', 'COLDER THAN THE HUDSON', 'SNOW WHILE THE VALLEY RAINS'),
 ('NEW ENGLAND', 'SEABOARD LOWLAND'): ('NEW ENGLAND COAST', 'OCEAN TEMPERS SPRING, FALL', 'RAIN–SNOW LINE SITS HERE'),
 ('ST. LAWRENCE VALLEY', 'CHAMPLAIN'): ('CHAMPLAIN VALLEY', 'WIND FUNNELS NORTH–SOUTH', 'ARCTIC AIR POURS IN'),
 ('ADIRONDACK', ''): ('ADIRONDACKS', 'ONTARIO BANDS ON WEST SLOPES', 'COLDEST NIGHTS IN THE EAST'),
 ('SUPERIOR UPLAND', ''): ('SUPERIOR UPLAND', 'SOUTH-SHORE SNOW BELTS', 'OPEN TO ARCTIC AIR'),
 ('INTERIOR LOW PLATEAUS', 'HIGHLAND RIM'): ('HIGHLAND RIM', 'SLOW STORMS: HEAVY RAIN', 'NIGHT, LATE-SEASON TORNADOES'),
 ('INTERIOR LOW PLATEAUS', 'LEXINGTON PLAIN'): ('BLUEGRASS', 'STORM LINES CROSS UNBROKEN', ''),
 ('INTERIOR LOW PLATEAUS', 'NASHVILLE BASIN'): ('NASHVILLE BASIN', 'COLD AIR POOLS', 'CALM-NIGHT FOG'),
 ('OZARK PLATEAUS', 'SPRINGFIELD-SALEM PLATEAUS'): ('OZARK PLATEAU', 'HEAVY RAIN ON SOUTH FACE', 'VALLEYS FLASH-FLOOD'),
 ('OZARK PLATEAUS', 'BOSTON "MOUNTAINS"'): ('BOSTON MOUNTAINS', 'SOUTH WINDS: HEAVY RAIN', 'HOLLOWS FLASH-FLOOD'),
 ('OUACHITA', 'ARKANSAS VALLEY'): ('ARKANSAS VALLEY', 'WIND FUNNELS EAST–WEST', ''),
 ('OUACHITA', 'OUACHITA MOUNTAINS'): ('OUACHITA MOUNTAINS', 'SOUTH WINDS: HEAVY RAIN', 'WETTEST IN ARKANSAS'),
 ('COASTAL PLAIN', 'EMBAYED'): ('COASTAL PLAIN', 'SEA BREEZE PUSHES INLAND', 'ITS FRONT FIRES STORMS'),
 ('COASTAL PLAIN', 'SEA ISLAND'): ('SEA ISLANDS', 'SEA-BREEZE STORMS INLAND', 'SURGE, KING TIDES FLOOD MARSH'),
 ('COASTAL PLAIN', 'EAST GULF COASTAL PLAIN'): ('EAST GULF COASTAL PLAIN', 'GULF DOWNPOURS ALL YEAR', 'DIXIE ALLEY TORNADOES'),
 ('COASTAL PLAIN', 'MISSISSIPPI ALLUVIAL PLAIN'): ('MISSISSIPPI DELTA', 'STICKY DEW POINTS', 'TORNADOES IN ANY SEASON'),
 ('COASTAL PLAIN', 'FLORIDIAN'): ('FLORIDA PENINSULA', 'SEA BREEZES COLLIDE DAILY', 'LIGHTNING CAPITAL'),
 ('COASTAL PLAIN', 'WEST GULF COASTAL PLAIN'): ('WEST GULF COASTAL PLAIN', 'GULF AIR ON SOUTH WINDS', 'HURRICANE RAINS STALL'),
 ('PACIFIC BORDER', 'PUGET TROUGH'): ('PUGET–WILLAMETTE LOWLAND', 'LIGHT, STEADY RAIN', 'GAP WINDS: ICE STORMS'),
 ('PACIFIC BORDER', 'OLYMPIC MOUNTAINS'): ('OLYMPIC MOUNTAINS', 'WETTEST IN THE LOWER 48', 'RAIN SHADOW NORTHEAST'),
 ('PACIFIC BORDER', 'OREGON COAST RANGE'): ('OREGON COAST RANGE', 'FIRST LIFT: HEAVY RAIN', 'HOLDS MARINE AIR'),
 ('PACIFIC BORDER', 'CALIFORNIA COAST RANGES'): ('CALIFORNIA COAST RANGES', 'HOLD THE MARINE LAYER', 'GAPS LET FOG INLAND'),
 ('PACIFIC BORDER', 'KLAMATH MOUNTAINS'): ('KLAMATH MOUNTAINS', 'HEAVY RAIN AND SNOW', ''),
 ('PACIFIC BORDER', 'CALIFORNIA TROUGH'): ('CENTRAL VALLEY', 'WINTER TULE FOG', 'DELTA BREEZE COOLS IT'),
 ('PACIFIC BORDER', 'LOS ANGELES RANGES'): ('TRANSVERSE RANGES', 'SOUTH WINDS: DEBRIS FLOWS', 'SANTA ANAS THROUGH PASSES'),
 ('LOWER CALIFORNIAN', ''): ('PENINSULAR RANGES', 'HOLD THE MARINE LAYER', 'SANTA ANAS THROUGH PASSES'),
 ('CASCADE-SIERRA MOUNTAINS', 'NORTHERN CASCADE MOUNTAINS'): ('NORTH CASCADES', 'DEEP SNOW', 'DRY EAST SIDE'),
 ('CASCADE-SIERRA MOUNTAINS', 'MIDDLE CASCADE MOUNTAINS'): ('CASCADES', 'DEEP SNOW', 'DRY EAST SIDE'),
 ('CASCADE-SIERRA MOUNTAINS', 'SOUTHERN CASCADE MOUNTAINS'): ('SOUTHERN CASCADES', 'DEEP SNOW', 'DRY EAST SIDE'),
 ('CASCADE-SIERRA MOUNTAINS', 'SIERRA NEVADA'): ('SIERRA NEVADA', 'DEEP SNOW', 'EAST: RAIN SHADOW, WAVE CLOUDS'),
 ('COLUMBIA PLATEAU', 'WALLA WALLA PLATEAU'): ('COLUMBIA BASIN', 'RAIN SHADOW: DRY', 'WINTER FOG TRAPPED'),
 ('COLUMBIA PLATEAU', 'BLUE MOUNTAIN'): ('BLUE MOUNTAINS', 'SNOW ON HIGH GROUND', ''),
 ('COLUMBIA PLATEAU', 'PAYETTE'): ('PAYETTE', 'WINTER INVERSIONS: FOG, HAZE', ''),
 ('COLUMBIA PLATEAU', 'SNAKE RIVER PLAIN'): ('SNAKE RIVER PLAIN', 'WIND FUNNELS ACROSS IT', 'RAIN SHADOW: DRY'),
 ('COLUMBIA PLATEAU', 'HARNEY'): ('HARNEY HIGH DESERT', 'FROST EVEN IN SUMMER', ''),
 ('NORTHERN ROCKY MOUNTAINS', ''): ('NORTHERN ROCKIES', 'HEAVY MOUNTAIN SNOW', 'ARCTIC AIR STOPS EAST'),
 ('MIDDLE ROCKY MOUNTAINS', ''): ('MIDDLE ROCKIES', 'DEEP MOUNTAIN SNOW', 'SUMMER PEAK STORMS'),
 ('SOUTHERN ROCKY MOUNTAINS', ''): ('SOUTHERN ROCKIES', 'SUMMER PEAK STORMS', 'UPSLOPE SNOW ON THE FRONT'),
 ('WYOMING BASIN', ''): ('WYOMING BASIN', 'FIERCE WEST WINDS', 'BLOWING SNOW'),
 ('COLORADO PLATEAUS', 'UINTA BASIN'): ('UINTA BASIN', 'WINTER INVERSIONS, HAZE', ''),
 ('COLORADO PLATEAUS', 'HIGH PLATEAUS OF UTAH'): ('HIGH PLATEAUS OF UTAH', 'SNOW ON HIGH GROUND', 'MONSOON STORMS'),
 ('COLORADO PLATEAUS', 'CANYON LANDS'): ('CANYON LANDS', 'RAIN SHADOW: DRY', 'SLOT-CANYON FLASH FLOODS'),
 ('COLORADO PLATEAUS', 'NAVAJO'): ('NAVAJO SECTION', 'BIG DAY–NIGHT SWINGS', 'JULY–AUGUST MONSOON'),
 ('COLORADO PLATEAUS', 'GRAND CANYON'): ('GRAND CANYON SECTION', 'RIM LIFTS MONSOON STORMS', 'RIM SNOW, GORGE HEAT'),
 ('COLORADO PLATEAUS', 'DATIL'): ('DATIL–MOGOLLON', 'MONSOON STORMS FIRE HERE', ''),
 ('BASIN AND RANGE', 'GREAT BASIN'): ('GREAT BASIN', 'SIERRA RAIN SHADOW', 'EACH RANGE MAKES STORMS'),
 ('BASIN AND RANGE', 'SONORAN DESERT'): ('SONORAN DESERT', 'MONSOON STORMS, HABOOBS', 'EXTREME HEAT'),
 ('BASIN AND RANGE', 'MEXICAN HIGHLAND'): ('MEXICAN HIGHLAND', 'SKY-ISLAND MONSOON STORMS', ''),
 ('BASIN AND RANGE', 'SACRAMENTO'): ('SACRAMENTO SECTION', 'MONSOON STORMS ON PEAKS', 'UPSLOPE CLOUD ON EAST WINDS'),
 ('BASIN AND RANGE', 'SALTON TROUGH'): ('SALTON TROUGH', 'BELOW SEA LEVEL: EXTREME HEAT', 'GULF SURGES: HUMIDITY'),
}
# edges: (name, high side sections, low side sections, quiet line, up lines, down lines). "up" = the wind pushes air from
# the low side onto the high side; "down" = it pours off the high side. lev: the pressure level read (hPa).
EDGE = [
 ('ALLEGHENY FRONT', [('APPALACHIAN PLATEAUS', 'ALLEGHENY MOUNTAIN'), ('APPALACHIAN PLATEAUS', 'SOUTHERN NEW YORK'), ('APPALACHIAN PLATEAUS', 'KANAWHA')],
  [('VALLEY AND RIDGE', 'MIDDLE')], 850, 'THE PLATEAU BREAKS OFF', ['AIR PUSHED UP IT', 'CLOUD PILES ON'], ['AIR POURS OFF', 'STORM LINES WEAKEN']),
 ('BLUE RIDGE FRONT', [('BLUE RIDGE', 'NORTHERN'), ('BLUE RIDGE', 'SOUTHERN')], [('PIEDMONT', 'PIEDMONT UPLAND'), ('PIEDMONT', 'PIEDMONT LOWLANDS')], 850,
  'COLD AIR WEDGES HERE', ['EAST WINDS WEDGE COLD AIR', 'DRIZZLE, ICE'], ['WEST WINDS SINK DOWN', 'WARM, DRY, GUSTY']),
 ('ROCKY MOUNTAIN FRONT', [('SOUTHERN ROCKY MOUNTAINS', ''), ('MIDDLE ROCKY MOUNTAINS', ''), ('NORTHERN ROCKY MOUNTAINS', '')],
  [('GREAT PLAINS', 'COLORADO PIEDMONT'), ('GREAT PLAINS', 'HIGH PLAINS'), ('GREAT PLAINS', 'RATON'), ('GREAT PLAINS', 'MISSOURI PLATEAU, UNGLACIATED'), ('GREAT PLAINS', 'MISSOURI PLATEAU, GLACIATED')], 700,
  'MOUNTAINS RISE OFF THE PLAINS', ['EAST WINDS PUSHED UP', 'UPSLOPE SNOW'], ['WEST WINDS POUR DOWN', 'CHINOOK GUSTS']),
 ('SIERRA WEST SLOPE', [('CASCADE-SIERRA MOUNTAINS', 'SIERRA NEVADA')], [('PACIFIC BORDER', 'CALIFORNIA TROUGH')], 700,
  'PACIFIC STORMS LIFT HERE', ['WEST WINDS PUSHED UP', 'RAIN, SNOW ABOVE'], ['EAST WINDS POUR DOWN', 'FIRE WEATHER']),
 ('SIERRA ESCARPMENT', [('CASCADE-SIERRA MOUNTAINS', 'SIERRA NEVADA')], [('BASIN AND RANGE', 'GREAT BASIN')], 700,
  'RAIN SHADOW STARTS', ['EAST WINDS PUSHED UP', 'EAST-FACE CLOUD'], ['WEST WINDS POUR DOWN', 'GUSTS, WAVE CLOUDS']),
 ('CASCADE WEST SLOPE', [('CASCADE-SIERRA MOUNTAINS', 'NORTHERN CASCADE MOUNTAINS'), ('CASCADE-SIERRA MOUNTAINS', 'MIDDLE CASCADE MOUNTAINS'), ('CASCADE-SIERRA MOUNTAINS', 'SOUTHERN CASCADE MOUNTAINS')],
  [('PACIFIC BORDER', 'PUGET TROUGH'), ('PACIFIC BORDER', 'KLAMATH MOUNTAINS'), ('PACIFIC BORDER', 'CALIFORNIA TROUGH')], 850,
  'PACIFIC STORMS LIFT HERE', ['WEST WINDS PUSHED UP', 'PASS SNOW'], ['EAST WINDS POUR DOWN', 'DRY GAP WINDS']),
 ('CASCADE EAST SLOPE', [('CASCADE-SIERRA MOUNTAINS', 'NORTHERN CASCADE MOUNTAINS'), ('CASCADE-SIERRA MOUNTAINS', 'MIDDLE CASCADE MOUNTAINS'), ('CASCADE-SIERRA MOUNTAINS', 'SOUTHERN CASCADE MOUNTAINS')],
  [('COLUMBIA PLATEAU', 'WALLA WALLA PLATEAU'), ('COLUMBIA PLATEAU', 'HARNEY'), ('BASIN AND RANGE', 'GREAT BASIN')], 850,
  'RAIN SHADOW STARTS', ['EAST WINDS PUSHED UP', 'EAST-FACE CLOUD'], ['WEST WINDS POUR DOWN', 'DRY, GUSTY']),
 ('MOGOLLON RIM', [('COLORADO PLATEAUS', 'DATIL'), ('COLORADO PLATEAUS', 'NAVAJO'), ('COLORADO PLATEAUS', 'GRAND CANYON')],
  [('BASIN AND RANGE', 'MEXICAN HIGHLAND'), ('BASIN AND RANGE', 'SONORAN DESERT')], 700,
  'MONSOON STORMS FIRE FIRST', ['MOIST SOUTH WINDS UP IT', 'STORMS FIRE'], ['NORTH WINDS POUR DOWN', 'DRY AIR SPILLS SOUTH']),
 ('BALCONES ESCARPMENT', [('GREAT PLAINS', 'EDWARDS PLATEAU')], [('COASTAL PLAIN', 'WEST GULF COASTAL PLAIN')], 850,
  'FLASH FLOOD ALLEY', ['GULF AIR PUSHED UP', 'RAIN CAN STALL'], ['WINDS POUR DOWN', 'DRY, WARM']),
 ('CAPROCK ESCARPMENT', [('GREAT PLAINS', 'HIGH PLAINS')], [('CENTRAL LOWLAND', 'OSAGE PLAINS')], 850,
  'DRYLINE OFTEN SITS HERE', ['MOIST EAST WINDS UP IT', 'STORMS CAN FIRE'], ['WEST WINDS POUR DOWN', 'DRYLINE PUSHES EAST']),
 ('WASATCH FRONT', [('MIDDLE ROCKY MOUNTAINS', ''), ('COLORADO PLATEAUS', 'HIGH PLATEAUS OF UTAH')], [('BASIN AND RANGE', 'GREAT BASIN')], 700,
  'DEEP POWDER', ['WEST WINDS PUSHED UP', 'HEAVY SNOW'], ['EAST WINDS POUR DOWN', 'CANYON GUSTS']),
]
SPOT = [
 ('LAKE SUPERIOR', -87.5, 47.6, ['SNOW BELTS: SOUTH, EAST SHORES']),
 ('LAKE MICHIGAN', -87.0, 43.8, ['LAKE-EFFECT SNOW: EAST SHORE']),
 ('LAKE HURON', -82.4, 44.8, ['LAKE-EFFECT SNOW: EAST SHORE']),
 ('LAKE ERIE', -81.2, 42.2, ['SNOW BELTS: SOUTHEAST SHORE']),
 ('LAKE ONTARIO', -77.8, 43.6, ['HEAVIEST BANDS: TUG HILL']),
 ('GREAT SALT LAKE', -112.5, 41.1, ['LAKE-EFFECT SNOW SOUTH, EAST']),
 ('COLUMBIA RIVER GORGE', -121.9, 45.65, ['SEA-LEVEL CASCADE GAP', 'GAP WINDS, ICE STORMS']),
 ('PUGET SOUND CONVERGENCE ZONE', -122.25, 47.95, ['OLYMPIC-SPLIT WINDS MEET', 'A SHOWER OR SNOW BAND']),
 ('PALMER DIVIDE', -104.65, 39.15, ['PLAINS RIDGE: MORE SNOW, HAIL']),
]
W0, S0, DX = -125.0, 24.0, 59.0 / 2360

def main(shp, dem, dst):
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
        nm, a, b = SEC.get(k, ((k[1] or k[0]).title().upper(), '', ''))
        # typical height: median of the grid inside the section
        m = Image.new('L', (Ww, Hh), 0); dr = ImageDraw.Draw(m)
        for p in (g.geoms if g.geom_type == 'MultiPolygon' else [g]):
            dr.polygon([((x - W0) / DX, (50 - y) / (26.0 / Hh)) for x, y in p.exterior.coords], fill=1)
        v = Z[np.array(m, bool)]; v = v[np.isfinite(v)]
        ft = int(round(float(np.median(v)) * 3.28084 / 100) * 100) if v.size else None
        # label anchors: the pole of the biggest piece, plus a 1-degree lattice of points well inside, so a label can sit in
        # whatever part of a big section is on screen
        big = max(g.geoms, key=lambda p: p.area) if g.geom_type == 'MultiPolygon' else g
        pts = [list(polylabel(big, 0.02).coords[0])]
        inner = g.buffer(-0.12)
        for lo in np.arange(math.floor(g.bounds[0]) + 0.25, g.bounds[2], 0.5):     # half a degree: a zoomed-in map still finds one
            for la in np.arange(math.floor(g.bounds[1]) + 0.25, g.bounds[3], 0.5):
                if inner.contains(Point(lo, la)): pts.append([float(lo), float(la)])
        simp = g.simplify(0.02, preserve_topology=True)
        rings = [[[round(x, 3), round(y, 3)] for x, y in p.exterior.coords] for p in (simp.geoms if simp.geom_type == 'MultiPolygon' else [simp]) if p.area > 0.01]
        secs.append({'n': nm, 'p': k[0], 'ft': ft, 'l': [x for x in (a, b) if x], 'a': [[round(x, 2), round(y, 2)] for x, y in pts], 'r': rings})
    edges = []
    for nm, hi, lo, lev, quiet, up, down in EDGE:
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
            c = list(p.coords)
            # which side is the high one: probe 0.15 deg either side along the normal at a dozen points
            score = 0
            for t in np.linspace(0.05, 0.95, 12):
                q = p.interpolate(t, normalized=True); q2 = p.interpolate(min(1, t + 0.02), normalized=True)
                dx, dy = q2.x - q.x, q2.y - q.y; L = math.hypot(dx, dy) or 1
                nx, ny = -dy / L, dx / L
                a1, a2 = zat(q.x + nx * 0.15, q.y + ny * 0.15), zat(q.x - nx * 0.15, q.y - ny * 0.15)
                if np.isfinite(a1) and np.isfinite(a2): score += 1 if a1 > a2 else -1
            rise = []
            for t in np.linspace(0.05, 0.95, 20):
                q = p.interpolate(t, normalized=True); q2 = p.interpolate(min(1, t + 0.02), normalized=True)
                dx, dy = q2.x - q.x, q2.y - q.y; L = math.hypot(dx, dy) or 1
                nx, ny = -dy / L * (1 if score >= 0 else -1), dx / L * (1 if score >= 0 else -1)
                a1, a2 = zat(q.x + nx * 0.1, q.y + ny * 0.1), zat(q.x - nx * 0.1, q.y - ny * 0.1)
                if np.isfinite(a1) and np.isfinite(a2): rise.append(a1 - a2)
            out.append({'c': [[round(x, 3), round(y, 3)] for x, y in c], 'up': 1 if score >= 0 else -1, 'rise': int(round(float(np.median(rise)) * 3.28084 / 100) * 100) if rise else None})
        out = [o for o in out if o['rise'] is not None and o['rise'] >= 150]   # a stretch with no real step (a valley seam) is not this edge
        edges.append({'n': nm, 'lev': lev, 'q': quiet, 'u': up, 'd': down, 'parts': out})
        print(nm, len(out), 'parts', [o['rise'] for o in out])
    J = {'src': 'USGS Physiographic Divisions of the Conterminous U.S. (Fenneman & Johnson 1946); heights USGS 3DEP', 'sec': secs, 'edge': edges,
         'spot': [{'n': n, 'c': [lo, la], 'l': l} for n, lo, la, l in SPOT]}
    json.dump(J, open(dst, 'w'), separators=(',', ':'))
    print(len(secs), 'sections', sum(len(s['a']) for s in secs), 'anchors')

if __name__ == '__main__':
    main(*sys.argv[1:4])
