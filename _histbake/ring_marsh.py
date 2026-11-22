"""GHOST WATERS BEYOND THE CITY, step 2 (2026-11-22; user: "can you expand this water visual beyond the NYC water borders").

The city layer (/ghost-marsh.json: Viele 1865 + USGS 1897) stops at the city line. This adds the wet ground of the USGS 15-minute
sheets around it -- the Hackensack Meadowlands, Newark Bay, the Long Island south shore, Westchester -- by the same rule the city bake
used: what the survey printed as water or marsh AND is dry land today is ground that has been filled since.

  sheets   USGS Historical Topographic Map Collection, 1:62,500, public domain (prd-tnm S3), one edition per 15' cell, the earliest
           1888-1901 print (sheets.json). Warped in NAD27, the outlines then moved to WGS84 with PROJ's NADCON grid (~35 m E, 11 m N).
  marsh    USGS printed marsh as a fine blue line hatch over the paper: no single pixel is blue, so the sheet is blurred (sigma
           4 px, ~20 m) and read against its own paper color (see sheet_mask: the scans' paper runs cream to near-white).
  neatline each sheet's body is cut to its own 15' cell, so no collar or neighbour's stamp comes through.
  today    ring/wet.npy (ring_osm.py): water -- the sea included -- and wetland today, from our basemap's OSM tiles. Wet today ->
           not a ghost.
  the city NYC's own land is left to the existing layer (its features are kept untouched).

Run: python3 _histbake/ring_osm.py && python3 _histbake/ring_marsh.py  ->  _histbake/ring/ghost_ring.json
"""
import glob, json, os, sys
import numpy as np, cv2, rasterio, pyproj
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from rasterio import features
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, LineString
from shapely.ops import transform as shp_transform, unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
SHEETS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'ring', 'sheets')
sys.path.insert(0, HERE)
from ring_grid import RES, W0, S0, E0, N0, NX, NY, T
pyproj.network.set_network_enabled(True)
NAD27 = 'EPSG:4267'

def paper(a):
    h, w = a.shape[:2]; c = cv2.GaussianBlur(a[::4, ::4], (0, 0), 1)[h // 24:-h // 24, w // 24:-w // 24].reshape(-1, 3)
    q = (c // 8).astype(int); k = q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2]; v, n = np.unique(k, return_counts=True); t = v[np.argmax(n)]
    return np.array([t // 1024 * 8 + 4, t // 32 % 32 * 8 + 4, t % 32 * 8 + 4], np.float32)

def sheet_mask(path):
    with rasterio.open(path) as s:
        a = s.read().transpose(1, 2, 0).astype(np.float32)
        # EACH SHEET AGAINST ITS OWN PAPER: the scans run from cream (252,244,172) to near-white (244,252,236), so a fixed blue
        # cut read Brooklyn as 97% marsh and Tarrytown as none. Marsh is where the blur loses red and gains blue and green
        # against the paper (the commonest color of the sheet's body); black lettering darkens all three and fails the hue tests.
        P = paper(a); b = cv2.GaussianBlur(a, (0, 0), 4)
        br = (b[..., 2] - b[..., 0]) - (P[2] - P[0]); gr = (b[..., 1] - b[..., 0]) - (P[1] - P[0]); rd = P[0] - b[..., 0]
        m = ((br >= 30) & (gr >= 20) & (rd >= 40)).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        m = cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_OPEN, k), cv2.MORPH_CLOSE, k)
        dst = np.zeros((NY, NX), np.uint8)
        reproject(m, dst, src_transform=s.transform, src_crs=s.crs, dst_transform=T, dst_crs=NAD27, resampling=Resampling.nearest)
        # the neatline: this sheet's own 15' cell (its bounds, rounded inward to the quarter degree)
        from rasterio.warp import transform_bounds
        l, bt, r, tp = transform_bounds(s.crs, NAD27, *s.bounds)
        cl, cb = np.ceil(l * 4) / 4, np.ceil(bt * 4) / 4
        cr, ct = cl + .25, cb + .25
        c0, c1 = int(round((cl - W0) / RES)), int(round((cr - W0) / RES))
        r0, r1 = int(round((N0 - ct) / RES)), int(round((N0 - cb) / RES))
        cell = np.zeros_like(dst); cell[max(0, r0):max(0, r1), max(0, c0):max(0, c1)] = 1
        return dst * cell, cell

def chaikin(p, n=2):
    def ring(c):
        c = list(c)[:-1]
        for _ in range(n):
            q = []
            for i in range(len(c)):
                (x0, y0), (x1, y1) = c[i], c[(i + 1) % len(c)]
                q += [(.75 * x0 + .25 * x1, .75 * y0 + .25 * y1), (.25 * x0 + .75 * x1, .25 * y0 + .75 * y1)]
            c = q
        return c + c[:1]
    if p.is_empty or p.geom_type != 'Polygon' or len(p.exterior.coords) < 4: return p
    return Polygon(ring(p.exterior.coords), [ring(r.coords) for r in p.interiors if len(r.coords) >= 4])

def main():
    meta = json.load(open(os.path.join(HERE, 'ring', 'sheets.json')))
    old = np.zeros((NY, NX), np.uint8); cover = np.zeros((NY, NX), np.uint8); yr = np.zeros((NY, NX), np.int16)
    for path in sorted(glob.glob(os.path.join(SHEETS, '*.tif'))):
        m, cell = sheet_mask(path); y = int(os.path.basename(path).split('_')[-3])
        old |= m; cover |= cell; yr[m > 0] = y
        print(os.path.basename(path), y, 'marsh share %.3f' % (m[cell > 0].mean() if cell.any() else 0), flush=True)
    wet = np.load(os.path.join(HERE, 'ring', 'wet.npy'))   # ring_osm.py: water and wetland today, from our basemap
    # the city keeps its own layer
    city = np.zeros((NY, NX), np.uint8)
    bor = json.load(open(os.path.join(HERE, '..', '_maplab', 'bathy', 'nyc_boroughs.json')))
    geoms = [shape(f['geometry']) for f in bor['features']] if 'features' in bor else [shape(bor)]
    features.rasterize(((g, 1) for g in geoms), out=city, transform=T)
    city = cv2.dilate(city, np.ones((7, 7), np.uint8))     # a seam of ~25 m so the two layers meet, not overlap
    ghost = (old == 1) & (wet == 0) & (city == 0)
    g = ghost.astype(np.uint8)
    g = cv2.morphologyEx(g, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    # SMOOTH, LIKE THE CITY'S (2026-11-22, first look: stair-stepped pixel edges, and holes punched by the sheets' lettering and rail
    # lines): pin-holes under ~0.5 ha are filled (an upland island is kept), then the edge is blurred and re-cut at half, so the
    # outline follows the marsh, not the grid
    from skimage.morphology import remove_small_holes
    g = remove_small_holes(g > 0, area_threshold=80).astype(np.float32)
    g = (cv2.GaussianBlur(g, (0, 0), 2.2) > .5).astype(np.uint8)
    np.save(os.path.join(HERE, 'ring', 'ghost.npy'), g)
    to84 = pyproj.Transformer.from_crs(NAD27, 'EPSG:4326', always_xy=True).transform
    geod = pyproj.Geod(ellps='WGS84'); out = []
    for geom, v in features.shapes(g, mask=g > 0, transform=T, connectivity=8):
        p = chaikin(shape(geom).simplify(RES * 1.1)).simplify(RES * 0.35)
        if p.is_empty: continue
        p = shp_transform(to84, p)
        a = abs(geod.geometry_area_perimeter(p)[0])
        if a < 4000: continue                                  # under ~ a city block: a speck, not a marsh
        c = p.representative_point(); cy, cx = int((N0 - c.y) / RES), int((c.x - W0) / RES)
        y = int(yr[min(NY - 1, max(0, cy)), min(NX - 1, max(0, cx))]) or 1897
        p = Polygon([(round(x, 5), round(yy, 5)) for x, yy in p.exterior.coords], [[(round(x, 5), round(yy, 5)) for x, yy in r.coords] for r in p.interiors if Polygon(r).area > RES * RES * 30])
        out.append({'type': 'Feature', 'properties': {'area_m2': int(a), 'boro': 'beyond the city', 'src': 'USGS %d' % y}, 'geometry': mapping(p)})
    fc = {'type': 'FeatureCollection', 'features': out}
    json.dump(fc, open(os.path.join(HERE, 'ring', 'ghost_ring.json'), 'w'), separators=(',', ':'))
    print('features', len(out), 'km2 %.1f' % (sum(f['properties']['area_m2'] for f in out) / 1e6))

if __name__ == '__main__':
    main()
