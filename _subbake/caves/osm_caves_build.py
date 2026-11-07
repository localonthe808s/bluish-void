"""OSM cave entrances (tiles from osm_caves_fetch.py) -> GeoJSONSeq for tippecanoe.

Data (c) OpenStreetMap contributors, ODbL 1.0 - credit "(c) OpenStreetMap contributors".
Baked 2026-11-07.  Run: python3 -I osm_caves_build.py TILE_DIR OUT.geojsonl
Properties (all optional except none):
  n     name (name:en preferred, else name)
  show  1 when show_cave=yes|guided|... or tourism=attraction|museum or fee=yes with opening_hours
  len   cave length in metres (from length / cave:length tags, parsed number; "km" handled)
  dep   cave depth in metres (from depth / cave:depth / ele:depth? -> depth only)
Then: tippecanoe -o cave_entrances_v1.pmtiles -l e -Z2 -z12 -r1 --drop-densest-as-needed ...
"""
import sys, os, json, re, glob
SRC, OUT = sys.argv[1], sys.argv[2]
def num(v):
    if not v: return None
    v = v.strip().lower().replace(",", ".")
    m = re.match(r"^~?\s*(-?\d+(?:\.\d+)?)\s*(km|m|ft|')?", v)
    if not m: return None
    x = abs(float(m.group(1)))
    u = m.group(2)
    if u == "km": x *= 1000
    elif u in ("ft", "'"): x *= 0.3048
    return round(x) if x >= 1 else None
seen = set(); n = 0; us = 0
US = [(24.4, -125.0, 49.5, -66.9), (51, -180, 72, -129), (18.8, -160.5, 22.4, -154.7), (17.8, -67.4, 18.6, -64.5)]
with open(OUT, "w") as out:
    for fn in sorted(glob.glob(os.path.join(SRC, "t_*.json"))):
        for e in json.load(open(fn, "rb"))["elements"]:
            k = (e["type"], e["id"])
            if k in seen: continue
            seen.add(k)
            lat = e.get("lat", e.get("center", {}).get("lat")); lon = e.get("lon", e.get("center", {}).get("lon"))
            if lat is None: continue
            t = e.get("tags", {}); p = {}
            nm = t.get("name:en") or t.get("name")
            if nm: p["n"] = nm[:80]
            sc = t.get("show_cave", "").lower()
            if (sc and sc != "no") or t.get("tourism") in ("attraction", "museum"): p["show"] = 1
            L = num(t.get("length") or t.get("cave:length"))
            D = num(t.get("depth") or t.get("cave:depth"))
            if L: p["len"] = L
            if D: p["dep"] = D
            out.write(json.dumps({"type": "Feature", "properties": p,
                "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}},
                ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
            if any(a <= lat <= c and b <= lon <= d for a, b, c, d in US): us += 1
print("features", n, "US-box", us)
