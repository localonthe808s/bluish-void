"""GHOST WATERS BEYOND THE CITY, step 1 (2026-11-22): what is water or wetland TODAY around NYC, rasterized onto ring_marsh.py's grid.

Read from our own basemap (tiles.bluishvoid.com, OpenStreetMap via Protomaps, z13): the water layer's polygons (ocean, bays, rivers,
lakes -- the sea included, so no coastline flood fill is needed) and the landuse layer's wetland. Overpass, which the city bake used,
took 42 s for a one-block query on 2026-11-22; the basemap is the same OSM water, already cut into tiles.

Output: _histbake/ring/wet.npy (uint8, 1 = wet today), the grid of ring_marsh.py."""
import gzip, math, os, sys, urllib.request
import numpy as np, mapbox_vector_tile
from rasterio import features
from shapely.geometry import shape
from shapely.ops import transform as shp_transform
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ring_grid import W0, S0, E0, N0, NX, NY, T

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'ring', 'osm'); os.makedirs(CACHE, exist_ok=True)
URL = 'https://tiles.bluishvoid.com/bluish-basemap-20261114/%d/%d/%d.mvt'
Z = 13
SKIP = {'swimming_pool', 'fountain'}

def tx(lon): return (lon + 180) / 360 * 2 ** Z
def ty(lat): return (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * 2 ** Z

def fetch(x, y):
    f = os.path.join(CACHE, '%d_%d_%d.mvt' % (Z, x, y))
    if not os.path.exists(f):
        r = urllib.request.urlopen(urllib.request.Request(URL % (Z, x, y), headers={'User-Agent': 'bluish-void-histbake/1.0'}), timeout=60).read()
        open(f, 'wb').write(r)
    r = open(f, 'rb').read()
    if r[:2] == b'\x1f\x8b': r = gzip.decompress(r)
    return mapbox_vector_tile.decode(r, default_options={'y_coord_down': True}) if r else {}

def main():
    wet = np.zeros((NY, NX), np.uint8); n = 0
    for x in range(int(tx(W0)), int(tx(E0)) + 1):
        for y in range(int(ty(N0)), int(ty(S0)) + 1):
            t = fetch(x, y); n += 1
            def to_ll(px, py, x=x, y=y):
                ext = 4096.0
                lon = (x + np.asarray(px) / ext) / 2 ** Z * 360 - 180
                lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + np.asarray(py) / ext) / 2 ** Z))))
                return lon, lat
            gs = []
            for f in t.get('water', {}).get('features', []):
                if f['geometry']['type'] in ('Polygon', 'MultiPolygon') and (f['properties'].get('kind') not in SKIP):
                    gs.append(shape(f['geometry']))
            for f in t.get('landuse', {}).get('features', []):
                if f['properties'].get('kind') == 'wetland' and f['geometry']['type'] in ('Polygon', 'MultiPolygon'):
                    gs.append(shape(f['geometry']))
            gs = [shp_transform(to_ll, g.buffer(0)) for g in gs]
            gs = [g for g in gs if not g.is_empty]
            if gs: features.rasterize(((g, 1) for g in gs), out=wet, transform=T, merge_alg=features.MergeAlg.replace)
    np.save(os.path.join(HERE, 'ring', 'wet.npy'), wet)
    print('tiles', n, 'wet share %.3f' % wet.mean())

if __name__ == '__main__':
    main()
