#!/usr/bin/env python3
"""1782 -- THE BRITISH HEADQUARTERS MAP (user 2026-10-28: HISTORICAL WATERS, "do them all 4"). B.F. Stevens's 1900 facsimile of the
British army's manuscript survey of New York, 1782: public domain, NYPL's full-resolution stitch on Wikimedia Commons
(File:Stevens_Facsimile_of_British_Headquarters_Map_of_New_York.jpg, 28582 x 12132).

What this map can give, honestly: the SHORE. It does not colour its water -- streams are thin dark lines in the same ink as the roads,
so they cannot be lifted by colour the way Viele's or the USGS sheets' can -- but land is drawn textured and the water is plain paper
edged by a tan wash along every shore. So:
  - land = inked or textured ground (the tan shore wash excluded), the sheet's mounting seams erased first (they are found as the
    columns and rows inked right across the sheet), closed, small enclosures (fields) filled, rivers left open;
  - the 1782 SHORE = the land's edge only where it meets that tan wash (an edge where the surveyor simply stopped drawing is not a shore);
  - FILLED SINCE 1782 = what was water in 1782 inside today's Manhattan, the one island the sheet covers end to end.

Georeference: Map Warper map 13702's ten control points (open API), carried onto this image by matching Map Warper's thumbnail (scale and
offset solved to sub-pixel, correlation 0.91), plus two added by eye in the north where all ten were missing (Jeffrey's Hook, Mill Rock);
an affine fit, leave-one-out median 67 m, worst 238 m -- the map's own drafting, not a modern survey.

    python3 bhq1782.py WORKDIR OUT.json       (WORKDIR holds bhq_full.jpg, land_r4.npy from the classifier, georef_affine.npy)
"""
import json, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage as nd
from shapely.geometry import shape, Polygon, MultiPolygon, LineString
from shapely.ops import unary_union
import rasterio.features
from affine import Affine

Image.MAX_IMAGE_PIXELS = None
HERE = os.path.dirname(os.path.abspath(__file__))


def main(work, out):
    land = np.load(os.path.join(work, 'land_r4.npy'))
    land = nd.binary_closing(land, iterations=5)                       # heal the seam cuts (7 px)
    c = np.load(os.path.join(work, 'georef_affine.npy')); cx, cy = c[:3], c[3:]
    kx = 1 / (111320 * np.cos(np.radians(40.75))); ky = 1 / 110540
    # reduced pixel (col, row) -> full pixel X = 4 col + 1.5 -> local metres -> lon / lat
    a = cx[1] / 1e4 * 4 * kx; b = cx[2] / 1e4 * 4 * kx; c0 = -74 + (cx[0] + (cx[1] + cx[2]) / 1e4 * 1.5) * kx
    d = cy[1] / 1e4 * 4 * ky; e = cy[2] / 1e4 * 4 * ky; f0 = 40.7 + (cy[0] + (cy[1] + cy[2]) / 1e4 * 1.5) * ky
    T = Affine(a, b, c0, d, e, f0)
    # the tan shore wash, again, to tell a shore from the edge of the drawing
    im = np.asarray(Image.open(os.path.join(work, 'bhq_full.jpg')).reduce(4)).astype(np.float32)
    R, G, B = im[..., 0], im[..., 1], im[..., 2]; gray = im.mean(-1)
    m = nd.uniform_filter(gray, 7); m2 = nd.uniform_filter(gray * gray, 7); sd = np.sqrt(np.maximum(m2 - m * m, 0))
    ochre = np.load(os.path.join(work, 'ochre_r4.npy')) if os.path.exists(os.path.join(work, 'ochre_r4.npy')) else (R - B > 40) & (G - B > 20) & (gray > 140) & (gray < 222) & (sd < 14)
    shore_px = (land ^ nd.binary_erosion(land, iterations=1)) & nd.binary_dilation(ochre, iterations=6)
    polys = [shape(g) for g, v in rasterio.features.shapes(land.astype(np.uint8), mask=land, transform=T) if v]
    L = unary_union([p.buffer(0) for p in polys]).simplify(0.00003)
    # shore lines: the land's rings, kept where the pixel under them is a shore pixel
    inv = ~T
    def is_shore(x, y):
        cc, rr = inv * (x, y); cc, rr = int(cc), int(rr)
        if rr < 0 or cc < 0 or rr >= land.shape[0] or cc >= land.shape[1]: return False
        return bool(shore_px[max(0, rr - 2):rr + 3, max(0, cc - 2):cc + 3].any())
    lines = []
    for p in (L.geoms if hasattr(L, 'geoms') else [L]):
        if p.area < 2e-7: continue
        for ring in [p.exterior] + list(p.interiors):
            run = []
            for x, y in ring.coords:
                if is_shore(x, y): run.append([round(x, 5), round(y, 5)])
                else:
                    if len(run) > 3: lines.append(run)
                    run = []
            if len(run) > 3: lines.append(run)
    # a 'shore' far out in today's water is the drawing's own edge, not a coast: keep runs whose median point is within 400 m of
    # today's land in the city (the islands -- Ellis, Liberty, Governors -- included)
    city = unary_union([Polygon(r).buffer(0) for b in json.load(open(os.path.join(HERE, '..', 'city_boroughs.json')))['hi'] for r in b['r'] if len(r) > 3]).buffer(0.0048)
    from shapely.geometry import Point
    lines = [r for r in lines if sorted(city.contains(Point(q)) for q in r)[len(r) // 2]]
    # filled since 1782: today's Manhattan minus 1782 land
    hi = json.load(open(os.path.join(HERE, '..', 'city_boroughs.json')))['hi']
    man = unary_union([Polygon(r).buffer(0) for b in hi if b['n'] == 'Manhattan' for r in b['r'] if len(r) > 3])
    # only fill wider than ~220 m, twice the map's placement error, survives (user 2026-10-28, on the 1782 lines: "idk if we need the british
    # lines" -- they ran down the middle of Roosevelt Island, the ~110 m error drawn as if it were history). The shore runs are no longer drawn.
    filled = man.difference(L).buffer(-0.00133).buffer(0.00133).buffer(-0.00018).buffer(0.00018)
    fp = [[[[round(x, 5), round(y, 5)] for x, y in g.exterior.coords]] for g in (filled.geoms if hasattr(filled, 'geoms') else [filled]) if g.area > 3e-7]
    km2 = sum(Polygon(r[0]).area for r in fp) * 111.32 * 111.32 * np.cos(np.radians(40.75))
    json.dump({'src': 'British Headquarters map of New York, 1782 (B.F. Stevens facsimile, 1900; NYPL via Wikimedia Commons), georeferenced from Map Warper 13702',
               'err_m': 67, 'shore': lines, 'filled': fp}, open(out, 'w'), separators=(',', ':'))
    print(len(lines), 'shore runs,', len(fp), 'filled polygons, %.1f km2 of today\'s Manhattan was water in 1782' % km2, os.path.getsize(out), 'bytes')


if __name__ == '__main__':
    main(*sys.argv[1:3])
