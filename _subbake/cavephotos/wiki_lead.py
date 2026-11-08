"""Lead-image finder for CAVES tab photos (BLUISH VOID), 2026-11-07.

For each cave in caves_notable_v1.json: English Wikipedia search
(https://en.wikipedia.org/w/api.php, list=search) -> top article ->
prop=pageimages (the article's lead image) -> Commons imageinfo/extmetadata
for licence. Writes a candidate table for hand review; nothing is chosen here.

usage: python3 -I wiki_lead.py caves_notable_v1.json OUT.json
"""
import json, sys, time, urllib.error, urllib.parse, urllib.request
UA = "bluishvoid.com (dashboard; cave photos)"

def get(api, params):
    params = dict(params, format="json")
    req = urllib.request.Request(api + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    for k in range(6):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            time.sleep(5 * (k + 1))
    raise RuntimeError("429 forever")

WP = "https://en.wikipedia.org/w/api.php"
CM = "https://commons.wikimedia.org/w/api.php"
caves = json.load(open(sys.argv[1]))
out = []
for c in caves:
    s = get(WP, {"action": "query", "list": "search", "srsearch": c["n"] + " cave", "srlimit": 1})
    hits = s["query"]["search"]
    art = hits[0]["title"] if hits else None
    row = {"n": c["n"], "article": art}
    if art:
        p = get(WP, {"action": "query", "titles": art, "prop": "pageimages|images", "piprop": "original|name", "imlimit": 50, "redirects": 1})
        pg = list(p["query"]["pages"].values())[0]
        row["lead"] = pg.get("pageimage")
        row["images"] = [i["title"] for i in pg.get("images", [])]
        if row["lead"]:
            ii = get(CM, {"action": "query", "titles": "File:" + row["lead"], "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 960})
            ip = list(ii["query"]["pages"].values())[0]
            inf = (ip.get("imageinfo") or [{}])[0]
            md = inf.get("extmetadata", {})
            row.update(w=inf.get("width"), h=inf.get("height"), lic=md.get("LicenseShortName", {}).get("value"), oncommons=bool(ip.get("imageinfo")))
    out.append(row)
    print(row["n"], "|", art, "|", row.get("lead"), row.get("w"), row.get("h"), row.get("lic"), flush=True)
    time.sleep(1.5)
json.dump(out, open(sys.argv[2], "w"), indent=1)
