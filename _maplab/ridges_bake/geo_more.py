"""THE RIDGES, what the ground does to the weather (2026-10-11). First pass added rock and ice-age geology; the user corrected it:
"we dont need actual geology info i just meant how these geological features would affect weather and areas of interest for
storm development". So each belt now carries two weather lines (belt[].rock / belt[].made, kept as field names), and sec[] names
the Catskills and the Hudson Valley -- sections of the same USGS physiographic map (Fenneman & Johnson 1946) -- with theirs.
Only the well-known terrain effects: upslope and lake snow on the plateau, valley channelling and cold pools, storms firing on
the Blue Ridge, cold-air damming and the lee trough over the Piedmont, colder highlands, the sea-breeze front on the plain.
python3 geo_more.py <city_ridges_geo.json> <dl/physio/physio>   (run on geo_build.py's output)"""
import sys, json, shapefile
from shapely.geometry import shape, box, Point
from shapely.ops import unary_union
G = json.load(open(sys.argv[1]))
ROCK = {   # (user 2026-10-11: "we dont need actual geology info ... how these features would affect weather and areas of
           #  interest for storm development") -- what each belt does to the air, the well-known patterns only
    'ALLEGHENY PLATEAU': ('WEST WINDS LIFTED ONTO IT: UPSLOPE SNOW', 'LAKE ERIE\u2019S SNOW BANDS RUN ACROSS IT'),
    'RIDGE AND VALLEY':  ('VALLEYS STEER WIND SOUTHWEST\u2013NORTHEAST', 'COLD AIR POOLS IN THEM: NIGHT FOG, FROST'),
    'BLUE RIDGE':        ('SUMMER STORMS OFTEN FIRE ON ITS CRESTS', 'COLD AIR GETS WEDGED ON ITS EAST SIDE'),
    'PIEDMONT':          ('WHERE THAT WEDGE SITS: ICE, STUCK CLOUD', 'LEE TROUGH: STORMS OFTEN RE-FIRE HERE'),
    'HIGHLANDS':         ('A FEW DEGREES COLDER THAN THE CITY', 'OFTEN SNOW HERE WHILE THE CITY RAINS'),
    'COASTAL PLAIN':     ('THE SEA BREEZE PUSHES INLAND ACROSS IT', 'ITS FRONT CAN SET OFF AFTERNOON STORMS'),
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
add(('APPALACHIAN PLATEAUS', 'CATSKILL'), 0, ['THE CATSKILLS', 'EAST WINDS IN A NOR\u2019EASTER', 'WRING OUT HEAVY SNOW AND RAIN'])
add(('VALLEY AND RIDGE', 'HUDSON VALLEY'), 0, ['HUDSON VALLEY', 'FUNNELS WIND NORTH\u2013SOUTH', 'HOLDS COLD AIR: FREEZING RAIN'], at=(-73.75, 42.6))   # the upper valley near Albany: open ground for a label, inside the section
G['sec'] = SEC
G.pop('ice', None)
G['src'] += '; sections: same map'
json.dump(G, open(sys.argv[1], 'w'), separators=(',', ':'))
print(len(SEC), 'sections', [b.get('rock') for b in G['belt']])
