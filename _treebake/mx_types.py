#!/usr/bin/env python3
"""MEXICO'S FORESTS (user 2026-10-29, "Go for it" on Canada + Mexico tree data). Mexico publishes no species map: its national inventory
(CONAFOR INFyS) records species on field plots only. What it does map is the forest TYPE: INEGI's land use and vegetation, Serie VII
(1:250,000, 2018 imagery; via CONAFOR's IDEFOR WFS geonode:cdv_usuev250svii_cnal_wgs84, fields CLAVE / DESCRIPCIO), and Mexico's
forests are largely named for their trees (pine, pine-oak, oak, sacred fir). Every tree-forming type, primary or regrowing ("VSA/",
secondary vegetation with trees), in eleven groups:
  - OUT/mx/{z}/{x}/{y}.png z3-9: palette index = the INEGI type (1-31; +32 = regrowing), color = its group, so a tap reads the type back;
  - OUT/mx_types.json: the groups and the type table;
  - the 0.25 deg "what grows here" packs (OUT/cells, made by ca_species.py) get 'ft': [[group, % of the cell's land], ...].
    python3 mx_types.py FOREST_GEOJSON OUT"""
import glob, json, math, os, sys
import numpy as np
from PIL import Image
from rasterio.features import rasterize
from rasterio.transform import from_bounds as tfb
from shapely.geometry import shape, mapping
from shapely.ops import transform as stransform
from pyproj import Transformer
GROUPS = [   # name, what it is, rgb
    ('PINE', 'THE HIGH SIERRAS', (80, 140, 80)),
    ('PINE-OAK', 'THE SIERRA MADRES, THE COMMONEST FOREST', (128, 138, 62)),
    ('OAK', 'FOOTHILLS AND PLATEAUS', (156, 104, 62)),
    ('FIR, CYPRESS, JUNIPER', 'SACRED FIR (WHERE THE MONARCHS WINTER), CYPRESS, JUNIPER', (22, 74, 52)),
    ('CLOUD FOREST', 'MISTY MOUNTAINSIDES: SWEETGUM, OAK, TREE FERNS', (38, 128, 138)),
    ('RAINFOREST', 'EVERGREEN, THE SOUTHEAST', (14, 104, 66)),
    ('SEASONAL FOREST', 'SHEDS SOME LEAVES IN THE DRY SEASON', (128, 172, 80)),
    ('DRY FOREST', 'BARE IN THE DRY SEASON, GREEN IN THE RAINS', (200, 172, 92)),
    ('MANGROVE', 'THE COASTS', (56, 146, 168)),
    ('MESQUITE', 'THE DRY NORTH', (176, 150, 112)),
    ('RIVERSIDE', 'ALONG THE RIVERS', (214, 186, 70)),
]
TYPES = [   # INEGI CLAVE, English, group index
    ('BP', 'pine forest', 0), ('BPQ', 'pine-oak forest', 1), ('BQP', 'oak-pine forest', 1), ('BQ', 'oak forest', 2),
    ('BA', 'sacred fir (oyamel) forest', 3), ('BS', 'ayarin (Douglas-fir) forest', 3), ('BB', 'cypress (cedro) forest', 3), ('BJ', 'juniper (tascate) forest', 3),
    ('BM', 'cloud forest', 4),
    ('SAP', 'tall evergreen rainforest', 5), ('SAQ', 'tall semi-evergreen rainforest', 5), ('SMQ', 'medium semi-evergreen forest', 5),
    ('SMP', 'medium evergreen forest', 5), ('SBP', 'low evergreen forest', 5), ('SBQP', 'low semi-evergreen forest', 5), ('PT', 'peten (forest islands in the wetlands)', 5),
    ('SMS', 'medium semi-deciduous forest', 6), ('SMC', 'medium deciduous forest', 6), ('SBS', 'low semi-deciduous forest', 6),
    ('SBC', 'low deciduous forest', 7), ('SBK', 'low thorny deciduous forest', 7), ('SBQ', 'low thorny semi-evergreen forest', 7),
    ('VM', 'mangrove', 8), ('MK', 'mesquite forest', 9), ('MKE', 'tropical mesquite', 9),
    ('BG', 'gallery forest', 10), ('SG', 'tropical gallery forest', 10), ('VG', 'riverside woodland', 10),
]
Z = 9; W0, S0, E0, N0 = -118.5, 14.4, -86.6, 32.8
CLA0, CLO0 = 24.0, -125.0
def tx(lo, z): return (lo + 180) / 360 * 2 ** z
def ty(la, z): r = math.radians(la); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z

def main(src, out):
    idx = {c: i + 1 for i, (c, _, _) in enumerate(TYPES)}
    G = json.load(open(src)); fwd = Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True).transform; shapes = []
    for f in G['features']:
        c = f['properties']['CLAVE']; sec = c.startswith('VSA/'); k = idx.get(c[4:] if sec else c)
        if not k or not f.get('geometry'): continue
        shapes.append((mapping(stransform(fwd, shape(f['geometry']))), k + (32 if sec else 0)))
    print(len(shapes), 'forest polygons', flush=True)
    x0, x1 = int(tx(W0, Z)), int(tx(E0, Z)) + 1; y0, y1 = int(ty(N0, Z)), int(ty(S0, Z)) + 1; PW, PH = (x1 - x0) * 256, (y1 - y0) * 256
    R = 20037508.342789244; mx0 = x0 / 2 ** Z * 2 * R - R; mx1 = x1 / 2 ** Z * 2 * R - R; my0 = R - y0 / 2 ** Z * 2 * R; my1 = R - y1 / 2 ** Z * 2 * R
    mos = rasterize(shapes, out_shape=(PH, PW), transform=tfb(mx0, my1, mx1, my0, PW, PH), fill=0, dtype='uint8')
    # palette: each type its group's color, regrowing a touch paler; every index a distinct color so a tap can read it back
    pal = np.zeros((256, 3), np.int32); seen = set()
    rank = {}
    for i, (_, _, g) in enumerate(TYPES):
        rk = rank[g] = rank.get(g, -1) + 1   # types of one group 6 shades apart in blue: the same color to the eye, apart to a tap
        for sec in (0, 1):
            c = np.array(GROUPS[g][2], float); c = c + (255 - c) * .22 if sec else c; c[2] = min(255, c[2] + 6 * rk); c = tuple(int(round(v)) for v in c)
            while c in seen: c = (c[0], c[1], (c[2] + 1) % 256)
            seen.add(c); pal[i + 1 + 32 * sec] = c
    flat = [int(v) for v in pal.ravel()]; trns = bytes([0] + [225] * 63)
    n = 0; lv, ox, oy = mos, x0, y0
    for z in range(Z, 2, -1):
        if z < Z:   # halve by the commoner type of each 2x2
            if ox % 2: lv = np.pad(lv, ((0, 0), (256, 0))); ox -= 1
            if oy % 2: lv = np.pad(lv, ((256, 0), (0, 0))); oy -= 1
            if lv.shape[1] % 512: lv = np.pad(lv, ((0, 0), (0, 512 - lv.shape[1] % 512)))
            if lv.shape[0] % 512: lv = np.pad(lv, ((0, 512 - lv.shape[0] % 512), (0, 0)))
            q = [lv[0::2, 0::2], lv[0::2, 1::2], lv[1::2, 0::2], lv[1::2, 1::2]]
            cnt = [sum((a == b) & (b > 0) for b in q) for a in q]; pick = np.argmax(np.stack(cnt), 0)
            lv = np.choose(pick, q).astype(np.uint8); ox //= 2; oy //= 2
        for j in range(lv.shape[0] // 256):
            for i in range(lv.shape[1] // 256):
                tl = lv[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256]
                if not tl.any(): continue
                dd = os.path.join(out, 'mx', str(z), str(ox + i)); os.makedirs(dd, exist_ok=True)
                im = Image.fromarray(tl, 'P'); im.putpalette(flat); im.save(os.path.join(dd, '%d.png' % (oy + j)), optimize=True, transparency=trns); n += 1
        print('z%d, %d tiles so far' % (z, n), flush=True)
    json.dump({'src': 'INEGI Uso de suelo y vegetacion, Serie VII (1:250,000), via CONAFOR IDEFOR', 'groups': [[a, b, list(c)] for a, b, c in GROUPS],
               'types': {str(i + 1): [c, e, g] for i, (c, e, g) in enumerate(TYPES)}, 'pal': {str(i): list(map(int, pal[i])) for i in range(64) if pal[i].any()},
               'zmax': Z}, open(os.path.join(out, 'mx_types.json'), 'w'), separators=(',', ':'))
    # the cells: each group's share of the 0.25 deg cell's land (every pixel counts, forest or not; water too -- close enough)
    px = (x0 * 256 + np.arange(PW) + .5) / (2 ** Z * 256) * 360 - 180
    py = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y0 * 256 + np.arange(PH) + .5) / (2 ** Z * 256)))))
    cj = np.floor((px - CLO0) / .25).astype(np.int64); ci = np.floor((py - CLA0) / .25).astype(np.int64)
    gi = np.zeros(64, np.int64) - 1
    for i, (_, _, g) in enumerate(TYPES): gi[i + 1] = g; gi[i + 33] = g
    ci0, cj0 = ci.min(), cj.min(); NI, NJ = ci.max() - ci0 + 1, cj.max() - cj0 + 1; NG = len(GROUPS)
    cnt = np.zeros((NI * NJ, NG)); tot = np.zeros(NI * NJ)
    for r in range(PH):
        cid = (ci[r] - ci0) * NJ + (cj - cj0); g = gi[mos[r]]
        tot += np.bincount(cid, minlength=NI * NJ)
        ok = g >= 0
        if ok.any(): np.add.at(cnt, (cid[ok], g[ok]), 1)
    packs = {}
    for f in glob.glob(os.path.join(out, 'cells', '*.json')): packs[os.path.basename(f)[:-5]] = json.load(open(f))
    nn = 0
    for c in np.nonzero(cnt.sum(1) > 0)[0]:
        sh = cnt[c] / tot[c]; row = [[int(g), round(float(sh[g]) * 100, 1)] for g in np.argsort(-sh) if sh[g] >= .005]
        if not row: continue
        i, j = divmod(int(c), int(NJ)); la0 = CLA0 + (i + ci0) * .25; lo0 = CLO0 + (j + cj0) * .25
        key = '%d_%d' % (int(math.floor(la0 / 2) * 2), int(math.floor(lo0 / 2) * 2)); ck = '%.2f_%.2f' % (la0, lo0)
        P = packs.setdefault(key, {}); P[ck] = dict(P.get(ck, {}), ft=row); nn += 1
    os.makedirs(os.path.join(out, 'cells'), exist_ok=True)
    for k2, v in packs.items(): json.dump(v, open(os.path.join(out, 'cells', k2 + '.json'), 'w'), separators=(',', ':'))
    print(nn, 'Mexican cells', flush=True)

if __name__ == '__main__': main(*sys.argv[1:3])
