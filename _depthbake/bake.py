#!/usr/bin/env python3
"""SEAFLOOR DEPTH AS NUMBERS, ON THE CDN (user 2026-10-17: "do 1-4", moving yesterday's live fetches onto Cloudflare). The
TIDES view's moving sea (swell_core.js) read depth straight from NOAA NCEI's DEM_all ImageServer for every view -- several
~1 MB uncompressed F32 requests per pan, never reusable. Baked here once from the same source (CUDEM 1/9" where it exists,
else the Coastal Relief Models) into a web-mercator pyramid of NUMERIC tiles:

  256 px lossless WebP; a sea pixel (DEM below 0 m) is opaque with depth in DECIMETRES = R*256 + G (to 6,553 m), B 0; a land
  pixel is opaque with B 255; no data is transparent (the swell code reads that as "not surveyed", not as land).

z8 is fetched tile by tile (DEM_all silently returns no data for wide boxes -- the swell port found a 9x6 degree box 88%
empty -- and a z8 tile is 1.4 degrees), then the quadtree descends to z12 only under tiles holding shelf water (some sea
shallower than 200 m), 2x2 or 4x4 tiles a request; z5-7 are built from z8 by 2x2 means. cover.json = the z8 tiles baked.

    python3 bake.py OUT [--workers 6]
"""
import io, json, math, os, sys, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np, tifffile
from PIL import Image

SRC = 'https://gis.ngdc.noaa.gov/arcgis/rest/services/DEM_mosaics/DEM_all/ImageServer/exportImage'
R = 6378137.0; T = 256
REGIONS = [((-125.5, 24.0, -66.5, 49.6), 12), ((-160.6, 18.5, -154.4, 22.6), 12), ((-68.2, 17.5, -64.3, 18.8), 12), ((-179.9, 51.0, -129.5, 71.6), 10)]

def tile_bounds(z, x, y):
    n = 2 ** z; s = 2 * math.pi * R / n; x0 = -math.pi * R + x * s; y1 = math.pi * R - y * s
    return x0, y1 - s, x0 + s, y1

def lonlat_tile(lon, lat, z):
    n = 2 ** z; lat = max(-85, min(85, lat))
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

def fetch(z, bx, by, B):
    x0, _, _, y1 = tile_bounds(z, bx * B, by * B); _, y0, x1, _ = tile_bounds(z, bx * B + B - 1, by * B + B - 1)
    q = dict(bbox='%.3f,%.3f,%.3f,%.3f' % (x0, y0, x1, y1), bboxSR=3857, imageSR=3857, size='%d,%d' % (B * T, B * T), format='tiff',
             pixelType='F32', interpolation='RSP_BilinearInterpolation', f='image')
    for a in range(5):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(SRC + '?' + urllib.parse.urlencode(q), headers={'User-Agent': 'bluishvoid.com depth bake'}), timeout=180).read()
            h = tifffile.imread(io.BytesIO(raw)).astype(np.float32)
            if h.ndim == 3: h = h[..., 0]
            h[(h < -1e5) | (h > 1e5)] = np.nan
            return h
        except Exception as e:
            if a == 4: raise
            time.sleep(5 * (a + 1))

def encode(h, land=None):
    fin = np.isfinite(h); sea = fin & (h < 0); ld = (fin & (h >= 0)) if land is None else land
    dm = np.clip(np.round(np.nan_to_num(-h) * 10), 1, 65535).astype(np.uint32)
    img = np.zeros(h.shape + (4,), np.uint8)
    img[..., 0] = np.where(sea, dm >> 8, 0); img[..., 1] = np.where(sea, dm & 255, 0); img[..., 2] = np.where(ld & ~sea, 255, 0)
    img[..., 3] = np.where(sea | ld, 255, 0)
    return img, bool(sea.any()), bool((sea & (np.nan_to_num(-h) < 200)).any())

def save(out, z, x, y, img):
    p = os.path.join(out, str(z), str(x)); os.makedirs(p, exist_ok=True)
    Image.fromarray(img).save(os.path.join(p, '%d.webp' % y), 'WEBP', lossless=True, quality=100, method=4)

def main():
    out = sys.argv[1]; workers = int(sys.argv[sys.argv.index('--workers') + 1]) if '--workers' in sys.argv else 6
    os.makedirs(out, exist_ok=True)
    donef = os.path.join(out, 'done.txt'); done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    shelff = os.path.join(out, 'shelf.txt'); shelf = set(open(shelff).read().split()) if os.path.exists(shelff) else set()
    dl, sl = open(donef, 'a'), open(shelff, 'a'); lock = threading.Lock(); st = {'n': 0, 'err': 0, 't0': time.time()}
    def work(z, bx, by, B):
        key = '%d/%d/%d/%d' % (z, bx, by, B)
        if key in done: return
        try: h = fetch(z, bx, by, B)
        except Exception as e:
            with lock: st['err'] += 1
            print('ERR', key, e, flush=True); return
        for i in range(B):
            for j in range(B):
                img, has, sh = encode(h[j * T:(j + 1) * T, i * T:(i + 1) * T])
                if not has: continue
                save(out, z, bx * B + i, by * B + j, img)
                with lock:
                    st['n'] += 1
                    if sh: k = '%d/%d/%d' % (z, bx * B + i, by * B + j); shelf.add(k); sl.write(k + '\n')
        with lock: done.add(key); dl.write(key + '\n'); dl.flush(); sl.flush()
    for box, maxz in REGIONS:
        x0, y1 = lonlat_tile(box[0], box[1], 8); x1, y0 = lonlat_tile(box[2], box[3], 8)
        need = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        for z in range(8, maxz + 1):
            B = 1 if z == 8 else 2 if z == 9 else 4
            blocks = sorted({(x // B, y // B) for x, y in need})
            with ThreadPoolExecutor(workers) as ex: list(ex.map(lambda b: work(z, b[0], b[1], B), blocks))
            print('%s z%d: %d tiles in %d blocks | made %d err %d | %.0f min' % (box, z, len(need), len(blocks), st['n'], st['err'], (time.time() - st['t0']) / 60), flush=True)
            if z == maxz: break
            need = [(2 * x + dx, 2 * y + dy) for x, y in need if '%d/%d/%d' % (z, x, y) in shelf for dx in (0, 1) for dy in (0, 1)]
    # z7..z5 from z8: 2x2 mean of the decoded depths (sea where the children have sea)
    for z in (7, 6, 5):
        src = os.path.join(out, str(z + 1)); kids = {}
        if not os.path.isdir(src): continue
        for xs in os.listdir(src):
            for f in os.listdir(os.path.join(src, xs)):
                if f.endswith('.webp'): kids.setdefault((int(xs) // 2, int(f[:-5]) // 2), []).append((int(xs), int(f[:-5])))
        for (px, py), ch in kids.items():
            big = np.full((2 * T, 2 * T), np.nan, np.float32); bl = np.zeros((2 * T, 2 * T), bool)
            for (cx, cy) in ch:
                a = np.asarray(Image.open(os.path.join(src, str(cx), '%d.webp' % cy)).convert('RGBA')).astype(np.float32)
                sea = (a[..., 3] > 127) & (a[..., 2] < 128)
                d = np.where(sea, (a[..., 0] * 256 + a[..., 1]) / 10, np.nan)
                sl = (slice((cy - 2 * py) * T, (cy - 2 * py + 1) * T), slice((cx - 2 * px) * T, (cx - 2 * px + 1) * T))
                big[sl] = d; bl[sl] = (a[..., 3] > 127) & (a[..., 2] >= 128)
            with np.errstate(invalid='ignore'):
                m = np.nanmean(big.reshape(T, 2, T, 2).swapaxes(1, 2).reshape(T, T, 4), 2)
            lm = bl.reshape(T, 2, T, 2).swapaxes(1, 2).reshape(T, T, 4).mean(2) > 0.5
            img, has, _ = encode(np.where(np.isfinite(m), -m, np.nan), land=lm & ~np.isfinite(m))
            if has: save(out, z, px, py, img)
        print('z%d from children: %d' % (z, len(kids)), flush=True)
    cov = set()
    for z in os.listdir(out):
        if not z.isdigit() or int(z) < 8: continue
        k = 2 ** (int(z) - 8)
        for xs in os.listdir(os.path.join(out, z)):
            for f in os.listdir(os.path.join(out, z, xs)):
                if f.endswith('.webp'): cov.add('%d/%d' % (int(xs) // k, int(f[:-5]) // k))
    json.dump(sorted(cov), open(os.path.join(out, 'cover.json'), 'w'), separators=(',', ':'))
    print('DONE tiles', st['n'], 'err', st['err'], 'cover', len(cov), flush=True)

if __name__ == '__main__': main()
