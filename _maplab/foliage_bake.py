#!/usr/bin/env python3
"""
THE FOLIAGE TAB'S BAKE (2026-09-13). One PNG in the 12-hour view's frame -- how
far each pixel's greenness has fallen from its own August peak, as a colour
ramp (green, yellow, orange, red, brown = 0 to 50%+) -- plus a small JSON with
the date, regional means and the last fortnight's USA-NPN "colored leaves"
reports as points. Uploaded to R2 at foliage/latest.{png,json}; the page
draws the PNG as a single wide-view frame over our own basemap.

Sources, both public: NASA GIBS MODIS_Terra_NDVI_8Day (250 m; on GIBS this is
the near-real-time ROLLING 8-day composite, one per day, keyed by the day it
ends -- 2026-09-06 and 2026-09-12 differ) decoded through the GIBS colormap; USA-NPN observations (phenophase 498 "Colored leaves",
`state[]` filters -- the bbox parameters return nothing).

THE CLOUD RULE: never difference one composite. 2026-09-06 read the
Adirondacks a third low under solid cloud while the weeks either side read
normal. current = max of the latest two published composites; baseline = max
of the August composites; progress = 1 - current/baseline, only where the
baseline says forest (> 0.45).

    python3 _maplab/foliage_bake.py [outdir]          # writes latest.png + latest.json
"""
import datetime, io, json, math, os, re, sys, time, urllib.parse, urllib.request
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '_foliage_out')
os.makedirs(OUT, exist_ok=True)
BOX = (-8927823, 4607718, -7636517, 5716479)        # the 12-hour view, EPSG:3857
W, H = 1400, 1202
LAYER = 'MODIS_Terra_NDVI_8Day'
WMS = 'https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi'
CMAP = 'https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_NDVI.xml'
STATES = ['NY', 'NJ', 'CT', 'MA', 'VT', 'NH', 'PA', 'RI', 'ME']
R = 6378137.0


def get(u, timeout=120):
    req = urllib.request.Request(u, headers={'User-Agent': 'bluishvoid.com foliage bake'})
    return urllib.request.urlopen(req, timeout=timeout).read()


def latest_two(today, keys, vals):
    """The newest published rolling composite, and the one about six days
    before it (two windows that barely overlap, so a cloudy week cannot fool
    both). Returns [(date, ndvi)...], newest first."""
    out = []
    d = today
    for _ in range(10):
        v = ndvi(d, keys, vals)
        if v is not None:
            out.append((d, v))
            break
        d -= datetime.timedelta(days=1)
    if out:
        d = out[0][0] - datetime.timedelta(days=6)
        for _ in range(6):
            v = ndvi(d, keys, vals)
            if v is not None:
                out.append((d, v))
                break
            d -= datetime.timedelta(days=1)
    return out


def colormap():
    x = get(CMAP).decode('utf-8', 'replace')
    ents = re.findall(r'<ColorMapEntry[^>]*rgb="(\d+),(\d+),(\d+)"[^>]*value="\[?([-\d.]+)', x)
    keys = np.array([[int(r), int(g), int(b)] for r, g, b, _ in ents])
    vals = np.array([float(v) for _, _, _, v in ents])
    return keys, vals


def ndvi(date, keys, vals):
    u = (WMS + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=%s&CRS=EPSG:3857&BBOX=%d,%d,%d,%d'
         '&WIDTH=%d&HEIGHT=%d&FORMAT=image/png&TIME=%s' % (LAYER, BOX[0], BOX[1], BOX[2], BOX[3], W, H, date.isoformat()))
    a = np.array(Image.open(io.BytesIO(get(u, 240))).convert('RGB'))
    flat = a.reshape(-1, 3)
    out = np.full(flat.shape[0], np.nan)
    for i in range(0, flat.shape[0], 250000):
        ch = flat[i:i + 250000]
        d = ((ch[:, None, :] - keys[None, :, :]) ** 2).sum(2)
        idx = d.argmin(1)
        ok = d.min(1) == 0
        out[i:i + 250000] = np.where(ok, vals[idx], np.nan)
    v = out.reshape(a.shape[:2])
    share = float(np.isfinite(v).mean())
    print('  %s valid %.2f' % (date, share), flush=True)
    return v if share > 0.3 else None       # a blank (unpublished) composite decodes to nothing


def relief():
    """ASTER GDEM greyscale shaded relief for the box, 0..255 (mean ~127), or
    None. Multiplied into the ramp so the mountains read through the green
    (user 2026-09-13: "add the topography as an undertone")."""
    u = (WMS + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=ASTER_GDEM_Greyscale_Shaded_Relief'
         '&CRS=EPSG:3857&BBOX=%d,%d,%d,%d&WIDTH=%d&HEIGHT=%d&FORMAT=image/png' % (BOX + (W, H)))
    try:
        return np.array(Image.open(io.BytesIO(get(u, 240))).convert('L')).astype(np.float32)
    except Exception as e:
        print('relief: unavailable (%s)' % e)
        return None


# THE RAMP IS CENTRED ON PEAK (2026-09-13). Greenness falls ~15-30% at peak
# colour on this index and 40%+ only once the leaves are down, so a ramp that
# reached orange at 40% painted every peak yellow. Orange now sits at 20%,
# red at 28%, brown (bare) from 40%. The page reads these stops for its legend.
RAMP = [(0.0, (34, 120, 40)), (0.08, (150, 190, 40)), (0.15, (240, 200, 40)),
        (0.20, (235, 120, 30)), (0.28, (200, 40, 30)), (0.40, (120, 60, 30)), (1.01, (90, 45, 25))]
RAMP_LEGEND = [(0, '0%'), (8, '8%'), (15, '15%'), (20, '20% PEAK'), (28, '28%'), (40, '40%+ BARE')]


def ramp(p, alpha=0.80, shade=None):
    h, w = p.shape
    img = np.zeros((h, w, 4), np.uint8)
    stops = RAMP
    m = np.isfinite(p)
    for i in range(len(stops) - 1):
        a, ca = stops[i]; b, cb = stops[i + 1]
        sel = m & (p >= a) & (p < b)
        if not sel.any():
            continue
        t = ((p - a) / (b - a))[sel][:, None]
        col = np.array(ca) * (1 - t) + np.array(cb) * t
        if shade is not None:
            # hillshade as lightness, around the relief's own middle grey
            # (~127): flat ground keeps the ramp's colour, a sunlit slope
            # lifts to 1.4x and a shadowed one falls to 0.55x -- strong enough
            # that the ridges read as ridges under the green
            f = np.clip(1.0 + (shade[sel] - 127.0) / 85.0, 0.55, 1.4)[:, None]
            col = col * f
        img[sel, :3] = np.clip(col, 0, 255).astype(np.uint8)
        img[sel, 3] = int(255 * alpha)
    return Image.fromarray(img)


def bands(p, shade, sigma=7, blobs=False):
    """THE BANDS LOOK (user 2026-09-13: "id rather see bands"): the index
    blurred to landscape scale (sigma 7 px ~ 6 km) and posterised to the
    ramp's own stops, so the colour comes as bands that follow the hills
    rather than county lines or 250 m speckle. Same relief undertone."""
    # a MASK-AWARE blur: blur(p x mask) / blur(mask), so water, towns and
    # the untyped edge do not bleed a filled-in value into the forest next
    # to them (the first cut filled gaps with the mean and drew yellow
    # halos round every lake and city). Only pixels with 300 m of forest
    # around them keep a band; the rest stay clear and the map shows through.
    fin = np.isfinite(p)
    pv = np.where(fin, p, 0.0).astype(np.float32)
    mk = fin.astype(np.float32)
    to = lambda a: Image.fromarray((np.clip(a, 0, 1) * 250).astype(np.uint8))           # noqa: E731
    bp = np.array(to(pv).filter(ImageFilter.GaussianBlur(sigma))).astype(np.float32) / 250.0
    bm = np.array(to(mk).filter(ImageFilter.GaussianBlur(sigma))).astype(np.float32) / 250.0
    with np.errstate(invalid='ignore', divide='ignore'):
        q = np.where(bm > 0.35, bp / bm, np.nan)
    # posterise: each pixel takes the lower stop of the band it falls in
    stops = [st for st, _ in RAMP[:-1]]
    post = np.full_like(q, np.nan)
    for lo in stops:
        post = np.where(np.isfinite(q) & (q >= lo), lo + 0.001, post)
    if blobs:
        # THE BLOBS AS OUTLINES (user 2026-09-13: "the smoothed view should be
        # gone"): from the second stop up, each band's edge drawn in the
        # band's own colour and its inside only faintly tinted, so the raw
        # 250 m detail reads through even in late October when every pixel
        # is above the first stop and a filled blob was the whole map.
        post = np.where(post >= RAMP[1][0], post, np.nan)
        img = np.array(ramp(post, shade=None).convert('RGBA'))
        fin = np.isfinite(post)
        lvl = np.where(fin, post, -1.0)
        edge = np.zeros_like(fin)
        edge[1:, :] |= lvl[1:, :] != lvl[:-1, :]
        edge[:-1, :] |= lvl[:-1, :] != lvl[1:, :]
        edge[:, 1:] |= lvl[:, 1:] != lvl[:, :-1]
        edge[:, :-1] |= lvl[:, :-1] != lvl[:, 1:]
        edge &= fin
        # a two-pixel line: the edge and its inward neighbour
        e2 = edge.copy()
        e2[1:, :] |= edge[:-1, :]; e2[:, 1:] |= edge[:, :-1]
        e2 &= fin
        alpha = np.where(e2, 235, np.where(fin, 60, 0)).astype(np.uint8)
        img[..., 3] = alpha
        return Image.fromarray(img, 'RGBA')
    return ramp(post, shade=shade)


FOREST_MASK = None
FOREST_CODES = None


def index_of(cur, base, mask=None):
    """progress = 1 - cur/base on forest pixels only (the typed-forest mask
    where it exists, else August greenness > 0.55), clipped 0..1."""
    with np.errstate(invalid='ignore', divide='ignore'):
        p = 1 - cur / base
    ok = np.isfinite(p) & (base > 0.55)
    if mask is not None:
        ok &= mask
    p = np.where(ok, p, np.nan)
    return np.clip(p, 0, 1)


def frame(p, shade):
    """The index -> the RGBA frame: a 5-px median first (the 250 m pixels
    speckle yellow over a green field at map scale; a median keeps rivers and
    ridgelines while removing the salt), then the ramp with the relief."""
    pm = np.where(np.isfinite(p), p, -1.0).astype(np.float32)
    med = np.array(Image.fromarray((np.clip(pm, 0, 1) * 250 + 2).astype(np.uint8)).filter(ImageFilter.MedianFilter(5))).astype(np.float32)
    p_s = np.where(np.isfinite(p), (med - 2) / 250.0, np.nan)
    return ramp(np.clip(p_s, 0, 1), shade=shade)


CDN = 'https://cdn.bluishvoid.com/foliage/'


def on_cdn(path):
    # FOLIAGE_FORCE=1 re-renders everything: the edge cache answers HEAD with
    # a copy for a day after the bucket object is deleted (2026-09-13, nine
    # of twelve season frames were skipped and the loop went dark on them)
    if os.environ.get('FOLIAGE_FORCE'):
        return False
    try:
        req = urllib.request.Request(CDN + path, method='HEAD', headers={'User-Agent': 'bluishvoid.com foliage bake'})
        return urllib.request.urlopen(req, timeout=20).status == 200
    except Exception:
        return False


def season_frames(year, keys, vals, shade):
    """Weekly frames for a past season, Sep 15 - Dec 1, rendered only for
    dates not already on the CDN. Returns the list of dates that exist (on
    the CDN or freshly written under OUT/season/<year>/)."""
    dates, todo = [], []
    d = datetime.date(year, 9, 15)
    while d <= datetime.date(year, *SEASON_END):
        if on_cdn('season/%d/%s.webp' % (year, d.isoformat())) and on_cdn('season/%d/%s_bands.webp' % (year, d.isoformat())) \
                and on_cdn('season/%d/%s_blobs.webp' % (year, d.isoformat())):
            dates.append(d.isoformat())
        else:
            todo.append(d)
        d += datetime.timedelta(days=7)
    if todo:
        print('season %d: rendering %d frames' % (year, len(todo)), flush=True)
        aug = [datetime.date(year, 8, 5), datetime.date(year, 8, 13), datetime.date(year, 8, 21), datetime.date(year, 8, 29)]
        bimgs = [v for v in (ndvi(x, keys, vals) for x in aug) if v is not None]
        if bimgs:
            base = np.nanmax(np.stack(bimgs), 0)
            os.makedirs(os.path.join(OUT, 'season', str(year)), exist_ok=True)
            for d in todo:
                v = ndvi(d, keys, vals)
                v2 = ndvi(d - datetime.timedelta(days=6), keys, vals)
                if v is None:
                    continue
                cur = np.nanmax(np.stack([x for x in (v, v2) if x is not None]), 0)
                pp = index_of(cur, base, FOREST_MASK)
                frame(pp, shade).save(os.path.join(OUT, 'season', str(year), d.isoformat() + '.webp'), 'WEBP', quality=82, method=6)
                bands(pp, shade).save(os.path.join(OUT, 'season', str(year), d.isoformat() + '_bands.webp'), 'WEBP', quality=82, method=6)
                bands(pp, shade, blobs=True).save(os.path.join(OUT, 'season', str(year), d.isoformat() + '_blobs.webp'), 'WEBP', quality=82, method=6)
                dates.append(d.isoformat())
    return {'year': year, 'dates': sorted(dates), 'base': CDN + 'season/%d/' % year}


def archive_this_season(today, prev):
    """One frame a week of the current season under season/<year>/: today's
    latest.webp is copied there when a week has passed since the last one."""
    have = ((prev or {}).get('season_this') or {}).get('dates') or []
    have = [x for x in have if x[:4] == str(today.year)]
    last = max(have) if have else None
    if last is None or (today - datetime.date.fromisoformat(last)).days >= 7:
        os.makedirs(os.path.join(OUT, 'season', str(today.year)), exist_ok=True)
        import shutil
        shutil.copyfile(os.path.join(OUT, 'latest.webp'), os.path.join(OUT, 'season', str(today.year), today.isoformat() + '.webp'))
        shutil.copyfile(os.path.join(OUT, 'latest_bands.webp'), os.path.join(OUT, 'season', str(today.year), today.isoformat() + '_bands.webp'))
        if os.path.exists(os.path.join(OUT, 'latest_blobs.webp')):
            shutil.copyfile(os.path.join(OUT, 'latest_blobs.webp'), os.path.join(OUT, 'season', str(today.year), today.isoformat() + '_blobs.webp'))
        have.append(today.isoformat())
    return {'year': today.year, 'dates': sorted(set(have)), 'base': CDN + 'season/%d/' % today.year}


# COUNTY BLOCKS (user 2026-09-13: "id rather see bands or color blocks"). The
# 217 counties of the nine states in the box, from the Census outlines
# (plotly's GeoJSON mirror of the 2010 cartographic boundaries), simplified
# to ~100 KB and shipped once as counties.json; the bake rasterises them into
# one label image and averages the index per county, today and for each week
# of last season, so the page can paint the blocks the way the foliage maps
# people know read -- while the 250 m raster stays underneath for detail.
COUNTY_SRC = 'https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json'
COUNTY_STATES = {'36': 'NY', '34': 'NJ', '09': 'CT', '25': 'MA', '50': 'VT', '33': 'NH', '42': 'PA', '44': 'RI', '23': 'ME'}


def county_shapes():
    """{fips: {'n': name, 's': state, 'r': [ring, ...]}} with rings in lon/lat,
    simplified; written to OUT/counties.json (uploaded once)."""
    import shapely.geometry as sg
    j = json.loads(get(COUNTY_SRC, 120))
    out = {}
    for f in j.get('features', []):
        fid = str(f.get('id') or '')
        st = COUNTY_STATES.get(fid[:2])
        if not st:
            continue
        g = sg.shape(f['geometry']).simplify(0.008, preserve_topology=True)
        polys = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
        rings = [[[round(x, 4), round(y, 4)] for x, y in pg.exterior.coords] for pg in polys if not pg.is_empty]
        if rings:
            out[fid] = {'n': (f.get('properties') or {}).get('NAME'), 's': st, 'r': rings}
    with open(os.path.join(OUT, 'counties.json'), 'w') as fh:
        json.dump(out, fh, separators=(',', ':'))
    return out


def county_labels(shapes):
    """One label image for the box: each county's exterior rings filled with
    its index (1..n); returns (labels HxW int32, [fips...])."""
    im = Image.new('I', (W, H), 0)
    dr = ImageDraw.Draw(im)
    ids = []
    for fips, c in shapes.items():
        ids.append(fips)
        k = len(ids)
        for ring in c['r']:
            pts = [px(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                dr.polygon(pts, fill=k)
    return np.array(im, dtype=np.int32), ids


def county_means(labels, ids, p, min_px=400):
    """Mean index per county over its FOREST pixels. A county needs 400 of
    them (~25 km2 at 250 m) to get a block: the boroughs and the sliver
    counties on the box's edge were being coloured by a handful of noisy
    pixels and read as orange in September (2026-09-13)."""
    valid = np.isfinite(p) & (labels > 0)
    if not valid.any():
        return {}
    sums = np.bincount(labels[valid], weights=p[valid], minlength=len(ids) + 1)
    cnt = np.bincount(labels[valid], minlength=len(ids) + 1)
    out = {}
    for k, fips in enumerate(ids, 1):
        if cnt[k] >= min_px:
            out[fips] = int(round(100 * sums[k] / cnt[k]))
    return out


def county_last_year(year, keys, vals, labels, ids, prev):
    """Per-county share for each week of last season, carried forward once done."""
    cl = (prev or {}).get('counties_ly')
    if cl and cl.get('year') == year and cl.get('dates') and cl.get('by'):
        return cl
    print('county curves (%d):' % year, flush=True)
    aug = [datetime.date(year, 8, 5), datetime.date(year, 8, 13), datetime.date(year, 8, 21), datetime.date(year, 8, 29)]
    bimgs = [v for v in (ndvi(x, keys, vals) for x in aug) if v is not None]
    if not bimgs:
        return None
    base = np.nanmax(np.stack(bimgs), 0)
    dates, by = [], {fips: [] for fips in ids}
    d = datetime.date(year, 9, 15)
    while d <= datetime.date(year, *SEASON_END):
        v = ndvi(d, keys, vals)
        v2 = ndvi(d - datetime.timedelta(days=6), keys, vals)
        if v is not None:
            cur = np.nanmax(np.stack([x for x in (v, v2) if x is not None]), 0)
            pp = index_of(cur, base, FOREST_MASK)
            m = county_means(labels, ids, pp)
            dates.append(d.isoformat())
            for fips in ids:
                by[fips].append(m.get(fips))
        d += datetime.timedelta(days=7)
    return {'year': year, 'dates': dates, 'by': by}


# THE FOREST ITSELF (user 2026-09-13: "are we able to see species location?").
# USFS FIA Forest Atlas, Forest Type Groups, 250 m (MODIS 2002-03 plus ~100
# layers; the Forest Service's own product, served by the USGS geoplatform
# image service with CORS for bluishvoid.com). Species-level maps exist in
# the same atlas as per-species basal area rasters, but the type GROUP is
# what decides the colour: maple/beech/birch is the show, aspen/birch and
# elm/ash go yellow, oak/hickory turns late and russet, spruce, fir and pine
# never turn. Rendered once a season as FOREST_FRAME with the relief, plus
# forest_codes.png (one byte a pixel, the group index) for the page's taps.
FTG = ('https://imagery.geoplatform.gov/iipp/rest/services/Vegetation/'
       'USFS_EDW_FIA_ForestAtlas_ForestTypeGroups_109_CONUS/ImageServer')
# SIX COLOURS, NOT FOUR (user 2026-09-13: "is there a way to break up the
# colors further on FOREST?"). Measured over the box's typed forest: maple,
# beech, birch 57%; oak, hickory 31%; the pines 5%; spruce and fir 3%; the
# river-bottom elm, ash, cottonwood 1%; aspen and birch 1%; everything else
# under 1% each and folded into its nearest kin. The pines against the
# spruce-fir mark the Pine Barrens and the sandy uplands against the boreal
# high ground; the two golds are the river bottoms against the far north.
FOREST_ROLES = [   # (label as the atlas prints it, our role, display rgb)
    ('Maple/Beech/Birch Group', 'THE SHOW', (232, 108, 38)),
    ('Aspen/Birch Group', 'NORTH GOLD', (244, 208, 56)),
    ('Elm/Ash/Cottonwood Group', 'RIVER GOLD', (206, 176, 104)),
    ('Oak/Hickory Group', 'LATE, RUSSET', (168, 106, 58)),
    ('Oak/Pine Group', 'LATE, RUSSET', (156, 112, 60)),
    ('Oak/Gum/Cypress Group', 'LATE, RUSSET', (160, 118, 62)),
    ('Spruce/Fir Group', 'SPRUCE, FIR', (22, 74, 52)),
    ('White/Red/Jack Pine Group', 'PINE', (78, 142, 78)),
    ('Loblolly/Shortleaf Pine Group', 'PINE', (84, 148, 80)),
    ('Longleaf/Slash Pine Group', 'PINE', (84, 148, 80)),
    ('Pinyon/Juniper Group', 'PINE', (80, 140, 78)),
    ('Douglas-fir Group', 'SPRUCE, FIR', (26, 80, 54)),
    ('Exotic Softwoods Group', 'PINE', (82, 144, 80)),
]
FOREST_LEGEND = [('THE SHOW', 'MAPLE, BEECH, BIRCH', (232, 108, 38)), ('LATE, RUSSET', 'OAK, HICKORY', (168, 106, 58)),
                 ('NORTH GOLD', 'ASPEN, BIRCH', (244, 208, 56)), ('RIVER GOLD', 'ELM, ASH, COTTONWOOD', (206, 176, 104)),
                 ('PINE', 'WHITE, RED, PITCH', (78, 142, 78)), ('SPRUCE, FIR', 'THE HIGH GROUND', (22, 74, 52))]
FOREST_FRAME = 'forest_v2.webp'     # bump when the palette changes; the CDN copy is otherwise kept


def forest(shade, prev):
    """-> (codes HxW uint8 with 0 = no forest and i+1 = FOREST_ROLES[i], legend
    rows). Renders forest_v1.webp + forest_codes.png under OUT when the CDN
    does not have them yet; always returns the codes for the region shares."""
    leg = json.loads(get(FTG + '/legend?f=json', 60))
    import base64
    cols = {}
    for L in leg.get('layers', []):
        for it in L.get('legend', []):
            im = Image.open(io.BytesIO(base64.b64decode(it['imageData']))).convert('RGB')
            a = np.array(im).reshape(-1, 3)
            v, c = np.unique(a, axis=0, return_counts=True)
            cols[it.get('label')] = tuple(int(x) for x in v[c.argmax()])
    u = (FTG + '/exportImage?bbox=%d,%d,%d,%d&bboxSR=3857&imageSR=3857&size=%d,%d&format=png'
         '&interpolation=RSP_NearestNeighbor&f=image' % (BOX + (W, H)))
    a = np.array(Image.open(io.BytesIO(get(u, 240))).convert('RGB'))
    flat = a.reshape(-1, 3)
    codes = np.zeros(flat.shape[0], np.uint8)
    for i, (label, role, rgb) in enumerate(FOREST_ROLES):
        c = cols.get(label)
        if c is None:
            continue
        m = (flat[:, 0] == c[0]) & (flat[:, 1] == c[1]) & (flat[:, 2] == c[2])
        codes[m] = i + 1
    codes = codes.reshape(a.shape[:2])
    global FOREST_CODES
    FOREST_CODES = codes
    print('forest: %.0f%% of the box is typed forest' % (100 * (codes > 0).mean()))
    if not (on_cdn(FOREST_FRAME) and on_cdn('forest_codes.png')):
        img = np.zeros((H, W, 4), np.uint8)
        for i, (label, role, rgb) in enumerate(FOREST_ROLES):
            m = codes == i + 1
            col = np.array(rgb, np.float32)[None, :]
            if shade is not None:
                f = np.clip(1.0 + (shade[m] - 127.0) / 85.0, 0.55, 1.4)[:, None]
                col = col * f
            img[m, :3] = np.clip(col, 0, 255).astype(np.uint8)
            img[m, 3] = 218
        Image.fromarray(img).save(os.path.join(OUT, FOREST_FRAME), 'WEBP', quality=82, method=6)
        Image.fromarray(codes, 'L').save(os.path.join(OUT, 'forest_codes.png'), optimize=True)
    return codes


# WHICH TREE LEADS (user 2026-09-13: "is it not possible to break up maple
# beech birch?"). The type groups cannot be split -- they are the atlas's own
# classes -- but the Forest Service's FHTET species rasters can: modelled
# basal area per species at 30 m (circa 2002, made for the insect-and-disease
# risk map), one raster function per species on the same image service
# family. Sampled to the bake's 250 m grid, the leading colour-maker at each
# forest pixel is the species (or kin) with the most basal area, drawn only
# where that leader holds at least SPECIES_MIN_BA square feet an acre. The
# frame is rendered once a season (SPECIES_FRAME), like the forest.
FHP = ('https://imagery.geoplatform.gov/iipp/rest/services/Vegetation/'
       'USFS_EDW_FHP_TreeSpeciesMetrics_BasalArea/ImageServer')
SPECIES = [   # (role, what it does in fall, display rgb, the rasters summed)
    ('SUGAR MAPLE', 'ORANGE TO RED, EARLY OCTOBER', (250, 120, 40), ['sugar_maple']),
    ('RED MAPLE', 'SCARLET, THE FIRST TO TURN', (215, 45, 40), ['red_maple', 'silver_maple']),
    ('BEECH', 'BRONZE, HOLDS ITS LEAVES', (205, 160, 90), ['American_beech']),
    ('BIRCH', 'CLEAR YELLOW', (250, 225, 95), ['yellow_birch', 'paper_birch', 'sweet_birch', 'gray_birch']),
    ('ASPEN', 'GOLD, EARLY', (240, 190, 30), ['quaking_aspen', 'bigtooth_aspen']),
    ('RED OAK', 'RUSSET RED, LATE OCTOBER', (165, 65, 50), ['northern_red_oak', 'black_oak', 'scarlet_oak', 'pin_oak']),
    ('WHITE OAK', 'BROWN AND WINE, THE LAST', (135, 100, 75), ['white_oak', 'chestnut_oak', 'swamp_white_oak']),
    ('HICKORY', 'GOLDEN BROWN', (190, 145, 45), ['hickory_spp', 'shagbark_hickory', 'pignut_hickory', 'mockernut_hickory', 'bitternut_hickory']),
    ('ASH', 'PLUM AND YELLOW, EARLY', (175, 125, 150), ['white_ash', 'green_ash', 'black_ash']),
    ('HEMLOCK', 'EVERGREEN, THE RAVINES', (35, 95, 85), ['eastern_hemlock']),
    ('PINE', 'EVERGREEN', (80, 140, 80), ['eastern_white_pine', 'red_pine', 'pitch_pine']),
    ('SPRUCE, FIR', 'EVERGREEN, THE HIGH GROUND', (22, 74, 52), ['red_spruce', 'black_spruce', 'white_spruce', 'Balsam_fir', 'Norway_spruce']),
]
SPECIES_FRAME = 'species_v2.webp'   # v2: smoothed leaders, Balsam_fir spelled as the service has it
SPECIES_MIN_BA = 5.0
SPECIES_BLUR = 1.4                  # px of the 250 m grid; a 30 m raster sampled nearest is salt and pepper


def blur2d(a, sigma):
    """A separable Gaussian in numpy (PIL will not blur a float image)."""
    r = max(1, int(round(3 * sigma)))
    x = np.arange(-r, r + 1, dtype=np.float32)
    k = np.exp(-0.5 * (x / sigma) ** 2); k /= k.sum()
    pad = np.pad(a, ((0, 0), (r, r)), mode='edge')
    out = np.zeros_like(a)
    for i, w in enumerate(k):
        out += w * pad[:, i:i + a.shape[1]]
    pad = np.pad(out, ((r, r), (0, 0)), mode='edge')
    out2 = np.zeros_like(a)
    for i, w in enumerate(k):
        out2 += w * pad[i:i + a.shape[0], :]
    return out2


def canada_mask():
    """True north of the border, by a piecewise line through the box: the
    Niagara, Lake Ontario's north shore, the St Lawrence, then the 45th
    parallel. The first cut used "outside the county shapes", but those
    cover nine states, so Maryland, Delaware and West Virginia came out
    looking like Canada with a hard line along the Mason-Dixon (user
    2026-09-13: "is this line of green and black accurate?"). The typed
    forest stops at this line; north of it the greenness rule stands."""
    R = 6378137.0
    X0, Y0, X1, Y1 = BOX
    xs = X0 + (np.arange(W) + 0.5) / W * (X1 - X0)
    ys = Y1 - (np.arange(H) + 0.5) / H * (Y1 - Y0)
    lon = xs / R * 180 / math.pi
    lat = (2 * np.arctan(np.exp(ys / R)) - math.pi / 2) * 180 / math.pi
    LON, LAT = np.meshgrid(lon, lat)
    line = np.where(LON < -79.05, 42.88,
           np.where(LON < -76.9, 43.55,
           np.where(LON < -76.4, 44.0,
           np.where(LON < -74.7, 44.1 + (LON + 76.4) * 0.53,
           np.where(LON < -71.0, 45.0, 45.7)))))
    return LAT > line


# A FOREST MASK NORTH OF THE BORDER (user 2026-09-13: "will that fix that
# smoothing in canada too?"). The Forest Service's typed forest stops at the
# line, so Canada carried the index on every green pixel, farmland included,
# and came out blotchy against the speckled US side. NASA's MODIS IGBP land
# cover (500 m, yearly) covers it: the five forest classes and woody savanna
# are the mask there. Colours are matched to the layer's own colormap.
IGBP_LAYER = 'MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual'
IGBP_RGB = {1: (33, 138, 33), 2: (49, 204, 49), 3: (152, 204, 49), 4: (150, 250, 150), 5: (141, 186, 141),
            6: (186, 141, 141), 7: (245, 222, 179), 8: (218, 235, 157), 9: (255, 213, 0), 10: (240, 185, 103),
            11: (71, 131, 181), 12: (250, 239, 115), 13: (255, 0, 0), 14: (153, 147, 86), 15: (255, 255, 255),
            16: (191, 191, 189), 17: (134, 202, 227), 255: (100, 100, 100)}
IGBP_FOREST = {1, 2, 3, 4, 5, 8}


def igbp_forest():
    """True where MODIS land cover says forest, on the bake's grid; the newest
    year the service has (tried back from last year)."""
    for year in range(datetime.date.today().year - 1, datetime.date.today().year - 5, -1):
        u = ('https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0'
             '&LAYERS=%s&CRS=EPSG:3857&BBOX=%d,%d,%d,%d&WIDTH=%d&HEIGHT=%d&FORMAT=image/png&TIME=%d-01-01'
             % ((IGBP_LAYER,) + BOX + (W, H, year)))
        try:
            a = np.array(Image.open(io.BytesIO(get(u, 240))).convert('RGB')).astype(np.int32)
        except Exception as e:
            print('igbp: %d failed (%s)' % (year, e)); continue
        keys = list(IGBP_RGB)
        pal = np.array([IGBP_RGB[k] for k in keys], np.int32)
        flat = a.reshape(-1, 3)
        d = ((flat[:, None, :] - pal[None, :, :]) ** 2).sum(2)
        cls = np.array(keys)[d.argmin(1)].reshape(a.shape[:2])
        near = d.min(1).reshape(a.shape[:2]) <= 3 * 12 * 12
        forest = near & np.isin(cls, list(IGBP_FOREST))
        if (near & (cls != 255)).mean() > 0.3:
            print('igbp: %d, forest on %.0f%% of the box' % (year, 100 * forest.mean()))
            return forest
    return None


def species_raster(fn):
    u = (FHP + '/exportImage?bbox=%d,%d,%d,%d&bboxSR=3857&imageSR=3857&size=%d,%d&format=tiff&pixelType=F32'
         '&interpolation=RSP_NearestNeighbor&f=image&renderingRule=%s'
         % (BOX + (W, H) + (urllib.parse.quote('{"rasterFunction":"%s"}' % fn),)))
    a = np.array(Image.open(io.BytesIO(get(u, 240)))).astype(np.float32)
    # the service's nodata comes back as huge floats; basal area is 0-400 sq ft an acre
    return np.where(np.isfinite(a) & (a >= 0) & (a <= 400), a, 0.0)


def species(shade, mask):
    """Renders SPECIES_FRAME + species_codes.png under OUT when the CDN does
    not have them (0 = no leader, i+1 = SPECIES[i]); nothing otherwise."""
    if on_cdn(SPECIES_FRAME) and on_cdn('species_codes.png'):
        return
    ba = []
    for role, _, _, fns in SPECIES:
        acc = np.zeros((H, W), np.float32)
        for fn in fns:
            try:
                acc += species_raster(fn)
            except Exception as e:
                print('species: %s failed (%s)' % (fn, e))
        # the leader is decided on a lightly smoothed field, so one 30 m cell
        # sampled into a 250 m pixel does not flip the colour by itself
        acc = blur2d(acc, SPECIES_BLUR)
        ba.append(acc)
        print('species: %-12s covers %.1f%% of the box at >= %g' % (role, 100 * (acc >= SPECIES_MIN_BA).mean(), SPECIES_MIN_BA))
    st = np.stack(ba)
    lead = st.argmax(0).astype(np.uint8) + 1
    top = st.max(0)
    ok = top >= SPECIES_MIN_BA
    if mask is not None:
        ok &= mask
    codes = np.where(ok, lead, 0).astype(np.uint8)
    img = np.zeros((H, W, 4), np.uint8)
    for i, (role, _, rgb, _) in enumerate(SPECIES):
        m = codes == i + 1
        col = np.array(rgb, np.float32)[None, :]
        if shade is not None:
            f = np.clip(1.0 + (shade[m] - 127.0) / 85.0, 0.55, 1.4)[:, None]
            col = col * f
        img[m, :3] = np.clip(col, 0, 255).astype(np.uint8)
        img[m, 3] = 218
    Image.fromarray(img).save(os.path.join(OUT, SPECIES_FRAME), 'WEBP', quality=82, method=6)
    Image.fromarray(codes, 'L').save(os.path.join(OUT, 'species_codes.png'), optimize=True)
    tot = (codes > 0).sum() or 1
    print('species: leaders ' + ', '.join('%s %.0f%%' % (r[0], 100 * (codes == i + 1).sum() / tot) for i, r in enumerate(SPECIES)))


def forest_shares(codes, labels, ids):
    """per county fips -> {'show': %, 'gold': %, 'late': %, 'ever': %} of its typed forest"""
    role_of = {i + 1: r for i, (_, r, _) in enumerate(FOREST_ROLES)}
    key = {'THE SHOW': 'show', 'NORTH GOLD': 'gold', 'RIVER GOLD': 'gold', 'LATE, RUSSET': 'late',
           'PINE': 'ever', 'SPRUCE, FIR': 'ever'}
    out = {}
    valid = codes > 0
    tot = np.bincount(labels[valid], minlength=len(ids) + 1)
    per = {}
    for code, role in role_of.items():
        per.setdefault(key[role], np.zeros(len(ids) + 1))
        per[key[role]] += np.bincount(labels[valid & (codes == code)], minlength=len(ids) + 1)
    for k, fips in enumerate(ids, 1):
        if tot[k] >= 200:
            out[fips] = {r: int(round(100 * per[r][k] / tot[k])) for r in per}
    return out


def px(lon, lat):
    x = lon * np.pi / 180 * R
    y = R * np.log(np.tan(np.pi / 4 + lat * np.pi / 360))
    return (x - BOX[0]) / (BOX[2] - BOX[0]) * W, (BOX[3] - y) / (BOX[3] - BOX[1]) * H


# the places a New Yorker drives to for the colour (user 2026-09-13: "for
# NYCers going upstate on weekends"), each a box for the mean and an anchor
# for its sign on the map
REGIONS = [('Adirondacks', -74.6, -73.6, 43.6, 44.4), ('Catskills', -74.7, -74.0, 41.9, 42.3),
           ('Shawangunks', -74.35, -74.15, 41.65, 41.82),
           ('Hudson Valley', -74.0, -73.6, 41.2, 41.8), ('Litchfield Hills', -73.4, -73.0, 41.7, 42.0),
           ('Berkshires', -73.4, -72.9, 42.1, 42.7), ('Poconos', -75.6, -75.0, 41.0, 41.4),
           ('Delaware Water Gap', -75.2, -74.9, 40.9, 41.2), ('Finger Lakes', -77.3, -76.3, 42.3, 42.9),
           ('Green Mountains', -73.1, -72.6, 43.0, 44.3), ('White Mountains', -71.7, -71.0, 43.9, 44.4),
           ('New York City & Long Island', -74.1, -72.2, 40.6, 41.0)]
# WHAT "PEAK" IS ON THIS INDEX (learned from the 2025 replay, 2026-09-13).
# Greenness falls only a little while leaves TURN and collapses when they
# DROP, so the index reads ~20% in the Adirondacks at peak colour and keeps
# falling into November. A level threshold therefore puts every peak in
# November. Peak colour is the week of the FASTEST decline, and each region
# has its own level at that week (Adirondacks ~21%, Catskills ~20% in 2025).
# The bands are RELATIVE to that level, per region, from last year's curve;
# the absolute fallback below is only for a region with no history.
# sign priority (the label queue drops the lowest first when signs collide at
# this scale) and, where a box centre sits on a neighbour's sign, an anchor
PRI = {'Adirondacks': 78, 'Catskills': 78, 'New York City & Long Island': 76, 'Hudson Valley': 74,
       'Green Mountains': 72, 'White Mountains': 72, 'Berkshires': 70, 'Finger Lakes': 70,
       'Poconos': 68, 'Litchfield Hills': 64, 'Delaware Water Gap': 64,
       'Shawangunks': 62}
# signs sit where a New Yorker would point (user 2026-09-13: "some of these
# locations aren't in the right spot"): the Hudson Valley on the river at
# Hyde Park, the city-and-island sign on Long
# Island at the Nassau line rather than out in Suffolk
ANCHOR = {'Hudson Valley': (41.78, -73.93), 'Shawangunks': (41.72, -74.42), 'Catskills': (42.12, -74.45),
          'New York City & Long Island': (40.74, -73.45)}
# the Harriman & Bear Mountain sign was dropped (user 2026-09-13: "keep
# breakneck, remove harriman"): it crowded the Highlands against the lookouts
# and Bear Mountain is a lookout of the Hudson Valley
BANDS = [(0, 'NOT YET'), (8, 'STARTING'), (15, 'NEAR PEAK'), (20, 'PEAK'), (30, 'PAST PEAK')]
REL = [(0.0, 'NOT YET'), (0.35, 'STARTING'), (0.75, 'NEAR PEAK'), (0.95, 'PEAK'), (1.3, 'PAST PEAK')]


def band(pct, peak_level=None):
    if peak_level:
        out = REL[0][1]
        for f, name in REL:
            if pct >= f * peak_level:
                out = name
        return out
    out = BANDS[0][1]
    for lo, name in BANDS:
        if pct >= lo:
            out = name
    return out


def peak_of(dates, arr):
    """(date, level) of PEAK COLOUR on last year's weekly curve, or (None, None).

    Not the fastest decline any more: with the window run out to Dec 1 the
    fastest week is the leaf DROP in mid-November (the index jumps 25 points
    in the Adirondacks the week of Nov 17), which put every northern peak
    three to six weeks late. Measured against the 2025 peaks people reported
    (user 2026-09-13), the reading that lands within a week everywhere is:
    the first week the index rises PEAK_RISE points in a week, or the day
    40% of the season's whole loss is in (PEAK_FRAC, interpolated to the
    day), whichever comes first. The level is the curve's value that day,
    which is what the relative bands read against."""
    pts = [(dt, x) for dt, x in zip(dates, arr) if x is not None]
    if len(pts) < 4:
        return None, None
    ds = [datetime.date.fromisoformat(d) for d, _ in pts]
    xs = [x for _, x in pts]
    total = xs[-1] - xs[0]
    if total <= 3:
        return None, None
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
    if not cand:
        return None, None
    day, lvl = min(cand)
    return day.isoformat(), int(round(lvl))


PEAK_RISE = 8.0     # points of index in a week: the colour phase's steep week
PEAK_FRAC = 0.40    # share of the season's whole loss


def region_means(p):
    out = {}
    for name, lo0, lo1, la0, la1 in REGIONS:
        x0, y1 = px(lo0, la0); x1, y0 = px(lo1, la1)
        sub = p[int(max(0, y0)):int(min(H, y1)), int(max(0, x0)):int(min(W, x1))]
        m = np.isfinite(sub)
        if m.sum() < 50:
            continue
        out[name] = (int(round(100 * float(np.nanmean(sub)))), int(round(100 * float((sub[m] >= 0.5).mean()))))
    return out


def previous():
    try:
        return json.loads(get('https://cdn.bluishvoid.com/foliage/latest.json?v=%d' % int(time.time()), 60))
    except Exception:
        return {}


def last_year_curve(year, keys, vals, prev):
    """Last season's progress per region, weekly Sep 15 - Dec 1, from the same
    satellite record -- so each sign can say when its peak came last year.
    Fourteen fetches, done once and carried forward in the JSON."""
    ly = (prev or {}).get('last_year')
    if ly and ly.get('year') == year and ly.get('regions') and all(n in ly['regions'] for n, *_ in REGIONS):
        return ly
    print('last year (%d):' % year, flush=True)
    aug = [datetime.date(year, 8, 5), datetime.date(year, 8, 13), datetime.date(year, 8, 21), datetime.date(year, 8, 29)]
    bimgs = [v for v in (ndvi(d, keys, vals) for d in aug) if v is not None]
    if not bimgs:
        return None
    base = np.nanmax(np.stack(bimgs), 0)
    dates, per = [], {n: [] for n, *_ in REGIONS}
    d = datetime.date(year, 9, 15)
    while d <= datetime.date(year, *SEASON_END):
        v = ndvi(d, keys, vals)
        v2 = ndvi(d - datetime.timedelta(days=6), keys, vals)
        if v is not None:
            cur = np.nanmax(np.stack([x for x in (v, v2) if x is not None]), 0)
            pp = index_of(cur, base, FOREST_MASK)
            rm = region_means(pp)
            dates.append(d.isoformat())
            for n in per:
                per[n].append(rm.get(n, (None, None))[0])
        d += datetime.timedelta(days=7)
    return {'year': year, 'dates': dates, 'regions': per}
CLASSES = {'Less than 5%': 0, '5-24%': 1, '25-49%': 2, '50-74%': 3, '75-94%': 4, '95% or more': 5}


WEEKEND_WX = {0: 'CLEAR', 1: 'CLEAR', 2: 'PARTLY CLOUDY', 3: 'OVERCAST', 45: 'FOG', 48: 'FOG',
              51: 'DRIZZLE', 53: 'DRIZZLE', 55: 'DRIZZLE', 56: 'DRIZZLE', 57: 'DRIZZLE',
              61: 'RAIN', 63: 'RAIN', 65: 'RAIN', 66: 'RAIN', 67: 'RAIN',
              71: 'SNOW', 73: 'SNOW', 75: 'SNOW', 77: 'SNOW', 80: 'SHOWERS', 81: 'SHOWERS', 82: 'SHOWERS',
              85: 'SNOW', 86: 'SNOW', 95: 'STORMS', 96: 'STORMS', 99: 'STORMS'}


def weekend(today, anchors):
    """Saturday and Sunday ahead, per region anchor: {name: [[date, word, hiF, rain%], ...]}.
    One Open-Meteo call for every anchor; 'this weekend' is the next Saturday,
    or today's if it is the weekend already."""
    # the weekend a planner is planning: this Saturday if it is still ahead
    # (or is today), otherwise next Saturday -- a Sunday looks a week on
    sat = today + datetime.timedelta(days=(5 - today.weekday()) % 7)
    sun = sat + datetime.timedelta(days=1)
    names = [n for n, _ in anchors]
    u = ('https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s'
         '&daily=weathercode,temperature_2m_max,precipitation_probability_max&temperature_unit=fahrenheit'
         '&timezone=America%%2FNew_York&start_date=%s&end_date=%s'
         % (','.join('%.3f' % a[0] for _, a in anchors), ','.join('%.3f' % a[1] for _, a in anchors),
            sat.isoformat(), sun.isoformat()))
    try:
        j = json.loads(get(u, 60))
    except Exception as e:
        print('weekend: unavailable (%s)' % e)
        return {}, sat.isoformat()
    if isinstance(j, dict):
        j = [j]
    out = {}
    for n, row in zip(names, j):
        d = (row or {}).get('daily') or {}
        days = []
        for i, dt in enumerate(d.get('time') or []):
            code = (d.get('weathercode') or [None])[i]
            days.append([dt, WEEKEND_WX.get(code, 'CLOUDY') if code is not None else None,
                         (round((d.get('temperature_2m_max') or [None])[i]) if (d.get('temperature_2m_max') or [None])[i] is not None else None),
                         (d.get('precipitation_probability_max') or [None])[i]])
        out[n] = days
    return out, sat.isoformat()


def pace(today, pct, ly, name):
    """Days ahead (+) or behind (-) last year's curve at today's share, or None
    when the share is still inside the noise (< 8%)."""
    if not ly or pct is None or pct < 8:
        return None
    arr = ly.get('regions', {}).get(name)
    if not arr:
        return None
    pts = [(datetime.date.fromisoformat(dt), x) for dt, x in zip(ly['dates'], arr) if x is not None]
    if len(pts) < 2:
        return None
    ref = datetime.date(pts[0][0].year, today.month, today.day)   # today, last year
    # the first date last year at or past today's share, interpolated
    for (d0, x0), (d1, x1) in zip(pts, pts[1:]):
        if x0 <= pct <= x1 and x1 > x0:
            at = d0 + datetime.timedelta(days=(pct - x0) / (x1 - x0) * (d1 - d0).days)
            return (at - ref).days
    if pct < pts[0][1]:
        return None
    return None


# THE SEASON WINDOW (user 2026-09-13: "it ends nov 10th, is that accurate?").
# It was not: the coast, the city and Long Island peak in early-to-mid
# November and hold colour past Thanksgiving, and a curve cut at Nov 10 made
# "PEAK LAST YEAR NOV 10" the window's edge rather than a measurement for
# the Berkshires and the city. Weekly from Sep 15 through Dec 1, when the
# leaves are down everywhere and the last frame reads bare.
SEASON_END = (12, 1)

SPOTS = [
    ('Bear Mountain', 'NY', 'Hudson Valley', 'Metro-North to Peekskill, then a taxi'),
    ('Breakneck Ridge', 'NY', 'Hudson Valley', 'Metro-North Hudson Line, Breakneck Ridge stop (weekends)'),
    ('Storm King Mountain', 'NY', 'Hudson Valley', 'Metro-North to Beacon, then a taxi'),
    ('Mount Beacon', 'NY', 'Hudson Valley', 'Metro-North to Beacon, walk to the trailhead'),
    ('Minnewaska State Park', 'NY', 'Shawangunks', 'Trailways bus to New Paltz, then a taxi'),
    ('Mohonk Preserve', 'NY', 'Shawangunks', 'Trailways bus to New Paltz'),
    ('Sams Point', 'NY', 'Shawangunks', 'car'),
    ('Kaaterskill Falls', 'NY', 'Catskills', 'Trailways bus to Palenville'),
    ('Overlook Mountain', 'NY', 'Catskills', 'Trailways bus to Woodstock'),
    ('Hunter Mountain', 'NY', 'Catskills', 'Trailways bus to Hunter'),
    ('Slide Mountain', 'NY', 'Catskills', 'car'),
    ('Mount Tammany', 'NJ', 'Delaware Water Gap', 'car'),
    ('High Point State Park', 'NJ', 'Delaware Water Gap', 'car'),
    ('Bash Bish Falls', 'MA', 'Berkshires', 'Metro-North Harlem Line to Wassaic, then a taxi'),
    ('Mount Greylock', 'MA', 'Berkshires', 'car'),
    ('Prospect Mountain, Lake George', 'NY', 'Adirondacks', 'car (Lake George)'),
    ('Whiteface Mountain', 'NY', 'Adirondacks', 'car'),
    ('Olana State Historic Site', 'NY', 'Hudson Valley', 'Amtrak to Hudson, then a taxi'),
]


# DRIVE TIME FROM COLUMBUS CIRCLE (user 2026-09-13: "remove those rings and
# just add the drive time to the locations"). Real routed minutes from the
# public OSRM router, one call per place, cached in foliage_drive.json next to
# this file (committed: roads do not move, and the router is a shared demo).
# A place the router cannot reach falls back to the crow-flies miles at 48 mph
# times 1.25 for the roads, flagged so the sign can say "about".
DRIVE_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'foliage_drive.json')
CITY = (-73.982, 40.768)


def drive_minutes(name, lat, lon):
    try:
        cache = json.load(open(DRIVE_CACHE))
    except Exception:
        cache = {}
    key = '%s@%.3f,%.3f' % (name, lat, lon)
    if key in cache:
        return cache[key]
    out = None
    try:
        u = ('https://router.project-osrm.org/route/v1/driving/%.4f,%.4f;%.4f,%.4f?overview=false'
             % (CITY[0], CITY[1], lon, lat))
        # Python's TLS stack fails the handshake with this router (SSLV3_ALERT,
        # 2026-09-13) while curl is fine, so curl carries the request
        import subprocess
        raw = subprocess.run(['curl', '-s', '-m', '30', '-A', 'bluishvoid.com foliage bake', u],
                             capture_output=True, text=True, timeout=40).stdout
        j = json.loads(raw)
        r = (j.get('routes') or [None])[0]
        if r and r.get('duration'):
            out = {'min': int(round(r['duration'] / 60.0)), 'mi': int(round(r['distance'] / 1609.34)), 'routed': True}
    except Exception as e:
        print('drive: %s unrouted (%s)' % (name, e))
    if out is None:
        d = math.hypot((lon - CITY[0]) * 53.0, (lat - CITY[1]) * 69.0)
        out = {'min': int(round(d * 1.25 / 48.0 * 60)), 'mi': int(round(d)), 'routed': False}
    cache[key] = out
    with open(DRIVE_CACHE, 'w') as fh:
        json.dump(cache, fh, indent=0, sort_keys=True)
    time.sleep(0.3)
    return out


def spots(prev):
    """The lookouts, located once through Nominatim and carried forward."""
    have = {x['name']: x for x in (prev or {}).get('spots') or []}
    out = []
    for name, st, region, how in SPOTS:
        if name in have and have[name].get('lat') is not None:
            sp = dict(have[name])
            if not (sp.get('drive') or {}).get('routed'):
                sp['drive'] = drive_minutes(name, sp['lat'], sp['lon'])
            out.append(sp); continue
        try:
            q = urllib.parse.urlencode({'q': '%s, %s' % (name, st), 'format': 'json', 'limit': 1})
            req = urllib.request.Request('https://nominatim.openstreetmap.org/search?' + q,
                                         headers={'User-Agent': 'bluishvoid.com foliage bake (contact via site)'})
            j = json.loads(urllib.request.urlopen(req, timeout=30).read())
            time.sleep(1.1)
            if not j:
                print('spot: %s not found' % name); continue
            la, lo = float(j[0]['lat']), float(j[0]['lon'])
            x, y = px(lo, la)
            if not (0 <= x < W and 0 <= y < H):
                print('spot: %s outside the box' % name); continue
            out.append({'name': name, 'lat': round(la, 4), 'lon': round(lo, 4), 'region': region, 'how': how,
                        'drive': drive_minutes(name, la, lo)})
        except Exception as e:
            print('spot: %s failed (%s)' % (name, e))
    return out


def npn_points(today):
    a = (today - datetime.timedelta(days=14)).isoformat()
    q = 'start_date=%s&end_date=%s&phenophase_id[0]=498&request_src=bluishvoid_foliage' % (a, today.isoformat())
    q += ''.join('&state[%d]=%s' % (i, s) for i, s in enumerate(STATES))
    try:
        rows = json.loads(get('https://services.usanpn.org/npn_portal/observations/getObservations.json?' + q, 240))
    except Exception as e:
        print('npn: unavailable (%s)' % e)
        return []
    best = {}
    for r in rows:
        if str(r.get('phenophase_status')) != '1':
            continue
        cls = CLASSES.get(r.get('intensity_value'))
        if cls is None:
            continue
        try:
            la, lo = float(r['latitude']), float(r['longitude'])
        except Exception:
            continue
        x, y = px(lo, la)
        if not (0 <= x < W and 0 <= y < H):
            continue
        key = (round(la, 3), round(lo, 3))
        d = str(r.get('observation_date') or '')
        cur = best.get(key)
        # the site's most recent report; ties go to the most coloured
        if cur is None or d > cur[3] or (d == cur[3] and cls > cur[2]):
            el = r.get('elevation_in_meters')
            best[key] = [round(la, 4), round(lo, 4), cls, d, str(r.get('common_name') or ''),
                         (int(el) if isinstance(el, (int, float)) and el > -999 else None)]
    pts = sorted(best.values(), key=lambda p: (-p[2], p[3]))[:500]
    print('npn: %d rows -> %d sites' % (len(rows), len(pts)))
    return pts


# CENTRAL PARK AT 10 M (user 2026-09-13: "build a small 10m display"). The
# park is three MODIS pixels wide; Sentinel-2 sees it at 10 m. Through the
# Planetary Computer's data API (keyless): every scene since August over the
# park's box, NDVI as (B08-B04)/(B08+B04) and the scene classification, both
# as numpy; a pixel counts only where the SCL says vegetation, bare, water or
# unclassified (4-7), so cloud, shadow and cirrus fall out; the August
# baseline is the clear-sky maximum of August, today is the maximum of the
# last PARK_DAYS days (widened once when nothing clear landed). The index
# and ramp are the big map's own, so the inset reads on the same legend.
PARK_BOX = (-73.982, 40.7645, -73.949, 40.8005)     # west, south, east, north
PARK_W, PARK_H = 300, 420
# the park itself, corner by corner (Columbus Circle, Grand Army Plaza,
# 110th & Fifth, 110th & Central Park West): everything outside is cut and
# the frame is turned so the park stands upright (user 2026-09-13: "remove
# the rest outside of central park")
PARK_POLY = [(-73.9819, 40.7681), (-73.9730, 40.7644), (-73.9493, 40.7968), (-73.9580, 40.8005)]
PARK_MARK = (-73.9625, 40.7855)     # the middle of the Jacqueline Kennedy Onassis Reservoir: the share and the date sit here
PARK_DAYS = 14
PARK_CLEAR = 0.5       # a look counts when this share of the box is clear by the scene's own mask
PARK_LANDSAT = False   # Landsat is wired but off: at 30 m its park pixels mix in street, and one hazy
                       # look inflated a max-composited baseline until 29 August read 40% turned against itself
PARK_FRAME = 'park_v1.webp'
PC_STAC = 'https://planetarycomputer.microsoft.com/api/stac/v1/search'
PC_DATA = 'https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/%s/%dx%d.npy' % (','.join(str(x) for x in PARK_BOX), PARK_W, PARK_H)


def park_scenes(since):
    """Sentinel-2 (10 m, every 2-5 days) and Landsat 8/9 (30 m, every 8)
    over the park since `since`, newest first: (collection, id, date)."""
    out = []
    for coll in ('sentinel-2-l2a', 'landsat-c2-l2'):
        body = json.dumps({'collections': [coll], 'bbox': list(PARK_BOX),
                           'datetime': since + 'T00:00:00Z/' + datetime.date.today().isoformat() + 'T23:59:59Z',
                           'query': {'eo:cloud_cover': {'lt': 80}}, 'limit': 60,
                           'sortby': [{'field': 'datetime', 'direction': 'desc'}]}).encode()
        req = urllib.request.Request(PC_STAC, data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'bluishvoid.com foliage bake'})
        try:
            j = json.loads(urllib.request.urlopen(req, timeout=60).read())
        except Exception as e:
            print('park: %s search failed (%s)' % (coll, e)); continue
        out += [(coll, f['id'], f['properties']['datetime'][:10]) for f in j.get('features', [])]
    return sorted(out, key=lambda x: x[2], reverse=True)


def park_ndvi(coll, scene_id):
    """the scene's NDVI over the park, NaN where the sky was not clear.
    Sentinel-2: the scene classification's vegetation and bare classes only
    (water, unclassified, cloud, shadow, cirrus all fall out -- 'unclassified'
    is mostly haze). Landsat: surface reflectance scaled (x0.0000275 - 0.2)
    before the ratio, cleared by the QA bits for fill, dilated cloud, cirrus,
    cloud and shadow."""
    q = '?collection=%s&item=%s' % (coll, scene_id)
    if coll == 'sentinel-2-l2a':
        a = np.load(io.BytesIO(get(PC_DATA + q + '&expression=' + urllib.parse.quote('(B08-B04)/(B08+B04)') + '&asset_as_band=true&resampling=bilinear', 120)))
        scl = np.load(io.BytesIO(get(PC_DATA + q + '&assets=SCL&resampling=nearest', 120)))
        ok = np.isin(scl[0], [4, 5])
    else:
        ex = '((nir08*0.0000275-0.2)-(red*0.0000275-0.2))/((nir08*0.0000275-0.2)+(red*0.0000275-0.2))'
        a = np.load(io.BytesIO(get(PC_DATA + q + '&expression=' + urllib.parse.quote(ex) + '&asset_as_band=true&resampling=bilinear', 120)))
        qa = np.load(io.BytesIO(get(PC_DATA + q + '&assets=qa_pixel&resampling=nearest', 120)))[0].astype(np.int64)
        ok = (qa & 0b11111) == 0
    nd = a[0].astype(np.float32)
    ok = ok & np.isfinite(nd) & (nd >= -1) & (nd <= 1) & ((a[1] > 0) if a.shape[0] > 1 else True)
    # the scene's own water call, so the inset can tell the reservoir from a
    # ball field's infield (both fall out of the canopy; they are not the same thing)
    water = (scl[0] == 6) if coll == 'sentinel-2-l2a' else ((qa >> 7) & 1) == 1
    return np.where(ok, nd, np.nan), float(ok.mean()), water


def park(prev):
    today = datetime.date.today()
    scenes = park_scenes((today.replace(month=8, day=1) if today.month >= 8 else datetime.date(today.year - 1, 8, 1)).isoformat())
    if not PARK_LANDSAT:
        scenes = [s for s in scenes if s[0] == 'sentinel-2-l2a']
    aug = [s for s in scenes if s[2][5:7] == '08']
    base_imgs, base_used, water_votes = [], [], []
    for coll, sid, d in aug:
        try:
            nd, clear, wet = park_ndvi(coll, sid)
            if clear >= 0.2:
                base_imgs.append(nd); base_used.append(d); water_votes.append(wet)
        except Exception as e:
            print('park: %s failed (%s)' % (sid, e))
    if not base_imgs:
        raise RuntimeError('no clear August scene over the park')
    base = np.nanmedian(np.stack(base_imgs), 0)     # the median of August, not its maximum: one bright outlier cannot set it
    water = np.mean(np.stack(water_votes), 0) >= 0.5   # water where most August looks called it water
    # TODAY: only a MOSTLY CLEAR look counts (PARK_CLEAR of the box clear by
    # the scene's own mask). Thin cloud and haze pass the masks at the edges
    # and depress NDVI, and a composite stitched from such scraps read the
    # park 49% turned on September 13 with nothing turned. Newest clear look
    # since the baseline month wins; if September has had none, the last
    # clear look of August stands in, flagged stale, so the inset says so.
    sep1 = today.replace(month=9, day=1).isoformat() if today.month >= 9 else (today.replace(day=1)).isoformat()
    looks = []          # (date, coll, ndvi) clear looks, newest first
    for coll, sid, d in scenes:
        if d < sep1 and looks:
            break
        try:
            nd, clear, _ = park_ndvi(coll, sid)
            print('park: %s %s clear %.0f%%' % (d, coll[:8], 100 * clear))
            if clear >= PARK_CLEAR:
                looks.append((d, coll, nd))
                if d >= sep1 and len(looks) >= 2:
                    break
        except Exception as e:
            print('park: %s failed (%s)' % (sid, e))
    if not looks:
        raise RuntimeError('no clear look at the park')
    fresh = [x for x in looks if x[0] >= sep1]
    stale = not fresh
    use = fresh if fresh else looks[:1]
    cur_imgs = [x[2] for x in use]
    cur_used = [(x[1], x[0]) for x in use]
    cur = np.nanmax(np.stack(cur_imgs), 0)
    with np.errstate(invalid='ignore', divide='ignore'):
        p = 1 - cur / base
    canopy = np.isfinite(base) & (base > 0.45)
    veg = canopy & np.isfinite(cur)
    coverage = float(veg.sum() / canopy.sum()) if canopy.any() else 0.0
    p = np.where(veg, np.clip(p, 0, 1), np.nan)
    # inside the park only: canopy on the ramp; what is not canopy splits in
    # two (user 2026-09-15: "all of these areas look like water but some of
    # those are baseball fields"): WATER (the reservoir, the Lake, the Meer)
    # a deep blue-black, BARE GROUND (the infields, the Met's roof, plazas,
    # paths) a dry earth tone; the city outside cut away
    W0, S0, E0, N0 = PARK_BOX
    poly = [((lon - W0) / (E0 - W0) * PARK_W, (N0 - lat) / (N0 - S0) * PARK_H) for lon, lat in PARK_POLY]
    mimg = Image.new('L', (PARK_W, PARK_H), 0)
    ImageDraw.Draw(mimg).polygon(poly, fill=255)
    inside = np.array(mimg) > 0
    p = np.where(inside, p, np.nan)
    img = np.array(ramp(p, 0.96, None).convert('RGBA'))
    fill = inside & ~np.isfinite(p)
    img[fill & water] = (14, 26, 46, 215)
    img[fill & ~water] = (118, 104, 82, 215)
    img[~inside] = (0, 0, 0, 0)
    # turn the frame so the park's long axis stands upright, then crop to it
    ang = math.degrees(math.atan2(poly[0][0] - poly[3][0], poly[0][1] - poly[3][1]))
    fr = Image.fromarray(img, 'RGBA').rotate(-ang, resample=Image.BICUBIC, expand=True)
    # the reservoir's middle, carried through the same turn and crop, so the
    # page can write the share and the date on the water
    mk = Image.new('L', (PARK_W, PARK_H), 0)
    ImageDraw.Draw(mk).ellipse([(PARK_MARK[0] - W0) / (E0 - W0) * PARK_W - 2, (N0 - PARK_MARK[1]) / (N0 - S0) * PARK_H - 2,
                                (PARK_MARK[0] - W0) / (E0 - W0) * PARK_W + 2, (N0 - PARK_MARK[1]) / (N0 - S0) * PARK_H + 2], fill=255)
    mk = mk.rotate(-ang, resample=Image.BICUBIC, expand=True)
    bb = fr.getbbox()
    crop = (max(0, bb[0] - 3), max(0, bb[1] - 3), min(fr.width, bb[2] + 3), min(fr.height, bb[3] + 3)) if bb else (0, 0, fr.width, fr.height)
    fr = fr.crop(crop); mk = mk.crop(crop)
    mka = np.array(mk)
    my, mx = np.unravel_index(int(mka.argmax()), mka.shape)
    mark = [round(float(mx) / fr.width, 3), round(float(my) / fr.height, 3)]
    fr.save(os.path.join(OUT, PARK_FRAME), 'WEBP', quality=88, method=6)
    out_w, out_h = fr.size
    pct = int(round(100 * float(np.nanmean(p)))) if veg.any() else None
    dates = sorted(set(d for _, d in cur_used))
    out = {'url': CDN + PARK_FRAME, 'w': out_w, 'h': out_h, 'box': list(PARK_BOX), 'as_of': dates[-1], 'mark': mark,
           'scenes': dates, 'base_scenes': sorted(set(base_used)), 'pct': pct,
           'coverage': round(coverage, 2), 'thin': coverage < 0.6, 'stale': stale, 'canopy_share': round(float(canopy.mean()), 3),
           'water_share': round(float((inside & water).sum() / max(1, inside.sum())), 3),
           'built': today.isoformat()}
    print('park: %s%% turned as of %s, %.0f%% of the canopy seen (scenes %s; baseline %d August looks)'
          % (pct, out['as_of'], 100 * coverage, ','.join(dates), len(base_used)))
    return out


def main():
    today = datetime.date.today()
    keys, vals = colormap()
    prev = previous()                      # yesterday's file: history, last year, spots, the archive list
    aug = [datetime.date(today.year, 8, 5), datetime.date(today.year, 8, 13),
           datetime.date(today.year, 8, 21), datetime.date(today.year, 8, 29)]
    print('baseline (August %d):' % today.year, flush=True)
    base_imgs = [v for v in (ndvi(d, keys, vals) for d in aug) if v is not None]
    if not base_imgs:
        raise SystemExit('no August baseline yet')
    base = np.nanmax(np.stack(base_imgs), 0)
    print('current (newest composite and the one six days before):', flush=True)
    pair = [(d, v) for d, v in latest_two(today, keys, vals) if d > aug[-1]]
    cur_imgs = [v for _, v in pair]
    cur_dates = [d.isoformat() for d, _ in pair]
    if not cur_imgs:
        cur_imgs, cur_dates = [base], ['baseline']      # August: nothing has turned yet
    cur = np.nanmax(np.stack(cur_imgs), 0)
    shade = relief()
    # ONLY TYPED FOREST CARRIES THE INDEX (user 2026-09-13: "why does this
    # scattering happen?"). Masked by greenness alone, harvested cornfields
    # and mown hay on the Lake Ontario plain, in the Champlain and St
    # Lawrence valleys and round the Finger Lakes read as 15-25% "turned" in
    # mid-September, and lake-edge pixels with a low August baseline
    # inflated small changes into big shares. The Forest Service's typed
    # forest, at the same 250 m, is the honest mask; farmland, towns and
    # water get no index at all and the map shows through.
    # CANADA TOO (user 2026-09-13: "last season shows canada but all other
    # views block canada out"). The Forest Service's typed forest stops at
    # the border, so north of it the index fell back to nothing. Outside the
    # counties -- which is Canada and the sea in this box -- the greenness
    # rule alone (August NDVI > 0.55, in index_of) carries the index, the
    # way the whole map did before the forest mask; the species frame keeps
    # to the typed forest it is made from.
    shapes = county_shapes()
    labels, ids = county_labels(shapes)
    global FOREST_MASK
    forest_only = None
    try:
        forest_only = forest(shade, prev) > 0
        north = canada_mask()
        igbp = igbp_forest()
        FOREST_MASK = forest_only | (north & igbp if igbp is not None else north)
    except Exception as e:
        print('forest mask: unavailable (%s), falling back to greenness' % e)
        FOREST_MASK = None
    p = index_of(cur, base, FOREST_MASK)
    frame(p, shade).save(os.path.join(OUT, 'latest.webp'), 'WEBP', quality=82, method=6)   # ~1/6 the PNG, alpha kept
    bands(p, shade).save(os.path.join(OUT, 'latest_bands.webp'), 'WEBP', quality=82, method=6)
    bands(p, shade, blobs=True).save(os.path.join(OUT, 'latest_blobs.webp'), 'WEBP', quality=82, method=6)
    counties_now = county_means(labels, ids, p)
    try:
        fcodes = FOREST_CODES if FOREST_CODES is not None else forest(shade, prev)
        forest_by_county = forest_shares(fcodes, labels, ids)
        try:
            species(shade, forest_only)
        except Exception as e:
            print('species: unavailable (%s)' % e)
    except Exception as e:
        print('forest: unavailable (%s)' % e)
        fcodes, forest_by_county = None, {}
    counties_ly = county_last_year(today.year - 1, keys, vals, labels, ids, prev)
    print('counties: %d with a reading today' % len(counties_now))
    # LAST SEASON, WEEK BY WEEK (user 2026-09-13: "what will the map look like
    # during peak?"): the same frame for each week of last autumn, baked once
    # and kept on R2 under season/<year>/, so the page can play the wave
    season_last = season_frames(today.year - 1, keys, vals, shade)
    # and this season's own weekly archive, one frame a week, for the same loop
    season_this = archive_this_season(today, prev)
    ly = last_year_curve(today.year - 1, keys, vals, prev)
    # the season's history rides in the file: one row per bake day, 90 days
    hist = [h for h in (prev.get('history') or []) if h.get('date') and h['date'] != today.isoformat()][-89:]
    means = region_means(p)
    hist.append({'date': today.isoformat(), 'pct': {n: v[0] for n, v in means.items()}, 'counties': counties_now})
    week_ago = (today - datetime.timedelta(days=7)).isoformat()
    older = [h for h in hist if h['date'] <= week_ago]
    ref = older[-1]['pct'] if older else None
    anchors = [(name, ANCHOR.get(name, ((la0 + la1) / 2, (lo0 + lo1) / 2))) for name, lo0, lo1, la0, la1 in REGIONS]
    wx, sat = weekend(today, anchors)
    regions = []
    for name, lo0, lo1, la0, la1 in REGIONS:
        if name not in means:
            continue
        pct, past = means[name]
        pk_date, pk_level = (None, None)
        if ly and ly.get('regions', {}).get(name):
            pk_date, pk_level = peak_of(ly['dates'], ly['regions'][name])
        alat, alon = ANCHOR.get(name, ((la0 + la1) / 2, (lo0 + lo1) / 2))
        regions.append({'name': name, 'lat': round(alat, 3), 'lon': round(alon, 3), 'pri': PRI.get(name, 66),
                        'drive': drive_minutes(name, alat, alon),
                        'pct': pct, 'past_peak': past, 'band': band(pct, pk_level),
                        'delta7': ((pct - ref[name]) if (ref and name in ref) else None),
                        'peak_last_year': pk_date, 'peak_level': pk_level,
                        'pace_days': pace(today, pct, ly, name), 'weekend': wx.get(name)})
    try:
        park_doc = park(prev)
    except Exception as e:
        print('park: unavailable (%s)' % e)
        park_doc = (prev or {}).get('park')
    doc = {'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'park': park_doc,
           'composites': cur_dates, 'baseline': [d.isoformat() for d in aug[:len(base_imgs)]],
           'layer': LAYER, 'box': BOX, 'w': W, 'h': H, 'regions': regions, 'bands': BANDS, 'rel_bands': REL,
           'history': hist, 'last_year': ly, 'weekend_from': sat, 'spots': spots(prev),
           'season_last': season_last, 'season_this': season_this, 'ramp': RAMP_LEGEND,
           'counties': counties_now, 'counties_ly': counties_ly, 'counties_url': CDN + 'counties.json',
           'forest_url': CDN + FOREST_FRAME, 'forest_codes_url': CDN + 'forest_codes.png',
           'forest_legend': [[r, txt, list(rgb)] for r, txt, rgb in FOREST_LEGEND],
           'forest_roles': [[lab, role] for lab, role, _ in FOREST_ROLES], 'forest_by_county': forest_by_county,
           'species_url': CDN + SPECIES_FRAME, 'species_codes_url': CDN + 'species_codes.png',
           'species_legend': [[r, txt, list(rgb)] for r, txt, rgb, _ in SPECIES],
           'species_roles': [[r, txt] for r, txt, _, _ in SPECIES],
           'points': npn_points(today), 'points_since': (today - datetime.timedelta(days=14)).isoformat(),
           'classes': ['<5%', '5-24%', '25-49%', '50-74%', '75-94%', '95%+']}
    with open(os.path.join(OUT, 'latest.json'), 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('wrote', OUT, '| composites', cur_dates, '| regions', ', '.join('%s %d%%' % (r['name'], r['pct']) for r in regions))


if __name__ == '__main__':
    if '--park' in sys.argv:
        # the inset alone, merged into the plan file already under OUT
        _pp = os.path.join(OUT, 'latest.json')
        _prev = json.load(open(_pp)) if os.path.exists(_pp) else {}
        _prev['park'] = park(_prev)
        with open(_pp, 'w') as fh:
            json.dump(_prev, fh)
        print('park merged into', _pp)
        sys.exit(0)
    main()
