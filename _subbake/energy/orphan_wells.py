"""ORPHANED WELLS -> under/orphan_wells_v1.pmtiles (layer "w", points).

Source: USGS, "United States Documented Unplugged Orphaned Oil and Gas Well Dataset"
(Grove & Merrill 2022), ScienceBase 62ebd67bd34eacf539724c56, US_orphaned_wells.csv
https://www.sciencebase.gov/catalog/item/62ebd67bd34eacf539724c56
117,672 wells from 27 state agencies (data files 2019-07..2022-06). Licence CC0 (public domain).
Credit "USGS (state oil & gas agencies)". Baked 2026-11-07.
props: st = 2-letter state, id = API number (digits) or USGS/IGS id, nm = well name + number (<=40 chars)
Usage: python3 -I orphan_wells.py DL_DIR WORK_DIR
"""
import sys, os, csv, json, subprocess, urllib.request
UA = {"User-Agent": "bluishvoid.com bake"}
URL = "https://www.sciencebase.gov/catalog/file/get/62ebd67bd34eacf539724c56?f=__disk__11%2Fe9%2F27%2F11e927c652d995f46129f282b400063b5d262369"
ST = dict(Alabama="AL", Alaska="AK", Arizona="AZ", Arkansas="AR", California="CA", Colorado="CO", Illinois="IL",
          Indiana="IN", Kansas="KS", Kentucky="KY", Louisiana="LA", Michigan="MI", Mississippi="MS", Missouri="MO",
          Montana="MT", Nebraska="NE", Nevada="NV", Ohio="OH", Oklahoma="OK", Pennsylvania="PA", Tennessee="TN",
          Texas="TX", Utah="UT", Wyoming="WY", **{"New York": "NY", "New Mexico": "NM", "North Dakota": "ND",
          "West Virginia": "WV", "Virginia": "VA", "South Dakota": "SD", "Idaho": "ID", "Oregon": "OR"})
dl, work = sys.argv[1], sys.argv[2]
os.makedirs(dl, exist_ok=True); os.makedirs(work, exist_ok=True)
src = os.path.join(dl, "US_orphaned_wells.csv")
if not os.path.exists(src):
    open(src, "wb").write(urllib.request.urlopen(urllib.request.Request(URL, headers=UA)).read())
out = os.path.join(work, "orphan.geojsons")
n = bad = 0
with open(src, encoding="utf-8-sig", newline="") as fi, open(out, "w") as fo:
    for r in csv.DictReader(fi):
        try:
            lat, lon = float(r["Latitude"]), float(r["Longitude"])
        except ValueError:
            bad += 1; continue
        if not (17 < lat < 72 and -180 < lon < -60): bad += 1; continue
        p = {"st": ST.get(r["State"].strip(), r["State"].strip()[:2].upper())}
        wid = r["Well identifier"].strip()
        if wid: p["id"] = wid.split(":", 1)[1] if wid.startswith("API:") else wid
        nm = " ".join((r["Well name"].strip() + " " + r["Well number"].strip()).split())
        if nm and nm.lower() not in ("unknown", "n/a", "na", "none"): p["nm"] = nm[:40]
        fo.write(json.dumps({"type": "Feature", "properties": p,
                             "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}},
                            separators=(",", ":")) + "\n")
        n += 1
print("wells", n, "skipped", bad)
# two passes: z3-8 thinned with no properties (density only), z9-12 every well with props
lo, hi = os.path.join(work, "orphan_lo.pmtiles"), os.path.join(work, "orphan_hi.pmtiles")
subprocess.run(["tippecanoe", "-f", "-o", lo, "-l", "w", "-Z3", "-z8", "-B8", "-r2", "-X",
                "--drop-densest-as-needed", "-P", out], check=True)
subprocess.run(["tippecanoe", "-f", "-o", hi, "-l", "w", "-Z9", "-z12", "-r1",
                "--drop-densest-as-needed", "-P", out], check=True)
pm = os.path.join(work, "orphan_wells_v1.pmtiles")
subprocess.run(["tile-join", "-f", "-o", pm, "--attribution=USGS", lo, hi], check=True)
print("wrote", pm)
