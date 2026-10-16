#!/usr/bin/env python3
"""RIVERS FOR NORTH AMERICA AND THE CARIBBEAN (user 2026-10-16: "lets add rivers and relief for all north america and the
caribbean", "dont limit yourself to those sources"). The basemap draws OSM river lines only from z10 (_bvPaintPlus); this
fills the national and regional zooms, z3-9, every river sized by the land it drains.

Source: GEOGLOWS v2 (geoglows-v2 open S3 bucket, CC BY 4.0; its stream lines are NGA's TDX-Hydro, CC BY-SA 4.0, so these
tiles are CC BY-SA too), traced from the 12 m TanDEM-X elevation model. The global simplified stream file carries only
LINKNO; tables/v2-model-table.parquet gives each reach DSContArea (m2 drained at its outlet). North America and the
Caribbean are GEOGLOWS regions (VPUs) 701-718 and 801-804. TDX-Hydro has no reaches on the Canadian Arctic islands or
Greenland.

Output: one PMTiles archive of vector tiles (layer "rivers", property a = km2 drained), z3-8, each zoom keeping only the
rivers that read at that scale (thresholds below), simplified to ~half a pixel. The page draws it with protomaps-leaflet
(_bvPaintPlus) up to z9, over-zooming z8; width by drainage.

    python3 bake.py streams.gpkg model.parquet meta.parquet OUT.pmtiles
"""
import math, sqlite3, struct, sys, gzip
import numpy as np, pandas as pd
import mapbox_vector_tile
from shapely import wkb
from shapely.geometry import box, mapping
from shapely.strtree import STRtree
from pmtiles.tile import zxy_to_tileid, TileType, Compression
from pmtiles.writer import Writer

VPUS = set(range(701, 719)) | set(range(801, 805))
THR = {3: 30000, 4: 15000, 5: 6000, 6: 2500, 7: 1000, 8: 300}     # km2 drained to be drawn at that tile zoom

def gpkg_geom(b):
    flags = b[3]; env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    return wkb.loads(bytes(b[8 + env:]))

def lonlat_tile(lon, lat, z):
    n = 2 ** z; lat = max(-85, min(85, lat))
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

def tile_bounds(z, x, y):
    n = 2 ** z
    w = x / n * 360 - 180; e = (x + 1) / n * 360 - 180
    nn = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n)))); s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return w, s, e, nn

def main(gpkg, model, meta, out):
    m = pd.read_parquet(model, columns=['LINKNO', 'DSContArea', 'VPUCode'])
    m = m[m.VPUCode.isin(VPUS) & (m.DSContArea >= THR[8] * 1e6)]
    area = dict(zip(m.LINKNO.astype(np.int64), (m.DSContArea / 1e6).round().astype(np.int64)))
    print('reaches kept', len(area), flush=True)
    c = sqlite3.connect(gpkg)
    feats = []
    for link, g in c.execute('select LINKNO, geom from global_streams_simplified'):
        a = area.get(int(link))
        if a is None: continue
        feats.append((a, gpkg_geom(g)))
    print('geometries', len(feats), flush=True)
    with open(out, 'wb') as f:
        W = Writer(f); n_t = 0
        for z in range(3, 9):
            sub = [(a, g) for a, g in feats if a >= THR[z]]
            px = 360.0 / (256 * 2 ** z)
            geoms = [g.simplify(px * 0.5, preserve_topology=False) for a, g in sub]
            tree = STRtree(geoms)
            x0, y0 = lonlat_tile(-180, 84, z); x1, y1 = lonlat_tile(-50, 7, z)
            cnt = 0
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    w, s, e, nn = tile_bounds(z, x, y)
                    pad = (e - w) * 8 / 256                          # a few pixels past the edge so round caps meet
                    bb = box(w - pad, s - pad, e + pad, nn + pad)
                    idx = tree.query(bb)
                    if not len(idx): continue
                    fs = []
                    for i in idx:
                        gi = geoms[i].intersection(bb)
                        if gi.is_empty: continue
                        fs.append({'geometry': gi.wkb, 'properties': {'a': int(sub[i][0])}})
                    if not fs: continue
                    # MVT in web mercator: quantize lon/lat through mercator so lines sit right at every latitude
                    def merc(gm):
                        from shapely.ops import transform
                        return transform(lambda X, Y, Z=None: (np.radians(X), np.log(np.tan(np.pi / 4 + np.radians(np.clip(Y, -85, 85)) / 2))), gm)
                    mb = merc(box(w, s, e, nn)).bounds
                    data = mapbox_vector_tile.encode([{'name': 'rivers', 'features': [{'geometry': merc(wkb.loads(q['geometry'])).wkb, 'properties': q['properties']} for q in fs]}],
                                                     default_options={'quantize_bounds': mb, 'extents': 4096, 'y_coord_down': False})
                    W.write_tile(zxy_to_tileid(z, x, y), gzip.compress(data)); cnt += 1
            n_t += cnt
            print('z%d: %d rivers, %d tiles' % (z, len(sub), cnt), flush=True)
        W.finalize({'tile_type': TileType.MVT, 'tile_compression': Compression.GZIP, 'min_zoom': 3, 'max_zoom': 8,
                    'min_lon_e7': int(-180e7), 'min_lat_e7': int(7e7), 'max_lon_e7': int(-50e7), 'max_lat_e7': int(84e7),
                    'center_zoom': 4, 'center_lon_e7': int(-100e7), 'center_lat_e7': int(45e7)},
                   {'vector_layers': [{'id': 'rivers', 'fields': {'a': 'Number'}, 'minzoom': 3, 'maxzoom': 8}],
                    'attribution': 'GEOGLOWS v2 / NGA TDX-Hydro (CC BY-SA 4.0)'})
    print('tiles', n_t)

if __name__ == '__main__':
    main(*sys.argv[1:5])
