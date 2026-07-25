#!/usr/bin/env python3
"""Bake _starfield.js — a real star catalog for the solar lab background.

Source: d3-celestial stars.6.json (BSD-3, data derived from the HYG database,
CC BY-SA — credit "HYG / d3-celestial" if this ever ships on the site).

The lab shows the solar system top-down from the north ecliptic pole, so the
sky is projected the same way (azimuthal equidistant): angle = ecliptic
longitude (0° right, CCW), radius = (90° − ecliptic latitude) / 90° × MAP_R.
The ecliptic itself (β=0, the zodiac band where the planets sit) lands exactly
on Neptune's display rim; stars south of the ecliptic spill into the corners.

    curl -sL -o /tmp/stars6.json \\
      https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/stars.6.json
    python3 build_starfield.py
"""
import json, math, pathlib

OBLIQ = math.radians(23.4392911)
MAG_LIMIT = 6.0      # full naked-eye depth of stars.6.json
LAT_MIN = -85.0      # wide windows show far beyond the square viewBox —
                     # keep nearly the whole sky so corners never go empty

def equ_to_ecl(ra_deg, dec_deg):
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    sb = math.sin(dec)*math.cos(OBLIQ) - math.cos(dec)*math.sin(OBLIQ)*math.sin(ra)
    beta = math.degrees(math.asin(max(-1, min(1, sb))))
    lam = math.degrees(math.atan2(
        math.sin(ra)*math.cos(OBLIQ) + math.tan(dec)*math.sin(OBLIQ),
        math.cos(ra)))
    return lam % 360, beta

stars = []
for f in json.load(open('/tmp/stars6.json'))['features']:
    mag = f['properties']['mag']
    if mag > MAG_LIMIT:
        continue
    ra, dec = f['geometry']['coordinates']
    ra = ra % 360
    lam, beta = equ_to_ecl(ra, dec)
    if beta < LAT_MIN:
        continue
    try:
        bv = float(f['properties'].get('bv') or 0.5)
    except ValueError:
        bv = 0.5
    stars.append([round(lam, 1), round(beta, 1), round(mag, 1), round(bv, 2)])
stars.sort(key=lambda s: s[2])

# Galactic → ecliptic (IAU NGP: RA 192.8595°, Dec 27.1283°, l_NCP 122.932°)
agp, dgp, lncp = math.radians(192.8595), math.radians(27.1283), math.radians(122.932)
def gal_to_ecl(l_deg, b_deg):
    lr, br = math.radians(l_deg), math.radians(b_deg)
    sdec = math.cos(br)*math.cos(dgp)*math.cos(lncp - lr) + math.sin(br)*math.sin(dgp)
    dec = math.asin(max(-1, min(1, sdec)))
    y = math.cos(br)*math.sin(lncp - lr)
    x = math.sin(br)*math.cos(dgp) - math.cos(br)*math.sin(dgp)*math.cos(lncp - lr)
    ra = math.degrees(agp + math.atan2(y, x)) % 360
    return equ_to_ecl(ra, math.degrees(dec))

gal = [list(gal_to_ecl(l, 0)) for l in range(0, 361, 4)]

# Warp grid for the ESO panorama: at each 4° of galactic longitude, the ecliptic
# coords of the band's top (b=+20°) and bottom (b=−20°) edge. The lab maps each
# 4°-wide slice of milkyway.webp onto its projected quad with an affine matrix.
GAL_B = 20
galgrid = []
for l in range(0, 361, 2):
    t = gal_to_ecl(l, GAL_B)
    b = gal_to_ecl(l, -GAL_B)
    galgrid.append([round(t[0], 1), round(t[1], 1), round(b[0], 1), round(b[1], 1)])

# Constellation stick figures — d3-celestial constellations.lines.json (IAU
# figures). Vertices converted to ecliptic; constellations whose mean latitude
# is deep south are dropped (the polar projection smears them off-canvas).
#     curl -sL -o /tmp/conlines.json \\
#       https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/constellations.lines.json
con_lines = []
try:
    cd = json.load(open('/tmp/conlines.json'))
    for f in cd['features']:
        geo = f['geometry']
        coords = geo['coordinates']
        if geo['type'] == 'LineString':
            coords = [coords]
        lines, lats = [], []
        for seg in coords:
            pts = []
            for ra, dec in seg:
                lam, beta = equ_to_ecl(ra % 360, dec)
                pts.append([round(lam, 1), round(beta, 1)])
                lats.append(beta)
            lines.append(pts)
        if lats and sum(lats)/len(lats) > -35:
            con_lines.append({'id': f['id'], 'l': lines})
    print('constellations kept:', len(con_lines))
except FileNotFoundError:
    print('constellation source missing — skipping')

# Famous stars (J2000 RA/Dec) worth a tiny label on the chart.
NAMED = [
    ('SIRIUS', 101.287, -16.716), ('BETELGEUSE', 88.793, 7.407),
    ('RIGEL', 78.634, -8.202),    ('ALDEBARAN', 68.980, 16.509),
    ('CAPELLA', 79.172, 45.998),  ('POLLUX', 116.329, 28.026),
    ('PROCYON', 114.825, 5.225),  ('REGULUS', 152.093, 11.967),
    ('SPICA', 201.298, -11.161),  ('ARCTURUS', 213.915, 19.182),
    ('ANTARES', 247.352, -26.432),('VEGA', 279.235, 38.784),
    ('ALTAIR', 297.696, 8.868),   ('DENEB', 310.358, 45.280),
    ('PLEIADES', 56.75, 24.117),  ('FOMALHAUT', 344.413, -29.622),
]
named = []
for name, ra, dec in NAMED:
    lam, beta = equ_to_ecl(ra, dec)
    if beta >= LAT_MIN - 4:
        named.append([round(lam, 1), round(beta, 1), name])

# Zodiac constellations at their real IAU ecliptic-longitude midpoints.
ZODIAC = [['ARIES',42],['TAURUS',71],['GEMINI',104],['CANCER',128],['LEO',156],
          ['VIRGO',196],['LIBRA',229],['SCORPIUS',244],['OPHIUCHUS',257],
          ['SAGITTARIUS',283],['CAPRICORNUS',314],['AQUARIUS',340],['PISCES',11]]

out = pathlib.Path(__file__).resolve().parent / '_starfield.js'
out.write_text(
    '/* AUTO-GENERATED by build_starfield.py — real night sky for the solar lab.\n'
    '   Stars: HYG database via d3-celestial stars.6.json (mag ≤ %.1f, ecl lat ≥ %.0f°).\n'
    '   Format: STARS = [eclLon°, eclLat°, mag, B−V][]. Credit: HYG / d3-celestial. */\n'
    % (MAG_LIMIT, LAT_MIN)
    + 'var STARS=' + json.dumps(stars, separators=(',', ':')) + ';\n'
    + 'var GALPLANE=' + json.dumps(gal, separators=(',', ':')) + ';\n'
    + 'var GALGRID=' + json.dumps(galgrid, separators=(',', ':')) + ';\n'
    + 'var GAL_B=' + str(GAL_B) + ';\n'
    + 'var CONST_LINES=' + json.dumps(con_lines, separators=(',', ':')) + ';\n'
    + 'var NAMED_STARS=' + json.dumps(named, separators=(',', ':')) + ';\n'
    + 'var ZODIAC=' + json.dumps(ZODIAC, separators=(',', ':')) + ';\n')
print('wrote _starfield.js: %d stars, %d gal points, %d named' %
      (len(stars), len(gal), len(named)))
