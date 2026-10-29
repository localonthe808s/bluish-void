#!/usr/bin/env python3
"""CANADA'S TREES (user 2026-10-29: "Is there species / tree data we could use for Canada, Mexico?" -> "Go for it"). Natural Resources
Canada's National Forest Inventory kNN maps, 2011 (Beaudoin et al. 2018, Open Government Licence - Canada): for every 250 m MODIS pixel,
each of 75 species or genera as a percent of the stand, and the stand's total wood volume (m3/ha). Three products, made to sit beside the
lower 48's (USFS RDS-2013-0013, _treebake/species.py; the FHTET leader map, _foliagebake/na_species.py):
  - OUT/lead/{z}/{x}/{y}.png z3-8: which fall-color group leads each treed pixel, the same groups and colors as the US map;
  - OUT/sp_ca/<code>.png: each species' wood volume over Canada at ~2 km (the US picture's ramp, scaled to its own 99th percentile);
  - OUT/cells/<la2>_<lo2>.json: the US 0.25-degree "what grows here" packs with Canada added (share of wood volume), border cells merged
    by how many forested pixels each side holds; and OUT/species.json, the US list plus Canada's taxa (FIA codes where they match).
    python3 ca_species.py NFI_DIR US_FULL_DIR OUT"""
import glob, json, math, os, sys, time
import numpy as np, rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.transform import from_bounds as tfb
from rasterio.features import rasterize
from rasterio.windows import transform as wtransform
from pyproj import Transformer
from PIL import Image
# the fall-color groups of _foliagebake/na_species.py, in its order (palette index = position + 1)
ROLES = ['SUGAR MAPLE', 'RED MAPLE', 'BEECH', 'BIRCH', 'ASPEN', 'RED OAK', 'WHITE OAK', 'HICKORY', 'ASH', 'HEMLOCK', 'PINE', 'SPRUCE, FIR',
         'SWEETGUM', 'TULIP POPLAR', 'SOURWOOD, BLACKGUM', 'LARCH', 'WESTERN MAPLES', 'GAMBEL OAK', 'COTTONWOOD', 'JUNIPER, PINYON']
RGB = [(250, 120, 40), (215, 45, 40), (205, 160, 90), (250, 225, 95), (240, 190, 30), (165, 65, 50), (135, 100, 75), (190, 145, 45), (175, 125, 150),
       (35, 95, 85), (80, 140, 80), (22, 74, 52), (190, 70, 60), (235, 200, 60), (200, 50, 45), (225, 165, 40), (238, 150, 50), (185, 95, 45), (215, 185, 70), (110, 130, 90)]
# NFI file tag -> (FIA code, name, scientific name, fall-color group or None)
SP = {
    'Abie_Ama': (11, 'Pacific silver fir', 'Abies amabilis', 'SPRUCE, FIR'), 'Abie_Bal': (12, 'balsam fir', 'Abies balsamea', 'SPRUCE, FIR'),
    'Abie_Las': (19, 'subalpine fir', 'Abies lasiocarpa', 'SPRUCE, FIR'), 'Abie_Spp': (10, 'other firs', 'Abies', 'SPRUCE, FIR'),
    'Acer_Mac': (312, 'bigleaf maple', 'Acer macrophyllum', 'WESTERN MAPLES'), 'Acer_Neg': (313, 'boxelder', 'Acer negundo', None),
    'Acer_Pen': (315, 'striped maple', 'Acer pensylvanicum', None), 'Acer_Rub': (316, 'red maple', 'Acer rubrum', 'RED MAPLE'),
    'Acer_Sac': (317, 'silver maple', 'Acer saccharinum', 'RED MAPLE'), 'Acer_Sah': (318, 'sugar maple', 'Acer saccharum', 'SUGAR MAPLE'),
    'Acer_Spi': (319, 'mountain maple', 'Acer spicatum', None), 'Acer_Spp': (310, 'other maples', 'Acer', None),
    'Alnu_Rub': (351, 'red alder', 'Alnus rubra', None), 'Alnu_Spp': (350, 'alders', 'Alnus', None),
    'Arbu_Men': (361, 'Pacific madrone', 'Arbutus menziesii', None),
    'Betu_All': (371, 'yellow birch', 'Betula alleghaniensis', 'BIRCH'), 'Betu_Pap': (375, 'paper birch', 'Betula papyrifera', 'BIRCH'),
    'Betu_Pop': (379, 'gray birch', 'Betula populifolia', 'BIRCH'), 'Betu_Spp': (370, 'other birches', 'Betula', 'BIRCH'),
    'Carp_Car': (391, 'American hornbeam', 'Carpinus caroliniana', None), 'Cary_Cor': (402, 'bitternut hickory', 'Carya cordiformis', 'HICKORY'),
    'Cham_Noo': (42, 'Alaska yellow-cedar', 'Callitropsis nootkatensis', 'HEMLOCK'), 'Fagu_Gra': (531, 'American beech', 'Fagus grandifolia', 'BEECH'),
    'Frax_Ame': (541, 'white ash', 'Fraxinus americana', 'ASH'), 'Frax_Nig': (543, 'black ash', 'Fraxinus nigra', 'ASH'),
    'Frax_Pen': (544, 'green ash', 'Fraxinus pennsylvanica', 'ASH'),
    'Genc_Spp': (299, 'other conifers', 'Pinophyta', None), 'Genh_Spp': (998, 'other broadleaf trees', 'Magnoliopsida', None),
    'Jugl_Cin': (601, 'butternut', 'Juglans cinerea', 'HICKORY'), 'Jugl_Nig': (602, 'black walnut', 'Juglans nigra', 'HICKORY'),
    'Juni_Vir': (68, 'eastern redcedar', 'Juniperus virginiana', 'JUNIPER, PINYON'),
    'Lari_Lar': (71, 'tamarack', 'Larix laricina', 'LARCH'), 'Lari_Lya': (72, 'subalpine larch', 'Larix lyallii', 'LARCH'),
    'Lari_Occ': (73, 'western larch', 'Larix occidentalis', 'LARCH'), 'Lari_Spp': (70, 'other larches', 'Larix', 'LARCH'),
    'Malu_Spp': (660, 'apples', 'Malus', None), 'Ostr_Vir': (701, 'eastern hophornbeam', 'Ostrya virginiana', None),
    'Pice_Abi': (91, 'Norway spruce', 'Picea abies', 'SPRUCE, FIR'), 'Pice_Eng': (93, 'Engelmann spruce', 'Picea engelmannii', 'SPRUCE, FIR'),
    'Pice_Gla': (94, 'white spruce', 'Picea glauca', 'SPRUCE, FIR'), 'Pice_Mar': (95, 'black spruce', 'Picea mariana', 'SPRUCE, FIR'),
    'Pice_Rub': (97, 'red spruce', 'Picea rubens', 'SPRUCE, FIR'), 'Pice_Sit': (98, 'Sitka spruce', 'Picea sitchensis', 'SPRUCE, FIR'),
    'Pice_Spp': (90, 'other spruces', 'Picea', 'SPRUCE, FIR'),
    'Pinu_Alb': (101, 'whitebark pine', 'Pinus albicaulis', 'PINE'), 'Pinu_Ban': (105, 'jack pine', 'Pinus banksiana', 'PINE'),
    'Pinu_Con': (108, 'lodgepole pine', 'Pinus contorta', 'PINE'), 'Pinu_Mon': (119, 'western white pine', 'Pinus monticola', 'PINE'),
    'Pinu_Pon': (122, 'ponderosa pine', 'Pinus ponderosa', 'PINE'), 'Pinu_Res': (125, 'red pine', 'Pinus resinosa', 'PINE'),
    'Pinu_Spp': (100, 'other pines', 'Pinus', 'PINE'), 'Pinu_Str': (129, 'eastern white pine', 'Pinus strobus', 'PINE'),
    'Pinu_Syl': (130, 'Scotch pine', 'Pinus sylvestris', 'PINE'),
    'Popu_Bal': (741, 'balsam poplar', 'Populus balsamifera', 'COTTONWOOD'), 'Popu_Gra': (743, 'bigtooth aspen', 'Populus grandidentata', 'ASPEN'),
    'Popu_Spp': (740, 'other poplars', 'Populus', 'ASPEN'), 'Popu_Tre': (746, 'quaking aspen', 'Populus tremuloides', 'ASPEN'),
    'Popu_Tri': (747, 'black cottonwood', 'Populus trichocarpa', 'COTTONWOOD'),
    'Prun_Pen': (761, 'pin cherry', 'Prunus pensylvanica', None), 'Prun_Ser': (762, 'black cherry', 'Prunus serotina', None),
    'Pseu_Men': (202, 'Douglas-fir', 'Pseudotsuga menziesii', 'SPRUCE, FIR'),
    'Quer_Alb': (802, 'white oak', 'Quercus alba', 'WHITE OAK'), 'Quer_Mac': (823, 'bur oak', 'Quercus macrocarpa', 'WHITE OAK'),
    'Quer_Rub': (833, 'northern red oak', 'Quercus rubra', 'RED OAK'), 'Quer_Spp': (800, 'other oaks', 'Quercus', 'RED OAK'),
    'Sali_Spp': (920, 'willows', 'Salix', 'COTTONWOOD'), 'Sorb_Ame': (935, 'American mountain-ash', 'Sorbus americana', None),
    'Thuj_Occ': (241, 'northern white-cedar', 'Thuja occidentalis', 'HEMLOCK'), 'Thuj_Pli': (242, 'western redcedar', 'Thuja plicata', 'HEMLOCK'),
    'Tili_Ame': (951, 'American basswood', 'Tilia americana', None),
    'Tsug_Can': (261, 'eastern hemlock', 'Tsuga canadensis', 'HEMLOCK'), 'Tsug_Het': (263, 'western hemlock', 'Tsuga heterophylla', 'HEMLOCK'),
    'Tsug_Mer': (264, 'mountain hemlock', 'Tsuga mertensiana', 'HEMLOCK'), 'Tsug_Spp': (260, 'other hemlocks', 'Tsuga', 'HEMLOCK'),
    'Ulmu_Ame': (972, 'American elm', 'Ulmus americana', None),
}
TREED_MIN = 25      # % of the pixel treed, to draw a leader
LEAD_MIN = 10       # % of the stand the leading group must hold
W0, S0, E0, N0 = -141.0, 41.6, -52.0, 70.0          # Canada, mercator box for the range pictures and the z8 leader canvas
OW = 3950                                            # ~2 km a pixel, the US pictures' scale
CLA0, CLO0 = 24.0, -125.0                            # the US cell grid's origin (cells extend it, same 0.25 deg step)
def mercy(la): return np.log(np.tan(np.pi / 4 + np.radians(la) / 2))
def tx(lo, z): return (lo + 180) / 360 * 2 ** z
def ty(la, z): r = math.radians(la); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z
def nfi(d, tag): return glob.glob(os.path.join(d, '*_%s_v1.tif' % tag))[0]
# THE BORDER (2026-10-29): the kNN maps run on past it into the US (a Vermont cell came out "Canadian"), so every NFI pixel inside the
# US (Natural Earth 1:50m) is dropped; the US side is the USFS maps' alone. NE = path to ne_50m_admin_0_countries.shp
_US = {}
def us_geom(crs):
    if crs.to_string() not in _US:
        import shapefile
        from shapely.geometry import shape, mapping
        from shapely.ops import transform as stransform
        r = shapefile.Reader(os.environ['NE']); i = [f[0] for f in r.fields[1:]].index('ADM0_A3')
        g = [shape(sr.shape.__geo_interface__) for sr in r.shapeRecords() if sr.record[i] == 'USA'][0]
        fwd = Transformer.from_crs('EPSG:4326', crs, always_xy=True).transform
        _US[crs.to_string()] = mapping(stransform(fwd, g))
    return _US[crs.to_string()]
def in_us(crs, transform, shp): return rasterize([(us_geom(crs), 1)], out_shape=shp, transform=transform, fill=0, dtype='uint8').astype(bool)

def lead_map(d, out):
    """pass A, full 250 m: the leading fall-color group of each treed pixel, then web-mercator palette tiles z8..z3"""
    ds = {k: rasterio.open(nfi(d, 'Species_' + k)) for k in SP}; tr = rasterio.open(nfi(d, 'LandCover_VegTreed'))
    H, W = tr.height, tr.width; lead = np.zeros((H, W), np.uint8); ri = {r: i for i, r in enumerate(ROLES)}
    S = 256
    for y in range(0, H, S):
        win = ((y, min(y + S, H)), (0, W)); h = win[0][1] - y
        acc = np.zeros((len(ROLES), h, W), np.float32)
        for k, (_, _, _, role) in SP.items():
            if role is None: continue
            a = ds[k].read(1, window=win).astype(np.float32); a[~np.isfinite(a)] = 0; a[(a < 0) | (a > 100)] = 0; acc[ri[role]] += a
        t = tr.read(1, window=win).astype(np.float32)
        us = in_us(tr.crs, wtransform(win, tr.transform), (h, W))
        best = acc.max(0); lead[y:y + h] = np.where((best >= LEAD_MIN) & (t >= TREED_MIN) & (t <= 100) & ~us, acc.argmax(0) + 1, 0)
        if y % 4096 == 0: print('lead rows', y, H, flush=True)
    Z = 8; x0, x1 = int(tx(W0, Z)), int(tx(E0, Z)) + 1; y0, y1 = int(ty(N0, Z)), int(ty(S0, Z)) + 1
    PW, PH = (x1 - x0) * 256, (y1 - y0) * 256
    m0 = Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True)
    R = 20037508.342789244; mx0 = x0 / 2 ** Z * 2 * R - R; mx1 = x1 / 2 ** Z * 2 * R - R; my0 = R - y0 / 2 ** Z * 2 * R; my1 = R - y1 / 2 ** Z * 2 * R
    mos = np.zeros((PH, PW), np.uint8)
    reproject(lead, mos, src_transform=tr.transform, src_crs=tr.crs, dst_transform=tfb(mx0, my1, mx1, my0, PW, PH), dst_crs='EPSG:3857',
              resampling=Resampling.mode, src_nodata=0, dst_nodata=0)
    del lead
    flat = [0, 0, 0]; [flat.extend(c) for c in RGB]; flat += [0] * (768 - len(flat)); trns = bytes([0] + [218] * len(RGB))
    share = np.bincount(mos.ravel(), minlength=len(ROLES) + 1); n = 0
    lv, ox, oy = mos, x0, y0
    for z in range(Z, 2, -1):
        if z < Z:   # halve by the commoner leader of each 2x2 (the max code breaks ties)
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
                dd = os.path.join(out, 'lead', str(z), str(ox + i)); os.makedirs(dd, exist_ok=True)
                im = Image.fromarray(tl, 'P'); im.putpalette(flat); im.save(os.path.join(dd, '%d.png' % (oy + j)), optimize=True, transparency=trns); n += 1
        print('lead z%d done, %d tiles so far' % (z, n), flush=True)
    t = share[1:].sum() or 1
    print('leaders: ' + ', '.join('%s %.0f%%' % (r, 100 * share[i + 1] / t) for i, r in enumerate(ROLES) if share[i + 1]), flush=True)

def ranges_and_cells(d, usdir, out):
    """pass B, 1 km: each species' wood volume -> its range picture and the 0.25 deg cell shares"""
    D = 4
    tr = rasterio.open(nfi(d, 'Structure_Volume_Total')); H, W = tr.height // D, tr.width // D
    T = tr.transform * tr.transform.scale(tr.width / W, tr.height / H); crs = tr.crs
    vol = tr.read(1, out_shape=(H, W), resampling=Resampling.average).astype(np.float32); vol[~np.isfinite(vol) | (vol < 0) | (vol > 3000)] = 0
    vol[in_us(crs, T, (H, W))] = 0   # every species is scaled by vol, so this drops the US side from the pictures and the cells
    xs = T.c + (np.arange(W) + .5) * T.a; ys = T.f + (np.arange(H) + .5) * T.e
    X, Y = np.meshgrid(xs, ys); lo, la = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True).transform(X, Y); del X, Y
    ci = np.floor((la - CLA0) / .25).astype(np.int64); cj = np.floor((lo - CLO0) / .25).astype(np.int64)
    ci0, cj0 = int(ci.min()), int(cj.min()); NI, NJ = int(ci.max()) - ci0 + 1, int(cj.max()) - cj0 + 1
    cid = ((ci - ci0) * NJ + (cj - cj0)).ravel(); del lo, la
    NC = NI * NJ; tot = np.bincount(cid, vol.ravel(), minlength=NC); nfor = np.bincount(cid, (vol > 5).ravel().astype(np.float64), minlength=NC)
    OH = int(round(OW * (mercy(N0) - mercy(S0)) / np.radians(E0 - W0)))
    olo = W0 + (np.arange(OW) + .5) / OW * (E0 - W0); oy = mercy(N0) - (np.arange(OH) + .5) / OH * (mercy(N0) - mercy(S0))
    ola = np.degrees(2 * np.arctan(np.exp(oy)) - np.pi / 2); OLO, OLA = np.meshgrid(olo, ola)
    ax, ay = Transformer.from_crs('EPSG:4326', crs, always_xy=True).transform(OLO, OLA); del OLO, OLA
    pc = np.floor((ax - T.c) / T.a).astype(np.int64); pr = np.floor((ay - T.f) / T.e).astype(np.int64)
    inn = (pc >= 0) & (pc < W) & (pr >= 0) & (pr < H); pc = np.clip(pc, 0, W - 1); pr = np.clip(pr, 0, H - 1)
    ramp = np.array([[198, 232, 156], [120, 198, 96], [46, 150, 72], [12, 98, 52], [4, 58, 34]], float)
    os.makedirs(os.path.join(out, 'sp_ca'), exist_ok=True); per = {}; meta = {}
    for k, (code, nm, sci, _) in SP.items():
        t0 = time.time()
        with rasterio.open(nfi(d, 'Species_' + k)) as r: a = r.read(1, out_shape=(H, W), resampling=Resampling.average).astype(np.float32)
        a[~np.isfinite(a) | (a < 0) | (a > 100)] = 0; a = a / 100 * vol          # this species' wood, m3/ha
        if a.max() <= 0: continue
        per[code] = np.bincount(cid, a.ravel(), minlength=NC).astype(np.float32)
        o = np.where(inn, a[pr, pc], 0); pos = o[o > 0]; p99 = float(np.percentile(pos, 99)) if pos.size else 1.0
        tt = np.clip(o / max(p99, 1e-3), 0, 1); idx = np.minimum(3.999, tt * 4); i0 = idx.astype(int); fr = (idx - i0)[..., None]
        rgb = ramp[i0] * (1 - fr) + ramp[np.minimum(i0 + 1, 4)] * fr
        alpha = np.where(o > p99 * .03, np.clip(60 + 195 * np.sqrt(tt), 0, 255), 0)
        Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8)).save(os.path.join(out, 'sp_ca', '%d.png' % code), optimize=True)
        meta[code] = {'c': code, 'n': nm, 'sci': sci, 'cp99': round(p99, 1), 'ccover': int((o > p99 * .03).sum())}
        print(k, nm, 'p99 %.1f m3/ha' % p99, '%.1fs' % (time.time() - t0), flush=True)
    # the species list: the US one, Canada's taxa marked (ca) or added (us: 0)
    S = json.load(open(os.path.join(usdir, 'species.json'))); have = {q['c']: q for q in S['sp']}
    for code, m in meta.items():
        if code in have: q = have[code]; q['ca'] = 1; q['cp99'] = m['cp99']; q['ccover'] = m['ccover']
        else: m.update({'us': 0, 'ca': 1, 'p99': 0, 'cover': 0}); S['sp'].append(m)
    S['sp'].sort(key=lambda q: -(q.get('cover', 0) + q.get('ccover', 0)))
    S['box_ca'] = [W0, S0, E0, N0]; S['src_ca'] = 'NRCan National Forest Inventory kNN species composition 2011 (Beaudoin et al. 2018), Open Government Licence - Canada'
    S['unit_ca'] = 'm3/ha'
    json.dump(S, open(os.path.join(out, 'species.json'), 'w'), separators=(',', ':'))
    # the cell packs: Canada's shares (of wood volume) merged into the US packs
    packs = {}
    for f in glob.glob(os.path.join(usdir, 'cells', '*.json')): packs[os.path.basename(f)[:-5]] = json.load(open(f))
    codes = list(per.keys()); M = np.stack([per[c] for c in codes]); nca = 0
    for c in np.nonzero(tot > 0)[0]:
        sh = M[:, c] / tot[c]; top = np.argsort(-sh)[:12]
        row = [[int(codes[i]), round(float(sh[i]) * 100, 1)] for i in top if sh[i] >= .005]
        if not row: continue
        i, j = divmod(int(c), NJ); la0 = CLA0 + (i + ci0) * .25; lo0 = CLO0 + (j + cj0) * .25
        key = '%d_%d' % (int(math.floor(la0 / 2) * 2), int(math.floor(lo0 / 2) * 2)); ck = '%.2f_%.2f' % (la0, lo0)
        P = packs.setdefault(key, {}); us = P.get(ck); n_ca = float(nfor[c])
        if us and us.get('sp'):   # a border cell: weigh each side by its forested 1 km pixels (the US side by its area share left)
            n_us = max(1.0, 448 - n_ca); w = n_ca / (n_ca + n_us); mix = {}   # ~448 1 km pixels in a 0.25 deg cell at 49 N
            for q in us['sp']: mix[q[0]] = mix.get(q[0], 0) + q[1] * (1 - w)
            for q in row: mix[q[0]] = mix.get(q[0], 0) + q[1] * w
            row = sorted([[k2, round(v, 1)] for k2, v in mix.items() if v >= .5], key=lambda q: -q[1])[:12]
            P[ck] = dict(us, sp=row, ca=1)
        else: P[ck] = {'sp': row, 'ca': 1, 'v': round(float(tot[c] / max(1, n_ca)), 0)}   # v: mean wood volume of its forest, m3/ha
        nca += 1
    os.makedirs(os.path.join(out, 'cells'), exist_ok=True)
    for k2, v in packs.items(): json.dump(v, open(os.path.join(out, 'cells', k2 + '.json'), 'w'), separators=(',', ':'))
    print(len(meta), 'Canadian taxa,', nca, 'Canadian cells,', len(packs), 'packs', flush=True)

if __name__ == '__main__':
    d, us, out = sys.argv[1:4]; os.makedirs(out, exist_ok=True)
    if 'B' not in sys.argv[4:]: lead_map(d, out)
    if 'A' not in sys.argv[4:]: ranges_and_cells(d, us, out)
