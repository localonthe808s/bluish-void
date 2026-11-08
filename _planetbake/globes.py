#!/usr/bin/env python3
"""THE MARS AND VENUS GLOBES (user 2026-11-08: "are there global maps of mars and venus?" -> "yes build both globes").

Four whole-planet maps, simple cylindrical (equirectangular, -180..180 east longitude, 90..-90 latitude), from the USGS Astrogeology
Science Center's planetary WMS (planetarymaps.usgs.gov, public domain NASA/USGS products), at the server's 4096-px limit:

  mars_color   Viking MDIM 2.1 colorized mosaic (NASA/JPL/USGS), shaded by the HRSC-MOLA blended hillshade (NASA/GSFC MOLA, ESA/DLR/FU
               Berlin HRSC, USGS): color x (0.35 + 0.65 x hillshade / its median, clipped 0.55-1.45), so the relief reads on the photo
  mars_elev    MOLA colorized elevation (NASA/GSFC), as USGS colors it
  venus_radar  Magellan synthetic-aperture radar, colorized mosaic (NASA/JPL/USGS) -- the gap-free one (the raw mosaic has holes)
  venus_elev   Magellan topography, as USGS colors it

Out: cdn planets/globe/{name}_{2k,4k}.jpg (2048x1024 for phones, 4096x2048 for computers). The page's globe is window._bvPlanetGlobe.

    python3 globes.py OUTDIR [--upload]
"""
import io, math, os, subprocess, sys, urllib.request
import numpy as np
from PIL import Image
W = ('https://planetarymaps.usgs.gov/cgi-bin/mapserv?service=WMS&request=GetMap&version=1.1.1&srs=EPSG:4326&styles=&bbox=-180,-90,180,90'
     '&width=4096&height=2048&format=image/jpeg&map=/maps/{p}/{p}_simp_cyl.map&layers={l}')
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com planet globes)'}

def get(p, l):
    b = urllib.request.urlopen(urllib.request.Request(W.format(p=p, l=l), headers=UA), timeout=300).read()
    return np.asarray(Image.open(io.BytesIO(b)).convert('RGB'))

def poles(a):
    """the mosaics smear radially toward the poles (a pixel row near 90 degrees is a few km of ground stretched round the whole map):
    each row is blurred along longitude by how much the projection stretches it, 1 / cos(latitude), so the cap reads as ground"""
    import cv2
    h, w = a.shape[:2]; out = a.copy()
    for r in range(h):
        lat = 90 - (r + 0.5) * 180 / h; st = 1 / max(math.cos(math.radians(lat)), 1e-3)
        k = int(round(st * (1.2 if abs(lat) < 60 else 1.2 + (abs(lat) - 60) / 30 * 5)))   # stronger toward the poles, where the mosaics streak most (v3)
        if k < 3: continue
        k = min(k | 1, w - 1)
        row = np.concatenate([a[r, -k:], a[r], a[r, :k]], 0).astype(np.float32)[None]
        out[r] = cv2.blur(row, (k, 1))[0, k:k + w].clip(0, 255).astype(np.uint8)
    return out


def main(out, up):
    os.makedirs(out, exist_ok=True)
    c = get('mars', 'MDIM21_color').astype(np.float32); hs = get('mars', 'HRSC_MOLA_Blend_Hillshade').mean(2)
    sh = np.clip(hs / np.median(hs), 0.55, 1.45)[..., None]
    maps = {'mars_color': np.clip(c * (0.35 + 0.65 * sh), 0, 255).astype(np.uint8), 'mars_elev': get('mars', 'MOLA_color'),
            'venus_radar': get('venus', 'MAGELLAN_color'), 'venus_elev': get('venus', 'MAGELLAN_topography')}
    for k, a in maps.items():
        a = poles(a)
        im = Image.fromarray(a)
        for tag, size in (('4k', (4096, 2048)), ('2k', (2048, 1024))):
            p = os.path.join(out, '%s_%s.jpg' % (k, tag)); (im if tag == '4k' else im.resize(size, Image.LANCZOS)).save(p, quality=88, optimize=True, progressive=True)
            if up: subprocess.run(['rclone', 'copyto', p, 'r2:bluishvoid-bg/planets/globe/%s_%s.jpg' % (k, tag), '--s3-no-check-bucket',
                                   '--header-upload', 'Content-Type: image/jpeg', '--header-upload', 'Cache-Control: public, max-age=31536000, immutable'], check=True)
            print(p, os.path.getsize(p) // 1024, 'KB')

if __name__ == '__main__':
    main(sys.argv[1], '--upload' in sys.argv)
