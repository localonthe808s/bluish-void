"""Bake the national ROAD MESH overlay: transparent WebP tiles (256 display px, 512 px images), z4-9.

Reads our own Protomaps basemap (a local copy of
r2:bluishvoid-bg/basemap/bluish-basemap-20260829.pmtiles), keeps the 'roads'
layer's motorway / trunk / primary / secondary / tertiary lines, and draws them in
the traffic tab's style (dark casing under a #05DB32 core) so the wide view shows
the road network without paying for TomTom flow tiles. TomTom keeps drawing jams
on top in the page.

Usage:
  python bake.py PMTILES OUTDIR [--zooms 4-9] [--only z/x/y ...] [--procs 8]

Work is split by z6 block: each worker decodes the data tiles of one z6 block
once and renders every output tile of z6-9 inside it. z4/z5 tiles are their own
units. Every output position under a covered z6 block is written (empty ones as
tiny transparent tiles) so the page never asks for a missing tile; cover.json
lists the z6 blocks that hold any road.
"""
import argparse, gzip, json, math, os, sys
from multiprocessing import Pool

import numpy as np
import skia
from PIL import Image

# ---------------------------------------------------------------- region
LAT_S, LAT_N, LON_W, LON_E = 24.0, 56.0, -128.0, -52.0

# ---------------------------------------------------------------- style
# class 0 motorway, 1 trunk/primary, 2 secondary, 3 tertiary (drawn as class 2)
CASING = (8, 10, 16)
CASING_A = 0.5
GREEN = (5, 219, 50)
CLASS2_CORE_A = 0.82
BASE_W = {0: (4.0, 2.3), 1: (3.4, 1.7), 2: (2.6, 1.2), 3: (2.6, 1.2)}   # (casing, core) px

# per output zoom: data zoom read, classes drawn, width scale
ZOOM_PLAN = {
    4: dict(dz=8,  classes=(0, 1),    scale=0.50),
    5: dict(dz=9,  classes=(0, 1),    scale=0.56),
    6: dict(dz=9,  classes=(0, 1, 2), scale=0.66),
    7: dict(dz=9,  classes=(0, 1, 2), scale=0.80),
    8: dict(dz=10, classes=(0, 1, 2, 3), scale=0.90),
    9: dict(dz=11, classes=(0, 1, 2, 3), scale=1.0),
}
# minimum widths so thin zooms keep a visible core
MIN_CORE, MIN_CASE = 0.6, 1.2

KIND_CLASS = {
    'motorway': 0, 'motorway_link': 0,
    'trunk': 1, 'trunk_link': 1, 'primary': 1, 'primary_link': 1,
    'secondary': 2, 'secondary_link': 2, 'tertiary': 3, 'tertiary_link': 3,
}
# links are drawn only from this output zoom up (they read as noise lower)
LINK_MIN_Z = 8

MARGIN = 8  # px of neighbor data pulled in around each output tile

# Image size. Tiles cover 256 display px (Leaflet tileSize 256) but are drawn at 2x
# so retina screens get crisp lines; 1x screens downsample them in the browser.
TILE_PX = 512


# ---------------------------------------------------------------- mercator
def lon2x(lon, z):
    return (lon + 180.0) / 360.0 * (1 << z)


def lat2y(lat, z):
    r = math.radians(lat)
    return (1 - math.asinh(math.tan(r)) / math.pi) / 2 * (1 << z)


def tile_range(z):
    x0, x1 = int(lon2x(LON_W, z)), int(lon2x(LON_E, z))
    y0, y1 = int(lat2y(LAT_N, z)), int(lat2y(LAT_S, z))
    return x0, x1, y0, y1


# ---------------------------------------------------------------- MVT decode
def _varint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1
        r |= (c & 0x7f) << s
        if c < 0x80:
            return r, i
        s += 7


def _fields(b):
    i, n = 0, len(b)
    while i < n:
        k, i = _varint(b, i)
        f, w = k >> 3, k & 7
        if w == 0:
            v, i = _varint(b, i)
        elif w == 2:
            ln, i = _varint(b, i)
            v = b[i:i + ln]; i += ln
        elif w == 1:
            v = b[i:i + 8]; i += 8
        elif w == 5:
            v = b[i:i + 4]; i += 4
        else:
            raise ValueError('wire type %d' % w)
        yield f, w, v


def _packed(b):
    out, i, n = [], 0, len(b)
    while i < n:
        v, i = _varint(b, i)
        out.append(v)
    return out


def _value(b):
    for f, w, v in _fields(b):
        if f == 1:
            return bytes(v).decode('utf-8', 'replace')
        return None
    return None


def decode_roads(data, link_ok):
    """-> (extent, {class: [np.array(N,2) line, ...]}) for the roads layer."""
    if data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    mv = memoryview(data)
    for f, w, layer in _fields(mv):
        if f != 3:
            continue
        name = None; feats = []; keys = []; vals = []; extent = 4096
        for lf, lw, lv in _fields(layer):
            if lf == 1:
                name = bytes(lv).decode()
                if name != 'roads':
                    break
            elif lf == 2:
                feats.append(lv)
            elif lf == 3:
                keys.append(bytes(lv).decode())
            elif lf == 4:
                vals.append(lv)
            elif lf == 5:
                extent = lv
        if name != 'roads':
            continue
        try:
            kd_key = keys.index('kind_detail')
        except ValueError:
            return extent, {}
        vcache = {}
        out = {0: [], 1: [], 2: [], 3: []}
        for fb in feats:
            tags = geom = None; gtype = 0
            for ff, fw, fv in _fields(fb):
                if ff == 2:
                    tags = _packed(fv)
                elif ff == 3:
                    gtype = fv
                elif ff == 4:
                    geom = fv
            if gtype != 2 or not tags or geom is None:
                continue
            kd = None
            for t in range(0, len(tags), 2):
                if tags[t] == kd_key:
                    vi = tags[t + 1]
                    if vi not in vcache:
                        vcache[vi] = _value(vals[vi])
                    kd = vcache[vi]
                    break
            cls = KIND_CLASS.get(kd)
            if cls is None or (not link_ok and kd.endswith('_link')):
                continue
            cmds = _packed(geom)
            x = y = 0; i = 0; cur = None
            lines = out[cls]
            while i < len(cmds):
                c = cmds[i]; i += 1
                cid, cnt = c & 7, c >> 3
                if cid == 1 or cid == 2:
                    for _ in range(cnt):
                        dx, dy = cmds[i], cmds[i + 1]; i += 2
                        x += (dx >> 1) ^ -(dx & 1)
                        y += (dy >> 1) ^ -(dy & 1)
                        if cid == 1:
                            if cur and len(cur) > 1:
                                lines.append(cur)
                            cur = [(x, y)]
                        else:
                            cur.append((x, y))
            if cur and len(cur) > 1:
                lines.append(cur)
        return extent, {k: [np.asarray(l, np.float64) for l in v] for k, v in out.items()}
    return 4096, {}


# ---------------------------------------------------------------- reader
_READER = None


def reader(path):
    global _READER
    if _READER is None:
        from pmtiles.reader import Reader, MmapSource
        _READER = Reader(MmapSource(open(path, 'rb')))
    return _READER


class DataCache:
    def __init__(self, path):
        self.path = path
        self.c = {}

    def get(self, dz, dx, dy, link_ok):
        k = (dz, dx, dy, link_ok)
        if k not in self.c:
            d = reader(self.path).get(dz, dx, dy)
            self.c[k] = decode_roads(d, link_ok) if d else (4096, {})
        return self.c[k]


# ---------------------------------------------------------------- render
def render_tile(cache, z, x, y):
    """-> RGBA uint8 array (TILE_PX,TILE_PX,4), or None when nothing is drawn."""
    plan = ZOOM_PLAN[z]
    dz = plan['dz']
    link_ok = z >= LINK_MIN_Z
    f = 1 << (dz - z)                       # data tiles per output tile edge
    m = MARGIN / 256.0                      # margin in output-tile units
    dx0 = int(math.floor((x - m) * f)); dx1 = int(math.floor((x + 1 + m) * f))
    dy0 = int(math.floor((y - m) * f)); dy1 = int(math.floor((y + 1 + m) * f))
    n = 1 << dz
    paths = {c: skia.Path() for c in plan['classes']}
    any_ = False
    for dx in range(dx0, dx1 + 1):
        for dy in range(max(dy0, 0), min(dy1, n - 1) + 1):
            ext, lines = cache.get(dz, dx % n, dy, link_ok)
            if not lines:
                continue
            s = 256.0 / (f * ext)
            ox = (dx - x * f) * 256.0 / f
            oy = (dy - y * f) * 256.0 / f
            for c in plan['classes']:
                p = paths[c]
                for ln in lines.get(c, ()):
                    pts = ln * s
                    pts[:, 0] += ox; pts[:, 1] += oy
                    # drop sub-quarter-pixel steps (keeps paths light)
                    if len(pts) > 2:
                        pts = pts[_thin(pts, 0.15)]
                    if (pts[:, 0].max() < -MARGIN or pts[:, 0].min() > 256 + MARGIN or
                            pts[:, 1].max() < -MARGIN or pts[:, 1].min() > 256 + MARGIN):
                        continue
                    p.moveTo(float(pts[0, 0]), float(pts[0, 1]))
                    for px, py in pts[1:]:
                        p.lineTo(float(px), float(py))
                    any_ = True
    if not any_:
        return None
    surf = skia.Surface(TILE_PX, TILE_PX)
    cv = surf.getCanvas()
    cv.clear(skia.ColorTRANSPARENT)
    cv.scale(TILE_PX / 256.0, TILE_PX / 256.0)   # geometry and widths stay in display px

    def stroke(color, w, alpha=1.0):
        return skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=w,
                          StrokeCap=skia.Paint.kRound_Cap, StrokeJoin=skia.Paint.kRound_Join,
                          Color=skia.Color(*color, int(round(alpha * 255))))

    sc = plan['scale']
    if 3 in paths:          # tertiary shares the secondary style: one path, one layer
        if 2 in paths:
            paths[2].addPath(paths.pop(3))
        else:
            paths[2] = paths.pop(3)
    order = sorted(paths, reverse=True)   # class 2 first, motorways last
    # casings: one opaque layer composited at .5 so crossings don't stack alpha
    cv.saveLayerAlpha(None, int(round(CASING_A * 255)))
    for c in order:
        cv.drawPath(paths[c], stroke(CASING, max(BASE_W[c][0] * sc, MIN_CASE)))
    cv.restore()
    for c in order:
        w = max(BASE_W[c][1] * sc, MIN_CORE)
        if c >= 2:
            cv.saveLayerAlpha(None, int(round(CLASS2_CORE_A * 255)))
            cv.drawPath(paths[c], stroke(GREEN, w))
            cv.restore()
        else:
            cv.drawPath(paths[c], stroke(GREEN, w))
    img = surf.makeImageSnapshot()
    arr = img.toarray(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType)
    return arr


def _thin(pts, tol):
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    lx, ly = pts[0]
    for i in range(1, len(pts) - 1):
        if abs(pts[i, 0] - lx) > tol or abs(pts[i, 1] - ly) > tol:
            keep[i] = True
            lx, ly = pts[i]
    return keep


def save(arr, out, z, x, y):
    d = os.path.join(out, str(z), str(x))
    os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, '%d.webp' % y)
    if arr is None:
        Image.new('RGBA', (TILE_PX, TILE_PX), (0, 0, 0, 0)).save(fn, 'WEBP', lossless=True)
        return 0
    Image.fromarray(arr).save(fn, 'WEBP', lossless=True, method=6)
    return 1


# ---------------------------------------------------------------- units
ARGS = None


def unit_block(xy):
    """Render z6 block (x6, y6) and its z7-9 children. -> (x6, y6, nonempty)."""
    x6, y6 = xy
    cache = DataCache(ARGS.pmtiles)
    zs = [z for z in ARGS.zooms if z >= 6]
    if 6 not in zs:
        zs = [6] + zs        # z6 decides coverage
    res = {}
    for z in sorted(zs):
        k = 1 << (z - 6)
        for x in range(x6 * k, x6 * k + k):
            for y in range(y6 * k, y6 * k + k):
                res[(z, x, y)] = render_tile(cache, z, x, y)
        # free decoded data of zooms no longer needed
        nxt = [ZOOM_PLAN[zz]['dz'] for zz in zs if zz > z]
        for key in list(cache.c):
            if key[0] not in nxt:
                del cache.c[key]
    nonempty = res[(6, x6, y6)] is not None
    if nonempty or ARGS.keep_empty:
        for (z, x, y), arr in res.items():
            if z in ARGS.zooms:
                save(arr, ARGS.out, z, x, y)
    return x6, y6, nonempty


def unit_low(zxy):
    z, x, y = zxy
    cache = DataCache(ARGS.pmtiles)
    arr = render_tile(cache, z, x, y)
    return z, x, y, arr is not None, arr


def init(args):
    global ARGS
    ARGS = args


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pmtiles')
    ap.add_argument('out')
    ap.add_argument('--zooms', default='4-9')
    ap.add_argument('--only', nargs='*', help='render just these z/x/y tiles')
    ap.add_argument('--procs', type=int, default=os.cpu_count())
    ap.add_argument('--keep-empty', action='store_true')
    a = ap.parse_args()
    lo, hi = map(int, a.zooms.split('-'))
    a.zooms = list(range(lo, hi + 1))
    os.makedirs(a.out, exist_ok=True)
    init(a)

    if a.only:
        cache = DataCache(a.pmtiles)
        for s in a.only:
            z, x, y = map(int, s.split('/'))
            save(render_tile(cache, z, x, y), a.out, z, x, y)
            print('rendered', s)
        return

    x0, x1, y0, y1 = tile_range(6)
    blocks = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    cover = []
    with Pool(a.procs, initializer=init, initargs=(a,)) as pool:
        for i, (x6, y6, ne) in enumerate(pool.imap_unordered(unit_block, blocks)):
            if ne:
                cover.append([x6, y6])
            if i % 20 == 0:
                print('z6 blocks %d/%d, covered %d' % (i + 1, len(blocks), len(cover)), flush=True)
        cover.sort()
        cov = set(map(tuple, cover))
        lows = []
        for z in (4, 5):
            if z not in a.zooms:
                continue
            want = sorted({(x6 >> (6 - z), y6 >> (6 - z)) for x6, y6 in cov})
            lows += [(z, x, y) for x, y in want]
        for z, x, y, ne, arr in pool.imap_unordered(unit_low, lows):
            save(arr, a.out, z, x, y)
        print('low zooms', len(lows), flush=True)

    meta = {
        'cover_z': 6,
        'cover': cover,
        'zooms': [min(a.zooms), max(a.zooms)],
        'bbox': [LON_W, LAT_S, LON_E, LAT_N],
        'tile_size': 256,
        'image_px': TILE_PX,
        'note': 'Every z4-9 tile under a cover z6 block exists (empty ones are transparent). '
                'Tiles outside the cover were never uploaded: do not request them.',
        'source': 'bluish-basemap-20260829.pmtiles (Protomaps, OpenStreetMap contributors)',
        'plan': {str(z): {'data_zoom': p['dz'], 'classes': list(p['classes']),
                          'links': z >= LINK_MIN_Z, 'width_scale': p['scale']}
                 for z, p in ZOOM_PLAN.items()},
    }
    with open(os.path.join(a.out, 'cover.json'), 'w') as fh:
        json.dump(meta, fh, separators=(',', ':'))
    print('cover blocks', len(cover))


if __name__ == '__main__':
    main()
