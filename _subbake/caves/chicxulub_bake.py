#!/usr/bin/env python3
"""CHICXULUB ON CAVES (2026-11-12, user: "can our geology map show more detail about the remnants of the chicxulub crater and the
sinkholes / cenotes left behind" -> "yes go ahead, show me the preview").

RELIEF   The crater is buried under about 3,000 ft of younger limestone; its only trace on the ground is a shallow trough, a few meters deep,
         curving along the buried rim (the one NASA/JPL showed from the Shuttle Radar Topography Mission, PIA03379). Elevation: AWS Terrain
         Tiles (terrarium, z10; SRTM over Mexico), the regional slope removed, shaded from the northwest with 25x vertical exaggeration,
         drawn as light and shadow with opacity that follows the shading (land only). Tiles are Web Mercator already: no resampling.
         (Tried first and dropped: XGM2019e global gravity via ICGEM -- at ~9 km it shows blobs, not the rings the survey maps show.)
CENOTES  Cenote Atlas (Benavente 2026, Zenodo 10.5281/zenodo.19715058, ODbL): 1,369 cenotes, base positions from the "Yuc_caves_Projected"
         ArcGIS layer (2020) + OpenStreetMap. Kept: name, municipality, state, depth (m), length (m).

    python3 _subbake/caves/chicxulub_bake.py <terrain tile dir (z10 terrarium x_y.png)> <cenotes_unified.json> <outdir>
    then rclone chicxulub_relief_v1.webp and chicxulub_v1.json to r2:bluishvoid-bg/under/
"""
import json, math, os, sys
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

TD, CEN, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
Z, X0, X1, Y0, Y1 = 10, 252, 265, 447, 455      # 91.4-86.5 W, 19.3-22.3 N
C0 = (21.33, -89.52)                             # crater center (peak-ring center, after Gulick et al. 2013)

W, H = (X1 - X0 + 1) * 256, (Y1 - Y0 + 1) * 256; E = np.zeros((H, W), np.float32)
for x in range(X0, X1 + 1):
    for y in range(Y0, Y1 + 1):
        a = np.asarray(Image.open(os.path.join(TD, '%d_%d.png' % (x, y))).convert('RGB')).astype(np.float32)
        E[(y - Y0) * 256:(y - Y0 + 1) * 256, (x - X0) * 256:(x - X0 + 1) * 256] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
land = E > 0.5
w = gaussian_filter(land.astype(np.float32), 40); reg = gaussian_filter(np.where(land, E, 0), 40) / np.maximum(w, 1e-3)
gy, gx = np.gradient(gaussian_filter(np.where(land, E, reg), 1.2))
mpp = 156543.03 * math.cos(math.radians(20.8)) / 2 ** Z
sl = np.arctan(25.0 * np.hypot(gx, gy) / mpp); asp = np.arctan2(-gx, gy); az, alt = math.radians(315), math.radians(40)
sh = np.sin(alt) * np.cos(sl) + np.cos(alt) * np.sin(sl) * np.cos(az - asp)
mid = np.median(sh[land]); d = np.clip((sh - mid) / 0.35, -1, 1)
rgb = np.where(d[..., None] > 0, [255, 248, 235], [8, 14, 30]).astype(np.float32)
alpha = np.where(land, np.abs(d) ** .85 * .62, 0)
edge = gaussian_filter(land.astype(np.float32), 2.0); alpha = alpha * np.clip(edge * 1.6 - .3, 0, 1)   # no hard halo at the coast
img = np.dstack([rgb, alpha[..., None] * 255]).clip(0, 255).astype(np.uint8)
im = Image.fromarray(img).resize((W // 2, H // 2), Image.LANCZOS)
os.makedirs(OUT, exist_ok=True); im.save(os.path.join(OUT, 'chicxulub_relief_v1.webp'), quality=82, method=6)
lon = lambda x: x / 2 ** Z * 360 - 180
lat = lambda y: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** Z))))
bounds = [[lat(Y1 + 1), lon(X0)], [lat(Y0), lon(X1 + 1)]]

C = json.load(open(CEN)); rows = []
for c in C:
    if c.get('lat') is None: continue
    dep = c.get('depth'); ln = c.get('length')
    rows.append([round(c['lat'], 5), round(c['lon'], 5), (c.get('name') or '').strip(), (c.get('municipio') or '').strip(), (c.get('state') or '').strip(),
                 round(float(dep), 1) if isinstance(dep, (int, float)) and dep > 0 else None, round(float(ln), 1) if isinstance(ln, (int, float)) and ln > 0 else None])
meta = {'center': C0, 'reliefBounds': bounds, 'n': len(rows),
        'sources': {'relief': 'AWS Terrain Tiles (SRTM), 25x exaggeration, regional slope removed', 'cenotes': 'Cenote Atlas (Zenodo 10.5281/zenodo.19715058), ODbL'}}
json.dump({'meta': meta, 'c': rows}, open(os.path.join(OUT, 'chicxulub_v1.json'), 'w'), separators=(',', ':'), ensure_ascii=False)
print('cenotes', len(rows), 'relief', im.size, 'bounds', bounds, 'kb', os.path.getsize(os.path.join(OUT, 'chicxulub_relief_v1.webp')) // 1024)
