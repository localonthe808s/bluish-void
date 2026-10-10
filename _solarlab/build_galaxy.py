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
# SOURCE SWITCHED 2026-10-10 (user: "is there not a better source?"): Pace 2024, the Local Volume Database
# (github.com/apace7/local_volume_database, CC0), the maintained census current work cites -- every dwarf found since
# McConnachie 2012 (Antlia II, Crater II, the ultra-faints), distances with references, and each dwarf's HOST.
#   lvdb_dwarf_mw.csv, lvdb_dwarf_m31.csv, lvdb_dwarf_local_field.csv from raw.githubusercontent.com/apace7/local_volume_database/main/data/
# Kept: confirmed galaxies within 1.5 Mpc whose host is the Milky Way, the LMC, Andromeda, Triangulum, or none.
# Andromeda and Triangulum themselves are added by hand (they are not dwarfs). The 2012 census stays for the record.
HOSTS = {'mw': 'MW', 'lmc': 'MW', 'm_031': 'M31', 'm_033': 'M31', '': 'Rest'}
lg = []
for fn in ('lvdb_dwarf_mw.csv', 'lvdb_dwarf_m31.csv', 'lvdb_dwarf_local_field.csv'):
    with open(os.path.join(SRC, fn), newline='') as f:
        for r in csv.DictReader(f):
            if r['confirmed_galaxy'] != '1' or r['host'] not in HOSTS: continue
            try: d = float(r['distance']); mv = float(r['M_V'] or -6)
            except ValueError: continue
            if d > 1500: continue
            x, y, z = eq_to_gal_xyz(float(r['ra']), float(r['dec']), d)
            rh = float(r['rhalf_physical']) if r['rhalf_physical'] else 0
            lg.append([r['name'], r1(x), r1(y), r1(z), round(mv, 1), '', HOSTS[r['host']], int(rh)])
for nm, ra, dec, d, mv in (('Andromeda', 10.6847, 41.2690, 783, -21.8), ('Triangulum', 23.4621, 30.6602, 809, -18.8)):
    x, y, z = eq_to_gal_xyz(ra, dec, d); lg.append([nm, r1(x), r1(y), r1(z), mv, 'spiral', 'M31', 0])
print('local group (LVDB): %d galaxies' % len(lg), {h: sum(1 for g in lg if g[6] == h) for h in ('MW', 'M31', 'Rest')})
# the discs of the big ones, as seen from above the Galactic plane: each galaxy's sky orientation (position angle east
# of north, inclination) gives its disc normal; the disc is a circle of radius R around the centre, rotated into
# Galactic xyz and projected on xy. (2026-10-10, user: "the local group feels very minimal still")
#   M31: PA 38, i 77, R 34 kpc (~220,000 ly across) -- de Vaucouleurs; M33: PA 23, i 56, R 9; LMC: PA 170, i 35, R 4.5;
#   SMC: PA 45, i 65, R 2.5. Milky Way: in the plane, R 15, centred 8.15 kpc toward l=0.
def disc(name, ra, dec, d, pa, inc, R, n=48):
    r = unit(ra, dec); north = np.array([-math.sin(math.radians(dec))*math.cos(math.radians(ra)), -math.sin(math.radians(dec))*math.sin(math.radians(ra)), math.cos(math.radians(dec))])
    east = np.cross(np.array([0, 0, 1.0]), r); east /= np.linalg.norm(east)
    major = math.cos(math.radians(pa)) * north + math.sin(math.radians(pa)) * east
    minor = np.cross(r, major); N = math.cos(math.radians(inc)) * r + math.sin(math.radians(inc)) * minor
    a = major; b = np.cross(N, a); c = r * d
    pts = []
    for k in range(n):
        th = 2 * math.pi * k / n; v = EQ2GAL.dot(c + R * (math.cos(th) * a + math.sin(th) * b)); pts.append([r1(v[0]), r1(v[1])])
    cg = EQ2GAL.dot(c); return {'name': name, 'cx': r1(cg[0]), 'cy': r1(cg[1]), 'R': R, 'pts': pts}
discs = [disc('Andromeda', 10.6847, 41.2690, 783, 38, 77, 34), disc('Triangulum', 23.4621, 30.6602, 809, 23, 56, 9),
         disc('LMC', 80.8937, -69.7561, 51, 170, 35, 4.5), disc('SMC', 13.1867, -72.8286, 64, 45, 65, 2.5),
         {'name': 'Milky Way', 'cx': R0, 'cy': 0.0, 'R': 15, 'pts': [[r1(R0 + 15 * math.cos(2*math.pi*k/48)), r1(15 * math.sin(2*math.pi*k/48))] for k in range(48)]}]
json.dump({'what': 'the Local Group; heliocentric Galactic xyz in kpc (the Sun sits 8 kpc from the Milky Way centre, invisible at this scale); discs = the big galaxies projected on the Galactic plane from their sky orientation',
           'galaxies': lg, 'discs': discs, 'barycentre_frac': 0.58, 'credit': 'Local Volume Database (Pace 2024, CC0) · discs: de Vaucouleurs orientations'},
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

# ---- 4b. LANIAKEA from Cosmicflows-4: measured distances, grouped, plus a gravity flow field -----------------------
# (2026-10-10, user: "lets improve laniakea, is there a better source?") Tully+ 2023, VizieR J/ApJ/944/94/table2:
#   SELECT TOP 60000 PGC, "1PGC", Vcmb, DM, e_DM, SGL, SGB  -> cf4.json. 55,877 galaxies with distance moduli (TF, FP,
# SNIa, SBF, TRGB, Cepheids, masers) and supergalactic coordinates. Galaxies sharing a group (1PGC) get one distance,
# the inverse-variance mean of their moduli -- the group averaging Tully uses, which tames the 20% scatter of a
# single Tully-Fisher distance. The flow field: the smoothed galaxy density in the supergalactic plane, its gradient
# baked on a grid; the lab draws streamlines down that gradient (linear theory: matter drains toward overdensity).
cf = jload('cf4.json'); groups = {}
for g in cf:
    if g['DM'] is None or g['SGL'] is None: continue
    k = g['1PGC'] or g['PGC']; w = 1.0 / max(0.05, g['e_DM'] or 0.4) ** 2
    G = groups.setdefault(k, {'wdm': 0.0, 'w': 0.0, 'n': 0, 'sgl': 0.0, 'sgb': 0.0, 'v': 0.0})
    G['wdm'] += w * g['DM']; G['w'] += w; G['n'] += 1; G['sgl'] += g['SGL']; G['sgb'] += g['SGB']; G['v'] += (g['Vcmb'] or 0)
cf_pts = []
for k, G in groups.items():
    dm = G['wdm'] / G['w']; d = 10 ** ((dm - 25) / 5); sgl = G['sgl'] / G['n']; sgb = G['sgb'] / G['n']
    if d > 260: continue
    v = unit(sgl, sgb) * d; cf_pts.append([r1(v[0]), r1(v[1]), r1(v[2]), G['n']])
# the density field: groups within 40 Mpc of the plane, each weighted by its members and by d^2 (flux-limit correction)
L = 140; NG = 112; grid = np.zeros((NG, NG)); cell = 2 * L / NG
for x, y, z, n in cf_pts:
    if abs(z) > 40 or abs(x) >= L or abs(y) >= L: continue
    i = int((y + L) / cell); j = int((x + L) / cell); grid[i, j] += n * min(4.0, max(1.0, (math.hypot(x, y, z) / 40.0) ** 2))   # complete to ~40 Mpc, thinning beyond
# the zone of avoidance: the Galactic plane runs along the SGX axis, so a wedge of ~10 deg either side of it is unseen;
# fill each hidden cell with the mean of the cells at the same radius 10-22 deg away (the usual cloning treatment)
Y, X = np.mgrid[0:NG, 0:NG]; cx = (X + .5) * cell - L; cy = (Y + .5) * cell - L; R = np.hypot(cx, cy); PHI = np.degrees(np.arctan2(cy, cx))
offaxis = np.minimum(np.abs(PHI), np.abs(np.abs(PHI) - 180))
hidden = offaxis < 10; donor = (offaxis >= 10) & (offaxis < 22)
rb = np.clip((R / 8).astype(int), 0, 99)
for b in range(100):
    dsel = donor & (rb == b); hsel = hidden & (rb == b)
    if dsel.any() and hsel.any(): grid[hsel] = grid[dsel].mean()
from scipy.ndimage import gaussian_filter
dens = gaussian_filter(grid, sigma=10.0 / cell)
dens = dens / dens.mean() - 1.0                                     # overdensity delta
gy, gx = np.gradient(dens)                                          # d/dy (rows), d/dx (cols), per cell
mag = np.hypot(gx, gy); print('cf4: %d groups kept, density grid %dx%d, delta max %.1f, |grad| p99 %.3f' % (len(cf_pts), NG, NG, dens.max(), np.percentile(mag, 99)))
json.dump({'what': 'Cosmicflows-4 groups: supergalactic xyz in Mpc from MEASURED distance moduli (inverse-variance group means), members; plus the overdensity field in the supergalactic plane (|SGZ|<40 Mpc, zone of avoidance filled from neighbouring latitudes, 10 Mpc smoothing) and its gradient on a grid spanning +-140 Mpc',
           'groups': cf_pts, 'grid': {'L': L, 'n': NG, 'delta': [[round(float(v), 2) for v in row] for row in dens], 'gx': [[round(float(v), 3) for v in row] for row in gx], 'gy': [[round(float(v), 3) for v in row] for row in gy]},
           'landmarks': lm, 'credit': 'Cosmicflows-4, Tully+ 2023 (55,877 galaxies with measured distances); flow: linear theory on the catalog\'s own density'},
          open(os.path.join(OUT, 'laniakea_cf4.json'), 'w'), separators=(',', ':'))

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
# ---- 6. THE OBSERVABLE UNIVERSE: quasars to the horizon, the rim coloured by the real microwave sky ------------------
# (2026-10-10, user: "can the unobservable universe surround the observable cosmic web?") Same equatorial slice as the
# cosmic web, now out to redshift 7 with SDSS quasars; the last-scattering surface is sampled from NASA's WMAP 9-year
# ILC map (public domain) along the celestial equator, one value per degree of RA, each the mean of a 5x5 patch.
#   quasars.csv   SkyServer: SELECT ra, z FROM SpecObj WHERE class='QSO' AND zWarning=0 AND dec BETWEEN -1.25 AND 1.25
#                 AND z BETWEEN 0.3 AND 7  (format=csv)
#   wmap_ilc.fits https://lambda.gsfc.nasa.gov/data/map/dr5/dfp/ilc/wmap_ilc_9yr_v5.fits  (HEALPix nside 512, NESTED, mK)
qs = []
with open(os.path.join(SRC, 'quasars.csv')) as f:
    for ln in f:
        if ln.startswith('#') or ln.startswith('ra'): continue
        ra, z = ln.strip().split(','); qs.append([round(float(ra), 2), round(float(z), 3)])
random.seed(11); random.shuffle(qs); qs = qs[:32000]
def ang2pix_nest(nside, theta, phi):
    z = math.cos(theta); za = abs(z); tt = (phi % (2*math.pi)) * 2 / math.pi
    if za <= 2/3:
        t1 = nside * (0.5 + tt); t2 = nside * z * 0.75; jp = int(t1 - t2); jm = int(t1 + t2)
        ifp = jp // nside; ifm = jm // nside
        face = (ifp & 3) + 4 if ifp == ifm else ((ifp & 3) if ifp < ifm else (ifm & 3) + 8)
        ix = jm & (nside - 1); iy = nside - (jp & (nside - 1)) - 1
    else:
        ntt = min(3, int(tt)); tp = tt - ntt; tmp = nside * math.sqrt(3 * (1 - za))
        jp = min(int(tp * tmp), nside - 1); jm = min(int((1 - tp) * tmp), nside - 1)
        if z >= 0: face = ntt; ix = nside - jm - 1; iy = nside - jp - 1
        else: face = ntt + 8; ix = jp; iy = jm
    ipf = 0
    for b in range(16): ipf |= ((ix >> b) & 1) << (2*b); ipf |= ((iy >> b) & 1) << (2*b + 1)
    return ipf + face * nside * nside
wm = fits.open(os.path.join(SRC, 'wmap_ilc.fits'))[1]; TMAP = np.asarray(wm.data['TEMPERATURE'], float).ravel(); NSIDE = int(wm.header['NSIDE'])
cmb = []
for ra in range(360):
    acc = []
    for dra in (-0.4, -0.2, 0, 0.2, 0.4):
        for ddec in (-0.4, -0.2, 0, 0.2, 0.4):
            v = EQ2GAL.dot(unit(ra + dra, ddec)); l = math.atan2(v[1], v[0]) % (2*math.pi); b = math.asin(max(-1, min(1, v[2])))
            acc.append(TMAP[ang2pix_nest(NSIDE, math.pi/2 - b, l)])
    cmb.append(round(float(np.mean(acc)) * 1000, 1))       # microkelvin
sm = np.array(cmb); print('cmb along the equator: std %.1f uK, median step %.1f uK (noise-like would be ~%.1f)' % (sm.std(), np.median(np.abs(np.diff(sm))), sm.std()*1.4))
table7 = [[round(z, 2), round(dc(z, 800), 3)] for z in np.arange(0, 7.001, 0.02)]
json.dump({'what': 'the observable universe in the same equatorial slice: SDSS quasars [RA deg, z] to z 7; the microwave background along the celestial equator (WMAP 9-yr ILC, microkelvin, one per degree of RA); horizons in billions of light-years (Planck 2018 cosmology, Davis & Lineweaver 2004)',
           'quasars': qs, 'cmb_uK': cmb, 'comoving_gly': table7,
           'horizons': {'hubble': 14.4, 'event': 16.0, 'last_scattering': 45.7, 'particle': 46.5},
           'farthest': [['JADES-GS-z14-0', 14.32, 33.8], ['MoM-z14', 14.44, 33.9]],
           'beyond': 'the whole universe is at least ~250 times wider than the observable one if finite (Vardanyan, Trotta & Silk 2011)',
           'credit': 'SDSS DR18 quasars · WMAP 9-year ILC map (NASA / LAMBDA) · Planck 2018 · Davis & Lineweaver 2004'},
          open(os.path.join(OUT, 'observable.json'), 'w'), separators=(',', ':'))
print('observable: %d quasars, cmb %d samples' % (len(qs), len(cmb)))
for n in sorted(os.listdir(OUT)): print(' ', n, os.path.getsize(os.path.join(OUT, n)), 'bytes')
