#!/usr/bin/env python3
"""FALL FOLIAGE FOR NORTH AMERICA (user 2026-10-17: "can you do what weve done for northeast foliage for north america?").

THE NORTHEAST TAB'S METHOD, unchanged (_maplab/foliage_bake.py): NASA GIBS MODIS_Terra_NDVI_8Day (250 m rolling composite)
decoded through the GIBS colormap; current = max of the newest composite and the one six days earlier (THE CLOUD RULE:
never difference one composite); baseline = max of the August composites; progress = 1 - current/baseline, only on forest
(MODIS IGBP land cover: the five forest classes and woody savanna) where August greenness > 0.55; a 5-px median; the same
peak-centred colour ramp (green -> yellow -> orange at 20% = peak -> red -> brown 40%+ bare).

Cut into a tile pyramid instead of one frame: computed at z7 (~1.2 km at 45 N; 1 km is what a continent needs, and it
keeps a daily bake inside a CI runner), in 2048 px blocks over 24-70 N, -170..-52, then z3-6 by averaging. Blocks with no
forest are skipped. The August baseline and the forest mask are fixed for the season, so each is cached per block as a
.npz (BASE_DIR) and only the two current composites are fetched daily.
Plus the USA-NPN "colored leaves" reports of the last fortnight for every state (points.json).

    python3 na.py OUT [BASE_DIR]       -> OUT/{z}/{x}/{y}.webp, OUT/points.json, OUT/meta.json
"""
import datetime, io, json, math, os, re, sys, urllib.request
import numpy as np
from PIL import Image, ImageFilter
from concurrent.futures import ThreadPoolExecutor

OUT = sys.argv[1]; BASE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(OUT, '..', 'foliage_base')
os.makedirs(OUT, exist_ok=True); os.makedirs(BASE, exist_ok=True)
WMS = 'https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi'
LAYER = 'MODIS_Terra_NDVI_8Day'
CMAP = 'https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_NDVI.xml'
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
STATES = ['AL','AZ','AR','CA','CO','CT','DE','FL','GA','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT',
          'NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','AK','DC']
CLASSES = {'Less than 5%': 0, '5-24%': 1, '25-49%': 2, '50-74%': 3, '75-94%': 4, '95% or more': 5}
Z = 7; BLK = 2048; R = 6378137.0; WORLD = 2 * math.pi * R
LON0, LON1, LAT0, LAT1 = -170.0, -52.0, 24.0, 70.0

def get(u, timeout=240):
    for a in range(4):
        try: return urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'bluishvoid.com foliage bake'}), timeout=timeout).read()
        except Exception:
            if a == 3: raise

def colormap():
    x = get(CMAP).decode('utf-8', 'replace')
    ents = re.findall(r'<ColorMapEntry[^>]*rgb="(\d+),(\d+),(\d+)"[^>]*value="\[?([-\d.]+)', x)
    lut = {}
    for r, g, b, v in ents: lut[(int(r) << 16) | (int(g) << 8) | int(b)] = float(v)
    return lut

def tile_px(lon, lat):
    n = 256 * 2 ** Z
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

def bbox_of(px0, py0, w, h):
    n = 256 * 2 ** Z; mpp = WORLD / n
    return (-WORLD / 2 + px0 * mpp, WORLD / 2 - (py0 + h) * mpp, -WORLD / 2 + (px0 + w) * mpp, WORLD / 2 - py0 * mpp)

def wms(layer, bb, w, h, time):
    u = (WMS + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=%s&CRS=EPSG:3857&BBOX=%.0f,%.0f,%.0f,%.0f&WIDTH=%d&HEIGHT=%d&FORMAT=image/png&TIME=%s'
         % ((layer,) + bb + (w, h, time)))
    return np.array(Image.open(io.BytesIO(get(u))).convert('RGB')).astype(np.uint32)

LUT = None
def ndvi(bb, w, h, date):
    a = wms(LAYER, bb, w, h, date.isoformat())
    key = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
    uk, inv = np.unique(key, return_inverse=True)
    vals = np.array([LUT.get(int(k), np.nan) for k in uk], np.float32)
    return vals[inv].reshape(key.shape)

def forest(bb, w, h):
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

def main():
    global LUT
    LUT = colormap(); today = datetime.date.today(); yr = today.year
    probe = bbox_of(*tile_px(-74.5, 44.0), 64, 64)
    d1 = published(probe, today); d2 = published(probe, d1 - datetime.timedelta(days=6)) if d1 else None
    print('composites', d1, d2)
    aug = [datetime.date(yr, 8, d) for d in (8, 16, 24, 31)]
    x0, y0 = tile_px(LON0, LAT1); x1, y1 = tile_px(LON1, LAT0)
    blocks = [(bx, by) for bx in range(x0 // BLK * BLK, x1, BLK) for by in range(y0 // BLK * BLK, y1, BLK)]
    made = {}
    def work(b):
        bx, by = b; bb = bbox_of(bx, by, BLK, BLK); cache = os.path.join(BASE, 'b_%d_%d.npz' % (bx, by))
        if os.path.exists(cache):
            z = np.load(cache); base = z['base'].astype(np.float32) / 250; fm = z['forest']
            if base.size == 1: return 0
        else:
            fm = forest(bb, BLK, BLK)
            if fm is None or fm.mean() < 0.002: np.savez_compressed(cache, base=np.zeros(1, np.uint8), forest=np.zeros(1, bool)); return 0
            base = None
            for d in aug:
                try: v = ndvi(bb, BLK, BLK, d)
                except Exception: continue
                base = v if base is None else np.fmax(base, v)
            if base is None: return 0
            np.savez_compressed(cache, base=np.nan_to_num(np.clip(base, 0, 1) * 250).astype(np.uint8), forest=fm)
            base = np.round(np.nan_to_num(np.clip(base, 0, 1)) * 250) / 250
        cur = None
        for d in (d1, d2):
            if not d: continue
            try: v = ndvi(bb, BLK, BLK, d)
            except Exception: continue
            cur = v if cur is None else np.fmax(cur, v)
        if cur is None: return 0
        with np.errstate(invalid='ignore', divide='ignore'): p = 1 - cur / base
        p = np.where(np.isfinite(p) & (base > 0.55) & fm, np.clip(p, 0, 1), np.nan)
        pm = np.where(np.isfinite(p), p, -1).astype(np.float32)
        med = np.array(Image.fromarray((np.clip(pm, 0, 1) * 250 + 2).astype(np.uint8)).filter(ImageFilter.MedianFilter(5))).astype(np.float32)
        p = np.where(np.isfinite(p), (med - 2) / 250, np.nan)
        np.save(os.path.join(BASE, 'p_%d_%d.npy' % (bx, by)), np.nan_to_num(p * 250, nan=255).astype(np.uint8))
        img = ramp(p); n = 0
        for i in range(BLK // 256):
            for j in range(BLK // 256):
                sub = img[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256]
                if sub[..., 3].max() == 0: continue
                tx, ty = (bx // 256) + i, (by // 256) + j; pth = os.path.join(OUT, str(Z), str(tx)); os.makedirs(pth, exist_ok=True)
                Image.fromarray(sub).save(os.path.join(pth, '%d.webp' % ty), 'WEBP', quality=70, alpha_quality=80, method=4); n += 1
        print('block', bx, by, n, 'tiles', flush=True); return n
    with ThreadPoolExecutor(4) as ex: tot = sum(ex.map(work, blocks))
    # z6..z3 from the progress grids: average the 2x2 children's progress (ignoring non-forest), then the same ramp
    grids = {}
    for f in os.listdir(BASE):
        if f.startswith('p_'):
            bx, by = map(int, f[2:-4].split('_')); grids[(bx, by)] = f
    for zz in range(Z - 1, 2, -1):
        k = 2 ** (Z - zz); tiles = {}
        for (bx, by), f in grids.items():
            a = np.load(os.path.join(BASE, f)).astype(np.float32); a[a == 255] = np.nan; a /= 250
            h = BLK // k
            with np.errstate(invalid='ignore'): s = np.nanmean(a.reshape(h, k, h, k).swapaxes(1, 2).reshape(h, h, k * k), 2)
            ox, oy = bx // k, by // k
            for i in range(0, h, 256):
                for j in range(0, h, 256):
                    tiles.setdefault(((ox + i) // 256, (oy + j) // 256), []).append((((ox + i) % 256, (oy + j) % 256), s[j:j + 256, i:i + 256]))
        for (tx, ty), parts in tiles.items():
            canv = np.full((256, 256), np.nan, np.float32)
            for (ix, iy), s in parts:
                hh, ww = s.shape; canv[iy:iy + hh, ix:ix + ww] = np.where(np.isfinite(s), s, canv[iy:iy + hh, ix:ix + ww])
            img = ramp(canv)
            if img[..., 3].max() == 0: continue
            pth = os.path.join(OUT, str(zz), str(tx)); os.makedirs(pth, exist_ok=True)
            Image.fromarray(img).save(os.path.join(pth, '%d.webp' % ty), 'WEBP', quality=70, alpha_quality=80, method=4)
        print('z%d: %d tiles' % (zz, len(tiles)), flush=True)
    pts = npn(today)
    json.dump({'built': datetime.datetime.utcnow().isoformat()[:16] + 'Z', 'composites': [str(d1), str(d2)], 'baseline': [str(d) for d in aug],
               'points': pts, 'ramp': RAMP}, open(os.path.join(OUT, 'meta.json'), 'w'), separators=(',', ':'))
    print('tiles z7', tot)

main()
