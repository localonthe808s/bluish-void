"""Candidate finder for CAVES tab photos (BLUISH VOID).

Source: Wikimedia Commons API (https://commons.wikimedia.org/w/api.php),
generator=search in the File namespace + prop=imageinfo/extmetadata.
Only keeps files whose LicenseShortName is public domain, CC0, CC BY or
CC BY-SA. Written 2026-11-07. Output is a candidate list for hand review.

usage: python3 -I commons_search.py OUT.json "query1" ["query2" ...]
"""
import json, sys, time, urllib.error, urllib.parse, urllib.request
UA = "bluishvoid.com (dashboard; cave photos)"
API = "https://commons.wikimedia.org/w/api.php"
OK = ("public domain", "pd", "cc0", "cc by", "cc-by")

def get(params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(API + "?" + q, headers={"User-Agent": UA})
    for k in range(8):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429: raise
            time.sleep(10 * (k + 1))
    raise RuntimeError("429 forever")

def lic_ok(s):
    s = (s or "").lower()
    if "nc" in s.split("-") or "-nc" in s or "nd" in s.split("-") or "-nd" in s:
        return False
    return any(s.startswith(o) for o in OK) or "public domain" in s

def search(q, n=20):
    d = get({"action": "query", "format": "json", "generator": "search",
             "gsrsearch": q, "gsrnamespace": 6, "gsrlimit": n,
             "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime",
             "iiurlwidth": 960})
    out = []
    for p in (d.get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png", "image/tiff", "image/webp"):
            continue
        md = ii.get("extmetadata", {})
        lic = md.get("LicenseShortName", {}).get("value", "")
        if not lic_ok(lic):
            continue
        out.append({"title": p["title"], "w": ii.get("width"), "h": ii.get("height"),
                    "lic": lic, "artist": md.get("Artist", {}).get("value", ""),
                    "desc": md.get("ImageDescription", {}).get("value", "")[:160],
                    "thumb": ii.get("thumburl"), "page": ii.get("descriptionurl"),
                    "idx": p.get("index", 99)})
    out.sort(key=lambda x: x["idx"])
    return out

if __name__ == "__main__":
    res = {}
    for q in sys.argv[2:]:
        res[q] = search(q)
        time.sleep(4)
    json.dump(res, open(sys.argv[1], "w"), indent=1)
