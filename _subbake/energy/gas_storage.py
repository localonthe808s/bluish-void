"""UNDERGROUND NATURAL GAS STORAGE -> under/gas_storage_v1.json (points).

Source: EIA underground natural gas storage fields (Form EIA-191, period 2018-12),
public copy of the EIA layer at
services1.arcgis.com/ajkPMiuiqxF9xEgP/arcgis/rest/services/Natural_Gas_Underground_Storage_US_EIA
(the official EIA service now needs a token). US government work, public domain. Credit "EIA".
Baked 2026-11-07.

props: n = field name (reservoir appended when a field has several), type = depleted|aquifer|salt,
       op = operator, st = state, s = 1 active / 0 inactive,
       cap = working gas capacity (Mcf), base = base gas (Mcf), del = max deliverability (Mcf/day)
Usage: python3 -I gas_storage.py OUT_JSON
"""
import sys, site, os, json, collections
sys.path.append(site.getusersitepackages())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _arcgis import fetch_layer, rnd

TY = {"Depleted Field": "depleted", "Aquifer": "aquifer", "Salt Dome": "salt"}
fs = fetch_layer("https://services1.arcgis.com/ajkPMiuiqxF9xEgP/arcgis/rest/services/Natural_Gas_Underground_Storage_US_EIA/FeatureServer/0")
cnt = collections.Counter((f["properties"].get("Field") or "").strip() for f in fs)
out = []
for f in fs:
    a = f["properties"]
    lon, lat = a.get("Longitude"), a.get("Latitude")
    if lon is None or lat is None:
        if not f.get("geometry"): continue
        lon, lat = f["geometry"]["coordinates"]
    fld = " ".join((a.get("Field") or "").split()).title()
    res = " ".join((a.get("Reservoir") or "").split()).title()
    n = fld + (" · " + res if res and cnt[(a.get("Field") or "").strip()] > 1 else "")
    p = {"n": n, "type": TY.get(a.get("Field_Type"), (a.get("Field_Type") or "").lower()),
         "op": " ".join((a.get("Company") or "").split()).title()[:60], "st": a.get("State"),
         "s": 1 if a.get("Status") == "Active" else 0}
    for k, src in (("cap", "work_cap"), ("base", "base_gas"), ("del", "maxdeliv")):
        if a.get(src) is not None: p[k] = a[src]
    out.append({"type": "Feature", "properties": p,
                "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}})
json.dump({"type": "FeatureCollection", "features": out}, open(sys.argv[1], "w"), separators=(",", ":"))
print("storage", len(out), collections.Counter(f["properties"]["type"] for f in out), os.path.getsize(sys.argv[1]))
