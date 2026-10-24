#!/usr/bin/env python3
"""OUR MAP OVER THE SATELLITE LOOP (2026-10-23, user: "do the same for the satellite loop").

The loop's frames are cut from NESDIS's full-disk GeoColor (bake.py), which has no lines in it. This draws the lines and
names the page lays over them: coastlines and country borders (Natural Earth 1:10m via world-atlas), state borders (US
Census 1:10m via us-atlas, the shared edges only, so the coast is not drawn twice), and the site's own place names (the
cityLbl list in index.html's BV_CONTINENTAL, plus the far regions' towns). One transparent PNG per sector at twice the
frame size, /satmaps/<sat>-<sector>.png, projected through fdgeo.py -- the same crops the frames are cut with.

    python3 _goesvid/satmaps_bake.py DATA_DIR      # DATA_DIR holds countries-10m.json and states-10m.json
Re-run after changing a crop in fdgeo.py or the names, and bump OVERLAY_V in bake.py and the page's ?v=.
"""
import json, os, re, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fdgeo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'satmaps')
S = 2            # the PNG is twice the frame
SS = 2           # drawn at twice that again and shrunk, for smooth lines
FONT = '/System/Library/Fonts/Helvetica.ttc'
FAR = [['Anchorage', 61.2181, -149.9003], ['Fairbanks', 64.8378, -147.7164], ['Juneau', 58.3019, -134.4197],
       ['Honolulu', 21.3069, -157.8583], ['Hilo', 19.7074, -155.0885], ['San Juan', 18.4655, -66.1057],
       ['Seattle', 47.6062, -122.3321], ['Portland', 45.5152, -122.6784], ['Denver', 39.7392, -104.9903],
       ['Miami', 25.7617, -80.1918], ['Atlanta', 33.749, -84.388]]   # no Minneapolis: it sits on Cosmos at continental scale


def topo(path):
    t = json.load(open(path))
    sc, tr = t['transform']['scale'], t['transform']['translate']
    arcs = []
    for a in t['arcs']:
        x = y = 0; pts = []
        for dx, dy in a:
            x += dx; y += dy
            pts.append((x * sc[0] + tr[0], y * sc[1] + tr[1]))
        arcs.append(pts)
    return t, arcs


def arc_uses(geoms):
    """how many geometries use each arc: 2 = a shared border, 1 = a coast or the outer edge"""
    n = {}
    def walk(a):
        if isinstance(a, int): n[a if a >= 0 else ~a] = n.get(a if a >= 0 else ~a, 0) + 1
        else:
            for b in a: walk(b)
    for g in geoms: walk(g.get('arcs', []))
    return n


def city_labels():
    """index.html's BV_CONTINENTAL.cityLbl, read out of the page so the two maps name the same places"""
    src = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    j = src.index('cityLbl:', src.index('window.BV_CONTINENTAL = {'))
    block = re.sub(r'/\*.*?\*/', '', src[j:j + 12000], flags=re.S)
    block = block[:re.search(r'\]\s*,\s*\n\s*[A-Za-z_]+\s*:', block).end()]
    return [[m.group(1), float(m.group(2)), float(m.group(3)), m.group(4)]
            for m in re.finditer(r"\[\s*'([^']+)'\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*(?:,\s*'(\w+)')?\s*\]", block)]


def main():
    data = sys.argv[1]
    os.makedirs(OUT, exist_ok=True)
    ct, carcs = topo(os.path.join(data, 'countries-10m.json'))
    st, sarcs = topo(os.path.join(data, 'states-10m.json'))
    cuse = arc_uses(ct['objects']['countries']['geometries'])
    suse = arc_uses(st['objects']['states']['geometries'])
    coast = [carcs[i] for i in range(len(carcs)) if cuse.get(i) == 1]
    borders = [carcs[i] for i in range(len(carcs)) if cuse.get(i, 0) >= 2]
    states = [sarcs[i] for i in range(len(sarcs)) if suse.get(i, 0) >= 2]
    # 2026-10-24: no names in the image any more -- the page draws our map's own names live, one size at any zoom
    names = []
    # d: desktop, twice the frame; m: phones, which show the frame about 630 CSS px wide (cover-fit in a near-square box),
    # so the same frame size with type and lines about 2.5x heavier relative to it
    for var, S, FS, LW in (('', 2, 35, 1.0), ('-m', 1, 25, 2.2)):
      W, H = fdgeo.OUT_W * S * SS, fdgeo.OUT_H * S * SS
      for (sat, sector) in fdgeo.SECTORS:
          im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
          d = ImageDraw.Draw(im)
          def line(arcs, width, rgba, halo):
              segs = []
              w0, e0, s0, n0 = fdgeo.SECTORS[(sat, sector)]
              pad = max(e0 - w0, n0 - s0) * 0.6
              for a in arcs:
                  if not any(s0 - pad < la < n0 + pad and (w0 - pad < lo < e0 + pad or w0 - pad < lo - 360 < e0 + pad) for lo, la in a[::max(1, len(a) // 12)] + a[-1:]):
                      continue
                  cur = []
                  for lo, la in a:
                      p = fdgeo.to_out(la, lo, sat, sector, S * SS)
                      if p is None or not (-W < p[0] < 2 * W and -H < p[1] < 2 * H):
                          if len(cur) > 1: segs.append(cur)
                          cur = []; continue
                      cur.append(p)
                  if len(cur) > 1: segs.append(cur)
              for sgm in segs: d.line(sgm, fill=(0, 0, 0, halo), width=width + int(1.5 * SS * S * LW), joint='curve')
              for sgm in segs: d.line(sgm, fill=rgba, width=width, joint='curve')
          u = SS * S * LW
          # 2026-10-24 (user): no state or country lines -- most of them follow rivers, and the line hid the valley fog on them
          line(coast, int(1.2 * u), (255, 255, 255, 150), 55)
          im = im.resize((fdgeo.OUT_W * S, fdgeo.OUT_H * S), Image.LANCZOS)
          d = ImageDraw.Draw(im)
          fs = FS
          font = ImageFont.truetype(FONT, fs, index=1)
          for nm, la, lo, _ in names:
              p = fdgeo.to_out(la, lo, sat, sector, S)
              if not p or not (8 < p[0] < im.width - 8 and 8 < p[1] < im.height - 8): continue
              r = 2.2 * S * (1 + (LW - 1) * 0.6)
              d.ellipse((p[0] - r - 1.5 * S, p[1] - r - 1.5 * S, p[0] + r + 1.5 * S, p[1] + r + 1.5 * S), fill=(8, 10, 16, 220))
              d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=(255, 255, 255, 255))
              d.text((p[0] + r + 5 * S, p[1]), nm, font=font, fill=(255, 255, 255, 240), anchor='lm',
                     stroke_width=max(2, int(1.6 * S * (1 + (LW - 1) * 0.6))), stroke_fill=(8, 10, 16, 215))
          out = os.path.join(OUT, '%s-%s%s.png' % (sat, sector, var))
          im.quantize(64, method=Image.FASTOCTREE).save(out, optimize=True)   # 64-colour palette PNG: 1/5 the bytes, the same look
          print(sat, sector + var, os.path.getsize(out) // 1024, 'KB')


if __name__ == '__main__':
    main()
