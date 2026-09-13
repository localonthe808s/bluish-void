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
import datetime, io, json, os, re, sys, time, urllib.parse, urllib.request
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


def bands(p, shade, sigma=7):
    """THE BANDS LOOK (user 2026-09-13: "id rather see bands"): the index
    blurred to landscape scale (sigma 7 px ~ 6 km) and posterised to the
    ramp's own stops, so the colour comes as bands that follow the hills
    rather than county lines or 250 m speckle. Same relief undertone."""
    pm = np.where(np.isfinite(p), p, np.nan).astype(np.float32)
    fill = np.nanmean(pm) if np.isfinite(pm).any() else 0.0
    im = Image.fromarray((np.clip(np.where(np.isfinite(pm), pm, fill), 0, 1) * 250 + 2).astype(np.uint8))
    bl = np.array(im.filter(ImageFilter.GaussianBlur(sigma))).astype(np.float32)
    q = np.where(np.isfinite(pm), (bl - 2) / 250.0, np.nan)
    # posterise: each pixel takes the lower stop of the band it falls in
    stops = [st for st, _ in RAMP[:-1]]
    post = np.full_like(q, np.nan)
    for lo in stops:
        post = np.where(np.isfinite(q) & (q >= lo), lo + 0.001, post)
    return ramp(post, shade=shade)


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
    try:
        req = urllib.request.Request(CDN + path, method='HEAD', headers={'User-Agent': 'bluishvoid.com foliage bake'})
        return urllib.request.urlopen(req, timeout=20).status == 200
    except Exception:
        return False


def season_frames(year, keys, vals, shade):
    """Weekly frames for a past season, Sep 15 - Nov 10, rendered only for
    dates not already on the CDN. Returns the list of dates that exist (on
    the CDN or freshly written under OUT/season/<year>/)."""
    dates, todo = [], []
    d = datetime.date(year, 9, 15)
    while d <= datetime.date(year, 11, 10):
        if on_cdn('season/%d/%s.webp' % (year, d.isoformat())) and on_cdn('season/%d/%s_bands.webp' % (year, d.isoformat())):
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
                with np.errstate(invalid='ignore', divide='ignore'):
                    pp = 1 - cur / base
                pp[~(base > 0.45)] = np.nan
                frame(np.clip(pp, 0, 1), shade).save(os.path.join(OUT, 'season', str(year), d.isoformat() + '.webp'), 'WEBP', quality=82, method=6)
                bands(np.clip(pp, 0, 1), shade).save(os.path.join(OUT, 'season', str(year), d.isoformat() + '_bands.webp'), 'WEBP', quality=82, method=6)
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
    while d <= datetime.date(year, 11, 10):
        v = ndvi(d, keys, vals)
        v2 = ndvi(d - datetime.timedelta(days=6), keys, vals)
        if v is not None:
            cur = np.nanmax(np.stack([x for x in (v, v2) if x is not None]), 0)
            with np.errstate(invalid='ignore', divide='ignore'):
                pp = 1 - cur / base
            pp[~(base > 0.45)] = np.nan
            m = county_means(labels, ids, np.clip(pp, 0, 1))
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
# never turn. Rendered once a season as forest_v1.webp with the relief, plus
# forest_codes.png (one byte a pixel, the group index) for the page's taps.
FTG = ('https://imagery.geoplatform.gov/iipp/rest/services/Vegetation/'
       'USFS_EDW_FIA_ForestAtlas_ForestTypeGroups_109_CONUS/ImageServer')
FOREST_ROLES = [   # (label as the atlas prints it, our role, display rgb)
    ('Maple/Beech/Birch Group', 'THE SHOW', (232, 108, 38)),
    ('Aspen/Birch Group', 'GOLD', (240, 200, 60)),
    ('Elm/Ash/Cottonwood Group', 'GOLD', (222, 182, 70)),
    ('Oak/Hickory Group', 'LATE, RUSSET', (168, 106, 58)),
    ('Oak/Pine Group', 'LATE, RUSSET', (150, 120, 62)),
    ('Oak/Gum/Cypress Group', 'LATE, RUSSET', (158, 132, 60)),
    ('Spruce/Fir Group', 'EVERGREEN', (26, 84, 48)),
    ('White/Red/Jack Pine Group', 'EVERGREEN', (32, 96, 52)),
    ('Loblolly/Shortleaf Pine Group', 'EVERGREEN', (36, 100, 54)),
    ('Longleaf/Slash Pine Group', 'EVERGREEN', (36, 100, 54)),
    ('Pinyon/Juniper Group', 'EVERGREEN', (40, 96, 56)),
    ('Douglas-fir Group', 'EVERGREEN', (30, 90, 50)),
    ('Exotic Softwoods Group', 'EVERGREEN', (44, 98, 58)),
]
FOREST_LEGEND = [('THE SHOW', 'MAPLE, BEECH, BIRCH', (232, 108, 38)), ('GOLD', 'ASPEN, BIRCH, ASH', (240, 200, 60)),
                 ('LATE, RUSSET', 'OAK, HICKORY', (168, 106, 58)), ('EVERGREEN', 'SPRUCE, FIR, PINE', (30, 92, 52))]


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
    print('forest: %.0f%% of the box is typed forest' % (100 * (codes > 0).mean()))
    if not (on_cdn('forest_v1.webp') and on_cdn('forest_codes.png')):
        img = np.zeros((H, W, 4), np.uint8)
        for i, (label, role, rgb) in enumerate(FOREST_ROLES):
            m = codes == i + 1
            col = np.array(rgb, np.float32)[None, :]
            if shade is not None:
                f = np.clip(1.0 + (shade[m] - 127.0) / 85.0, 0.55, 1.4)[:, None]
                col = col * f
            img[m, :3] = np.clip(col, 0, 255).astype(np.uint8)
            img[m, 3] = 218
        Image.fromarray(img).save(os.path.join(OUT, 'forest_v1.webp'), 'WEBP', quality=82, method=6)
        Image.fromarray(codes, 'L').save(os.path.join(OUT, 'forest_codes.png'), optimize=True)
    return codes


def forest_shares(codes, labels, ids):
    """per county fips -> {'show': %, 'gold': %, 'late': %, 'ever': %} of its typed forest"""
    role_of = {i + 1: r for i, (_, r, _) in enumerate(FOREST_ROLES)}
    key = {'THE SHOW': 'show', 'GOLD': 'gold', 'LATE, RUSSET': 'late', 'EVERGREEN': 'ever'}
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
           ('Shawangunks', -74.35, -74.15, 41.65, 41.82), ('Harriman & Bear Mountain', -74.12, -73.9, 41.2, 41.36),
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
       'Poconos': 68, 'Harriman & Bear Mountain': 68, 'Litchfield Hills': 64, 'Delaware Water Gap': 64,
       'Shawangunks': 62}
ANCHOR = {'Hudson Valley': (41.56, -73.52), 'Shawangunks': (41.72, -74.42), 'Catskills': (42.12, -74.45)}
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
    """(date, level) of the fastest weekly decline in greenness on a lightly
    smoothed curve -- peak colour -- or (None, None)."""
    pts = [(dt, x) for dt, x in zip(dates, arr) if x is not None]
    if len(pts) < 4:
        return None, None
    xs = [x for _, x in pts]
    sm = [xs[0]] + [(xs[i - 1] + xs[i] + xs[i + 1]) / 3.0 for i in range(1, len(xs) - 1)] + [xs[-1]]
    best, bi = None, None
    for i in range(1, len(sm)):
        d = sm[i] - sm[i - 1]
        if best is None or d > best:
            best, bi = d, i
    if bi is None:
        return None, None
    return pts[bi][0], int(round(sm[bi]))


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
    """Last season's progress per region, weekly Sep 15 - Nov 10, from the same
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
    while d <= datetime.date(year, 11, 10):
        v = ndvi(d, keys, vals)
        v2 = ndvi(d - datetime.timedelta(days=6), keys, vals)
        if v is not None:
            cur = np.nanmax(np.stack([x for x in (v, v2) if x is not None]), 0)
            with np.errstate(invalid='ignore', divide='ignore'):
                pp = 1 - cur / base
            pp[~(base > 0.45)] = np.nan
            pp = np.clip(pp, 0, 1)
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


SPOTS = [
    ('Bear Mountain', 'NY', 'Harriman & Bear Mountain', 'Metro-North to Peekskill, then a taxi'),
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


def spots(prev):
    """The lookouts, located once through Nominatim and carried forward."""
    have = {x['name']: x for x in (prev or {}).get('spots') or []}
    out = []
    for name, st, region, how in SPOTS:
        if name in have and have[name].get('lat') is not None:
            out.append(have[name]); continue
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
            out.append({'name': name, 'lat': round(la, 4), 'lon': round(lo, 4), 'region': region, 'how': how})
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
    with np.errstate(invalid='ignore', divide='ignore'):
        p = 1 - cur / base
    p[~(base > 0.45)] = np.nan
    p = np.clip(p, 0, 1)
    shade = relief()
    frame(p, shade).save(os.path.join(OUT, 'latest.webp'), 'WEBP', quality=82, method=6)   # ~1/6 the PNG, alpha kept
    bands(p, shade).save(os.path.join(OUT, 'latest_bands.webp'), 'WEBP', quality=82, method=6)
    shapes = county_shapes()
    labels, ids = county_labels(shapes)
    counties_now = county_means(labels, ids, p)
    try:
        fcodes = forest(shade, prev)
        forest_by_county = forest_shares(fcodes, labels, ids)
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
                        'pct': pct, 'past_peak': past, 'band': band(pct, pk_level),
                        'delta7': ((pct - ref[name]) if (ref and name in ref) else None),
                        'peak_last_year': pk_date, 'peak_level': pk_level,
                        'pace_days': pace(today, pct, ly, name), 'weekend': wx.get(name)})
    doc = {'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'composites': cur_dates, 'baseline': [d.isoformat() for d in aug[:len(base_imgs)]],
           'layer': LAYER, 'box': BOX, 'w': W, 'h': H, 'regions': regions, 'bands': BANDS, 'rel_bands': REL,
           'history': hist, 'last_year': ly, 'weekend_from': sat, 'spots': spots(prev),
           'season_last': season_last, 'season_this': season_this, 'ramp': RAMP_LEGEND,
           'counties': counties_now, 'counties_ly': counties_ly, 'counties_url': CDN + 'counties.json',
           'forest_url': CDN + 'forest_v1.webp', 'forest_codes_url': CDN + 'forest_codes.png',
           'forest_legend': [[r, txt, list(rgb)] for r, txt, rgb in FOREST_LEGEND],
           'forest_roles': [[lab, role] for lab, role, _ in FOREST_ROLES], 'forest_by_county': forest_by_county,
           'points': npn_points(today), 'points_since': (today - datetime.timedelta(days=14)).isoformat(),
           'classes': ['<5%', '5-24%', '25-49%', '50-74%', '75-94%', '95%+']}
    with open(os.path.join(OUT, 'latest.json'), 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('wrote', OUT, '| composites', cur_dates, '| regions', ', '.join('%s %d%%' % (r['name'], r['pct']) for r in regions))


if __name__ == '__main__':
    main()
