"""Build under/karst_v1.pmtiles (layer "k") from the USGS karst map of the US.

Source: Weary, D.J., and Doctor, D.H., 2014, Karst in the United States: A digital
map compilation and database: U.S. Geological Survey Open-File Report 2014-1156,
https://doi.org/10.3133/ofr20141156
Download: https://pubs.usgs.gov/of/2014/1156/downloads/USKarstMap.zip (282 MB,
fetched 2026-11-07).  US Government work, public domain.  Covers the contiguous
48, Alaska, Hawaii, Puerto Rico and the US Virgin Islands.

Run:  python3 -I karst_build.py SHAPEFILE_DIR OUT_GEOJSONSEQ
then tippecanoe (see karst_tiles.sh).

Polygons of the same class are dissolved together (unary_union in each shapefile's
own Albers metres), simplified at 25 m, reprojected to WGS84 with pyproj, exploded.
Properties:  c = class, x = exposure, w = climate (see CLASS / EXPO below).
"""
import sys; sys.path.append("/Users/vvvaa/Library/Python/3.9/lib/python/site-packages")
import json, glob, os, collections
import shapefile
from shapely.geometry import shape, mapping
from shapely.ops import unary_union, transform
from shapely import make_valid
import pyproj

SRC, OUT = sys.argv[1], sys.argv[2]
# file -> class key
FILES = {
    "Continguous48/Carbonates48": None,      # c or u (decided per record)
    "Continguous48/Evaporites48": "e",
    "Continguous48/SandstoneKarst48": "s",
    "Continguous48/Volcanics48": "v",
    "Continguous48/Piping48": "p",
    "Alaska/AKcarbonates": "c",
    "Alaska/Akvolcanics": "v",
    "Alaska/Thermokarst": "t",
    "Hawaii/HIcarbonates": "c",
    "Hawaii/HIvolcanics": "v",
    "PuertoRico_VirginIslands/PRcarbonates": "c",
    "PuertoRico_VirginIslands/VIcarbonates": "c",
}
def expo(kt, ex):
    ex = (ex or "").strip()
    if ex in ("E", "B1", "B2", "B3"): return ex
    k = (kt or "").lower()
    if "buried" in k:
        if "<300" in k: return "B1"
        if ">50" in k or "more than 50" in k: return "B2"
        return "B3"
    return "E"
def clim(kt, cl):
    c = (cl or "").strip().lower()
    if c in ("humid", "dry"): return c[0]
    k = (kt or "").lower()
    return "d" if "dry" in k else ("h" if "humid" in k else "")
groups = collections.defaultdict(list)
for f, cls in FILES.items():
    r = shapefile.Reader(os.path.join(SRC, f), encoding="latin1")
    prj = open(os.path.join(SRC, f + ".prj")).read()
    fl = [x[0] for x in r.fields[1:]]
    for i in range(len(r)):
        try: shp = r.shape(i)
        except shapefile.ShapefileException: continue      # a few empty geometries
        if not shp.points: continue
        d = dict(zip(fl, r.record(i)))
        kt = d.get("KARST_TYPE", "")
        if not kt and f.endswith("Carbonates48"): continue   # one empty record
        c = cls or ("u" if kt.lower().startswith("unconsolidated") else "c")
        if c in ("v", "p", "t"): key = (c, "", "")
        else: key = (c, expo(kt, d.get("Exposure")), clim(kt, d.get("Climate")))
        g = shape(shp.__geo_interface__)
        if not g.is_valid: g = make_valid(g)
        groups[(prj, f.split("/")[0]) + key].append(g)
    print(f, len(r), flush=True)
n = 0
with open(OUT, "w") as out:
    for (prj, region, c, x, w), gs in groups.items():
        tr = pyproj.Transformer.from_crs(pyproj.CRS.from_wkt(prj), "EPSG:4326", always_xy=True)
        u = unary_union([g.buffer(0) for g in gs]).simplify(25, preserve_topology=True)
        u = transform(tr.transform, u)
        polys = getattr(u, "geoms", [u])
        props = {"c": c}
        if x: props["x"] = x
        if w: props["w"] = w
        for p in polys:
            if p.geom_type not in ("Polygon", "MultiPolygon") or p.is_empty: continue
            out.write(json.dumps({"type": "Feature", "properties": props,
                                  "geometry": mapping(p)}, separators=(",", ":")) + "\n"); n += 1
        print(region, c, x, w, len(gs), "->", len(polys), flush=True)
print("features", n)
