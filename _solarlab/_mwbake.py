"""THE MILKY WAY IN 3D (2026-11-22; user: "the galaxy milky way view looks cheap still" / "the milk way looks 2D").

Inputs are ESA's January 2025 Gaia-based impressions (ESA/Gaia/DPAC, Stefan Payne-Wardenaar, CC BY-SA 3.0 IGO), 40 kpc across,
Galactic Centre at the image centre, the Sun below it (screen up = towards the centre from the Sun, screen left = l 90):
  https://www.cosmos.esa.int/web/gaia/milky-way  ->  MilkyWay_25J14_40KPC_Top_D53_5K_HighContrast.jpg, ..._Edge_5K_HighContrast.jpg

Outputs:
  mw_gaia_top_v2.webp   face-on, 3072 px (resized)                    -> r2:bluishvoid-bg/galaxy/
  mw_gaia_edge_v2.webp  edge-on band, 4096 x 1638 (cropped, resized)  -> r2:bluishvoid-bg/galaxy/
  galaxy/mw_stars.bin   a star cloud sampled from the face-on render (probability ~ brightness), each star given a height:
                        thin disc (scale height 0.25 kpc, flaring past the Sun), a thicker bar/bulge, and the outer warp
                        (z += .09 (R - 9.5)^1.2 * Y/R past 9.5 kpc, the same model the lab draws). Heights are a MODEL;
                        positions and colours come from the render.
  Layout (little-endian): uint16 N, uint8 P, P*3 palette bytes, then N * (int16 X*100, int16 Y*100, int16 z*1000, uint8 colour).

Run: python3 _mwbake.py <dir with the two HighContrast jpgs> <out dir for the webps>
"""
import os, sys, struct
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
SRC, OUT = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
N, SPAN, S = 22000, 40.0, 640                    # stars, kpc across, sampling grid

top = Image.open(os.path.join(SRC, 'MilkyWay_25J14_40KPC_Top_D53_5K_HighContrast.jpg')).convert('RGB')
top.resize((3072, 3072), Image.LANCZOS).save(os.path.join(OUT, 'mw_gaia_top_v2.webp'), quality=82, method=6)
edge = Image.open(os.path.join(SRC, 'MilkyWay_25J14_40KPC_Edge_5K_HighContrast.jpg')).convert('RGB')
edge.crop((0, 1500, 5000, 3500)).resize((4096, 1638), Image.LANCZOS).save(os.path.join(OUT, 'mw_gaia_edge_v2.webp'), quality=84, method=6)

a = np.asarray(top.resize((S, S), Image.LANCZOS)).astype(np.float32)
lum = a @ np.array([.3, .55, .15], np.float32)
yy, xx = np.mgrid[0:S, 0:S]
kpc = SPAN / S
X = -(yy + .5 - S / 2) * kpc; Y = -(xx + .5 - S / 2) * kpc; R = np.hypot(X, Y)
from PIL import ImageFilter
# weighted by LOCAL CONTRAST (brighter than the ~1.2 kpc around it = an arm), not by brightness: brightness alone follows the
# bulge's fall-off and the cloud became a white blob with no arms (2026-11-22)
L8 = Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8))
lum = np.asarray(L8.filter(ImageFilter.MedianFilter(5))).astype(np.float32)   # the render's bright foreground star points out first: one took 9,000 stars and smeared into a streak
blur = np.asarray(Image.fromarray(lum.astype(np.uint8)).filter(ImageFilter.GaussianBlur(19))).astype(np.float32)
con = np.clip(np.minimum(lum / np.maximum(blur, 4), 1.6) - .92, 0, None)
w = con ** 3 * np.clip(lum - 14, 0, None) ** .7 * (R < 19.5) * (R > 1.4) * (np.hypot(X - 17.6, Y - 2.6) > 1.8)   # the bar's own glow is drawn by the lab; so is the Sgr dwarf
w = w.ravel() / w.sum()
rng = np.random.default_rng(20261122)
pick = rng.choice(S * S, size=N, p=w)
px, py = pick % S, pick // S
jx, jy = rng.random(N), rng.random(N)
sx = -((py + jy) - S / 2) * kpc; sy = -((px + jx) - S / 2) * kpc; sr = np.hypot(sx, sy)
h = np.where(sr < 3.2, .22 + .45 * (1 - sr / 3.2), .2 + .02 * np.clip(sr - 8, 0, None))
z = h * np.sign(rng.random(N) - .5) * -np.log(1 - rng.random(N) * .995)
z += np.where(sr > 9.5, .09 * np.clip(sr - 9.5, 0, None) ** 1.2 * sy / np.maximum(sr, 1e-3), 0)
col = a[py, px]
col = np.clip(col * (205 / np.maximum(col.max(1, keepdims=True), 1)) * (.75 + .25 * rng.random((N, 1))), 0, 255).astype(np.uint8)   # each a point of light: its hue from the render, its brightness lifted (the render's dim arms made dim stars)
q = Image.fromarray(col.reshape(-1, 1, 3)).quantize(colors=48, method=Image.Quantize.MEDIANCUT)
pal = np.array(q.getpalette()[:48 * 3], np.uint8); idx = np.asarray(q).ravel().astype(np.uint8)
order = np.argsort(idx, kind='stable')                 # grouped by colour: one fill per colour in the lab
buf = struct.pack('<HB', N, 48) + pal.tobytes()
rec = np.zeros(N, dtype=[('x', '<i2'), ('y', '<i2'), ('z', '<i2'), ('c', 'u1')])
rec['x'] = np.round(sx[order] * 100); rec['y'] = np.round(sy[order] * 100); rec['z'] = np.round(np.clip(z[order], -30, 30) * 1000); rec['c'] = idx[order]
open(os.path.join(HERE, 'galaxy', 'mw_stars.bin'), 'wb').write(buf + rec.tobytes())
print('stars', N, 'bytes', len(buf) + rec.nbytes, '| z p5/p50/p95', np.percentile(np.abs(z), [5, 50, 95]).round(3))
