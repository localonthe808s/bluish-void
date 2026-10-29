#!/usr/bin/env python3
"""THE DROUGHT ATLAS, ONE FILE PER HALF DEGREE (2026-10-29). NOAA NCEI's Living Blended Drought Atlas v3 (Gille et al. 2026 / Cook et al. 2010,
public domain): summer (Jun-Aug) Palmer Modified Drought Index on a 0.5-degree grid over the lower 48, 0-2025 CE -- tree rings to 1899,
measured (NClimGrid) from 1900, extended each year. Each land cell -> cdn rings/lbda/<lat>_<lon>.bin: 2,026 signed bytes, PMDI x 10, year 0
first, -128 = none; rings/lbda/cells.json lists the cells and the years.
    python3 _ringbake/lbda.py LBDA-v3.nc OUTDIR"""
import json, os, sys
import numpy as np, h5py
def main(src, out):
    f = h5py.File(src, 'r'); P = f['PMDI'][:]; la = f['lat'][:]; lo = f['lon'][:]; t = f['time'][:]
    os.makedirs(out, exist_ok=True); cells = []
    for i in range(len(lo)):
        for j in range(len(la)):
            v = P[i, j, :]
            if np.isfinite(v).sum() < 100: continue
            b = np.where(np.isfinite(v), np.clip(np.round(v * 10), -127, 127), -128).astype(np.int8)
            k = '%.2f_%.2f' % (la[j], lo[i]); open(os.path.join(out, k + '.bin'), 'wb').write(b.tobytes()); cells.append([round(float(la[j]), 2), round(float(lo[i]), 2)])
    json.dump({'src': 'Living Blended Drought Atlas v3, NOAA NCEI (doi:10.25921/7xm8-jn36)', 'y0': int(t[0]), 'y1': int(t[-1]), 'blend': 1900, 'cells': cells}, open(os.path.join(out, 'cells.json'), 'w'), separators=(',', ':'))
    print(len(cells), 'cells', int(t[0]), int(t[-1]))
if __name__ == '__main__': main(*sys.argv[1:3])
