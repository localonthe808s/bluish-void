#!/usr/bin/env python3
"""Re-pull the East River and the Hudson from CUDEM at the model's NATIVE
resolution, and splice the bands into bathy/river_depth.json.

WHY THIS EXISTS AS A FILE. The original river_depth bake was run in-session and
never committed, so the recipe survived only as prose in GHOST_RIVERS.md and had
to be reconstructed. It is a file now.

THE PROBLEM IT SOLVES. river_depth.json's `harbour` source is one harbour-wide
export that comes back at 12.7 m per pixel -- that is the ImageServer's export
size ceiling, NOT the model's resolution. CUDEM's native is 1/9 arc-second
(3.0864e-05 deg, ~3.4 m in latitude); the service reports exactly that as its
pixelSize. Seven creek boxes were already pulled at native for precisely this
reason. The East River and the Hudson were not -- they are still the 12.7 m
harbour grid, which flattens a channel that actually reaches 36.6 m at Hell Gate.

So: same source, same grammar, same output contract -- just asked for in boxes
small enough that the server returns native pixels.

Output contract, matched to what harbour/creeks already emit (measured, not
assumed): single-ring closed Polygons, `{'d': class, 'src': name}`, coordinates
rounded to 5 decimals, no explicit alpha (drawDepth's log formula applies).
Only `bight` features are multi-ring and carry `a`; nothing here touches those.

    python3 river_depth_bake.py --dry            # list boxes and pixel sizes
    python3 river_depth_bake.py --validate       # re-bake gowanus, compare
    python3 river_depth_bake.py --bake           # pull rivers -> river_bands.json
    python3 river_depth_bake.py --merge          # splice into river_depth.json
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import tifffile
from shapely.geometry import Polygon
from shapely.geometry import box as shp_box
from shapely.ops import unary_union
from skimage import measure

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, 'bathy', 'river_depth.json')
BANDS_OUT = os.path.join(HERE, 'bathy', 'river_bands.json')

SRC = ('https://gis.ngdc.noaa.gov/arcgis/rest/services/'
       'DEM_mosaics/DEM_all/ImageServer/exportImage')
NATIVE = 3.0863998e-05          # deg/px, the service's own pixelSizeX (1/9 arcsec)

# the harbour bake's classes, unchanged -- these are what drawDepth expects
CLASSES = (1, 2, 4, 7, 10, 15, 20, 30)

# Boxes hugging the two channels, each small enough that `size` at native
# resolution is a sane request. They stay inside the harbour bake's own extent
# (-74.28..-73.68, 40.4802..40.93) so nothing lands outside the city view.
BOXES = [
    # --- East River, Battery to the Sound
    ('eastriver', -74.025, 40.690, -73.965, 40.725),   # Battery / Governors I.
    ('eastriver', -73.980, 40.712, -73.930, 40.782),   # Williamsburg -> Roosevelt I.
    ('eastriver', -73.945, 40.765, -73.895, 40.802),   # Hell Gate / Randalls
    ('eastriver', -73.905, 40.780, -73.835, 40.818),   # Rikers -> Throgs Neck
    ('eastriver', -73.845, 40.788, -73.762, 40.828),   # Throgs Neck -> Sound
    # --- Harlem River, the link between them
    ('harlem',    -73.962, 40.795, -73.902, 40.882),
    # --- Hudson, Battery to the city line
    ('hudson',    -74.042, 40.688, -73.988, 40.762),   # Battery -> 42nd
    ('hudson',    -74.018, 40.752, -73.958, 40.832),   # 42nd -> Washington Hts
    ('hudson',    -73.992, 40.822, -73.898, 40.892),   # GWB -> Spuyten Duyvil
    ('hudson',    -73.982, 40.882, -73.892, 40.930),   # city line
]

# The gowanus box, read off the existing output's own extent. Re-baking it is
# how we prove the reconstructed recipe matches the committed data.
GOWANUS = ('gowanus', -74.02, 40.66, -73.9987, 40.69)

# Tuned against gowanus (--validate). Honest note on how close that got: the
# committed creek features have a median ring of 28 points and a smallest
# (post-simplify) area near 138 px^2, and these constants land in that range.
# They do NOT reproduce the committed per-class histogram, and no threshold
# can: the committed profile RISES with depth (gowanus 1:2 ... 15:8) while
# interval banding FALLS (1:5 ... 15:1), because the shallow [1,2) interval is
# a thin rim that fragments around every bank irregularity. A global area floor
# removes features, it cannot move them between classes. So the original bake
# segmented differently in some way the prose does not record.
# What is verified instead is the invariant that actually governs rendering —
# one veil per pixel, checked directly by --probe.
# The tolerance is set by CORRECTNESS, not by looks. Probing Hell Gate: 4.5e-5
# leaves 0.6% of water pixels inside two bands and 96.7% class-correct, while
# 8e-6 gives 0.0% and 99.6%. Neighbouring bands share a boundary, and
# simplifying each side independently drifts the two copies across each other --
# the thinner the band, the worse it gets. Carrying the extra points is cheaper
# than painting a veil twice. 1.5e-5 still probes 0.0% nesting / 99.1% correct
# at 413 KB for the Hell Gate box, against 797 KB at 8e-6 -- half the bytes for
# 0.5 points of accuracy, on a file the browser has to fetch.
# MIN_AREA stays low: raising it does not help nesting at all, it only throws
# real water away (12.8% of probed pixels land in no band at 4000, versus 2.7%
# here), which is the one error the eye actually sees as a hole in the channel.
SIMPLIFY_DEG = 0.000015
MIN_AREA_PX = 200.0


def px_for(w, s, e, n):
    return int(round((e - w) / NATIVE)), int(round((n - s) / NATIVE))


def fetch(w, s, e, n, path, tries=3):
    """One native-resolution float32 tile out of the ImageServer."""
    W, H = px_for(w, s, e, n)
    q = urllib.parse.urlencode({
        'bbox': '%f,%f,%f,%f' % (w, s, e, n),
        'bboxSR': 4326, 'imageSR': 4326,
        'size': '%d,%d' % (W, H),
        'format': 'tiff', 'pixelType': 'F32',
        'interpolation': 'RSP_NearestNeighbor', 'f': 'image',
    })
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(SRC + '?' + q, timeout=180) as r:
                blob = r.read()
            if blob[:2] not in (b'II', b'MM'):     # an error comes back as JSON
                raise RuntimeError('not a tiff: ' + blob[:200].decode('utf8', 'replace'))
            open(path, 'wb').write(blob)
            return W, H
        except Exception as exc:                    # noqa: BLE001 - retry anything
            last = exc
            time.sleep(2 + 3 * attempt)
    raise RuntimeError('fetch failed for %s: %s' % ((w, s, e, n), last))


def bands(depth, w, s, e, n, src):
    """Interval depth bands as polygons, holes included.

    ONE VEIL PER PIXEL. Each class is the half-open interval [d, next) -- never
    a cumulative "deeper than d" nest. A nested bake renders the same water five
    or six veils dark; that trap is already documented for the bight.

    HOLES MATTER. A band around a deep core is an ANNULUS, and a single filled
    ring cannot express that -- the shallow band's outer ring would cover the
    deep core, so a pixel there would sit inside two bands and be painted twice.
    With holes honoured and the tolerance below, Hell Gate probes 0.0% of water
    pixels in more than one band and 99.6% in the class the raster actually says.
    So each connected component is emitted as a real polygon
    with its holes, rings classified by WINDING (point sampling misfires, per
    the bight work). drawDepth already fills every ring 'evenodd', which is how
    the bight features work, so multi-ring is native to the renderer.
    """
    h, wpx = depth.shape
    out = []

    def to_lonlat(ring):
        rr = ring[:, 0] - 1.0
        cc = ring[:, 1] - 1.0
        lon = w + (cc + 0.5) * (e - w) / wpx
        lat = n - (rr + 0.5) * (n - s) / h      # exportImage returns north-up
        return np.column_stack([lon, lat])

    for i, d in enumerate(CLASSES):
        nxt = CLASSES[i + 1] if i + 1 < len(CLASSES) else None
        m = depth >= d
        if nxt is not None:
            m &= depth < nxt
        if not m.any():
            continue
        lab = measure.label(m, connectivity=1)
        for region in measure.regionprops(lab):
            if region.area < MIN_AREA_PX:
                continue
            comp = lab == region.label
            # pad by one so a component touching the tile edge still closes
            padded = np.pad(comp.astype(np.float32), 1)
            rings = [r for r in measure.find_contours(padded, 0.5) if len(r) >= 4]
            if not rings:
                continue
            # one component has exactly one outer ring; the rest are its holes.
            # |signed area| picks the outer one without any point-in-polygon test.
            def sarea(r):
                y, x = r[:, 0], r[:, 1]
                return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
            rings.sort(key=lambda r: abs(sarea(r)), reverse=True)
            shell = to_lonlat(rings[0])
            holes = [to_lonlat(r) for r in rings[1:]
                     if abs(sarea(r)) >= MIN_AREA_PX * 0.25]
            try:
                poly = Polygon(shell, holes)
            except Exception:                       # noqa: BLE001 - degenerate ring
                continue
            if not poly.is_valid:
                poly = poly.buffer(0)
            # preserve_topology keeps the holes; False would silently drop them
            poly = poly.simplify(SIMPLIFY_DEG, preserve_topology=True)
            if poly.is_empty:
                continue
            for g in getattr(poly, 'geoms', [poly]):
                if g.geom_type != 'Polygon':
                    continue
                coords = []
                for ring in [g.exterior] + list(g.interiors):
                    xy = [[round(x, 5), round(y, 5)] for x, y in ring.coords]
                    if xy[0] != xy[-1]:
                        xy.append(xy[0])
                    if len(xy) >= 4:
                        coords.append(xy)
                if not coords:
                    continue
                out.append({'type': 'Feature',
                            'properties': {'d': d, 'src': src},
                            'geometry': {'type': 'Polygon', 'coordinates': coords}})
    return out


def clip_features(feats, clip):
    """Trim a box's bands to the part of it no earlier box already covered.

    The boxes below follow two winding channels and therefore overlap each
    other -- the Battery sits in both a Hudson box and an East River box, and
    the Harlem box lies inside the upper Hudson box. Measured on the first
    bake: a point in the rivers landed in 4.7 band polygons on average and up
    to 11, with combinations like (eastriver, harbour, hudson). Each of those
    is a veil, so the same water was being darkened two and three times over.
    Giving every box an exclusive claim fixes it without refetching a thing.
    """
    out = []
    for f in feats:
        c = f['geometry']['coordinates']
        try:
            p = Polygon(c[0], c[1:])
        except Exception:                           # noqa: BLE001 - degenerate ring
            continue
        if not p.is_valid:
            p = p.buffer(0)
        g = p.intersection(clip)
        if g.is_empty:
            continue
        for part in getattr(g, 'geoms', [g]):
            if part.geom_type != 'Polygon' or part.is_empty:
                continue
            rings = []
            for ring in [part.exterior] + list(part.interiors):
                xy = [[round(x, 5), round(y, 5)] for x, y in ring.coords]
                if xy[0] != xy[-1]:
                    xy.append(xy[0])
                if len(xy) >= 4:
                    rings.append(xy)
            if rings:
                out.append({'type': 'Feature',
                            'properties': dict(f['properties']),
                            'geometry': {'type': 'Polygon', 'coordinates': rings}})
    return out


def bake_box(name, w, s, e, n, tmpdir, label='', clip=None):
    tif = os.path.join(tmpdir, 'cudem_%s_%.4f_%.4f.tif' % (name, w, s))
    # Resumable, like the ink pyramid bake: the download is the slow half and the
    # vectorising constants get retuned, so never re-pull a tile already on disk.
    if os.path.exists(tif) and os.path.getsize(tif) > 1024:
        W, H = px_for(w, s, e, n)
    else:
        W, H = fetch(w, s, e, n, tif)
    arr = tifffile.imread(tif).astype('f4')
    depth = -arr                                   # CUDEM is elevation; below sea is negative
    depth[~np.isfinite(depth)] = -9999
    feats = bands(depth, w, s, e, n, name)
    # Trim to this box's exclusive claim. Without this the `clip` argument is
    # accepted and silently ignored -- which is exactly what happened on the
    # first attempt, and every per-box count came back byte-identical to the
    # unclipped run. The upper Hudson box is the tell: 89 features unclipped,
    # 16 once its 41% claim is applied.
    if clip is not None:
        feats = clip_features(feats, clip)
    deepest = float(depth[np.isfinite(depth)].max())
    print('  %-10s %-28s %5dx%-5d  deepest %5.1f m  %4d features'
          % (name, label or '%.3f,%.3f' % (w, s), W, H, deepest, len(feats)))
    return feats


def bake_mosaic(tmpdir):
    """Contour the rivers as ONE grid rather than ten separately-contoured boxes.

    NOT THE DEFAULT, AND HERE IS THE HONEST REASON. This was written to remove a
    seam at the box claim edges -- equal-separation transects put |delta alpha|
    across those edges at 1.61x the interior control. That finding was WRONG.
    Mosaicking barely moved the number (1.60x), and the split still showed
    "internal" joins at 1.57x even though a single contour pass leaves no
    internal boundary in the geometry at all. A placebo control settled it:
    lines offset a few hundred metres from any real edge score 1.38x against
    1.46x for the real edges, with random interior pairs at 1.00x. The boxes
    were drawn to hug the channels, so their edges cut ACROSS the river at steep
    depth gradients while the control sampled flat water -- the ratio measured
    my sampling, not a discontinuity.

    So there is no seam to fix, and `--bake` (ten boxes with exclusive claims)
    remains the default. This mode is kept because it is genuinely simpler --
    one contour pass, one `rivers` source, 598 features against 725, and the
    channel comes out as one connected band instead of fragments cut at box
    lines -- but it buys nothing measurable, so it does not ship.

    Two details that matter. The strips are cut ON the mosaic lattice, so they
    paste at integer offsets -- the hand-written boxes were off by up to 0.23 px,
    which would have smeared the joins they were meant to remove. And the result
    is clipped to the union of the corridor boxes, so this stays a river re-pull
    instead of quietly re-contouring the whole harbour rectangle at native.
    """
    W0 = min(w for _, w, _, _, _ in BOXES)
    E0 = max(e for _, _, _, e, _ in BOXES)
    S0 = min(s for _, _, s, _, _ in BOXES)
    N0 = max(n for _, _, _, _, n in BOXES)
    W = int(round((E0 - W0) / NATIVE))
    H = int(round((N0 - S0) / NATIVE))
    print('mosaic %d x %d px (%.0f MB), %.4f,%.4f -> %.4f,%.4f'
          % (W, H, W * H * 4 / 1048576, W0, S0, E0, N0))

    mosaic = np.full((H, W), -9999.0, dtype='f4')
    STRIP = 3024                      # px per request; H*STRIP*4 ~ 95 MB
    x = k = 0
    while x < W:
        wpx = min(STRIP, W - x)
        sw = W0 + x * NATIVE
        se = W0 + (x + wpx) * NATIVE
        path = os.path.join(tmpdir, 'mosaic_%02d.tif' % k)
        if not (os.path.exists(path) and os.path.getsize(path) > 1024):
            fetch(sw, S0, se, N0, path)
        arr = tifffile.imread(path).astype('f4')
        hh, ww = arr.shape
        mosaic[0:min(hh, H), x:x + min(ww, W - x)] = -arr[0:min(hh, H), 0:min(ww, W - x)]
        print('  strip %d  cols %5d..%-5d  got %dx%d' % (k, x, x + wpx, ww, hh))
        x += wpx
        k += 1

    mosaic[~np.isfinite(mosaic)] = -9999
    feats = bands(mosaic, W0, S0, E0, N0, 'rivers')
    print('  contoured once: %d features before corridor clip' % len(feats))
    corridor = unary_union([shp_box(w, s, e, n) for _, w, s, e, n in BOXES])
    feats = clip_features(feats, corridor)
    print('  after corridor clip: %d features' % len(feats))
    return feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--probe', action='store_true',
                    help='check one veil per pixel and correct class, on a real box')
    ap.add_argument('--probe-n', type=int, default=4000)
    ap.add_argument('--bake', action='store_true')
    ap.add_argument('--mosaic', action='store_true',
                    help='contour the rivers as ONE grid (no internal claim edges)')
    ap.add_argument('--seam', action='store_true',
                    help='measure veil discontinuity at the box edges vs a control')
    ap.add_argument('--merge', action='store_true')
    ap.add_argument('--tmp', default='/tmp')
    a = ap.parse_args()

    if a.dry:
        tot = 0
        for name, w, s, e, n in BOXES:
            W, H = px_for(w, s, e, n)
            tot += W * H
            print('  %-10s %8.3f,%7.3f -> %8.3f,%7.3f   %5d x %-5d px  %6.1f MB'
                  % (name, w, s, e, n, W, H, W * H * 4 / 1048576))
        print('  TOTAL %.1f Mpx, %.2f GB of float32 over %d boxes'
              % (tot / 1e6, tot * 4 / 1073741824, len(BOXES)))
        return

    if a.validate:
        # Re-bake a box whose committed output we can compare against.
        name, w, s, e, n = GOWANUS
        print('re-baking the gowanus box with the reconstructed recipe:')
        got = bake_box('gowanus', w, s, e, n, a.tmp, label='validation')
        have = [f for f in json.load(open(TARGET))['features']
                if f['properties'].get('src') == 'gowanus']
        from collections import Counter
        gc = Counter(f['properties']['d'] for f in got)
        hc = Counter(f['properties']['d'] for f in have)
        print('\n  class   committed   rebaked')
        for d in CLASSES:
            if hc.get(d) or gc.get(d):
                print('   %-5d  %7d   %7d' % (d, hc.get(d, 0), gc.get(d, 0)))
        print('   %-5s  %7d   %7d' % ('all', len(have), len(got)))
        gp = sorted(len(f['geometry']['coordinates'][0]) for f in got)
        hp = sorted(len(f['geometry']['coordinates'][0]) for f in have)
        if gp and hp:
            print('  median ring points: committed %d, rebaked %d'
                  % (hp[len(hp) // 2], gp[len(gp) // 2]))
        return

    if a.probe:
        # THE INVARIANT THAT MATTERS. drawDepth paints every polygon containing a
        # pixel, so if the bands nested, 19 m of water would be painted six veils
        # dark. Sample real water pixels and assert each falls inside exactly ONE
        # band, and that the band is the interval the raster actually says.
        from shapely.geometry import Point
        from shapely.strtree import STRtree
        name, w, s, e, n = 'eastriver', -73.945, 40.765, -73.895, 40.802   # Hell Gate
        tif = os.path.join(a.tmp, 'probe_hellgate.tif')
        W, H = fetch(w, s, e, n, tif)
        depth = -tifffile.imread(tif).astype('f4')
        depth[~np.isfinite(depth)] = -9999
        feats = bands(depth, w, s, e, n, name)
        # HONOUR THE HOLES. Building these from the shell alone was a bug in this
        # probe: every annulus then swallowed its own deep core and the run
        # reported 12.1% false nesting, which sent me hunting a defect in the
        # bake that was never there. The renderer fills 'evenodd'; match it.
        polys = [Polygon(f['geometry']['coordinates'][0], f['geometry']['coordinates'][1:])
                 for f in feats]
        klass = [f['properties']['d'] for f in feats]
        tree = STRtree(polys)

        def interval_of(dv):
            out = None
            for c in CLASSES:
                if dv >= c:
                    out = c
            return out

        rng = np.random.default_rng(7)
        rows, cols = np.nonzero(depth >= 1.0)
        if len(rows) == 0:
            print('no water in the probe box'); return
        pick = rng.choice(len(rows), size=min(a.probe_n, len(rows)), replace=False)
        exactly_one = right_class = zero = many = 0
        for idx in pick:
            r, c = int(rows[idx]), int(cols[idx])
            lon = w + (c + 0.5) * (e - w) / W
            lat = n - (r + 0.5) * (n - s) / H
            pt = Point(lon, lat)
            inside = [i for i in tree.query(pt) if polys[i].contains(pt)]
            if len(inside) == 1:
                exactly_one += 1
                if klass[inside[0]] == interval_of(float(depth[r, c])):
                    right_class += 1
            elif not inside:
                zero += 1
            else:
                many += 1
        tot = len(pick)
        print('\nprobed %d water pixels in the Hell Gate box (%d band polygons)' % (tot, len(feats)))
        print('  inside exactly one band : %5d  (%.1f%%)' % (exactly_one, 100 * exactly_one / tot))
        print('  inside more than one    : %5d  (%.1f%%)   <- nesting, must be ~0' % (many, 100 * many / tot))
        print('  inside none             : %5d  (%.1f%%)   <- dropped by the area floor' % (zero, 100 * zero / tot))
        print('  correct depth class     : %5d  (%.1f%% of the single hits)'
              % (right_class, 100 * right_class / max(1, exactly_one)))
        return

    if a.seam:
        # EQUAL-SEPARATION TRANSECTS, the same instrument the bight seam used.
        # A box edge is invisible to feature counts and easy to talk yourself
        # out of by eye, because the data really does get sharper across it.
        # The honest test is to sample pairs straddling an edge, sum the alpha
        # of every band containing each point (what drawDepth actually stacks),
        # and compare against pairs the same distance apart in the interior.
        from shapely.geometry import Point
        from shapely.strtree import STRtree
        doc = json.load(open(TARGET))
        polys, alph = [], []
        for f in doc['features']:
            p = f['properties']
            if p.get('src') == 'bight':          # drawn to its own canvas
                continue
            c = f['geometry']['coordinates']
            try:
                g = Polygon(c[0], c[1:])
            except Exception:                    # noqa: BLE001 - degenerate ring
                continue
            if not g.is_valid:
                g = g.buffer(0)
            polys.append(g)
            alph.append(p['a'] if p.get('a') is not None
                        else 0.10 + 0.14 * min(1.0, math.log(1 + p['d']) / math.log(31)))
        tree = STRtree(polys)

        def veil(pt):
            return sum(alph[i] for i in tree.query(pt) if polys[i].contains(pt))

        OFF = 0.00035                            # ~30 m either side
        rng = np.random.default_rng(5)
        seam, ctl = [], []
        for _, w, s, e, n in BOXES:
            for _ in range(400):
                if rng.random() < 0.5:
                    x = w if rng.random() < 0.5 else e
                    y = rng.uniform(s, n)
                    pa, pb = Point(x - OFF, y), Point(x + OFF, y)
                else:
                    y = s if rng.random() < 0.5 else n
                    x = rng.uniform(w, e)
                    pa, pb = Point(x, y - OFF), Point(x, y + OFF)
                va, vb = veil(pa), veil(pb)
                if va > 0 and vb > 0:
                    seam.append(abs(va - vb))
        for _ in range(4000):
            _, w, s, e, n = BOXES[rng.integers(len(BOXES))]
            x, y = rng.uniform(w, e), rng.uniform(s, n)
            th = rng.uniform(0, 2 * math.pi)
            pa = Point(x, y)
            pb = Point(x + OFF * math.cos(th), y + OFF * math.sin(th))
            va, vb = veil(pa), veil(pb)
            if va > 0 and vb > 0:
                ctl.append(abs(va - vb))
        seam, ctl = np.array(seam), np.array(ctl)
        print('across box edges : n=%d  mean %.4f  p90 %.4f'
              % (len(seam), seam.mean(), np.percentile(seam, 90)))
        print('control, same gap: n=%d  mean %.4f  p90 %.4f'
              % (len(ctl), ctl.mean(), np.percentile(ctl, 90)))
        r = seam.mean() / max(1e-9, ctl.mean())
        print('ratio %.2f (edges vs interior control)' % r)
        # THIS RATIO ALONE PROVES NOTHING, and reading it as a seam cost a whole
        # rebake. The boxes hug the channels, so their edges cut ACROSS the river
        # at steep depth gradients while the control samples mostly flat water:
        # the ratio runs ~1.5x with no discontinuity present anywhere. Measured
        # placebo -- lines offset 200-600 m from any real edge -- scored 1.38x
        # against 1.46x for the real edges. Only an excess OVER a placebo counts.
        print('NOT a verdict: box edges cut across the channel, so this runs ~1.5x')
        print('even with no discontinuity. Compare against placebo lines offset')
        print('from the edges before concluding anything (measured: 1.46x real vs')
        print('1.38x placebo vs 1.00x control -> no seam).')
        return

    if a.mosaic:
        feats = bake_mosaic(a.tmp)
        json.dump({'type': 'FeatureCollection', 'features': feats},
                  open(BANDS_OUT, 'w'), separators=(',', ':'))
        print('\nwrote %s: %d features, %.2f MB'
              % (BANDS_OUT, len(feats), os.path.getsize(BANDS_OUT) / 1048576))
        return

    if a.bake:
        feats = []
        print('pulling %d boxes at native %.1f m:' % (len(BOXES), NATIVE * 111320))
        # Each box only keeps the ground no earlier box claimed, so two pulls
        # never veil the same water twice. Order in BOXES is the priority.
        claimed = None
        for name, w, s, e, n in BOXES:
            rect = shp_box(w, s, e, n)
            excl = rect if claimed is None else rect.difference(claimed)
            if excl.is_empty:
                print('  %-10s fully claimed by earlier boxes, skipped' % name)
                continue
            feats += bake_box(name, w, s, e, n, a.tmp, clip=excl)
            claimed = rect if claimed is None else unary_union([claimed, rect])
        json.dump({'type': 'FeatureCollection', 'features': feats},
                  open(BANDS_OUT, 'w'), separators=(',', ':'))
        print('\nwrote %s: %d features, %.2f MB'
              % (BANDS_OUT, len(feats), os.path.getsize(BANDS_OUT) / 1048576))
        return

    if a.merge:
        doc = json.load(open(TARGET))
        feats = doc['features']
        new = json.load(open(BANDS_OUT))['features']
        names = {n for n, *_ in BOXES} | {'rivers'}
        feats = [f for f in feats if f['properties'].get('src') not in names]  # idempotent
        # Order is precedence: later features paint over earlier ones. The new
        # river bands must beat `harbour`, but must NOT displace the creeks --
        # those are the finer, more specific pulls at their own mouths. So they
        # go directly after the last harbour feature.
        last_harbour = max(i for i, f in enumerate(feats)
                           if f['properties'].get('src') == 'harbour')
        merged = feats[:last_harbour + 1] + new + feats[last_harbour + 1:]
        doc['features'] = merged
        json.dump(doc, open(TARGET, 'w'), separators=(',', ':'))
        from collections import Counter
        print('merged. features %d -> %d' % (len(feats), len(merged)))
        print('src totals:', dict(Counter(f['properties'].get('src') for f in merged)))
        print('%.2f MB' % (os.path.getsize(TARGET) / 1048576))
        return

    ap.print_help()


if __name__ == '__main__':
    sys.exit(main())
