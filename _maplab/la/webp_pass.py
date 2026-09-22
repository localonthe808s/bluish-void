"""Re-encode the heavy LA raster tiers as lossless WebP and point the index files at them.

Run after la_bake.py. The 3" sea/veg/land tiers are the three biggest files THE BASIN
loads on open (3.4 MB as PNG, 2.0 MB as lossless WebP, pixel-identical where alpha > 0;
measured 2026-09-21). The bake still writes PNG; this pass is idempotent.
"""
import json, os, sys
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
TIERS = ['sea_3as', 'veg_3as', 'land_3as']
for base in TIERS:
    png = os.path.join(HERE, base + '.png')
    if not os.path.exists(png): continue
    im = Image.open(png).convert('RGBA')
    im.save(os.path.join(HERE, base + '.webp'), 'WEBP', lossless=True, quality=100, method=6)
    print(base, os.path.getsize(png) // 1024, '->', os.path.getsize(os.path.join(HERE, base + '.webp')) // 1024, 'KB')
for idx in ['sea_index.json', 'veg_index.json', 'land_index.json']:
    p = os.path.join(HERE, idx); j = json.load(open(p)); n = 0
    for e in j:
        if e['img'].endswith('_3as.png'): e['img'] = e['img'][:-4] + '.webp'; n += 1
    json.dump(j, open(p, 'w'), separators=(',', ':')); print(idx, n, 'entries -> webp')
