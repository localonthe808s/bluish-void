"""THE COAST seafloor v3 (2026-09-25, user: "are you able to add more detail? it feels shaded out and lacking bathymetry
texture ... is that all of the hudson canyon down to its furthest extent?"). v2 had the 46 m grid only over 38.8-40.6N,
so the canyon's lower course and the slope either side were 750 m; and its deep ramp ran nearly to black, flattening
the abyss. v3: GMRT max tiles over the whole slope band (canyon, south, west, east; feathered 0.15 deg), a lifted
deep ramp, relief exaggeration that grows with depth (6x on the shelf to 16x in the abyss, where the floor is
gentlest), and a fine-texture term (the floor less its 2 km mean) so abyssal hills, sediment waves and channels read."""
import numpy as np, math, os, sys
from PIL import Image
from scipy.ndimage import gaussian_filter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lut2 import load, sample, feats, bins
R = 6378137.0
BOX = (-8682920, 4028802, -7235766, 5311971); W, H = 2264, 2007; SS = 2
X0, Y0, X1, Y1 = BOX
MED = load('gmrt_med.nc')
Zs = sample(MED, BOX, W * SS, H * SS)[0]
lon = (X0 + (np.arange(W * SS) + 0.5) / (W * SS) * (X1 - X0)) / R * 180 / math.pi
ys = Y1 - (np.arange(H * SS) + 0.5) / (H * SS) * (Y1 - Y0); lat = (2 * np.arctan(np.exp(ys / R)) - math.pi / 2) * 180 / math.pi
for f in ('t_canyon.nc', 't_south.nc', 't_west.nc', 't_east.nc'):
    if not os.path.exists(f) or os.path.getsize(f) < 1e6: print('skip', f); continue
    T = load(f); tw, tn = T[1], T[2]; te = tw + T[3] * T[0].shape[1]; ts = tn - T[4] * T[0].shape[0]
    # ANTI-ALIAS: the 46 m grid point-sampled every ~320 m left a row pattern the texture term turned into stripes; smooth
    # each tile to the output's footprint first (sigma ~ 0.45 of the target pixel, in source cells) so a pixel is an average
    tgt_m = (X1 - X0) / (W * SS) * math.cos(math.radians(38.5)); cell_m = T[3] * 111320 * math.cos(math.radians(T[2] - T[4] * T[0].shape[0] / 2))
    zt = np.where(np.isfinite(T[0]), T[0], 0).astype(np.float32)
    T = (gaussian_filter(zt, 0.45 * tgt_m / cell_m),) + tuple(T[1:])
    fx = np.clip(np.minimum(lon - tw, te - lon) / 0.15, 0, 1); fy = np.clip(np.minimum(lat - ts, tn - lat) / 0.15, 0, 1)
    wgt = fy[:, None] * fx[None, :]
    jj = np.where(wgt.any(axis=1))[0]; ii = np.where(wgt.any(axis=0))[0]
    if not len(jj) or not len(ii): continue
    sub = (X0 + ii[0] / (W * SS) * (X1 - X0), Y1 - (jj[-1] + 1) / (H * SS) * (Y1 - Y0), X0 + (ii[-1] + 1) / (W * SS) * (X1 - X0), Y1 - jj[0] / (H * SS) * (Y1 - Y0))
    Zc = sample(T, sub, len(ii), len(jj))[0]
    ok = np.isfinite(Zc) & (np.abs(Zc) < 12000)
    blk = wgt[jj[0]:jj[-1] + 1, ii[0]:ii[-1] + 1] * ok
    Zc = np.where(ok, Zc, 0)
    Zs[jj[0]:jj[-1] + 1, ii[0]:ii[-1] + 1] = Zs[jj[0]:jj[-1] + 1, ii[0]:ii[-1] + 1] * (1 - blk) + Zc * blk
    print('merged', f, len(ii), 'x', len(jj))
# DESTRIPE (measured 2026-09-25: over the flat abyss the regional grid carries a ~1.8 m row pattern, ~6 km period -- row
# means 5x stronger than column means in the render). The part of the fine texture that stays coherent ALONG a row for
# ~100 km is the grid, not the seafloor; it is removed, only where the floor is deep and flat.
from scipy.ndimage import uniform_filter1d
hp = Zs - gaussian_filter(Zs, 12)
rowc = uniform_filter1d(np.clip(hp, -8, 8), size=301, axis=1)   # clipped: a seamount's bump is not a stripe (it smeared along its row)
lowrel = np.clip((np.clip(-Zs, 0, 6000) - 1500) / 1000, 0, 1) * np.clip(1 - gaussian_filter(np.abs(hp), 8) / 40, 0, 1)
Zs = Zs - rowc * lowrel
np.save('coast3_Z2x.npy', Zs.astype(np.float32))
mpp = (X1 - X0) / (W * SS) * math.cos(math.radians(38.5))
D = np.clip(-Zs, 0, 6000)
# DE-STRIPE: much of the abyss in the 'max' grid is a coarser base interpolated to 46 m, and its ~460 m row facets came
# out as horizontal lines under 16x relief. Smooth ACROSS the rows (north-south, ~1.5 px = ~480 m) and barely along
# them, so the facets go and real features of a kilometre and up -- hills, sediment waves, channel walls -- stay.
Zg = gaussian_filter(Zs, (1.5, 0.7))
gy, gx = np.gradient(Zg, mpp)
ex = 6.0 + 10.0 * np.clip(D / 3000.0, 0, 1)                       # exaggeration grows with depth
gx *= ex; gy *= ex
slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
def hs(az, alt): az, alt = math.radians(az), math.radians(alt); return np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
flat = 0.5 * math.sin(math.radians(40)) + 0.3 * math.sin(math.radians(45)) + 0.2 * math.sin(math.radians(50))
rel = np.clip(0.5 * hs(315, 40) + 0.3 * hs(0, 45) + 0.2 * hs(45, 50) - flat, -0.6, 0.6)
# fine texture: the floor less its ~2 km mean, squashed, stronger where it is deep and the ramp is flat
tex = np.tanh((Zg - gaussian_filter(Zs, 4.0)) / 25.0) * (0.10 + 0.10 * np.clip(D / 2500.0, 0, 1))
stops = [(0, (44, 104, 166)), (40, (34, 90, 150)), (100, (26, 76, 134)), (200, (20, 64, 120)), (600, (16, 53, 104)),
         (1500, (13, 45, 92)), (3000, (11, 39, 82)), (5000, (9, 33, 72))]
xs = np.array([s[0] for s in stops], float); cols = np.array([s[1] for s in stops], float)
col = np.stack([np.interp(D, xs, cols[:, k]) for k in range(3)], -1)
col = col * (1 + 1.05 * rel[..., None] + tex[..., None])
Dg = gaussian_filter(D, 1.2)
for lev, a in ((50, 0.10), (100, 0.12), (200, 0.30), (1000, 0.16), (2000, 0.14), (3000, 0.14), (4000, 0.12)):
    s = np.sign(Dg - lev)
    edge = (s[:, 1:] != s[:, :-1])[:-1, :] | (s[1:, :] != s[:-1, :])[:, :-1]
    e = np.zeros_like(D, bool); e[:-1, :-1] = edge
    col[e] = col[e] * (1 - a) + np.array([150, 190, 230]) * a
sea = Zs < 0
col1 = col.reshape(H, SS, W, SS, 3).mean(axis=(1, 3)); seafrac = sea.reshape(H, SS, W, SS).mean(axis=(1, 3))
Z1, mpp1 = sample(MED, BOX, W, H); hs1, rel1 = feats(Z1, mpp1); hb, rb, eb, db, orb = bins(Z1, hs1, rel1)
L = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lut_land.npy')); land_rgba = L[hb, rb, eb]
out = np.zeros((H, W, 4))
out[..., :3] = land_rgba[..., :3] * (1 - seafrac[..., None]) + col1 * seafrac[..., None]
out[..., 3] = land_rgba[..., 3] * (1 - seafrac) + 252 * seafrac
Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save('coast3_rgba.png')
# SHIPPED AS WEBP, not a 256-colour PNG: the palette posterised the graded ramp into terraces (7 grey levels across an
# abyss patch); lossy WebP at q 92 keeps the gradient and the alpha
Image.open('coast3_rgba.png').save('/Users/vvvaa/bluish-void/city_bathy_coast.webp', 'WEBP', quality=92, method=6)
print('wrote', os.path.getsize('/Users/vvvaa/bluish-void/city_bathy_coast.webp') // 1024, 'KB')
