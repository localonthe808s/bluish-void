#!/usr/bin/env python3
"""AIR FROM TOXIC RELEASES (user 2026-11-20: "could we show the data differently? we have them as circles right now but it doesnt
really show the range or limits of the areas" -> "yes do the air footprint and outlines" -> "try it out").

EPA's Risk-Screening Environmental Indicators (RSEI) model takes every Toxics Release Inventory plant's air releases and models where
they travel, on 810 m squares out to about 49 km, weighting each chemical's concentration by its toxicity. The aggregated grid file sums
every plant and chemical per square (ToxConc; CTConc = the cancer toxicity weights only). This bake turns the lower-48 grid into map
tiles (edges softened: see SOFT EDGES): a single warm hue that fades in from the national 90th percentile of squares (so only the top tenth of the country is shaded at
all) to full above the 99.9th, blended between square centers, z4-10.

Grid: USA Contiguous Albers Equal Area (GRS80, lat0 23, lon0 -96, parallels 29.5 / 45.5); square (X, Y) is centered at (810 X, 810 Y) m
-- fitted exactly against the grid shapefile's own center coordinates (2026-11-20).

Out: OUT/air/{all,cx}/{z}/{x}/{y}.png and OUT/air_v1.json {year, version, built, lo/hi per variant, tiles}
Run: python3 _rseibake/bake.py OUT [path-or-url of aggmicroYYYY_YYYY.csv.gz]   (numpy, pandas, Pillow; ~20-40 min)
"""
import sys, os, re, io, json, math, time, datetime, subprocess, urllib.request
import numpy as np
import pandas as pd
from PIL import Image

BASE = 'https://gaftp.epa.gov/rsei/Current_Version/'
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid rsei bake)'}
ZMIN, ZMAX = 4, 10
C0 = np.array([180, 83, 9], np.float32)       # deep amber (dim, at the floor)
C1 = np.array([254, 240, 138], np.float32)    # pale gold (bright, at the top)

# ---- the projection (Snyder, ellipsoidal Albers) ----
A = 6378137.0; F = 1 / 298.257222101; E2 = 2 * F - F * F; E = math.sqrt(E2)
def _q(s): return (1 - E2) * (s / (1 - E2 * s * s) - (1 / (2 * E)) * np.log((1 - E * s) / (1 + E * s)))
def _m(ph): s = math.sin(ph); return math.cos(ph) / math.sqrt(1 - E2 * s * s)
_r = math.radians
_m1, _m2 = _m(_r(29.5)), _m(_r(45.5)); _q1, _q2, _q0 = _q(math.sin(_r(29.5))), _q(math.sin(_r(45.5))), _q(math.sin(_r(23)))
N_ = (_m1 * _m1 - _m2 * _m2) / (_q2 - _q1); C_ = _m1 * _m1 + N_ * _q1; RHO0 = A * math.sqrt(C_ - N_ * _q0) / N_
def albers(lat, lon):
    rho = A * np.sqrt(C_ - N_ * _q(np.sin(np.radians(lat)))) / N_; th = N_ * np.radians(lon + 96)
    return rho * np.sin(th), RHO0 - rho * np.cos(th)
def inv_albers(x, y):
    rho = np.hypot(x, RHO0 - y); th = np.arctan2(x, RHO0 - y); qq = (C_ - (rho * N_ / A) ** 2) / N_
    lat = np.arcsin(qq / 2)                                     # iterate to the ellipsoidal latitude
    for _ in range(6):
        s = np.sin(lat); lat = lat + (1 - E2 * s * s) ** 2 / (2 * np.cos(lat)) * (qq / (1 - E2) - s / (1 - E2 * s * s) + 1 / (2 * E) * np.log((1 - E * s) / (1 + E * s)))
    return np.degrees(lat), -96 + np.degrees(th / N_)


def source():
    if len(sys.argv) > 2:
        return sys.argv[2]
    idx = urllib.request.urlopen(urllib.request.Request(BASE, headers=UA), timeout=120).read().decode()
    ver = sorted(re.findall(r'href="(V\d+_RY\d{4})/"', idx))[-1]
    agg = urllib.request.urlopen(urllib.request.Request(BASE + ver + '/Aggregated_Grid_Cell/', headers=UA), timeout=120).read().decode()
    files = sorted(set(re.findall(r'href="(aggmicro\d{4}_(\d{4})\.csv\.gz)"', agg)), key=lambda t: t[1])
    return BASE + ver + '/Aggregated_Grid_Cell/' + files[-1][0]


def load(src, out):
    p = src
    if src.startswith('http'):
        p = os.path.join(out, os.path.basename(src))
        if not os.path.exists(p):
            subprocess.run(['curl', '-sS', '-L', '-m', '3600', '-A', UA['User-Agent'], '-o', p + '.part', src], check=True); os.replace(p + '.part', p)
    d = pd.read_csv(p, usecols=['GridCode', 'X', 'Y', 'ToxConc', 'CTConc'], dtype={'GridCode': 'int8', 'X': 'int32', 'Y': 'int32', 'ToxConc': 'float32', 'CTConc': 'float32'})
    return d[d.GridCode == 14]


def grids(d):
    """dense log10 rasters over the lower-48 grid, NaN-free (0 where nothing)"""
    x0, y0 = int(d.X.min()) - 2, int(d.Y.min()) - 2
    W, H = int(d.X.max()) - x0 + 3, int(d.Y.max()) - y0 + 3
    out = {}
    for k, col in (('all', 'ToxConc'), ('cx', 'CTConc')):
        v = d[col].values; ok = v > 0
        lv = np.log10(v[ok]); lo, hi = float(np.percentile(lv, 90)), float(np.percentile(lv, 99.9)) + .35
        G = np.zeros((H, W), np.float32); G[d.Y.values[ok] - y0, d.X.values[ok] - x0] = lv
        # SOFT EDGES (2026-11-20): the model stops each plume at about 49 km, so a big emitter drew as a hard-edged disc whose rim sat
        # well above the floor -- a computing limit, not where the air stops. Shown instead: the field blurred by ~4 km (sigma 5
        # squares; empty squares read as low), with each square allowed to stand up to 0.45 above it so real peaks keep their shape
        from scipy import ndimage as ND
        G = np.maximum(ND.gaussian_filter(np.where(G > 0, G, 1.5).astype(np.float32), 5), G - 0.45)
        out[k] = (G, lo, hi)
        print(k, 'squares > 0:', int(ok.sum()), 'floor (90th) %.2f top %.2f' % (lo, hi), flush=True)
    return out, x0, y0


def tile(G, x0, y0, lo, hi, z, tx, ty, Gmax=None):
    N = 256 * 2 ** z
    gx = tx * 256 + np.arange(256) + .5; gy = ty * 256 + np.arange(256) + .5
    lon = gx / N * 360 - 180; lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * gy / N))))
    LON, LAT = np.meshgrid(lon, lat); x, y = albers(LAT, LON); FX = x / 810 - x0; FY = y / 810 - y0
    CX = np.floor(FX).astype(np.int64); CY = np.floor(FY).astype(np.int64); fx = FX - CX; fy = FY - CY
    H, W = G.shape; ok = (CX >= 0) & (CY >= 0) & (CX < W - 1) & (CY < H - 1)
    CX = np.clip(CX, 0, W - 2); CY = np.clip(CY, 0, H - 2); S = Gmax if Gmax is not None else G
    L = S[CY, CX] * (1 - fx) * (1 - fy) + S[CY, CX + 1] * fx * (1 - fy) + S[CY + 1, CX] * (1 - fx) * fy + S[CY + 1, CX + 1] * fx * fy
    L = np.where(ok, L, 0)
    t = np.clip((L - lo) / (hi - lo), 0, 1)
    if not (t > 0).any():
        return None
    rgb = C0[None, None, :] * (1 - t[..., None]) + C1[None, None, :] * t[..., None]
    al = np.where(t > 0, 230 * np.clip(t * 1.15, 0, 1) ** .75, 0)
    return Image.fromarray(np.dstack([rgb, al]).astype(np.uint8))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
    os.makedirs(out, exist_ok=True)
    src = source(); m = re.search(r'aggmicro(\d{4})_(\d{4})', src); ver, year = (m.group(1), int(m.group(2))) if m else ('', 0)
    print('source', src, flush=True); t0 = time.time()
    d = load(src, out); print('squares', len(d), round(time.time() - t0), 's', flush=True)
    G, x0, y0 = grids(d)
    # `built` is also the tiles' cache key: every bake a new one
    meta = {'year': year, 'version': ver, 'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'tiles': {}}
    from scipy import ndimage as ND
    for k, (Gk, lo, hi) in G.items():
        meta[k] = {'lo': round(lo, 3), 'hi': round(hi, 3)}
        # the tiles to make at z10: every square above the floor, its center's tile, plus a ring for the fade
        ys, xs = np.nonzero(Gk >= lo); la, lo_ = inv_albers((xs + x0) * 810.0, (ys + y0) * 810.0)
        n = 0
        for z in range(ZMAX, ZMIN - 1, -1):
            N = 256 * 2 ** z
            T = set(zip(((lo_ + 180) / 360 * N // 256).astype(int).tolist(), ((1 - np.log(np.tan(np.pi / 4 + np.radians(la) / 2)) / np.pi) / 2 * N // 256).astype(int).tolist()))
            T = {(a + i, b + j) for a, b in T for i in (-1, 0, 1) for j in (-1, 0, 1)}
            px = 40075016.0 * math.cos(math.radians(38)) / N              # a pixel's size at mid-latitude
            k_ = px / 810.0
            Gm = ND.maximum_filter(Gk, size=int(round(k_))) if k_ > 1.6 else None   # zoomed out, keep the hot spots
            for tx, ty in T:
                im = tile(Gk, x0, y0, lo, hi, z, tx, ty, Gm)
                if im is None:
                    continue
                pth = os.path.join(out, 'air', k, str(z), str(tx)); os.makedirs(pth, exist_ok=True)
                im.save(os.path.join(pth, '%d.png' % ty), optimize=True); n += 1
            print(' ', k, 'z%d' % z, len(T), 'candidates,', n, 'tiles so far', round(time.time() - t0), 's', flush=True)
        meta['tiles'][k] = n
    json.dump(meta, open(os.path.join(out, 'air_v1.json'), 'w'), separators=(',', ':'))
    print('done', meta, round(time.time() - t0), 's', flush=True)


if __name__ == '__main__':
    main()
