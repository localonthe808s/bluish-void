#!/usr/bin/env python3
"""THE SEAFLOOR'S SHAPE, past the coastal bathymetry (user 2026-10-16: "highlight all underwater geology like rivers and
mountains especially on the west coast"). Our bathymetry layer (_bathybake/, NOAA's coastal DEMs) stops near the shelf and
slope; beyond it the dark map showed a flat ocean where the Pacific has the Gorda and Juan de Fuca ridges, the Mendocino
Fracture Zone, Davidson Seamount, the lower reaches of Monterey Canyon and the deep-sea fans.

Source: the same AWS open Terrain Tiles as the land relief (render_na.py), whose ocean is global bathymetry (SRTM15+ /
ETOPO1 / GEBCO behind, ~0.5-1 km). Same multidirectional hillshade as the land, applied to the sea floor only: land and
the coastal strip above 0 m are clear, so the basemap's coast and NOAA's detailed bathymetry (drawn above this) keep it.
Exaggeration is LOWER than on land -- ocean relief is already kilometres tall -- and lifts at continental scale.
Output: 256 px WebP RGBA, z3-9, overzoomed beyond.
"""
import math
import numpy as np
from PIL import Image
import render as RD, render_na as RN

def sea_block(z, bx, by, B):
    T, P = RD.T, RD.PAD
    xs, ys = range(bx * B - 1, bx * B + B + 1), range(by * B - 1, by * B + B + 1)
    jobs = {(x, y): RN._pool.submit(RN._tile, z, x, y) for x in xs for y in ys}
    big = np.full(((B + 2) * T, (B + 2) * T), np.nan, np.float32)
    for (x, y), f in jobs.items():
        a = f.result()
        if a is not None:
            i, j = y - (by * B - 1), x - (bx * B - 1)
            big[i * T:(i + 1) * T, j * T:(j + 1) * T] = a
    return big[T - P:T + B * T + P, T - P:T + B * T + P].copy()

def exaggeration(z):
    return float(np.clip(2.2 * 1.3 ** (9 - z), 2.2, 9.0))     # pilot 1: x1-5 read faint at every scale

def shade(A, px, ymid, z):
    sea = np.isfinite(A) & (A < -2)
    Z = np.where(np.isfinite(A), np.minimum(A, 0.0), 0.0)          # land flattened to the shore so the coast is no cliff
    ground = px * math.cos(math.radians(RD.merc_lat(ymid)))
    gy, gx = np.gradient(Z.astype(np.float64), ground)
    ex = exaggeration(z); gx *= ex; gy *= ex
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy); alt = math.radians(45)
    hs = 0.0; ws = 0.0
    for az, w in ((315, .5), (270, .2), (360, .2), (225, .1)):
        a = math.radians(az); hs = hs + w * (math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(a - aspect)); ws += w
    d = (hs / ws - math.sin(alt))[RD.PAD:-RD.PAD, RD.PAD:-RD.PAD]
    ok = sea[RD.PAD:-RD.PAD, RD.PAD:-RD.PAD]
    depth = -Z[RD.PAD:-RD.PAD, RD.PAD:-RD.PAD]
    lit = np.clip(d / 0.16, 0, 1) ** 0.85
    dark = np.clip(-d / 0.30, 0, 1) ** 0.8
    a_lit = 0.40 * lit                                             # sunlit flanks a cool pale blue
    a_dark = np.clip(0.72 * dark + np.clip((depth - 3000) / 3000, 0, 1) * 0.18, 0, 0.78)   # shadow, and the abyss a shade deeper
    white = a_lit > a_dark
    alpha = np.where(white, a_lit, a_dark) * ok
    rgb = np.where(white[..., None], np.array([150, 190, 235], np.float32), np.array([2, 6, 18], np.float32))
    return np.dstack([rgb, alpha[..., None] * 255]).astype(np.uint8), ok

def render_block(z, bx, by, B):
    x0, _, _, y1 = RD.tile_bounds(z, bx * B, by * B)
    _, y0, x1, _ = RD.tile_bounds(z, bx * B + B - 1, by * B + B - 1)
    px = (x1 - x0) / (B * RD.T)
    A = sea_block(z, bx, by, B)
    rgba, ok = shade(A, px, (y0 + y1) / 2, z)
    T = RD.T
    for i in range(B):
        for j in range(B):
            sub = rgba[j * T:(j + 1) * T, i * T:(i + 1) * T]
            has = bool(ok[j * T:(j + 1) * T, i * T:(i + 1) * T].any())
            im = Image.fromarray(sub, 'RGBA') if has and sub[..., 3].max() >= 3 else None
            yield bx * B + i, by * B + j, im, has
