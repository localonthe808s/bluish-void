#!/usr/bin/env python3
"""THE POLES ON THE CLOUD GLOBE (2026-11-08, user: "can this help with the globe view of clouds?" -> "yes do both").

The globe's world picture (worldbake.py) is stitched from five geostationary satellites, and above about 60 degrees none of them
sees the ground, so both caps faded to the base map. This fills them, hourly, as two strips on the world picture's own grid
(4096 x 2048 latitude / longitude; the caps are its top and bottom 455 rows, poleward of 50.01 degrees):

  NORTH  NASA GIBS daily true color (VIIRS NOAA-20, MODIS Terra where it has a gap), yesterday's whole day. Dark in the polar night,
         so it fills only what the sun lit (the Arctic gets little from November to February).
  SOUTH  the same true color over the continent, its ice shelves and the sea ice, and over the open Southern Ocean the CURRENT clouds:
         the AMRDC Antarctic infrared composite (UW-Madison, hourly, geostationary and polar-orbiting satellites blended), turned into
         white cloud over a dark sea. Infrared alone cannot tell cloud from ice (the plateau and the pack are as cold as cloud tops),
         so it is used only where GHRSST MUR (NASA JPL, via GIBS) says the sea is open and Natural Earth says it is not land.
         The composite's public GIF carries a grid, coastlines and a caption: those pixels are painted over from their neighbors.
         Its projection is not published; fitted from its own grid (2026-11-08): south polar stereographic, centre (1431.0, 1431.0),
         r = 2975.3 px x tan((90 + lat) / 2), x = cx + r sin(lon + 140 deg), y = cy - r cos(lon + 140 deg) on the 2864 x 2876 'xlarge'
         image; the 70/60/50/40/30 S circles agree to 0.01 %, its coastline matches Natural Earth's at 140.0 deg.

Out (R2, goes/video/WORLD/): polar_n.png, polar_s.png (RGBA, 4096 x 455; alpha = where there is something to show) and polar.json.
Credits: NASA GIBS / NASA Worldview; GHRSST MUR (NASA JPL PO.DAAC); "AMRC, SSEC, UW-Madison" (their requested short credit).

    python3 _goesvid/polarbake.py [--dry]
"""
import datetime as dt, io, json, math, os, subprocess, sys, tempfile, time, urllib.request
import numpy as np
from PIL import Image

UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com polar bake)'}
HERE = os.path.dirname(os.path.abspath(__file__))
OW, OH, NR = 4096, 2048, 455
LAT0 = 90 - NR * 180 / OH                     # 50.0098: the strips' equatorward edge
GIBS = ('https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS={L}&CRS=EPSG:4326'
        '&BBOX={s},-180,{n},180&WIDTH=%d&HEIGHT=%d&FORMAT={f}&TRANSPARENT=TRUE&TIME={d}' % (OW, NR))
AMRDC = 'https://amrdc.ssec.wisc.edu/web_products/satellite_imagery/antcomposite-ir-xlarge.gif'
PROJ = {'cx': 1431.0138, 'cy': 1431.0162, 'K': 2975.2941, 'th': 140.0}
BUCKET = 'bluishvoid-bg'; KEY = 'goes/video/WORLD/'
DRY = '--dry' in sys.argv


def get(url, timeout=120):
    for a in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read(), r.headers.get('Last-Modified')
        except Exception as e:
            print('  retry', a, url[:90], e, flush=True); time.sleep(8 * (a + 1))
    return None, None


def img(b, mode='RGB'):
    return np.asarray(Image.open(io.BytesIO(b)).convert(mode))


def truecolor(south, day):
    """yesterday's VIIRS NOAA-20 true color for one strip, MODIS Terra in its gaps; RGBA with alpha where lit"""
    s, n = (-90, -LAT0) if south else (LAT0, 90)
    out = None
    for L in ('VIIRS_NOAA20_CorrectedReflectance_TrueColor', 'MODIS_Terra_CorrectedReflectance_TrueColor'):
        b, _ = get(GIBS.format(L=L, s=s, n=n, f='image/jpeg', d=day))
        if not b: continue
        a = img(b).astype(np.float32)
        if a.shape[:2] != (NR, OW): continue
        if out is None: out = a
        else:
            gap = out.sum(2) < 24
            out[gap] = a[gap]
    if out is None: return None
    lit = (out.sum(2) >= 24).astype(np.float32)
    import cv2
    lit = cv2.GaussianBlur(lit, (0, 0), 3)            # a soft edge where the polar night begins
    return np.dstack([out, lit * 255]).clip(0, 255).astype(np.uint8)


def amrdc_strip():
    """the AMRDC infrared composite, its overlays painted out, warped onto the south strip; brightness 0-255 (cold = bright)"""
    import cv2
    b, lm = get(AMRDC, 180)
    if not b: return None, None
    im = Image.open(io.BytesIO(b)); pal = im.getpalette(); idx = np.asarray(im)
    P = np.array(pal[:768], np.int16).reshape(-1, 3)
    gray = (np.abs(P[:, 0] - P[:, 1]) < 8) & (np.abs(P[:, 1] - P[:, 2]) < 8)
    v = P[idx, 0].astype(np.uint8); over = ~gray[idx]
    over[-40:, :] = True                              # the caption along the bottom
    over = cv2.dilate(over.astype(np.uint8), np.ones((3, 3), np.uint8))
    v = cv2.inpaint(v, over, 3, cv2.INPAINT_TELEA)
    h, w = v.shape
    lat = (90 - (OH - NR + np.arange(NR) + 0.5) * 180 / OH)[:, None]
    lon = (-180 + (np.arange(OW) + 0.5) * 360 / OW)[None, :]
    r = PROJ['K'] * np.tan(np.radians((90 + lat) / 2)); ang = np.radians(lon + PROJ['th'])
    mx = (PROJ['cx'] + r * np.sin(ang)).astype(np.float32); my = (PROJ['cy'] - r * np.cos(ang)).astype(np.float32)
    ok = (mx >= 0) & (my >= 0) & (mx <= w - 1) & (my <= h - 1)
    out = cv2.remap(v, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return np.where(ok, out, 0).astype(np.uint8), lm


def south(day):
    import cv2
    tc = truecolor(True, day)
    ir, irt = amrdc_strip()
    land = np.asarray(Image.open(os.path.join(HERE, 'polar_land_s.png'))) > 0
    b, _ = get(GIBS.format(L='GHRSST_L4_MUR_Sea_Ice_Concentration', s=-90, n=-LAT0, f='image/png', d=day))
    ice = img(b, 'RGBA')[..., 3] > 0 if b else np.zeros((NR, OW), bool)
    # the coast's fringe, where the 1:50m land and the 1-km ice field both miss a few km, would read as open sea: widened ~15 km
    hard = cv2.dilate((land | ice).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    solid = cv2.GaussianBlur(hard.astype(np.float32), (0, 0), 4)      # 1 = land, shelf or pack: true color; 0 = open sea
    if tc is None and ir is None: return None, None
    rgb = tc[..., :3].astype(np.float32) if tc is not None else np.zeros((NR, OW, 3), np.float32)
    if tc is not None:   # the daily mosaic's seams over the ice sheet (a dark line out from the pole): dark specks on land painted over
        dark = (land & (rgb.mean(2) < 150)).astype(np.uint8)
        if dark.any(): rgb = cv2.inpaint(rgb.clip(0, 255).astype(np.uint8), cv2.dilate(dark, np.ones((3, 3), np.uint8)), 5, cv2.INPAINT_TELEA).astype(np.float32)
    al = tc[..., 3].astype(np.float32) / 255 if tc is not None else np.zeros((NR, OW), np.float32)
    if ir is not None:
        c = np.clip((ir.astype(np.float32) - 105) / 95, 0, 1); c = c * c * (3 - 2 * c)      # cloud cover from cold tops
        sea = np.array([25, 47, 68], np.float32)   # the satellites' own open ocean at 52-56 S (measured 2026-11-08)
        cloud = np.dstack([ir.astype(np.float32) * 0.92 + 20] * 3).clip(0, 255)
        cur = sea * (1 - c[..., None]) + cloud * c[..., None]
        has = (ir > 0).astype(np.float32)
        wsea = (1 - solid) * has                         # open sea with an infrared reading: today's clouds
        rgb = rgb * (1 - wsea[..., None]) + cur * wsea[..., None]
        al = np.maximum(al * (1 - wsea), wsea)
    return np.dstack([rgb, al * 255]).clip(0, 255).astype(np.uint8), irt


def put(path, key, ctype, cache):
    if DRY: return
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', path, 's3://%s/%s' % (BUCKET, key), '--content-type', ctype, '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', path, 'r2:%s/%s' % (BUCKET, key), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: ' + ctype, '--header-upload', 'Cache-Control: ' + cache], check=True)


def main():
    day = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).date().isoformat()
    tmp = tempfile.mkdtemp(); meta = {'at': int(time.time()), 'day': day}
    n = truecolor(False, day)
    s, irt = south(day)
    for k, a in (('n', n), ('s', s)):
        if a is None: print(k, 'none'); continue
        p = os.path.join(tmp, 'polar_%s.png' % k); Image.fromarray(a).save(p, optimize=True)
        meta[k] = {'cover': round(float((a[..., 3] > 32).mean()), 3), 'kb': os.path.getsize(p) // 1024}
        put(p, KEY + 'polar_%s.png' % k, 'image/png', 'public, max-age=600')
        print(k, meta[k], flush=True)
    meta['amrdc'] = irt
    jp = os.path.join(tmp, 'polar.json'); json.dump(meta, open(jp, 'w'))
    put(jp, KEY + 'polar.json', 'application/json', 'public, max-age=300')
    print('polar', meta, 'in', tmp if DRY else '')


if __name__ == '__main__':
    main()
