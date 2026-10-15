"""THE STREET TREES, BAKED INTO TILES (2026-10-15).

The city map used to ask NYC Open Data for the trees in view on every zoom: 2,000 rows a box and 6,000 held, so a
dense neighbourhood came back a few dots a block, and nothing showed until the closest zoom. This bakes the whole
2015 Street Tree Census (683,788 rows) into 0.01-degree tiles the page fetches from its own origin, so every tree in
view draws, from a mid zoom down.

Input: the census as CSV (tree_id, latitude, longitude, tree_dbh, status, health, spc_common, spc_latin), e.g.
  https://data.cityofnewyork.us/resource/uvpi-gqnh.csv?$select=tree_id,latitude,longitude,tree_dbh,status,health,spc_common,spc_latin&$limit=800000&$order=tree_id
Output: trees/index.json  {"cell":0.01, "sp":[[common, latin], ...], "tiles":[key, ...], "n": count}
        trees/t_<lat*100>_<lon*100>.json  [[tree_id, dlat, dlon, dbh, sp, hs], ...]
          dlat/dlon: metres-ish ints, (lat - tile south) * 1e5 and (lon - tile west) * 1e5
          sp: index into index.json's sp (-1 = unidentified)
          hs: 0 good, 1 fair, 2 poor, 3 alive with no health recorded, 4 dead, 5 stump
The full record (address, steward, sidewalk, problems) is still asked of the city by tree_id when a tree is tapped.

  python3 _maplab/trees_bake.py census.csv trees/
"""
import csv, json, math, os, sys

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
CELL = 0.01
sp_ix, sp = {}, []
tiles = {}
n = 0
with open(src, newline='') as f:
    for r in csv.DictReader(f):
        try:
            la, lo = float(r['latitude']), float(r['longitude'])
        except (TypeError, ValueError):
            continue
        ty, tx = math.floor(la / CELL), math.floor(lo / CELL)
        com, lat_n = (r.get('spc_common') or '').strip(), (r.get('spc_latin') or '').strip()
        if com or lat_n:
            k = (com, lat_n)
            if k not in sp_ix:
                sp_ix[k] = len(sp); sp.append([com, lat_n])
            s = sp_ix[k]
        else:
            s = -1
        st, h = (r.get('status') or '').lower(), (r.get('health') or '').lower()
        hs = 5 if st == 'stump' else 4 if st == 'dead' else {'good': 0, 'fair': 1, 'poor': 2}.get(h, 3)
        try:
            dbh = int(float(r.get('tree_dbh') or 0))
        except ValueError:
            dbh = 0
        tiles.setdefault((ty, tx), []).append([int(r['tree_id']), round((la - ty * CELL) * 1e5), round((lo - tx * CELL) * 1e5), min(dbh, 255), s, hs])
        n += 1
keys = []
for (ty, tx), rows in tiles.items():
    key = '%d_%d' % (ty, tx)
    keys.append(key)
    with open(os.path.join(out, 't_' + key + '.json'), 'w') as f:
        json.dump(rows, f, separators=(',', ':'))
with open(os.path.join(out, 'index.json'), 'w') as f:
    json.dump({'cell': CELL, 'sp': sp, 'tiles': sorted(keys), 'n': n, 'src': '2015 Street Tree Census, NYC Open Data uvpi-gqnh'}, f, separators=(',', ':'))
print(n, 'trees,', len(keys), 'tiles,', len(sp), 'species')
