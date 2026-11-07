"""URANIUM -> under/uranium_v1.json (polygons).

Source: EIA "Identified uranium resource areas" (EIA uranium resource area map),
public copy at services3.arcgis.com/17F7m6SrhCakwCcI/arcgis/rest/services/US_EIA_Uranium_Identified_Resource_Areas
US government work, public domain. Credit "EIA". Baked 2026-11-07.
props: n = area name. (Source STATUS field is 1 for every feature, dropped.)
Usage: python3 -I uranium.py OUT_JSON
"""
import sys, site, os, json
sys.path.append(site.getusersitepackages())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shapely.geometry import shape, mapping
from shapely import make_valid
from _arcgis import fetch_layer, rnd

fs = fetch_layer("https://services3.arcgis.com/17F7m6SrhCakwCcI/arcgis/rest/services/US_EIA_Uranium_Identified_Resource_Areas/FeatureServer/0")
out = []
for f in fs:
    if not f.get("geometry"): continue
    g = make_valid(shape(f["geometry"])).simplify(0.001, preserve_topology=True)
    if g.is_empty: continue
    if g.geom_type == "GeometryCollection":
        from shapely.ops import unary_union
        g = unary_union([x for x in g.geoms if x.geom_type in ("Polygon", "MultiPolygon")])
    m = mapping(g)
    out.append({"type": "Feature", "properties": {"n": " ".join((f["properties"].get("Name") or "").split())},
                "geometry": {"type": m["type"], "coordinates": rnd(json.loads(json.dumps(m["coordinates"])), 4)}})
json.dump({"type": "FeatureCollection", "features": out}, open(sys.argv[1], "w"), separators=(",", ":"))
print("uranium", len(out), os.path.getsize(sys.argv[1]))
