#!/usr/bin/env python3
"""THE CEMETERY AS IT IS PHOTOGRAPHED (2026-11-12, user: "those are a mess, thats not the real order" -> "Show the photo itself"): the
detected stones could not keep the real rows, so at close zoom the cemetery shows New York State's own orthophoto (NYS ITS Geospatial
Services, orthos.its.ny.gov, ~25-30 cm), clipped to the OSM cemetery outline and transparent outside it, as z16-19 webp tiles.

    python3 _cembake/photo_tiles.py <out dir> <ortho dir>:<osm.json> [<ortho dir>:<osm.json> ...]
    then: rclone copy <out dir> r2:bluishvoid-bg/cem/albany/ --s3-no-check-bucket --header-upload "Content-Type: image/webp"
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw
Image.MAX_IMAGE_PIXELS = None
OUT = sys.argv[1]; R = 6378137; PR = math.pi * R
mx = lambda lon: math.radians(lon) * R; my = lambda lat: R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
src = []
for arg in sys.argv[2:]:
    od, osm = arg.split(':')
    X0, Y1, RES, T, nx, ny = open(os.path.join(od, 'grid.txt')).read().split(); X0, Y1, RES = float(X0), float(Y1), float(RES); T, nx, ny = int(T), int(nx), int(ny)
    im = Image.new('RGB', (nx * T, ny * T))
    for j in range(ny):
        for i in range(nx): im.paste(Image.open(os.path.join(od, 't_%d_%d.png' % (i, j))).convert('RGB'), (i * T, j * T))
    cem = [e for e in json.load(open(osm))['elements'] if e.get('tags', {}).get('landuse') == 'cemetery'][0]
    poly = [(mx(g['lon']), my(g['lat'])) for g in cem['geometry']]
    src.append(dict(im=im, X0=X0, Y1=Y1, RES=RES, poly=poly))
    print('mosaic', od, im.size)
xs = [p[0] for s in src for p in s['poly']]; ys = [p[1] for s in src for p in s['poly']]
n = 0
for z in range(16, 20):
    size = 2 * PR / 2 ** z
    tx0, tx1 = int((min(xs) + PR) // size), int((max(xs) + PR) // size); ty0, ty1 = int((PR - max(ys)) // size), int((PR - min(ys)) // size)
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            bx0 = -PR + tx * size; by1 = PR - ty * size
            tile = Image.new('RGBA', (256, 256), (0, 0, 0, 0)); any_ = False
            for s in src:
                mask = Image.new('L', (256, 256), 0)
                ImageDraw.Draw(mask).polygon([((x - bx0) / size * 256, (by1 - y) / size * 256) for x, y in s['poly']], fill=255)
                if not mask.getbbox(): continue
                # exact float edges (Image.transform EXTENT), so neighbouring tiles meet without a rounding seam
                c = s['im'].transform((256, 256), Image.EXTENT, ((bx0 - s['X0']) / s['RES'], (s['Y1'] - by1) / s['RES'], (bx0 + size - s['X0']) / s['RES'], (s['Y1'] - by1 + size) / s['RES']), Image.BICUBIC)
                tile.paste(c, (0, 0), mask); any_ = True
            if not any_: continue
            d = os.path.join(OUT, str(z), str(tx)); os.makedirs(d, exist_ok=True)
            tile.save(os.path.join(d, '%d.webp' % ty), quality=78, method=5); n += 1
    print('z', z, 'tiles so far', n)
print('bounds lon/lat', [round(min(xs) / R * 180 / math.pi, 5), round((2 * math.atan(math.exp(min(ys) / R)) - math.pi / 2) * 180 / math.pi, 5), round(max(xs) / R * 180 / math.pi, 5), round((2 * math.atan(math.exp(max(ys) / R)) - math.pi / 2) * 180 / math.pi, 5)])
