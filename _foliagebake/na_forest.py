#!/usr/bin/env python3
"""THE FOREST ITSELF, NATIONALLY (2026-10-17). The Northeast bake's forest() (_maplab/foliage_bake.py) for the whole of
CONUS: USFS FIA Forest Atlas, Forest Type Groups, 250 m, from the USGS geoplatform image service, decoded through its own
legend swatches and painted in the Northeast's role palette (FOREST_ROLES; the western groups the Northeast box never
held are folded into their nearest kin). Cut as tiles OUT/forest/{z}/{x}/{y}.webp, z9 (305 m, the atlas's own scale) down
to z3 by nearest sampling, like the 1x frame the Northeast draws. Rendered once a season; writes forest_meta.json (url,
zooms, legend, roles) for na.py to carry in meta.json.

    python3 na_forest.py OUT SEED_DIR [--mask BASE_DIR]
--mask: also add the FIA western golds (na.FIA_GOLD) to the forest mask of every cached block in BASE_DIR; a block that
was skipped as forestless and now passes na.py's 0.2% rule has its cache removed, so the next na.py run builds it.
"""
import datetime, json, os, sys
import numpy as np
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import na

FOREST_ROLES = [   # (label as the atlas prints it, our role, display rgb) -- the Northeast's thirteen, then the West
    ('Maple/Beech/Birch Group', 'THE SHOW', (232, 108, 38)),
    ('Aspen/Birch Group', 'NORTH GOLD', (244, 208, 56)),
    ('Elm/Ash/Cottonwood Group', 'RIVER GOLD', (206, 176, 104)),
    ('Oak/Hickory Group', 'LATE, RUSSET', (168, 106, 58)),
    ('Oak/Pine Group', 'LATE, RUSSET', (156, 112, 60)),
    ('Oak/Gum/Cypress Group', 'LATE, RUSSET', (160, 118, 62)),
    ('Spruce/Fir Group', 'SPRUCE, FIR', (22, 74, 52)),
    ('White/Red/Jack Pine Group', 'PINE', (78, 142, 78)),
    ('Loblolly/Shortleaf Pine Group', 'PINE', (84, 148, 80)),
    ('Longleaf/Slash Pine Group', 'PINE', (84, 148, 80)),
    ('Pinyon/Juniper Group', 'PINE', (80, 140, 78)),
    ('Douglas-fir Group', 'SPRUCE, FIR', (26, 80, 54)),
    ('Exotic Softwoods Group', 'PINE', (82, 144, 80)),
    ('Western Larch Group', 'NORTH GOLD', (236, 196, 60)),
    ('Alder/Maple Group', 'RIVER GOLD', (200, 170, 100)),
    ('Other Western Hardwoods Group', 'RIVER GOLD', (204, 174, 102)),
    ('Western Oak Group', 'LATE, RUSSET', (164, 110, 60)),
    ('Tanoak/Laurel Group', 'LATE, RUSSET', (158, 114, 62)),
    ('Ponderosa Pine Group', 'PINE', (82, 146, 80)),
    ('Lodgepole Pine Group', 'PINE', (76, 138, 76)),
    ('Western White Pine Group', 'PINE', (80, 142, 78)),
    ('California Mixed Conifer Group', 'PINE', (78, 140, 78)),
    ('Other Western Softwoods Group', 'PINE', (80, 140, 78)),
    ('Fir/Spruce/Mountain Hemlock Grou', 'SPRUCE, FIR', (24, 76, 52)),
    ('Hemlock/Sitka Spruce Group', 'SPRUCE, FIR', (26, 82, 56)),
    ('Redwood Group', 'SPRUCE, FIR', (28, 78, 54)),
]
FOREST_LEGEND = [('THE SHOW', 'MAPLE, BEECH, BIRCH', (232, 108, 38)), ('LATE, RUSSET', 'OAK, HICKORY', (168, 106, 58)),
                 ('NORTH GOLD', 'ASPEN, BIRCH, LARCH', (244, 208, 56)), ('RIVER GOLD', 'ELM, ASH, COTTONWOOD, ALDER', (206, 176, 104)),
                 ('PINE', 'PONDEROSA, LODGEPOLE, SOUTHERN PINES', (78, 142, 78)),
                 ('SPRUCE, FIR', 'FIR, SPRUCE, HEMLOCK, DOUGLAS-FIR', (22, 74, 52))]
ZMAX, ZMIN, B9 = 9, 3, 2048
VERSION = 'v1'


def px9(x, y):
    n = 256 * 2 ** ZMAX; mpp = na.WORLD / n
    return int((x + na.WORLD / 2) / mpp), int((na.WORLD / 2 - y) / mpp)

def bbox9(bx, by):
    n = 256 * 2 ** ZMAX; mpp = na.WORLD / n
    return (-na.WORLD / 2 + bx * mpp, na.WORLD / 2 - (by + B9) * mpp, -na.WORLD / 2 + (bx + B9) * mpp, na.WORLD / 2 - by * mpp)

def palette():
    pal = np.zeros((len(FOREST_ROLES) + 1, 4), np.uint8)
    for i, (_, _, rgb) in enumerate(FOREST_ROLES): pal[i + 1] = rgb + (218,)
    return pal

def save_tiles(codes, zz, ox, oy, out, pal, sub='forest'):
    h, w = codes.shape; n = 0
    for j in range(0, h, 256):
        for i in range(0, w, 256):
            c = codes[j:j + 256, i:i + 256]
            if not c.any(): continue
            tx, ty = (ox + i) // 256, (oy + j) // 256
            d = os.path.join(out, sub, str(zz), str(tx)); os.makedirs(d, exist_ok=True)
            Image.fromarray(pal[c], 'RGBA').save(os.path.join(d, '%d.webp' % ty), 'WEBP', quality=82, alpha_quality=80, method=4); n += 1
    return n


def main():
    out, seed = sys.argv[1], sys.argv[2]
    work = os.path.join(seed, 'forest_codes'); os.makedirs(work, exist_ok=True)
    cols = na.ftg_colors(); pal = palette()
    lut = {}
    for i, (lab, _, _) in enumerate(FOREST_ROLES):
        c = cols.get(lab)
        if c: lut[(c[0] << 16) | (c[1] << 8) | c[2]] = i + 1
        else: print('forest: no swatch for', lab)
    x0, y0 = px9(na.FTG_EXTENT[0], na.FTG_EXTENT[3]); x1, y1 = px9(na.FTG_EXTENT[2], na.FTG_EXTENT[1])
    blocks = [(bx, by) for bx in range(x0 // B9 * B9, x1, B9) for by in range(y0 // B9 * B9, y1, B9)]
    print('forest: %d z9 blocks' % len(blocks), flush=True)

    def one(b):
        bx, by = b; f = os.path.join(work, 'c_%d_%d.png' % b)
        if os.path.exists(f): return
        a = na.ftg_rgb(bbox9(bx, by), B9, B9).astype(np.uint32)
        key = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
        uk, inv = np.unique(key, return_inverse=True)
        codes = np.array([lut.get(int(k), 0) for k in uk], np.uint8)[inv].reshape(key.shape)
        Image.fromarray(codes, 'L').save(f, optimize=True)
        print('block', bx, by, '%.0f%% typed' % (100 * (codes > 0).mean()), flush=True)
    with ThreadPoolExecutor(4) as ex: list(ex.map(one, blocks))

    tot = {}
    for zz in range(ZMAX, ZMIN - 1, -1):
        k = 2 ** (ZMAX - zz); canv = {}
        for bx, by in blocks:
            c = np.array(Image.open(os.path.join(work, 'c_%d_%d.png' % (bx, by))))[::k, ::k]
            if zz == ZMAX:
                tot[zz] = tot.get(zz, 0) + save_tiles(c, zz, bx, by, out, pal); continue
            ox, oy = bx // k, by // k; h = c.shape[0]
            for j in range(0, h, 256):
                for i in range(0, h, 256):
                    t = ((ox + i) // 256, (oy + j) // 256)
                    cv = canv.setdefault(t, np.zeros((256, 256), np.uint8))
                    sub = c[j:j + 256, i:i + 256]; ix, iy = (ox + i) % 256, (oy + j) % 256
                    cv[iy:iy + sub.shape[0], ix:ix + sub.shape[1]] = np.maximum(cv[iy:iy + sub.shape[0], ix:ix + sub.shape[1]], sub)
        for (tx, ty), cv in canv.items():
            tot[zz] = tot.get(zz, 0) + save_tiles(cv, zz, tx * 256, ty * 256, out, pal)
        print('forest z%d: %d tiles' % (zz, tot.get(zz, 0)), flush=True)
    meta = {'url': na.CDN + 'forest/{z}/{x}/{y}.webp', 'minzoom': ZMIN, 'maxzoom': ZMAX, 'version': VERSION,
            'source': 'USFS FIA Forest Atlas, Forest Type Groups (250 m, CONUS)',
            'legend': [[r, txt, list(rgb)] for r, txt, rgb in FOREST_LEGEND],
            'roles': [[lab, role] for lab, role, _ in FOREST_ROLES], 'tiles': tot,
            'built': datetime.date.today().isoformat()}
    json.dump(meta, open(os.path.join(seed, 'forest_meta.json'), 'w'), separators=(',', ':'))
    print('forest tiles', tot)

    if '--mask' in sys.argv:
        base = sys.argv[sys.argv.index('--mask') + 1]
        def upd(b):
            bx, by = b; f = os.path.join(base, 'b_%d_%d.npz' % b)
            if not os.path.exists(f): return
            g = na.fia_gold(na.bbox_of(bx, by, na.BLK, na.BLK), na.BLK, na.BLK)
            if g is None or not g.any(): return
            z = np.load(f); bs, fm = z['base'], z['forest']
            if bs.size == 1:
                if g.mean() >= 0.002:
                    os.remove(f); print('mask: block', bx, by, 'now forest (%.1f%% gold), cache removed' % (100 * g.mean()), flush=True)
                return
            add = int((g & ~fm).sum())
            np.savez_compressed(f, base=bs, forest=fm | g)
            print('mask: block', bx, by, '+%d gold pixels' % add, flush=True)
        with ThreadPoolExecutor(4) as ex: list(ex.map(upd, na.all_blocks()))


if __name__ == '__main__':
    main()
