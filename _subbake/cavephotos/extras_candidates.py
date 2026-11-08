"""Candidate EXTRA photos per cave for the CAVES tab (BLUISH VOID), 2026-11-07.

Source: Wikimedia Commons API (https://commons.wikimedia.org/w/api.php):
  1. prop=categories of each cave's existing main photo (photo_src page),
     keeping categories whose name shares a word with the cave name;
  2. list=categorymembers (files + one level of subcategories) of those;
  3. a File-namespace search on the cave name as a fallback.
Keeps only public domain / CC0 / CC BY / CC BY-SA (LicenseShortName),
raster images with long side >= 1000 px. Output: candidates for review by
eye on contact sheets (untrusted metadata; nothing here is published).

usage: python3 -I extras_candidates.py caves_v3.json OUT.json
"""
import json, re, sys, time, urllib.error, urllib.parse, urllib.request
UA = "bluishvoid.com (dashboard; cave info)"
API = "https://commons.wikimedia.org/w/api.php"
STOP = {"cave", "caves", "cavern", "caverns", "the", "of", "and", "de", "del", "la", "las", "los",
        "national", "park", "sistema", "system", "in", "photos", "photographs", "images", "files"}

def get(params):
    params = dict(params, format="json")
    url = API + "?" + urllib.parse.urlencode(params)
    for k in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503): raise
            time.sleep(10 * (k + 1))
    raise RuntimeError("429")

def lic_ok(s):
    s = (s or "").lower()
    if re.search(r"\b(nc|nd)\b", s.replace("-", " ")): return False
    return s.startswith(("public domain", "pd", "cc0", "cc by", "cc-by")) or "public domain" in s

def words(s):
    return {w for w in re.findall(r"[a-zà-ž]{3,}", s.lower()) if w not in STOP}

def info(titles):
    out = []
    for i in range(0, len(titles), 40):
        d = get({"action": "query", "titles": "|".join(titles[i:i + 40]), "prop": "imageinfo",
                 "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 320})
        for p in d.get("query", {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            if ii.get("mime") not in ("image/jpeg", "image/png", "image/tiff", "image/webp"): continue
            if max(ii.get("width", 0), ii.get("height", 0)) < 1000: continue
            md = ii.get("extmetadata", {}); g = lambda k: md.get(k, {}).get("value", "")
            if not lic_ok(g("LicenseShortName")): continue
            out.append({"title": p["title"], "w": ii["width"], "h": ii["height"], "lic": g("LicenseShortName"),
                        "artist": g("Artist")[:200], "desc": re.sub(r"<[^>]+>", "", g("ImageDescription"))[:200],
                        "thumb": ii.get("thumburl"), "page": ii.get("descriptionurl")})
        time.sleep(1)
    return out

def members(cat, typ="file", n=200):
    d = get({"action": "query", "list": "categorymembers", "cmtitle": cat, "cmtype": typ, "cmlimit": n})
    return [m["title"] for m in d.get("query", {}).get("categorymembers", [])]

caves = json.load(open(sys.argv[1])); res = {}
try: res = json.load(open(sys.argv[2]))
except Exception: pass
for c in caves:
    if c["n"] in res: continue
    nw = words(c["n"]); titles, cats = [], []
    if c.get("photo_src"):
        t = urllib.parse.unquote(c["photo_src"].split("/wiki/")[1]).replace("_", " ")
        d = get({"action": "query", "titles": t, "prop": "categories", "cllimit": 50, "clshow": "!hidden"})
        for p in d["query"]["pages"].values():
            cats += [x["title"] for x in p.get("categories", []) if words(x["title"]) & nw]
    for cat in cats[:4]:
        titles += members(cat)
        for sub in members(cat, "subcat", 30)[:12]:
            titles += members(sub, n=60)
    if len(set(titles)) < 15:
        d = get({"action": "query", "list": "search", "srsearch": c["n"] + " " + c["where"].split(",")[0],
                 "srnamespace": 6, "srlimit": 40})
        titles += [x["title"] for x in d.get("query", {}).get("search", [])]
    seen, uniq = set(), []
    for t in titles:
        if t not in seen: seen.add(t); uniq.append(t)
    res[c["n"]] = {"cats": cats, "cands": info(uniq[:400])}
    print(c["n"], cats[:3], len(uniq), len(res[c["n"]]["cands"]), flush=True)
    json.dump(res, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
