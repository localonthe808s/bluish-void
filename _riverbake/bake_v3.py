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
THR = {3: 30000, 4: 15000, 5: 6000, 6: 2500, 7: 1000, 8: 300, 9: 100, 10: 100}   # km2 drained to be drawn at that tile zoom
# BV_THR="3:10000,4:5000" overrides the cutoffs (read at import, so the block cut's worker processes see it too: 2026-11-07, they did not)
for _kv in filter(None, os.environ.get('BV_THR', '').split(',')):
    _k, _v = _kv.split(':'); THR[int(_k)] = int(_v)
BASIN = os.environ.get('BV_BASIN') == '1'   # 2026-11-08: also write b, where each reach ends up (basins.py tags the extract)
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
    # BV_DB names the database (reaches_full.sqlite for the EVERY RIVER cut, 2026-11-06); BV_FLOOR its smallest reach in km2
    c = sqlite3.connect(os.path.join(work, os.environ.get('BV_DB', 'reaches.sqlite')))
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
        floor = float(os.environ.get('BV_FLOOR', THR[9]))
        for b, a in sc.execute('select geom, DSContArea from "%s" where DSContArea >= ?' % st, (floor * 1e6,)):
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

def tiles(work, out, zmin=3, zmax=9):
    # BV_THR="3:10000,4:5000" overrides the cutoffs for a re-cut (2026-11-06: the continental zooms lowered to show more tributaries)
    c = db(work)
    for z in range(zmin, zmax + 1):
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
                for a, gb, bb2 in c.execute('select r.a, r.g, ' + ('r.b' if BASIN else '0') + ' from ri join r on r.id = ri.id where ri.maxx >= ? and ri.minx <= ? and ri.maxy >= ? and ri.miny <= ? and r.a >= ?',
                                       (bx0 - pad, bx1 + pad, by0 - pad, by1 + pad, THR[z])):
                    g = wkb.loads(gb)
                    if not g.intersects(bb): continue
                    g = g.intersection(bb).simplify(tol, preserve_topology=False)
                    if g.is_empty or g.length < tol: continue
                    fs.append({'geometry': g.wkb, 'properties': dict({'a': a}, **({'b': bb2 or 0} if BASIN else {}))})
                if not fs: continue
                data = mapbox_vector_tile.encode([{'name': 'rivers', 'features': fs}],
                                                 default_options={'quantize_bounds': (bx0, by0, bx1, by1), 'extents': 4096, 'y_coord_down': False})
                d = os.path.join(out, str(z), str(tx)); os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, '%d.mvt' % ty), 'wb') as f: f.write(data)
                cnt += 1
        print('z%d: %d tiles, %.0f s' % (z, cnt, time.time() - t0), flush=True)

def _block(args):
    """one z6 block: its reaches read ONCE, then every tile of zooms zmin..zmax inside it cut from memory (2026-11-07: the per-tile
    database reads re-parsed a long river thousands of times; the 1.1 M-reach EVERY RIVER cut ran ~2 h at z10 that way)"""
    work, out, zmin, zmax, bx, by = args
    c = db(work); B = 6; n = 2 ** B; ts6 = S / n
    x0 = -S / 2 + bx * ts6; x1 = x0 + ts6; y1 = S / 2 - by * ts6; y0 = y1 - ts6
    pad6 = ts6 / 256 * 8
    amin = min(THR[z] for z in range(zmin, zmax + 1))
    rows = c.execute('select r.a, r.g, ' + ('r.b' if BASIN else '0') + ' from ri join r on r.id = ri.id where ri.maxx >= ? and ri.minx <= ? and ri.maxy >= ? and ri.miny <= ? and r.a >= ?',
                     (x0 - pad6, x1 + pad6, y0 - pad6, y1 + pad6, amin)).fetchall()
    c.close()
    if not rows: return 0
    A = [r[0] for r in rows]; G = [wkb.loads(r[1]) for r in rows]; Bs = [r[2] or 0 for r in rows]; tree = STRtree(G); cnt = 0
    for z in range(zmin, zmax + 1):
        k = 2 ** (z - B); ts = S / 2 ** z; tol = ts / 256 * TOL; pad = ts / 256 * 8
        for tx in range(bx * k, bx * k + k):
            for ty in range(by * k, by * k + k):
                tx0 = -S / 2 + tx * ts; tx1 = tx0 + ts; ty1 = S / 2 - ty * ts; ty0 = ty1 - ts
                bb = box(tx0 - pad, ty0 - pad, tx1 + pad, ty1 + pad); fs = []
                for i in tree.query(bb):
                    if A[i] < THR[z]: continue
                    g = G[i]
                    if not g.intersects(bb): continue
                    g = g.intersection(bb).simplify(tol, preserve_topology=False)
                    if g.is_empty or g.length < tol: continue
                    fs.append({'geometry': g.wkb, 'properties': dict({'a': A[i]}, **({'b': Bs[i]} if BASIN else {}))})
                if not fs: continue
                data = mapbox_vector_tile.encode([{'name': 'rivers', 'features': fs}],
                                                 default_options={'quantize_bounds': (tx0, ty0, tx1, ty1), 'extents': 4096, 'y_coord_down': False})
                d = os.path.join(out, str(z), str(tx)); os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, '%d.mvt' % ty), 'wb') as f: f.write(data)
                cnt += 1
    return cnt

def tiles_blocks(work, out, zmin, zmax, procs=4):
    c = db(work); n = 2 ** 6; ts6 = S / n
    x0, x1, y0, y1 = c.execute('select min(minx), max(maxx), min(miny), max(maxy) from ri').fetchone(); c.close()
    jobs = [(work, out, zmin, zmax, bx, by) for bx in range(int((x0 + S / 2) // ts6), int((x1 + S / 2) // ts6) + 1)
            for by in range(int((S / 2 - y1) // ts6), int((S / 2 - y0) // ts6) + 1)]
    import multiprocessing as mp
    t0 = time.time(); done = 0; tot = 0
    with mp.Pool(procs) as pool:
        for k in pool.imap_unordered(_block, jobs):
            done += 1; tot += k
            if done % 25 == 0: print('blocks %d/%d, tiles %d, %.0f s' % (done, len(jobs), tot, time.time() - t0), flush=True)
    print('z%d-%d: %d tiles, %.0f s' % (zmin, zmax, tot, time.time() - t0), flush=True)

if __name__ == '__main__':
    if sys.argv[1] == 'extract': extract(sys.argv[2])
    elif sys.argv[1] == 'blocks': tiles_blocks(sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
    elif sys.argv[1] == 'tiles': tiles(sys.argv[2], sys.argv[3], *[int(a) for a in sys.argv[4:6]])
