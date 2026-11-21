#!/usr/bin/env python3
"""RADIO's globe texture FROM OUR OWN MAP (user 2026-11-21: "you didnt use our map im realizing, where our detail"; then "the world and
the dots feel blurry and lack detail" -> z6, 16k). The site's world stack, composited the way the dark-family maps paint it (the ON
THEME recipe in index.html's storm plan): the sea #0e2956, our depth tint (bathy/world1, full), our sea-floor shading (seafloor/v1,
85%), the land #07080b (Natural Earth 1:10m mask), our land relief (relief/v1, full), lakes #174580. Tiles read at z6 (Web Mercator,
16384 px around), kept on disk as memmaps and resampled to equirectangular in bands, so it runs in a few GB of memory.
Out: OUT/globe_16k.jpg (16384x8192; WebP stops at 16383), globe_8k.webp, globe_4k.webp.
Run: python3 _radiobake/globe_tex.py NE_DIR OUT [TILE_CACHE]   (numpy, Pillow, scipy)
"""
import sys, os, io, json, math, concurrent.futures as cf, urllib.request
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage as ND
Image.MAX_IMAGE_PIXELS = None

CDN = 'https://cdn.bluishvoid.com'
# (path, query, opacity, shading gain). The GLOBE ONLY reads stronger than the map (user 2026-11-21: "will that show more earth detail
# from farther out?" -> "just do 1 and 3"): the land lifted off black with its relief shading x1.6, so ranges read from orbit, and the
# sea-floor shading full and x1.4, so ridges and trenches show. The street map keeps its own recipe.
LAYERS = [('bathy/world1', '', 1.0, 1.0), ('seafloor/v1', '?v=5', 1.0, 1.4), ('relief/v1', '?b=3', 1.0, 1.6)]
Z = 6
N = 256 * 2 ** Z
W, H = 16384, 8192
SEA, LANDC, LAKEC = (0x0e, 0x29, 0x56), (0x11, 0x13, 0x19), (0x17, 0x45, 0x80)   # land #111319: the map's #07080b, lifted
UA = {'User-Agent': 'BluishVoid/1.0 (globe bake)'}


def tile(url):
    for _ in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)
            b = r.read()
            return np.asarray(Image.open(io.BytesIO(b)).convert('RGBA')) if r.status == 200 and b else None
        except Exception:
            pass
    return None


def mosaic(path, q, cache):
    fn = os.path.join(cache, path.replace('/', '_') + '_z%d.u8' % Z)
    if os.path.exists(fn + '.done'):
        return np.memmap(fn, np.uint8, 'r', shape=(N, N, 4))
    M = np.memmap(fn, np.uint8, 'w+', shape=(N, N, 4))
    n = 2 ** Z
    for y in range(n):                                               # a row of tiles at a time
        urls = ['%s/%s/%d/%d/%d.webp%s' % (CDN, path, Z, x, y, q) for x in range(n)]
        with cf.ThreadPoolExecutor(16) as ex:
            for x, a in enumerate(ex.map(tile, urls)):
                if a is not None:
                    M[y * 256:(y + 1) * 256, x * 256:(x + 1) * 256] = a
        if y % 8 == 0:
            print('  ', path, 'row', y, flush=True)
    M.flush(); open(fn + '.done', 'w').close()
    return np.memmap(fn, np.uint8, 'r', shape=(N, N, 4))


def rings(g):
    t, c = g['type'], g['coordinates']
    return [c] if t == 'Polygon' else c if t == 'MultiPolygon' else []


def mask(path):
    im = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(im)
    for f in json.load(open(path))['features']:
        for poly in rings(f['geometry']):
            d.polygon([((q[0] + 180) / 360 * W, (90 - q[1]) / 180 * H) for q in poly[0]], fill=255)
            for h in poly[1:]:
                d.polygon([((q[0] + 180) / 360 * W, (90 - q[1]) / 180 * H) for q in h], fill=0)
    return np.asarray(im.filter(ImageFilter.GaussianBlur(0.7)))


def main():
    ne, out = sys.argv[1], sys.argv[2]
    cache = sys.argv[3] if len(sys.argv) > 3 else os.path.join(out, 'tiles')
    os.makedirs(out, exist_ok=True); os.makedirs(cache, exist_ok=True)
    mos = [mosaic(p, q, cache) for p, q, _, _ in LAYERS]
    land, lake = mask(os.path.join(ne, 'ne_10m_land.geojson')), mask(os.path.join(ne, 'ne_10m_lakes.geojson'))
    print('  masks done', flush=True)
    OUT = np.memmap(os.path.join(cache, 'out.u8'), np.uint8, 'w+', shape=(H, W, 3))
    xs = (np.arange(W) + .5) / W * N - .5
    BAND = 32
    for r0 in range(0, H, BAND):
        lat = 90 - (np.arange(r0, r0 + BAND) + .5) / H * 180
        inside = (np.abs(lat) <= 85.05)[:, None, None]
        lr = np.radians(np.clip(lat, -85.0511, 85.0511))
        my = (1 - np.log(np.tan(lr) + 1 / np.cos(lr)) / math.pi) / 2 * N - .5
        y0, y1 = max(0, int(np.floor(my.min())) - 1), min(N, int(np.ceil(my.max())) + 2)
        YY, XX = np.meshgrid(my - y0, xs, indexing='ij')
        img = np.empty((BAND, W, 3), np.float32); img[:] = np.array(SEA, np.float32) / 255
        for i, (_, _, op, gain) in enumerate(LAYERS):
            if i == 2:
                m = land[r0:r0 + BAND, :, None].astype(np.float32) / 255
                img = img * (1 - m) + np.array(LANDC, np.float32) / 255 * m
            src = np.asarray(mos[i][y0:y1]).astype(np.float32) / 255
            smp = np.stack([ND.map_coordinates(src[..., c], [YY, XX], order=1, mode='nearest') for c in range(4)], -1)
            a = np.clip(smp[..., 3:4] * gain, 0, 1) * op * inside
            img = img * (1 - a) + smp[..., :3] * a
        k = lake[r0:r0 + BAND, :, None].astype(np.float32) / 255
        img = img * (1 - k) + np.array(LAKEC, np.float32) / 255 * k
        OUT[r0:r0 + BAND] = np.clip(img * 255 + .5, 0, 255).astype(np.uint8)
        if r0 % 1024 == 0:
            print('  rows', r0, flush=True)
    OUT.flush()
    im = Image.fromarray(np.asarray(OUT))
    im.save(os.path.join(out, 'globe_16k.jpg'), quality=72, optimize=True, progressive=True)
    i8 = im.resize((8192, 4096), Image.LANCZOS); i8.save(os.path.join(out, 'globe_8k.webp'), quality=86, method=6)
    i8.resize((4096, 2048), Image.LANCZOS).save(os.path.join(out, 'globe_4k.webp'), quality=88, method=6)
    for k in ('16k.jpg', '8k.webp', '4k.webp'):
        print(k, os.path.getsize(os.path.join(out, 'globe_' + k)) // 1024, 'KB')


if __name__ == '__main__':
    main()
