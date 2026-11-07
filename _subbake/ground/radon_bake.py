"""RADON POTENTIAL -> under/radon_v1.json

Source: USGS, Geologic Radon Potential Map of the United States (national merge of
USGS Open-File Report 93-292 state maps; service layer "USGS_radon_20250723_NAD83_Merge", 2025):
  https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Geologic_Radon_Potential_Map_of_the_United_States/FeatureServer/0
Licence: public domain (USGS). Attribution: "USGS Geologic Radon Potential (OFR 93-292, 2025 merge)".
Baked: 2026-11-07.

Props: p = potential "h" high (GRP 1, avg indoor screening > 4 pCi/L), "m" moderate (GRP 2, 2-4 pCi/L),
           "l" low (GRP 3, < 2 pCi/L);
       i = Radon Index (RI) 3..18 composite score (geology, soil permeability, aerial gamma,
           architecture, indoor data); >=12 high, 9-11 moderate, <=8 low;
       n = geologic province name (AREANAME), s = state.
Usage: python3 -I radon_bake.py WORKDIR [tol_deg]
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _arcgis import fetch_all
from shapely.geometry import shape, mapping
from shapely import set_precision

URL = "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Geologic_Radon_Potential_Map_of_the_United_States/FeatureServer/0"
work = sys.argv[1]
tol = float(sys.argv[2]) if len(sys.argv) > 2 else 0.005
raw = os.path.join(work, "radon_raw.json")
if not os.path.exists(raw):
    json.dump(fetch_all(URL, "AREANAME,GRP,RI,STATE", fmt="geojson", page=200), open(raw, "w"))


def rnd(o):
    if isinstance(o, dict):
        return {k: rnd(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        if o and isinstance(o[0], float):
            return [round(v, 4) for v in o]
        return [rnd(v) for v in o]
    return o


P = {1: "h", 2: "m", 3: "l"}
feats = []
for f in json.load(open(raw)):
    a = f["properties"]
    if not f.get("geometry") or a.get("GRP") not in P:
        continue
    g = shape(f["geometry"]).buffer(0).simplify(tol, preserve_topology=True)
    try:
        g = set_precision(g.buffer(0), 1e-4)
    except Exception:
        g = g.buffer(0)
    if g.is_empty:
        continue
    p = {"p": P[a["GRP"]], "i": a.get("RI")}
    if (a.get("AREANAME") or "").strip():
        p["n"] = a["AREANAME"].strip()
    if a.get("STATE"):
        p["s"] = a["STATE"]
    feats.append({"type": "Feature", "properties": p, "geometry": rnd(mapping(g))})
out = os.path.join(work, "radon_v1.json")
json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w"), separators=(",", ":"))
print(len(feats), "polygons", os.path.getsize(out))
