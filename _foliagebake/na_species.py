#!/usr/bin/env python3
"""WHICH TREE LEADS, NATIONALLY (2026-10-17). The Northeast bake's species() (_maplab/foliage_bake.py) over na.py's z8
blocks in CONUS: the Forest Service's FHTET modelled basal area per species (30 m, circa 2002), summed per role, lightly
smoothed (SPECIES_BLUR px), the leader drawn where it holds at least SPECIES_MIN_BA square feet an acre and the FIA atlas
types the pixel as forest (na_forest.py's codes). The Northeast's twelve roles, widened with their western and southern
kin and the few colour-makers the Northeast box never held (sweetgum, tulip poplar, sourwood, larch, the western maples,
Gambel oak, cottonwood, juniper). Tiles OUT/species/{z}/{x}/{y}.webp z8 down to z3 by nearest sampling, and
species_meta.json for na.py to carry. Rendered once a season.

    python3 na_species.py OUT SEED_DIR BASE_DIR
"""
import datetime, io, json, os, sys, urllib.parse
import numpy as np
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import na, na_forest

FHP = ('https://imagery.geoplatform.gov/iipp/rest/services/Vegetation/'
       'USFS_EDW_FHP_TreeSpeciesMetrics_BasalArea/ImageServer')
SPECIES = [   # (role, what it does in fall, display rgb, the rasters summed)
    ('SUGAR MAPLE', 'ORANGE TO RED, EARLY OCTOBER', (250, 120, 40), ['sugar_maple', 'black_maple']),
    ('RED MAPLE', 'SCARLET, THE FIRST TO TURN', (215, 45, 40), ['red_maple', 'silver_maple']),
    ('BEECH', 'BRONZE, HOLDS ITS LEAVES', (205, 160, 90), ['American_beech']),
    ('BIRCH', 'CLEAR YELLOW', (250, 225, 95), ['yellow_birch', 'paper_birch', 'sweet_birch', 'gray_birch', 'river_birch']),
    ('ASPEN', 'GOLD, EARLY', (240, 190, 30), ['quaking_aspen', 'bigtooth_aspen']),
    ('RED OAK', 'RUSSET RED, LATE OCTOBER', (165, 65, 50), ['northern_red_oak', 'black_oak', 'scarlet_oak', 'pin_oak',
                                                             'southern_red_oak', 'cherrybark_oak', 'Shumard_oak', 'northern_pin_oak']),
    ('WHITE OAK', 'BROWN AND WINE, THE LAST', (135, 100, 75), ['white_oak', 'chestnut_oak', 'swamp_white_oak', 'post_oak', 'bur_oak']),
    ('HICKORY', 'GOLDEN BROWN', (190, 145, 45), ['hickory_spp', 'shagbark_hickory', 'pignut_hickory', 'mockernut_hickory', 'bitternut_hickory']),
    ('ASH', 'PLUM AND YELLOW, EARLY', (175, 125, 150), ['white_ash', 'green_ash', 'black_ash']),
    ('HEMLOCK', 'EVERGREEN, THE RAVINES', (35, 95, 85), ['eastern_hemlock', 'western_hemlock', 'mountain_hemlock', 'western_redcedar']),
    ('PINE', 'EVERGREEN', (80, 140, 80), ['eastern_white_pine', 'red_pine', 'pitch_pine', 'jack_pine', 'loblolly_pine', 'shortleaf_pine',
                                          'longleaf_pine', 'slash_pine', 'Virginia_pine', 'ponderosa_pine', 'lodgepole_pine']),
    ('SPRUCE, FIR', 'EVERGREEN, THE HIGH GROUND', (22, 74, 52), ['red_spruce', 'black_spruce', 'white_spruce', 'Balsam_fir', 'Norway_spruce',
                                                                  'Engelmann_spruce', 'subalpine_fir', 'Douglas_fir', 'white_fir', 'grand_fir', 'Fraser_fir']),
    # the colour-makers beyond the Northeast box
    ('SWEETGUM', 'WINE, RED AND GOLD, LATE', (190, 70, 60), ['sweetgum']),
    ('TULIP POPLAR', 'CLEAR YELLOW, THE SOUTHERN HILLS', (235, 200, 60), ['yellow_poplar']),
    ('SOURWOOD, BLACKGUM', 'SCARLET, THE SOUTHERN UNDERSTORY', (200, 50, 45), ['sourwood', 'blackgum', 'sassafras', 'flowering_dogwood']),
    ('LARCH', 'GOLD NEEDLES, LATE OCTOBER', (225, 165, 40), ['western_larch', 'subalpine_larch', 'tamarack', 'larch_spp']),
    ('WESTERN MAPLES', 'YELLOW, AND RED IN THE CANYONS', (238, 150, 50), ['bigleaf_maple', 'Rocky_Mountain_maple', 'bigtooth_maple']),
    ('GAMBEL OAK', 'ORANGE AND RUST, THE FOOTHILLS', (185, 95, 45), ['Gambel_oak']),
    ('COTTONWOOD', 'GOLD ALONG THE RIVERS', (215, 185, 70), ['eastern_cottonwood', 'plains_cottonwood', 'narrowleaf_cottonwood',
                                                               'Fremont_cottonwood', 'black_cottonwood', 'balsam_poplar']),
    ('JUNIPER, PINYON', 'EVERGREEN, THE DRY COUNTRY', (110, 130, 90), ['Utah_juniper', 'oneseed_juniper', 'common_pinyon', 'singleleaf_pinyon',
                                                                       'Rocky_Mountain_juniper', 'western_juniper', 'Ashe_juniper', 'eastern_redcedar']),
]
SPECIES_MIN_BA = 5.0
SPECIES_BLUR = 1.4


def blur2d(a, sigma):
    """A separable Gaussian in numpy (PIL will not blur a float image)."""
    r = max(1, int(round(3 * sigma)))
    x = np.arange(-r, r + 1, dtype=np.float32)
    k = np.exp(-0.5 * (x / sigma) ** 2); k /= k.sum()
    pad = np.pad(a, ((0, 0), (r, r)), mode='edge'); out = np.zeros_like(a)
    for i, w in enumerate(k): out += w * pad[:, i:i + a.shape[1]]
    pad = np.pad(out, ((r, r), (0, 0)), mode='edge'); out2 = np.zeros_like(a)
    for i, w in enumerate(k): out2 += w * pad[i:i + a.shape[0], :]
    return out2

def species_raster(bb, fn):
    u = (FHP + '/exportImage?bbox=%.0f,%.0f,%.0f,%.0f&bboxSR=3857&imageSR=3857&size=%d,%d&format=tiff&pixelType=F32'
         '&interpolation=RSP_NearestNeighbor&f=image&renderingRule=%s'
         % (bb + (na.BLK, na.BLK) + (urllib.parse.quote('{"rasterFunction":"%s"}' % fn),)))
    raw = na.get(u, 240)
    # SPARSE TIFFS (2026-10-17): where a species is absent from most of a block the service sends a tiled TIFF whose empty
    # tiles have offset 0; PIL refuses those ("image file is truncated") or, told to load anyway, reads the header as
    # data. tifffile fills empty tiles with zero.
    try:
        import tifffile
        a = np.asarray(tifffile.imread(io.BytesIO(raw)), np.float32)
    except ImportError:
        a = np.array(Image.open(io.BytesIO(raw))).astype(np.float32)
    return np.where(np.isfinite(a) & (a >= 0) & (a <= 400), a, 0.0)

def typed(seed, bx, by):
    """the FIA typed-forest mask on a z8 block, from na_forest.py's z9 codes"""
    work = os.path.join(seed, 'forest_codes'); m = np.zeros((na.BLK, na.BLK), bool)
    for dx in (0, 1):
        for dy in (0, 1):
            f = os.path.join(work, 'c_%d_%d.png' % (2 * bx + dx * 2048, 2 * by + dy * 2048))
            if os.path.exists(f):
                c = np.array(Image.open(f))[::2, ::2] > 0
                m[dy * 1024:(dy + 1) * 1024, dx * 1024:(dx + 1) * 1024] = c
    return m


def main():
    out, seed, base = sys.argv[1], sys.argv[2], sys.argv[3]
    work = os.path.join(seed, 'species_codes'); os.makedirs(work, exist_ok=True)
    blocks = []
    for bx, by in na.all_blocks():
        bb = na.bbox_of(bx, by, na.BLK, na.BLK); E = na.FTG_EXTENT
        if bb[2] < E[0] or bb[0] > E[2] or bb[3] < E[1] or bb[1] > E[3]: continue
        if os.path.exists(os.path.join(base, 'p_%d_%d.npy' % (bx, by))) or typed(seed, bx, by).mean() > 0.002: blocks.append((bx, by))
    print('species: %d blocks x %d rasters' % (len(blocks), sum(len(s[3]) for s in SPECIES)), flush=True)

    def one(b):
        bx, by = b; f = os.path.join(work, 's_%d_%d.png' % b)
        if os.path.exists(f): return
        m = typed(seed, bx, by)
        if not m.any(): Image.fromarray(np.zeros((na.BLK, na.BLK), np.uint8), 'L').save(f); return
        bb = na.bbox_of(bx, by, na.BLK, na.BLK); ba = []
        for role, _, _, fns in SPECIES:
            acc = np.zeros((na.BLK, na.BLK), np.float32)
            for fn in fns:
                try: acc += species_raster(bb, fn)
                except Exception as e: print('species: %s %s failed (%s)' % (b, fn, e), flush=True)
            ba.append(blur2d(acc, SPECIES_BLUR))
        st = np.stack(ba); lead = st.argmax(0).astype(np.uint8) + 1
        codes = np.where((st.max(0) >= SPECIES_MIN_BA) & m, lead, 0).astype(np.uint8)
        Image.fromarray(codes, 'L').save(f, optimize=True)
        print('block', bx, by, '%.0f%% led' % (100 * (codes > 0).mean()), flush=True)
    with ThreadPoolExecutor(4) as ex: list(ex.map(one, blocks))

    pal = np.zeros((len(SPECIES) + 1, 4), np.uint8)
    for i, (_, _, rgb, _) in enumerate(SPECIES): pal[i + 1] = rgb + (218,)
    tot, share = {}, np.zeros(len(SPECIES) + 1)
    for zz in range(na.Z, 2, -1):
        k = 2 ** (na.Z - zz); canv = {}
        for bx, by in blocks:
            c = np.array(Image.open(os.path.join(work, 's_%d_%d.png' % (bx, by))))
            if zz == na.Z:
                share += np.bincount(c.ravel(), minlength=len(SPECIES) + 1)
                tot[zz] = tot.get(zz, 0) + na_forest.save_tiles(c, zz, bx, by, out, pal, 'species'); continue
            c = c[::k, ::k]; ox, oy = bx // k, by // k; h = c.shape[0]
            for j in range(0, h, 256):
                for i in range(0, h, 256):
                    t = ((ox + i) // 256, (oy + j) // 256)
                    cv = canv.setdefault(t, np.zeros((256, 256), np.uint8))
                    s = c[j:j + 256, i:i + 256]; ix, iy = (ox + i) % 256, (oy + j) % 256
                    cv[iy:iy + s.shape[0], ix:ix + s.shape[1]] = np.maximum(cv[iy:iy + s.shape[0], ix:ix + s.shape[1]], s)
        for (tx, ty), cv in canv.items():
            tot[zz] = tot.get(zz, 0) + na_forest.save_tiles(cv, zz, tx * 256, ty * 256, out, pal, 'species')
        print('species z%d: %d tiles' % (zz, tot.get(zz, 0)), flush=True)
    t = share[1:].sum() or 1
    print('species: leaders ' + ', '.join('%s %.0f%%' % (r[0], 100 * share[i + 1] / t) for i, r in enumerate(SPECIES)))
    meta = {'url': na.CDN + 'species/{z}/{x}/{y}.webp', 'minzoom': 3, 'maxzoom': na.Z,
            'source': 'USFS FHTET modeled basal area per species (30 m, circa 2002), leader per pixel, CONUS',
            'legend': [[r, txt, list(rgb)] for r, txt, rgb, _ in SPECIES], 'min_ba': SPECIES_MIN_BA, 'tiles': tot,
            'built': datetime.date.today().isoformat()}
    json.dump(meta, open(os.path.join(seed, 'species_meta.json'), 'w'), separators=(',', ':'))


if __name__ == '__main__':
    main()
