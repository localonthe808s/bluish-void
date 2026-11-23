#!/usr/bin/env python3
"""Bake DETOX-P2 (Hosseini et al. 2020, CC BY 4.0) dVp% into per-zone uint8 volumes.

Source: https://zenodo.org/records/3993276 (DETOX_MODELS.zip), grid_nc4 layers
DETOX-P2_<depth>.grd = 0.5 deg global grids (lon 0..360, lat -90..90), every 50 km.
Output: out/tomo/<zone>_v1.bin  uint8, index = (k*ny + j)*nx + i,
        value = clip(round(128 + dVp*64), 1, 255), 0 = no data.
"""
import json, os, sys
import numpy as np
import netCDF4 as N

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = 'DETOX-P2'
SRC = os.path.join(HERE, 'cache/tomo/DETOX_MODELS', MODEL, 'grid_nc4')
OUT = os.path.join(HERE, 'out/tomo')
ZONES = os.path.join(HERE, 'out/slab/zones_v1.json')
DEPTHS = list(range(50, 2851, 50))
STEP = 0.5
SCALE, OFFSET = 64, 128


def load_layer(d):
    ds = N.Dataset(os.path.join(SRC, '%s_%.2f.grd' % (MODEL, d)))
    lon = ds['lon'][:].astype(float); lat = ds['lat'][:].astype(float)
    z = np.array(ds['z'][:], dtype=np.float64)  # (lat, lon)
    ds.close()
    assert abs(lon[0]) < 1e-9 and abs(lon[1] - lon[0] - STEP) < 1e-9 and abs(lat[0] + 90) < 1e-9
    return z


def sample(z, lons, lats):
    """bilinear on the 0.5-deg grid; lons any range (wrapped to 0..360)."""
    x = (np.mod(lons, 360.0)) / STEP; y = (lats + 90.0) / STEP
    X, Y = np.meshgrid(x, y)
    x0 = np.clip(np.floor(X).astype(int), 0, z.shape[1] - 2); y0 = np.clip(np.floor(Y).astype(int), 0, z.shape[0] - 2)
    fx = X - x0; fy = Y - y0
    v = (z[y0, x0] * (1 - fx) * (1 - fy) + z[y0, x0 + 1] * fx * (1 - fy)
         + z[y0 + 1, x0] * (1 - fx) * fy + z[y0 + 1, x0 + 1] * fx * fy)
    return v  # NaN propagates -> no data


def main():
    zones = json.load(open(ZONES))['zones']
    os.makedirs(OUT, exist_ok=True)
    grids = {}
    for z_id, zv in zones.items():
        w, s, e, n = zv['box']
        nx = int(round((e - w) / STEP)) + 1; ny = int(round((n - s) / STEP)) + 1
        grids[z_id] = (np.linspace(w, e, nx), np.linspace(s, n, ny))
    vols = {k: np.zeros((len(DEPTHS), len(g[1]), len(g[0])), np.uint8) for k, g in grids.items()}
    for k, d in enumerate(DEPTHS):
        z = load_layer(d)
        for z_id, (lons, lats) in grids.items():
            v = sample(z, lons, lats)
            q = np.clip(np.round(OFFSET + v * SCALE), 1, 255)
            q[~np.isfinite(v)] = 0
            vols[z_id][k] = q.astype(np.uint8)
    idx = {
        'model': MODEL,
        'citation': ('Hosseini, K., Sigloch, K., Tsekhmistrenko, M., Zaheri, A., Nissen-Meyer, T., Igel, H. (2020). '
                     'Global mantle structure from multifrequency tomography using P, PP and P-diffracted waves. '
                     'Geophysical Journal International 220(1), 96-141.'),
        'doi': '10.1093/gji/ggz394',
        'url': 'https://doi.org/10.5281/zenodo.3993276',
        'download': 'https://zenodo.org/api/records/3993276/files/DETOX_MODELS.zip/content',
        'license': 'CC BY 4.0',
        'license_evidence': {
            'quote': 'Creative Commons Attribution 4.0 International',
            'url': 'https://zenodo.org/records/3993276',
            'api': 'https://zenodo.org/api/records/3993276 -> metadata.license.id = "cc-by-4.0"'},
        'param': 'dVp', 'units': 'percent (dVp/Vp vs IASP91)',
        'scale': SCALE, 'offset': OFFSET, 'nodata': 0,
        'encode': 'round(offset + dVp*scale) clipped 1..255',
        'order': 'z slowest, then y (south->north), then x (west->east); index = (k*ny + j)*nx + i',
        'step_deg': STEP, 'depths': DEPTHS,
        'interp': 'bilinear horizontal on the 0.5-deg model grid; model layers coincide with the depths (no depth interpolation)',
        'zones': {},
    }
    for z_id, vol in vols.items():
        lons, lats = grids[z_id]
        vol.tofile(os.path.join(OUT, '%s_v1.bin' % z_id))
        idx['zones'][z_id] = {'box': zones[z_id]['box'], 'nx': len(lons), 'ny': len(lats), 'nz': len(DEPTHS)}
    json.dump(idx, open(os.path.join(OUT, 'index_v1.json'), 'w'), indent=1)
    print('wrote', len(vols), 'zones')


if __name__ == '__main__':
    main()
