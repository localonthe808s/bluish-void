"""LANDSLIDES bake -> under/landslides_v1.pmtiles (layers "a" polygons, "p" points).

Source: USGS, Landslide Inventories across the United States (ver. 3.0, Feb 2025),
  Belair, Jones, Luna & Mirus, https://doi.org/10.5066/P14AJF8I
  (ScienceBase 671eef1fd34ed0f827ea9f12). Read from the USGS-hosted FeatureServers:
  polygons  .../US_Landslide_poly_v2/FeatureServer/12   (680,497)
  points    .../US_Landslide_point_v2/FeatureServer/11  (310,774)
Licence: USGS data release, public domain (credit USGS + constituent inventories).
Baked: 2026-11-07.

Usage: python3 -I landslides_bake.py RAWDIR WORKDIR [fetch|build|tile|all]
  (RAWDIR holds the untrusted downloads; WORKDIR the ndjson + pmtiles)
Needs tippecanoe on PATH. Upload:
  rclone copyto WORKDIR/landslides_v1.pmtiles r2:bluishvoid-bg/under/landslides_v1.pmtiles --s3-no-check-bucket
"""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _arcgis as A

BASE = "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/"
POLY = BASE + "US_Landslide_poly_v2/FeatureServer/12"
PNT = BASE + "US_Landslide_point_v2/FeatureServer/11"
FIELDS = "OBJECTID,Date_Min,Date_Max,Fatalities,Confidence,LS_Type,Inventory"

# LS_Type is free text (1,600+ spellings). k = coarse movement class, first match wins.
CLASSES = [
    ("sn", r"snow"),                                            # snow avalanche path/chute (not a landslide)
    ("cx", r"complex|composite|combination|multiple|slump,|slide.*flow|flow.*slide"),
    ("df", r"debris[ _-]?flow|debris torrent|mud|lahar|debris blowout"),
    ("fa", r"fall|topple"),
    ("av", r"avalanche"),                                       # rock/debris avalanche
    ("sp", r"spread|sand boil|liquef"),
    ("fl", r"flow|creep|rock glacier|solifluction"),                                    # earth flow, rock flow, ...
    ("sl", r"slide|slump|rotational|translational|block|failure|scarp|landslip"),
    ("dp", r"deposit|fan|talus|colluvi|scar"),
    ("ot", r"gull|fill|settle|crack|unstable|sinkhole|erosion"),
]
CLASS_RE = [(k, re.compile(p, re.I)) for k, p in CLASSES]


def klass(t):
    for k, r in CLASS_RE:
        if r.search(t):
            return k
    return "u"   # 'landslide' / 'unknown' / blank


def day(s):
    s = (s or "").strip()
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", s)
    if not m or m.group(1) in ("1900", "0001"):
        return None
    return "%s-%s-%s" % m.groups()


def props(a):
    t = (a.get("LS_Type") or "").strip()
    p = {"c": int(a.get("Confidence") or 0), "k": klass(t)}
    if t:
        p["t"] = t[:48]
    d0, d1 = day(a.get("Date_Min")), day(a.get("Date_Max"))
    if d0:
        p["d"] = d0
        p["y"] = int(d0[:4])
    if d1 and d1 != d0:
        p["e"] = d1
        if not d0:
            p["y"] = int(d1[:4])
    f = a.get("Fatalities") or 0
    if f and f > 0:
        p["x"] = int(f)
    s = (a.get("Inventory") or "").strip()
    if s:
        p["s"] = s[:60]
    return p


def build(raw, work):
    for name, sub in (("a", "poly"), ("p", "pnt")):
        n = 0
        with open(os.path.join(work, "ls_%s.ndjson" % name), "w") as out:
            for ft in A.iter_chunks(os.path.join(raw, "raw_ls_" + sub)):
                g = ft.get("geometry")
                if not g:
                    continue
                p = props(ft.get("properties") or {})
                # tippecanoe: show confident polygons first when dropping at low zoom
                out.write(json.dumps({"type": "Feature", "geometry": g, "properties": p},
                                     separators=(",", ":")) + "\n")
                n += 1
        print(name, n)


def tile(work):
    out = os.path.join(work, "landslides_v1.pmtiles")
    cmd = ["tippecanoe", "-o", out, "--force", "-n", "BLUISH landslides v1",
           "-A", "USGS Landslide Inventories across the U.S. v3 (2025)",
           "-Z4", "-z12", "-B11", "-r2.2",
           "--drop-densest-as-needed", "--extend-zooms-if-still-dropping",
           "--coalesce-densest-as-needed", "--detect-shared-borders",
           "--simplification=4", "--maximum-tile-bytes=600000",
           "-L", "a:" + os.path.join(work, "ls_a.ndjson"),
           "-L", "p:" + os.path.join(work, "ls_p.ndjson"),
           "--read-parallel", "--quiet"]
    print(" ".join(cmd)); subprocess.check_call(cmd)


if __name__ == "__main__":
    raw, work = sys.argv[1], sys.argv[2]
    step = sys.argv[3] if len(sys.argv) > 3 else "all"
    os.makedirs(work, exist_ok=True)
    if step in ("fetch", "all"):
        A.page(POLY, os.path.join(raw, "raw_ls_poly"), FIELDS, poly=True, workers=6)
        A.page(PNT, os.path.join(raw, "raw_ls_pnt"), FIELDS, workers=6)
    if step in ("build", "all"):
        build(raw, work)
    if step in ("tile", "all"):
        tile(work)
