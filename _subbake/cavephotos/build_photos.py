"""Resize the hand-picked cave photos and write the credit table
(BLUISH VOID CAVES tab), 2026-11-07.

Inputs: picks.json {cave name: candidate key} and meta.json (Commons
imageinfo/extmetadata saved by fetch_candidates.py), the 960 px thumbs in DLDIR.
Every pick was checked by eye on a contact sheet. Licences: public domain,
CC0, CC BY, CC BY-SA only (from Commons LicenseShortName).
Output: OUTDIR/<slug>.jpg (max 640 px long side, JPEG q80, progressive)
and photos.json {cave: {photo, credit, photo_src}}; the cdn path is
https://cdn.bluishvoid.com/under/caves/photos/<slug>.jpg.

usage: python3 -I build_photos.py picks.json meta.json DLDIR OUTDIR photos.json
"""
import html, json, os, re, sys
sys.path.append("/Users/vvvaa/Library/Python/3.9/lib/python/site-packages")
from PIL import Image

# author names where the Commons Artist field is empty or verbose
AUTHOR = {
    "gouffre-berger": "Gilbert Bohec",
    "jenolan-caves": "The bellman",
    "majlis-al-jinn": "Michaelmcandrew",
    "eisriesenwelt": "Matthias Kabel",
    "lascaux": "Paleolithic painting (photo: EU)",
    "chauvet-cave": "museum replica; photo by HTO",
    "cosquer-cave": "Cosquer Méditerranée replica; Kleber Rossillon & Région Provence-Alpes-Côte d'Azur",
    "altamira": "Museo de Altamira y D. Rodríguez",
    "wind-cave": "NPS",
    "mammoth-cave": "NPS",
    "jewel-cave": "NPS",
    "carlsbad-caverns": "NPS",
    "painted-cave": "NPS",
    "lost-river-gorge-and-boulder-caves": "~jar{}",
    "son-doong": "Doug Knuth",
    "deer-cave": "Bernard Dupont",
    "postojna-cave": "Ivan Ivankovic",
    "sea-lion-caves": "Art Bromage",
    "clearwater-cave": "Sunrise Odyssey",
    "skocjan-caves": "Lander",
    "scarisoara-cave": "Beradrian",
    "cango-caves": "Rute Martins (Leoa's Photography)",
}
picks, meta = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
dl, outdir = sys.argv[3], sys.argv[4]
os.makedirs(outdir, exist_ok=True)
out = {}
for cave, key in picks.items():
    m = meta[key]
    slug = key.split("_")[0]
    im = Image.open(os.path.join(dl, key + ".img")).convert("RGB")
    im.thumbnail((640, 640), Image.LANCZOS)
    im.save(os.path.join(outdir, slug + ".jpg"), "JPEG", quality=80, optimize=True, progressive=True)
    a = AUTHOR.get(slug) or html.unescape(re.sub(r"<[^>]+>", "", m["artist"])).strip()
    lic = m["lic"].replace("Public domain", "public domain")
    out[cave] = {"photo": f"https://cdn.bluishvoid.com/under/caves/photos/{slug}.jpg",
                 "credit": f"{a} / {lic} / Wikimedia Commons",
                 "photo_src": m["page"], "_wh": im.size}
json.dump(out, open(sys.argv[5], "w"), indent=1, ensure_ascii=False)
for c, v in out.items(): print(v["_wh"], c, "|", v["credit"])
