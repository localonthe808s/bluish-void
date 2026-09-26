"""THE COAST seafloor v4 (2026-09-25, user: "this is really cool, i like the coloring here better" -- the incision map
drawn to trace the Hudson Canyon). The look of that map made the view's seafloor: a smooth slate-blue depth gradient
with every canyon and channel glowing gold by how deeply it is cut below its ~8 km surroundings. The cut is scaled by
depth (40 m + 10% of the depth), so the 20 m Hudson Shelf Valley glows as the 300 m slope canyons do. A little of v3's
relief stays underneath for texture. Elevation = v3's merged, anti-aliased, destriped 2x grid (coast3_Z2x.npy)."""
import numpy as np, math, os, sys
from PIL import Image
from scipy.ndimage import gaussian_filter, uniform_filter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lut2 import load, sample, feats, bins
BOX = (-8682920, 4028802, -7235766, 5311971); W, H = 2264, 2007; SS = 2
X0, Y0, X1, Y1 = BOX
Zs = np.load('coast3_Z2x.npy').astype(np.float32)
mpp = (X1 - X0) / (W * SS) * math.cos(math.radians(38.5))
D = np.clip(-Zs, 0, 6000)
Zsm = gaussian_filter(np.minimum(Zs, 0), (1.5, 1.0))
inc = Zsm - uniform_filter(Zsm, int(8000 / mpp))                    # negative where the floor is cut below its surroundings
v = np.clip(-inc / (40 + 0.10 * D), 0, 1) ** 0.85
# FINER SCALE TOO (v4b, user: "is there no more detail to show in the ocean?"): the same cut measured against ~2.5 km,
# so gullies, tributaries and the smaller channels glow as well -- dimmer, and only where the 8 km cut is not already lit
Zf = gaussian_filter(np.minimum(Zs, 0), (1.2, 0.8))
incf = Zf - uniform_filter(Zf, int(2500 / mpp))
vf = np.clip(-incf / (18 + 0.05 * D), 0, 1) ** 0.9 * 0.6
v = np.maximum(v, vf)
# and the RAISED ground faintly (seamounts, slide blocks, levees): a cool highlight, never gold -- gold means a cut
up = np.clip(inc / (60 + 0.10 * D), 0, 1) * 0.35
# the incision map's slate ramp: light over the shelf, darkening to the abyss
d = np.clip(D / 5000.0, 0, 1)
base = np.stack([20 + 40 * (1 - d), 30 + 60 * (1 - d), 60 + 80 * (1 - d)], -1)
# a little relief underneath, for texture (v3's lighting, a third of its strength)
gy, gx = np.gradient(gaussian_filter(Zs, (1.5, 0.7)), mpp)
ex = 6.0 + 10.0 * np.clip(D / 3000.0, 0, 1); gx *= ex; gy *= ex
slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
hs = np.sin(math.radians(40)) * np.cos(slope) + np.cos(math.radians(40)) * np.sin(slope) * np.cos(math.radians(315) - aspect)
rel = np.clip(hs - math.sin(math.radians(40)), -0.6, 0.6)
base = base * (1 + 0.55 * rel[..., None])     # v4b: more of the relief texture back (0.35 -> 0.55)
base = base + up[..., None] * np.array([40, 60, 80])
# the gold: the incision map's own blend (red and green lifted toward amber, blue left as the sea's)
col = base.copy()
col[..., 0] = np.maximum(base[..., 0], v * 255); col[..., 1] = np.maximum(base[..., 1], v * 200)
sea = Zs < 0
col1 = col.reshape(H, SS, W, SS, 3).mean(axis=(1, 3)); seafrac = sea.reshape(H, SS, W, SS).mean(axis=(1, 3))
MED = load('gmrt_med.nc')
Z1, mpp1 = sample(MED, BOX, W, H); hs1, rel1 = feats(Z1, mpp1); hb, rb, eb, db, orb = bins(Z1, hs1, rel1)
L = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lut_land.npy')); land_rgba = L[hb, rb, eb]
out = np.zeros((H, W, 4))
out[..., :3] = land_rgba[..., :3] * (1 - seafrac[..., None]) + col1 * seafrac[..., None]
out[..., 3] = land_rgba[..., 3] * (1 - seafrac) + 252 * seafrac
Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save('coast4_rgba.png')
Image.open('coast4_rgba.png').save('/Users/vvvaa/bluish-void/city_bathy_coast.webp', 'WEBP', quality=92, method=6)
print('wrote', os.path.getsize('/Users/vvvaa/bluish-void/city_bathy_coast.webp') // 1024, 'KB')
