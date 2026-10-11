"""DARK MATTER (2026-10-11): the measured evidence, baked once for the page (the sources are fixed publications).

  sparc   SPARC (Lelli, McGaugh & Schombert 2016, AJ 152, 157): 175 galaxies' rotation curves, each radius with the
          observed speed and the speeds the gas, the stellar disc and the bulge alone would give. The expected speed
          from the visible matter is Vbar = sqrt(Vgas|Vgas| + 0.5 Vdisk^2 + 0.7 Vbul^2) (the usual 3.6-micron mass-to-light
          ratios 0.5 and 0.7). Kept per galaxy: name, distance (Mpc), radius (kpc), Vobs, errV, Vbar (km/s).
  lz      LUX-ZEPLIN, 4.2 tonne-years (PRL 135, 011802, 2025; HEPData ins2841863): the 90% upper limit on the WIMP-nucleon
          spin-independent cross-section vs mass, its expected-sensitivity bands, and the 1,220 events it recorded in
          S1 / log10(S2) space.
  bullet  Chandra's Bullet Cluster composite (NASA/CXC/STScI/Magellan/ESO), rehosted to R2.
Writes OUT/dm.json and OUT/bullet.jpg.
"""
import csv, io, json, math, os, sys, urllib.request, zipfile

OUT = sys.argv[1] if len(sys.argv) > 1 else '_dm_out'
os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'curl/8.4.0 (bluishvoid.com dark-matter bake)', 'Accept': '*/*'}   # HEPData answers 403 to python's default and to some custom agents
get = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read()

# ---- SPARC ----
z = zipfile.ZipFile(io.BytesIO(get('https://astroweb.case.edu/SPARC/Rotmod_LTG.zip')))
gal = []
for name in sorted(z.namelist()):
    if not name.endswith('_rotmod.dat'): continue
    txt = z.read(name).decode('utf-8', 'ignore').splitlines(); dist = None; R = []; V = []; E = []; B = []
    for ln in txt:
        if ln.startswith('# Distance'): dist = float(ln.split('=')[1].split()[0]); continue
        if ln.startswith('#') or not ln.strip(): continue
        r, vo, ev, vg, vd, vb = [float(x) for x in ln.split()[:6]]
        vbar2 = vg * abs(vg) + 0.5 * vd * vd + 0.7 * vb * vb
        R.append(round(r, 2)); V.append(round(vo, 1)); E.append(round(ev, 1)); B.append(round(math.copysign(math.sqrt(abs(vbar2)), vbar2), 1))
    gal.append({'n': name.replace('_rotmod.dat', ''), 'd': dist, 'r': R, 'v': V, 'e': E, 'b': B})
print('sparc galaxies', len(gal), 'points', sum(len(g['r']) for g in gal))

# ---- LZ ----
def hep(table):
    raw = get('https://www.hepdata.net/download/table/ins2841863/%s/1/csv' % urllib.request.quote(table)).decode()
    blocks, cur = [], None
    for ln in raw.splitlines():
        if ln.startswith('#') or not ln.strip():
            if cur: blocks.append(cur); cur = None
            continue
        row = next(csv.reader([ln]))
        try: vals = [float(x) for x in row]
        except ValueError: cur = {'head': row, 'rows': []}; continue
        if cur is None: cur = {'head': None, 'rows': []}
        cur['rows'].append(vals)
    if cur: blocks.append(cur)
    return blocks
si = hep('SI cross section'); ev = hep('Data')
lz = {'limit': [[r[0], r[1]] for r in si[0]['rows']], 'bands': [{'head': b['head'], 'rows': b['rows']} for b in si[1:]],
      'events': [[round(r[0], 2), round(r[1], 3)] for r in ev[0]['rows']]}
print('lz limit pts', len(lz['limit']), 'bands', [b['head'] for b in lz['bands']], 'events', len(lz['events']))

open(os.path.join(OUT, 'bullet.jpg'), 'wb').write(get('https://chandra.si.edu/photo/2006/1e0657/1e0657.jpg'))
json.dump({'sparc': gal, 'lz': lz, 'credit': 'SPARC, Lelli, McGaugh & Schombert 2016 · LZ Collaboration 2025 via HEPData · Chandra: NASA/CXC/CfA/M.Markevitch; NASA/STScI; Magellan/U.Arizona/D.Clowe; ESO WFI'},
          open(os.path.join(OUT, 'dm.json'), 'w'), separators=(',', ':'))
print('dm.json', os.path.getsize(os.path.join(OUT, 'dm.json')), 'bytes')
