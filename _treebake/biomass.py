#!/usr/bin/env python3
"""HOW MUCH WOOD THE FOREST HOLDS (user 2026-10-29, TREES improvement 7). ESA Climate Change Initiative Biomass v7.0: forest above-ground
biomass in tonnes of dry matter a hectare, 1 km, 2005-2012 and 2015-2024 (Santoro et al.; free with citation, ESA CCI Biomass terms).
Read straight from CEDA's archive by HTTP range (the 3 GB file is gzip-chunked HDF5; only the lower 48 is fetched), cut to web-mercator
palette PNGs z3-z8 per year: palette index = biomass / 6 t/ha (0-63, capped at 378), under 12 t/ha clear. OUT/<year>/{z}/{x}/{y}.png
    python3 biomass.py OUT YEAR [YEAR...]"""
import math, os, sys
import numpy as np, h5py
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rangefile import RangeFile
URL = 'https://dap.ceda.ac.uk/neodc/esacci/biomass/data/agb/maps/v7.0/netcdf/ESACCI-BIOMASS-L4-AGB-MERGED-1000m-fv7.0.nc'
Z = 8; STEP = 6
# the lower 48 first (2026-10-29), then North America with Canada and Mexico (user 2026-10-29, "go for it"): BOX=na
W0, S0, E0, N0 = (-141.0, 14.5, -52.0, 70.0) if os.environ.get('BOX') == 'na' else (-125.0, 24.3, -66.8, 49.5)
STOPS = [(2, (236, 226, 190)), (8, (204, 204, 140)), (16, (150, 180, 100)), (26, (80, 150, 95)), (38, (30, 115, 100)), (50, (15, 80, 85)), (63, (8, 50, 60))]
def palette():
    pal = np.zeros((256, 3), np.int32); seen = set()
    for m in range(2, 64):
        for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
            if a <= m <= b: f = (m - a) / (b - a); pal[m] = [round(ca[i] + (cb[i] - ca[i]) * f + 1e-9) for i in range(3)]; break
        c = tuple(pal[m])
        while c in seen: c = (c[0], c[1], (c[2] + 1) % 256)
        pal[m] = c; seen.add(c)
    return pal
def tx(lo, z): return (lo + 180) / 360 * 2 ** z
def ty(la, z): r = math.radians(la); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z
def main(out, years):
    h = h5py.File(RangeFile(URL), 'r')
    lat = h['lat'][:]; lon = h['lon'][:]; t = h['time'][:]
    units = h['time'].attrs.get('units', b''); units = units.decode() if isinstance(units, bytes) else str(units)
    import datetime
    base = datetime.datetime.strptime(units.split('since')[1].strip()[:10], '%Y-%m-%d'); yrs = [(base + datetime.timedelta(days=float(v))).year for v in t]
    print('years', yrs, flush=True)
    r0, r1 = sorted([int(np.argmin(abs(lat - N0))), int(np.argmin(abs(lat - S0)))]); c0, c1 = int(np.argmin(abs(lon - W0))), int(np.argmin(abs(lon - E0)))
    la = lat[r0:r1 + 1]; lo = lon[c0:c1 + 1]
    pal = palette(); flat = []; [flat.extend(int(v) for v in pal[i]) for i in range(256)]; trns = bytes([0, 0] + [255] * 62 + [0] * 192)
    x0, x1 = int(tx(W0, Z)), int(tx(E0, Z)) + 1; y0, y1 = int(ty(N0, Z)), int(ty(S0, Z)) + 1; PW, PH = (x1 - x0) * 256, (y1 - y0) * 256
    px = (x0 * 256 + np.arange(PW) + .5) / (2 ** Z * 256) * 360 - 180; py = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y0 * 256 + np.arange(PH) + .5) / (2 ** Z * 256)))))
    ci = np.clip(np.round((px - lo[0]) / (lo[1] - lo[0])).astype(int), 0, len(lo) - 1); ri = np.clip(np.round((py - la[0]) / (la[1] - la[0])).astype(int), 0, len(la) - 1)
    for Y in years:
        k = yrs.index(Y); a = h['agb'][k, r0:r1 + 1, c0:c1 + 1].astype(np.float32); print(Y, 'read', a.shape, flush=True)
        idx = np.where(a > 0, np.clip(np.round(a / STEP), 0, 63), 0).astype(np.uint8); idx[idx < 2] = 0
        mos = idx[ri[:, None], ci[None, :]]; n = 0
        okx = (px >= min(lo[0], lo[-1])) & (px <= max(lo[0], lo[-1])); oky = (py >= min(la[0], la[-1])) & (py <= max(la[0], la[-1]))
        mos[~oky, :] = 0; mos[:, ~okx] = 0   # outside the read window: clear, not the edge value smeared
        lv = mos; ox, oy = x0, y0
        for z in range(Z, 2, -1):
            if z < Z:
                # halve: mean of the cells holding forest, empty unless 2 of 4 do; keep the z-grid aligned
                if ox % 2: lv = np.pad(lv, ((0, 0), (256, 0))); ox -= 1
                if oy % 2: lv = np.pad(lv, ((256, 0), (0, 0))); oy -= 1
                if lv.shape[1] % 512: lv = np.pad(lv, ((0, 0), (0, 512 - lv.shape[1] % 512)))
                if lv.shape[0] % 512: lv = np.pad(lv, ((0, 512 - lv.shape[0] % 512), (0, 0)))
                b = lv.reshape(lv.shape[0] // 2, 2, lv.shape[1] // 2, 2).astype(np.float32); m = b >= 2; c = m.sum((1, 3)); s = (b * m).sum((1, 3))
                lv = np.where(c >= 2, np.round(s / np.maximum(c, 1)), 0).astype(np.uint8); ox //= 2; oy //= 2
            for j in range(lv.shape[0] // 256):
                for i in range(lv.shape[1] // 256):
                    tl = lv[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256]
                    if not (tl >= 2).any(): continue
                    d = os.path.join(out, str(Y), str(z), str(ox + i)); os.makedirs(d, exist_ok=True)
                    im = Image.fromarray(tl, 'P'); im.putpalette(flat); im.save(os.path.join(d, '%d.png' % (oy + j)), optimize=True, transparency=trns); n += 1
        print(Y, 'tiles', n, flush=True)
if __name__ == '__main__':
    main(sys.argv[1], [int(y) for y in sys.argv[2:]])
