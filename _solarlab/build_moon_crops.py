#!/usr/bin/env python3
"""Find each moon's disc inside its NASA frame.

These are science-release images: the moon is often a small bright blob on a
large black field, sometimes with captions or a scale bar baked in. Dropping
them straight into a circular clip yields a black disc with a speck in it, so
we measure where the disc actually is and hand the lab a crop.

Emits fx, fy (disc centre as a fraction of width/height), fr (disc radius as a
fraction of width) and the image aspect.
"""
import re, io, json, urllib.request
from PIL import Image

s = open('/Users/vvvaa/bluish-void/_solarlab/solar_lab.html').read()
i = s.index('var MOON_IMG'); blk = s[i:s.index('};', i)]
imgs = re.findall(r"(\w+):'([^']+)'", blk)

def largest_blob(im, thr):
    """Biggest connected run of pixels brighter than thr (iterative flood fill)."""
    w, h = im.size
    px = im.load()
    seen = bytearray(w*h)
    best = None
    for sy in range(0, h, 2):
        for sx in range(0, w, 2):
            if seen[sy*w+sx] or px[sx, sy] <= thr:
                continue
            stack = [(sx, sy)]; seen[sy*w+sx] = 1
            minx = maxx = sx; miny = maxy = sy; area = 0
            while stack:
                x, y = stack.pop(); area += 1
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
                for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                    nx, ny = x+dx, y+dy
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny*w+nx] and px[nx, ny] > thr:
                        seen[ny*w+nx] = 1; stack.append((nx, ny))
            if best is None or area > best[0]:
                best = (area, minx, miny, maxx, maxy)
    return best

out = {}
for name, url in imgs:
    try:
        raw = urllib.request.urlopen(url, timeout=45).read()
        im0 = Image.open(io.BytesIO(raw)).convert('L')
    except Exception as e:
        print('%-11s FETCH FAIL %s' % (name, e)); continue
    W0, H0 = im0.size
    scale = 360.0 / max(W0, H0)
    im = im0.resize((max(1,int(W0*scale)), max(1,int(H0*scale))))
    w, h = im.size
    hist = im.histogram()
    # threshold above the black sky floor but below the lit surface
    thr = 18
    b = largest_blob(im, thr)
    if not b:
        print('%-11s no blob' % name); continue
    area, minx, miny, maxx, maxy = b
    bw, bh = maxx-minx+1, maxy-miny+1
    cx, cy = (minx+maxx)/2.0, (miny+maxy)/2.0
    r = max(bw, bh)/2.0
    out[name] = dict(fx=round(cx/w, 4), fy=round(cy/h, 4),
                     fr=round(r/w, 4), aspect=round(H0/float(W0), 4),
                     fill=round((bw*bh)/float(w*h), 3))
    print('%-11s %4dx%-4d disc centre (%.3f,%.3f)  r=%.3f of width  covers %.0f%% of frame'
          % (name, W0, H0, cx/w, cy/h, r/w, out[name]['fill']*100))
json.dump(out, open('moon_crops.json','w'), indent=1)
print('\nmeasured', len(out), 'of', len(imgs))
