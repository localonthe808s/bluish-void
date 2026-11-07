"""PRINCIPAL AQUIFERS -> under/aquifers_v1.json

Source: USGS, "Principal Aquifers of the 48 Conterminous United States, Hawaii,
Puerto Rico, and the U.S. Virgin Islands" (2003, file dated 2015), ScienceBase
item 63140610d34e36012efa385d, file aquifers_us.zip (us_aquifers.shp, NAD83 geographic).
  https://www.sciencebase.gov/catalog/item/63140610d34e36012efa385d
Licence: public domain (USGS). Attribution: "USGS Principal Aquifers".
Baked: 2026-11-07.

Dissolves polygons per aquifer (AQ_CODE), drops the 999 "Other rocks" filler,
simplifies (topology-preserving), rounds to 4 decimals.
Props: n = aquifer name, r = rock-type code (1..6, see ROCK), c = USGS AQ_CODE.
Usage: python3 -I aquifers_bake.py us_aquifers.shp OUT.json [tol_deg]
"""
import json, sys
sys.path.append("/Users/vvvaa/Library/Python/3.9/lib/python/site-packages")
import shapefile
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from shapely import set_precision

ROCK = {100: 1, 200: 2, 300: 3, 400: 4, 500: 5, 600: 6}
shp, out = sys.argv[1], sys.argv[2]
tol = float(sys.argv[3]) if len(sys.argv) > 3 else 0.005
r = shapefile.Reader(shp)
groups = {}
for sr in r.iterShapeRecords():
    a = sr.record.as_dict()
    if a["AQ_CODE"] == 999:
        continue
    g = shape(sr.shape.__geo_interface__)
    if not g.is_valid:
        g = g.buffer(0)
    groups.setdefault(a["AQ_CODE"], [a, []])[1].append(g)
def rnd(o):
    if isinstance(o, dict):
        return {k: rnd(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        if o and isinstance(o[0], float):
            return [round(v, 4) for v in o]
        return [rnd(v) for v in o]
    return o


feats = []
for code, (a, gs) in sorted(groups.items()):
    g = unary_union(gs).simplify(tol, preserve_topology=True)
    try:
        g = set_precision(g.buffer(0), 1e-4)
    except Exception:
        g = g.buffer(0)
    if g.is_empty:
        continue
    feats.append({"type": "Feature", "properties": {"n": a["AQ_NAME"], "r": ROCK[a["ROCK_TYPE"]], "c": code},
                  "geometry": rnd(mapping(g))})
json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w"), separators=(",", ":"))
print(len(feats), "aquifers")
