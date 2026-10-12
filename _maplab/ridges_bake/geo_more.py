"""THE RIDGES, the landscape told further (2026-10-11, user: "describe the geology's landscape further in the ridges view").
Adds to city_ridges_geo.json:
  belt[].rock / belt[].made : what each belt is made of, and how it got its shape (standard regional geology, no numbers invented:
                              ages are the textbook ones -- Grenville basement ~1.1 billion yrs, the Alleghanian collision ~300
                              million, the Triassic rift basins ~200 million, the last ice sheet's edge ~20,000 yrs)
  sec[]  : named SECTIONS of the same USGS physiographic map (Fenneman & Johnson 1946), each at a point inside its own polygon
  ice[]  : the Wisconsin and pre-Wisconsin glacial limits, USGS "Generalized Glacial Limit Lines" (King & Beikman 1974 geologic
           map, 1:2,500,000; Stanford purl vz874sc7648), clipped to the box -- GENERALISED, so the page draws them soft
python3 geo_more.py <city_ridges_geo.json> <dl/physio/physio> <glac_ridges.json>"""
import sys, json, shapefile
from shapely.geometry import shape, box, Point
from shapely.ops import unary_union
G = json.load(open(sys.argv[1]))
ROCK = {
    'ALLEGHENY PLATEAU': ('FLAT LAYERS OF SANDSTONE, SHALE, COAL', 'LIFTED WHOLE, THEN CUT BY RIVERS'),
    'RIDGE AND VALLEY':  ('THE SAME LAYERS, FOLDED LIKE A RUG', 'WHEN AFRICA HIT ~300 MILLION YRS AGO'),
    'BLUE RIDGE':        ('GRANITE AND GNEISS ~1.1 BILLION YRS', 'THE OLDEST ROCK ON THIS MAP'),
    'PIEDMONT':          ('ROOTS OF OLD MOUNTAINS: SCHIST, GNEISS', 'WORN DOWN TO ROLLING HILLS'),
    'HIGHLANDS':         ('GNEISS ~1.1 BILLION YRS', 'THE BLUE RIDGE’S ROCK, SURFACING AGAIN'),
    'COASTAL PLAIN':     ('LOOSE SAND, GRAVEL AND CLAY', 'WASHED OFF THE MOUNTAINS, TILTING SEAWARD'),
}
# two anchors move to open ground INSIDE their own belt (checked against the polygons): with three lines they found no room
# beside the NYC alerts and the NJ flood zones -- the Hudson Highlands at Bear Mountain, southern Maryland's coastal plain
MOVE = {'HIGHLANDS': [-74.1, 41.3], 'COASTAL PLAIN': [-76.95, 38.4]}
for b in G['belt']:
    if b['n'] in ROCK: b['rock'], b['made'] = ROCK[b['n']]
    if b['n'] in MOVE: b['c'] = MOVE[b['n']]
B = box(-81.2, 37.677, -73.35, 42.922)
r = shapefile.Reader(sys.argv[2]); S = {}
for rec, sh in zip(r.records(), r.shapes()):
    g = shape(sh.__geo_interface__).buffer(0).intersection(B)
    if not g.is_empty: S.setdefault((rec[7], rec[8]), []).append(g)
def parts(k):
    u = unary_union(S[k]); return sorted(list(u.geoms) if hasattr(u, 'geoms') else [u], key=lambda p: -p.area)
SEC = []
def add(k, i, lines, at=None):
    p = parts(k)[i]
    pt = Point(at) if at else p.representative_point()
    assert p.contains(pt), (k, at)
    SEC.append({'n': lines, 'c': [round(pt.x, 3), round(pt.y, 3)]})
add(('APPALACHIAN PLATEAUS', 'CATSKILL'), 0, ['THE CATSKILLS', 'A PLATEAU CARVED INTO PEAKS'])
add(('PIEDMONT', 'PIEDMONT LOWLANDS'), 0, ['RIFT BASIN', 'RED SANDSTONE, PANGAEA', 'PULLING APART ~200 MILLION YRS AGO'])
add(('PIEDMONT', 'PIEDMONT LOWLANDS'), 1, ['RIFT BASIN', 'RED SANDSTONE ~200 MILLION YRS'], at=(-74.95, 40.47))
add(('VALLEY AND RIDGE', 'HUDSON VALLEY'), 0, ['HUDSON VALLEY', 'A LOWLAND OF SOFT SHALE'])
G['sec'] = SEC
GL = json.load(open(sys.argv[3]))
def labat(L, lon):
    pts = list(zip(L[0::2], L[1::2])); q = min(pts, key=lambda p: abs(p[0] - lon)); return [q[0], q[1]]
G['ice'] = [{'k': 'w', 'r': L, 'lab': labat(L, -79.6), 'n': ['THE LAST ICE SHEET STOPPED HERE', '~20,000 YRS AGO']} for L in GL['w']] + \
           [{'k': 'p', 'r': L, 'lab': labat(L, -76.3), 'n': ['AN OLDER ICE AGE’S EDGE']} for L in GL['p']]
G['src'] += '; sections: same map; glacial limits: USGS Generalized Glacial Limit Lines (King & Beikman 1974, 1:2.5M)'
json.dump(G, open(sys.argv[1], 'w'), separators=(',', ':'))
print(len(SEC), 'sections', len(G['ice']), 'ice lines', [b.get('rock') for b in G['belt']])
