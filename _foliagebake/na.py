#!/usr/bin/env python3
"""FALL FOLIAGE FOR NORTH AMERICA (user 2026-10-17: "can you do what weve done for northeast foliage for north america?").

THE NORTHEAST TAB'S METHOD, unchanged (_maplab/foliage_bake.py): NASA GIBS MODIS_Terra_NDVI_8Day (250 m rolling composite)
decoded through the GIBS colormap; current = max of the newest composite and the one six days earlier (THE CLOUD RULE:
never difference one composite); baseline = max of the August composites; progress = 1 - current/baseline, only on forest
(MODIS IGBP land cover: the five forest classes and woody savanna) where August greenness > 0.55; a 5-px median; the same
peak-centred colour ramp (green -> yellow -> orange at 20% = peak -> red -> brown 40%+ bare).

Cut into a tile pyramid instead of one frame: computed at z8 (~600 m at 45 N), in 2048 px blocks over 24-70 N, -170..-52, then z3-7 by averaging. Blocks with no
forest are skipped. The August baseline and the forest mask are fixed for the season, so each is cached per block as a
.npz (BASE_DIR) and only the two current composites are fetched daily.
Plus the USA-NPN "colored leaves" reports of the last fortnight for every state (points.json).

THE UPSTATE VIEW'S NUMBERS, NATIONALLY (2026-10-17: the national FOLIAGE view should match THE CITY's UPSTATE FOLIAGE).
Each the Northeast bake's own function, run over the progress grids instead of the one frame:
  regions      REGIONS boxes (the Northeast's twelve, same names and boxes, plus the country's well-known color drives),
               mean progress over forest pixels (region_means), delta7 against the history row a week back, band() relative
               to last year's peak level (peak_of on the weekly curve of last season)
  history      one row per bake day, carried forward from yesterday's meta.json (90 rows)
  counties     county_means over a county label grid (l_*.npz in BASE, rasterised once from foliage/na/counties.json)
  last_year, counties_ly, season_last   last season's weekly frames, baked once by na_season.py, carried forward
  season_this  this season's weekly frames; archive_this_season() copies today's pyramid to season/<year>/<date>/ when a
               week has passed since the last one
  forest       USFS FIA Forest Type Groups tiles (na_forest.py, once a season), carried forward
  species      FHTET species leaders as tiles (na_species.py, once a season), carried forward
Everything carried forward is also kept in BASE/carry.json (the cached base dir), so a day the CDN cannot be read does not
drop the season.

    python3 na.py OUT [BASE_DIR] [SEED_DIR]   -> OUT/{z}/{x}/{y}.webp, OUT/meta.json, OUT/season/<year>/<date>/... (weekly)
SEED_DIR (optional): season_<year>.json from na_season.py and forest_meta.json from na_forest.py, read when yesterday's
meta.json does not carry them yet.
"""
import datetime, io, json, math, os, re, shutil, sys, time, urllib.request
import numpy as np
from PIL import Image, ImageFilter, ImageDraw
from concurrent.futures import ThreadPoolExecutor

WMS = 'https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi'
LAYER = 'MODIS_Terra_NDVI_8Day'
CMAP = 'https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_NDVI.xml'
CDN = 'https://cdn.bluishvoid.com/foliage/na/'
IGBP_LAYER = 'MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual'
IGBP_RGB = {1: (33, 138, 33), 2: (49, 204, 49), 3: (152, 204, 49), 4: (150, 250, 150), 5: (141, 186, 141),
            6: (186, 141, 141), 7: (245, 222, 179), 8: (218, 235, 157), 9: (255, 213, 0), 10: (240, 185, 103),
            11: (71, 131, 181), 12: (250, 239, 115), 13: (255, 0, 0), 14: (153, 147, 86), 15: (255, 255, 255),
            16: (191, 191, 189), 17: (134, 202, 227), 255: (100, 100, 100)}
# FOREST THAT TURNS: deciduous needleleaf (larch, tamarack -- gold), deciduous broadleaf, mixed. The Northeast tab also
# counts evergreen needleleaf and woody savanna, harmless in its box; across the boreal belt they are spruce and pine, and
# their autumn greenness drop is low sun and first snow, which painted Canada and Alaska red as if past peak.
IGBP_FOREST = {3, 4, 5}
RAMP = [(0.0, (34, 120, 40)), (0.08, (150, 190, 40)), (0.15, (240, 200, 40)),
        (0.20, (235, 120, 30)), (0.28, (200, 40, 30)), (0.40, (120, 60, 30)), (1.01, (90, 45, 25))]
RAMP_LEGEND = [(0, '0%'), (8, '8%'), (15, '15%'), (20, '20% PEAK'), (28, '28%'), (40, '40%+ BARE')]
STATES = ['AL','AZ','AR','CA','CO','CT','DE','FL','GA','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT',
          'NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','AK','DC']
CLASSES = {'Less than 5%': 0, '5-24%': 1, '25-49%': 2, '50-74%': 3, '75-94%': 4, '95% or more': 5}
# z8 (~600 m at 45 N; was z7, blocky past z9 -- 2026-10-17)
Z = 8; BLK = 2048; R = 6378137.0; WORLD = 2 * math.pi * R
LON0, LON1, LAT0, LAT1 = -170.0, -52.0, 24.0, 70.0
AUG_DAYS = (8, 16, 24, 31)
SEASON_START, SEASON_END = (9, 15), (12, 1)

# THE REGIONS (name, west, east, south, north) -- the Northeast bake's tuple order. The first twelve are its REGIONS,
# same names and boxes; the rest are the country's and southern Canada's well-known fall-color drives, each box drawn
# over the forest rather than the towns. Dropped after the first bake for holding almost no forest the mask can see
# (deciduous IGBP classes plus the FIA western golds): the Black Hills (18 pixels: ponderosa), the North Cascades and
# Kananaskis (alpine larch is untyped; 90 and 51 pixels), the Eastern Sierra (no block). PRI is the label priority (the page's queue drops the lowest first).
REGIONS = [('Adirondacks', -74.6, -73.6, 43.6, 44.4), ('Catskills', -74.7, -74.0, 41.9, 42.3),
           ('Shawangunks', -74.35, -74.15, 41.65, 41.82),
           ('Hudson Valley', -74.0, -73.6, 41.2, 41.8), ('Litchfield Hills', -73.4, -73.0, 41.7, 42.0),
           ('Berkshires', -73.4, -72.9, 42.1, 42.7), ('Poconos', -75.6, -75.0, 41.0, 41.4),
           ('Delaware Water Gap', -75.2, -74.9, 40.9, 41.2), ('Finger Lakes', -77.3, -76.3, 42.3, 42.9),
           ('Green Mountains', -73.1, -72.6, 43.0, 44.3), ('White Mountains', -71.7, -71.0, 43.9, 44.4),
           ('New York City & Long Island', -74.1, -72.2, 40.6, 41.0),
           # New England, New York and Pennsylvania
           ('Northeast Kingdom', -72.3, -71.5, 44.4, 45.0), ('Western Maine Mountains', -71.0, -70.2, 44.6, 45.2),
           ('Maine Highlands', -70.2, -69.0, 45.3, 46.0), ('Acadia', -68.5, -68.1, 44.25, 44.45),
           ('Mohawk Trail', -73.1, -72.6, 42.55, 42.75), ('Allegheny National Forest', -79.4, -78.7, 41.4, 41.95),
           ('Pennsylvania Wilds', -78.4, -77.4, 41.2, 41.8), ('Laurel Highlands', -79.6, -79.0, 39.75, 40.3),
           # Appalachians and the South
           ('Shenandoah', -78.8, -78.2, 38.2, 38.9), ('West Virginia Highlands', -80.2, -79.4, 38.3, 39.2),
           ('New River Gorge', -81.2, -80.85, 37.85, 38.15), ('Blue Ridge Parkway', -80.5, -79.3, 36.6, 37.6),
           ('NC High Country', -82.0, -81.3, 35.9, 36.35), ('Asheville & Pisgah', -82.9, -82.3, 35.2, 35.7),
           ('Great Smoky Mountains', -84.0, -83.1, 35.45, 35.8), ('North Georgia Mountains', -84.6, -83.4, 34.5, 35.0),
           ('Cumberland Plateau', -85.6, -84.5, 35.6, 36.6), ('Red River Gorge', -83.8, -83.5, 37.7, 37.9),
           ('Hocking Hills', -82.7, -82.3, 39.35, 39.6), ('Brown County', -86.4, -86.0, 39.0, 39.3),
           ('Shawnee Hills', -89.0, -88.2, 37.3, 37.7), ('Missouri Ozarks', -92.5, -90.5, 36.8, 37.8),
           ('Arkansas Ozarks', -94.0, -91.5, 35.6, 36.4), ('Ouachita Mountains', -94.7, -93.0, 34.3, 34.9),
           # the Great Lakes and the Upper Midwest
           ('Upper Peninsula', -89.9, -85.0, 45.9, 46.9), ('Keweenaw', -88.8, -87.8, 46.9, 47.5),
           ('Northern Michigan', -86.2, -84.4, 44.3, 45.4), ('Door County', -87.6, -86.9, 44.8, 45.3),
           ('Northwoods', -90.5, -88.8, 45.5, 46.3), ('North Shore', -92.0, -89.6, 46.8, 47.9),
           ('Boundary Waters', -92.2, -90.3, 47.7, 48.2), ('Driftless Area', -91.8, -90.6, 42.6, 44.0),
           # the West
           ('Colorado Front Range', -106.1, -105.3, 39.2, 39.9),
           ('Aspen & Maroon Bells', -107.2, -106.6, 38.9, 39.4), ('Crested Butte', -107.3, -106.8, 38.7, 39.0),
           ('San Juan Mountains', -108.2, -107.3, 37.5, 38.2), ('Sangre de Cristo', -105.9, -105.3, 35.6, 36.7),
           ('San Francisco Peaks', -111.8, -111.5, 35.2, 35.45), ('Wasatch Range', -111.9, -111.4, 40.3, 41.0),
           ('Fishlake', -111.9, -111.3, 38.4, 38.8), ('Grand Teton', -110.9, -110.4, 43.5, 44.1),
           ('Glacier', -114.4, -113.3, 48.3, 49.0), ('Columbia River Gorge', -122.3, -121.2, 45.5, 45.75),
           # southern Canada
           ('Laurentians', -75.0, -73.8, 45.9, 46.6), ('La Mauricie', -73.3, -72.6, 46.6, 47.2),
           ('Eastern Townships', -72.8, -71.3, 45.0, 45.6), ('Charlevoix', -71.0, -70.0, 47.3, 47.9),
           ('Gatineau Park', -76.1, -75.7, 45.45, 45.7), ('Algonquin', -79.0, -77.6, 45.3, 46.1),
           ('Muskoka', -79.9, -78.9, 44.8, 45.4), ('Algoma', -84.8, -84.0, 46.9, 47.6),
           ('Fundy', -65.5, -64.8, 45.5, 45.8), ('Cape Breton Highlands', -61.1, -60.3, 46.3, 47.0)]
PRI = {'Adirondacks': 78, 'Catskills': 78, 'New York City & Long Island': 76, 'Hudson Valley': 74,
       'Green Mountains': 72, 'White Mountains': 72, 'Berkshires': 70, 'Finger Lakes': 70,
       'Poconos': 68, 'Litchfield Hills': 64, 'Delaware Water Gap': 64, 'Shawangunks': 62,
       'Great Smoky Mountains': 80, 'Blue Ridge Parkway': 78, 'Shenandoah': 76, 'Upper Peninsula': 74,
       'Aspen & Maroon Bells': 74, 'Arkansas Ozarks': 70, 'Missouri Ozarks': 66, 'Door County': 70,
       'North Shore': 70, 'Laurentians': 72, 'Algonquin': 72, 'Cape Breton Highlands': 70, 'Grand Teton': 70,
       'Wasatch Range': 66, 'Colorado Front Range': 66,
       'Glacier': 66, 'Northeast Kingdom': 64, 'Asheville & Pisgah': 66, 'NC High Country': 64, 'Muskoka': 66,
       'West Virginia Highlands': 64, 'Acadia': 66, 'Columbia River Gorge': 62, 'San Juan Mountains': 64,
       'Northern Michigan': 64, 'Eastern Townships': 62, 'Charlevoix': 60, 'Gatineau Park': 58,
       'Northwoods': 60, 'Boundary Waters': 60, 'Driftless Area': 58, 'Crested Butte': 60, 'Sangre de Cristo': 60,
       'Hocking Hills': 58, 'Brown County': 56, 'Red River Gorge': 56, 'Cumberland Plateau': 56,
       'North Georgia Mountains': 60, 'Pennsylvania Wilds': 60, 'Allegheny National Forest': 58,
       'Laurel Highlands': 58, 'New River Gorge': 60, 'Keweenaw': 60, 'Western Maine Mountains': 60,
       'Maine Highlands': 60, 'Mohawk Trail': 56, 'Shawnee Hills': 54, 'Ouachita Mountains': 56,
       'San Francisco Peaks': 58, 'Fishlake': 54, 'La Mauricie': 56, 'Algoma': 58, 'Fundy': 56,}
RNAMES = {r[0] for r in REGIONS}
ANCHOR = {'Hudson Valley': (41.78, -73.93), 'Shawangunks': (41.72, -74.42), 'Catskills': (42.12, -74.45),
          'New York City & Long Island': (40.74, -73.45)}
BANDS = [(0, 'NOT YET'), (8, 'STARTING'), (15, 'NEAR PEAK'), (20, 'PEAK'), (30, 'PAST PEAK')]
REL = [(0.0, 'NOT YET'), (0.35, 'STARTING'), (0.75, 'NEAR PEAK'), (0.95, 'PEAK'), (1.3, 'PAST PEAK')]
PEAK_RISE = 8.0     # points of index in a week: the colour phase's steep week
PEAK_FRAC = 0.40    # share of the season's whole loss
# a county needs this many forest pixels for a block: the Northeast's 400 at its 922 m frame pixel, as the same ground at z8
COUNTY_MIN_PX = 900


def get(u, timeout=240):
    for a in range(4):
        try: return urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluishvoid.com foliage bake'}), timeout=timeout).read()
        except Exception:
            if a == 3: raise
            time.sleep(2 + 3 * a)

def colormap():
    x = get(CMAP).decode('utf-8', 'replace')
    ents = re.findall(r'<ColorMapEntry[^>]*rgb="(\d+),(\d+),(\d+)"[^>]*value="\[?([-\d.]+)', x)
    lut = {}
    for r, g, b, v in ents: lut[(int(r) << 16) | (int(g) << 8) | int(b)] = float(v)
    return lut

def tile_pxf(lon, lat):
    n = 256 * 2 ** Z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n

def tile_px(lon, lat):
    x, y = tile_pxf(lon, lat)
    return int(x), int(y)

def bbox_of(px0, py0, w, h):
    n = 256 * 2 ** Z; mpp = WORLD / n
    return (-WORLD / 2 + px0 * mpp, WORLD / 2 - (py0 + h) * mpp, -WORLD / 2 + (px0 + w) * mpp, WORLD / 2 - py0 * mpp)

def all_blocks():
    x0, y0 = tile_px(LON0, LAT1); x1, y1 = tile_px(LON1, LAT0)
    return [(bx, by) for bx in range(x0 // BLK * BLK, x1, BLK) for by in range(y0 // BLK * BLK, y1, BLK)]

def wms(layer, bb, w, h, time_):
    u = (WMS + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=%s&CRS=EPSG:3857&BBOX=%.0f,%.0f,%.0f,%.0f&WIDTH=%d&HEIGHT=%d&FORMAT=image/png&TIME=%s'
         % ((layer,) + bb + (w, h, time_)))
    return np.array(Image.open(io.BytesIO(get(u))).convert('RGB')).astype(np.uint32)

LUT = None
def ndvi(bb, w, h, date):
    global LUT
    if LUT is None: LUT = colormap()
    a = wms(LAYER, bb, w, h, date.isoformat())
    key = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
    uk, inv = np.unique(key, return_inverse=True)
    vals = np.array([LUT.get(int(k), np.nan) for k in uk], np.float32)
    return vals[inv].reshape(key.shape)

# THE WESTERN GOLDS (2026-10-17). MODIS IGBP at 500 m calls almost none of the Rockies' aspen deciduous -- the Colorado
# block held 489 forest pixels in four million and was skipped, so the aspens, the Wasatch and the Tetons had no index.
# The Northeast bake's own mask in the US is the Forest Service's typed forest (FIA Forest Type Groups, 250 m); its two
# groups that turn and that IGBP misses, Aspen/Birch and Western Larch, are added to the IGBP mask across CONUS. The
# evergreen groups stay out, for the reason IGBP_FOREST gives.
FTG = ('https://imagery.geoplatform.gov/iipp/rest/services/Vegetation/'
       'USFS_EDW_FIA_ForestAtlas_ForestTypeGroups_109_CONUS/ImageServer')
FTG_EXTENT = (-14244268.17, 2608755.24, -7264768.17, 6737255.24)
FIA_GOLD = ('Aspen/Birch Group', 'Western Larch Group')
_FTG_COLS = None

def ftg_colors():
    """{legend label: rgb} from the image service's legend swatches (the Northeast bake's forest() reading)"""
    global _FTG_COLS
    if _FTG_COLS is None:
        import base64
        cols = {}
        for L in json.loads(get(FTG + '/legend?f=json', 60)).get('layers', []):
            for it in L.get('legend', []):
                a = np.array(Image.open(io.BytesIO(base64.b64decode(it['imageData']))).convert('RGB')).reshape(-1, 3)
                v, c = np.unique(a, axis=0, return_counts=True)
                cols[it.get('label')] = tuple(int(x) for x in v[c.argmax()])
        _FTG_COLS = cols
    return _FTG_COLS

def ftg_rgb(bb, w, h):
    u = (FTG + '/exportImage?bbox=%.0f,%.0f,%.0f,%.0f&bboxSR=3857&imageSR=3857&size=%d,%d&format=png'
         '&interpolation=RSP_NearestNeighbor&f=image' % (bb + (w, h)))
    return np.array(Image.open(io.BytesIO(get(u, 240))).convert('RGB'))

def fia_gold(bb, w, h):
    if bb[2] < FTG_EXTENT[0] or bb[0] > FTG_EXTENT[2] or bb[3] < FTG_EXTENT[1] or bb[1] > FTG_EXTENT[3]: return None
    try:
        a = ftg_rgb(bb, w, h); cols = ftg_colors()
    except Exception as e:
        print('fia: unavailable (%s)' % e); return None
    m = np.zeros(a.shape[:2], bool)
    for lab in FIA_GOLD:
        c = cols.get(lab)
        if c: m |= (a[..., 0] == c[0]) & (a[..., 1] == c[1]) & (a[..., 2] == c[2])
    return m

def forest(bb, w, h):
    ok = igbp_forest(bb, w, h); g = fia_gold(bb, w, h)
    if g is None: return ok
    return g if ok is None else (ok | g)

def igbp_forest(bb, w, h):
    yr = datetime.date.today().year
    for year in range(yr - 1, yr - 5, -1):
        try: a = wms(IGBP_LAYER, bb, w, h, '%d-01-01' % year).astype(np.int32)
        except Exception: continue
        ks = list(IGBP_RGB); pal = np.array([IGBP_RGB[k] for k in ks], np.int32)
        key = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
        uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        rgb = np.stack([(uk >> 16) & 255, (uk >> 8) & 255, uk & 255], 1)
        d = ((rgb[:, None, :] - pal[None, :, :]) ** 2).sum(2)
        cls = np.array(ks)[d.argmin(1)]; near = d.min(1) <= 3 * 144; ok = near & np.isin(cls, list(IGBP_FOREST))
        if (cnt * (near & (cls != 255))).sum() > 0.02 * key.size: return ok[inv].reshape(key.shape)   # a year not yet published comes back blank
    return None

def published(probe_bb, start, back=10):
    d = start
    for _ in range(back):
        try:
            v = ndvi(probe_bb, 64, 64, d)
            if np.isfinite(v).mean() > 0.2: return d
        except Exception: pass
        d -= datetime.timedelta(days=1)
    return None

def ramp(p, alpha=0.78):
    h, w = p.shape; img = np.zeros((h, w, 4), np.uint8); m = np.isfinite(p)
    for i in range(len(RAMP) - 1):
        a, ca = RAMP[i]; b, cb = RAMP[i + 1]; sel = m & (p >= a) & (p < b)
        if not sel.any(): continue
        t = ((p - a) / (b - a))[sel][:, None]
        img[sel, :3] = np.clip(np.array(ca) * (1 - t) + np.array(cb) * t, 0, 255).astype(np.uint8); img[sel, 3] = int(255 * alpha)
    return img


# ---------------------------------------------------------------- the per-block pieces (shared with na_season.py)
def baseline(bb, aug):
    base = None
    for d in aug:
        try: v = ndvi(bb, BLK, BLK, d)
        except Exception: continue
        base = v if base is None else np.fmax(base, v)
    return base

def progress(bb, base, fm, dates):
    """the index on one block: 1 - max(current composites)/baseline on forest, the 5-px median; None if no composite"""
    cur = None
    for d in dates:
        if not d: continue
        try: v = ndvi(bb, BLK, BLK, d)
        except Exception: continue
        cur = v if cur is None else np.fmax(cur, v)
    if cur is None: return None
    with np.errstate(invalid='ignore', divide='ignore'): p = 1 - cur / base
    p = np.where(np.isfinite(p) & (base > 0.55) & fm, np.clip(p, 0, 1), np.nan)
    pm = np.where(np.isfinite(p), p, -1).astype(np.float32)
    med = np.array(Image.fromarray((np.clip(pm, 0, 1) * 250 + 2).astype(np.uint8)).filter(ImageFilter.MedianFilter(5))).astype(np.float32)
    return np.where(np.isfinite(p), (med - 2) / 250, np.nan)

def to_u8(p):
    return np.nan_to_num(p * 250, nan=255).astype(np.uint8)

def from_u8(a):
    a = a.astype(np.float32); a[a == 255] = np.nan; return a / 250

def block_tiles(p, bx, by, out):
    img = ramp(p); n = 0
    for i in range(BLK // 256):
        for j in range(BLK // 256):
            sub = img[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256]
            if sub[..., 3].max() == 0: continue
            tx, ty = (bx // 256) + i, (by // 256) + j; pth = os.path.join(out, str(Z), str(tx)); os.makedirs(pth, exist_ok=True)
            Image.fromarray(sub).save(os.path.join(pth, '%d.webp' % ty), 'WEBP', quality=70, alpha_quality=80, method=4); n += 1
    return n

def pyramid(grids, out, zmin=3):
    """z7..zmin from the z8 progress grids ({(bx, by): path of a u8 .npy}): average the children's progress (ignoring
    non-forest), then the same ramp"""
    for zz in range(Z - 1, zmin - 1, -1):
        k = 2 ** (Z - zz); tiles = {}
        for (bx, by), f in grids.items():
            a = from_u8(np.load(f))
            h = BLK // k
            with np.errstate(invalid='ignore'), __import__('warnings').catch_warnings():
                __import__('warnings').simplefilter('ignore')
                s = np.nanmean(a.reshape(h, k, h, k).swapaxes(1, 2).reshape(h, h, k * k), 2)
            ox, oy = bx // k, by // k
            for i in range(0, h, 256):
                for j in range(0, h, 256):
                    tiles.setdefault(((ox + i) // 256, (oy + j) // 256), []).append((((ox + i) % 256, (oy + j) % 256), s[j:j + 256, i:i + 256]))
        n = 0
        for (tx, ty), parts in tiles.items():
            canv = np.full((256, 256), np.nan, np.float32)
            for (ix, iy), s in parts:
                hh, ww = s.shape; canv[iy:iy + hh, ix:ix + ww] = np.where(np.isfinite(s), s, canv[iy:iy + hh, ix:ix + ww])
            img = ramp(canv)
            if img[..., 3].max() == 0: continue
            pth = os.path.join(out, str(zz), str(tx)); os.makedirs(pth, exist_ok=True)
            Image.fromarray(img).save(os.path.join(pth, '%d.webp' % ty), 'WEBP', quality=70, alpha_quality=80, method=4); n += 1
        print('z%d: %d tiles' % (zz, n), flush=True)


# ---------------------------------------------------------------- regions and counties over the grids
def region_means(grids):
    """{name: (pct, past_peak)}: mean progress over the forest pixels in each box (the Northeast's region_means)"""
    out = {}
    for name, lo0, lo1, la0, la1 in REGIONS:
        x0, y0 = tile_pxf(lo0, la1); x1, y1 = tile_pxf(lo1, la0)
        vals = []
        for (bx, by), f in grids.items():
            ix0, ix1 = max(int(x0), bx), min(int(math.ceil(x1)), bx + BLK)
            iy0, iy1 = max(int(y0), by), min(int(math.ceil(y1)), by + BLK)
            if ix0 >= ix1 or iy0 >= iy1: continue
            a = np.load(f, mmap_mode='r')[iy0 - by:iy1 - by, ix0 - bx:ix1 - bx]
            vals.append(from_u8(np.asarray(a)).ravel())
        if not vals: continue
        v = np.concatenate(vals); v = v[np.isfinite(v)]
        if v.size < 50: continue
        out[name] = (int(round(100 * float(v.mean()))), int(round(100 * float((v >= 0.5).mean()))))
    return out

def county_labels(base_dir, counties=None, blocks=None):
    """per-block county label grids (int16; 0 = none, k = ids[k-1]) cached as l_bx_by.npz in base_dir (a 1-element
    array where no county reaches the block), plus l_ids.json; only blocks without an l_ file are rasterised"""
    idp = os.path.join(base_dir, 'l_ids.json')
    todo = [b for b in (blocks or []) if not os.path.exists(os.path.join(base_dir, 'l_%d_%d.npz' % b))]
    if os.path.exists(idp) and not todo:
        return json.load(open(idp))
    if counties is None:
        counties = json.loads(get(CDN + 'counties.json', 120))
    ids = json.load(open(idp)) if os.path.exists(idp) else sorted(counties)
    polys = []
    for k, fips in enumerate(ids, 1):
        for ring in (counties.get(fips) or {}).get('r', []):
            pts = [tile_pxf(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                polys.append((k, pts, min(xs), min(ys), max(xs), max(ys)))
    for bx, by in todo:
        im = Image.new('I', (BLK, BLK), 0); dr = ImageDraw.Draw(im); n = 0
        for k, pts, a, b, c, d in polys:
            if c < bx or a > bx + BLK or d < by or b > by + BLK: continue
            dr.polygon([(x - bx, y - by) for x, y in pts], fill=k); n += 1
        np.savez_compressed(os.path.join(base_dir, 'l_%d_%d.npz' % (bx, by)),
                            l=np.array(im, dtype=np.int16) if n else np.zeros(1, np.int16))
    json.dump(ids, open(idp, 'w'))
    return ids

def county_means(grids, base_dir, ids, min_px=COUNTY_MIN_PX):
    """Mean index per county over its forest pixels (the Northeast's county_means), summed across blocks"""
    sums = np.zeros(len(ids) + 1); cnt = np.zeros(len(ids) + 1)
    for (bx, by), f in grids.items():
        lp = os.path.join(base_dir, 'l_%d_%d.npz' % (bx, by))
        if not os.path.exists(lp): continue
        lab = np.load(lp)['l'].astype(np.int32)
        if lab.size == 1: continue
        p = from_u8(np.load(f))
        valid = np.isfinite(p) & (lab > 0)
        if not valid.any(): continue
        sums += np.bincount(lab[valid], weights=p[valid], minlength=len(ids) + 1)
        cnt += np.bincount(lab[valid], minlength=len(ids) + 1)
    return {fips: int(round(100 * sums[k] / cnt[k])) for k, fips in enumerate(ids, 1) if cnt[k] >= min_px}


def band(pct, peak_level=None):
    if peak_level:
        out = REL[0][1]
        for f, name in REL:
            if pct >= f * peak_level: out = name
        return out
    out = BANDS[0][1]
    for lo, name in BANDS:
        if pct >= lo: out = name
    return out

def peak_of(dates, arr):
    """(date, level) of peak color on last year's weekly curve -- the Northeast bake's peak_of, unchanged: the first week
    the index rises PEAK_RISE points, or the day PEAK_FRAC of the season's whole loss is in, whichever comes first"""
    pts = [(dt, x) for dt, x in zip(dates, arr) if x is not None]
    if len(pts) < 4: return None, None
    ds = [datetime.date.fromisoformat(d) for d, _ in pts]; xs = [x for _, x in pts]
    total = xs[-1] - xs[0]
    if total <= 3: return None, None
    cand = []
    for i in range(1, len(xs)):
        if xs[i] - xs[i - 1] >= PEAK_RISE:
            cand.append((ds[i], xs[i])); break
    for i in range(1, len(xs)):
        if xs[i] - xs[0] >= PEAK_FRAC * total:
            a, b = xs[i - 1] - xs[0], xs[i] - xs[0]
            f = (PEAK_FRAC * total - a) / (b - a) if b > a else 0.0
            day = ds[i - 1] + datetime.timedelta(days=round(7 * f))
            cand.append((day, xs[i - 1] + (xs[i] - xs[i - 1]) * f)); break
    if not cand: return None, None
    day, lvl = min(cand)
    return day.isoformat(), int(round(lvl))

def season_dates(year, upto=None):
    d = datetime.date(year, *SEASON_START); out = []
    while d <= datetime.date(year, *SEASON_END) and (upto is None or d <= upto):
        out.append(d); d += datetime.timedelta(days=7)
    return out


def npn(today):
    a = (today - datetime.timedelta(days=14)).isoformat(); best = {}
    for k in range(0, len(STATES), 10):
        q = 'start_date=%s&end_date=%s&phenophase_id[0]=498&request_src=bluishvoid_foliage' % (a, today.isoformat())
        q += ''.join('&state[%d]=%s' % (i, s) for i, s in enumerate(STATES[k:k + 10]))
        try: rows = json.loads(get('https://services.usanpn.org/npn_portal/observations/getObservations.json?' + q))
        except Exception as e: print('npn: part failed', e); continue
        for r in rows:
            if str(r.get('phenophase_status')) != '1': continue
            cls = CLASSES.get(r.get('intensity_value'))
            if cls is None: continue
            try: la, lo = float(r['latitude']), float(r['longitude'])
            except Exception: continue
            key = (round(la, 3), round(lo, 3)); d = str(r.get('observation_date') or ''); cur = best.get(key)
            if cur is None or d > cur[3] or (d == cur[3] and cls > cur[2]):
                best[key] = [round(la, 4), round(lo, 4), cls, d, str(r.get('common_name') or '')]
    pts = sorted(best.values(), key=lambda p: (-p[2], p[3]))[:3000]
    print('npn:', len(pts), 'sites'); return pts

def previous():
    try: return json.loads(get(CDN + 'meta.json?v=%d' % int(time.time()), 60))
    except Exception as e:
        print('previous meta.json unavailable (%s)' % e); return {}

def archive_this_season(today, prev, out):
    """One frame a week of the current season under season/<year>/<date>/: today's pyramid is copied there when a week
    has passed since the last one (the Northeast's archive_this_season, as a tile pyramid)"""
    have = [x for x in (((prev or {}).get('season_this') or {}).get('dates') or []) if x[:4] == str(today.year)]
    last = max(have) if have else None
    if (last is None or (today - datetime.date.fromisoformat(last)).days >= 7) and datetime.date(today.year, *SEASON_START) <= today <= datetime.date(today.year, *SEASON_END):
        dst = os.path.join(out, 'season', str(today.year), today.isoformat())
        for zz in range(3, Z + 1):
            if os.path.isdir(os.path.join(out, str(zz))):
                shutil.copytree(os.path.join(out, str(zz)), os.path.join(dst, str(zz)), dirs_exist_ok=True)
        have.append(today.isoformat()); print('season: archived', today.isoformat())
    return {'year': today.year, 'dates': sorted(set(have)), 'base': CDN + 'season/%d/' % today.year}


def main():
    OUT = sys.argv[1]; BASE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(OUT, '..', 'foliage_base')
    SEED = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(OUT, exist_ok=True); os.makedirs(BASE, exist_ok=True)
    today = datetime.date.today(); yr = today.year
    probe = bbox_of(*tile_px(-74.5, 44.0), 64, 64)
    # two days back (2026-10-17): the newest rolling composite is still being filled in on GIBS -- a straight seam along a
    # GIBS tile edge at -73.1 (Vermont) where neighbouring tiles held different days
    d1 = published(probe, today - datetime.timedelta(days=2)); d2 = published(probe, d1 - datetime.timedelta(days=6)) if d1 else None
    print('composites', d1, d2)
    aug = [datetime.date(yr, 8, d) for d in AUG_DAYS]
    blocks = all_blocks()
    def work(b):
        bx, by = b; bb = bbox_of(bx, by, BLK, BLK); cache = os.path.join(BASE, 'b_%d_%d.npz' % (bx, by))
        if os.path.exists(cache):
            z = np.load(cache); base = z['base'].astype(np.float32) / 250; fm = z['forest']
            if base.size == 1: return 0
        else:
            fm = forest(bb, BLK, BLK)
            if fm is None or fm.mean() < 0.002: np.savez_compressed(cache, base=np.zeros(1, np.uint8), forest=np.zeros(1, bool)); return 0
            base = baseline(bb, aug)
            if base is None: return 0
            np.savez_compressed(cache, base=np.nan_to_num(np.clip(base, 0, 1) * 250).astype(np.uint8), forest=fm)
            base = np.round(np.nan_to_num(np.clip(base, 0, 1)) * 250) / 250
        p = progress(bb, base, fm, (d1, d2))
        if p is None: return 0
        np.save(os.path.join(BASE, 'p_%d_%d.npy' % (bx, by)), to_u8(p))
        n = block_tiles(p, bx, by, OUT)
        print('block', bx, by, n, 'tiles', flush=True); return n
    with ThreadPoolExecutor(4) as ex: tot = sum(ex.map(work, blocks))
    grids = {}
    for f in os.listdir(BASE):
        if f.startswith('p_') and f.count('_') == 2:
            bx, by = map(int, f[2:-4].split('_')); grids[(bx, by)] = os.path.join(BASE, f)
    pyramid(grids, OUT)

    # ---- the upstate view's numbers
    prev = previous()
    carry_p = os.path.join(BASE, 'carry.json')
    carry = json.load(open(carry_p)) if os.path.exists(carry_p) else {}
    def seed(name):
        p = os.path.join(SEED, name) if SEED else None
        return json.load(open(p)) if p and os.path.exists(p) else None
    def carried(key):
        return prev.get(key) or carry.get(key)
    try:
        ids = county_labels(BASE, blocks=sorted(grids))
        counties_now = county_means(grids, BASE, ids)
    except Exception as e:
        print('counties: unavailable (%s)' % e); counties_now = {}
    print('counties:', len(counties_now), 'with a reading')
    means = region_means(grids)
    # last season: the weekly curves, carried forward once na_season.py has made them
    ly = carried('last_year'); counties_ly = carried('counties_ly'); season_last = carried('season_last')
    s_ly = seed('season_%d.json' % (yr - 1))
    if s_ly and not (ly and ly.get('year') == yr - 1 and all(n in ly.get('regions', {}) for n, *_ in REGIONS)):
        ly = {'year': yr - 1, 'dates': s_ly['dates'], 'regions': {n: v for n, v in s_ly['regions'].items() if n in RNAMES}}
        counties_ly = {'year': yr - 1, 'dates': s_ly['dates'], 'by': s_ly['counties']}
        season_last = {'year': yr - 1, 'dates': s_ly['dates'], 'base': CDN + 'season/%d/' % (yr - 1)}
    # this season: the backfilled weeks seed the history and the archive list
    hist = [h for h in (carried('history') or []) if h.get('date') and h['date'] != today.isoformat()]
    season_this_prev = carried('season_this')
    s_this = seed('season_%d.json' % yr)
    if s_this:
        have = {h['date'] for h in hist}
        for i, d in enumerate(s_this['dates']):
            if d not in have:
                hist.append({'date': d, 'pct': {n: arr[i] for n, arr in s_this['regions'].items() if arr[i] is not None and n in RNAMES}})
        st_dates = sorted(set(((season_this_prev or {}).get('dates') or []) + s_this['dates']))
        season_this_prev = {'year': yr, 'dates': st_dates, 'base': CDN + 'season/%d/' % yr}
    hist.sort(key=lambda h: h['date'])
    hist = hist[-89:]
    hist.append({'date': today.isoformat(), 'pct': {n: v[0] for n, v in means.items()}})
    season_this = archive_this_season(today, {'season_this': season_this_prev}, OUT)
    week_ago = (today - datetime.timedelta(days=7)).isoformat()
    older = [h for h in hist if h['date'] <= week_ago]
    ref = older[-1]['pct'] if older else None
    regions = []
    for name, lo0, lo1, la0, la1 in REGIONS:
        if name not in means: continue
        pct, past = means[name]
        pk_date, pk_level = (None, None)
        if ly and ly.get('regions', {}).get(name):
            pk_date, pk_level = peak_of(ly['dates'], ly['regions'][name])
        alat, alon = ANCHOR.get(name, ((la0 + la1) / 2, (lo0 + lo1) / 2))
        regions.append({'name': name, 'lat': round(alat, 3), 'lon': round(alon, 3), 'box': [lo0, la0, lo1, la1],
                        'pri': PRI.get(name, 60), 'pct': pct, 'past_peak': past, 'band': band(pct, pk_level),
                        'delta7': ((pct - ref[name]) if (ref and name in ref) else None),
                        'peak_last_year': pk_date, 'peak_level': pk_level})
    fdoc = carried('forest') or seed('forest_meta.json') or {}
    sdoc = carried('species') or seed('species_meta.json') or {}
    keep = {'history': hist, 'last_year': ly, 'counties_ly': counties_ly, 'season_last': season_last,
            'season_this': season_this, 'forest': fdoc or None, 'species': sdoc or None}
    pts = npn(today)
    doc = {'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'composites': [str(d1), str(d2)],
           'baseline': [str(d) for d in aug], 'points': pts, 'ramp': RAMP_LEGEND, 'ramp_stops': RAMP,
           'regions': regions, 'bands': BANDS, 'rel_bands': REL,
           'history': hist, 'last_year': ly,
           'counties': counties_now, 'counties_url': CDN + 'counties.json', 'counties_ly': counties_ly,
           'season_last': season_last, 'season_this': season_this,
           'forest': fdoc or None, 'forest_url': fdoc.get('url'), 'forest_legend': fdoc.get('legend'),
           'forest_roles': fdoc.get('roles'),
           'species': sdoc or None, 'species_url': sdoc.get('url'), 'species_legend': sdoc.get('legend')}
    json.dump(doc, open(os.path.join(OUT, 'meta.json'), 'w'), separators=(',', ':'))
    json.dump(keep, open(carry_p, 'w'), separators=(',', ':'))
    print('tiles z8', tot, '| regions', len(regions), '| counties', len(counties_now), '| history', len(hist),
          '| season_last', len((season_last or {}).get('dates') or []), '| season_this', len(season_this['dates']))


if __name__ == '__main__':
    main()
