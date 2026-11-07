"""LEAKING UNDERGROUND STORAGE TANKS -> under/lust_v1.pmtiles (layer "r").

Source: EPA UST Finder, Releases layer (FeatureServer/1, ~531k points)
  https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/UST_Finder_Feature_Layer_2/FeatureServer/1
Licence: US EPA, public domain (US Government work). Attribution: "US EPA UST Finder".
Baked: 2026-11-07.

Props: s = 0 No Further Action (closed) / 1 Open / 2 Unknown;
       y = year reported (int, absent if null); n = facility name (<=40 chars).
Usage: python3 -I lust_bake.py WORKDIR   (raw fetch cached in WORKDIR/lust_raw.json)
"""
import json, os, subprocess, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _arcgis import fetch_all

URL = "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/UST_Finder_Feature_Layer_2/FeatureServer/1"
work = sys.argv[1]
raw = os.path.join(work, "lust_raw.json")
if not os.path.exists(raw):
    feats = fetch_all(URL, "OBJECTID,Name,Status,Reported_Date,Latitude,Longitude", fmt="json",
                      geometry=False, workers=6)
    json.dump([f["attributes"] for f in feats], open(raw, "w"))
rows = json.load(open(raw))
S = {"No Further Action": 0, "Open": 1}
gj = os.path.join(work, "lust.geojsonl")
kept = 0
with open(gj, "w") as o:
    for a in rows:
        la, lo = a.get("Latitude"), a.get("Longitude")
        if la is None or lo is None or not (-90 <= la <= 90 and -180 <= lo <= 180) or (la == 0 and lo == 0):
            continue
        p = {"s": S.get(a.get("Status"), 2)}
        d = a.get("Reported_Date")
        if d is not None:
            y = (datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=d)).year
            if 1900 < y <= 2026:
                p["y"] = y
        n = (a.get("Name") or "").strip()
        if n:
            p["n"] = n[:40]
        o.write(json.dumps({"type": "Feature", "properties": p,
                            "geometry": {"type": "Point", "coordinates": [round(lo, 5), round(la, 5)]}}) + "\n")
        kept += 1
print("kept", kept, "of", len(rows))
out = os.path.join(work, "lust_v1.pmtiles")
subprocess.run(["tippecanoe", "-q", "-o", out, "--force", "-l", "r", "-Z2", "-z12", "-B10",
                "--drop-densest-as-needed", "-r1.6", "--maximum-tile-bytes=400000",
                "-P", gj], check=True)
