#!/usr/bin/env python3
"""Bake the GALAXY / UNIVERSE lab's frame files (_solarlab/galaxy/*.json).

Five frames, five files, every one drawn from a catalog rather than a picture. Run with the directory holding the
raw downloads (they are big and are NOT committed):

    python3 build_galaxy.py /path/to/downloads

Downloads (all keyless; VizieR = https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync?request=doQuery&lang=adql&format=json):
  hyg.csv           HYG v4.1  https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv
                    (CC BY-SA 2.5 -- credit "HYG / David Nash")
  clusters.json     Hunt & Reffert 2023, Gaia DR3 clusters   VizieR J/A+A/673/A114/clusters
                    SELECT Name, GLON, GLAT, dist50, N, logAge50, r50pc, Type, Plx
  masers.json       Reid et al. 2019, maser parallaxes       VizieR J/ApJ/885/131/table1
                    SELECT Name, RAJ2000, DEJ2000, plx, e_plx, Arm
  localgroup.json   McConnachie 2012, Local Group census     VizieR J/AJ/144/4/catalog  (SELECT *)
  twomrs.json       Huchra et al. 2012, 2MASS Redshift Survey  VizieR J/ApJS/199/26/table3
                    SELECT TOP 50000 RAJ2000, DEJ2000, Ktmag, cz
  sdss.csv          SDSS DR18 SkyServer, SELECT ra, dec, z FROM SpecObj WHERE class='GALAXY' AND zWarning=0
                    AND dec BETWEEN -1.25 AND 1.25 AND z BETWEEN 0.002 AND 0.3  (format=csv)
  radcliffe.tab     Alves et al. 2020 best-fit Radcliffe Wave, Harvard Dataverse doi:10.7910/DVN/OE51SZ (CC0)
  localbubble.fits  Pelgrims et al. 2020 Local Bubble shell, Dataverse doi:10.7910/DVN/RHPVNC (CC0):
                    HEALPix nside 128 RING, inner-shell distance (pc) per direction
"""
import csv, json, math, os, sys, random
import numpy as np

SRC = sys.argv[1] if len(sys.argv) > 1 else 'galaxy_dl'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'galaxy')
os.makedirs(OUT, exist_ok=True)
PC_LY = 3.26156
R0 = 8.15                      # kpc, Sun to Galactic Centre (Reid et al. 2019)
H0 = 70.0                      # km/s/Mpc for redshift distances

# ---- coordinate frames ------------------------------------------------------------------------------------------
EQ2GAL = np.array([[-0.0548755604, -0.8734370902, -0.4838350155],
                   [ 0.4941094279, -0.4448296300,  0.7469822445],
                   [-0.8676661490, -0.1980763734,  0.4559837762]])
def unit(lon, lat):
    lon, lat = math.radians(lon), math.radians(lat)
    return np.array([math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)])
def eq_to_gal_xyz(ra, dec, d):
    return EQ2GAL.dot(unit(ra, dec)) * d
def gal_lb_xyz(l, b, d):
    return unit(l, b) * d
# supergalactic: north pole at (l 47.37, b +6.32), origin at (l 137.37, b 0)
SGZ = unit(47.37, 6.32); SGX = unit(137.37, 0.0); SGX = SGX - SGZ*SGX.dot(SGZ); SGX /= np.linalg.norm(SGX); SGY = np.cross(SGZ, SGX)
GAL2SG = np.vstack([SGX, SGY, SGZ])

def r2(v): return round(float(v), 2)
def r1(v): return round(float(v), 1)
def jload(name):
    d = json.load(open(os.path.join(SRC, name)))
    names = [m['name'] for m in d['metadata']]
    return [dict(zip(names, r)) for r in d['data']]

# ---- 1. NEIGHBORHOOD: a thousand light-years ---------------------------------------------------------------------
stars = []; named = []
with open(os.path.join(SRC, 'hyg.csv'), newline='') as f:
    for r in csv.DictReader(f):
        try: d = float(r['dist']); mag = float(r['mag'])
        except ValueError: continue
        if d >= 99999 or d > 1000 / PC_LY: continue           # inside 1,000 ly
        if r['proper'] == 'Sol': continue
        if not (mag <= 6.5 or d < 12): continue                # naked-eye, plus everything within 40 ly
        x, y, z = eq_to_gal_xyz(float(r['ra']) * 15, float(r['dec']), d) * PC_LY
        try: ci = float(r['ci'])
        except ValueError: ci = 0.6
        stars.append([r1(x), r1(y), r1(z), round(mag, 1), round(ci, 2)])
        if r['proper']: named.append([r['proper'], r1(x), r1(y), r1(z), round(mag, 1)])
clusters = []
for c in jload('clusters.json'):
    if c['dist50'] is None or c['N'] is None: continue
    if c['dist50'] > 1300 / PC_LY * 1.0 and c['dist50'] > 400: pass
    if c['dist50'] > 1200: continue
    if c['N'] < 50 or (c['Type'] or '').strip() != 'o': continue
    x, y, z = gal_lb_xyz(c['GLON'], c['GLAT'], c['dist50']) * PC_LY
    nm = c['Name'].replace('_', ' ')
    clusters.append([nm, r1(x), r1(y), r1(z), int(c['N']), round(c['logAge50'] or 8, 2), r1((c['r50pc'] or 2) * PC_LY)])
# the Local Bubble shell in the Galactic plane: HEALPix RING ang2pix, the lmax=10 smoothing
from astropy.io import fits
hb = fits.open(os.path.join(SRC, 'localbubble.fits'))[1].data
NS = 128
def ang2pix_ring(nside, theta, phi):
    z = math.cos(theta); za = abs(z); tt = (phi % (2*math.pi)) * 2 / math.pi
    if za <= 2/3:
        t1 = nside * (0.5 + tt); t2 = nside * z * 0.75
        jp = int(t1 - t2); jm = int(t1 + t2)
        ir = nside + 1 + jp - jm; kshift = 1 - (ir & 1)
        ip = (jp + jm - nside + kshift + 1) // 2; ip %= 4 * nside
        return nside * (nside - 1) * 2 + (ir - 1) * 4 * nside + ip
    tp = tt - int(tt); tmp = nside * math.sqrt(3 * (1 - za))
    jp = int(tp * tmp); jm = int((1 - tp) * tmp); ir = jp + jm + 1; ip = int(tt * ir) % (4 * ir)
    return 2 * ir * (ir - 1) + ip if z > 0 else 12 * nside * nside - 2 * ir * (ir + 1) + ip
col = hb['r_in_lmax-10']
bubble = []
for l in range(0, 360, 3):
    r = float(col[ang2pix_ring(NS, math.pi/2, math.radians(l))]) * PC_LY
    bubble.append([l, r1(r)])
rad = []
rows = [ln.split('\t') for ln in open(os.path.join(SRC, 'radcliffe.tab')).read().strip().split('\n')[1:]]
for i in range(0, len(rows), 8):
    x, y, z = (float(v) * PC_LY for v in rows[i][:3]); rad.append([r1(x), r1(y), r1(z)])
json.dump({'what': 'the solar neighborhood, 1,000 light-years across; heliocentric Galactic xyz in light-years (x to the Galactic Centre, y along rotation l=90, z to the north Galactic pole)',
           'stars': stars, 'named': named, 'clusters': clusters, 'bubble': bubble, 'radcliffe': rad,
           'credit': 'HYG v4.1 (CC BY-SA) · Gaia DR3 clusters: Hunt & Reffert 2023 · Local Bubble shell: Pelgrims+ 2020 · Radcliffe Wave: Alves+ 2020'},
          open(os.path.join(OUT, 'neighborhood.json'), 'w'), separators=(',', ':'))
print('neighborhood: %d stars (%d named), %d clusters, bubble %d pts, radcliffe %d pts' % (len(stars), len(named), len(clusters), len(bubble), len(rad)))

# ---- 2. MILKY WAY: galactocentric kpc, GC at the origin, Sun at (-R0, 0) ------------------------------------------
def helio_to_gc(l, b, d):
    x, y, z = gal_lb_xyz(l, b, d); return x - R0, y, z
mw_cl = []
for c in jload('clusters.json'):
    if c['dist50'] is None: continue
    X, Y, Z = helio_to_gc(c['GLON'], c['GLAT'], c['dist50'] / 1000)
    mw_cl.append([r2(X), r2(Y), round(c['logAge50'] or 8, 1), int(c['N'] or 0)])
ARMS = {'Per': 'Perseus', 'Loc': 'Local (Orion)', 'Nor': 'Norma', 'Out': 'Outer',
        'ScN': 'Scutum-Centaurus', 'ScF': 'Scutum-Centaurus (far side)', 'CtN': 'Scutum-Centaurus', 'OSC': 'Scutum-Centaurus (far side)',
        'SgN': 'Sagittarius-Carina', 'SgF': 'Sagittarius-Carina', 'CrN': 'Sagittarius-Carina',
        '3kN': '3-kpc', '3kF': '3-kpc'}
masers = []; by_arm = {}
for m in jload('masers.json'):
    if not m['plx'] or m['plx'] <= 0: continue
    d = 1.0 / m['plx']                                           # kpc
    g = EQ2GAL.dot(unit(m['RAJ2000'], m['DEJ2000'])); l = math.degrees(math.atan2(g[1], g[0])) % 360; b = math.degrees(math.asin(g[2]))
    X, Y, Z = helio_to_gc(l, b, d)
    arm = ARMS.get((m['Arm'] or '').strip(), '')
    masers.append([m['Name'], r2(X), r2(Y), arm, round(m['e_plx'] / m['plx'], 2) if m['e_plx'] else 0.2])
    if arm: by_arm.setdefault(arm, []).append((X, Y))
# each arm: a log spiral ln R = a + k*beta fitted to its own masers, drawn only across the measured azimuth span
arms = []
for arm, pts in by_arm.items():
    if len(pts) < 8: continue                                    # the 3-kpc arms: six masers, not a spiral to draw
    R = np.hypot([p[0] for p in pts], [p[1] for p in pts]); beta = np.degrees(np.arctan2([p[1] for p in pts], [p[0] for p in pts]))
    b0 = np.median(beta); beta = (beta - b0 + 180) % 360 - 180 + b0          # unwrap around the arm's middle
    k, a = np.polyfit(beta, np.log(R), 1)
    pitch = math.degrees(math.atan(abs(k) * 180 / math.pi))
    lo, hi = float(beta.min()) - 8, float(beta.max()) + 8
    pts_out = [[r2(math.exp(a + k*bb) * math.cos(math.radians(bb))), r2(math.exp(a + k*bb) * math.sin(math.radians(bb)))] for bb in np.linspace(lo, hi, 60)]
    arms.append({'name': arm, 'n': len(pts), 'pitch': round(pitch, 1), 'pts': pts_out, 'a': round(float(a), 5), 'k': round(float(k), 6), 'lo': round(lo, 1), 'hi': round(hi, 1)})
    print('  arm %-20s %3d masers  pitch %.1f deg  beta %.0f..%.0f' % (arm, len(pts), pitch, lo, hi))
json.dump({'what': 'the Milky Way face-on; galactocentric kpc, Galactic Centre at the origin, Sun at (-8.15, 0); x toward the Sun is negative, y along l=90',
           'R0': R0, 'clusters': mw_cl, 'masers': masers, 'arms': arms,
           'bar': {'half_len': 5.0, 'half_wid': 1.5, 'angle': 28, 'note': 'model: a bar ~10 kpc long at ~28 deg to the Sun-centre line (Wegg+ 2015)'},
           'arm_model': 'each arm: ln R = a + k * beta (beta = atan2(y, x) in degrees, unwrapped around the arm), measured over beta lo..hi; the lab extends it beyond that span as a fading model',
           'credit': 'maser parallaxes: Reid+ 2019 (BeSSeL/VERA) · clusters: Hunt & Reffert 2023 (Gaia DR3) · arms: log spirals fitted here to the masers'},
          open(os.path.join(OUT, 'milkyway.json'), 'w'), separators=(',', ':'))
print('milky way: %d clusters, %d masers, %d arms' % (len(mw_cl), len(masers), len(arms)))

# ---- 3. LOCAL GROUP: galactic kpc, Milky Way at the origin -------------------------------------------------------
lg = []
for g in jload('localgroup.json'):
    if g['D'] is None: continue
    nm = (g['Name'] or '').strip(); sub = (g['SubG'] or '').strip()
    if nm in ('The Galaxy', 'Canis Major'): continue
    x, y, z = eq_to_gal_xyz(g['RAJ2000'], g['DEJ2000'], g['D'])
    lg.append([nm, r1(x), r1(y), r1(z), g['VMag'] if g['VMag'] is not None else -6, (g['MType'] or '').strip(), sub])
json.dump({'what': 'the Local Group; heliocentric Galactic xyz in kpc (the Sun sits 8 kpc from the Milky Way centre, invisible at this scale)',
           'galaxies': lg, 'credit': 'McConnachie 2012, The Observed Properties of Dwarf Galaxies in and around the Local Group'},
          open(os.path.join(OUT, 'localgroup.json'), 'w'), separators=(',', ':'))
print('local group: %d galaxies' % len(lg))

# ---- 4. LANIAKEA: 2MRS galaxies, redshift distances, supergalactic Mpc -------------------------------------------
gal = []
for g in jload('twomrs.json'):
    if not g['cz'] or g['cz'] < 300 or g['cz'] > 16000: continue
    d = g['cz'] / H0
    v = GAL2SG.dot(EQ2GAL.dot(unit(g['RAJ2000'], g['DEJ2000']))) * d
    gal.append([r1(v[0]), r1(v[1]), r1(v[2])])
LANDMARKS = [  # name, RA, Dec (deg), distance Mpc -- the well-known clusters and the Great Attractor region
    ['Virgo Cluster', 187.7, 12.4, 16.5], ['Fornax Cluster', 54.6, -35.5, 19], ['Antlia Cluster', 157.5, -35.3, 40],
    ['Centaurus Cluster', 192.2, -41.3, 52], ['Hydra Cluster', 159.2, -27.5, 58], ['Norma Cluster · Great Attractor', 243.9, -60.9, 68],
    ['Perseus Cluster', 49.9, 41.5, 73], ['Coma Cluster', 195.0, 28.0, 100], ['Pavo-Indus', 315.0, -35.0, 60],
    ['Shapley Supercluster', 202.5, -31.5, 200], ['Leo Cluster', 176.1, 19.9, 92], ['Ursa Major', 176.5, 56.0, 20]]
lm = []
for nm, ra, dec, d in LANDMARKS:
    v = GAL2SG.dot(EQ2GAL.dot(unit(ra, dec))) * d; lm.append([nm, r1(v[0]), r1(v[1]), r1(v[2])])
json.dump({'what': 'the local universe out to ~230 Mpc; supergalactic xyz in Mpc, distance = cz / 70 (redshift, so a cluster smears along its line of sight)',
           'galaxies': gal, 'landmarks': lm, 'credit': '2MASS Redshift Survey (Huchra+ 2012), 44,599 galaxies'},
          open(os.path.join(OUT, 'laniakea.json'), 'w'), separators=(',', ':'))
print('laniakea: %d galaxies, %d landmarks' % (len(gal), len(lm)))

# ---- 5. COSMIC WEB: SDSS galaxies in a 2.5-degree equatorial stripe ------------------------------------------------
rows = []
with open(os.path.join(SRC, 'sdss.csv')) as f:
    for ln in f:
        if ln.startswith('#') or ln.startswith('ra'): continue
        ra, dec, z = ln.strip().split(','); rows.append([round(float(ra), 2), round(float(z), 4)])
random.seed(7); random.shuffle(rows); rows = rows[:50000]
# comoving distance table for flat LCDM (Om 0.3), Gly, z = 0 .. 0.32 step 0.004
def dc(z, n=400):
    om = 0.3; c = 299792.458 / H0                                 # Mpc
    zs = np.linspace(0, z, n); E = np.sqrt(om * (1 + zs)**3 + 1 - om)
    return float(np.trapz(1 / E, zs) * c) * 3.26156 / 1000      # Gly
table = [[round(z, 3), round(dc(z), 3)] for z in np.arange(0, 0.3201, 0.004)]
json.dump({'what': 'SDSS spectroscopic galaxies within 1.25 deg of the celestial equator, z < 0.3: [RA deg, z]; distance from the comoving table (flat LCDM, H0 70, Om 0.3), in billions of light-years',
           'galaxies': rows, 'comoving_gly': table, 'stripe_deg': 2.5,
           'credit': 'SDSS DR18 (SkyServer), %d of %d galaxies in the stripe' % (len(rows), len(rows))},
          open(os.path.join(OUT, 'universe.json'), 'w'), separators=(',', ':'))
print('universe: %d galaxies' % len(rows))
for n in sorted(os.listdir(OUT)): print(' ', n, os.path.getsize(os.path.join(OUT, n)), 'bytes')
