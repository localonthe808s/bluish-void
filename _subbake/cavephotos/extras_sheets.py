"""Download 320 px Commons thumbs of extra-photo candidates and build one
numbered contact sheet per cave for review by eye (BLUISH VOID CAVES tab),
2026-11-07. Source: thumburl from the Commons API (extras_candidates.py).
Titles that look like maps/diagrams/signs/logos are dropped up front; the
main photo is excluded. Up to 24 candidates per cave, spread over the list.

usage: python3 -I extras_sheets.py caves_v3.json cands.json THUMBDIR SHEETDIR [cave ...]
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.append("/Users/vvvaa/Library/Python/3.9/lib/python/site-packages")
from PIL import Image, ImageDraw
UA = "bluishvoid.com (dashboard; cave info)"
BAD = re.compile(r"map|diagram|plan\b|logo|sign|plaque|survey|profile|section|chart|poster|stamp|"
                 r"brochure|ticket|postcard|\.png$|\.tif|selfie|coat of arms|drawing|engraving|svg", re.I)
caves = {c["n"]: c for c in json.load(open(sys.argv[1]))}
cands = json.load(open(sys.argv[2])); td, sd = sys.argv[3], sys.argv[4]
os.makedirs(td, exist_ok=True); os.makedirs(sd, exist_ok=True)
names = sys.argv[5:] or list(cands)
def slug(n): return caves[n]["photo"].rsplit("/", 1)[1][:-4] if caves[n].get("photo") else re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-")
pick = {}
for n in names:
    main = caves[n].get("photo_src") or ""
    mt = urllib.parse.unquote(main.split("/wiki/")[-1]).replace("_", " ")
    L = [x for x in cands[n]["cands"] if x["title"] != mt and not BAD.search(x["title"])]
    if len(L) > 24:
        step = len(L) / 24; L = [L[int(i * step)] for i in range(24)]
    pick[n] = L
    s = slug(n); W, H, C = 330, 250, 6
    if not L: continue
    for i, x in enumerate(L):
        f = os.path.join(td, f"{s}_{i}.img")
        if not os.path.exists(f):
            for k in range(6):
                try:
                    b = urllib.request.urlopen(urllib.request.Request(x["thumb"], headers={"User-Agent": UA}), timeout=60).read(); break
                except urllib.error.HTTPError as e:
                    if e.code != 429: raise
                    time.sleep(8 * (k + 1))
            open(f, "wb").write(b); time.sleep(0.5)
    sheet = Image.new("RGB", (W * C, (H + 16) * ((len(L) + C - 1) // C)), "white"); d = ImageDraw.Draw(sheet)
    for i, x in enumerate(L):
        try: im = Image.open(os.path.join(td, f"{s}_{i}.img")).convert("RGB")
        except Exception: continue
        im.thumbnail((W - 6, H - 6)); X, Y = (i % C) * W, (i // C) * (H + 16)
        sheet.paste(im, (X + 3, Y + 3)); d.text((X + 4, Y + H + 1), f"{i} {x['title'][5:50]}", fill="black")
    sheet.save(os.path.join(sd, s + ".jpg"), quality=78); print(s, len(L), flush=True)
for n, L in pick.items():
    json.dump({"n": n, "slug": slug(n), "cands": L}, open(os.path.join(sd, slug(n) + ".json"), "w"), indent=1, ensure_ascii=False)
