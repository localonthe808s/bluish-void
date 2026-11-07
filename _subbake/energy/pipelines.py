"""PIPELINES -> under/pipelines_v1.pmtiles (layer "p").

Source: U.S. Energy Information Administration (EIA) energy infrastructure layers,
ArcGIS feature services in org FiaPA4ga0iQKduv3 (services2.arcgis.com):
  Natural_Gas_Interstate_and_Intrastate_Pipelines_1 (32,892 lines)
  Crude_Oil_Trunk_Pipelines_1, Petroleum_Products_Pipelines_1, Hydrocarbon_Gas_Liquids_Pipelines_1
Licence: US government work, public domain. Credit "EIA". Baked 2026-11-07.

props: t = gas|crude|product|hgl ; o = operator ; c = Interstate|Intrastate (gas only);
       nm = pipe name (oil/product/hgl only)
Usage: python3 -I pipelines.py WORK_DIR
"""
import sys, site, os, json, subprocess
sys.path.append(site.getusersitepackages())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _arcgis import fetch_layer, rnd

B = "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
SRC = [("gas", "Natural_Gas_Interstate_and_Intrastate_Pipelines_1"),
       ("crude", "Crude_Oil_Trunk_Pipelines_1"),
       ("product", "Petroleum_Products_Pipelines_1"),
       ("hgl", "Hydrocarbon_Gas_Liquids_Pipelines_1")]
work = sys.argv[1]; os.makedirs(work, exist_ok=True)
out = os.path.join(work, "pipelines.geojsons")
with open(out, "w") as f:
    for t, svc in SRC:
        fs = fetch_layer(B + svc + "/FeatureServer/0", page=2000)
        print(t, len(fs))
        for ft in fs:
            g, p = ft.get("geometry"), ft.get("properties") or {}
            if not g: continue
            q = {"t": t}
            o = (p.get("Operator") or p.get("Opername") or "").strip()
            if o: q["o"] = o[:60]
            if t == "gas" and p.get("TYPEPIPE"): q["c"] = p["TYPEPIPE"].strip()
            nm = (p.get("Pipename") or "").strip()
            if nm: q["nm"] = nm[:60]
            g["coordinates"] = rnd(g["coordinates"], 5)
            f.write(json.dumps({"type": "Feature", "properties": q, "geometry": g}, separators=(",", ":")) + "\n")
pm = os.path.join(work, "pipelines_v1.pmtiles")
subprocess.run(["tippecanoe", "-f", "-o", pm, "-l", "p", "-Z2", "-z12",
                "--drop-densest-as-needed", "--extend-zooms-if-still-dropping",
                "--simplification=4", "-P", "--attribution=EIA", out], check=True)
print("wrote", pm)
