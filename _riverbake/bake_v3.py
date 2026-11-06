#!/usr/bin/env python3
"""RIVERS v3: THE FULL-DETAIL STREAMS (user 2026-11-06: "i want river shapes to be highly detailed, i love their natural shape and
i dont want to gloss over its detail [with] crude or thickened lines that obscure its natural complex and rich path ... this is
regarding the basemap for all maps").

v2 (bake.py) read GEOGLOWS' global_streams_SIMPLIFIED file, simplified each reach again to half a pixel per zoom and then rounded
every bend with two passes of Chaikin corner-cutting. Each step took meanders off. v3:
  - reads the FULL TDX-Hydro streams, region by region (hydrography/vpu=NNN/streams_NNN.gpkg, EPSG:3857, DSContArea on each reach),
  - cuts each reach out of its region's lakes (lakes_NNN.gpkg, lakes of 0.5 km2 or more: smaller ponds only chopped lines into dashes),
  - simplifies only to 0.15 of a screen pixel at each zoom (0.3 of a device pixel on a retina screen) and never smooths,
  - adds z9 (rivers draining 100 km2 or more), so the last zoom before the basemap's OSM water no longer stretches z8.
Same license as v2: the streams are NGA TDX-Hydro, CC BY-SA 4.0, via GEOGLOWS v2 (CC BY 4.0).

Disk-light: one region is downloaded, reduced into reaches.sqlite (an R*Tree over the kept reaches, pre-trimmed at 10 m, far below
z9's 46 m tolerance) and deleted before the next. Then the tiles are cut from the index, one tile at a time.

    python3 bake_v3.py extract WORKDIR            # all 22 North American + Caribbean regions -> WORKDIR/reaches.sqlite
    python3 bake_v3.py tiles WORKDIR OUTDIR       # OUTDIR/{z}/{x}/{y}.mvt, plain protobuf (as the CDN serves v2)
    rclone copy OUTDIR r2:bluishvoid-bg/rivers/v3 --s3-no-check-bucket --header-upload "Content-Type: application/x-protobuf" \
        --header-upload "Cache-Control: public, max-age=31536000, immutable"
"""
import math, os, sqlite3, sys, time, urllib.request
import shapely
from shapely import wkb
from shapely.geometry import box
from shapely.strtree import STRtree
import mapbox_vector_tile

VPUS = list(range(701, 719)) + list(range(801, 805))
THR = {3: 30000, 4: 15000, 5: 6000, 6: 2500, 7: 1000, 8: 300, 9: 100}   # km2 drained to be drawn at that tile zoom
TOL = 0.15                       # of a 256-px tile's pixel
PRE = 10.0                       # m, the extract's trim
LAKE_MIN = 0.5e6                 # m2
R = 6378137.0; S = 2 * math.pi * R
BUCKET = 'https://geoglows-v2.s3-us-west-2.amazonaws.com/hydrography/vpu%3D{v}/{k}_{v}.gpkg'
UA = {'User-Agent': 'bluishvoid.com river bake'}

def gpkg_geom(b):
    flags = b[3]; env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    return wkb.loads(bytes(b[8 + env:]))

def merc(xy):
    import numpy as np
    lon = xy[:, 0]; lat = np.clip(xy[:, 1], -85, 85)
    return np.column_stack([np.radians(lon) * R, np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * R])

def fetch(url, path):
    if os.path.exists(path): return
    tmp = path + '.part'
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, open(tmp, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)
    os.replace(tmp, path)

def db(work):
    c = sqlite3.connect(os.path.join(work, 'reaches.sqlite'))
    c.execute('create table if not exists r(id integer primary key, a integer, vpu integer, g blob)')
    c.execute('create virtual table if not exists ri using rtree(id, minx, maxx, miny, maxy)')
    c.execute('create table if not exists done(vpu integer primary key)')
    return c

def extract(work):
    os.makedirs(work, exist_ok=True); c = db(work)
    done = {v for (v,) in c.execute('select vpu from done')}
    for v in VPUS:
        if v in done: continue
        t0 = time.time(); sp = os.path.join(work, 'streams_%d.gpkg' % v); lp = os.path.join(work, 'lakes_%d.gpkg' % v)
        fetch(BUCKET.format(v=v, k='streams'), sp); fetch(BUCKET.format(v=v, k='lakes'), lp)
        lakes = []
        lc = sqlite3.connect(lp); lt = lc.execute('select table_name from gpkg_contents').fetchone()[0]
        lsrs = lc.execute('select srs_id from gpkg_geometry_columns').fetchone()[0]
        for (b,) in lc.execute('select geom from "%s"' % lt):
            g = gpkg_geom(b)
            if g is None or g.is_empty: continue
            if lsrs == 4326: g = shapely.transform(g, merc)      # the lakes come in lon/lat, the streams in web mercator
            if g.area < LAKE_MIN: continue
            if not g.is_valid: g = g.buffer(0)
            lakes.append(g.simplify(PRE))
        lc.close()
        shapely.prepare(lakes)
        ltree = STRtree(lakes) if lakes else None
        sc = sqlite3.connect(sp); st = sc.execute('select table_name from gpkg_contents').fetchone()[0]
        n = 0; rows = []
        for b, a in sc.execute('select geom, DSContArea from "%s" where DSContArea >= ?' % st, (THR[9] * 1e6,)):
            g = gpkg_geom(b)
            if g is None or g.is_empty: continue
            if ltree is not None:
                for k in ltree.query(g):
                    if not lakes[k].intersects(g): continue
                    # the lake cut to the reach's own box first: a Great Lake's whole outline against every reach took minutes a region
                    x0, y0, x1, y1 = g.bounds
                    g = g.difference(shapely.clip_by_rect(lakes[k], x0 - 1, y0 - 1, x1 + 1, y1 + 1))
                    if g.is_empty: break
                if g.is_empty: continue
            g = g.simplify(PRE, preserve_topology=False)
            if g.is_empty: continue
            x0, y0, x1, y1 = g.bounds
            rows.append((int(round(a / 1e6)), v, g.wkb, x0, x1, y0, y1)); n += 1
        sc.close()
        for a, vv, gb, x0, x1, y0, y1 in rows:
            cur = c.execute('insert into r(a, vpu, g) values (?,?,?)', (a, vv, gb))
            c.execute('insert into ri values (?,?,?,?,?)', (cur.lastrowid, x0, x1, y0, y1))
        c.execute('insert into done values (?)', (v,)); c.commit()
        os.remove(sp); os.remove(lp)
        print('vpu %d: %d reaches, %d lakes, %.0f s' % (v, n, len(lakes), time.time() - t0), flush=True)

def tiles(work, out):
    c = db(work)
    for z in range(3, 10):
        n = 2 ** z; ts = S / n; tol = ts / 256 * TOL; pad = ts / 256 * 8
        # the kept reaches' extent, in tiles
        x0, x1, y0, y1 = c.execute('select min(minx), max(maxx), min(miny), max(maxy) from ri').fetchone()
        tx0, tx1 = int((x0 + S / 2) // ts), int((x1 + S / 2) // ts); ty0, ty1 = int((S / 2 - y1) // ts), int((S / 2 - y0) // ts)
        cnt = 0; t0 = time.time()
        for tx in range(tx0, tx1 + 1):
            bx0 = -S / 2 + tx * ts; bx1 = bx0 + ts
            for ty in range(ty0, ty1 + 1):
                by1 = S / 2 - ty * ts; by0 = by1 - ts
                bb = box(bx0 - pad, by0 - pad, bx1 + pad, by1 + pad)
                fs = []
                for a, gb in c.execute('select r.a, r.g from ri join r on r.id = ri.id where ri.maxx >= ? and ri.minx <= ? and ri.maxy >= ? and ri.miny <= ? and r.a >= ?',
                                       (bx0 - pad, bx1 + pad, by0 - pad, by1 + pad, THR[z])):
                    g = wkb.loads(gb)
                    if not g.intersects(bb): continue
                    g = g.intersection(bb).simplify(tol, preserve_topology=False)
                    if g.is_empty or g.length < tol: continue
                    fs.append({'geometry': g.wkb, 'properties': {'a': a}})
                if not fs: continue
                data = mapbox_vector_tile.encode([{'name': 'rivers', 'features': fs}],
                                                 default_options={'quantize_bounds': (bx0, by0, bx1, by1), 'extents': 4096, 'y_coord_down': False})
                d = os.path.join(out, str(z), str(tx)); os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, '%d.mvt' % ty), 'wb') as f: f.write(data)
                cnt += 1
        print('z%d: %d tiles, %.0f s' % (z, cnt, time.time() - t0), flush=True)

if __name__ == '__main__':
    if sys.argv[1] == 'extract': extract(sys.argv[2])
    elif sys.argv[1] == 'tiles': tiles(sys.argv[2], sys.argv[3])
