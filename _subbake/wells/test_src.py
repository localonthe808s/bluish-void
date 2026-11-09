"""Run one state adapter and report counts + 3 samples.
usage: python3 -I test_src.py <code> [limit]
"""
import sys, os, json, importlib.util, math
here = os.path.dirname(os.path.abspath(__file__))
code = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
spec = importlib.util.spec_from_file_location("src_" + code, os.path.join(here, "src_%s.py" % code))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
n = ni = bad = 0; samples = []; ids = set(); dup = 0
lat0 = lat1 = lon0 = lon1 = None
for w in m.wells():
    n += 1
    ok = (isinstance(w.get("lat"), float) and isinstance(w.get("lon"), float)
          and -90 <= w["lat"] <= 90 and -180 <= w["lon"] <= 180 and w.get("log")
          and w["id"].startswith(code + ":") and w["src"] == code)
    for iv in w.get("log") or []:
        if not (len(iv) == 3 and isinstance(iv[2], str) and len(iv[2]) <= 120): ok = False
    if not ok: bad += 1
    if w["id"] in ids: dup += 1
    ids.add(w["id"])
    ni += len(w["log"])
    lat0 = w["lat"] if lat0 is None else min(lat0, w["lat"]); lat1 = w["lat"] if lat1 is None else max(lat1, w["lat"])
    lon0 = w["lon"] if lon0 is None else min(lon0, w["lon"]); lon1 = w["lon"] if lon1 is None else max(lon1, w["lon"])
    if n in (1, 1000, 50000) or len(samples) < 3 and n % 997 == 0: samples.append(w)
    if limit and n >= limit: break
print("src=%s wells=%d intervals=%d bad=%d dup_ids=%d bbox=lat[%s,%s] lon[%s,%s]" % (code, n, ni, bad, dup, lat0, lat1, lon0, lon1))
for s in samples[:3]:
    s = dict(s); s["log"] = s["log"][:6] + (["...%d more" % (len(s["log"]) - 6)] if len(s["log"]) > 6 else [])
    print(json.dumps(s))
