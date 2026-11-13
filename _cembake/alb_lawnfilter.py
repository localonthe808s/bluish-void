#!/usr/bin/env python3
"""Drop stone detections that are not set in open lawn (woods edges, brush, flowering trees).
A stone keeps its place when most of the ground within ~3 m of it is green grass (green over red and blue, not the yellow-green of
blossom), since headstones stand in mown lawn and the false hits sit in leaf litter and tree crowns.
    python3 _cembake/alb_lawnfilter.py <ortho dir> <stones_px.npy> [min lawn share, default 0.55]
Writes stones_px.npy back (keeps the original as stones_px_raw.npy)."""
import os, sys, numpy as np
from PIL import Image
from scipy.ndimage import uniform_filter
OD, SP = sys.argv[1], sys.argv[2]; TH = float(sys.argv[3]) if len(sys.argv) > 3 else 0.55
X0, Y1, RES, T, nx, ny = open(os.path.join(OD, 'grid.txt')).read().split(); T, nx, ny = int(T), int(nx), int(ny)
img = np.zeros((ny*T, nx*T, 3), np.uint8)
for i in range(nx):
    for j in range(ny):
        p = os.path.join(OD, 't_%d_%d.png' % (i, j))
        if os.path.exists(p): img[j*T:(j+1)*T, i*T:(i+1)*T] = np.asarray(Image.open(p).convert('RGB'))
r, g, b = [img[..., k].astype(np.int16) for k in range(3)]
lawn = ((g > r + 8) & (g > b + 6) & (g > 60)).astype(np.float32)
share = uniform_filter(lawn, 25)
raw = SP.replace('stones_px.npy', 'stones_px_raw.npy')
P = np.load(raw) if os.path.exists(raw) else np.load(SP)
if not os.path.exists(raw): np.save(raw, P)
xi = np.clip(P[:, 0].astype(int), 0, img.shape[1]-1); yi = np.clip(P[:, 1].astype(int), 0, img.shape[0]-1)
keep = share[yi, xi] >= TH
np.save(SP, P[keep]); print('kept', keep.sum(), 'of', len(P))
