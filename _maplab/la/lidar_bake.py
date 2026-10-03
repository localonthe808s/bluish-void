#!/usr/bin/env python3
"""
THE BASIN AT ONE METRE (2026-10-02; user: "do the lidar rebake"). The finest land relief was the 1/3 arc-second
3DEP tier, ~10 m a pixel, so past ~9 m/px the map only enlarged it and at street level it lay across the blocks as
soft blotches (it is faded out there since c29775b2). 3DEP's dynamic service answers with true 1 m lidar over the
whole home frame -- measured on Griffith Park: pixel size 1.0 m, 98% of neighbouring pixels differ, smooth second
differences (not a coarse model resampled).

This bakes HOME_LAND (la_bake.py) at 1 m in 0.01-degree tiles (1,113 x 1,113 px, square in degrees -- see px_of), shaded with land_image's own
recipe -- three suns, the same light and shade alpha, 32 steps -- so a tile is the 1/3" tier with the detail put
back. Each tile is pulled with a MARGIN and cropped after shading: the gradient and the 0.8 px smoothing are
one-sided at an edge, which would rule a faint grid across the hills. Tiles that are all sea are skipped; a flat
basin tile is still written (it is nearly empty), because a 1 m tile CLEARS the coarser tiers under it in the lab's
exclusive relief list -- leaving it out would let the 10 m blotches show through on the flats.

Output: hs1m/r{row}c{col}.png (gitignored; uploaded to R2 la/hs1m/v1/) and land1m_index.json (compact: the grid
and the list of tiles present; the lab expands it). Resumable: a tile on disk is kept, sea tiles are remembered in
hs1m/_sea.txt. Three requests in flight -- USGS is a public service.

    python3 lidar_bake.py            # bake (hours)
    python3 lidar_bake.py --index    # rewrite the index from what is on disk
    python3 lidar_bake.py --one 34.125 -118.30   # the tile holding that point, for a look
"""
import concurrent.futures as cf, io, json, math, os, sys, time, urllib.parse, urllib.request
import numpy as np
from scipy import ndimage
import tifffile
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
# TWO REGIONS (2026-10-03, NYC added: user chose to bake the shading INTO the CITY pyramid). `--region nyc` bakes the
# five boroughs' 1 m relief for the lab's city view; only tiles touching a borough are pulled (the frame is mostly
# water and New Jersey, which the CITY map draws dark).
REGION = sys.argv[sys.argv.index('--region') + 1] if '--region' in sys.argv else 'la'
if REGION == 'nyc':
    HERE = os.path.join(os.path.dirname(HERE), 'bathy')
OUT = os.path.join(HERE, 'nyc_hs1m' if REGION == 'nyc' else 'hs1m')
SRC = 'https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage'
W0, S0, D = -118.85, 33.69, 0.01                  # HOME_LAND's south-west corner, tile size in degrees
NC, NR = 90, 66                                     # to -117.95 E, 34.35 N (HOME_LAND reaches 34.346)
if REGION == 'nyc':
    W0, S0, NC, NR = -74.26, 40.49, 57, 43          # Tottenville to Glen Oaks, Great Kills to Riverdale
M = 48 if REGION == 'nyc' else 6                    # margin pixels each side, cropped after shading (NYC: > 3 x its 16 px smoothing)
ZFAC = 1.0                                          # the 1/3" tier's own
BASE = 'https://cdn.bluishvoid.com/%s/lidar/v1/' % REGION   # + hs1m/ hs2m/ hs4m/
INDEX = 'nyc_land1m_index.json' if REGION == 'nyc' else 'land1m_index.json'


def borough_tiles():
    """NYC only: the (r, c) whose box touches a borough. bathy/nyc_boroughs.json keeps each landmass as its own ring
    (the ring trap in ink_pyramid_bake.py), so every ring is unioned as a polygon of its own."""
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    polys = []
    for f in json.load(open(os.path.join(HERE, 'nyc_boroughs.json')))['features']:
        g = f['geometry']
        for part in (g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]):
            for ring in part:
                if len(ring) >= 4:
                    pg = Polygon(ring).buffer(0)
                    if pg.area > 0: polys.append(pg)
    U = unary_union(polys)
    return set((r, c) for r in range(NR) for c in range(NC) if U.intersects(box(*box_of(r, c))))


def box_of(r, c):
    w, s = W0 + c * D, S0 + r * D
    return w, s, w + D, s + D


def px_of(box):
    """SQUARE IN DEGREES, or the server moves the box. ArcGIS exportImage keeps square pixels in the request's
    spatial reference and quietly widens the extent to fit: the first pass asked 922 x 1,113 px for a 0.01 x 0.01
    degree tile and every tile came back stretched about 20% north-south (adjacent tiles' shared margin disagreed by
    22 m of elevation). One pixel per 1/111,300 degree both ways: 1 m north-south, ~0.83 m east-west here."""
    w, s, e, n = box
    k = int(round((n - s) * 111320))
    return int(round((e - w) / (n - s) * k)), k


def pull(box, size):
    w, s, e, n = box
    q = {'bbox': '%f,%f,%f,%f' % box, 'bboxSR': 4326, 'imageSR': 4326, 'size': '%d,%d' % size,
         'format': 'tiff', 'pixelType': 'F32', 'noData': -9999, 'interpolation': 'RSP_BilinearInterpolation', 'f': 'image'}
    for k in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(SRC + '?' + urllib.parse.urlencode(q),
                                       headers={'User-Agent': 'bluishvoid.com LA relief bake'}), timeout=300).read()
            return tifffile.imread(io.BytesIO(b)).astype('float32')
        except Exception as ex:
            time.sleep(10 * (k + 1))
            last = ex
    raise RuntimeError('pull failed %s: %s' % (box, last))


def shade(a, box):
    """land_image's recipe, returning the 2-channel (L, A) array; same constants."""
    w, s, e, n = box
    H, Wd = a.shape
    land = a > 0.5
    my = (n - s) / H * 111320.0
    mx = (e - w) / Wd * 111320.0 * math.cos(math.radians((s + n) / 2))
    a0 = np.where(a < -9000, 0, np.clip(a, 0, None))
    if REGION != 'nyc':
        g = ndimage.gaussian_filter(a0, 0.8)
    else:
        # THE CITY'S BARE EARTH IS FACETED. The 3DEP model removes every building and fills its footprint with flat
        # triangles, so a plain hillshade draws a field of shards across every block (seen at Inwood, 2026-10-03).
        # Smooth by TERRAIN: broadly (14 px) where the ground is flat at a 16 px scale, the 1 m detail (1.2 px) blended
        # back in where it really slopes, 5-12 degrees -- Inwood Hill's cliffs, the moraine, Todt Hill stay crisp.
        g_lo, g_hi = ndimage.gaussian_filter(a0, 1.2), ndimage.gaussian_filter(a0, 14)
        sy, sx = np.gradient(ndimage.gaussian_filter(a0, 16), my, mx)
        wt = ndimage.gaussian_filter(np.clip((np.degrees(np.arctan(np.hypot(sx, sy))) - 5) / 7, 0, 1), 6)
        g = g_hi + wt * (g_lo - g_hi)
    gy, gx = np.gradient(g * ZFAC, my, mx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(gy, -gx)
    alt = math.radians(45)
    hs = np.zeros_like(g)
    for az_deg, wt in ((315, 0.6), (270, 0.2), (0, 0.2)):
        az = math.radians(az_deg)
        hs += wt * (math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(az - math.pi / 2 - aspect))
    sh = hs / math.sin(alt) - 1.0
    dark = np.clip(-sh, 0, 1) * 0.62
    lite = np.clip(sh / 0.41, 0, 1) * 0.30
    alpha = np.where(sh < 0, dark, lite) * land
    alpha = np.round(alpha * 255 / 8) * 8
    alpha[alpha < 10] = 0
    out = np.zeros((H, Wd, 2), 'uint8')
    out[..., 0] = np.where(sh < 0, 0, 255)
    out[..., 0][alpha == 0] = 0
    out[..., 1] = np.clip(alpha, 0, 255)
    return out, land


def bake_tile(r, c):
    name = 'r%02dc%02d.png' % (r, c)
    p = os.path.join(OUT, name)
    if os.path.exists(p):
        return name, 'kept'
    box = box_of(r, c)
    pw, ph = px_of(box)
    # the pull with its margin: the same metres per pixel, M pixels wider each side
    dx, dy = (box[2] - box[0]) / pw, (box[3] - box[1]) / ph
    big = (box[0] - M * dx, box[1] - M * dy, box[2] + M * dx, box[3] + M * dy)
    a = pull(big, (pw + 2 * M, ph + 2 * M))
    la, land = shade(a, big)
    la, land = la[M:-M, M:-M], land[M:-M, M:-M]
    if land.mean() < 0.002:
        return name, 'sea'
    tmp = p + '.part'
    Image.fromarray(la).save(tmp, format='PNG', optimize=True)
    os.replace(tmp, p)
    return name, '%d KB' % (os.path.getsize(p) // 1024)


# THE PYRAMID. A 1 m tile is ~255 KB and a view at 10 m/px spans ~120 of them (30 MB), so the 1 m tiles are
# averaged into 2 m and 4 m levels (2 x 2 and 4 x 4 tiles each, the same ~920 x 1,110 px a file) and each level
# draws only in its own band of scale: any view then needs about 4-9 files. Averaged PREMULTIPLIED -- a pixel is
# light (L 255) or shade (L 0) with an alpha, so a mixed block becomes a grey with the summed weight, which the
# canvas draws exactly as the four would have looked from that far.
LEVELS = [(4, 6, 12), (2, 3, 6), (1, 0, 3)]          # (metres a pixel, minMpp, maxMpp), coarse first: the lab draws in order
if REGION == 'nyc':                                   # the CITY pyramid is baked at every scale down from 70 m/px
    LEVELS = [(16, 24, 1e9), (4, 6, 24), (2, 3, 6), (1, 0, 3)]


def level_dir(k):
    return OUT if k == 1 else os.path.join(HERE, ('nyc_hs%dm' if REGION == 'nyc' else 'hs%dm') % k)


def build_level(k):
    src = 1 if k <= 4 else k // 4                        # 16 m is built from 4 m: from 1 m it would be a 17,808 px mosaic
    SRC = level_dir(src)
    os.makedirs(level_dir(k), exist_ok=True)
    have = set(f[:-4] for f in os.listdir(SRC) if f.endswith('.png'))
    NRs, NCs = (NR + src - 1) // src, (NC + src - 1) // src
    k_out, k = k, k // src                                # k is now the fan-in from the source level
    made = 0
    for R in range((NRs + k - 1) // k):
        for C in range((NCs + k - 1) // k):
            name = 'r%02dc%02d' % (R, C)
            p = os.path.join(level_dir(k_out), name + '.png')
            kids = [(R * k + i, C * k + j) for i in range(k) for j in range(k)]
            if not any('r%02dc%02d' % kc in have for kc in kids):
                continue
            if os.path.exists(p):
                made += 1; continue
            th, tw = 1113, 1113                                  # a 1 m tile's size: square in degrees (px_of)
            col = np.zeros((th * k, tw * k), 'float32'); alp = np.zeros_like(col)
            for i in range(k):
                for j in range(k):
                    rr, cc = R * k + i, C * k + j
                    f = os.path.join(SRC, 'r%02dc%02d.png' % (rr, cc))
                    if not os.path.exists(f):
                        continue
                    im = np.asarray(Image.open(f).convert('LA').resize((tw, th))).astype('float32')
                    a = im[..., 1] / 255.0
                    y0 = (k - 1 - i) * th                         # row 0 is the SOUTH row; images run north-down
                    alp[y0:y0 + th, j * tw:(j + 1) * tw] = a
                    col[y0:y0 + th, j * tw:(j + 1) * tw] = im[..., 0] * a
            sa = alp.reshape(th, k, tw, k).mean(axis=(1, 3))
            sc = col.reshape(th, k, tw, k).mean(axis=(1, 3))
            L = np.where(sa > 0, sc / np.maximum(sa, 1e-6), 0)
            out = np.zeros((th, tw, 2), 'uint8')
            out[..., 0] = np.clip(np.round(L), 0, 255)
            out[..., 1] = np.clip(np.round(sa * 255 / 4) * 4, 0, 255)
            Image.fromarray(out).save(p + '.part', format='PNG', optimize=True); os.replace(p + '.part', p)
            made += 1
    print('level %d m: %d tiles' % (k_out, made), flush=True)


def write_index():
    levels = []
    for k in sorted(k for k, _, _ in LEVELS if k != 1):      # finest first: the 16 m level is built FROM the 4 m one
        build_level(k)
    for k, lo, hi in LEVELS:
        tiles = sorted(f[:-4] for f in os.listdir(level_dir(k)) if f.endswith('.png'))
        levels.append({'base': '%shs%dm/' % (BASE, k), 'd': D * k, 'minMpp': lo, 'maxMpp': hi, 'tiles': tiles})
    doc = {'w0': W0, 's0': S0, 'levels': levels,
           'note': '3DEP 1 m lidar hillshade (la/lidar_bake.py), averaged to 2 m and 4 m; tile rRRcCC spans w0+C*d..+d, s0+R*d..+d'}
    with open(os.path.join(HERE, INDEX), 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('index: %s' % ', '.join('%d m %d' % (k, len(l['tiles'])) for (k, _, _), l in zip(LEVELS, levels)))


def main():
    os.makedirs(OUT, exist_ok=True)
    if '--index' in sys.argv:
        return write_index()
    if '--one' in sys.argv:
        i = sys.argv.index('--one'); lat, lon = float(sys.argv[i + 1]), float(sys.argv[i + 2])
        print(bake_tile(int((lat - S0) / D), int((lon - W0) / D)))
        return
    seaf = os.path.join(OUT, '_sea.txt')
    sea = set(open(seaf).read().split()) if os.path.exists(seaf) else set()
    keep = borough_tiles() if REGION == 'nyc' else None
    todo = [(r, c) for r in range(NR) for c in range(NC)
            if (keep is None or (r, c) in keep) and 'r%02dc%02d' % (r, c) not in sea and not os.path.exists(os.path.join(OUT, 'r%02dc%02d.png' % (r, c)))]
    print('%d tiles to bake (%d done, %d sea)' % (len(todo), NR * NC - len(todo) - len(sea), len(sea)), flush=True)
    t0, done = time.time(), 0
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(bake_tile, r, c): (r, c) for r, c in todo}
        for fu in cf.as_completed(futs):
            done += 1
            try:
                name, what = fu.result()
            except Exception as e:
                print('FAILED %s: %s' % (futs[fu], e), flush=True); continue
            if what == 'sea':
                with open(seaf, 'a') as f: f.write(name[:-4] + '\n')
            if done % 25 == 0 or done == len(todo):
                el = time.time() - t0
                print('%d/%d  %.0f min, ~%.0f min left  (last %s %s)' % (done, len(todo), el / 60, el / done * (len(todo) - done) / 60, name, what), flush=True)
    write_index()


if __name__ == '__main__':
    main()
