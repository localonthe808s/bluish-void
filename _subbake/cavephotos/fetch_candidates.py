"""Download 960 px Commons thumbnails + licence metadata for hand-picked
candidate photos (BLUISH VOID CAVES tab), 2026-11-07.

Source: Wikimedia Commons API imageinfo (iiprop=url|size|extmetadata,
iiurlwidth=960). Files are untrusted downloads and go to their own folder.

usage: python3 -I fetch_candidates.py CANDS.json DLDIR META.json
  CANDS.json = [[key, "File:..."], ...]   (key = slug or slug_alt)
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request
UA = "bluishvoid.com (dashboard; cave photos)"
API = "https://commons.wikimedia.org/w/api.php"

def fetch(url, js=True):
    for k in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                b = r.read()
                return json.loads(b) if js else b
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            time.sleep(10 * (k + 1))
    raise RuntimeError("429")

cands = json.load(open(sys.argv[1])); dl = sys.argv[2]
try: meta = json.load(open(sys.argv[3]))
except Exception: meta = {}
for key, title in cands:
    if key in meta and meta[key]["title"] == title and os.path.exists(os.path.join(dl, key + ".img")):
        continue
    q = urllib.parse.urlencode({"action": "query", "format": "json", "titles": title, "prop": "imageinfo",
                                "iiprop": "url|size|extmetadata", "iiurlwidth": 960})
    d = fetch(API + "?" + q)
    p = list(d["query"]["pages"].values())[0]
    if "imageinfo" not in p:
        print("MISSING", key, title); continue
    ii = p["imageinfo"][0]; md = ii.get("extmetadata", {})
    g = lambda k: md.get(k, {}).get("value", "")
    meta[key] = {"title": title, "w": ii["width"], "h": ii["height"], "thumb": ii.get("thumburl") or ii["url"],
                 "page": ii["descriptionurl"], "artist": g("Artist"), "credit": g("Credit"),
                 "lic": g("LicenseShortName"), "licurl": g("LicenseUrl"), "attr_req": g("AttributionRequired"),
                 "desc": g("ImageDescription")[:300]}
    open(os.path.join(dl, key + ".img"), "wb").write(fetch(meta[key]["thumb"], js=False))
    print("ok", key, meta[key]["lic"], flush=True)
    json.dump(meta, open(sys.argv[3], "w"), indent=1)
    time.sleep(2)
json.dump(meta, open(sys.argv[3], "w"), indent=1)
