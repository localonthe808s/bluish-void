"""learn a raster's look (rgba by hillshade/relief/elevation on land, by depth/relief at sea) off an existing
bake, then bake another box with it. python3 lut2.py learn <img> <X0,Y0,X1,Y1> <grid.nc> <prefix>
                                      python3 lut2.py bake <X0,Y0,X1,Y1> <W> <H> <grid.nc> <prefix> <out.png>"""
import sys, math, numpy as np, netCDF4 as nc
from PIL import Image
from scipy.ndimage import uniform_filter, gaussian_filter
R = 6378137.0
def load(p):
    d = nc.Dataset(p); nx, ny = [int(v) for v in d['dimension'][:]]
    z = np.array(d['z'][:], dtype=np.float32).reshape(ny, nx)
    return z, float(d['x_range'][0]), float(d['y_range'][1]), float(d['spacing'][0]), float(d['spacing'][1])
def sample(G, box, W, H):
    z, LON0, LAT1, DLON, DLAT = G; NY, NX = z.shape
    X0, Y0, X1, Y1 = box
    lon = (X0 + (np.arange(W) + 0.5) / W * (X1 - X0)) / R * 180 / math.pi
    ys = Y1 - (np.arange(H) + 0.5) / H * (Y1 - Y0); lat = (2 * np.arctan(np.exp(ys / R)) - math.pi / 2) * 180 / math.pi
    fx = (lon - LON0) / DLON - 0.5; fy = (LAT1 - lat) / DLAT - 0.5
    x0 = np.clip(np.floor(fx).astype(int), 0, NX - 2); y0 = np.clip(np.floor(fy).astype(int), 0, NY - 2)
    tx = np.clip(fx - x0, 0, 1)[None, :]; ty = np.clip(fy - y0, 0, 1)[:, None]
    Z = z[y0][:, x0] * (1 - tx) * (1 - ty) + z[y0][:, x0 + 1] * tx * (1 - ty) + z[y0 + 1][:, x0] * (1 - tx) * ty + z[y0 + 1][:, x0 + 1] * tx * ty
    return Z, (X1 - X0) / W * math.cos(math.radians(40.7))
def feats(Z, mpp):
    Zs = gaussian_filter(Z, 1.0); gy, gx = np.gradient(Zs, mpp)
    az, alt = math.radians(315), math.radians(45)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return hs, Z - uniform_filter(Z, 15)
def bins(Z, hs, rel):
    return (np.clip(((hs + 0.2) / 1.4 * 24).astype(int), 0, 23), np.clip(((rel + 150) / 300 * 16).astype(int), 0, 15),
            np.clip((Z / 150).astype(int), 0, 11), np.clip((-Z / 25).astype(int), 0, 239), np.clip(((rel + 300) / 600 * 8).astype(int), 0, 7))
def learn(img, box, grid, pre):
    im = np.array(Image.open(img).convert('RGBA')).astype(float); H, W, _ = im.shape
    Z, mpp = sample(load(grid), box, W, H); hs, rel = feats(Z, mpp); hb, rb, eb, db, orb = bins(Z, hs, rel)
    land = Z >= 0; train = land & ~((im[..., 2] > im[..., 0] + 30) & (im[..., 3] > 120))
    lut = np.zeros((24, 16, 12, 4)); cnt = np.zeros((24, 16, 12))
    np.add.at(lut, (hb[train], rb[train], eb[train]), im[train]); np.add.at(cnt, (hb[train], rb[train], eb[train]), 1)
    L = np.where(cnt[..., None] > 0, lut / np.maximum(cnt, 1)[..., None], np.nan)
    with np.errstate(all='ignore'):
        for ax in (2, 1, 0):
            m = np.nanmean(L, axis=ax, keepdims=True); L = np.where(np.isnan(L), np.broadcast_to(m, L.shape), L)
    L = np.where(np.isnan(L), im[train].mean(0), L)
    sea = ~land; ol = np.zeros((240, 8, 4)); oc = np.zeros((240, 8))
    np.add.at(ol, (db[sea], orb[sea]), im[sea]); np.add.at(oc, (db[sea], orb[sea]), 1)
    O = np.where(oc[..., None] > 0, ol / np.maximum(oc, 1)[..., None], np.nan)
    with np.errstate(all='ignore'):
        m = np.nanmean(O, axis=1, keepdims=True); O = np.where(np.isnan(O), np.broadcast_to(m, O.shape), O)
    for i in range(240):
        if np.isnan(O[i]).any(): O[i] = O[i - 1] if i else im[sea].mean(0)
    np.save(pre + '_land.npy', L); np.save(pre + '_sea.npy', O)
    out = np.where(land[..., None], L[hb, rb, eb], O[db, orb]); err = np.abs(out - im)
    print('reproduction: RGB err %.1f alpha err %.1f | land alpha %.1f sea rgb %.1f' % (err[..., :3].mean(), err[..., 3].mean(), err[land][:, 3].mean(), err[sea][:, :3].mean()))
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(pre + '_rebake.png')
def bake(box, W, H, grid, pre, outp):
    Z, mpp = sample(load(grid), box, W, H); hs, rel = feats(Z, mpp); hb, rb, eb, db, orb = bins(Z, hs, rel)
    L = np.load(pre + '_land.npy'); O = np.load(pre + '_sea.npy')
    out = np.where((Z >= 0)[..., None], L[hb, rb, eb], O[db, orb])
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(outp); np.save(outp + '.Z.npy', Z)
if __name__ == '__main__':
    bx = lambda s: tuple(float(v) for v in s.split(','))
    if sys.argv[1] == 'learn': learn(sys.argv[2], bx(sys.argv[3]), sys.argv[4], sys.argv[5])
    else: bake(bx(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], sys.argv[6], sys.argv[7])
