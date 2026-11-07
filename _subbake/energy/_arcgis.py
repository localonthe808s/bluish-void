"""Shared helper: page an ArcGIS FeatureServer layer into a GeoJSON feature list."""
import json, time, urllib.request, urllib.parse

UA = {"User-Agent": "bluishvoid.com bake"}

def fetch_layer(url, page=1000, extra=None):
    feats, off = [], 0
    while True:
        q = {"where": "1=1", "outFields": "*", "outSR": "4326", "f": "geojson",
             "resultOffset": off, "resultRecordCount": page, "orderByFields": ""}
        q.update(extra or {})
        u = url + "/query?" + urllib.parse.urlencode(q)
        for tries in range(5):
            try:
                d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120))
                break
            except Exception as e:
                if tries == 4: raise
                time.sleep(3 * (tries + 1))
        fs = d.get("features", [])
        feats += fs
        off += len(fs)
        if not fs or (not d.get("properties", {}).get("exceededTransferLimit") and not d.get("exceededTransferLimit") and len(fs) < page):
            break
    return feats

def rnd(c, nd=5):
    if isinstance(c, (int, float)): return round(c, nd)
    return [rnd(x, nd) for x in c]
