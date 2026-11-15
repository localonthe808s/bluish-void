#!/usr/bin/env python3
"""USGS NHD (high resolution) RIVER + STREAM LINES FOR THE LOWER 48, PACKED -- sibling of nhd_national.py (the lakes).
TDX-Hydro rivers stop at z11 in the lower 48; these replace OSM's waterway lines at street zoom (z12-14).

  state NAME   download the state's NHD GeoPackage, read NHDFlowline, cut z12-14 by z11 BLOCK (3 forked workers) into
               WORK/store.sqlite (one row per tile per state), delete the download
  all WORK     every state in nhd_national.STATES (lower 48 + DC); a failed state is logged SKIPPED, rerun picks it up
  build        one PMTiles archive; a tile two states share is decoded and merged (appended), never overwritten

    python3 nhd_flow_national.py state New_York WORK
    python3 nhd_flow_national.py build WORK OUT.pmtiles

Layer "flow". Kept: StreamRiver 460 (46000 / 46003 intermittent / 46006 perennial / 46007 ephemeral), CanalDitch 336, Connector 334.
Dropped: ArtificialPath 558 (runs through lake / wide-river polygons the map already draws), Pipeline 428, Coastline 566,
Underground Conduit 420. Properties: k = perennial | intermittent | ephemeral | canal | connector (StreamRiver without a
persistence code -> perennial), n = GNIS name when present, o = Strahler stream order from NHDFlowlineVAA where the state
has it (partial coverage; absent = unknown, not 'small').
"""
import gzip, math, os, struct, sqlite3, sys, time, zipfile
import multiprocessing as mp
import numpy as np, shapely
from shapely.geometry import box, shape
from shapely.strtree import STRtree
import mapbox_vector_tile
from nhd_national import gpkg_geom, merc, tile_id, fetch, URL, STATES, S, R, TOL

def store(work, name=None):
    # FLOW_STORE names a second store file: another process held a long read on store.sqlite (2026-11-14) and every commit
    # failed "database is locked"; 'merge' folds it back in before the build
    c = sqlite3.connect(os.path.join(work, name or os.environ.get('FLOW_STORE', 'store.sqlite')), timeout=600)
    c.execute('create table if not exists t(id integer, z integer, x integer, y integer, st text, d blob)')
    c.execute('create index if not exists ti on t(id)')
    c.execute('create table if not exists done(st text primary key, shapes integer, tiles integer, secs real)')
    return c

def do_merge(work, other):
    c = store(work, 'store.sqlite'); c.execute('attach ? as b', (os.path.join(work, other),))
    have = {r[0] for r in c.execute('select st from main.done')}
    new = [r[0] for r in c.execute('select st from b.done') if r[0] not in have]
    for st in new:
        c.execute('delete from main.t where st = ?', (st,))
        c.execute('insert into main.t select * from b.t where st = ?', (st,))
        c.execute('insert into main.done select * from b.done where st = ?', (st,)); c.commit()
    print('merged', len(new), 'states from', other, flush=True)

ZMIN, ZMAX, BZ = 12, 14, 11; CZ = int(os.environ.get("FLOW_CZ", 7))   # chunk zoom; 8 = a quarter the memory per fork (Mississippi thrashed at 7 on a loaded machine)
KEEP_FT = (460, 336, 334)
DROP_Z12 = set(os.environ.get('FLOW_DROP_Z12', '').split(',')) - {''}   # e.g. "connector,ephemeral" if a z12 tile runs too big

def kind(ft, fc):
    if ft == 336: return 'canal'
    if ft == 334: return 'connector'
    return {46003: 'intermittent', 46007: 'ephemeral'}.get(fc, 'perennial')

G = []; P = []; TREE = None; RT = None   # the state's lines, inherited by the forked workers

def lines_only(g):
    """2-D (Multi)LineString parts of g, or None."""
    t = g.geom_type
    if t in ('LineString', 'MultiLineString'): return g
    if t == 'GeometryCollection':
        ls = [p for p in g.geoms if p.geom_type in ('LineString', 'MultiLineString')]
        if ls: return shapely.multilinestrings([q for p in ls for q in getattr(p, 'geoms', [p])])
    return None

def env(b):
    """(minx, maxx, miny, maxy) of a GPKG geometry blob: its header envelope, else the parsed bounds"""
    if b[3] >> 1 & 7:
        return struct.unpack(('<' if b[3] & 1 else '>') + '4d', bytes(b[8:40]))
    x0, y0, x1, y1 = gpkg_geom(b).bounds; return x0, x1, y0, y1

def rtree(c):
    """(table, geometry column, pk, rtree table) -- the GPKG's own R-tree; one built here when a state ships without it (Arkansas)"""
    tbl, col = c.execute("select table_name, column_name from gpkg_geometry_columns where lower(table_name) = 'nhdflowline'").fetchone()
    pk = [r[1] for r in c.execute('pragma table_info("%s")' % tbl) if r[5] == 1][0]   # fid in New York, OBJECTID in Arizona
    names = {r[0].lower(): r[0] for r in c.execute("select name from sqlite_master")}
    rt = names.get(('rtree_%s_%s' % (tbl, col)).lower())
    if rt is None:
        rt = 'bv_rtree'
        if rt not in names:
            c.execute('create virtual table bv_rtree using rtree(id, minx, maxx, miny, maxy)')
            for ft in KEEP_FT:
                c.executemany('insert into bv_rtree values (?,?,?,?,?)', ((i, *env(b)) for i, b in
                              c.execute('select "%s", "%s" from "%s" where ftype = ? and "%s" is not null' % (pk, col, tbl, col), (ft,))))
            c.commit()
    return tbl, col, pk, rt

def load(c, so, lon0, lat0, lon1, lat1):
    """the kept lines whose bbox meets this lon/lat window (the GPKG's R-tree), into G / P"""
    tbl, col, pk, rt = RT
    q = ('select f."%s", f.ftype, f.fcode, f.gnis_name, f.permanent_identifier from "%s" f join "%s" r on r.id = f."%s" '
         'where r.maxx >= ? and r.minx <= ? and r.maxy >= ? and r.miny <= ? and f.ftype in (%s)') % (col, tbl, rt, pk, ','.join(map(str, KEEP_FT)))
    for b, ft, fc, nm, pid in c.execute(q, (lon0, lon1, lat0, lat1)):
        if b is None: continue
        try:
            g = gpkg_geom(b)
            if g is None or g.is_empty: continue
            g = lines_only(shapely.transform(shapely.force_2d(g), merc))   # Z/M dropped before projecting
            if g is None or g.is_empty: continue
        except Exception: continue
        o = so.get(pid)
        G.append(g); P.append({'k': kind(ft, fc), **({'n': nm} if nm else {}), **({'o': int(o)} if o else {})})

def m2ll(x, y):
    return x / R * 180 / math.pi, math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)

def block(bxy):
    bx, by = bxy; ts = S / 2 ** BZ; pad = ts / 256 * 4
    x0 = -S / 2 + bx * ts; y1 = S / 2 - by * ts
    bb = box(x0 - pad, y1 - ts - pad, x0 + ts + pad, y1 + pad)
    idx = TREE.query(bb, predicate='intersects')
    if not len(idx): return []
    lg = shapely.intersection(np.array([G[i] for i in idx], dtype=object), bb)
    lp = [P[i] for i in idx]; out = []
    for z in range(ZMIN, ZMAX + 1):
        k = 2 ** (z - BZ); t = S / 2 ** z; tol = t / 256 * TOL; tp = t / 256 * 4
        zg = shapely.simplify(lg, tol, preserve_topology=False)   # once per zoom per block, then clip each tile
        keep = [i for i in range(len(zg)) if not shapely.is_empty(zg[i]) and not (z == 12 and lp[i]['k'] in DROP_Z12)]
        if not keep: continue
        zg = zg[keep]; zp = [lp[i] for i in keep]; lt = STRtree(zg)
        for tx in range(bx * k, bx * k + k):
            for ty in range(by * k, by * k + k):
                tx0 = -S / 2 + tx * t; ty1 = S / 2 - ty * t; tb = box(tx0 - tp, ty1 - t - tp, tx0 + t + tp, ty1 + tp)
                j = lt.query(tb, predicate='intersects')
                if not len(j): continue
                cg = shapely.intersection(zg[j], tb); fs = []
                for g, jj in zip(cg, j):
                    g = lines_only(g)
                    if g is None or g.is_empty or g.length < tol: continue
                    fs.append({'geometry': g.wkb, 'properties': zp[jj]})
                if fs:
                    out.append((z, tx, ty, mapbox_vector_tile.encode([{'name': 'flow', 'features': fs}],
                                default_options={'quantize_bounds': (tx0, ty1 - t, tx0 + t, ty1), 'extents': 4096, 'y_coord_down': False})))
    return out

def do_state(name, work):
    """the state is read one z7 CHUNK at a time (64 z11 blocks; lines found through the GPKG R-tree): Arizona whole thrashed
    5.7 GB of swap on the 8 GB machine. Each z11 block belongs to exactly one chunk, so nothing is cut twice."""
    global TREE
    c = store(work)
    if c.execute('select 1 from done where st = ?', (name,)).fetchone(): print(name, 'done already', flush=True); return
    c.execute('delete from t where st = ?', (name,)); c.commit()   # a half-written state from a killed run
    t0 = time.time(); zp = os.path.join(work, 'src', name + '.zip'); os.makedirs(os.path.dirname(zp), exist_ok=True)
    fetch(URL % name, zp); t1 = time.time()
    with zipfile.ZipFile(zp) as zf:
        gp = [n for n in zf.namelist() if n.endswith('.gpkg')][0]; zf.extract(gp, os.path.join(work, 'src'))
    gpath = os.path.join(work, 'src', gp); os.remove(zp)
    g = sqlite3.connect(gpath)
    if not g.execute("select 1 from gpkg_geometry_columns where lower(table_name) = 'nhdflowline'").fetchone():
        g.close(); os.remove(gpath); c.execute('insert into done values (?,?,?,?)', (name, 0, 0, time.time() - t0)); c.commit(); return
    try:   # NHDFlowlineVAA carries a Strahler order on part of the network (New York: 21 % of flowlines); o only where it is >= 1
        so = {pid: o for pid, o in g.execute('select permanent_identifier, streamorder from NHDFlowlineVAA where streamorder >= 1')}
    except sqlite3.Error: so = {}
    global RT; RT = rtree(g)
    lo0, lo1, la0, la1 = g.execute('select min(minx), max(maxx), min(miny), max(maxy) from "%s"' % RT[3]).fetchone()
    (X0, Y1), (X1, Y0) = merc(np.array([[lo0, la1]])).tolist()[0], merc(np.array([[lo1, la0]])).tolist()[0]
    ts = S / 2 ** BZ; CK = 2 ** (BZ - CZ); n = nl = nb = 0
    bxr = range(int((X0 + S / 2) // ts), int((X1 + S / 2) // ts) + 1); byr = range(int((S / 2 - Y1) // ts), int((S / 2 - Y0) // ts) + 1)
    chunks = sorted({(bx // CK, by // CK) for bx in bxr for by in byr})
    for cx, cy in chunks:
        tc = S / 2 ** CZ; pad = ts / 256 * 8
        mx0 = -S / 2 + cx * tc - pad; mx1 = mx0 + tc + 2 * pad; my1 = S / 2 - cy * tc + pad; my0 = my1 - tc - 2 * pad
        (l0, a0), (l1, a1) = m2ll(mx0, my0), m2ll(mx1, my1)
        G.clear(); P.clear(); load(g, so, l0, a0, l1, a1)
        if not G: continue
        TREE = STRtree(G); nl += len(G)
        blocks = [(bx, by) for bx in range(cx * CK, cx * CK + CK) if bx in bxr for by in range(cy * CK, cy * CK + CK) if by in byr
                  if len(TREE.query(box(-S / 2 + bx * ts, S / 2 - (by + 1) * ts, -S / 2 + (bx + 1) * ts, S / 2 - by * ts)))]
        nb += len(blocks)
        with mp.get_context('fork').Pool(int(os.environ.get('FLOW_WORKERS', 3))) as pool:
            for res in pool.imap_unordered(block, blocks, chunksize=2):
                c.executemany('insert into t values (?,?,?,?,?,?)', [(tile_id(z, x, y), z, x, y, name, d) for z, x, y, d in res]); n += len(res)
        c.commit(); TREE = None
    G.clear(); P.clear(); g.close(); os.remove(gpath)
    c.execute('insert into done values (?,?,?,?)', (name, nl, n, time.time() - t0)); c.commit()
    print('%s: %d lines (chunk-loaded), %d tiles, %d blocks, %d chunks, %.0f s (download %.0f, cut %.0f)' %
          (name, nl, n, nb, len(chunks), time.time() - t0, t1 - t0, time.time() - t1), flush=True)

def do_build(work, out):
    from pmtiles.writer import Writer
    from pmtiles.tile import TileType, Compression
    c = store(work); n = merged = 0; t0 = time.time()
    with open(out, 'wb') as f:
        W = Writer(f); cur = None; rows = []
        def flush(rows):
            nonlocal n, merged
            if len(rows) == 1: data = rows[0][4]
            else:
                feats = []
                for r in rows:
                    d = mapbox_vector_tile.decode(r[4], default_options={'y_coord_down': False})
                    feats += [{'geometry': shape(ft['geometry']).wkb, 'properties': ft['properties']} for ft in d.get('flow', {}).get('features', [])]
                data = mapbox_vector_tile.encode([{'name': 'flow', 'features': feats}], default_options={'quantize_bounds': (0, 0, 4096, 4096), 'extents': 4096, 'y_coord_down': False})
                merged += 1
            W.write_tile(rows[0][0], gzip.compress(data)); n += 1
        for row in c.execute('select id, z, x, y, d from t order by id'):
            if cur is not None and row[0] != cur: flush(rows); rows = []
            cur = row[0]; rows.append(row)
        if rows: flush(rows)
        W.finalize({'tile_type': TileType.MVT, 'tile_compression': Compression.GZIP, 'min_zoom': ZMIN, 'max_zoom': ZMAX,
                    'min_lon_e7': int(-125e7), 'min_lat_e7': int(24e7), 'max_lon_e7': int(-66e7), 'max_lat_e7': int(50e7),
                    'center_zoom': 12, 'center_lon_e7': int(-74e7), 'center_lat_e7': int(41e7)},
                   {'vector_layers': [{'id': 'flow', 'fields': {'k': 'String', 'n': 'String', 'o': 'Number'}, 'minzoom': ZMIN, 'maxzoom': ZMAX}],
                    'attribution': 'USGS National Hydrography Dataset (public domain)'})
    print('built %d tiles (%d merged across a state line), %.0f s' % (n, merged, time.time() - t0), flush=True)

if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'state': do_state(a[1], a[2])
    elif a[0] == 'all':
        for s in STATES:
            try: do_state(s, a[1])
            except Exception as e: print('SKIPPED', s, e, flush=True)
            G.clear(); P.clear()
    elif a[0] == 'build': do_build(a[1], a[2])
    elif a[0] == 'merge': do_merge(a[1], a[2])
