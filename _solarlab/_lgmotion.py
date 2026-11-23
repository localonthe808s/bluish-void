"""LOCAL GROUP: who is coming and who is going, and the real galaxies beyond the group (2026-11-22; user: "do 1 2 3 4 5 6").

Source: the Local Volume Database (Pace 2024, CC0) -- the catalogue the Local Group frame is already built from:
  https://raw.githubusercontent.com/apace7/local_volume_database/main/data/dwarf_all.csv
Each galaxy's measured line-of-sight velocity (heliocentric) becomes its velocity relative to the Milky Way's centre (the
Galactic standard of rest: the Sun's own motion, U 11.1, V 12.24 + 233.4, W 7.25 km/s, taken out), so a negative number means
it is coming toward us. Andromeda and Triangulum are giants, not in the dwarf table: their heliocentric velocities are added
(-300 and -179 km/s, NED). Galaxies of the table beyond the Local Group, out to 5 Mpc, become the frame's real background.

Output: galaxy/lg_motion.json = { v: {name: v_gsr km/s}, far: [[name, x, y, z kpc heliocentric Galactic, v_gsr, host]] }
Run: python3 _lgmotion.py <dwarf_all.csv>
"""
import csv, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
T = [[-0.0548755604, 0.4941094279, -0.8676661490], [-0.8734370902, -0.4448296300, -0.1980763734], [-0.4838350155, 0.7469822445, 0.4559837762]]   # galactic -> equatorial
D = math.pi / 180

def gal(ra, dec):
    e = [math.cos(dec * D) * math.cos(ra * D), math.cos(dec * D) * math.sin(ra * D), math.sin(dec * D)]
    g = [T[0][j] * e[0] + T[1][j] * e[1] + T[2][j] * e[2] for j in range(3)]
    return math.atan2(g[1], g[0]) / D, math.asin(max(-1, min(1, g[2]))) / D

def gsr(vh, l, b):
    return vh + 11.1 * math.cos(l * D) * math.cos(b * D) + (12.24 + 233.4) * math.sin(l * D) * math.cos(b * D) + 7.25 * math.sin(b * D)

lg = json.load(open(os.path.join(HERE, 'galaxy', 'localgroup.json')))
mine = {g[0] for g in lg['galaxies']}
v, far = {}, []
for r in csv.DictReader(open(sys.argv[1])):
    try: ra, dec = float(r['ra']), float(r['dec'])
    except ValueError: continue
    l, b = gal(ra, dec)
    vh = r.get('vlos_systemic') or ''
    vg = round(gsr(float(vh), l, b), 1) if vh not in ('', 'nan') else None
    if r['name'] in mine:
        if vg is not None: v[r['name']] = vg
        continue
    try: dm = float(r['distance_modulus'])
    except ValueError: continue
    d = 10 ** (dm / 5 + 1) / 1000                   # kpc
    if d > 5000 or d < 1100: continue
    far.append([r['name'], round(d * math.cos(b * D) * math.cos(l * D), 1), round(d * math.cos(b * D) * math.sin(l * D), 1), round(d * math.sin(b * D), 1), vg, r.get('host') or ''])
for nm, ra, dec, vh in (('Andromeda', 10.6847, 41.2690, -300.0), ('Triangulum', 23.4621, 30.6599, -179.0)):
    l, b = gal(ra, dec); v[nm] = round(gsr(vh, l, b), 1)
json.dump({'what': 'velocities relative to the Milky Way centre (km/s, negative = approaching) and galaxies 1.1-5 Mpc away; Local Volume Database (Pace 2024)', 'v': v, 'far': far},
          open(os.path.join(HERE, 'galaxy', 'lg_motion.json'), 'w'), separators=(',', ':'))
print('velocities', len(v), 'of', len(mine), '| far', len(far), '| Andromeda', v['Andromeda'], 'Triangulum', v['Triangulum'])
