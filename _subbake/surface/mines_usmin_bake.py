"""ABANDONED / HISTORIC MINES bake -> under/mines_usmin_v1.pmtiles (layers "m" points, "a" polygons).

Source: USGS USMIN, "Prospect- and Mine-Related Features from U.S. Geological Survey
  7.5- and 15-Minute Topographic Quadrangle Maps of the United States"
  (Horton & San Juan, ScienceBase 5a1492c3e4b09fc93dcfd574, https://doi.org/10.5066/F78W3CHG).
  Read from the USGS-hosted FeatureServer USGS_Topographic_Mine_Symbols:
    8 = 24k_Points (466,747)   2 = 24k_Polygons (142,658)    (7.5-minute maps, 1:24,000)
    7 = 48k_Points (3,165)     1 = 48k_Polygons (212)        (1:48,000 - 7.5x15 min / PR)
    6 = 625k_Points (101,205)  0 = 625k_Polygons (11,703)    (15-minute maps, 1:62,500 / AK 1:63,360)
Licence: USGS public domain (CC0). Baked: 2026-11-07.

15-minute / 48k features within ~150 m of a 1:24k feature of the same group are dropped
(the same mine drawn on an older, coarser map).

Usage: python3 -I mines_usmin_bake.py RAWDIR WORKDIR [fetch|build|tile|all]
Upload:
  rclone copyto WORKDIR/mines_usmin_v1.pmtiles r2:bluishvoid-bg/under/mines_usmin_v1.pmtiles --s3-no-check-bucket
"""
import json, math, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _arcgis as A

SVC = "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/USGS_Topographic_Mine_Symbols/FeatureServer/"
LAYERS = {  # id: (kind, scale tag)
    8: ("pt", 24), 7: ("pt", 48), 6: ("pt", 62),
    2: ("poly", 24), 1: ("poly", 48), 0: ("poly", 62),
}
PT_FIELDS = "OBJECTID,Ftr_Type,Ftr_Name,Ftr_Azimuth,Topo_Date,Topo_Scale"
PG_FIELDS = "OBJECTID,Ftr_Type,Ftr_Name,Topo_Date,Topo_Scale"

# Ftr_Type -> (f code, g group). g groups: shaft adit prospect mine quarry pit waste works disturbed
TYPES = {
    "Mine Shaft": ("shaft", "shaft"), "Air Shaft": ("airshaft", "shaft"), "Glory Hole": ("gloryhole", "shaft"),
    "Adit": ("adit", "adit"),
    "Prospect Pit": ("prospect", "prospect"), "Diggings": ("diggings", "prospect"), "Trench": ("trench", "prospect"),
    "Mine": ("mine", "mine"), "Coal Mine": ("coal", "mine"), "Uranium Mine": ("uranium", "mine"),
    "Silica Mine": ("silica", "mine"), "Placer Mine": ("placer", "mine"), "Hydraulic Mine": ("hydraulic", "mine"),
    "Open Pit Mine": ("openpit", "mine"), "Open Pit Mine or Quarry": ("openpitq", "mine"), "Strip Mine": ("strip", "mine"),
    "Quarry": ("quarry", "quarry"), "Quarry - Rock": ("q_rock", "quarry"), "Quarry - Limestone": ("q_lime", "quarry"),
    "Quarry - Pumice": ("q_pumice", "quarry"), "Quarry - Gypsum": ("q_gypsum", "quarry"),
    "Gravel Pit": ("gravel", "pit"), "Sand Pit": ("sand", "pit"), "Sand and Gravel Pit": ("sandgravel", "pit"),
    "Borrow Pit": ("borrow", "pit"), "Gravel/Borrow Pit - Undifferentiated": ("gravelborrow", "pit"),
    "Clay Pit": ("clay", "pit"), "Caliche Pit": ("caliche", "pit"), "Cinder Pit": ("cinder", "pit"),
    "Scoria Pit": ("scoria", "pit"), "Shale Pit": ("shale", "pit"), "Chert Pit": ("chert", "pit"),
    "Marl Pit": ("marl", "pit"), "Shell Pit": ("shell", "pit"), "Bentonite Pit": ("bentonite", "pit"),
    "Lignite Pit": ("lignite", "pit"), "Iron Pit": ("iron", "pit"),
    "Tailings - Undifferentiated": ("tailings", "waste"), "Tailings - Pond": ("t_pond", "waste"),
    "Tailings - Dredge": ("t_dredge", "waste"), "Tailings - Placer": ("t_placer", "waste"),
    "Tailings - Mill": ("t_mill", "waste"), "Mine Dump": ("dump", "waste"), "Slag Pile": ("slag", "waste"),
    "Ore Stockpile/Storage": ("stockpile", "waste"), "Settling Pond": ("settling", "waste"),
    "Leach Pond": ("leach", "waste"), "Evaporation Pond": ("evap", "waste"),
    "Tipple": ("tipple", "works"), "Mill Site": ("mill", "works"), "Salt Evaporator": ("salt", "works"),
    "Disturbed Surface": ("disturbed", "disturbed"), "Disturbed Surface - Pit": ("disturbedpit", "disturbed"),
}
# low-zoom priority: underground openings and named mines survive thinning first
RANK = {"shaft": 9, "adit": 9, "mine": 8, "works": 7, "waste": 6, "quarry": 5, "prospect": 3, "pit": 2, "disturbed": 1}
UNKNOWN = {}


def props(a, sc, pt):
    t = (a.get("Ftr_Type") or "").strip()
    f, g = TYPES.get(t, (None, None))
    if f is None:
        UNKNOWN[t] = UNKNOWN.get(t, 0) + 1
        f, g = "other", "other"
    p = {"f": f, "g": g, "sc": sc}
    n = (a.get("Ftr_Name") or "").strip()
    if n:
        p["n"] = n[:60]
    m = re.search(r"(1[89]\d\d|20\d\d)", a.get("Topo_Date") or "")
    if m:
        p["y"] = int(m.group(1))
    if pt and g == "adit":
        az = a.get("Ftr_Azimuth")
        if az is not None and az > 0:
            p["r"] = int(az) % 360   # adit symbol azimuth, degrees clockwise from north (as drawn on the map)
    return p


def ring_mean(g):  # vertex mean of the first outer ring (dedupe only; no shapely under -I)
    c = g["coordinates"]
    r = c[0][0] if g["type"] == "MultiPolygon" else c[0]
    return sum(p[0] for p in r) / len(r), sum(p[1] for p in r) / len(r)


def key(lon, lat, g):  # ~150 m cell
    return (g, int(lon / 0.0018), int(lat / 0.00135))


def build(raw, work):
    stats = {}
    for kind, lname in (("pt", "m"), ("poly", "a")):
        seen = set()
        out = open(os.path.join(work, "mines_%s.ndjson" % lname), "w")
        for lid in sorted(LAYERS, key=lambda i: LAYERS[i][1]):   # 24k first
            k2, sc = LAYERS[lid]
            if k2 != kind:
                continue
            kept = dup = 0
            for ft in A.iter_chunks(os.path.join(raw, "raw_mines_%d" % lid)):
                g = ft.get("geometry")
                if not g:
                    continue
                p = props(ft.get("properties") or {}, sc, kind == "pt")
                if kind == "pt":
                    lon, lat = g["coordinates"][:2]
                else:
                    lon, lat = ring_mean(g)
                cells = [key(lon + dx * 0.0018, lat + dy * 0.00135, p["g"]) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
                if sc != 24 and any(c in seen for c in cells):
                    dup += 1
                    continue
                if sc == 24:
                    seen.add(key(lon, lat, p["g"]))
                rank = RANK.get(p["g"], 0) + (1 if "n" in p else 0)
                out.write(json.dumps({"type": "Feature", "geometry": g, "properties": dict(p, _r=rank)},
                                     separators=(",", ":")) + "\n")
                kept += 1
            stats["%s_%d" % (kind, sc)] = (kept, dup)
        out.close()
    print(stats, "unknown types:", UNKNOWN)


def tile(work):
    out = os.path.join(work, "mines_usmin_v1.pmtiles")
    cmd = ["tippecanoe", "-o", out, "--force", "-n", "BLUISH mines USMIN v1",
           "-A", "USGS USMIN topographic mine symbols (CC0)",
           "-Z4", "-z12", "-B12", "-r2.4",
           "--order-descending-by=_r", "--exclude=_r",
           "--drop-densest-as-needed", "--extend-zooms-if-still-dropping",
           "--coalesce-densest-as-needed", "--simplification=4",
           "--maximum-tile-bytes=600000",
           "-L", "m:" + os.path.join(work, "mines_m.ndjson"),
           "-L", "a:" + os.path.join(work, "mines_a.ndjson"),
           "--read-parallel", "--quiet"]
    print(" ".join(cmd)); subprocess.check_call(cmd)


if __name__ == "__main__":
    raw, work = sys.argv[1], sys.argv[2]
    step = sys.argv[3] if len(sys.argv) > 3 else "all"
    os.makedirs(work, exist_ok=True)
    if step in ("fetch", "all"):
        for lid, (kind, sc) in LAYERS.items():
            A.page(SVC + str(lid), os.path.join(raw, "raw_mines_%d" % lid),
                   PT_FIELDS if kind == "pt" else PG_FIELDS, poly=(kind == "poly"), workers=6)
    if step in ("build", "all"):
        build(raw, work)
    if step in ("tile", "all"):
        tile(work)
