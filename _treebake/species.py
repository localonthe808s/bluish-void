#!/usr/bin/env python3
"""EVERY TREE, WHERE IT GROWS (user 2026-10-29: SPECIES, "do 2"). USFS Wilson et al. 2013, Live tree species basal area of the contiguous US
(RDS-2013-0013, public domain): 324 species, basal area (sq ft / acre) at 250 m, Albers. Two products from one pass:
  - trees/sp/<code>.png: the species over the lower 48 in web mercator at ~2 km, one ramp (alpha and color by basal area, scaled to
    the species' own 99th percentile) -- what SPECIES draws when a tree is picked;
  - trees/cells/<la2>_<lo2>.json: for each 0.25 deg cell, the species there by share of the cell's basal area (top 12) -- "what grows here".
    python3 species.py RASTER_DIR METRICS_CSV OUTDIR [codes...]"""
import csv, json, os, sys, time
import numpy as np, rasterio
from rasterio.enums import Resampling
from pyproj import Transformer
from PIL import Image
D = 4                                    # 250 m -> 1 km read
W0, S0, E0, N0 = -125.0, 24.0, -66.5, 49.6   # mercator output box
OW = 2600
def mercy(la): return np.log(np.tan(np.pi / 4 + np.radians(la) / 2))
def main(rdir, metrics, out, *only):
    names = {}
    for r in csv.reader(open(metrics, encoding='latin-1')):
        try: names[int(r[2])] = (r[0].strip(), r[1].strip())
        except Exception: pass
    files = sorted(f for f in os.listdir(rdir) if f.endswith('.img'))
    if only: files = [f for f in files if f[1:-4] in only]
    os.makedirs(os.path.join(out, 'sp'), exist_ok=True); os.makedirs(os.path.join(out, 'cells'), exist_ok=True)
    with rasterio.open(os.path.join(rdir, files[0])) as r0:
        H, W = r0.height // D, r0.width // D; T = r0.transform * r0.transform.scale(r0.width / W, r0.height / H); crs = r0.crs
    # the 1 km grid's cell ids (0.25 deg) and the mercator output's lookup into it
    xs = T.c + (np.arange(W) + .5) * T.a; ys = T.f + (np.arange(H) + .5) * T.e
    tr = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    X, Y = np.meshgrid(xs, ys); lo, la = tr.transform(X, Y)
    ci = np.floor((la - 24) / .25).astype(np.int32); cj = np.floor((lo + 125) / .25).astype(np.int32)
    NC, NJ = 104, 236; ok = (ci >= 0) & (ci < NC) & (cj >= 0) & (cj < NJ); cid = np.where(ok, ci * NJ + cj, NC * NJ)
    OH = int(round(OW * (mercy(N0) - mercy(S0)) / np.radians(E0 - W0)))
    olo = W0 + (np.arange(OW) + .5) / OW * (E0 - W0); oy = mercy(N0) - (np.arange(OH) + .5) / OH * (mercy(N0) - mercy(S0))
    ola = np.degrees(2 * np.arctan(np.exp(oy)) - np.pi / 2); OLO, OLA = np.meshgrid(olo, ola)
    ax, ay = Transformer.from_crs('EPSG:4326', crs, always_xy=True).transform(OLO, OLA)
    pc = np.floor((ax - T.c) / T.a).astype(np.int64); pr = np.floor((ay - T.f) / T.e).astype(np.int64)
    inn = (pc >= 0) & (pc < W) & (pr >= 0) & (pr < H); pc = np.clip(pc, 0, W - 1); pr = np.clip(pr, 0, H - 1)
    ramp = np.array([[198, 232, 156], [120, 198, 96], [46, 150, 72], [12, 98, 52], [4, 58, 34]], float)
    tot = np.zeros(NC * NJ + 1); per = {}; meta = []
    for k, f in enumerate(files):
        t0 = time.time(); code = int(f[1:-4])
        with rasterio.open(os.path.join(rdir, f)) as r:
            a = r.read(1, out_shape=(H, W), resampling=Resampling.average).astype(np.float32)
            nd = r.nodata
        a[~np.isfinite(a)] = 0; a[a < 0] = 0
        if nd is not None: a[a == nd] = 0
        if a.max() <= 0: continue
        s = np.bincount(cid.ravel(), a.ravel(), minlength=NC * NJ + 1); tot += s; per[code] = s.astype(np.float32)
        o = np.where(inn, a[pr, pc], 0); pos = o[o > 0]
        p99 = float(np.percentile(pos, 99)) if pos.size else 1.0
        t = np.clip(o / max(p99, 1e-3), 0, 1); idx = np.minimum(3.999, t * 4); i0 = idx.astype(int); fr = (idx - i0)[..., None]
        rgb = ramp[i0] * (1 - fr) + ramp[np.minimum(i0 + 1, 4)] * fr
        alpha = np.where(o > p99 * .03, np.clip(60 + 195 * np.sqrt(t), 0, 255), 0)
        Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8)).save(os.path.join(out, 'sp', '%d.png' % code), optimize=True)
        nm = names.get(code, ('species %d' % code, ''))
        meta.append({'c': code, 'n': nm[0], 'sci': nm[1], 'p99': round(p99, 1), 'cover': int((o > p99 * .03).sum())})
        print(k, f, nm[0], '%.1fs' % (time.time() - t0), flush=True)
    meta.sort(key=lambda m: -m['cover'])
    json.dump({'src': 'USFS RDS-2013-0013 (Wilson et al. 2013), live tree basal area, public domain', 'box': [W0, S0, E0, N0], 'unit': 'sq ft/acre', 'sp': meta},
              open(os.path.join(out, 'species.json'), 'w'), separators=(',', ':'))
    # what grows in each cell, packed in 2-degree files
    codes = list(per.keys()); M = np.stack([per[c] for c in codes]); packs = {}; npx = np.bincount(cid.ravel(), minlength=NC * NJ + 1)
    for c in range(NC * NJ):
        if tot[c] <= 0: continue
        sh = M[:, c] / tot[c]; top = np.argsort(-sh)[:12]
        row = [[int(codes[i]), round(float(sh[i]) * 100, 1)] for i in top if sh[i] >= .005]
        i, j = divmod(c, NJ); la0 = 24 + i * .25; lo0 = -125 + j * .25
        key = '%d_%d' % (int(np.floor(la0 / 2) * 2), int(np.floor(lo0 / 2) * 2))
        packs.setdefault(key, {})['%.2f_%.2f' % (la0, lo0)] = {'ba': round(float(tot[c] / max(1, npx[c])), 1), 'sp': row}   # ba: the cell's mean live basal area, sq ft/acre
    for k, v in packs.items(): json.dump(v, open(os.path.join(out, 'cells', k + '.json'), 'w'), separators=(',', ':'))
    print(len(meta), 'species,', len(packs), 'cell packs')
if __name__ == '__main__': main(*sys.argv[1:])
