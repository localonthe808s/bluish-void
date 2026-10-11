import shapefile, json
from shapely.geometry import shape, box, LineString, MultiLineString
from shapely.ops import unary_union, linemerge
r = shapefile.Reader('dl/physio/physio')
B = box(-81.2, 37.677, -73.35, 42.922)
prov = {}
for rec, sh in zip(r.records(), r.shapes()):
    g = shape(sh.__geo_interface__).buffer(0)
    if not g.intersects(B): continue
    prov.setdefault(rec[7], []).append(g)
P = {k: unary_union(v) for k, v in prov.items()}
print({k: round(v.intersection(B).area, 2) for k, v in P.items()})
def edge(a, b, minlen=0.3):
    l = P[a].boundary.intersection(P[b].buffer(0.02)).intersection(B.buffer(-0.01))
    l = linemerge(l) if l.geom_type == 'MultiLineString' else l
    parts = list(l.geoms) if hasattr(l, 'geoms') else [l]
    parts = [p.simplify(0.008) for p in parts if p.geom_type == 'LineString' and p.length > minlen]
    return parts
for a, b in [('APPALACHIAN PLATEAUS', 'VALLEY AND RIDGE'), ('PIEDMONT', 'COASTAL PLAIN'), ('BLUE RIDGE', 'PIEDMONT'),
             ('NEW ENGLAND', 'PIEDMONT'), ('VALLEY AND RIDGE', 'BLUE RIDGE'), ('VALLEY AND RIDGE', 'PIEDMONT'), ('VALLEY AND RIDGE', 'NEW ENGLAND'),
             ('APPALACHIAN PLATEAUS', 'CENTRAL LOWLAND')]:
    E = edge(a, b)
    print(a, '|', b, [(round(p.length, 2), len(p.coords), [round(c, 2) for c in p.coords[0]], [round(c, 2) for c in p.coords[-1]]) for p in E])
import pickle; pickle.dump(P, open('prov.pkl', 'wb'))
