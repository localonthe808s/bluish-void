"""Build the per-cave photo galleries for the CAVES tab (BLUISH VOID),
2026-11-07.

Inputs: caves_v3.json; picks.json {slug: [[idx, caption(, "m")], ...]} chosen
by eye from contact sheets (extras_sheets.py; "m" = manual candidate set);
SHEETS dir and SHEETS_M dir with <slug>.json candidate lists.
For each cave with a main photo: re-fetch the main photo's Commons file
(named on its photo_src page) and each pick at up to 1280 px via the Commons
API thumbnail (prop=imageinfo, iiurlwidth), resize to max 1280 px long side,
JPEG q80 progressive -> OUTDIR/<slug>-<i>.jpg (main = -0). Credits come from
Commons extmetadata Artist + LicenseShortName (public domain / CC0 / CC BY /
CC BY-SA only); main-photo credits are carried over from v3 unchanged.
Output gallery.json {cave name: [{u, c, s, cap}]}. Files are untrusted
downloads; DL dir is separate from scripts.

usage: python3 -I extras_build.py caves_v3.json picks.json SHEETS SHEETS_M DL OUTDIR gallery.json
"""
import html, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.append("/Users/vvvaa/Library/Python/3.9/lib/python/site-packages")
from PIL import Image
UA = "bluishvoid.com (dashboard; cave info)"
API = "https://commons.wikimedia.org/w/api.php"
CDN = "https://cdn.bluishvoid.com/under/caves/photos2/"

def fetch(url, js=True):
    for k in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90) as r:
                b = r.read(); return json.loads(b) if js else b
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503): raise
            time.sleep(10 * (k + 1))
    raise RuntimeError("429")

def iinfo(title):
    q = {"action": "query", "format": "json", "titles": title, "prop": "imageinfo",
         "iiprop": "url|size|extmetadata", "iiurlwidth": 1280}
    p = list(fetch(API + "?" + urllib.parse.urlencode(q))["query"]["pages"].values())[0]
    ii = p["imageinfo"][0]
    if ii["height"] > ii["width"]:   # portrait: bound the height instead
        q["iiurlwidth"] = max(1, int(1280 * ii["width"] / ii["height"]))
        p = list(fetch(API + "?" + urllib.parse.urlencode(q))["query"]["pages"].values())[0]
        ii = p["imageinfo"][0]
    return ii

def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()
    return re.sub(r"\s+", " ", s)

caves, picks = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
sd, sdm, dl, outdir = sys.argv[3:7]
os.makedirs(dl, exist_ok=True); os.makedirs(outdir, exist_ok=True)
try: gal = json.load(open(sys.argv[7]))
except Exception: gal = {}

def save(title, slug, i):
    ii = iinfo(title)
    raw = os.path.join(dl, f"{slug}-{i}.raw")
    if not os.path.exists(raw):
        open(raw, "wb").write(fetch(ii.get("thumburl") or ii["url"], js=False)); time.sleep(1)
    im = Image.open(raw).convert("RGB"); im.thumbnail((1280, 1280), Image.LANCZOS)
    im.save(os.path.join(outdir, f"{slug}-{i}.jpg"), "JPEG", quality=80, optimize=True, progressive=True)
    return ii, im.size

for c in caves:
    if not c.get("photo_src"): continue
    slug = c["photo"].rsplit("/", 1)[1][:-4]
    want = picks.get(slug, [])
    if c["n"] in gal and len(gal[c["n"]]) == 1 + len(want): continue
    mt = urllib.parse.unquote(c["photo_src"].split("/wiki/")[1]).replace("_", " ")
    ii, sz = save(mt, slug, 0)
    L = [{"u": CDN + f"{slug}-0.jpg", "c": c["credit"], "s": c["photo_src"], "cap": "", "_wh": sz}]
    for j, pk in enumerate(want, 1):
        cand = json.load(open(os.path.join(sdm if len(pk) > 2 else sd, slug + ".json")))["cands"][pk[0]]
        ii, sz = save(cand["title"], slug, j)
        md = ii.get("extmetadata", {}); g = lambda k: md.get(k, {}).get("value", "")
        lic = g("LicenseShortName").replace("Public domain", "public domain")
        a = clean(g("Artist")) or clean(g("Credit")) or "unknown"
        if len(a) > 80: a = a[:77].rsplit(" ", 1)[0] + "..."
        L.append({"u": CDN + f"{slug}-{j}.jpg", "c": f"{a} / {lic} / Wikimedia Commons",
                  "s": ii["descriptionurl"], "cap": pk[1], "_wh": sz})
    gal[c["n"]] = L
    json.dump(gal, open(sys.argv[7], "w"), indent=1, ensure_ascii=False)
    print(c["n"], [x["_wh"] for x in L], flush=True)
