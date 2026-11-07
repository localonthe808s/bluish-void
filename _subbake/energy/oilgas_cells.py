"""OIL & GAS FIELDS -> under/oilgas_cells_v1.pmtiles (layer "c", prop k).

Source: USGS, "Oil and Gas Exploration and Production in the United States Shown
as Quarter-Mile Cells" (uscells05g), ScienceBase item 664b5facd34e1955f5a4721b
https://www.sciencebase.gov/catalog/item/664b5facd34e1955f5a4721b
966,750 quarter-square-mile (~805 m side) cells, NAD83 lon/lat, wells 1859-2005.
Licence: USGS public domain. Credit: "IHS Energy and USGS". Baked 2026-11-07.

k = CELLSYMB: 1 oil, 2 gas, 3 oil and gas, 4 dry or unknown.
Usage (run with python3 -I; downloaded data are untrusted):
  python3 -I oilgas_cells.py DL_DIR WORK_DIR   # DL_DIR holds uscells05g.shp/.dbf/.shx
Downloads the shapefile parts from the item JSON if missing, then builds three tilesets
and joins them:
  z3-5  aggregate: cells binned to a 0.06 deg lat x 0.075 deg lon grid (~6.7 km), dissolved per class
  z6-8  aggregate: 0.02 x 0.025 deg grid (~2.2 km), dissolved per class
  z9-12 the real cells (rotated ~805 m squares as published)
Aggregate features carry a=1. Bin class: if productive cells (k 1-3) are < 1/3 of the bin -> 4;
else 3 when both oil (1|3) and gas (2|3) are >= 25 % of the productive cells, else 1 or 2.
"""
import sys, site, os, json, subprocess, urllib.request
sys.path.append(site.getusersitepackages())
import collections
import shapefile, shapely
from shapely.geometry import box, mapping

UA = {"User-Agent": "bluishvoid.com bake"}
dl, work = sys.argv[1], sys.argv[2]
os.makedirs(dl, exist_ok=True); os.makedirs(work, exist_ok=True)

def get(url, path):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA)) as r, open(path, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)

if not os.path.exists(os.path.join(dl, "uscells05g.shp")):
    item = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://www.sciencebase.gov/catalog/item/664b5facd34e1955f5a4721b?format=json", headers=UA)))
    for x in item["facets"][0]["files"]:
        if x["name"].rsplit(".", 1)[-1] in ("shp", "dbf", "shx", "prj"):
            get(x["url"], os.path.join(dl, x["name"]))

r = shapefile.Reader(os.path.join(dl, "uscells05g"))
out = os.path.join(work, "oilgas.geojsons")
n = 0
with open(out, "w") as f:
    for sr in r.iterShapeRecords():
        k = int(sr.record["CELLSYMB"])
        ring = [[round(x, 5), round(y, 5)] for x, y in sr.shape.points]
        f.write(json.dumps({"type": "Feature", "properties": {"k": k},
                            "geometry": {"type": "Polygon", "coordinates": [ring]}},
                           separators=(",", ":")) + "\n")
        n += 1
print("cells", n)

def agg(B, path):
    bins = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    for x, y, k in r.iterRecords(fields=["CC83XCOORD", "CC83YCOORD", "CELLSYMB"]):
        bins[(int((x + 180) // (B * 1.25)), int((y + 90) // B))][int(k)] += 1
    byk = collections.defaultdict(list)
    for (i, j), c in bins.items():
        tot, prod = sum(c), c[1] + c[2] + c[3]
        if prod * 3 < tot: k = 4
        else:
            o, g = c[1] + c[3], c[2] + c[3]
            k = 3 if (o >= .25 * prod and g >= .25 * prod) else (1 if o > g else 2)
        byk[k].append(box(i, j, i + 1, j + 1))
    with open(path, "w") as f:
        for k, L in sorted(byk.items()):
            u = shapely.transform(shapely.unary_union(L, grid_size=1), lambda a: a * [B * 1.25, B] - [180, 90])
            for g in (u.geoms if hasattr(u, "geoms") else [u]):
                rings = [[[round(x, 4), round(y, 4)] for x, y in ring.coords] for ring in [g.exterior, *g.interiors]]
                f.write(json.dumps({"type": "Feature", "properties": {"k": k, "a": 1},
                                    "geometry": {"type": "Polygon", "coordinates": rings}}, separators=(",", ":")) + "\n")
            print("agg", B, "k", k, "bins", len(L))

TC = ["tippecanoe", "-q", "-f", "-l", "c", "-P", "--simplification=2"]
parts = []
for B, z0, z1 in ((0.06, 3, 5), (0.02, 6, 8)):
    gj = os.path.join(work, "oilgas_agg_%g.geojsons" % B); agg(B, gj)
    pt = os.path.join(work, "oilgas_z%d.pmtiles" % z0); parts.append(pt)
    subprocess.run(TC + ["-o", pt, "-Z%d" % z0, "-z%d" % z1, "--coalesce-densest-as-needed", gj], check=True)
pt = os.path.join(work, "oilgas_z9.pmtiles"); parts.append(pt)
subprocess.run(TC + ["-o", pt, "-Z9", "-z12", "--no-tiny-polygon-reduction", "--coalesce-densest-as-needed", out], check=True)
pm = os.path.join(work, "oilgas_cells_v1.pmtiles")
subprocess.run(["tile-join", "-f", "-o", pm, "--attribution=IHS Energy and USGS", *parts], check=True)
print("wrote", pm)
