"""NATURAL HYDROGEN + HELIUM -> under/hydrogen_v1.json (+ hydrogen_v1.pmtiles if the polygons are big)

Source: USGS (Ellis & Gelman 2024), "Naturally Occurring Geologic Hydrogen Prospectivity
Maps" (10-22-2024), ArcGIS Online feature service:
  https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Naturally_Occurring_Geologic_Hydrogen_Prospectivity_Maps_10_22_2024_WFL1/FeatureServer
  layers 1 (Known Hydrogen Occurrences), 2 (Known Helium Concentrations), 6 (Total Prospectivity)
Licence: public domain (USGS). Attribution: "USGS geologic hydrogen prospectivity (Ellis & Gelman 2024)".
Baked: 2026-11-07.

Features carry k: "h2" = gas sample with measured H2 (props h = H2 mol %, e = He %, n = well/field, d = depth ft)
                  "he" = helium gas sample (props e = He mol %, n = field)
                  "p"  = total prospectivity zone (prop v = score bin 1..8: score 0.1-wide bins, v=1 is <0.2, v=8 is >=0.8)
Usage: python3 -I hydrogen_bake.py WORKDIR
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _arcgis import fetch_all
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from shapely import set_precision

B = "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Naturally_Occurring_Geologic_Hydrogen_Prospectivity_Maps_10_22_2024_WFL1/FeatureServer/"
work = sys.argv[1]


def cached(name, layer, fields):
    p = os.path.join(work, name)
    if not os.path.exists(p):
        json.dump(fetch_all(B + str(layer), fields, fmt="geojson", workers=4), open(p, "w"))
    return json.load(open(p))


def rnd(o, nd=4):
    if isinstance(o, dict):
        return {k: rnd(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        if o and isinstance(o[0], float):
            return [round(v, nd) for v in o]
        return [rnd(v, nd) for v in o]
    return o


def s(v):
    v = (v or "").strip() if isinstance(v, str) else v
    return v or None


pts = []
for f in cached("h2_raw.json", 1, "WELL_NAME,FIELD,STATE,H2,HE,DEPTH,Name"):
    a = f["properties"]; g = f.get("geometry")
    if not g or a.get("H2") is None:
        continue
    p = {"k": "h2", "h": round(a["H2"], 2)}
    if a.get("HE"):
        p["e"] = round(a["HE"], 3)
    n = s(a.get("WELL_NAME")) or s(a.get("Name")) or s(a.get("FIELD"))
    if n:
        p["n"] = n.title()[:40]
    if a.get("DEPTH"):
        p["d"] = int(a["DEPTH"])
    pts.append({"type": "Feature", "properties": p, "geometry": rnd(g)})
nh2 = len(pts)
for f in cached("he_raw.json", 2, "Field,Formation,He"):
    a = f["properties"]; g = f.get("geometry")
    if not g or a.get("He") is None:
        continue
    p = {"k": "he", "e": round(a["He"], 3)}
    if s(a.get("Field")):
        p["n"] = a["Field"].strip().title()[:32]
    pts.append({"type": "Feature", "properties": p, "geometry": rnd(g)})
print("h2", nh2, "he", len(pts) - nh2)

cells = cached("prosp_raw.json", 6, "gridcode")
bins = {}
for f in cells:
    gc = f["properties"]["gridcode"]
    v = min(8, max(1, gc // 10))
    bins.setdefault(v, []).append(shape(f["geometry"]).buffer(0))
polys = []
for v in sorted(bins):
    g = unary_union(bins[v]).buffer(0.0005).buffer(-0.0005).simplify(0.01, preserve_topology=True)
    g = set_precision(g.buffer(0), 1e-3)
    polys.append({"type": "Feature", "properties": {"k": "p", "v": v}, "geometry": rnd(mapping(g), 3)})
    print("bin", v, len(bins[v]), "cells")
out = os.path.join(work, "hydrogen_v1.json")
json.dump({"type": "FeatureCollection", "features": polys + pts}, open(out, "w"), separators=(",", ":"))
print(out, os.path.getsize(out))
