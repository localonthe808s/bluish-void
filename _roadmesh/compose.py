"""Composite baked mesh tiles over a page capture, to judge the look.

Usage: python compose.py TILEDIR_OR_URL BASE.png OUT.png --z 7 --dpr 2 \
           --anchor LON LAT PX PY
TILEDIR_OR_URL is a local {z}/{x}/{y}.webp tree or an https URL prefix.
The anchor pins one geographic point to a device pixel of the capture
(default: NYC City Hall, as placed in tr_base.png).
"""
import argparse, io, math, os, urllib.request
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument('tiles'); ap.add_argument('base'); ap.add_argument('out')
ap.add_argument('--z', type=int, default=7)
ap.add_argument('--dpr', type=float, default=2.0)
ap.add_argument('--anchor', type=float, nargs=4, default=[-74.006, 40.7128, 1213.4, 903.6])
a = ap.parse_args()

base = Image.open(a.base).convert('RGBA')
W, H = base.size
z, s = a.z, a.dpr
lon, lat, px, py = a.anchor
wx = (lon + 180) / 360 * 256 * (1 << z)
wy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 256 * (1 << z)
ox, oy = wx - px / s, wy - py / s          # css world px at the capture's top-left
tx0, ty0 = int(ox // 256), int(oy // 256)
tx1, ty1 = int((ox + W / s) // 256), int((oy + H / s) // 256)
T = int(round(256 * s))                    # one tile in device px
mos = Image.new('RGBA', ((tx1 - tx0 + 1) * T, (ty1 - ty0 + 1) * T))
for tx in range(tx0, tx1 + 1):
    for ty in range(ty0, ty1 + 1):
        src = '%s/%d/%d/%d.webp' % (a.tiles.rstrip('/'), z, tx, ty)
        try:
            if src.startswith('http'):
                req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0 (roadmesh compose)'})  # Cloudflare 403s urllib's UA
                im = Image.open(io.BytesIO(urllib.request.urlopen(req).read()))
            elif os.path.exists(src):
                im = Image.open(src)
            else:
                continue
        except Exception as e:
            print('miss', src, e)
            continue
        im = im.convert('RGBA')
        if im.size != (T, T):
            im = im.resize((T, T), Image.LANCZOS if im.width > T else Image.BILINEAR)
        mos.paste(im, ((tx - tx0) * T, (ty - ty0) * T))
cx, cy = int(round((ox - tx0 * 256) * s)), int(round((oy - ty0 * 256) * s))
layer = mos.crop((cx, cy, cx + W, cy + H))
Image.alpha_composite(base, layer).convert('RGB').save(a.out)
print('wrote', a.out, 'tiles', tx0, tx1, ty0, ty1)
