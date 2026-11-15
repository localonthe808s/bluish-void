#!/usr/bin/env python3
"""RIVERS v4: z10-12 IN ONE PMTILES ARCHIVE (2026-11-14). bake_v3.py cut z3-9 (and v3b's z10) as loose {z}/{x}/{y}.mvt files; deeper
zooms that way are hundreds of thousands of files. This cuts z10-12 from the same extract with bake_v3's exact geometry rules (the
reach clipped to the tile + 8 px pad, simplified to 0.15 px at that zoom, no smoothing, lakes already cut out in the extract, layer
"rivers", props a = km2 drained and b = basin from basins.py) and packs them into one PMTiles v3 archive, each tile gzip-compressed
(header tile_compression = GZIP, as _waterbake/nhd_national.py writes nhd_us.pmtiles; protomaps-leaflet reads it over range requests).

  - extract: reaches_full_b.sqlite (EVERY RIVER, reaches down to 9 km2, with basins.py's b column), from
    r2:bluishvoid-archive/bake/river_basin_bake/reaches_full_b.sqlite. The untagged reaches_full.sqlite / reaches.sqlite (floor 100)
    in river_bake2_full/ lack b.
  - z12 only OUTSIDE the lower 48: USGS NHD flowlines take z12 there. A z12 tile wholly inside the union of the 48 states + DC
    (Census cb_2023_us_state_500k, the same list nhd_national.py bakes) is skipped; one touching a border or the coast is written.
  - cut by z7 block (the block's reaches read once, every z10-12 tile inside cut from memory), 4 forked workers; tiles go to
    WORK/v4store.sqlite (resumable: finished blocks are recorded), then 'build' writes the archive in tile-id order.

Commands run (2026-11-14):
    rclone copyto r2:bluishvoid-archive/bake/river_basin_bake/reaches_full_b.sqlite ~/river_bake3/work/reaches_full_b.sqlite --s3-no-check-bucket
    rclone copy r2:bluishvoid-archive/bake/nhd_bake/bounds/ ~/river_bake3/bounds --s3-no-check-bucket
    python3 bake_v4.py test  ~/river_bake3/work ~/river_bake3/bounds/cb_2023_us_state_500k.shp 37/48,37/47,32/53,38/44,31/50   # z7 blocks: NYC, Hudson, Miss. delta, Quebec, Ozarks; sizes only
    python3 bake_v4.py cut   ~/river_bake3/work ~/river_bake3/bounds/cb_2023_us_state_500k.shp
    python3 bake_v4.py build ~/river_bake3/work ~/river_bake3/rivers_z10_12.pmtiles
    rclone copyto ~/river_bake3/rivers_z10_12.pmtiles r2:bluishvoid-bg/rivers/v4/rivers_z10_12.pmtiles --s3-no-check-bucket \
        --header-upload "Content-Type: application/vnd.pmtiles" --header-upload "Cache-Control: public, max-age=31536000, immutable"
Env: BV_THR="10:9,11:9,12:9" (default below) sets the km2 cutoffs; BV_PROCS the worker count.
Same license as v3: NGA TDX-Hydro, CC BY-SA 4.0, via GEOGLOWS v2 (CC BY 4.0).
"""
import gzip, math, os, sqlite3, sys, time
os.environ.setdefault('BV_BASIN', '1')
os.environ.setdefault('BV_DB', 'reaches_full_b.sqlite')
os.environ.setdefault('BV_THR', '10:9,11:9,12:9')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_v3 as V
import shapely
from shapely import wkb
from shapely.geometry import box, shape
from shapely.strtree import STRtree
import mapbox_vector_tile

ZMIN, ZMAX, B = 10, 12, 7
S = V.S; TOL = V.TOL; THR = V.THR
L48 = None   # the lower 48 + DC in web mercator, prepared (set before the workers fork)

def load_l48(shp):
    import shapefile
    from shapely.ops import unary_union
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '_waterbake'))
    from nhd_national import STATES
    names = set(s.replace('_', ' ') for s in STATES)
    rd = shapefile.Reader(shp); ni = [f[0] for f in rd.fields[1:]].index('NAME')
    got = [sr for sr in rd.shapeRecords() if sr.record[ni] in names]
    assert len(got) == len(names), (len(got), len(names))
    U = unary_union([shape(sr.shape.__geo_interface__) for sr in got])
    UM = shapely.transform(U, V.merc); shapely.prepare(UM)
    return UM

def tbox(z, x, y):
    ts = S / 2 ** z; x0 = -S / 2 + x * ts; y1 = S / 2 - y * ts
    return x0, y1 - ts, x0 + ts, y1

def block(args):
    """one z7 block -> [(z, x, y, gz bytes)], plus counts of z12 tiles skipped inside the lower 48"""
    work, bx, by = args
    c = V.db(work); x0, y0, x1, y1 = tbox(B, bx, by); pad = S / 2 ** B / 256 * 8
    amin = min(THR[z] for z in range(ZMIN, ZMAX + 1))
    rows = c.execute('select r.a, r.g, r.b from ri join r on r.id = ri.id where ri.maxx >= ? and ri.minx <= ? and ri.maxy >= ? and ri.miny <= ? and r.a >= ?',
                     (x0 - pad, x1 + pad, y0 - pad, y1 + pad, amin)).fetchall()
    c.close()
    if not rows: return bx, by, [], 0
    A = [r[0] for r in rows]; G = [wkb.loads(r[1]) for r in rows]; Bs = [r[2] or 0 for r in rows]; tree = STRtree(G)
    bb7 = box(x0, y0, x1, y1)
    l48 = 'in' if L48.contains(bb7) else ('out' if not L48.intersects(bb7) else 'edge')
    out = []; skipped = 0
    for z in range(ZMIN, ZMAX + 1):
        k = 2 ** (z - B); ts = S / 2 ** z; tol = ts / 256 * TOL; pd = ts / 256 * 8
        for tx in range(bx * k, bx * k + k):
            for ty in range(by * k, by * k + k):
                tx0, ty0, tx1, ty1 = tbox(z, tx, ty)
                if z == 12 and (l48 == 'in' or (l48 == 'edge' and L48.contains(box(tx0, ty0, tx1, ty1)))):
                    skipped += 1; continue
                bb = box(tx0 - pd, ty0 - pd, tx1 + pd, ty1 + pd); fs = []
                for i in tree.query(bb):
                    if A[i] < THR[z]: continue
                    g = G[i]
                    if not g.intersects(bb): continue
                    g = g.intersection(bb).simplify(tol, preserve_topology=False)
                    if g.is_empty or g.length < tol: continue
                    fs.append({'geometry': g.wkb, 'properties': {'a': A[i], 'b': Bs[i]}})
                if not fs: continue
                data = mapbox_vector_tile.encode([{'name': 'rivers', 'features': fs}],
                                                 default_options={'quantize_bounds': (tx0, ty0, tx1, ty1), 'extents': 4096, 'y_coord_down': False})
                out.append((z, tx, ty, gzip.compress(data)))
    return bx, by, out, skipped

def blocks_all(work):
    c = V.db(work); x0, x1, y0, y1 = c.execute('select min(minx), max(maxx), min(miny), max(maxy) from ri').fetchone(); c.close()
    t = S / 2 ** B
    return [(bx, by) for bx in range(int((x0 + S / 2) // t), int((x1 + S / 2) // t) + 1) for by in range(int((S / 2 - y1) // t), int((S / 2 - y0) // t) + 1)]

def store(work):
    s = sqlite3.connect(os.path.join(work, 'v4store.sqlite'))
    s.execute('create table if not exists t(id integer primary key, z integer, x integer, y integer, d blob)')
    s.execute('create table if not exists done(bx integer, by integer, n integer, skipped integer, primary key(bx, by))')
    return s

def run(work, shp, jobs, keep):
    global L48
    import multiprocessing as mp
    from pmtiles.tile import zxy_to_tileid
    L48 = load_l48(shp)
    # the pool forks FIRST: macOS's system sqlite segfaults in a forked child once the parent has opened a database (2026-11-14,
    # "crashed on child side of fork" in openDatabase -> the pool lost the task and hung), so main touches sqlite only after the fork
    with mp.get_context('fork').Pool(int(os.environ.get('BV_PROCS', '4'))) as pool:
      if callable(jobs): jobs = jobs()
      s = store(work) if keep else None
      if s is not None:
        done = set(s.execute('select bx, by from done').fetchall()); jobs = [j for j in jobs if j not in done]
      t0 = time.time(); nb = 0; tot = {z: 0 for z in range(ZMIN, ZMAX + 1)}; skip = 0; big = (0, None); byt = 0
      if True:
        for bx, by, out, sk in pool.imap_unordered(block, [(work, bx, by) for bx, by in jobs]):
            nb += 1; skip += sk
            for z, x, y, d in out:
                tot[z] += 1; byt += len(d)
                raw = len(gzip.decompress(d))
                if raw > big[0]: big = (raw, '%d/%d/%d' % (z, x, y), len(d))
            if s is not None:
                s.executemany('insert or replace into t values (?,?,?,?,?)', [(zxy_to_tileid(z, x, y), z, x, y, d) for z, x, y, d in out])
                s.execute('insert or replace into done values (?,?,?,?)', (bx, by, len(out), sk)); s.commit()
            if not keep or nb % 25 == 0 or nb == len(jobs):
                print('blocks %d/%d, tiles %s, z12 skipped %d, %.1f MB gz, largest raw %s, %.0f s' % (nb, len(jobs), tot, skip, byt / 1e6, big, time.time() - t0), flush=True)
    print('CUT_DONE %s skipped=%d %.0f s' % (tot, skip, time.time() - t0), flush=True)

def build(work, out):
    from pmtiles.writer import Writer
    from pmtiles.tile import TileType, Compression
    s = store(work); t0 = time.time(); n = 0
    c = V.db(work); x0, x1, y0, y1 = c.execute('select min(minx), max(maxx), min(miny), max(maxy) from ri').fetchone(); c.close()
    lo0, la0 = V_unmerc(x0, y0); lo1, la1 = V_unmerc(x1, y1)
    with open(out, 'wb') as f:
        W = Writer(f)
        for tid, d in s.execute('select id, d from t order by id'):
            W.write_tile(tid, d); n += 1
        W.finalize({'tile_type': TileType.MVT, 'tile_compression': Compression.GZIP, 'min_zoom': ZMIN, 'max_zoom': ZMAX,
                    'min_lon_e7': int(lo0 * 1e7), 'min_lat_e7': int(la0 * 1e7), 'max_lon_e7': int(lo1 * 1e7), 'max_lat_e7': int(la1 * 1e7),
                    'center_zoom': 10, 'center_lon_e7': int(-74e7), 'center_lat_e7': int(41e7)},
                   {'vector_layers': [{'id': 'rivers', 'fields': {'a': 'Number', 'b': 'Number'}, 'minzoom': ZMIN, 'maxzoom': ZMAX}],
                    'attribution': 'NGA TDX-Hydro (CC BY-SA 4.0) via GEOGLOWS v2'})
    print('BUILT %d tiles, %.0f s' % (n, time.time() - t0), flush=True)

def V_unmerc(x, y):
    return math.degrees(x / V.R), math.degrees(2 * math.atan(math.exp(max(min(y, S / 2), -S / 2) / V.R)) - math.pi / 2)

if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'test': run(a[1], a[2], [tuple(int(v) for v in p.split('/')) for p in a[3].split(',')], False)
    elif a[0] == 'cut': run(a[1], a[2], lambda: blocks_all(a[1]), True)
    elif a[0] == 'build': build(a[1], a[2])
