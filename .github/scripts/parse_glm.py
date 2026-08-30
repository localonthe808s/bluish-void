"""Distil GOES-19 GLM L2 granules (gran/*.nc) into glm/latest.json.

Flashes only, clipped to a box around NYC; each carries the granule's start
time so the client can fade by age. The output stays tiny (a heavy storm day
in this box is a few hundred flashes in 12 minutes).
"""
import calendar
import glob
import json
import re
import time

import netCDF4
import numpy as np

W, S, E, N = -76.0, 39.0, -71.0, 42.5

flashes = []
for p in sorted(glob.glob('gran/*.nc')):
    m = re.search(r'_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})', p)
    t = calendar.timegm(time.strptime(' '.join(m.groups()), '%Y %j %H %M %S')) if m else int(time.time())
    try:
        ds = netCDF4.Dataset(p)
        la = np.asarray(ds.variables['flash_lat'][:], dtype=float)
        lo = np.asarray(ds.variables['flash_lon'][:], dtype=float)
        ds.close()
    except Exception:
        continue
    sel = (la >= S) & (la <= N) & (lo >= W) & (lo <= E)
    for lon, lat in zip(lo[sel], la[sel]):
        flashes.append([round(float(lon), 3), round(float(lat), 3), t])

out = {'t': int(time.time()), 'src': 'GOES-19 GLM', 'box': [W, S, E, N], 'flashes': flashes}
json.dump(out, open('latest.json', 'w'), separators=(',', ':'))
print(len(flashes), 'flashes in box from', len(glob.glob('gran/*.nc')), 'granules')
