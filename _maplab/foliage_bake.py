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
from PIL import Image

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


def ramp(p, alpha=0.80):
    h, w = p.shape
    img = np.zeros((h, w, 4), np.uint8)
    stops = [(0.0, (34, 120, 40)), (0.12, (150, 190, 40)), (0.25, (240, 200, 40)),
             (0.40, (235, 120, 30)), (0.55, (200, 40, 30)), (0.75, (120, 60, 30)), (1.01, (90, 45, 25))]
    m = np.isfinite(p)
    for i in range(len(stops) - 1):
        a, ca = stops[i]; b, cb = stops[i + 1]
        sel = m & (p >= a) & (p < b)
        if not sel.any():
            continue
        t = ((p - a) / (b - a))[sel][:, None]
        img[sel, :3] = (np.array(ca) * (1 - t) + np.array(cb) * t).astype(np.uint8)
        img[sel, 3] = int(255 * alpha)
    return Image.fromarray(img)


def px(lon, lat):
    x = lon * np.pi / 180 * R
    y = R * np.log(np.tan(np.pi / 4 + lat * np.pi / 360))
    return (x - BOX[0]) / (BOX[2] - BOX[0]) * W, (BOX[3] - y) / (BOX[3] - BOX[1]) * H


REGIONS = [('Adirondacks', -74.6, -73.6, 43.6, 44.4), ('Catskills', -74.7, -74.0, 41.9, 42.3),
           ('Finger Lakes', -77.3, -76.3, 42.3, 42.9), ('Green Mountains', -73.1, -72.6, 43.0, 44.3),
           ('White Mountains', -71.7, -71.0, 43.9, 44.4), ('Berkshires', -73.4, -72.9, 42.1, 42.7),
           ('Poconos', -75.6, -75.0, 41.0, 41.4), ('Hudson Valley', -74.0, -73.6, 41.2, 41.8),
           ('New York City & Long Island', -74.1, -72.2, 40.6, 41.0)]
CLASSES = {'Less than 5%': 0, '5-24%': 1, '25-49%': 2, '50-74%': 3, '75-94%': 4, '95% or more': 5}


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
    img = ramp(p)
    img.save(os.path.join(OUT, 'latest.webp'), 'WEBP', quality=82, method=6)   # ~1/6 the PNG, alpha kept
    regions = []
    for name, lo0, lo1, la0, la1 in REGIONS:
        x0, y1 = px(lo0, la0); x1, y0 = px(lo1, la1)
        sub = p[int(max(0, y0)):int(min(H, y1)), int(max(0, x0)):int(min(W, x1))]
        m = np.isfinite(sub)
        if m.sum() < 50:
            continue
        regions.append({'name': name, 'pct': int(round(100 * float(np.nanmean(sub)))),
                        'past_peak': int(round(100 * float((sub[m] >= 0.5).mean())))})
    doc = {'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'composites': cur_dates, 'baseline': [d.isoformat() for d in aug[:len(base_imgs)]],
           'layer': LAYER, 'box': BOX, 'w': W, 'h': H, 'regions': regions,
           'points': npn_points(today), 'points_since': (today - datetime.timedelta(days=14)).isoformat(),
           'classes': ['<5%', '5-24%', '25-49%', '50-74%', '75-94%', '95%+']}
    with open(os.path.join(OUT, 'latest.json'), 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('wrote', OUT, '| composites', cur_dates, '| regions', ', '.join('%s %d%%' % (r['name'], r['pct']) for r in regions))


if __name__ == '__main__':
    main()
