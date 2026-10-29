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
# COLORS MATCH THE US AND CANADA (user 2026-10-29: "Does Canada/US/Mexico's tree color match? Make sure species match colors"): where
# the trees are the same, the group IS the US fall-color group's color (_foliagebake/na_species.py SPECIES, ca_species.py RGB); pine-oak is
# woven from the pine and oak colors (2 px checks); the tropical types the US maps do not have get colors >= 27 CIE76 Delta E from every
# US color, each other and the old-growth cyan (picked by search over hue windows that keep each type's sense; no purples).
GROUPS = [   # name, what it is, rgb[, second rgb for a weave]
    ('PINE', 'THE HIGH SIERRAS (AS PINE IN THE US)', (80, 140, 80)),
    ('PINE-OAK', 'WOVEN PINE AND OAK: THE SIERRA MADRES, THE COMMONEST FOREST', (80, 140, 80), (135, 100, 75)),
    ('OAK', 'FOOTHILLS AND PLATEAUS (AS WHITE OAK IN THE US)', (135, 100, 75)),
    ('FIR, CYPRESS', 'SACRED FIR, WHERE THE MONARCHS WINTER (AS SPRUCE, FIR IN THE US)', (22, 74, 52)),
    ('JUNIPER', 'THE DRY EDGES (AS JUNIPER, PINYON IN THE US)', (110, 130, 90)),
    ('CLOUD FOREST', 'MISTY MOUNTAINSIDES: SWEETGUM, OAK, TREE FERNS', (38, 191, 176)),
    ('RAINFOREST', 'EVERGREEN, THE SOUTHEAST', (0, 153, 51)),
    ('SEASONAL FOREST', 'SHEDS SOME LEAVES IN THE DRY SEASON', (145, 217, 22)),
    ('DRY FOREST', 'BARE IN THE DRY SEASON, GREEN IN THE RAINS', (242, 235, 182)),
    ('MANGROVE', 'THE COASTS', (22, 103, 217)),
    ('MESQUITE', 'THE DRY NORTH', (173, 168, 160)),
    ('RIVERSIDE', 'ALONG THE RIVERS (AS COTTONWOOD IN THE US)', (215, 185, 70)),
]
TYPES = [   # INEGI CLAVE, English, group index
    ('BP', 'pine forest', 0), ('BPQ', 'pine-oak forest', 1), ('BQP', 'oak-pine forest', 1), ('BQ', 'oak forest', 2),
    ('BA', 'sacred fir (oyamel) forest', 3), ('BS', 'ayarin (Douglas-fir) forest', 3), ('BB', 'cypress (cedro) forest', 3), ('BJ', 'juniper (tascate) forest', 4),
    ('BM', 'cloud forest', 5),
    ('SAP', 'tall evergreen rainforest', 6), ('SAQ', 'tall semi-evergreen rainforest', 6), ('SMQ', 'medium semi-evergreen forest', 6),
    ('SMP', 'medium evergreen forest', 6), ('SBP', 'low evergreen forest', 6), ('SBQP', 'low semi-evergreen forest', 6), ('PT', 'peten (forest islands in the wetlands)', 6),
    ('SMS', 'medium semi-deciduous forest', 7), ('SMC', 'medium deciduous forest', 7), ('SBS', 'low semi-deciduous forest', 7),
    ('SBC', 'low deciduous forest', 8), ('SBK', 'low thorny deciduous forest', 8), ('SBQ', 'low thorny semi-evergreen forest', 8),
    ('VM', 'mangrove', 9), ('MK', 'mesquite forest', 10), ('MKE', 'tropical mesquite', 10),
    ('BG', 'gallery forest', 11), ('SG', 'tropical gallery forest', 11), ('VG', 'riverside woodland', 11),
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
    # palette (idx: 1-28 type, +32 regrowing, +64 the weave's oak pixels of a pine-oak type): the group's exact color, nudged a few
    # blue steps only where needed so every index is a distinct color a tap can read back; pi maps index -> [type, regrowing]
    pal = np.zeros((256, 3), np.int32); seen = set(); pi = {}
    def put(ix, c, ti, reg):
        c = list(c)
        while tuple(c) in seen: c[2] = (c[2] + 1) % 256
        seen.add(tuple(c)); pal[ix] = c; pi[str(ix)] = [ti, reg]
    for sec in (0, 1):
        for i, (_, _, g) in enumerate(TYPES):
            put(i + 1 + 32 * sec, GROUPS[g][2], i + 1, sec)
            if len(GROUPS[g]) > 3: put(i + 1 + 32 * sec + 64, GROUPS[g][3], i + 1, sec)
    weave = np.zeros(256, bool)
    for i, (_, _, g) in enumerate(TYPES):
        if len(GROUPS[g]) > 3: weave[i + 1] = weave[i + 33] = True
    flat = [int(v) for v in pal.ravel()]; trns = bytes([0] + [218] * 127)   # the US and Canada maps' alpha
    ck = ((np.arange(256)[:, None] // 2 + np.arange(256)[None, :] // 2) % 2).astype(bool)   # 2 px checks
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
                tl = np.where(weave[tl] & ck, tl + 64, tl).astype(np.uint8)   # pine-oak: every other 2 px check in the oak color
                dd = os.path.join(out, 'mx', str(z), str(ox + i)); os.makedirs(dd, exist_ok=True)
                im = Image.fromarray(tl, 'P'); im.putpalette(flat); im.save(os.path.join(dd, '%d.png' % (oy + j)), optimize=True, transparency=trns); n += 1
        print('z%d, %d tiles so far' % (z, n), flush=True)
    json.dump({'src': 'INEGI Uso de suelo y vegetacion, Serie VII (1:250,000), via CONAFOR IDEFOR', 'groups': [[q[0], q[1]] + [list(c) for c in q[2:]] for q in GROUPS],
               'types': {str(i + 1): [c, e, g] for i, (c, e, g) in enumerate(TYPES)}, 'pal': {k: list(map(int, pal[int(k)])) for k in pi}, 'pi': pi,
               'zmax': Z}, open(os.path.join(out, 'mx_types.json'), 'w'), separators=(',', ':'))
    # the cells: each group's share of the 0.25 deg cell's land (every pixel counts, forest or not; water too -- close enough)
    px = (x0 * 256 + np.arange(PW) + .5) / (2 ** Z * 256) * 360 - 180
    py = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y0 * 256 + np.arange(PH) + .5) / (2 ** Z * 256)))))
    cj = np.floor((px - CLO0) / .25).astype(np.int64); ci = np.floor((py - CLA0) / .25).astype(np.int64)
    gi = np.zeros(256, np.int64) - 1
    for i, (_, _, g) in enumerate(TYPES): gi[i + 1] = g; gi[i + 33] = g; gi[i + 65] = g; gi[i + 97] = g
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
