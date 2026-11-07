"""COAL FIELDS + COAL MINES -> under/coal_v1.json (one GeoJSON FeatureCollection).

Fields: USGS Open-File Report 96-92, "Coal Fields of the United States" (Tully 1996),
  https://pubs.usgs.gov/of/1996/of96-092/arcview_files/uscoal_p.{shp,shx,dbf}
  public domain (USGS). Lower 48 + Alaska. Rank from COALTYPE; "doubtful value" kept as d=1.
  Field / province names joined by point-in-polygon from Esri's "USA Coal Fields" view
  (services.arcgis.com/P3ePLMYs2RVChkJx/.../USA_Coal_Fields_view, itself built from the
  same USGS data; lower 48 only, so Alaska fields have no name).
Mines: EIA "Surface and Underground Coal Mines in the US" (Form EIA-7A + MSHA 7000-2,
  period 2023), services2.arcgis.com/FiaPA4ga0iQKduv3/.../Surface_and_Underground_Coal_Mines_in_the_US
  US government work, public domain.
Baked 2026-11-07.

props  fields: k='field', r=rank (anthracite|lowvol|bituminous|subbituminous|lignite),
               d=1 if "of doubtful value", n=field name, pv=province, age
       mines:  k='mine', n=name, ty='surface'|'underground', st=state, prod=short tons (yr in 'yr')
Usage: python3 -I coal.py DL_DIR OUT_JSON
"""
import sys, site, os, json, urllib.request
sys.path.append(site.getusersitepackages())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shapefile
from shapely.geometry import shape, mapping, Point
from shapely import STRtree, make_valid
from shapely.ops import unary_union
from _arcgis import fetch_layer, rnd, UA

dl, outp = sys.argv[1], sys.argv[2]
os.makedirs(dl, exist_ok=True)
base = "https://pubs.usgs.gov/of/1996/of96-092/arcview_files/uscoal_p."
for e in ("shp", "shx", "dbf"):
    p = os.path.join(dl, "uscoal_p." + e)
    if not os.path.exists(p):
        open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(base + e, headers=UA)).read())

RANK = {20: "anthracite", 40: "lowvol", 60: "bituminous", 30: "subbituminous", 50: "lignite"}
r = shapefile.Reader(os.path.join(dl, "uscoal_p"))
polys, holes = [], []
for sr in r.iterShapeRecords():
    ct = int(sr.record["COALTYPE"])
    g = make_valid(shape(sr.shape.__geo_interface__))
    if ct == 0: holes.append(g); continue
    polys.append((g, RANK[ct - ct % 10 if ct % 10 == 5 else ct], 1 if ct % 10 == 5 else 0))
hole_u = unary_union(holes)

esri = fetch_layer("https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/USA_Coal_Fields_view/FeatureServer/0", page=1000)
eg = [make_valid(shape(f["geometry"])) for f in esri]
tree = STRtree(eg)

feats = []
for g, rank, d in polys:
    g = g.difference(hole_u)
    g = g.simplify(0.004, preserve_topology=True)
    if g.is_empty or g.area < 1e-6: continue
    p = {"k": "field", "r": rank}
    if d: p["d"] = 1
    pt = g.representative_point()
    for i in tree.query(pt, predicate="within"):
        a = esri[int(i)]["properties"]
        if a.get("NAME") and not a["NAME"].startswith("Unnamed"): p["n"] = a["NAME"].strip()
        if a.get("PROVINCE"): p["pv"] = a["PROVINCE"].strip()
        if a.get("AGE"): p["age"] = a["AGE"].strip()
        break
    m = mapping(g)
    feats.append({"type": "Feature", "properties": p,
                  "geometry": {"type": m["type"], "coordinates": rnd(json.loads(json.dumps(m["coordinates"])), 4)}})
nf = len(feats)

mines = fetch_layer("https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/Surface_and_Underground_Coal_Mines_in_the_US/FeatureServer/0", page=1000)
for f in mines:
    a, g = f["properties"], f.get("geometry")
    if not g: continue
    p = {"k": "mine", "n": " ".join((a.get("MINE_NAME") or "").split()),
         "ty": (a.get("MINE_TYPE") or "").strip().lower(), "st": (a.get("state") or "").strip().title()}
    if a.get("PRODUCTION") is not None: p["prod"] = a["PRODUCTION"]; p["yr"] = a.get("PERIOD")
    feats.append({"type": "Feature", "properties": p,
                  "geometry": {"type": "Point", "coordinates": rnd(g["coordinates"], 5)}})
json.dump({"type": "FeatureCollection", "features": feats}, open(outp, "w"), separators=(",", ":"))
print("fields", nf, "mines", len(feats) - nf, "bytes", os.path.getsize(outp))
