"""THE WHOLE MANTLE, FOR THE CUT WALLS (2026-11-23; user: "can we detail and improve what the core looks like accurately / scientifically in
these slices"). DETOX-P2 (Hosseini et al. 2020, CC BY 4.0, doi 10.5281/zenodo.3993276) averaged to a global 2 deg x 100 km volume so the
cut wall shows the deep mantle's real structure everywhere, not only inside a zone's box -- the two great slow piles at the base of the
mantle (under Africa and the Pacific, the LLSVPs) and the cold slab graveyards. Same encoding as the zone volumes: uint8 = 128 + dVp% x 64,
0 = no data; order z (depth) slowest, then y (lat -90..90), then x (lon -180..180).

Run: python3 _slabbake/tomo_global_bake.py   (needs the DETOX zip unpacked in cache/tomo by tomo_bake.py)  -> out/tomo/global_v1.bin/.json
"""
import json, os
import numpy as np
import tomo_bake as T

STEP = 2.0
DEPTHS = list(range(100, 2851, 100))

def main():
    nx, ny = int(360 / STEP), int(180 / STEP) + 1
    vol = np.zeros((len(DEPTHS), ny, nx), np.uint8)
    lons = -180 + np.arange(nx) * STEP; lats = -90 + np.arange(ny) * STEP
    for k, d in enumerate(DEPTHS):
        z = T.load_layer(d)                       # 0.5 deg, lon 0..360, lat -90..90
        # a box average over each 2 deg cell (the model's real resolution is coarser than its 0.5 deg grid anyway)
        acc = np.zeros((ny, nx)); cnt = np.zeros((ny, nx))
        for oy in (-0.75, -0.25, 0.25, 0.75):
            for ox in (-0.75, -0.25, 0.25, 0.75):
                v = T.sample(z, lons + ox, np.clip(lats + oy, -90, 90)); ok = np.isfinite(v)
                acc[ok] += v[ok]; cnt[ok] += 1
        m = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
        q = np.clip(np.round(T.OFFSET + m * T.SCALE), 1, 255); q[~np.isfinite(m)] = 0
        vol[k] = q.astype(np.uint8)
        print(d, 'km', 'min %.2f max %.2f' % (np.nanmin(m), np.nanmax(m)))
    out = os.path.join(T.OUT); os.makedirs(out, exist_ok=True)
    vol.tofile(os.path.join(out, 'global_v1.bin'))
    json.dump({'model': T.MODEL, 'license': 'CC BY 4.0', 'citation': 'Hosseini et al. 2020, GJI 220(1) 96-141, doi:10.1093/gji/ggz394',
               'nx': nx, 'ny': ny, 'nz': len(DEPTHS), 'lon0': -180, 'lat0': -90, 'step': STEP, 'depths': DEPTHS, 'scale': T.SCALE, 'offset': T.OFFSET},
              open(os.path.join(out, 'global_v1.json'), 'w'))
    print('wrote', vol.nbytes // 1024, 'KB')

if __name__ == '__main__':
    main()
