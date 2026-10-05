#!/usr/bin/env python3
"""Bake the SOLAR IMAGER's helioseismology band (2026-10-05, user: "add the 360 strip right below these ... and then above
the two suns - add 1 2 3 4 5").

Everything here is SDO/HMI helioseismology from Stanford's JSOC (public NASA data -- credit NASA/SDO, the HMI science
team and Stanford JSOC), turned into clean pictures and a small data file for the page:

  strip.png     THE WHOLE SUN, 360 deg: the newest HMI composite map (Composite_Maps_JPEG, every 12 h) -- the far side
                from helioseismic holography, the near side from the magnetograph -- cropped to the map itself (no axes,
                no colour bars) and with the plot's purple grid painted out (the site uses no purple).
  farside.png   THE FAR SIDE BY TRAVEL TIME: HMI's time-distance far-side disc (current_twohemi_NRT.jpg, the left disc),
                cropped and masked round. A second, independent detector beside the GONG FAR-SIDE tab.
  flows.json    UNDER THE SURFACE: the newest Carrington rotation's synoptic subsurface flows (time-distance, binned
                120 x 40, 3 deg cells, 60S-60N), the shallowest of its six depth layers, in m/s relative to the Sun's
                mean rotation. The page draws it as moving streaks.
  meta.json     what each one is, its time, and its source.

Usage: python3 helio_bake.py <out_dir>        (needs numpy, pillow, astropy)"""
import io, json, os, re, sys, time, urllib.request
import numpy as np
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else 'helio_out'
os.makedirs(OUT, exist_ok=True)
J = 'http://jsoc.stanford.edu'
UA = {'User-Agent': 'bluishvoid.com helioseismology bake (+https://bluishvoid.com)'}

def get(url, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read(), r.headers.get('Last-Modified')
        except Exception as e:
            if k == tries - 1: raise
            time.sleep(5)

def newest(listing_url, pattern):
    html = get(listing_url + '?C=M;O=D')[0].decode('utf8', 'ignore')
    names = re.findall(r'href="(?:\./)?(' + pattern + ')"', html)
    if not names: raise SystemExit('nothing matching %s at %s' % (pattern, listing_url))
    return names[0]

meta = {'baked': int(time.time() * 1000), 'credit': 'NASA/SDO, the HMI science team and Stanford JSOC'}

# ---- 1. THE WHOLE SUN -------------------------------------------------------------------------------------------
name = newest(J + '/data/farside/Composite_Maps_JPEG/', r'COMPOSITE_MAP_[0-9._:]+\.png')
raw, lm = get(J + '/data/farside/Composite_Maps_JPEG/' + name)
im = np.asarray(Image.open(io.BytesIO(raw)).convert('RGB')).astype(int)
H, W, _ = im.shape
# the map is the big block of non-white between the colour bars: rows/cols where most pixels are not white
nonwhite = (im.sum(axis=2) < 700)
cols = np.where(nonwhite[int(H * .3):int(H * .7)].mean(axis=0) > .9)[0]
rows = np.where(nonwhite[:, int(W * .3):int(W * .7)].mean(axis=1) > .9)[0]
# the longest contiguous runs (the colour bars are separate, narrower runs)
def run(ix):
    best, cur = (0, 0), [ix[0], ix[0]]
    for a, b in zip(ix[:-1], ix[1:]):
        if b == a + 1: cur[1] = b
        else:
            if cur[1] - cur[0] > best[1] - best[0]: best = tuple(cur)
            cur = [b, b]
    if cur[1] - cur[0] > best[1] - best[0]: best = tuple(cur)
    return best
x0, x1 = run(cols); y0, y1 = run(rows)
m = im[y0 + 2:y1 - 1, x0 + 2:x1 - 1].copy()                             # inside the plot's black frame
# PAINT THE GRID OUT. The plot draws purple lines every 60 deg of longitude and 30 deg of latitude; blended over the gold
# and the blue-grey they are muted, so a colour test misses them. Found instead by their tint along a whole column/row:
# purple lifts blue over green everywhere along the line. Each such column/row is filled from its clean neighbours.
def tint(a, axis): return (a[:, :, 2] - a[:, :, 1]).mean(axis=axis)
for axis in (0, 1):                                                    # 0: columns (longitude lines), 1: rows (latitude)
    t = tint(m, axis)
    # against its own neighbourhood (the map is gold on the left and blue-grey on the right, so no global baseline)
    nb = (np.roll(t, 4) + np.roll(t, -4)) / 2; sc = t - nb; spread = np.median(np.abs(sc - np.median(sc))) + 1e-6
    bad = np.where(sc / spread > 8)[0]
    bad = np.unique(np.concatenate([bad, bad - 1, bad + 1]))          # the line's anti-aliased edges too
    bad = bad[(bad > 0) & (bad < len(t) - 1)]
    n = m.shape[1] if axis == 0 else m.shape[0]
    good = np.setdiff1d(np.arange(n), bad)
    for b in bad:
        lo = good[good < b]; hi = good[good > b]
        if not len(lo) or not len(hi): continue
        l, h = lo[-1], hi[0]; src = l if (b - l) <= (h - b) else h      # the NEAREST clean line, copied: averaging two
        if axis == 0: m[:, b] = m[:, src]                               # flattened the magnetogram's speckle into pale bands
        else: m[b, :] = m[src, :]
    print('  grid', 'columns' if axis == 0 else 'rows', len(bad), 'painted out')
strip = Image.fromarray(m.clip(0, 255).astype(np.uint8)).resize((1440, 720), Image.LANCZOS)
strip.save(os.path.join(OUT, 'strip.png'), optimize=True)
d = re.search(r'(\d{4})\.(\d\d)\.(\d\d)_(\d\d):(\d\d)', name)
meta['strip'] = {'file': 'strip.png', 'time': '%s-%s-%sT%s:%s:00Z' % d.groups(), 'source': J + '/data/farside/',
                 'crop': [int(x0), int(y0), int(x1), int(y1)], 'from': name,
                 'what': 'Far side from HMI helioseismic holography (travel-time shift); near side from the HMI magnetogram.'}
print('strip', name, 'map box', x0, y0, x1, y1)

# ---- 2. THE FAR SIDE BY TRAVEL TIME ----------------------------------------------------------------------------
raw, lm2 = get(J + '/data/timed/current_img/current_twohemi_NRT.jpg')
im2 = Image.open(io.BytesIO(raw)).convert('RGB'); a2 = np.asarray(im2).astype(int); H2, W2, _ = a2.shape
left = a2[:, :W2 // 2]
nw = left.sum(axis=2) < 690
r_ = np.where(nw[:, int(W2 * .1):int(W2 * .4)].mean(axis=1) > .5)[0]; c_ = np.where(nw[int(H2 * .3):int(H2 * .7)].mean(axis=0) > .5)[0]
ry0, ry1 = run(r_); cx0, cx1 = run(c_)
side = min(ry1 - ry0, cx1 - cx0); cy, cx = (ry0 + ry1) // 2, (cx0 + cx1) // 2
disc = im2.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2)).resize((600, 600), Image.LANCZOS).convert('RGBA')
yy, xx = np.mgrid[0:600, 0:600]; rr = np.hypot(xx - 299.5, yy - 299.5)
alpha = np.clip((290 - rr) * 60, 0, 255).astype(np.uint8)            # just inside the plot's black rim, a 4 px edge
disc.putalpha(Image.fromarray(alpha))
disc.save(os.path.join(OUT, 'farside.png'), optimize=True)
title_time = None
meta['farside'] = {'file': 'farside.png', 'modified': lm2, 'source': J + '/data/timed/',
                   'what': 'HMI time-distance far-side imaging: travel-time shift; dark patches are active regions on the far side.'}
print('farside disc', cx, cy, side, lm2)

# ---- 3. UNDER THE SURFACE ----------------------------------------------------------------------------------------
from astropy.io import fits
FL = J + '/data/timed/td_synop_flow/synoptic_flow_data/low_res_data/'
vxn = newest(FL, r'synop_CR\d+_vx_binned\.fits'); cr = int(re.search(r'CR(\d+)', vxn).group(1))
vx = fits.open(io.BytesIO(get(FL + vxn)[0]))[0].data.astype(float)
vy = fits.open(io.BytesIO(get(FL + vxn.replace('_vx_', '_vy_'))[0]))[0].data.astype(float)
L = 0                                                                  # the shallowest of the six layers
gx, gy = np.nan_to_num(vx[L]), np.nan_to_num(vy[L])
# Carrington rotation start (JD), the standard formula, to give the map its dates
jd0 = 2398140.2270 + 27.2752316 * cr
t0 = (jd0 - 2440587.5) * 86400e3
meta['flows'] = {'file': 'flows.json', 'cr': cr, 'start': int(t0), 'end': int(t0 + 27.2752316 * 864e5), 'layer': L, 'layers': int(vx.shape[0]),
                 'grid': [int(gx.shape[1]), int(gx.shape[0])], 'lat': [-60, 60], 'units': 'm/s relative to the mean rotation',
                 'source': J + '/data/timed/', 'what': 'HMI time-distance synoptic subsurface flows, binned 120 x 40, shallowest layer.'}
with open(os.path.join(OUT, 'flows.json'), 'w') as f:
    json.dump({'cr': cr, 'w': int(gx.shape[1]), 'h': int(gx.shape[0]), 'lat': [-60, 60],
               'vx': [round(v, 1) for v in gx.ravel().tolist()], 'vy': [round(v, 1) for v in gy.ravel().tolist()]}, f, separators=(',', ':'))
print('flows CR', cr, 'speeds p99 %.1f m/s' % np.percentile(np.hypot(gx, gy), 99))

with open(os.path.join(OUT, 'meta.json'), 'w') as f: json.dump(meta, f, indent=1)
for n in ['strip.png', 'farside.png', 'flows.json', 'meta.json']:
    print(n, os.path.getsize(os.path.join(OUT, n)), 'bytes')
