#!/usr/bin/env python3
"""MINERALS (user 2026-11-07: "can we add deposits and oil reservoirs to geology?" -> "yes build 1 and 2"). The USGS Mineral Resources
Data System (MRDS, public domain, https://mrdata.usgs.gov/mrds/mrds-csv.zip, ~304k mines, prospects and occurrences worldwide, 267k in the
US) as one PMTiles archive for THE ROCK's MINERALS switch.

Each point: id (dep_id, for the USGS page), n (site name), c (up to three commodities), g (group, the color), s (status), y (production
years when known). Producers show from z3, past producers z5, prospects z7, occurrences/unknown z8; sand, gravel, stone and other bulk
industrial sites two zooms later -- the continent view is the working mines, not 300k dots.

    python3 mrds_bake.py mrds.csv out.geojsons && tippecanoe ... (see build line at the bottom)
"""
import csv, json, sys
GROUP = [
    ('P', ['gold', 'silver', 'platinum', 'palladium', 'pgm']),
    ('B', ['copper', 'lead', 'zinc', 'nickel', 'molybdenum', 'cobalt', 'mercury', 'cadmium', 'bismuth', 'arsenic']),
    ('F', ['iron', 'manganese', 'chromium', 'tungsten', 'vanadium', 'titanium', 'aluminum', 'magnesium', 'magnesite']),
    ('C', ['lithium', 'ree', 'rare earth', 'beryllium', 'tin', 'tantalum', 'niobium', 'columbium', 'antimony', 'gallium', 'germanium', 'indium', 'tellurium', 'graphite', 'cesium', 'scandium', 'zirconium', 'yttrium', 'hafnium', 'rhenium', 'selenium', 'fluorine', 'fluorite', 'barium', 'barite']),
    ('E', ['uranium', 'thorium', 'coal', 'geothermal', 'oil', 'gas', 'lignite', 'peat', 'helium']),
    ('G', ['gemstone', 'diamond', 'gem', 'turquoise', 'opal', 'garnet', 'jade', 'quartz crystal']),
    ('I', ['sand', 'gravel', 'stone', 'clay', 'limestone', 'granite', 'marble', 'gypsum', 'anhydrite', 'salt', 'halite', 'potash', 'potassium', 'phosphate', 'phosphorus', 'feldspar', 'mica', 'talc', 'soapstone', 'diatomite', 'pumice', 'perlite', 'bentonite', 'kaolin', 'silica', 'dolomite', 'slate', 'flagstone', 'volcanic', 'boron', 'borate', 'sulfur', 'calcium', 'kyanite', 'vermiculite', 'zeolite', 'asbestos', 'cement', 'shale', 'trona', 'sodium', 'iodine', 'bromine', 'nitrate', 'wollastonite', 'olivine', 'quartz', 'sandstone', 'basalt', 'traprock', 'cinder', 'scoria', 'lime', 'marl', 'chalk', 'aggregate', 'abrasive', 'emery', 'garnet', 'corundum', 'pyrophyllite', 'sillimanite', 'andalusite', 'nepheline', 'fire clay', 'fuller', 'ball clay', 'common clay', 'shell', 'caliche', 'gilsonite', 'asphalt']),
]
BULK = ['sand and gravel', 'stone', 'gravel', 'sand', 'clay', 'limestone', 'granite', 'common clay', 'crushed', 'dimension']
STATUS = {'Producer': 'P', 'Past Producer': 'X', 'Prospect': 'R', 'Occurrence': 'O', 'Plant': 'L', 'Unknown': 'U'}
MINZ = {'P': 3, 'L': 5, 'X': 5, 'R': 7, 'O': 8, 'U': 8}
def group(c):
    c = c.lower()
    for g, keys in GROUP:
        if any(k in c for k in keys): return g
    return 'O'
RANK = {'P': 5, 'L': 4, 'X': 3, 'R': 2, 'O': 1, 'U': 0}
GRID_PX = {3: 26, 4: 26, 5: 26, 6: 26, 7: 20, 8: 20, 9: 15, 10: 15, 11: 12}   # px per cell by zoom: sparse when zoomed out, the most important first
def merc(lo, la):
    import math
    x = (lo + 180) / 360; y = (1 - math.log(math.tan(math.radians(la)) + 1 / math.cos(math.radians(la))) / math.pi) / 2
    return x, min(max(y, 0), 1)
def declutter(P):
    """minzoom per point: the first zoom where it wins its 14 px cell (or joins a free one), never before its status allows; DECLUTTER
    (2026-11-07, the first cut blanketed the West at z6: 42k producers and 129k past producers all showed by z5)"""
    order = sorted(range(len(P)), key=lambda i: -P[i]['score'])
    mz = [None] * len(P)
    for z in range(3, 12):
        cell = 256 * 2 ** z / GRID_PX[z]; occ = set()
        for i in range(len(P)):
            if mz[i] is not None: occ.add((int(P[i]['x'] * cell), int(P[i]['y'] * cell)))
        for i in order:
            if mz[i] is not None or P[i]['allow'] > z: continue
            k = (int(P[i]['x'] * cell), int(P[i]['y'] * cell))
            if k in occ: continue
            occ.add(k); mz[i] = z
    return [m if m is not None else 12 for m in mz]
def main(src, out):
    n = 0; P = []
    with open(out, 'w') as fo:
        for r in csv.DictReader(open(src, encoding='utf-8', errors='replace')):
            try: la, lo = float(r['latitude']), float(r['longitude'])
            except Exception: continue
            if not (-90 <= la <= 90 and -180 <= lo <= 180): continue
            comm = [x.strip() for x in ','.join([r['commod1'], r['commod2'], r['commod3']]).split(',') if x.strip()]
            seen = []; [seen.append(x) for x in comm if x not in seen]
            c1 = seen[0] if seen else ''
            g = group(c1) if c1 else 'O'
            s = STATUS.get(r['dev_stat'], 'U')
            mz = MINZ[s] + (2 if c1.lower() in BULK or any(c1.lower().startswith(b) for b in BULK) else 0)
            y = ''
            a, b = r['yr_fst_prd'].strip(), r['yr_lst_prd'].strip()
            if a or b: y = (a or '?') + ('-' + b if b and b != a else '')
            bulk = c1.lower() in BULK or any(c1.lower().startswith(b) for b in BULK)
            p = {'id': int(r['dep_id']) if r['dep_id'].isdigit() else r['dep_id'], 'n': (r['site_name'] or '').strip()[:60], 'c': ', '.join(seen[:3])[:60], 'g': g, 's': s}
            if y: p['y'] = y[:20]
            x, yy = merc(lo, la)
            P.append({'p': p, 'll': [round(lo, 5), round(la, 5)], 'x': x, 'y': yy, 'allow': mz, 'score': RANK[s] * 10 - (25 if bulk else 0) + (3 if g in 'PBCE' else 0)})
        Z = declutter(P)
        for q, z in zip(P, Z):
            fo.write(json.dumps({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': q['ll']}, 'properties': q['p'], 'tippecanoe': {'minzoom': z}}, separators=(',', ':')) + '\n'); n += 1
        import collections; print('points', n, 'first shown at', sorted(collections.Counter(Z).items()))
if __name__ == '__main__': main(sys.argv[1], sys.argv[2])
# build: tippecanoe -o minerals_v1.pmtiles -l m -Z3 -z12 --drop-densest-as-needed -M 450000 --extend-zooms-if-still-dropping -P minerals.geojsons
