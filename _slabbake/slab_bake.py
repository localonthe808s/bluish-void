"""SUBDUCTION bake (GEOLOGY > EARTHQUAKES > BELOW, 2026-11-22; user: "can we visualize earthquake data below the earth like this?"
-> "geology, start with tonga").

One zone per run. For each zone writes out/slab/<zone>_v1.bin + <zone>_v1.json:
  quakes  USGS ComCat (public domain), M4+ since 1973 inside the zone's box, sorted by time. Column-ordered little-endian:
          lon int16 (0.001 deg from box west), lat int16 (0.001 deg from box south), depth uint16 (0.1 km), mag uint8 (x10),
          t uint32 (seconds since 1973-01-01 UTC)
  slab    USGS Slab2 (Hayes et al. 2018, ScienceBase 5aa1b00ee4b0b1c392e86467, public domain) depth grid resampled to STEP deg:
          int16 km below sea level, -1 = no slab
  coast   Natural Earth 10m land + minor islands (public domain) clipped to the box: int16 (0.001 deg) rings
The JSON carries the box, counts, the byte offsets of each block, and the zone's words.

Run: python3 _slabbake/slab_bake.py <out> [zone]     (cache in _slabbake/cache; Slab2 tarball must already be unpacked there)
"""
import json, os, struct, sys, time, urllib.request, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); CACHE = os.path.join(HERE, 'cache')
ZONES = {
  'tonga': dict(name='TONGA-KERMADEC', slab='ker', box=(172.0, -38.0, 190.0, -13.0), step=0.1,
                plate='PACIFIC PLATE', under='AUSTRALIAN PLATE'),
}
EPOCH = datetime.datetime(1973, 1, 1, tzinfo=datetime.timezone.utc)

def get(url, path):
    if not os.path.exists(path):
        print('fetch', url[:110]); urllib.request.urlretrieve(url, path)
    return path

def quakes(z):
    w, s, e, n = z['box']; out = []
    years = list(range(1973, datetime.date.today().year + 1, 4))
    for y in years:
        a, b = '%d-01-01' % y, '%d-01-01' % (y + 4)
        p = os.path.join(CACHE, 'qk_%s_%d.csv' % (z['slab'], y))
        if y + 4 > datetime.date.today().year and os.path.exists(p) and time.time() - os.path.getmtime(p) > 86400: os.remove(p)
        get('https://earthquake.usgs.gov/fdsnws/event/1/query?format=csv&orderby=time-asc&minmagnitude=4&minlatitude=%g&maxlatitude=%g&minlongitude=%g&maxlongitude=%g&starttime=%s&endtime=%s'
            % (s, n, w, e, a, b), p)
        rows = open(p).read().strip().split('\n')[1:]
        print(y, len(rows)); assert len(rows) < 20000, 'chunk too big'
        for r in rows:
            c = r.split(',')
            try:
                t = datetime.datetime.strptime(c[0][:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=datetime.timezone.utc)
                lat, lon, dep, mag = float(c[1]), float(c[2]), float(c[3] or 0), float(c[4])
            except Exception: continue
            if lon < 0: lon += 360
            if not (w <= lon <= e and s <= lat <= n): continue
            out.append((lon, lat, max(0, dep), mag, int((t - EPOCH).total_seconds())))
    out.sort(key=lambda q: q[4]); return out

def slab(z):
    w, s, e, n = z['box']; st = z['step']
    d = np.loadtxt(os.path.join(CACHE, 'Slab2Distribute_Mar2018/Slab2_TXT/%s_slab2_dep_02.24.18.xyz' % z['slab']), delimiter=',')
    nx, ny = int(round((e - w) / st)) + 1, int(round((n - s) / st)) + 1
    g = np.full((ny, nx), -1, np.int16)
    ok = ~np.isnan(d[:, 2]); d = d[ok]
    ix = np.round((d[:, 0] - w) / st).astype(int); iy = np.round((d[:, 1] - s) / st).astype(int)
    m = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny) & (np.abs(d[:, 0] - (w + ix * st)) < 1e-3) & (np.abs(d[:, 1] - (s + iy * st)) < 1e-3)
    g[iy[m], ix[m]] = np.clip(np.round(-d[m, 2]), 0, 32000).astype(np.int16)
    return g

def coast(z):
    w, s, e, n = z['box']; rings = []
    for nm in ('ne_10m_land', 'ne_10m_minor_islands'):
        p = get('https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/%s.geojson' % nm, os.path.join(CACHE, nm + '.geojson'))
        for f in json.load(open(p))['features']:
            g = f['geometry']; polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
            for poly in polys:
                for ring in poly[:1]:
                    pts = [((x + 360 if x < 0 else x), y) for x, y in ring]
                    if not any(w - .5 <= x <= e + .5 and s - .5 <= y <= n + .5 for x, y in pts): continue
                    q = [(min(max(x, w), e), min(max(y, s), n)) for x, y in pts]
                    q2 = [q[0]] + [p for i, p in enumerate(q[1:]) if abs(p[0] - q[i][0]) + abs(p[1] - q[i][1]) > .004]
                    if len(q2) >= 3: rings.append(q2)
    return rings

def main():
    out = os.path.join(sys.argv[1] if len(sys.argv) > 1 else 'out', 'slab'); os.makedirs(out, exist_ok=True)
    key = sys.argv[2] if len(sys.argv) > 2 else 'tonga'; z = ZONES[key]; w, s, e, n = z['box']
    Q = quakes(z); G = slab(z); C = coast(z)
    N = len(Q); a = np.array(Q)
    blocks = [('lon', np.round((a[:, 0] - w) * 1000).astype('<i2')), ('lat', np.round((a[:, 1] - s) * 1000).astype('<i2')),
              ('dep', np.round(a[:, 2] * 10).astype('<u2')), ('mag', np.clip(np.round(a[:, 3] * 10), 0, 255).astype('u1')),
              ('t', a[:, 4].astype('<u4'))]
    buf = bytearray(); off = {}
    def put(k, arr):
        while len(buf) % 4: buf.append(0)
        off[k] = len(buf); buf.extend(arr.tobytes())
    for k, arr in blocks: put(k, arr)
    put('slab', G.astype('<i2'))
    flat = []; lens = []
    for r in C: lens.append(len(r)); flat.extend([(round((x - w) * 1000), round((y - s) * 1000)) for x, y in r])
    put('coast', np.array(flat, '<i2').reshape(-1));
    open(os.path.join(out, key + '_v1.bin'), 'wb').write(bytes(buf))
    meta = dict(zone=key, name=z['name'], plate=z['plate'], under=z['under'], box=z['box'], n=N, off=off,
                slab=dict(step=z['step'], nx=G.shape[1], ny=G.shape[0], maxdep=int(G.max())), coast=lens,
                epoch='1973-01-01T00:00:00Z', built=time.strftime('%Y-%m-%d'),
                deepest=dict(dep=float(a[:, 2].max()), mag=float(a[a[:, 2].argmax(), 3]), t=int(a[a[:, 2].argmax(), 4])),
                biggest=dict(mag=float(a[:, 3].max()), dep=float(a[a[:, 3].argmax(), 2]), t=int(a[a[:, 3].argmax(), 4]),
                             lon=float(a[a[:, 3].argmax(), 0]), lat=float(a[a[:, 3].argmax(), 1])),
                bands=[int((a[:, 2] < 70).sum()), int(((a[:, 2] >= 70) & (a[:, 2] < 300)).sum()), int((a[:, 2] >= 300).sum())])
    json.dump(meta, open(os.path.join(out, key + '_v1.json'), 'w'), separators=(',', ':'))
    print(key, N, 'quakes', len(buf) // 1024, 'KB', 'bands', meta['bands'], 'deepest', meta['deepest'], 'biggest', meta['biggest'])

if __name__ == '__main__':
    main()
