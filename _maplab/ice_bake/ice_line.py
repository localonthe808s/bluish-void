"""THE ICE AGE LINE for the CITY MAP's GEOLOGY tab (2026-10-12, user: "move the ice age line to the geology tab in CITY MAP, make
sure the line is as accurate and detailed as possible").
Source: NYS Museum Surficial Geologic Map of New York, Lower Hudson sheet (Cadwell and others, 1989; Map and Chart Series 40,
1:250,000), https://www.nysm.nysed.gov/sites/default/files/LowerHudson_Surficial_0.zip -- UTM 18N, field MATERIAL.
'tm' (till moraine) is the Harbor Hill moraine; the ice sheet's limit is its SOUTH edge, where the outwash plain ('og') begins.
  line[]: Bay Ridge -> Queens -> Nassau (tm/og contact); Staten Island: the tm/og contact, then the moraine's south side on to
          its southwest tip at Tottenville (where it meets the Arthur Kill; the line goes on into NJ, outside this sheet).
  hill[]: the moraine itself (tm polygons), for a faint fill.
Both clipped to lon -74.32..-73.55, lat 40.45..40.95, simplified 0.00004 deg (~4 m).
python3 ice_line.py <LowerHudson_Surficial (no ext)> <out.json>"""
import sys, json, shapefile
from shapely.geometry import shape, box, LineString, Point
from shapely.ops import transform, unary_union, linemerge
from pyproj import Transformer
T = Transformer.from_crs('EPSG:26918', 'EPSG:4326', always_xy=True)
B = box(-74.32, 40.45, -73.55, 40.95)
U = {}
for sr in shapefile.Reader(sys.argv[1]).iterShapeRecords():
    g = transform(T.transform, shape(sr.shape.__geo_interface__)).buffer(0)
    if g.intersects(B.buffer(0.2)): U.setdefault(sr.record['MATERIAL'], []).append(g)
U = {k: unary_union(v) for k, v in U.items()}
tm, og = U['tm'], U['og']
def merged(e):
    m = linemerge(e) if e.geom_type == 'MultiLineString' else e
    return [p for p in (m.geoms if hasattr(m, 'geoms') else [m]) if p.geom_type == 'LineString']
contact = sorted(merged(tm.boundary.intersection(og.buffer(0.0006))), key=lambda p: -p.length)
main = contact[0]                                         # Bay Ridge -> Nassau
si_c = [p for p in contact if p.bounds[0] < -74.04 and p.length > 0.05][0]   # Staten Island contact
if si_c.coords[0][0] < si_c.coords[-1][0]: si_c = LineString(list(si_c.coords)[::-1])   # east -> west
si = [g for g in tm.geoms if g.bounds[0] < -74.2][0]
north = unary_union([U[k] for k in ('t', 'km', 'k', 'r', 'ld', 'ls', 'pm', 'bi', 'b') if k in U])
rest = sorted(merged(si.exterior.difference(north.buffer(0.0006))), key=lambda p: -p.length)[0]
rc = list(rest.coords); end = si_c.coords[-1]
i0 = min(range(len(rc)), key=lambda i: Point(rc[i]).distance(Point(end)))
itip = min(range(len(rc)), key=lambda i: rc[i][1])          # Tottenville, the southwest tip
seg = rc[i0:itip + 1] if itip >= i0 else rc[itip:i0 + 1][::-1]
si_line = LineString(list(si_c.coords) + seg[1:])
out = {'src': 'NYS Museum Surficial Geologic Map of NY, Lower Hudson sheet (Cadwell et al. 1989, 1:250,000): south edge of the Harbor Hill moraine (tm) against outwash (og)',
       'line': [], 'hill': []}
for L in (main, si_line):
    c = L.intersection(B).simplify(0.00004)
    for p in (c.geoms if hasattr(c, 'geoms') else [c]):
        if p.geom_type == 'LineString' and len(p.coords) > 1: out['line'].append([round(v, 5) for xy in p.coords for v in xy])
h = tm.intersection(B).simplify(0.00004)
for p in (h.geoms if hasattr(h, 'geoms') else [h]):
    if p.geom_type == 'Polygon' and p.area > 1e-6: out['hill'].append([round(v, 5) for xy in p.exterior.coords for v in xy])
json.dump(out, open(sys.argv[2], 'w'), separators=(',', ':'))
print('lines', [len(l) // 2 for l in out['line']], 'hills', [len(h) // 2 for h in out['hill']])
