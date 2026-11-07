#!/usr/bin/env python3
"""WILD PARKS (user 2026-11-07, at the dark map over the Great Lakes: "why is canadas green brighter than the USs green spaces?").
The basemap tags Canada's big provincial parks (Algonquin, Quetico, the Ontario parks) kind=park, the class of a city park, so they drew
in the bright public-park green at near full strength, while the US wild lands (the Adirondacks, the Boundary Waters, the north woods)
come through as nature_reserve and draw as the soft wild-land tint. This lists every kind=park feature larger than 40 km^2 (Central Park
is 3.4, Pelham Bay 11, Griffith 17) by the tiles' own feature id, read off z9 -- the ids hold from z9 in (below that the archive merges
features under new ids, and the client sizes them by their drawn box instead).

    python3 wild_parks.py OUT.json
"""
import math, sys, json, gzip, urllib.request, collections
from concurrent.futures import ThreadPoolExecutor
import mapbox_vector_tile
from shapely.geometry import shape
Z = 9; URL = 'https://tiles.bluishvoid.com/bluish-basemap-20260829/%d/%d/%d.mvt'; MIN_KM2 = 40.0
def tx(lon): return int((lon + 180) / 360 * 2 ** Z)
def ty(lat): return int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * 2 ** Z)
def lat_of(y): n = math.pi - 2 * math.pi * (y + .5) / 2 ** Z; return math.degrees(math.atan(math.sinh(n)))
def one(xy):
    x, y = xy
    for k in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(URL % (Z, x, y), headers={'User-Agent': 'bluishvoid.com park bake', 'Origin': 'https://bluishvoid.com'}), timeout=60).read(); break
        except Exception as e:
            if k == 3: print('fail', x, y, e, flush=True); return []
    if not b: return []
    if b[:2] == b'\x1f\x8b': b = gzip.decompress(b)
    d = mapbox_vector_tile.decode(b); ext = 4096; side = 40075.016 * math.cos(math.radians(lat_of(y))) / 2 ** Z; out = []
    for f in d.get('landuse', {}).get('features', []):
        if f['properties'].get('kind') != 'park' or f.get('id') is None: continue
        try: a = shape(f['geometry']).area / ext ** 2 * side * side
        except Exception: continue
        out.append((f['id'], a))
    return out
def main(out):
    T = [(x, y) for x in range(tx(-141), tx(-52) + 1) for y in range(ty(62), ty(24) + 1)]
    A = collections.Counter(); done = 0
    with ThreadPoolExecutor(24) as ex:
        for r in ex.map(one, T):
            for i, a in r: A[i] += a
            done += 1
            if done % 1000 == 0: print(done, '/', len(T), 'tiles,', sum(1 for v in A.values() if v >= MIN_KM2), 'wild so far', flush=True)
    W = sorted(i for i, a in A.items() if a >= MIN_KM2)
    json.dump(W, open(out, 'w'), separators=(',', ':'))
    print('parks seen', len(A), 'wild (>= %g km2)' % MIN_KM2, len(W), flush=True)
if __name__ == '__main__': main(sys.argv[1])
