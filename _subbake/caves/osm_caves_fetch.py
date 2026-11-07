"""Fetch OpenStreetMap natural=cave_entrance worldwide via the Overpass API.

Source: https://overpass-api.de/api/interpreter (OpenStreetMap data, ODbL 1.0,
credit "(c) OpenStreetMap contributors").  Baked 2026-11-07 for the GEOLOGY >
CAVES tab of bluishvoid.com.

Queries a 30x60 degree grid (nodes + ways/relations as centres) with curl
(python 3.9's LibreSSL fails the Overpass TLS handshake), pausing between
tiles, and writes one JSON per tile into OUTDIR.
Run:  python3 -I osm_caves_fetch.py OUTDIR
Next: osm_caves_build.py turns the tiles into cave_entrances_v1.pmtiles.
"""
import sys, os, json, time, subprocess
OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
URL = "https://overpass-api.de/api/interpreter"
UA = "bluishvoid.com bake"
def q(s, w, n, e):
    return ('[out:json][timeout:300];(nwr["natural"="cave_entrance"](%s,%s,%s,%s););out center tags;'
            % (s, w, n, e))
tiles = [(la, lo) for la in range(-90, 90, 30) for lo in range(-180, 180, 60)]
for la, lo in tiles:
    fn = os.path.join(OUT, "t_%d_%d.json" % (la, lo))
    if os.path.exists(fn): continue
    for attempt in range(5):
        try:
            tmp = fn + ".part"
            subprocess.run(["curl", "-sS", "--max-time", "400", "-A", UA, "-o", tmp,
                            "--data-urlencode", "data=" + q(la, lo, la + 30, lo + 60), URL], check=True)
            j = json.load(open(tmp, "rb"))
            if "remark" in j and ("error" in j["remark"].lower() or "timed out" in j["remark"].lower()):
                raise RuntimeError(j["remark"])
            os.rename(tmp, fn)
            print(la, lo, len(j["elements"]), flush=True); break
        except Exception as ex:
            print("retry", la, lo, str(ex)[:200], flush=True); time.sleep(30 * (attempt + 1))
    time.sleep(8)
