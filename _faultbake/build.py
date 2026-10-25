"""THE FAULTS, BAKED (2026-10-25, user: "do 1 2 3" -- bake the fault lines with high accuracy and detail; fold THE CITY's traces in).

One line layer for the whole country, the most detailed public source winning wherever two cover the same ground:
  1. THE CITY's traced faults (USGS I-2306 / I-2003, 1:24,000)            -- Manhattan and the Bronx
  2. state bedrock maps: NJ (NJGWS 1:100,000), CT (Rodgers 1985)            -- fetch_states.py
     NY: the State Museum's brittle structures (Isachsen & McKendree 1977, MCS #31, 1:250,000) -- NYS_Faults.* in the work dir
         (nysm.nysed.gov/sites/default/files/2025-10/NYS_Faults.zip); SGMC has no New York faults beyond the Vermont map's spill
         into the east, so this fills the state, kept off that strip, THE CITY and the Quaternary lines it would double
  3. USGS Quaternary faults (the active ones, 1:24,000 - 1:250,000)         -- everywhere, never thinned
  4. USGS State Geologic Map Compilation (1:50,000 - 1:1,000,000)           -- the rest; dropped inside 1-2, and
                                                                               where it doubles a Quaternary fault
Properties: k kind (fault/thrust/normal/strike), u 1 if approximate/inferred/concealed, q 1 if Quaternary (active), s source.
Tiled with tippecanoe at full detail up to z14 (simplified only below), every line kept from z7 up.

    python3 _faultbake/build.py <work dir with SGMC_Structure.*, Qfaults_US_Database.*, states.geojson> <out.pmtiles>
"""
import json, os, subprocess, sys
import shapefile
from pyproj import Transformer

W = sys.argv[1]; OUT = sys.argv[2]
NYC = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'city_faults.json')))
states = json.load(open(os.path.join(W, 'states.geojson')))
TR = Transformer.from_crs('+proj=aea +lat_0=23 +lon_0=-96 +lat_1=29.5 +lat_2=45.5 +x_0=0 +y_0=0 +datum=NAD83 +units=m', 'EPSG:4326', always_xy=True)
UNSURE = ('approx', 'infer', 'conceal', 'quer', 'uncertain', 'question')
def kind(t):
    t = (t or '').lower()
    return 'thrust' if ('thrust' in t or 'reverse' in t) else 'strike' if ('strike' in t or 'lateral' in t) else 'normal' if 'normal' in t else 'fault'
out = open(os.path.join(W, 'faults.geojsonl'), 'w'); n = {}
def emit(coords, p, src):
    if len(coords) < 2: return
    p['s'] = src; n[src] = n.get(src, 0) + 1
    out.write(json.dumps({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [[round(x, 6), round(y, 6)] for x, y in coords]}, 'properties': p}, separators=(',', ':')) + '\n')

# 1. THE CITY
xs = []; 
for f in NYC['f']:
    emit(f['c'], {'k': 'fault', 'u': 1 if f.get('k') in ('inferred', 'approx', 'approximate', 'concealed') else 0, 'q': 0, 'r': int(f.get('r', 1))}, 'USGS I-2306 / I-2003, 1:24,000')
    xs += f['c']
NB = (min(c[0] for c in xs) - .01, min(c[1] for c in xs) - .01, max(c[0] for c in xs) + .01, max(c[1] for c in xs) + .01)
inNYC = lambda x, y: NB[0] <= x <= NB[2] and NB[1] <= y <= NB[3]
# 2. STATES
for f in states['features']:
    g = f['geometry']; parts = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates'] if g['type'] == 'MultiLineString' else []
    for c in parts: emit(c, {'k': f['properties']['k'], 'u': f['properties']['u'], 'q': 0}, f['properties']['s'])
# 3. QUATERNARY (and a hash of where they run, ~400 m cells, to keep SGMC from doubling them)
CELL = 0.004; qcells = set()
r = shapefile.Reader(os.path.join(W, 'Qfaults_US_Database'))
for sr in r.iterShapeRecords():
    d = sr.record.as_dict(); pts = sr.shape.points
    if not pts: continue
    lt = (d.get('linetype') or '').lower()
    for i in range(len(sr.shape.parts)):
        a = sr.shape.parts[i]; b = sr.shape.parts[i + 1] if i + 1 < len(sr.shape.parts) else len(pts); seg = pts[a:b]
        emit(seg, {'k': kind(d.get('slip_sense')), 'u': 0 if 'well' in lt else 1, 'q': 1}, 'USGS Quaternary faults')
        for j in range(len(seg) - 1):
            (x0, y0), (x1, y1) = seg[j], seg[j + 1]; m = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / (CELL / 2)))
            for t in range(m + 1):
                x = x0 + (x1 - x0) * t / m; y = y0 + (y1 - y0) * t / m; qcells.add((int(x // CELL), int(y // CELL)))
def nearQ(x, y):
    cx, cy = int(x // CELL), int(y // CELL)
    return any((cx + i, cy + j) in qcells for i in (-1, 0, 1) for j in (-1, 0, 1))
# 2b. NEW YORK (after the Quaternary hash, so it can be kept off those lines too)
NYKEEP = lambda t: ('fault' in t or 'shear zone' in t or 'mylonite' in t) and 'locality' not in t and 'location' not in t
TR_NY = Transformer.from_crs('EPSG:26918', 'EPSG:4326', always_xy=True)      # no .prj; NAD83 fits SGMC's overlap a hair better than NAD27
vcells = set()                                                                 # where SGMC's New York lines (the Vermont map) run
r = shapefile.Reader(os.path.join(W, 'SGMC_Structure'))
for sr in r.iterShapeRecords():
    if sr.record['STATE'] != 'NY': continue
    xs_, ys_ = TR.transform([p[0] for p in sr.shape.points], [p[1] for p in sr.shape.points])
    for x, y in zip(xs_, ys_): vcells.add((int(x // CELL), int(y // CELL)))
nearV = lambda x, y: any((int(x // CELL) + i, int(y // CELL) + j) in vcells for i in (-2, -1, 0, 1, 2) for j in (-2, -1, 0, 1, 2))
nyd = {'kind': 0, 'nyc': 0, 'vt': 0, 'qdup': 0}
if os.path.exists(os.path.join(W, 'NYS_Faults.shp')):
    r = shapefile.Reader(os.path.join(W, 'NYS_Faults'))
    for sr in r.iterShapeRecords():
        t = (sr.record['Type'] or '').strip().lower()
        if not NYKEEP(t): nyd['kind'] += 1; continue
        pts = sr.shape.points
        for i in range(len(sr.shape.parts)):
            a = sr.shape.parts[i]; b = sr.shape.parts[i + 1] if i + 1 < len(sr.shape.parts) else len(pts)
            xs_, ys_ = TR_NY.transform([p[0] for p in pts[a:b]], [p[1] for p in pts[a:b]]); seg = list(zip(xs_, ys_))
            if len(seg) < 2: continue
            mx, my = seg[len(seg) // 2]
            if inNYC(mx, my): nyd['nyc'] += 1; continue
            if sum(1 for x, y in seg if nearV(x, y)) > 0.5 * len(seg): nyd['vt'] += 1; continue
            if sum(1 for x, y in seg if nearQ(x, y)) > 0.6 * len(seg): nyd['qdup'] += 1; continue
            emit(seg, {'k': kind(t), 'u': 1 if ('infer' in t or 'subsurface' in t) else 0, 'q': 0}, 'NYSM Brittle Structures 1:250,000')
    print('NY dropped', nyd)
# 4. SGMC
r = shapefile.Reader(os.path.join(W, 'SGMC_Structure')); dropped = {'state': 0, 'nyc': 0, 'qdup': 0}
for sr in r.iterShapeRecords():
    d = sr.record.as_dict(); de = (d.get('DESCRIPTIO') or '').lower()
    if 'fault' not in de: continue
    if d.get('STATE') in ('NJ', 'CT'): dropped['state'] += 1; continue
    pts = sr.shape.points
    for i in range(len(sr.shape.parts)):
        a = sr.shape.parts[i]; b = sr.shape.parts[i + 1] if i + 1 < len(sr.shape.parts) else len(pts)
        xs_, ys_ = TR.transform([p[0] for p in pts[a:b]], [p[1] for p in pts[a:b]]); seg = list(zip(xs_, ys_))
        if not seg: continue
        mx, my = seg[len(seg) // 2]
        if inNYC(mx, my): dropped['nyc'] += 1; continue
        if sum(1 for x, y in seg if nearQ(x, y)) > 0.6 * len(seg): dropped['qdup'] += 1; continue
        emit(seg, {'k': kind(de), 'u': 1 if any(w in de for w in UNSURE) else 0, 'q': 0}, 'USGS SGMC (' + (d.get('STATE') or '') + ')')
out.close()
print('kept', sum(n.values()), 'dropped', dropped)
srcs = {}
for k, v in n.items(): srcs[k.split(' (')[0]] = srcs.get(k.split(' (')[0], 0) + v
print(srcs)
subprocess.run(['tippecanoe', '-o', OUT, '-f', '-l', 'faults', '-Z4', '-z14', '-d14', '--simplify-only-low-zooms', '--no-line-simplification' if False else '--simplification=2',
                '--drop-densest-as-needed', '--extend-zooms-if-still-dropping', '-r1', '--no-tile-size-limit', '-q', os.path.join(W, 'faults.geojsonl')], check=True)
print('pmtiles', OUT, os.path.getsize(OUT) // 1024, 'KB')
