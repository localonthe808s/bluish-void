"""Print the road kinds in a few tiles of the basemap at successive zooms.

Usage: python probe.py URL_OR_PMTILES z x y [z x y ...]
A tile at (z, x, y) is decoded and its 'roads' layer tallied by kind/kind_detail.
"""
import sys, gzip, collections, urllib.request
import mapbox_vector_tile


def fetch(src, z, x, y):
    if src.endswith('.pmtiles'):
        from pmtiles.reader import Reader, MmapSource
        f = open(src, 'rb')
        return Reader(MmapSource(f)).get(z, x, y)
    return urllib.request.urlopen(f"{src}/{z}/{x}/{y}.mvt").read()


src = sys.argv[1]
a = list(map(int, sys.argv[2:]))
for i in range(0, len(a), 3):
    z, x, y = a[i:i + 3]
    d = fetch(src, z, x, y)
    if d and d[:2] == b'\x1f\x8b':
        d = gzip.decompress(d)
    t = mapbox_vector_tile.decode(d)
    print(z, x, y, list(t.keys()), len(d))
    c = collections.Counter((f['properties'].get('kind'), f['properties'].get('kind_detail')) for f in t['roads']['features'])
    for k, v in sorted(c.items(), key=lambda a: -a[1]):
        print('   ', k, v)
    print('    sample', t['roads']['features'][0]['properties'], t['roads'].get('extent'))
