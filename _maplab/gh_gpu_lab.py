#!/usr/bin/env python3
# Cloud render lab v2: slice renderCloudsSVG + classifyClouds + defs out of
# index.html and render golden-hour AND daytime cloud scenes via headless
# Chrome so we can SEE the artwork (the live app can't preview: CORS).
import json, math, os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "index.html").read_text().splitlines()

def find_line(pred, start=0):
    for i in range(start, len(SRC)):
        if pred(SRC[i]):
            return i
    raise RuntimeError("anchor not found")

# defs that follow id="golden-sky-svg"
_svg = find_line(lambda l: 'id="golden-sky-svg"' in l)
_d0  = find_line(lambda l: l.strip() == "<defs>", _svg)
_d1  = find_line(lambda l: l.strip() == "</defs>", _d0)
DEFS = "\n".join(SRC[_d0+1:_d1])

# renderCloudsSVG: declaration → first 8-space closing brace
_f0 = find_line(lambda l: l.startswith("        function renderCloudsSVG("))
_f1 = find_line(lambda l: l == "        }", _f0+1)
RENDER_FN = "\n".join(SRC[_f0:_f1+1])

# classifyClouds + its helpers (calcCloudBase..classifyClouds)
_c0 = find_line(lambda l: l.startswith("        function calcCloudBase("))
_cc = find_line(lambda l: l.startswith("        function classifyClouds("))
_c1 = find_line(lambda l: l == "        }", _cc+1)
CLASSIFY = "\n".join(SRC[_c0:_c1+1])
print("slice: defs %d-%d  render %d-%d  classify %d-%d" % (_d0+2,_d1,_f0+1,_f1+1,_c0+1,_c1+1))

# ── cloud data builder ──────────────────────────────────────────────────────
def cd(cL=0, cM=0, cH=0, cape=50, w300=20, w500=20, w700=10, pr=0, snow=0,
       temp=70, rh=55, dp=52, vis=131000, wc=0, li=99, blh=800, fzl=12000, wd300=240):
    return dict(cL=cL, cM=cM, cH=cH, cT=max(cL,cM,cH), cape=cape, w300=w300,
                w500=w500, w700=w700, pr=pr, snow=snow, temp=temp, rh=rh, dp=dp,
                vis=vis, wc=wc, li=li, blh=blh, fzl=fzl, wd300=wd300)

SCEN = [
  ("Fair cumulus, sunset", "gh", 3.0, cd(cL=30, cM=0, cH=0, cape=400, temp=80, rh=50)),
  ("Cumulonimbus + rain, sunset", "gh", 2.5, cd(cL=58, cM=22, cH=42, cape=2500, pr=1.6, temp=82, rh=72, dp=70, w500=45, w300=60, blh=1400)),
  ("Stratocumulus deck, sunset", "gh", 2.5, cd(cL=70, cape=50, temp=60, rh=80)),
  ("Altocumulus rows, sunset", "gh", 2.5, cd(cM=52, cH=0, cape=50, temp=70, rh=47, dp=50, w700=8)),
  ("Cirrus, sunset", "gh", 2.0, cd(cH=45, cape=10)),
  ("Cirrocumulus, sunset", "gh", 2.0, cd(cH=35, cape=10, w300=12)),
  ("Mixed layers, sunset", "gh", 2.5, cd(cL=40, cM=52, cH=50, temp=88, rh=47, dp=64, cape=350)),
  ("Overcast rain (Ns), sunset", "gh", 2.0, cd(cL=95, cM=90, cH=60, pr=2.0, rh=95, temp=55, dp=53)),
  ("Mixed layers, blue hour", "gh", -3.0, cd(cL=40, cM=52, cH=50, temp=70, rh=47, dp=55, cape=200)),
  ("Fair cumulus, midday", "day", 45.0, cd(cL=35, cape=500, temp=82, rh=45)),
]
FOCUS = os.environ.get("FOCUS","")
if FOCUS:
    want = [x.strip() for x in FOCUS.split("|")]
    SCEN = [s for s in SCEN if s[0] in want]

CELL_W = int(os.environ.get("CELL_W", 1000))
COLS = int(os.environ.get("COLS", 1))
SKY_H = round((CELL_W - 4)/2 * 232/220)
ROW_H = SKY_H + 28
ROWS = math.ceil(len(SCEN)/COLS)
PAGE_W = CELL_W*COLS + (COLS+1)*6 + 20
PAGE_H = ROWS*ROW_H + (ROWS+1)*6 + 40

# daytime blue sky gradient (the app recolors ghNowGrad live; this stands in)
DAY_GRAD = ('<linearGradient id="dayGrad" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0%" stop-color="#3f78d8"/>'
            '<stop offset="55%" stop-color="#5a93e0"/>'
            '<stop offset="100%" stop-color="#b9d4ee"/></linearGradient>')

cells = []
for i,(label,mode,sa,data) in enumerate(SCEN):
    cells.append(dict(id="s%d"%i, label=label, mode=mode, sa=sa, cd=data))

def cell_svg(c):
    bg = "dayGrad" if c["mode"]=="day" else "ghFcGrad"
    def panel(pid, withCanvas):
        return ('<div class="pan"><svg class="sky" viewBox="0 -60 220 232" preserveAspectRatio="xMidYMax meet" id="%s">'
                '<defs>%s%s</defs><g clip-path="url(#ghClipL)" id="g_%s">'
                '<rect x="0" y="-100" width="220" height="280" fill="url(#%s)"/>'
                '<rect id="ghTerrainR" x="0" y="132" width="220" height="48" fill="#1a1018"/></g></svg>%s</div>') % (
                pid, DEFS, DAY_GRAD, pid, bg, ('<canvas class="gl" id="cv_%s"></canvas>' % c["id"]) if withCanvas else '')
    return ('<div class="cell"><div class="lbl">%s <span class="sa">sa %.1f&deg;</span> <span class="tag">SVG now &larr; &rarr; GPU</span></div>'
            '<div class="row">%s%s</div></div>') % (c["label"], c["sa"], panel(c["id"], False), panel(c["id"]+"b", True))

page = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  body{margin:0;background:#0b0b12;font-family:-apple-system,sans-serif;}
  .grid{display:grid;grid-template-columns:repeat(%d,%dpx);gap:6px;padding:10px;}
  .cell{background:#000;border-radius:6px;overflow:hidden;}
  .lbl{color:#cdd;font-size:12px;font-weight:700;padding:4px 7px;letter-spacing:.02em;}
  .sa{color:#8aa;font-weight:500;}
  .sky{display:block;width:100%%;height:%dpx;} .row{display:grid;grid-template-columns:1fr 1fr;gap:4px;} .pan{position:relative;} .gl{position:absolute;left:0;top:0;width:100%%;height:100%%;pointer-events:none;} .tag{color:#7a8;font-weight:500;}
</style></head><body>
<div class="grid">%s</div>
<script src="/cloud_gl.js?v=34"></script><script src="/sky_gl.js?v=4"></script><script src="/sky2_gl.js?v=7"></script>
<script>
var saNow = 2.5;
window.bvF = function(c){ return c == null ? null : c * 9 / 5 + 32; }; window.bvDF = function(c){ return c == null ? null : c * 9 / 5; };   /* the site's C->F helpers (index.html top) */
%s
%s
var SCEN = %s;
SCEN.forEach(function(s){
  var grp = document.getElementById('g_'+s.id);
  saNow = s.sa;
  try {
    var types = classifyClouds(s.cd);
    var dbg = types.map(function(t){return t.genus.slice(0,2)+':'+t.species+' '+Math.round(t.cover);}).join(' | ');
    var lbl = grp.closest('.cell').querySelector('.lbl');
    if (lbl) lbl.innerHTML += ' <span style="color:#f90;font-weight:600">['+dbg+']</span>';
    renderCloudsSVG(grp, 'ghFc', s.cd, types, s.mode==='gh', 0);
  } catch(e){
    console.warn('render fail', s.id, e);
    grp.ownerSVGElement.insertAdjacentHTML('beforeend','<text x=8 y=20 fill=red font-size=9>'+e.message+'</text>');
  }
});
/* the GPU twin of each scene, animated */
var CV = SCEN.map(function(s){ var cv = document.getElementById('cv_'+s.id); var r = cv.getBoundingClientRect(), d = 2; cv.width = r.width*d; cv.height = r.height*d;
  var g = cv.getContext('2d'); g.setTransform(cv.width/220, 0, 0, cv.height/232, 0, 0); return { s: s, cv: cv, g: g, types: classifyClouds(s.cd) }; });
/* STATIC (user: "i dont think we need to animate the golden hour artworks"): each sky rendered once */
var t0 = performance.now();
CV.forEach(function(c){ bvSky2(c.g, { W: 220, H: 232, hz: 40, sa: c.s.sa, types: c.types, ppu: 4 }); });
console.log('sky2 render ms', Math.round(performance.now() - t0));
document.title='ready';
</script></body></html>""" % (
  COLS, CELL_W, SKY_H,
  "".join(cell_svg(c) for c in cells),
  CLASSIFY,
  RENDER_FN,
  json.dumps([dict(id=c["id"], cd=c["cd"], mode=c["mode"], sa=c["sa"]) for c in cells]),
)

(ROOT / "_cloudlab" / "gh_gpu.html").write_text(page)
print("cells %d  page %dx%d" % (len(cells), PAGE_W, PAGE_H))
print("PAGE_W=%d PAGE_H=%d" % (PAGE_W, PAGE_H))
