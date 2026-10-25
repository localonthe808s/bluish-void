"""THE ICE LINE, CONTINUED (2026-10-25, user: "continue the glacial line"). Same rule as ice_line.py (2026-10-12): the ice
sheet's limit is the SOUTH edge of its terminal moraine, from the surveys' own maps, kept at their detail (~4 m simplify).
  NY (Lower Hudson sheet, Cadwell et al. 1989, 1:250,000): every 'tm' edge whose south side is outwash and has no moraine
     beyond it to the sea -- the Harbor Hill moraine through Brooklyn and Queens, then the Ronkonkoma moraine (the outer one
     east of Lake Success) to Montauk; Staten Island as before.
  NJ (NJGWS surficial geology, 1:100,000; NJDEP Features/Geology/MapServer/25): the Late Wisconsinan terminal moraine
     (Qwmtr Rahway till, Qwmtn Netcong till), its south-facing edge with no moraine beyond it -- Perth Amboy to the
     Delaware at Belvidere.
python3 ice_line_v2.py <LowerHudson_Surficial (no ext)> <old city_ice_line.json> <out.json>"""
import sys, json, subprocess, urllib.parse
import shapefile
from shapely.geometry import shape, box, LineString, Point, MultiLineString
from shapely.ops import transform, unary_union, linemerge
from pyproj import Transformer
T = Transformer.from_crs('EPSG:26918', 'EPSG:4326', always_xy=True)
SIMP = 0.00004
def lines_of(g):
    m = linemerge(g) if g.geom_type == 'MultiLineString' else g
    return [p for p in (m.geoms if hasattr(m, 'geoms') else [m]) if p.geom_type == 'LineString' and p.length > 0]
# ---- NY: Long Island east of the old line's end
U = {}
for sr in shapefile.Reader(sys.argv[1]).iterShapeRecords():
    g = transform(T.transform, shape(sr.shape.__geo_interface__)).buffer(0)
    if g.bounds[2] > -73.7: U.setdefault(sr.record['MATERIAL'], []).append(g)
tm = unary_union(U['tm']); og = unary_union(U['og'])
contact = tm.boundary.intersection(og.buffer(0.0006))
keep = []
for seg in lines_of(contact):
    for a, b in zip(list(seg.coords)[:-1], list(seg.coords)[1:]):
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ray = LineString([(mx, my - 0.0008), (mx, 40.3)])
        keep.append((LineString([a, b]), not ray.intersects(tm)))
outer = linemerge([s for s, k in keep if k])
LI0 = [l for l in lines_of(outer) if l.length > 0.004 and l.bounds[2] > -73.6]
# ---- NJ: terminal moraine minus its contact with the glacial deposits north of it
def nj(where):
    feats, off = [], 0
    while True:
        q = urllib.parse.urlencode({'where': where, 'outFields': 'GEOABB', 'outSR': 4326, 'f': 'geojson', 'resultOffset': off, 'resultRecordCount': 1000})
        j = json.loads(subprocess.run(['curl', '-s', '-m', '120', 'https://mapsdep.nj.gov/arcgis/rest/services/Features/Geology/MapServer/25/query?' + q], capture_output=True, check=True).stdout)
        f = j.get('features', []); feats += f; off += len(f)
        if len(f) < 1000: return [shape(x['geometry']).buffer(0) for x in feats if x.get('geometry')]
mor = unary_union(nj("GEOABB IN ('Qwmtr','Qwmtn')"))
def outer_edge(poly, south_to):
    keep = []
    for seg in lines_of(poly.boundary):
        for a2, b2 in zip(list(seg.coords)[:-1], list(seg.coords)[1:]):
            mx, my = (a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2
            # the outside is away from the ice, which came from the north-northeast: probe and cast to the southwest
            keep.append((LineString([a2, b2]), not poly.contains(Point(mx - 0.00035, my - 0.00035)) and not LineString([(mx - 0.0006, my - 0.0006), (mx - 0.5, my - 0.5)]).intersects(poly)))
    return [l for l in lines_of(linemerge([s2 for s2, k in keep if k])) if l.length > 0.004]
def bridge(ls, gap=0.012):
    # rivers and lakes cut the moraine: join pieces whose ends are within ~1 km, nearest first
    ls = [list(l.coords) for l in ls]; joined = True
    while joined:
        joined = False
        for i in range(len(ls)):
            for j in range(len(ls)):
                if i == j: continue
                a3, b3 = ls[i], ls[j]
                for A, B in ((a3, b3), (a3, b3[::-1]), (a3[::-1], b3), (a3[::-1], b3[::-1])):
                    if Point(A[-1]).distance(Point(B[0])) < gap:
                        ls[i] = A + B; del ls[j]; joined = True; break
                if joined: break
            if joined: break
    return [LineString(c) for c in ls if len(c) > 1]
NJ = bridge(outer_edge(mor, 40.0)); LI = bridge(LI0)
# ---- join with the old (NYC) lines
old = json.load(open(sys.argv[2]))
out = {'src': old['src'] + '; Long Island: same sheet, the outermost moraine edge (Harbor Hill, then Ronkonkoma to Montauk); New Jersey: NJGWS surficial geology 1:100,000, the Late Wisconsinan terminal moraine (Rahway and Netcong tills), south edge',
       'line': list(old['line']), 'hill': list(old.get('hill', []))}
for L in LI + NJ:
    c = L.simplify(SIMP)
    if len(c.coords) > 1: out['line'].append([round(v, 5) for xy in c.coords for v in xy])
json.dump(out, open(sys.argv[3], 'w'), separators=(',', ':'))
print('LI', len(LI), [round(l.length, 3) for l in LI][:8], 'NJ', len(NJ), [round(l.length, 3) for l in NJ][:8])
