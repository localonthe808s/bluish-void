#!/usr/bin/env python3
"""ALBANY'S HEADSTONES AT 25 CM (2026-11-12, user: "those are a mess, thats not the real order" -> "it should be what we did for the NYC
cemetaries"). NYC's /city_stones.json snaps each stone to a 2 m grid, and these rows run closer than that, so they came out scrambled.
This file uses the SAME encoding with 64 m cells -- each byte pair a 0.25 m step inside its cell -- which the map's stone drawing reads
unchanged (it divides cell by 256). One file for Albany Rural and St. Agnes.

    python3 _cembake/albany_stones.py <repo root> <stones_px.npy>:<ortho grid.txt> [<stones_px.npy>:<ortho grid.txt> ...]
"""
import base64, json, os, sys
import numpy as np

ROOT = sys.argv[1]
X, Y = [], []
for arg in sys.argv[2:]:
    sp, grid = arg.split(':')
    X0, Y1, RES = [float(v) for v in open(grid).read().split()[:3]]
    P = np.load(sp)
    X += list(X0 + P[:, 0] * RES)
    Y += list(Y1 - P[:, 1] * RES)
CELL = 64.0
x0 = float(np.floor(min(X) / CELL) * CELL)
y0 = float(np.floor(min(Y) / CELL) * CELL)
cells = {}
for x, y in zip(X, Y):
    i, j = int((x - x0) // CELL), int((y - y0) // CELL)
    a = min(255, int((x - x0 - i * CELL) / CELL * 256))
    b = min(255, int((y - y0 - j * CELL) / CELL * 256))
    cells.setdefault('%d,%d' % (i, j), set()).add((a, b))
out = {'x0': x0, 'y0': y0, 'cell': CELL, 'n': sum(len(v) for v in cells.values()),
       'c': {k: base64.b64encode(bytes([q for ab in sorted(v) for q in ab])).decode() for k, v in cells.items()}}
json.dump(out, open(os.path.join(ROOT, 'albany_stones.json'), 'w'), separators=(',', ':'))
print('stones', out['n'], 'cells', len(cells), 'kb', os.path.getsize(os.path.join(ROOT, 'albany_stones.json')) // 1024)
