#!/usr/bin/env python3
"""LAKES AND PONDS FROM USGS (user 2026-11-07, at a pond at Forest Valley Rd and Freedom Rd, Pleasant Valley NY: "it looks like bodies of
water could be refined further" -> "yes start with the NHD bake"). The basemap's lakes are OpenStreetMap's: that pond is 32 hand-traced
points with straight-line shores; USGS's National Hydrography Dataset (High Resolution, 1:24,000 or finer, public domain) has it in 93
points that follow the shore the lidar shows. This bakes NHD's water polygons into vector tiles for street-level zooms.

Kept: NHDWaterbody LakePond (390), Reservoir (436), Estuary (493); NHDArea StreamRiver (460, the wide rivers' channels), CanalDitch (336),
Rapids (431). Left out: SwampMarsh (466), SeaOcean (445), BayInlet (312), Foreshore (364), Inundation (403) -- the basemap's sea and the
wetland fill draw those. Source per state: prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/State/GPKG/NHD_H_<State>_State_GPKG.zip
(EPSG:4269, NAD83 lon/lat ~= WGS84 at map scale).

    python3 bake_nhd.py STATE.gpkg [STATE2.gpkg ...] OUTDIR [zmin zmax]

Layer "water", properties: t = 'lake' | 'reservoir' | 'estuary' | 'river' | 'canal' | 'rapids', n = GNIS name (when there is one).
Simplified to 0.15 px per zoom, never smoothed; one tile at a time per z10 block, every polygon read once (the river bake's lesson).
"""
import math, os, sqlite3, sys, time
import numpy as np, shapely
from shapely import wkb
from shapely.geometry import box
from shapely.strtree import STRtree
import mapbox_vector_tile

KEEP_WB = {390: 'lake', 436: 'reservoir', 493: 'estuary'}
KEEP_AR = {460: 'river', 336: 'canal', 431: 'rapids'}
R = 6378137.0; S = 2 * math.pi * R; TOL = 0.15

def gpkg_geom(b):
    flags = b[3]; env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    return wkb.loads(bytes(b[8 + env:]))

def merc(xy):
    lon = xy[:, 0]; lat = np.clip(xy[:, 1], -85, 85)
    return np.column_stack([np.radians(lon) * R, np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * R])

def load(paths):
    G, P = [], []
    for p in paths:
        c = sqlite3.connect(p)
        for tbl, keep in (('NHDWaterbody', KEEP_WB), ('NHDArea', KEEP_AR)):
            gc = c.execute("select column_name from gpkg_geometry_columns where lower(table_name) = lower(?)", (tbl,)).fetchone()[0]
            q = 'select "%s", ftype, gnis_name from "%s" where ftype in (%s)' % (gc, tbl, ','.join(str(k) for k in keep))
            for b, ft, nm in c.execute(q):
                if b is None: continue
                g = gpkg_geom(b)
                if g is None or g.is_empty: continue
                g = shapely.force_2d(shapely.transform(g, merc))
                if not g.is_valid: g = g.buffer(0)
                if g.is_empty: continue
                G.append(g); P.append({'t': keep[ft], **({'n': nm} if nm else {})})
        c.close()
        print('loaded', os.path.basename(p), len(G), flush=True)
    return G, P

def main(args):
    paths = [a for a in args if a.endswith('.gpkg')]; rest = [a for a in args if not a.endswith('.gpkg')]
    out = rest[0]; zmin = int(rest[1]) if len(rest) > 1 else 11; zmax = int(rest[2]) if len(rest) > 2 else 15
    G, P = load(paths); tree = STRtree(G)
    x0, y0, x1, y1 = shapely.total_bounds(G)
    for z in range(zmin, zmax + 1):
        n = 2 ** z; ts = S / n; tol = ts / 256 * TOL; pad = ts / 256 * 4; t0 = time.time(); cnt = 0
        for tx in range(int((x0 + S / 2) // ts), int((x1 + S / 2) // ts) + 1):
            for ty in range(int((S / 2 - y1) // ts), int((S / 2 - y0) // ts) + 1):
                bx0 = -S / 2 + tx * ts; bx1 = bx0 + ts; by1 = S / 2 - ty * ts; by0 = by1 - ts
                bb = box(bx0 - pad, by0 - pad, bx1 + pad, by1 + pad); fs = []
                for i in tree.query(bb):
                    g = G[i]
                    if not g.intersects(bb): continue
                    g = g.intersection(bb).simplify(tol, preserve_topology=True)
                    if g.is_empty or g.area < tol * tol * 4: continue          # under ~2 px across at this zoom: nothing to draw
                    fs.append({'geometry': g.wkb, 'properties': P[i]})
                if not fs: continue
                data = mapbox_vector_tile.encode([{'name': 'water', 'features': fs}],
                                                 default_options={'quantize_bounds': (bx0, by0, bx1, by1), 'extents': 4096, 'y_coord_down': False})
                d = os.path.join(out, str(z), str(tx)); os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, '%d.mvt' % ty), 'wb') as f: f.write(data)
                cnt += 1
        print('z%d: %d tiles, %.0f s' % (z, cnt, time.time() - t0), flush=True)

if __name__ == '__main__':
    main(sys.argv[1:])
