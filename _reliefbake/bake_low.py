"""relief z3-4 over the NA bake's area, from the AWS Terrain Tiles (render_na.render_block, no 3DEP at this scale)"""
import os, sys, math
sys.path.insert(0, sys.argv[1])            # _reliefbake
import render as RD, render_na as RN
from bake import lonlat_tile
OUT = sys.argv[2]
RD.exaggeration = lambda z: 1.6 * 1.26 ** (12 - z)   # the same curve, uncapped below z5: z4 x10.2, z3 x12.8
W, S, E, N = -179.9, 7.0, -11.0, 84.0
made = 0
for z in (3, 4):
    x0, y1 = lonlat_tile(W, S, z); x1, y0 = lonlat_tile(E, N, z)
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for tx, ty, im, has in RN.render_block(z, x, y, 1, False):
                if im is None: continue
                p = os.path.join(OUT, str(z), str(tx), '%d.webp' % ty); os.makedirs(os.path.dirname(p), exist_ok=True)
                im.save(p, 'WEBP', quality=70, alpha_quality=70, method=4); made += 1
print('made', made)
