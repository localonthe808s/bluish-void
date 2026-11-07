#!/usr/bin/env python3
"""USGS NHD LAKES FOR THE LOWER 48, PACKED (user 2026-11-07: "do all 48 states packed"). bake_nhd.py did New York as 274,857 loose tiles
(z15 alone 55 min, one tile at a time); the country that way is ~15 M files -- days of uploads and ~$65 in R2 writes. This:

  state NAME   download the state's NHD GeoPackage, cut z11-15 by z11 BLOCK (each block's shapes clipped once, every sub-tile cut from
               that small set; 3 forked workers) into WORK/store.sqlite (one row per tile per state), delete the download
  build        one PMTiles archive: a tile two states share is decoded and merged, not overwritten; plus cover.json
  cover        just the cover: per z9 block, all of it inside the baked states ("f") or a 256-bit mask of its z13 cells ("p")

    python3 nhd_national.py state New_York WORK
    python3 nhd_national.py build WORK OUT.pmtiles COVER.json STATES.shp
Same layer and filters as bake_nhd.py (layer "water", t = lake | reservoir | estuary | river | canal | rapids, n = GNIS name).
"""
import gzip, json, math, os, sqlite3, sys, time, urllib.request, zipfile
import multiprocessing as mp
import numpy as np, shapely
from shapely import wkb
from shapely.geometry import box, shape
from shapely.strtree import STRtree
import mapbox_vector_tile

KEEP_WB = {390: 'lake', 436: 'reservoir', 493: 'estuary'}
KEEP_AR = {460: 'river', 336: 'canal', 431: 'rapids'}
R = 6378137.0; S = 2 * math.pi * R; TOL = 0.15; ZMIN, ZMAX, BZ = 11, 15, 11
URL = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/State/GPKG/NHD_H_%s_State_GPKG.zip'
UA = {'User-Agent': 'bluishvoid.com water bake'}
STATES = ['Alabama', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware', 'District_of_Columbia', 'Florida', 'Georgia',
          'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts', 'Michigan', 'Minnesota',
          'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New_Hampshire', 'New_Jersey', 'New_Mexico', 'New_York', 'North_Carolina',
          'North_Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode_Island', 'South_Carolina', 'South_Dakota', 'Tennessee', 'Texas',
          'Utah', 'Vermont', 'Virginia', 'Washington', 'West_Virginia', 'Wisconsin', 'Wyoming']

def gpkg_geom(b):
    flags = b[3]; env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    return wkb.loads(bytes(b[8 + env:]))

def merc(xy):
    lon = xy[:, 0]; lat = np.clip(xy[:, 1], -85, 85)
    return np.column_stack([np.radians(lon) * R, np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * R])

def tile_id(z, x, y):
    from pmtiles.tile import zxy_to_tileid
    return zxy_to_tileid(z, x, y)

G = []; P = []; TREE = None   # the state's shapes, inherited by the forked workers

def load(path):
    c = sqlite3.connect(path)
    for tbl, keep in (('NHDWaterbody', KEEP_WB), ('NHDArea', KEEP_AR)):
        row = c.execute("select column_name from gpkg_geometry_columns where lower(table_name) = lower(?)", (tbl,)).fetchone()
        if not row: continue
        q = 'select "%s", ftype, gnis_name from "%s" where ftype in (%s)' % (row[0], tbl, ','.join(str(k) for k in keep))
        for b, ft, nm in c.execute(q):
            if b is None: continue
            try:
                g = gpkg_geom(b)
                if g is None or g.is_empty: continue
                g = shapely.force_2d(shapely.transform(g, merc))
                if not g.is_valid: g = g.buffer(0)
                if g.is_empty: continue
            except Exception: continue
            G.append(g); P.append({'t': keep[ft], **({'n': nm} if nm else {})})
    c.close()

def block(bxy):
    bx, by = bxy; ts = S / 2 ** BZ; pad = ts / 256 * 4
    x0 = -S / 2 + bx * ts; y1 = S / 2 - by * ts
    bb = box(x0 - pad, y1 - ts - pad, x0 + ts + pad, y1 + pad)
    loc = []
    for i in TREE.query(bb):
        g = G[i]
        if not g.intersects(bb): continue
        g = g.intersection(bb)
        if not g.is_empty: loc.append((g, P[i]))
    if not loc: return []
    lt = STRtree([g for g, _ in loc]); out = []
    for z in range(ZMIN, ZMAX + 1):
        k = 2 ** (z - BZ); t = S / 2 ** z; tol = t / 256 * TOL; tp = t / 256 * 4
        for tx in range(bx * k, bx * k + k):
            for ty in range(by * k, by * k + k):
                tx0 = -S / 2 + tx * t; ty1 = S / 2 - ty * t; tb = box(tx0 - tp, ty1 - t - tp, tx0 + t + tp, ty1 + tp); fs = []
                for j in lt.query(tb):
                    g, pr = loc[j]
                    if not g.intersects(tb): continue
                    g = g.intersection(tb).simplify(tol, preserve_topology=True)
                    if g.is_empty or g.area < tol * tol * 4: continue
                    fs.append({'geometry': g.wkb, 'properties': pr})
                if fs:
                    out.append((z, tx, ty, mapbox_vector_tile.encode([{'name': 'water', 'features': fs}],
                                default_options={'quantize_bounds': (tx0, ty1 - t, tx0 + t, ty1), 'extents': 4096, 'y_coord_down': False})))
    return out

def store(work):
    c = sqlite3.connect(os.path.join(work, 'store.sqlite'))
    c.execute('create table if not exists t(id integer, z integer, x integer, y integer, st text, d blob)')
    c.execute('create index if not exists ti on t(id)')
    c.execute('create table if not exists done(st text primary key, shapes integer, tiles integer, secs real)')
    return c

def fetch(url, path):
    if os.path.exists(path): return
    for attempt in range(6):   # USGS resets a connection now and then (Missouri, 2026-11-07, killed the whole run): retry with backoff
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r, open(path + '.part', 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    f.write(b)
            os.replace(path + '.part', path); return
        except Exception as e:
            print('download retry', attempt + 1, os.path.basename(path), e, flush=True); time.sleep(15 * (attempt + 1))
    raise RuntimeError('download failed: ' + url)

def do_state(name, work):
    global TREE
    c = store(work)
    if c.execute('select 1 from done where st = ?', (name,)).fetchone(): print(name, 'done already'); return
    t0 = time.time(); zp = os.path.join(work, 'src', name + '.zip'); os.makedirs(os.path.dirname(zp), exist_ok=True)
    fetch(URL % name, zp)
    with zipfile.ZipFile(zp) as zf:
        gp = [n for n in zf.namelist() if n.endswith('.gpkg')][0]; zf.extract(gp, os.path.join(work, 'src'))
    gpath = os.path.join(work, 'src', gp); os.remove(zp)
    load(gpath); os.remove(gpath)
    if not G: c.execute('insert into done values (?,?,?,?)', (name, 0, 0, time.time() - t0)); c.commit(); return
    TREE = STRtree(G)
    x0, y0, x1, y1 = shapely.total_bounds(G); ts = S / 2 ** BZ
    blocks = [(bx, by) for bx in range(int((x0 + S / 2) // ts), int((x1 + S / 2) // ts) + 1)
              for by in range(int((S / 2 - y1) // ts), int((S / 2 - y0) // ts) + 1)
              if len(TREE.query(box(-S / 2 + bx * ts, S / 2 - (by + 1) * ts, -S / 2 + (bx + 1) * ts, S / 2 - by * ts)))]
    n = 0
    with mp.get_context('fork').Pool(3) as pool:
        for res in pool.imap_unordered(block, blocks, chunksize=4):
            c.executemany('insert into t values (?,?,?,?,?,?)', [(tile_id(z, x, y), z, x, y, name, d) for z, x, y, d in res]); n += len(res)
    c.execute('insert into done values (?,?,?,?)', (name, len(G), n, time.time() - t0)); c.commit()
    print('%s: %d shapes, %d tiles, %d blocks, %.0f s' % (name, len(G), n, len(blocks), time.time() - t0), flush=True)

def do_build(work, out, cover_out, shp):
    from pmtiles.writer import Writer
    from pmtiles.tile import TileType, Compression
    c = store(work); states = [r[0] for r in c.execute('select st from done')]; n = merged = 0; t0 = time.time()
    with open(out, 'wb') as f:
        W = Writer(f); cur = None; rows = []
        def flush(rows):
            nonlocal n, merged
            if len(rows) == 1: data = rows[0][4]
            else:
                feats = []
                for r in rows:
                    d = mapbox_vector_tile.decode(r[4], default_options={'y_coord_down': False})
                    feats += [{'geometry': shape(ft['geometry']).wkb, 'properties': ft['properties']} for ft in d.get('water', {}).get('features', [])]
                data = mapbox_vector_tile.encode([{'name': 'water', 'features': feats}], default_options={'quantize_bounds': (0, 0, 4096, 4096), 'extents': 4096, 'y_coord_down': False})
                merged += 1
            W.write_tile(rows[0][0], gzip.compress(data)); n += 1
        for row in c.execute('select id, z, x, y, d from t order by id'):
            if cur is not None and row[0] != cur: flush(rows); rows = []
            cur = row[0]; rows.append(row)
        if rows: flush(rows)
        W.finalize({'tile_type': TileType.MVT, 'tile_compression': Compression.GZIP, 'min_zoom': ZMIN, 'max_zoom': ZMAX,
                    'min_lon_e7': int(-125e7), 'min_lat_e7': int(24e7), 'max_lon_e7': int(-66e7), 'max_lat_e7': int(50e7),
                    'center_zoom': 12, 'center_lon_e7': int(-74e7), 'center_lat_e7': int(41e7)},
                   {'vector_layers': [{'id': 'water', 'fields': {'t': 'String', 'n': 'String'}, 'minzoom': ZMIN, 'maxzoom': ZMAX}],
                    'attribution': 'USGS National Hydrography Dataset (public domain)'})
    print('built %d tiles (%d merged across a state line), %.0f s' % (n, merged, time.time() - t0), flush=True)
    do_cover(states, cover_out, shp)

def do_cover(states, out, shp):
    import shapefile
    from shapely.ops import unary_union
    names = set(s.replace('_', ' ') for s in states)
    rd = shapefile.Reader(shp); ni = [f[0] for f in rd.fields[1:]].index('NAME')
    U = unary_union([shape(sr.shape.__geo_interface__) for sr in rd.shapeRecords() if sr.record[ni] in names])
    UM = shapely.transform(U, merc); shapely.prepare(UM)
    full, part = [], {}; t9 = S / 2 ** 9; t13 = S / 2 ** 13
    x0, y0, x1, y1 = UM.bounds
    for bx in range(int((x0 + S / 2) // t9), int((x1 + S / 2) // t9) + 1):
        for by in range(int((S / 2 - y1) // t9), int((S / 2 - y0) // t9) + 1):
            bb = box(-S / 2 + bx * t9, S / 2 - (by + 1) * t9, -S / 2 + (bx + 1) * t9, S / 2 - by * t9)
            if not UM.intersects(bb): continue
            if UM.contains(bb): full.append('%d/%d' % (bx, by)); continue
            bits = 0
            for i in range(16):
                for j in range(16):
                    cx = -S / 2 + (bx * 16 + i) * t13; cy = S / 2 - (by * 16 + j) * t13
                    if UM.contains(box(cx, cy - t13, cx + t13, cy)): bits |= 1 << (j * 16 + i)
            if bits: part['%d/%d' % (bx, by)] = '%064x' % bits
    json.dump({'v': 2, 'states': sorted(names), 'f': full, 'p': part}, open(out, 'w'), separators=(',', ':'))
    print('cover: %d full z9 blocks, %d partial' % (len(full), len(part)), flush=True)

if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'state': do_state(a[1], a[2])
    elif a[0] == 'all':
        for s in STATES:
            try: do_state(s, a[1])
            except Exception as e: print('SKIPPED', s, e, flush=True)   # one state failing no longer ends the run; rerun 'all' picks it up
            G.clear(); P.clear()
    elif a[0] == 'build': do_build(a[1], a[2], a[3], a[4])
    elif a[0] == 'cover': do_cover(a[1].split(','), a[2], a[3])
