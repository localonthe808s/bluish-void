"""HEAT FLOW -> under/heatflow_v1.pmtiles (layer "h", points)

Source: IHFC Global Heat Flow Database, Release 2024, v.2026-03.
  Global Heat Flow Data Assessment Group et al. (2024), GFZ Data Services,
  https://doi.org/10.5880/fidgeo.2024.014
  https://datapub.gfz.de/download/10.5880.FIDGEO.2024.014-VEueRf/GHFBD-R2024_v.2026-03.zip
Licence: CC BY 4.0. Attribution: "IHFC Global Heat Flow Database (GFZ, CC BY 4.0)".
Baked: 2026-11-07.

Reads IHFC_2024_GHFDB_v.2026.03.txt (tab-separated; header row 13 = field names).
Props: q = heat flow mW/m2 (int, P1 'q'), n = site name (<=32 chars, omitted if '?'/blank),
       e = environment: 0 onshore (continental), 1 onshore lake/river, 2 offshore (continental),
           3 offshore (marine), 9 other/unknown.
Usage: python3 -I heatflow_bake.py TXT WORKDIR
"""
import json, os, subprocess, sys, collections
txt, work = sys.argv[1], sys.argv[2]
L = open(txt, encoding="utf-8", errors="replace").read().split("\n")
hi = next(i for i, l in enumerate(L) if l.startswith("q\t"))
H = L[hi].split("\t")
ix = {k: H.index(k) for k in ("q", "name", "lat_NS", "long_EW", "environment")}
ENV = {"[onshore (continental)]": 0, "[onshore (lake, river, etc.)]": 1,
       "[offshore (continental)]": 2, "[offshore (marine)]": 3}
envc = collections.Counter(); qs = []; seen = set(); out = []
for l in L[hi + 1:]:
    c = l.split("\t")
    if len(c) < 5:
        continue
    try:
        q = float(c[ix["q"]]); la = float(c[ix["lat_NS"]]); lo = float(c[ix["long_EW"]])
    except ValueError:
        continue
    if not (-90 <= la <= 90 and -180 <= lo <= 180):
        continue
    envc[c[ix["environment"]]] += 1
    p = {"q": int(round(q)), "e": ENV.get(c[ix["environment"]].lower(), 9)}
    n = c[ix["name"]].strip()
    if n and n not in ("?", "-"):
        p["n"] = n[:32]
    qs.append(q)
    out.append({"type": "Feature", "properties": p,
                "geometry": {"type": "Point", "coordinates": [round(lo, 4), round(la, 4)]}})
print(len(out), "points"); print(envc.most_common())
qs.sort()
pct = {p: round(qs[min(len(qs) - 1, int(len(qs) * p / 100))], 1) for p in (1, 5, 10, 25, 50, 75, 90, 95, 99)}
print("min", qs[0], "max", qs[-1], "pct", pct)
gj = os.path.join(work, "heatflow.geojsonl")
with open(gj, "w") as o:
    for f in out:
        o.write(json.dumps(f, separators=(",", ":")) + "\n")
subprocess.run(["tippecanoe", "-q", "-o", os.path.join(work, "heatflow_v1.pmtiles"), "--force", "-l", "h",
                "-Z0", "-z9", "-B5", "-r1.4", "--drop-densest-as-needed",
                "-P", gj], check=True)
