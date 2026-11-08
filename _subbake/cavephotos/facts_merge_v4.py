"""Merge caves_notable_v3.json + photo galleries + per-cave facts into
caves_notable_v4.json (BLUISH VOID CAVES tab), 2026-11-07.

Inputs:
  v3.json          https://cdn.bluishvoid.com/under/caves_notable_v3.json
  gallery.json     extras_build.py output (Commons photos, licences checked)
  main_caps.json   short captions for each cave's existing main photo
  facts/out_*.json per-cave facts researched from official park / show-cave
                   sites, NPS, UNESCO, Wikipedia and speleological sources
                   (each entry lists its own src_info URLs)
  tnotes.json      t_note text recased as full sentences (same meaning)
Every v3 field is kept unchanged except t_note. New fields: photos, rock,
formed, visit, visit_note, difficulty, diff_note, tour, season, found,
found_note, site, features, src_info.

usage: python3 -I facts_merge_v4.py v3.json gallery.json main_caps.json tnotes.json OUT.json facts/out_0.json ...
"""
import json, sys
v3, gal, caps, tn = (json.load(open(f)) for f in sys.argv[1:5])
facts = {}
for f in sys.argv[6:]:
    for x in json.load(open(f)): facts[x["n"]] = x
# editorial fixes after review
if "Lascaux" in facts:
    facts["Lascaux"].update(difficulty="easy", diff_note="replica visit at Lascaux IV; the original cave is closed")
def fix(n, **kw):
    if n in facts: facts[n].update(kw)
def dropfeat(n, prefix):
    if n in facts: facts[n]["features"] = [x for x in facts[n].get("features", []) if not x.startswith(prefix)]
fix("Lost River Gorge and Boulder Caves", rock="granite (boulder talus, not a solution cave)")
dropfeat("Hölloch", "more than 1,000 m deep")          # depth figures disagree
dropfeat("Scărișoara Cave", "ice core shows")          # ice-age claims conflict
if "Son Doong" in facts:
    facts["Son Doong"]["features"] = [x.replace("stalagmites up to 80 m", "stalagmites up to about 70 m")
                                      for x in facts["Son Doong"].get("features", [])]
# author names where the Commons Artist field is empty, verbose or a non-name
CREDIT_FIX = [
    ("Ad Meskens You are free", "Ad Meskens"),
    ('"Tichnor Quality Views," Reg. U. S. Pat. Off. Made Only by Tichnor Bros.,...', "Tichnor Bros. postcard"),
    ('Pub. by Crystal Cave Co. Inc., Reading, PA. "Tichnor Quality Views," Reg. U....', "Crystal Cave Co., Tichnor Bros. postcard"),
    ('Pub. by E. C. Gilman, Hellertown, PA. "Tichnor Quality Views," Reg. U. S....', "E. C. Gilman, Tichnor Bros. postcard"),
    ("The original uploader was Michaelmcandrew at English Wikipedia.", "Michaelmcandrew"),
    ("This picture belongs to Gilbert Bohec Please credit : Gilbert Bohec /...", "Gilbert Bohec"),
    ("Photograph by Mike Peel (www.mikepeel.net).", "Mike Peel"),
    ("Enrique Baquero Link to Wikispecies", "Enrique Baquero"),
    ("Horseluv10 at English Wikipedia", "Horseluv10"),
    ("Dave Bunnell / Under Earth Images", "Dave Bunnell (Under Earth Images)"),
    ("User:MatthiasKabel", "Matthias Kabel"),
    ("CarlsbadCavernsNPS", "NPS"),
    ("Já / CC BY 3.0", "Genius920308 / CC BY 3.0"),
    ("unknown / CC BY-SA 2.0 de", "Nanosmile / CC BY-SA 2.0 de"),
    ("NikyValt / CC BY-SA 4.0", "Marcin Jamkowski (uploaded by NikyValt) / CC BY-SA 4.0"),
]
def credit(c):
    for a, b in CREDIT_FIX:
        if c.startswith(a): c = b + c[len(a):]
    return c
ORDER = ["rock", "formed", "visit", "visit_note", "difficulty", "diff_note", "tour", "season",
         "found", "found_note", "site", "features", "src_info"]
out = []
for c in v3:
    c = dict(c)
    if c["n"] in tn: c["t_note"] = tn[c["n"]]
    g = gal.get(c["n"])
    if g:
        ph = [{k: x[k] for k in ("u", "c", "s", "cap")} for x in g]
        ph[0]["cap"] = caps.get(c["n"], "")
        for x in ph[1:]: x["c"] = credit(x["c"])
        c["photos"] = ph
    f = facts.get(c["n"], {})
    for k in ORDER:
        if f.get(k) not in (None, "", []): c[k] = f[k]
    out.append(c)
json.dump(out, open(sys.argv[5], "w"), ensure_ascii=False, separators=(",", ":"))
print(len(out), "caves;", sum(1 for c in out if "photos" in c), "with photos")
