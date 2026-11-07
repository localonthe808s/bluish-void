"""Shared helper for the UNDERGROUND bakes: paged ArcGIS FeatureServer query.

Fetches every row of a layer with resultOffset paging (ordered by OBJECTID),
optionally in parallel. User-Agent identifies the project only.
"""
import json, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "bluishvoid.com bake"}
USER_SITE = "/Users/vvvaa/Library/Python/3.9/lib/python/site-packages"
if USER_SITE not in sys.path:
    sys.path.append(USER_SITE)


def get_json(url, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                d = json.loads(r.read())
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 + 3 * i)


def fetch_all(layer_url, out_fields="*", fmt="geojson", page=2000, workers=4,
              geometry=True, extra=None):
    """Return a list of features (GeoJSON features if fmt=geojson, else esri attribute dicts)."""
    n = get_json(layer_url + "/query?where=1%3D1&returnCountOnly=true&f=json")["count"]
    def one(off):
        q = {"where": "1=1", "outFields": out_fields, "orderByFields": "OBJECTID",
             "resultOffset": off, "resultRecordCount": page, "f": fmt,
             "returnGeometry": "true" if geometry else "false", "outSR": 4326}
        if extra:
            q.update(extra)
        d = get_json(layer_url + "/query?" + urllib.parse.urlencode(q))
        return d.get("features", [])
    out = []
    with ThreadPoolExecutor(workers) as ex:
        for i, feats in enumerate(ex.map(one, range(0, n, page))):
            out.extend(feats)
            if i % 20 == 0:
                print(f"  {len(out)}/{n}", file=sys.stderr, flush=True)
    print(f"  fetched {len(out)} of {n}", file=sys.stderr)
    return out
