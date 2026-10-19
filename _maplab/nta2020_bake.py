"""NYC'S OFFICIAL NEIGHBORHOODS FOR THE NATIONAL MAP (2026-10-19).

LOCAL names the neighborhood the place stands in ("PARK SLOPE · BROOKLYN"). Outside New York that comes from
OpenStreetMap by the place's point; inside the five boroughs it is the city's own 2020 Neighborhood Tabulation Areas
(NYC Department of City Planning, NYC Open Data 9nt8-h7nd), found by point-in-polygon, with the street-tree reading
THE CITY's NYC STREET TREES card gives a neighborhood (trees a census block, its rank, the most common species) --
recounted here for the 2020 areas, since trees/nta.json is keyed to the 2010 ones.

Input:  the NTAs as GeoJSON   https://data.cityofnewyork.us/resource/9nt8-h7nd.geojson?$limit=1000
        the 2015 Street Tree Census as CSV
          https://data.cityofnewyork.us/resource/uvpi-gqnh.csv?$select=tree_id,latitude,longitude,status,health,spc_common,spc_latin,block_id&$limit=800000&$order=tree_id
        trees/index.json (its species list: the names THE CITY's card uses)
Output: city_nta2020.json  {"a": [[code, name, borough, type, live trees, blocks, good share, [top species, ...], bbox, polys], ...],
                            "median": trees a block, "src": ...}
          type: the city's NTA type (0 residential; 5 rikers, 6 cemetery, 7 airport, 8 park, 9 other special areas)
          bbox: [w, s, e, n]; polys: [[ring, ...], ...], rings of [lon, lat], simplified ~3 m, rounded to 1e-5
          the ranking (median, rank) uses residential areas with 30 or more blocks, as THE CITY's does

  python3 _maplab/nta2020_bake.py nta2020.geojson census.csv trees/index.json city_nta2020.json
"""
import csv, json, sys
from shapely.geometry import shape, Point, mapping
from shapely.strtree import STRtree

src_nta, src_csv, src_ix, out = sys.argv[1:5]
ix = json.load(open(src_ix))
sp_ix = {(c, l): i for i, (c, l) in enumerate(ix['sp'])}
feats = json.load(open(src_nta))['features']
geoms = [shape(f['geometry']) for f in feats]
tree = STRtree(geoms)
rows = [[f['properties']['nta2020'], f['properties']['ntaname'], f['properties']['boroname'], int(f['properties'].get('ntatype') or 0), 0, set(), 0, {}]
        for f in feats]
n = miss = 0
with open(src_csv, newline='') as fh:
    for r in csv.DictReader(fh):
        try:
            la, lo = float(r['latitude']), float(r['longitude'])
        except (TypeError, ValueError):
            continue
        st, h = (r.get('status') or '').lower(), (r.get('health') or '').lower()
        hs = 5 if st == 'stump' else 4 if st == 'dead' else {'good': 0, 'fair': 1, 'poor': 2}.get(h, 3)
        if hs > 3:
            continue
        p = Point(lo, la)
        hit = [i for i in tree.query(p) if geoms[i].contains(p)]
        if not hit:
            miss += 1
            continue
        R = rows[hit[0]]
        R[4] += 1; R[5].add(r.get('block_id')); R[6] += 1 if hs == 0 else 0
        s = sp_ix.get(((r.get('spc_common') or '').strip(), (r.get('spc_latin') or '').strip()), -1)
        if s >= 0:
            R[7][s] = R[7].get(s, 0) + 1
        n += 1
rnd = lambda c: [round(c[0], 5), round(c[1], 5)]
outrows = []
for R, g in zip(rows, geoms):
    s = g.simplify(0.00003, preserve_topology=True)
    m = mapping(s)
    ps = [m['coordinates']] if m['type'] == 'Polygon' else list(m['coordinates'])
    polys = [[[rnd(c) for c in ring] for ring in p] for p in ps]
    top = [ix['sp'][k][0] for k, v in sorted(R[7].items(), key=lambda kv: -kv[1])[:3]]
    b = g.bounds
    outrows.append([R[0], R[1], R[2], R[3], R[4], len(R[5]), round(R[6] / R[4], 3) if R[4] else 0, top,
                    [round(b[0], 4), round(b[1], 4), round(b[2], 4), round(b[3], 4)], polys])
per = sorted(r[4] / r[5] for r in outrows if r[3] == 0 and r[5] >= 30)
with open(out, 'w') as f:
    json.dump({'a': outrows, 'median': round(per[len(per) // 2], 2),
               'src': '2020 Neighborhood Tabulation Areas (NYC Open Data 9nt8-h7nd); 2015 Street Tree Census (uvpi-gqnh)'}, f, separators=(',', ':'))
print(len(outrows), 'areas,', n, 'live trees placed,', miss, 'outside every area; median', round(per[len(per) // 2], 2), 'trees a block')
