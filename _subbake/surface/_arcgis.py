"""Shared ArcGIS FeatureServer pager for the _subbake/surface bakes.

Pages a layer by OBJECTID ranges (step = maxRecordCount) with a thread pool,
writing each chunk as raw GeoJSON (EPSG:4326) into OUTDIR/chunk_<a>.json.
Existing chunks are skipped, so a crashed run just resumes.
Downloaded files are untrusted data: readers should run under `python3 -I`.
"""
import json, os, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "bluishvoid.com bake"}


def get_json(url, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def oid_range(layer):
    st = json.dumps([{"statisticType": "min", "onStatisticField": "OBJECTID", "outStatisticFieldName": "a"},
                     {"statisticType": "max", "onStatisticField": "OBJECTID", "outStatisticFieldName": "b"}])
    d = get_json(layer + "/query?" + urllib.parse.urlencode({"where": "1=1", "outStatistics": st, "f": "json"}))
    a = d["features"][0]["attributes"]
    return a["a"], a["b"]


def page(layer, outdir, fields, poly=False, step=None, workers=8):
    os.makedirs(outdir, exist_ok=True)
    meta = get_json(layer + "?f=json")
    step = step or meta.get("maxRecordCount", 1000)
    lo, hi = oid_range(layer)
    jobs = list(range(lo, hi + 1, step))

    def one(a):
        fn = os.path.join(outdir, "chunk_%09d.json" % a)
        if os.path.exists(fn):
            return 0
        q = {"where": "OBJECTID>=%d AND OBJECTID<%d" % (a, a + step), "outFields": fields,
             "outSR": 4326, "f": "geojson", "geometryPrecision": 6 if not poly else 5}
        if poly:
            q["maxAllowableOffset"] = 0.00005
        for i in range(6):
            try:
                d = get_json(layer + "/query?" + urllib.parse.urlencode(q))
                if "features" not in d:
                    raise RuntimeError(str(d)[:200])
                break
            except Exception as e:
                if i == 5:
                    print("FAILED", a, e, flush=True)
                    return -1
                time.sleep(5 * (i + 1))
        tmp = fn + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d["features"], f)
        os.replace(tmp, fn)
        return len(d["features"])

    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for n, r in enumerate(ex.map(one, jobs)):
            if r > 0:
                done += r
            if n % 50 == 0:
                print(layer.rsplit("/", 3)[-3], n, "/", len(jobs), flush=True)
    fails = [a for a in jobs if not os.path.exists(os.path.join(outdir, "chunk_%09d.json" % a))]
    print("chunks missing:", len(fails))
    return fails


def iter_chunks(outdir):
    for fn in sorted(os.listdir(outdir)):
        if fn.startswith("chunk_") and fn.endswith(".json"):
            with open(os.path.join(outdir, fn)) as f:
                yield from json.load(f)
