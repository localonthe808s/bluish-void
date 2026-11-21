#!/usr/bin/env python3
"""RADIO's globe texture FROM OUR OWN MAP (user 2026-11-21: "you didnt use our map im realizing, where our detail"): the site's
world stack, composited the way the dark-family maps paint it (the ON THEME recipe in index.html's storm plan): the sea
#0e2956, our depth tint (bathy/world1, full), our sea-floor shading (seafloor/v1, 85%), the land #07080b (Natural Earth 1:50m
mask), our land relief (relief/v1, full), lakes #174580. Tiles read at z5 (Web Mercator, 8192 px around) and resampled to
equirectangular. Beyond Mercator's 85 deg the plain colors carry on.
Out: OUT/globe_{8k,4k}.webp. Run: python3 _radiobake/globe_tex.py NE_DIR OUT [TILE_CACHE]   (numpy, Pillow, scipy)
"""
import sys, os, io, json, math, concurrent.futures as cf, urllib.request
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ND

CDN = 'https://cdn.bluishvoid.com'
LAYERS = [('bathy/world1', '', 1.0), ('seafloor/v1', '?v=5', 0.85), ('relief/v1', '?b=3', 1.0)]
Z = 5
SEA, LANDC, LAKEC = (0x0e, 0x29, 0x56), (0x07, 0x08, 0x0b), (0x17, 0x45, 0x80)
UA = {'User-Agent': 'BluishVoid/1.0 (globe bake)'}


def tile(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)
        b = r.read()
        return Image.open(io.BytesIO(b)).convert('RGBA') if r.status == 200 and b else None
    except Exception:
        return None


def mosaic(path, q, cache):
    n = 2 ** Z
    fn = os.path.join(cache, path.replace('/', '_') + '_z%d.png' % Z)
    if os.path.exists(fn):
        return np.asarray(Image.open(fn)).astype(np.float32) / 255
    M = Image.new('RGBA', (256 * n, 256 * n), (0, 0, 0, 0))
    jobs = {(x, y): '%s/%s/%d/%d/%d.webp%s' % (CDN, path, Z, x, y, q) for x in range(n) for y in range(n)}
    with cf.ThreadPoolExecutor(16) as ex:
        for (x, y), im in zip(jobs, ex.map(tile, jobs.values())):
            if im is not None:
                M.paste(im, (x * 256, y * 256))
    M.save(fn)
    print(' ', path, 'mosaic done', flush=True)
    return np.asarray(M).astype(np.float32) / 255


def rings(g):
    t, c = g['type'], g['coordinates']
    return [c] if t == 'Polygon' else c if t == 'MultiPolygon' else []


def mask(path, W, H):
    im = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(im)
    for f in json.load(open(path))['features']:
        for poly in rings(f['geometry']):
            d.polygon([((q[0] + 180) / 360 * W, (90 - q[1]) / 180 * H) for q in poly[0]], fill=255)
            for h in poly[1:]:
                d.polygon([((q[0] + 180) / 360 * W, (90 - q[1]) / 180 * H) for q in h], fill=0)
    return np.asarray(im.filter(__import__('PIL.ImageFilter', fromlist=['x']).GaussianBlur(0.7))).astype(np.float32)[..., None] / 255


def main():
    ne, out = sys.argv[1], sys.argv[2]
    cache = sys.argv[3] if len(sys.argv) > 3 else os.path.join(out, 'tiles')
    os.makedirs(out, exist_ok=True); os.makedirs(cache, exist_ok=True)
    W, H = 8192, 4096
    lat = 90 - (np.arange(H) + .5) / H * 180
    lr = np.radians(np.clip(lat, -85.0511, 85.0511))
    my = (1 - np.log(np.tan(lr) + 1 / np.cos(lr)) / math.pi) / 2 * (256 * 2 ** Z) - .5   # mercator row for each output row
    mxv = (np.arange(W) + .5) / W * (256 * 2 ** Z) - .5
    YY, XX = np.meshgrid(my, mxv, indexing='ij')
    inside = (np.abs(lat) <= 85.05)[:, None, None]
    img = np.empty((H, W, 3), np.float32); img[:] = np.array(SEA, np.float32) / 255
    def over(rgba, op):
        out_ = np.empty((H, W, 4), np.float32)
        for c in range(4):
            out_[..., c] = ND.map_coordinates(rgba[..., c], [YY, XX], order=1, mode='nearest')
        a = out_[..., 3:4] * op * inside
        img[:] = img * (1 - a) + out_[..., :3] * a
    for i, (p, q, op) in enumerate(LAYERS):
        rgba = mosaic(p, q, cache)
        if i == 2:                                                   # the land goes down before its relief
            m = mask(os.path.join(ne, 'ne_50m_land.geojson'), W, H)
            img[:] = img * (1 - m) + np.array(LANDC, np.float32) / 255 * m
        over(rgba, op); del rgba
        print(' ', p, 'laid', flush=True)
    lk = mask(os.path.join(ne, 'ne_50m_lakes.geojson'), W, H)
    img[:] = img * (1 - lk) + np.array(LAKEC, np.float32) / 255 * lk
    im = Image.fromarray(np.clip(img * 255 + .5, 0, 255).astype(np.uint8))
    im.save(os.path.join(out, 'globe_8k.webp'), quality=86, method=6)
    im.resize((4096, 2048), Image.LANCZOS).save(os.path.join(out, 'globe_4k.webp'), quality=88, method=6)
    for k in ('8k', '4k'):
        print(k, os.path.getsize(os.path.join(out, 'globe_%s.webp' % k)) // 1024, 'KB')


if __name__ == '__main__':
    main()
