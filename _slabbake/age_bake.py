"""SEA-FLOOR AGE bake for the subduction globe (2026-11-23).

Source: Seton et al. 2020, G-Cubed, doi:10.1029/2020GC009214 -- EarthByte present-day ocean-floor age grid v2020.1,
GTS2012 timescale, 6 arc-minute, gridline-registered. CC BY 4.0 (LICENSE.txt in the same EarthByte folder).
  https://www.earthbyte.org/webdav/ftp/earthbyte/agegrid/2020/Grids/age.2020.1.GTS2012.6m.nc

Writes out/age/age_color.png  2048x1024 RGBA equirectangular, age ramp orange (0 Ma) -> blue (180+ Ma), land alpha 0
       out/age/age_u8.png     1024x512  L    equirectangular, round(age) clipped 0..254, 255 = no data
Resampling is bilinear with NaN-aware normalized weights (no speckle at coasts).

Run: python3 _slabbake/age_bake.py
"""
import os, json
import numpy as np
import netCDF4
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'cache', 'age', 'age.2020.1.GTS2012.6m.nc')
OUT = os.path.join(HERE, 'out', 'age')

# ramp stops (Ma, hex) -- warm young to deep-blue old, no purple/magenta
STOPS = [(0, '#fb923c'), (15, '#f59e0b'), (35, '#facc15'), (60, '#84cc16'), (85, '#22c55e'),
         (110, '#14b8a6'), (140, '#0891b2'), (165, '#2563eb'), (180, '#1d4ed8')]


def load():
    d = netCDF4.Dataset(SRC)
    lon = d.variables['lon'][:].data; lat = d.variables['lat'][:].data
    z = d.variables['z'][:]
    z = np.where(np.ma.getmaskarray(z), np.nan, np.ma.getdata(z)).astype(np.float64)
    assert abs(lon[0] + 180) < 1e-6 and abs(lat[0] + 90) < 1e-6 and len(lon) == 3601 and len(lat) == 1801
    return z  # z[iy, ix], iy=0 -> -90, ix=0 -> -180, step 0.1


def sample(z, lons, lats):
    """NaN-aware bilinear sample. Returns (value, weight-of-valid-neighbours)."""
    x = (np.asarray(lons) + 180.0) / 0.1; y = (np.asarray(lats) + 90.0) / 0.1
    x = np.mod(x, 3600.0)  # wrap (col 3600 == col 0)
    y = np.clip(y, 0, 1800 - 1e-9)
    x0 = np.floor(x).astype(int); y0 = np.floor(y).astype(int)
    fx = x - x0; fy = y - y0
    x1 = x0 + 1; y1 = y0 + 1
    num = np.zeros(np.shape(x)); den = np.zeros(np.shape(x))
    for xi, yi, w in ((x0, y0, (1 - fx) * (1 - fy)), (x1, y0, fx * (1 - fy)), (x0, y1, (1 - fx) * fy), (x1, y1, fx * fy)):
        v = z[yi, xi]; ok = np.isfinite(v)
        num += np.where(ok, v, 0) * w * ok; den += w * ok
    with np.errstate(invalid='ignore', divide='ignore'):
        val = np.where(den > 0, num / den, np.nan)
    return val, den


def grid(W, H):
    lons = -180 + (np.arange(W) + 0.5) * 360.0 / W
    lats = 90 - (np.arange(H) + 0.5) * 180.0 / H
    return np.meshgrid(lons, lats)


# --- OKLab interpolation of the ramp ---
def _lin(c): c = c / 255.0; return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
def _gam(c): return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055)
def to_oklab(rgb):
    r, g, b = _lin(rgb[..., 0]), _lin(rgb[..., 1]), _lin(rgb[..., 2])
    l = np.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = np.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = np.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return np.stack([0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
                     1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
                     0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s], -1)
def from_oklab(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return np.clip(np.stack([_gam(r), _gam(g), _gam(bb)], -1) * 255, 0, 255)

def ramp_lut():
    ages = np.array([a for a, _ in STOPS], float)
    labs = to_oklab(np.array([[int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)] for _, h in STOPS], float))
    t = np.arange(181, dtype=float)
    lut = np.stack([np.interp(t, ages, labs[:, k]) for k in range(3)], -1)
    return from_oklab(lut)  # 181 x 3, index = age Ma (clamped)


def main():
    os.makedirs(OUT, exist_ok=True)
    z = load()
    fin = z[np.isfinite(z)]
    stats = dict(min=float(fin.min()), max=float(fin.max()), mean=float(fin.mean()), cells=int(fin.size))
    # area-weighted mean (cos lat)
    latc = np.linspace(-90, 90, 1801)[:, None] * np.ones((1, 3601))
    w = np.cos(np.radians(latc))[np.isfinite(z)]
    stats['mean_area_weighted'] = float((fin * w).sum() / w.sum())

    lut = ramp_lut()
    # colour 2048x1024
    LO, LA = grid(2048, 1024)
    val, den = sample(z, LO, LA)
    idx = np.clip(np.nan_to_num(val, nan=0), 0, 180)
    i0 = np.floor(idx).astype(int); f = (idx - i0)[..., None]; i1 = np.minimum(i0 + 1, 180)
    rgb = lut[i0] * (1 - f) + lut[i1] * f
    alpha = np.clip((den - 0.3) / 0.4, 0, 1) * 255
    rgba = np.dstack([rgb, alpha]).round().astype(np.uint8)
    rgba[alpha == 0, :3] = 0
    Image.fromarray(rgba).save(os.path.join(OUT, 'age_color.png'), optimize=True)

    # u8 1024x512
    LO, LA = grid(1024, 512)
    val, den = sample(z, LO, LA)
    u8 = np.where(den >= 0.5, np.clip(np.round(np.nan_to_num(val, nan=0)), 0, 254), 255).astype(np.uint8)
    Image.fromarray(u8).save(os.path.join(OUT, 'age_u8.png'), optimize=True)

    checks = {}
    for name, la, lo in (('tonga_seaward', -21.0, -172.5), ('japan_seaward', 38.0, 145.0)):
        v, d = sample(z, np.array([lo]), np.array([la]))
        checks[name] = dict(lat=la, lon=lo, age_ma=None if not np.isfinite(v[0]) else round(float(v[0]), 1))
    print(json.dumps(dict(stats=stats, checks=checks, ramp=[list(map(int, lut[a])) for a in (0, 30, 60, 90, 120, 150, 180)]), indent=1))


if __name__ == '__main__':
    main()
