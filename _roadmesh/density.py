"""Road length per kind_detail inside one z8 tile, read at each data zoom.

Usage: python density.py PMTILES x8 y8
Shows at which data zoom secondary/tertiary arrive in full (length in z8-tile
units: 1.0 = one tile edge).
"""
import sys, collections
import numpy as np
sys.path.insert(0, __import__('os').path.dirname(__file__))
import bake

path, x8, y8 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
cache = bake.DataCache(path)

# reuse the decoder, one kind_detail at a time
orig = dict(motorway=0, motorway_link=0, trunk=1, trunk_link=1, primary=1, primary_link=1,
            secondary=2, secondary_link=2, tertiary=2, tertiary_link=2)
for dz in range(8, 14):
    f = 1 << (dz - 8)
    tot = collections.Counter()
    for dx in range(x8 * f, x8 * f + f):
        for dy in range(y8 * f, y8 * f + f):
            d = bake.reader(path).get(dz, dx, dy)
            if not d:
                continue
            for kd in orig:
                bake.KIND_CLASS = {kd: 0}
                ext, lines = bake.decode_roads(d, True)
                for ln in lines.get(0, ()):
                    # clip-ish: count only segment length (buffer overlap is small)
                    tot[kd] += np.hypot(*np.diff(ln, axis=0).T).sum() / ext / f
    print(dz, ' '.join('%s=%.1f' % (k, tot[k]) for k in orig))
