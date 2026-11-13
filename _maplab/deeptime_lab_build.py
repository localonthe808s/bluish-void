#!/usr/bin/env python3
"""DEEP TIME LAB (2026-11-13, user: "make a lab and show me all the areas for DEEP TIME"). Builds _maplab/deeptime_lab.html:
every tectonic event's globe view (captured from the live page into _maplab/deeptime_lab/<slug>.jpg with the CDP harness) beside its
cross-section running live -- DT.plateScene, DT.TECT, DT.EVENTS and DT.EVKIND copied out of index.html so the lab draws exactly what
the site draws -- grouped into the storylines the events belong to, with the scale/importance proposals under review.
    python3 _maplab/deeptime_lab_build.py
"""
import json, os, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, 'index.html')).read()
def grab(start, end):
    i = src.index(start); j = src.index(end, i) + len(end); return src[i:j]
code = '\n'.join([
    grab("    DT.EVENTS = [", "\n    ];"),
    grab("    DT.EVKIND = {", "};"),
    grab("    DT.TECT = {", "\n    };"),
    grab("    DT.plateScene = function(cv, o, t){", "\n      g.globalAlpha = 1; };"),
])
meta = {m['name']: m for m in json.load(open(os.path.join(ROOT, '_maplab', 'deeptime_lab', 'meta.json')))}
# approximate figures for the proposals: how long, the range then (≈) and now, and where New York stands on it
FACTS = {
  'Grenville orogeny': ['1,250-980 Ma', 'roots under the whole east', 'Mt Marcy, Adirondacks, 1,629 m (a young uplift of old rock)', 'The Fordham gneiss of the Bronx and the bedrock under the boroughs is Grenville crust.'],
  'Rodinia breaks up': ['780-600 Ma', '', 'the Pacific edge of North America begins', 'Far from New York: the west coast of Laurentia.'],
  'The Iapetus Ocean opens': ['620-550 Ma', '', 'the old coastline is buried under the Appalachians', 'The Inwood marble (Inwood Hill, Marble Hill) is limestone from this new coast\u2019s shallow sea floor.'],
  'Taconic orogeny': ['470-440 Ma', 'perhaps Andes-high (\u2248 4-5 km)', 'Mt Equinox, Taconic Range, 1,163 m', 'Manhattan schist and Cameron\u2019s Line -- the suture where the arc was welded on -- run through Manhattan and the Bronx.'],
  'Caledonian orogeny': ['490-390 Ma', 'Himalaya-scale in places', 'Ben Nevis, Scotland, 1,345 m', 'The same belt as the Appalachians, continued across what became the Atlantic: Newfoundland, Ireland, Scotland, Norway.'],
  'Acadian orogeny': ['420-350 Ma', '\u2248 4-6 km', 'Mt Washington, 1,917 m', 'New England\u2019s granites and the Catskills (the sediment shed off this range).'],
  'Alleghanian and Variscan orogenies': ['325-260 Ma', 'Himalaya-high (\u2248 6-8 km)', 'Mt Mitchell, 2,037 m: the Appalachians\u2019 highest today', 'The last collision that finished Pangaea; New York sat in its interior.'],
  'The Newark rift and the Palisades': ['230-190 Ma', '', 'Palisades cliffs, 160 m, across the Hudson', 'The Palisades are the sill itself, seen from Riverside Drive.'],
  'The Atlantic opens': ['200 Ma-today', '', 'the Mid-Atlantic Ridge, still spreading \u2248 2.5 cm a year', 'New York\u2019s harbor and continental shelf sit on the margin this opening left.'],
  'Laramide orogeny': ['80-55 Ma', '', 'Mt Elbert, 4,401 m', 'The Rockies; New York is untouched.'],
  'The Himalaya begin': ['50 Ma-today', 'still rising', 'Everest, 8,849 m', 'The modern example of what the Alleghanian Appalachians were.'],
  'Alpine orogeny': ['65 Ma-today', 'still rising', 'Mont Blanc, 4,806 m', 'The same belt as the Himalaya.'],
}
STORIES = [
  ['THE APPALACHIANS: AN OCEAN OPENS AND CLOSES (A WILSON CYCLE)', 'The range was built in three collisions, on rock from a fourth, then torn by the rift that opened the Atlantic. New York stands on every stage.',
   ['Grenville orogeny', 'The Iapetus Ocean opens', 'Taconic orogeny', 'Acadian orogeny', 'Alleghanian and Variscan orogenies', 'The Newark rift and the Palisades', 'The Atlantic opens']],
  ['PANGAEA ASSEMBLES', 'Several collisions on several coasts at once close Iapetus and the Rheic Ocean into one supercontinent.',
   ['Taconic orogeny', 'Caledonian orogeny', 'Acadian orogeny', 'Alleghanian and Variscan orogenies']],
  ['THE ALPINE-HIMALAYAN BELT', 'Pieces of Gondwana cross the Tethys one after another; Africa and India close it from the south. Still going.',
   ['Alpine orogeny', 'The Himalaya begin']],
  ['THE OTHER EDGES', 'Rodinia tears open the Pacific side of North America; much later a flat slab raises the Rockies far inland.',
   ['Rodinia breaks up', 'Laramide orogeny']],
]
PROPOSALS = [
  ['THEN AND NOW, TO SCALE', 'A height ruler in each cross-section: the range at its height (\u2248, e.g. the Alleghanian Appalachians near Himalaya-high) against what is left today (Mt Mitchell 2,037 m) and Everest for reference. The worn-down stump is the point.'],
  ['ITS FOOTPRINT ON THE GLOBE', 'Light the whole belt along the model\u2019s boundary, not a dot, with its length (\u2248 km) and a familiar modern range drawn to the same scale beside it.'],
  ['HOW LONG IT TOOK', 'A duration bar on the timeline (Taconic \u2248 30 Myr, Alleghanian \u2248 65 Myr): mountain building is slow, the frame is a snapshot of it.'],
  ['WHERE YOU CAN STAND ON IT', 'The rock in New York each event made: Fordham gneiss (Grenville), Inwood marble (Iapetus coast), Manhattan schist and Cameron\u2019s Line (Taconic), the Palisades (Newark). Tap through to THE ROCK map at that spot.'],
  ['STORYLINES', 'PLAY a chain in order -- the Appalachians\u2019 seven steps -- with a progress strip, each scene handing over to the next, the globe following the place.'],
]
def card(nm):
    m = meta[nm]; f = FACTS.get(nm, ['', '', '', '']); e = m['e']; col = m['kind'][1]
    return ('<div class="ev"><img src="deeptime_lab/%s.jpg" alt="">' % m['slug']
            + '<div class="tx"><b style="color:%s">%s</b><i>%s \u00b7 %s \u00b7 LASTED %s</i><p>%s</p>' % (col, nm.upper(), m['kind'][0], ('%.0f MILLION YEARS AGO' % e[0]) if e[0] < 1000 else ('%.1f BILLION YEARS AGO' % (e[0] / 1000)), f[0], e[3])
            + '<canvas data-ev="%s"></canvas>' % nm.replace('"', '&quot;')
            + '<dl>' + (('<dt>AT ITS HEIGHT</dt><dd>%s</dd>' % f[1]) if f[1] else '') + '<dt>TODAY</dt><dd>%s</dd><dt>NEW YORK</dt><dd>%s</dd></dl></div></div>' % (f[2], f[3]))
body = ''.join('<section><h2>%s</h2><p class="lede">%s</p><div class="chain">%s</div>%s</section>' % (
    t, d, ' <span>\u2192</span> '.join('<a href="#%s">%s</a>' % (meta[n]['slug'], n) for n in L),
    ''.join('<div id="%s">%s</div>' % (meta[n]['slug'], card(n)) for n in L)) for t, d, L in STORIES)
props = ''.join('<li><b>%s</b> %s</li>' % (a, b) for a, b in PROPOSALS)
html = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>DEEP TIME LAB</title><style>
body{margin:0;background:#04060c;color:#fff;font:600 14px/1.45 system-ui,sans-serif}
header{padding:28px 24px 8px;max-width:1240px;margin:auto} h1{margin:0;font-size:1.3rem;letter-spacing:.14em;color:#05DB32} header p{opacity:.8;max-width:760px}
.props{max-width:1240px;margin:8px auto 18px;padding:16px 24px;background:#2B22F4;border-radius:14px} .props h3{margin:0 0 8px;letter-spacing:.1em;font-size:.8rem;color:#05DB32}
.props ol{margin:0;padding-left:20px} .props li{margin:6px 0} .props b{letter-spacing:.06em;font-size:.78rem;margin-right:6px}
section{max-width:1240px;margin:0 auto 34px;padding:0 24px} h2{font-size:.9rem;letter-spacing:.12em;color:#05DB32;margin:26px 0 4px} .lede{opacity:.8;margin:0 0 8px}
.chain{font-size:.72rem;letter-spacing:.06em;margin:0 0 14px} .chain a{color:#fff;text-decoration:none;border-bottom:1px solid rgba(255,255,255,.3)} .chain span{opacity:.5;margin:0 4px}
.ev{display:grid;grid-template-columns:360px 1fr;gap:18px;align-items:start;background:#0b0f1c;border-radius:14px;padding:14px;margin:0 0 12px}
.ev img{width:360px;height:360px;border-radius:50%;background:#04060c;object-fit:cover}
.tx b{display:block;letter-spacing:.08em} .tx i{display:block;font-style:normal;font-size:.72rem;letter-spacing:.08em;opacity:.7;margin:2px 0 6px} .tx p{margin:0 0 10px;max-width:640px}
.tx canvas{border-radius:10px;display:block} dl{display:grid;grid-template-columns:120px 1fr;gap:4px 10px;margin:12px 0 0;font-size:.8rem} dt{opacity:.6;letter-spacing:.08em;font-size:.68rem;padding-top:2px} dd{margin:0}
@media(max-width:760px){.ev{grid-template-columns:1fr}.ev img{width:100%;height:auto}}
</style></head><body>
<header><h1>DEEP TIME LAB</h1><p>Every plate-tectonic event in GEOLOGY &rsaquo; DEEP TIME, in the storylines it belongs to: the globe as the site shows it on that event&rsquo;s frame (where it happened, on the plate model&rsquo;s own boundaries) and its cross-section, running live. The figures marked &asymp; are rough reconstructions. Built by _maplab/deeptime_lab_build.py from index.html.</p></header>
<div class="props"><h3>PROPOSED: SHOWING THE SCALE AND IMPORTANCE</h3><ol>''' + props + '''</ol></div>
''' + body + '''
<script>var DT = {}; DT.fmtAge = function(ma){ return ma >= 1000 ? (ma / 1000).toFixed(1) + ' BILLION YEARS AGO' : Math.round(ma) + ' MILLION YEARS AGO'; };
''' + code + '''
(function(){ var cvs = [].slice.call(document.querySelectorAll('canvas[data-ev]')), t0 = performance.now(), last = 0;
  var loop = function(now){ requestAnimationFrame(loop); if (now - last < 33) return; last = now;
    cvs.forEach(function(cv){ var r = cv.getBoundingClientRect(); if (r.bottom < -40 || r.top > innerHeight + 40) return; try { DT.plateScene(cv, DT.TECT[cv.getAttribute('data-ev')][3], (now - t0) / 1000); } catch(e){} }); };
  requestAnimationFrame(loop); })();
</script></body></html>'''
open(os.path.join(ROOT, '_maplab', 'deeptime_lab.html'), 'w').write(html)
print('wrote _maplab/deeptime_lab.html', len(html) // 1024, 'KB')
