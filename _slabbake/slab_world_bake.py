"""SUBDUCTION, THE WHOLE PLANET (GEOLOGY, 2026-11-22; user: "do 1 2 3 4 5 6 7 8").

Writes to <out>/slab/:
  world_v1.bin/.json   every M5+ quake the USGS has located since 1973, worldwide (the overview globe)
  zones_v1.bin/.json   all 27 Slab2 zones at 0.5 deg (the overview's slabs) + each zone's name, box, counts, trench point
  <zone>_v1.bin/.json  per zone: every M4+ quake since 1973 in its box, its Slab2 grid at 0.1 deg, its 10m coast
  volc_v1.json         subduction-zone volcanoes (Smithsonian GVP, from the site's volcano/latest.json) with the slab depth under each
Binary layout (little-endian, each block 4-byte aligned, offsets in the json):
  quakes: lon uint16 ((lon - box west) * 1000; world file: (lon+180)*100), lat uint16 (same, from box south / (lat+90)*100),
          dep uint16 (0.1 km), mag uint8 (x10), t uint32 (s since 1973-01-01)
  slab:   int16 km below sea level, -1 = none, row-major from (west, south)
Sources: USGS ComCat (public domain); USGS Slab2, Hayes et al. 2018 (public domain); Natural Earth (public domain);
Smithsonian GVP Volcanoes of the World (free with credit).

Run: python3 _slabbake/slab_world_bake.py <out>        (cache: _slabbake/cache; Slab2 tarball unpacked there)
"""
import csv, datetime, io, json, os, sys, time, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); CACHE = os.path.join(HERE, 'cache')
SLAB = os.path.join(CACHE, 'Slab2Distribute_Mar2018')
EPOCH = datetime.datetime(1973, 1, 1, tzinfo=datetime.timezone.utc)
TRENCH = { 'alu': 'ALEUTIAN TRENCH', 'cal': 'CALABRIAN ARC', 'cam': 'MIDDLE AMERICA TRENCH', 'car': 'LESSER ANTILLES TRENCH', 'cas': 'CASCADIA SUBDUCTION ZONE',
  'cot': 'COTABATO TRENCH', 'hel': 'HELLENIC TRENCH', 'izu': 'MARIANA TRENCH', 'ker': 'TONGA TRENCH', 'kur': 'JAPAN TRENCH', 'mak': 'MAKRAN TRENCH', 'man': 'MANILA TRENCH',
  'mue': 'MUERTOS TROUGH', 'phi': 'PHILIPPINE TRENCH', 'png': 'NEW GUINEA TRENCH', 'puy': 'PUYSEGUR TRENCH', 'ryu': 'RYUKYU TRENCH', 'sam': 'PERU-CHILE TRENCH',
  'sco': 'SOUTH SANDWICH TRENCH', 'sol': 'NEW BRITAIN TRENCH', 'sul': 'NORTH SULAWESI TRENCH', 'sum': 'SUNDA TRENCH', 'van': 'NEW HEBRIDES TRENCH' }
NAMES = { 'alu': 'ALASKA-ALEUTIANS', 'cal': 'CALABRIA', 'cam': 'CENTRAL AMERICA', 'car': 'LESSER ANTILLES', 'cas': 'CASCADIA', 'cot': 'COTABATO',
  'hal': 'HALMAHERA', 'hel': 'HELLENIC ARC', 'him': 'HIMALAYA', 'hin': 'HINDU KUSH', 'izu': 'IZU-BONIN-MARIANA', 'ker': 'TONGA-KERMADEC',
  'kur': 'KURILS-KAMCHATKA-JAPAN', 'mak': 'MAKRAN', 'man': 'MANILA TRENCH', 'mue': 'MUERTOS TROUGH', 'pam': 'PAMIR', 'phi': 'PHILIPPINE TRENCH',
  'png': 'NEW GUINEA', 'puy': 'PUYSEGUR', 'ryu': 'RYUKYU', 'sam': 'SOUTH AMERICA', 'sco': 'SOUTH SANDWICH', 'sol': 'SOLOMON ISLANDS',
  'sul': 'SULAWESI', 'sum': 'SUMATRA-JAVA', 'van': 'VANUATU' }

def fetch(url, path, maxage=None):
    if os.path.exists(path) and (maxage is None or time.time() - os.path.getmtime(path) < maxage): return open(path, encoding='utf-8').read()
    for k in range(5):
        try:
            d = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluishvoid-slab-bake'}), timeout=180).read().decode('utf-8')
            open(path, 'w', encoding='utf-8').write(d); return d
        except Exception as e:
            print('  retry', k, e); time.sleep(5 * (k + 1))
    raise SystemExit('failed ' + url)

def count(q):
    return int(fetch('https://earthquake.usgs.gov/fdsnws/event/1/count?' + q, os.path.join(CACHE, 'n_%d.txt' % (hash(q) & 0xffffffff)), 86400 * 30).strip())

def quakes(tag, box, minmag):
    """All events in box since 1973, chunked so no request passes 20,000. box = (w, s, e, n), w/e may exceed 180."""
    w, s, e, n = box if box else (0, 0, 0, 0); yr = datetime.date.today().year; out = []
    geo = 'minlatitude=%g&maxlatitude=%g&minlongitude=%g&maxlongitude=%g&minmagnitude=%g' % (s, n, w, e, minmag) if box else 'minmagnitude=%g' % minmag
    spans = []; stack = [(datetime.date(1973, 1, 1), datetime.date(yr + 1, 1, 1))]
    while stack:
        a, b = stack.pop()
        c = count(geo + '&starttime=%s&endtime=%s' % (a, b))
        if c < 18000: spans.append((a, b))
        else: m = a + (b - a) / 2; stack += [(a, m), (m, b)]
    spans.sort()
    for a, b in spans:
        recent = b.year >= yr
        d = fetch('https://earthquake.usgs.gov/fdsnws/event/1/query?format=csv&orderby=time-asc&' + geo + '&starttime=%s&endtime=%s' % (a, b),
                  os.path.join(CACHE, 'q_%s_%s_%s.csv' % (tag, a, b)), 86400 if recent else None)
        for r in csv.DictReader(io.StringIO(d)):   # a real CSV reader: place names carry commas
            try:
                t = datetime.datetime.strptime(r['time'][:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=datetime.timezone.utc)
                lat, lon, dep, mag = float(r['latitude']), float(r['longitude']), float(r['depth'] or 0), float(r['mag'])
            except Exception: continue
            if box and lon < w: lon += 360
            # FIXED DEPTHS (2026-11-23): solutions that could not resolve depth are pinned at 0, 5, 10, 33 or 35 km -- a default, not a
            # measurement; they stack into flat stripes. Flagged so the page draws them soft.
            fx = 1 if round(dep, 1) in (0.0, 5.0, 10.0, 33.0, 35.0) else 0
            out.append((lon, lat, max(0.0, dep), mag, int((t - EPOCH).total_seconds()), fx))
    out.sort(key=lambda q: q[4]); print(tag, len(out), 'quakes in', len(spans), 'requests'); return out

class Buf:
    def __init__(s): s.b = bytearray(); s.off = {}
    def put(s, k, arr):
        while len(s.b) % 4: s.b.append(0)
        s.off[k] = len(s.b); s.b.extend(np.ascontiguousarray(arr).tobytes())

def pack_quakes(B, Q, lon0, lat0, scale):
    a = np.array(Q, dtype=np.float64).reshape(-1, 6)
    B.put('lon', np.clip(np.round((a[:, 0] - lon0) * scale), 0, 65535).astype('<u2'))
    B.put('lat', np.clip(np.round((a[:, 1] - lat0) * scale), 0, 65535).astype('<u2'))
    B.put('dep', np.clip(np.round(a[:, 2] * 10), 0, 65535).astype('<u2'))
    B.put('mag', np.clip(np.round(a[:, 3] * 10), 0, 255).astype('u1'))
    B.put('t', a[:, 4].astype('<u4'))
    B.put('fx', a[:, 5].astype('u1'))
    return a

def grid(z):
    import glob
    d = np.loadtxt(glob.glob(os.path.join(SLAB, 'Slab2_TXT/%s_slab2_dep_*.xyz' % z))[0], delimiter=',')   # file dates differ per zone
    d = d[~np.isnan(d[:, 2])]; d[:, 0] = np.where(d[:, 0] < 0, d[:, 0] + 360, d[:, 0]); return d

def resample(d, w, s, e, n, st):
    nx, ny = int(round((e - w) / st)) + 1, int(round((n - s) / st)) + 1
    g = np.full((ny, nx), -1, np.int16)
    ix = np.round((d[:, 0] - w) / st).astype(int); iy = np.round((d[:, 1] - s) / st).astype(int)
    m = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
    g[iy[m], ix[m]] = np.clip(np.round(-d[m, 2]), 0, 32000).astype(np.int16)
    return g

def coast(box):
    w, s, e, n = box; rings = []
    for nm in ('ne_10m_land', 'ne_10m_minor_islands'):
        p = os.path.join(CACHE, nm + '.geojson')
        if not os.path.exists(p): urllib.request.urlretrieve('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/%s.geojson' % nm, p)
        for f in json.load(open(p))['features']:
            g = f['geometry']; polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
            for poly in polys:
                for shift in (0, 360):
                    pts = [(x + shift, y) for x, y in poly[0]]
                    if not any(w - .5 <= x <= e + .5 and s - .5 <= y <= n + .5 for x, y in pts): continue
                    q = [(min(max(x, w), e), min(max(y, s), n)) for x, y in pts]
                    q2 = [q[0]] + [p for i, p in enumerate(q[1:]) if abs(p[0] - q[i][0]) + abs(p[1] - q[i][1]) > .01]
                    if len(q2) >= 3 and len(set(q2)) > 2: rings.append(q2)
    return rings

def main():
    out = os.path.join(sys.argv[1] if len(sys.argv) > 1 else 'out', 'slab'); os.makedirs(out, exist_ok=True)
    only = sys.argv[2].split(',') if len(sys.argv) > 2 else None
    zones = sorted(NAMES)
    # ---- cities (Natural Earth populated places, public domain): the biggest few in each zone's box
    pp = os.path.join(CACHE, 'ne_10m_populated_places_simple.geojson')
    if not os.path.exists(pp): urllib.request.urlretrieve('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_populated_places_simple.geojson', pp)
    PLACES = [(f['properties'].get('scalerank', 10), f['properties'].get('pop_max') or 0, f['properties']['name'], f['geometry']['coordinates']) for f in json.load(open(pp, encoding='utf-8'))['features']]
    # ---- the zones
    ZM = {}; ov = Buf()
    for z in zones:
        d = grid(z); w, e, s, n = d[:, 0].min(), d[:, 0].max(), d[:, 1].min(), d[:, 1].max()
        box = (float(np.floor(w - 1.5)), float(np.floor(s - 1.5)), float(np.ceil(e + 1.5)), float(np.ceil(n + 1.5)))
        sh = d[-d[:, 2] < 15]; tp = sh[len(sh) // 2] if len(sh) else d[np.argmin(-d[:, 2])]
        mid = d[np.argsort(d[:, 1])[len(d) // 2]]
        g5 = resample(d, box[0], box[1], box[2], box[3], 0.5); ov.put(z, g5.astype('<i2'))
        ZM[z] = dict(name=NAMES[z], box=box, ov=dict(nx=g5.shape[1], ny=g5.shape[0], st=0.5), maxdep=int(-d[:, 2].min()),
                     trench=[round(float(tp[0]), 2), round(float(tp[1]), 2)], mid=[round(float(mid[0]), 2), round(float(mid[1]), 2)], tname=TRENCH.get(z))
        cs = []
        for rk, pop, nm, (x, y) in PLACES:
            xx = x + 360 if x < box[0] else x
            if box[0] <= xx <= box[2] and box[1] <= y <= box[3]: cs.append((-pop, rk, nm.upper(), round(xx, 2), round(y, 2)))
        pick = []   # Natural Earth's own importance first (scalerank), then size; nothing within 80 km of a city already picked (no suburbs)
        for c in sorted(cs, key=lambda c: (c[1], c[0])):
            if all(np.hypot((c[3] - q[1]) * np.cos(np.radians(c[4])), c[4] - q[2]) * 111 > 80 for q in pick): pick.append([c[2], c[3], c[4]])
            if len(pick) >= 8: break
        ZM[z]['cities'] = pick
        if only and z not in only: continue
        Q = quakes(z, box, 4.0); B = Buf(); a = pack_quakes(B, Q, box[0], box[1], 1000)
        g = resample(d, box[0], box[1], box[2], box[3], 0.1); B.put('slab', g.astype('<i2'))
        C = coast(box); flat = []; lens = []
        for r in C: lens.append(len(r)); flat.extend([(round((x - box[0]) * 1000), round((y - box[1]) * 1000)) for x, y in r])
        B.put('coast', np.array(flat, '<u2').reshape(-1) if flat else np.zeros(0, '<u2'))
        open(os.path.join(out, z + '_v1.bin'), 'wb').write(bytes(B.b))
        bands = [int((a[:, 2] < 70).sum()), int(((a[:, 2] >= 70) & (a[:, 2] < 300)).sum()), int((a[:, 2] >= 300).sum())] if len(a) else [0, 0, 0]
        i_dp = int(a[:, 2].argmax()) if len(a) else 0; i_mg = int(a[:, 3].argmax()) if len(a) else 0
        meta = dict(zone=z, name=NAMES[z], box=box, n=len(Q), off=B.off, scale=1000, slab=dict(step=0.1, nx=g.shape[1], ny=g.shape[0], maxdep=int(g.max())),
                    coast=lens, bands=bands, built=time.strftime('%Y-%m-%d'),
                    deepest=dict(dep=float(a[i_dp, 2]), mag=float(a[i_dp, 3]), t=int(a[i_dp, 4])) if len(a) else None,
                    biggest=dict(mag=float(a[i_mg, 3]), dep=float(a[i_mg, 2]), t=int(a[i_mg, 4]), lon=float(a[i_mg, 0]), lat=float(a[i_mg, 1])) if len(a) else None)
        json.dump(meta, open(os.path.join(out, z + '_v1.json'), 'w'), separators=(',', ':'))
        ZM[z].update(n=len(Q), bands=bands, deepest=meta['deepest'], biggest=meta['biggest'])
        print(z, len(Q), len(B.b) // 1024, 'KB')
    open(os.path.join(out, 'zones_v1.bin'), 'wb').write(bytes(ov.b))
    json.dump(dict(zones=ZM, off=ov.off, built=time.strftime('%Y-%m-%d')), open(os.path.join(out, 'zones_v1.json'), 'w'), separators=(',', ':'))
    if only: return
    # ---- the world, M5+
    Q = quakes('world', None, 5.0); B = Buf(); a = np.array(Q).reshape(-1, 6)
    a[:, 0] = np.where(a[:, 0] < -180, a[:, 0] + 360, a[:, 0])
    pack_quakes(B, [tuple(r) for r in a], -180, -90, 100)
    open(os.path.join(out, 'world_v1.bin'), 'wb').write(bytes(B.b))
    json.dump(dict(n=len(Q), off=B.off, scale=100, lon0=-180, lat0=-90, built=time.strftime('%Y-%m-%d'),
                   bands=[int((a[:, 2] < 70).sum()), int(((a[:, 2] >= 70) & (a[:, 2] < 300)).sum()), int((a[:, 2] >= 300).sum())]), open(os.path.join(out, 'world_v1.json'), 'w'), separators=(',', ':'))
    # ---- volcanoes over slabs: the slab depth under each subduction volcano (0.1 deg grids)
    V = json.loads(fetch('https://cdn.bluishvoid.com/volcano/latest.json', os.path.join(CACHE, 'volcano_latest.json'), 86400 * 7))['volcanoes']
    grids = {z: (grid(z)) for z in zones}
    vo = []
    for v in V:
        if not str(v.get('setting', '')).lower().startswith('subduction'): continue
        lon = v['lon'] + 360 if v['lon'] < 0 else v['lon']; best = None
        for z, d in grids.items():
            m = (np.abs(d[:, 0] - lon) < .06) & (np.abs(d[:, 1] - v['lat']) < .06)
            if m.any():
                dep = float(-d[m, 2].mean())
                if best is None or dep < best[1]: best = (z, dep)
        vo.append(dict(n=v['n'], name=v['name'], lat=v['lat'], lon=v['lon'], elev=v.get('elev'), last=v.get('last'), zone=best[0] if best else None, slab=round(best[1]) if best else None))
    json.dump(dict(volcanoes=vo, built=time.strftime('%Y-%m-%d')), open(os.path.join(out, 'volc_v1.json'), 'w'), separators=(',', ':'))
    over = [x['slab'] for x in vo if x['slab'] is not None]
    print('volcanoes', len(vo), 'over a slab', len(over), 'median slab depth', float(np.median(over)) if over else None)

if __name__ == '__main__':
    main()
