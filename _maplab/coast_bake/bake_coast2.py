"""THE COAST's relief/seafloor, round 2 (2026-09-25, user: "make this view have our best detailed ocean bathymetry,
this will be the view where we highlight the hudson canyon the best"). Land as round 1 (LUT learned off
city_bathy_ne.png). Sea: GMRT med (~750 m) everywhere, GMRT max (~46 m) over the Hudson Canyon (feathered), drawn
at 2x and averaged down: a continuous depth ramp in the site's navy family, multi-directional hillshade with vertical
exaggeration, faint isobaths (the 200 m shelf break stronger). Mercator rows."""
import numpy as np, math, netCDF4 as nc, sys
from PIL import Image
from scipy.ndimage import gaussian_filter, uniform_filter, zoom as ndzoom
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lut2 import load, sample, feats, bins
R = 6378137.0
BOX = (-8682920, 4028802, -7235766, 5311971); W, H = 2264, 2007; SS = 2
def grid_sample(G, box, w, h):
    return sample(G, box, w, h)[0]
MED = load('gmrt_med.nc'); CAN = load('t_canyon.nc')
X0, Y0, X1, Y1 = BOX
Zs = grid_sample(MED, BOX, W * SS, H * SS)
# the canyon survey, feathered into the regional grid over 0.15 deg inside its edges
lon = (X0 + (np.arange(W * SS) + 0.5) / (W * SS) * (X1 - X0)) / R * 180 / math.pi
ys = Y1 - (np.arange(H * SS) + 0.5) / (H * SS) * (Y1 - Y0); lat = (2 * np.arctan(np.exp(ys / R)) - math.pi / 2) * 180 / math.pi
cw_, cn = CAN[1], CAN[2]; ce = cw_ + CAN[3] * CAN[0].shape[1]; cs = cn - CAN[4] * CAN[0].shape[0]
fx = np.clip(np.minimum(lon - cw_, ce - lon) / 0.15, 0, 1); fy = np.clip(np.minimum(lat - cs, cn - lat) / 0.15, 0, 1)
wgt = fy[:, None] * fx[None, :]
jj = np.where(wgt.any(axis=1))[0]; ii = np.where(wgt.any(axis=0))[0]
if len(jj) and len(ii):
    sub = (X0 + ii[0] / (W * SS) * (X1 - X0), Y1 - (jj[-1] + 1) / (H * SS) * (Y1 - Y0), X0 + (ii[-1] + 1) / (W * SS) * (X1 - X0), Y1 - jj[0] / (H * SS) * (Y1 - Y0))
    Zc = grid_sample(CAN, sub, len(ii), len(jj))
    blk = wgt[jj[0]:jj[-1] + 1, ii[0]:ii[-1] + 1]
    Zs[jj[0]:jj[-1] + 1, ii[0]:ii[-1] + 1] = Zs[jj[0]:jj[-1] + 1, ii[0]:ii[-1] + 1] * (1 - blk) + Zc * blk
    print('canyon survey merged over', len(ii), 'x', len(jj), 'px')
mpp = (X1 - X0) / (W * SS) * math.cos(math.radians(38.5))
# relief: exaggerated, lit from the NW and the N, a touch of the NE so canyon walls on every side read
Ze = gaussian_filter(Zs, 0.7) * 6.0
gy, gx = np.gradient(Ze, mpp)
slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
def hs(az, alt): az, alt = math.radians(az), math.radians(alt); return np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
shade = 0.5 * hs(315, 40) + 0.3 * hs(0, 45) + 0.2 * hs(45, 50)
flat = hs(315, 40)[0, 0] * 0 + (0.5 * math.sin(math.radians(40)) + 0.3 * math.sin(math.radians(45)) + 0.2 * math.sin(math.radians(50)))
rel = np.clip(shade - flat, -0.6, 0.6)
# depth ramp: the site's shelf (17,57,111) and deep (6,25,51) as anchors, with the shelf itself graded and a lift toward shore
D = np.clip(-Zs, 0, 6000)
stops = [(0, (40, 96, 156)), (40, (30, 82, 140)), (100, (22, 68, 124)), (200, (17, 57, 111)), (600, (12, 42, 86)),
         (1500, (9, 33, 70)), (3000, (7, 27, 58)), (5000, (5, 20, 44))]
xs = np.array([s[0] for s in stops], float); cols = np.array([s[1] for s in stops], float)
col = np.stack([np.interp(D, xs, cols[:, k]) for k in range(3)], -1)
col = col * (1 + 0.95 * rel[..., None])                      # relief lights and darkens the ramp
# isobaths: a faint line where the depth crosses a level; the 200 m shelf break stronger
Dg = gaussian_filter(D, 1.2)
for lev, a in ((50, 0.10), (100, 0.12), (200, 0.30), (1000, 0.16), (2000, 0.14), (3000, 0.14), (4000, 0.12)):
    s = np.sign(Dg - lev)
    edge = (s[:, 1:] != s[:, :-1])[:-1, :] | (s[1:, :] != s[:-1, :])[:, :-1]
    e = np.zeros_like(D, bool); e[:-1, :-1] = edge
    col[e] = col[e] * (1 - a) + np.array([150, 190, 230]) * a
sea = Zs < 0
# down to the view's size: average the 2x2 blocks
col1 = col.reshape(H, SS, W, SS, 3).mean(axis=(1, 3))
seafrac = sea.reshape(H, SS, W, SS).mean(axis=(1, 3))
# land: the learned look, at 1x
Z1, mpp1 = sample(MED, BOX, W, H); hs1, rel1 = feats(Z1, mpp1); hb, rb, eb, db, orb = bins(Z1, hs1, rel1)
L = np.load('lut_land.npy'); land_rgba = L[hb, rb, eb]
out = np.zeros((H, W, 4))
out[..., :3] = land_rgba[..., :3] * (1 - seafrac[..., None]) + col1 * seafrac[..., None]
out[..., 3] = land_rgba[..., 3] * (1 - seafrac) + 252 * seafrac
Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save('coast2_rgba.png')
q = Image.open('coast2_rgba.png').quantize(colors=256, method=Image.Quantize.FASTOCTREE)
q.save('/Users/vvvaa/bluish-void/city_bathy_coast.png', optimize=True)
import os; print('wrote', os.path.getsize('/Users/vvvaa/bluish-void/city_bathy_coast.png') // 1024, 'KB')
