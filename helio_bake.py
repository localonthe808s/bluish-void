#!/usr/bin/env python3
"""Bake the SOLAR IMAGER's helioseismology band (2026-10-05, user: "add the 360 strip right below these ... and then above
the two suns - add 1 2 3 4 5").

Everything here is SDO/HMI helioseismology from Stanford's JSOC (public NASA data -- credit NASA/SDO, the HMI science
team and Stanford JSOC), turned into clean pictures and a small data file for the page:

  strip.jpg     THE WHOLE SUN, 360 deg, BUILT FROM THE DATA (2026-10-05, user of the first version, an upscaled crop of
                Stanford's 560 px composite plot: "is this the best it can look?"). Far side: the newest HMI far-side
                PHASE MAP (data/farside/Phase_Maps, 1 deg, helioseismic holography -- inherently that coarse), smoothly
                interpolated and feathered at its edge. Near side: the HMI line-of-sight magnetic synoptic map at full
                resolution (data/hmi/synoptic hmi.Synoptic_Mr_nrt.<CR>, 0.1 deg, sine-latitude), its unfilled longitudes
                taken from the previous rotation. No plot, so no grid to paint out; the site's own colours.
  farside.png   THE FAR SIDE BY TRAVEL TIME: HMI's time-distance far-side disc (current_twohemi_NRT.jpg, the left disc),
                cropped and masked round. A second, independent detector beside the GONG FAR-SIDE tab.
  flows.json    UNDER THE SURFACE: the newest Carrington rotation's synoptic subsurface flows (time-distance, binned
                120 x 40, 3 deg cells, 60S-60N), the shallowest of its six depth layers, in m/s relative to the Sun's
                mean rotation. The page draws it as moving streaks.
  meta.json     what each one is, its time, and its source.

Usage: python3 helio_bake.py <out_dir>        (needs numpy, pillow, astropy, scipy)"""
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

def run(ix):
    """the longest contiguous run of indices (a plot's box, a disc's extent)"""
    best, cur = (0, 0), [ix[0], ix[0]]
    for a, b in zip(ix[:-1], ix[1:]):
        if b == a + 1: cur[1] = b
        else:
            if cur[1] - cur[0] > best[1] - best[0]: best = tuple(cur)
            cur = [b, b]
    if cur[1] - cur[0] > best[1] - best[0]: best = tuple(cur)
    return best

meta = {'baked': int(time.time() * 1000), 'credit': 'NASA/SDO, the HMI science team and Stanford JSOC'}

# ---- 1. THE WHOLE SUN, from the data ---------------------------------------------------------------------------
import warnings; warnings.filterwarnings('ignore')
from astropy.io import fits
from scipy.ndimage import map_coordinates, gaussian_filter
SYN = 'https://jsoc1.stanford.edu/data/hmi/synoptic/'
pname = newest(J + '/data/farside/Phase_Maps/', r'PHASE_MAP_[0-9._:]+\.fits')
ph = fits.open(io.BytesIO(get(J + '/data/farside/Phase_Maps/' + pname)[0]))[0].data.astype(float)      # 181 x 361: lat -90..90, Carrington lon 0..360
syn_html = get(SYN)[0].decode('utf8', 'ignore')
crs = sorted(set(int(c) for c in re.findall(r'hmi\.Synoptic_Mr_nrt\.(\d+)\.fits', syn_html)))
cr = crs[-1]
def syn(name):
    try:
        h = fits.open(io.BytesIO(get(SYN + name)[0])); hd = [x for x in h if x.data is not None][0]
        return hd.data.astype(float), hd.header
    except Exception as e:
        print('  synoptic', name, 'failed', e); return None, None
B, hb = syn('hmi.Synoptic_Mr_nrt.%d.fits' % cr)
Bp, _ = syn('hmi.Synoptic_Mr.%d.fits' % (cr - 1))
if Bp is None: Bp, _ = syn('hmi.Synoptic_Mr_nrt.%d.fits' % (cr - 1))
if Bp is not None and B is not None:
    hole = np.isnan(B); B[hole] = Bp[hole]                             # this rotation's map is still filling in
NY, NX = B.shape                                                       # 1440 x 3600: sine-latitude rows, lon 0..360 left to right
OW, OH = 2048, 1024
lon = (np.arange(OW) + 0.5) / OW * 360.0
lat = 90.0 - (np.arange(OH) + 0.5) / OH * 180.0
LON, LAT = np.meshgrid(lon, lat)
# near side: sine-latitude rows (row 0 = south), Carrington longitude across
ry = (np.sin(np.radians(LAT)) + 1) / 2 * NY - 0.5; rx = LON / 360.0 * NX - 0.5
Bn = np.nan_to_num(B, nan=0.0)
near = map_coordinates(Bn, [ry, rx], order=1, mode='nearest')
# far side: the phase map on a 1 deg grid (row 0 = 90S), smooth cubic, its validity feathered over ~3 deg
pv = np.isfinite(ph).astype(float); pz = np.nan_to_num(ph, nan=0.0)
fy = LAT + 90.0; fx = LON
far = map_coordinates(gaussian_filter(pz, 0.6), [fy, fx], order=3, mode='wrap')
wv = map_coordinates(gaussian_filter(pv, 1.8), [fy, fx], order=1, mode='wrap')
wf = np.clip((wv - 0.2) / 0.6, 0, 1)                                   # the far side's share, soft at its edge
far = np.where(wv > 0.05, far / np.maximum(gaussian_filter(pv, 0.6)[np.clip(fy.astype(int), 0, 180), np.clip(fx.astype(int), 0, 360)], 0.3), 0)
# colours: near side -- a cool grey with field +white / -black, saturating at +-120 G; far side -- gold, active regions
# (strongly negative phase) going dark brown, quiet sun a little lighter
t = np.clip(near / 300.0, -1, 1)                                     # 300 G: sunspot groups saturate, the quiet network stays faint
grey = np.array([128, 140, 160], float)
nearc = np.where(t[..., None] >= 0, grey + (np.array([250, 252, 255]) - grey) * (t[..., None] ** 1.15),
                 grey + (np.array([12, 14, 22]) - grey) * ((-t[..., None]) ** 1.15))
# above ~65 deg the line-of-sight field is foreshortened and the sine-latitude rows stretch it into streaks: fade to grey
pole = np.clip((np.abs(LAT) - 62) / 12, 0, 1)[..., None]; nearc = nearc * (1 - pole) + grey * pole
fv = far[wf > 0.5]; med = np.median(fv) if fv.size else 0; sd = (np.percentile(fv, 84) - np.percentile(fv, 16)) / 2 if fv.size else 1
z = (far - med) / (sd or 1)
gold = np.array([200, 165, 70], float)
# only a STRONG negative phase is an active region: below -1.6 sd it darkens to brown, the rest is a gentle gold texture
dk = np.clip((-z - 1.3) / 2.8, 0, 1) ** 1.6                          # a gradual ramp: no hard edge at a threshold, weak patches stay faint
farc = gold + (np.array([232, 205, 125]) - gold) * (np.clip(z, -1.3, 3.0) / 3.0 * 0.6)[..., None]
farc = farc + (np.array([46, 30, 8]) - farc) * dk[..., None]
img = farc * wf[..., None] + nearc * (1 - wf[..., None])
# where neither has data (the near side's poles), a quiet dark
nodata = (wf < 0.02) & np.isnan(map_coordinates(np.where(np.isnan(B), np.nan, 0.0), [ry, rx], order=0, mode='nearest'))
img[nodata] = grey                                                    # (blends into the faded poles)
Image.fromarray(img.clip(0, 255).astype(np.uint8)).save(os.path.join(OUT, 'strip.jpg'), quality=88, optimize=True, progressive=True)
d = re.search(r'(\d{4})\.(\d\d)\.(\d\d)_(\d\d):(\d\d)', pname)
meta['strip'] = {'file': 'strip.jpg', 'time': '%s-%s-%sT%s:%s:00Z' % d.groups(), 'source': J + '/data/farside/', 'cr': cr,
                 'near_source': SYN, 'from': [pname, 'hmi.Synoptic_Mr_nrt.%d.fits' % cr],
                 'what': 'Far side: HMI helioseismic holography phase map. Near side: HMI line-of-sight magnetic synoptic map.'}
print('strip', pname, 'near CR', cr, 'far coverage %.0f%%' % (100 * (wf > 0.5).mean()))

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

# ---- 4. GONG'S FAR-SIDE MAP: is today's a map at all, and which is the last real one? -----------------------------
# (2026-10-10, user screenshot: the imager's FAR-SIDE tab showed NSO's "INSUFFICIENT DATA TO PRODUCE FARSIDE MAPS"
# placeholder; then "can you hold on to the last one until theres a new one?") GONG needs a good day of data for a map;
# when it is short, NSO publishes that red-on-black picture under the normal filename, and it may regenerate the file
# into a real map within 48 h. The candidate files (every 12 h, newest first) are fetched and measured: the placeholder
# is ~2-3% pure red, a real map has none. meta.gong records the newest file (ok true/false) and lastGood, the newest
# REAL map; the page shows lastGood while the newest is the placeholder, and HMI's far side (farside.png above) only
# when no real map is found at all.
try:
    G = 'https://farside.nso.edu/oQR/f6r/'
    # farside.nso.edu answers home connections in a quarter of a second and drops every datacenter: GitHub's runners,
    # Cloudflare's network (the proxy worker gets 522), allorigins, codetabs (all tried 2026-10-10). The one vantage that
    # works is wsrv.nl (images.weserv.nl), an open image proxy NSO does not block: it fetches the file live (404s on an
    # unpublished map), re-encodes it (the red share survives) and caches it for a year keyed on the full source URL --
    # so files young enough to be regenerated carry a per-run query, which NSO ignores. Direct fetch stays as the
    # fallback for a local run.
    import urllib.parse, urllib.error
    def getg(u, bust=''):
        w = 'https://wsrv.nl/?url=' + urllib.parse.quote(u + bust, safe='') + '&output=jpg'
        try: return get(w, tries=1)
        except urllib.error.HTTPError as e:
            if e.code == 404: raise                                    # not published (yet)
        try: return get(w, tries=1)
        except Exception: return get(u, tries=1)
    def gong_cands(days=12):
        out = []
        for back in range(days):
            t = time.gmtime(time.time() - back * 86400); ym = time.strftime('%Y%m', t); d = time.strftime('%y%m%d', t)
            for hhmm in ('1200', '0000'): out.append((G + ym + '/mrf6r' + d + '/mrf6r' + d + 't' + hhmm + '.jpg', back))
        return out
    def gong_time(u):
        gm = re.search(r'mrf6r(\d\d)(\d\d)(\d\d)t(\d\d)(\d\d)', u); return '20%s-%s-%sT%s:%s:00Z' % gm.groups()
    def gong_red(body):
        ga = np.asarray(Image.open(io.BytesIO(body)).convert('RGB')).astype(int)
        return float(((ga[..., 0] > 150) & (ga[..., 1] < 90) & (ga[..., 2] < 90)).mean())
    newest = None; good = None; run_bust = '?r=' + time.strftime('%Y%m%d%H', time.gmtime())
    for u, back in gong_cands():
        try: body = getg(u, run_bust if back <= 2 else '')[0]       # young files may still turn into a real map
        except urllib.error.HTTPError as e:
            if e.code == 404: continue
            raise
        red = gong_red(body); ok = red < 0.005
        print('gong', u.rsplit('/', 1)[-1], 'red share %.4f' % red, 'ok' if ok else 'PLACEHOLDER')
        if newest is None: newest = (u, red, ok)
        if ok: good = u; break
    if newest is None: raise RuntimeError('no GONG file published in %d days' % 12)
    meta['gong'] = {'newest': newest[0], 'time': gong_time(newest[0]), 'ok': newest[2], 'red': round(newest[1], 4),
                    'lastGood': good, 'lastGoodTime': gong_time(good) if good else None,
                    'what': 'NSO GONG far-side map; ok=false means NSO published its INSUFFICIENT DATA placeholder; lastGood is the newest real map (checked via wsrv.nl)'}
except Exception as e:
    print('gong check failed', e)

with open(os.path.join(OUT, 'meta.json'), 'w') as f: json.dump(meta, f, indent=1)
for n in ['strip.jpg', 'farside.png', 'flows.json', 'meta.json']:
    print(n, os.path.getsize(os.path.join(OUT, n)), 'bytes')
