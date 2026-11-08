#!/usr/bin/env python3
"""THE MARS AND VENUS GLOBES (user 2026-11-08: "are there global maps of mars and venus?" -> "yes build both globes").

Four whole-planet maps, simple cylindrical (equirectangular, -180..180 east longitude, 90..-90 latitude), from the USGS Astrogeology
Science Center's planetary WMS (planetarymaps.usgs.gov, public domain NASA/USGS products), at the server's 4096-px limit:

  mars_color   Viking MDIM 2.1 colorized mosaic (NASA/JPL/USGS), shaded by the HRSC-MOLA blended hillshade (NASA/GSFC MOLA, ESA/DLR/FU
               Berlin HRSC, USGS): color x (0.35 + 0.65 x hillshade / its median, clipped 0.55-1.45), so the relief reads on the photo
  mars_elev    MOLA colorized elevation (NASA/GSFC), as USGS colors it
  mars_themis  Mars Odyssey THEMIS daytime infrared mosaic (NASA/JPL/ASU), grayscale
  venus_radar  Magellan synthetic-aperture radar, colorized mosaic (NASA/JPL/USGS) -- the gap-free one (the raw mosaic has holes)
  venus_elev   Magellan topography, as USGS colors it

Out: cdn planets/globe/{name}_{2k,4k}.jpg (2048x1024 for phones, 4096x2048 for computers). The page's globe is window._bvPlanetGlobe.

    python3 globes.py OUTDIR [--upload]
"""
import io, math, os, subprocess, sys, urllib.request
import numpy as np
from PIL import Image
W = ('https://planetarymaps.usgs.gov/cgi-bin/mapserv?service=WMS&request=GetMap&version=1.1.1&srs=EPSG:4326&styles=&bbox=-180,-90,180,90'
     '&width=4096&height=2048&format=image/jpeg&map=/maps/{m}_simp_cyl.map&layers={l}')
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com planet globes)'}

MAPF = {'mars': 'mars/mars', 'venus': 'venus/venus', 'mercury': 'mercury/mercury', 'moon': 'earth/moon', 'io': 'jupiter/io', 'europa': 'jupiter/europa',
        'ganymede': 'jupiter/ganymede', 'callisto': 'jupiter/callisto', 'titan': 'saturn/titan'}

def get(p, l):
    b = urllib.request.urlopen(urllib.request.Request(W.format(m=MAPF[p], l=l), headers=UA), timeout=300).read()
    return np.asarray(Image.open(io.BytesIO(b)).convert('RGB'))

def fill(a):
    """where nothing was imaged (pure black, mostly toward the poles): the row's own mean, or the nearest row that has one"""
    import cv2
    miss0 = (a.astype(np.int32).sum(2) < 10).astype(np.uint8)
    # narrow seams (a few px, e.g. the 0-degree join in the Galileo/Voyager mosaics) are painted from their neighbors; only the wide
    # unimaged areas (mostly the poles) take the row mean below (2026-11-08: the mean drew a dashed line down Io, Ganymede, Callisto)
    big = cv2.dilate(cv2.erode(miss0, np.ones((1, 15), np.uint8)), np.ones((1, 15), np.uint8))
    small = (miss0 & (1 - big)).astype(np.uint8)
    if small.any(): a = cv2.inpaint(np.ascontiguousarray(a), cv2.dilate(small, np.ones((3, 3), np.uint8)), 4, cv2.INPAINT_TELEA)
    a = a.astype(np.float32); miss = a.sum(2) < 10; h = a.shape[0]; means = [None] * h
    for r in range(h):
        ok = ~miss[r]
        if ok.sum() > a.shape[1] * 0.02: means[r] = a[r][ok].mean(0)
    for r in range(h):
        if not miss[r].any(): continue
        m = means[r]
        if m is None:
            near = [q for q in range(h) if means[q] is not None]
            if not near: continue
            m = means[min(near, key=lambda q: abs(q - r))]
        a[r][miss[r]] = m
    return a.clip(0, 255).astype(np.uint8)


def stretch(a):
    """a gray mosaic's levels, 1st to 99.5th percentile, to the full range (MESSENGER's was very dark)"""
    lo, hi = np.percentile(a, 1), np.percentile(a, 99.5)
    return ((a.astype(np.float32) - lo) / max(1, hi - lo) * 255).clip(0, 255).astype(np.uint8)


def seams(a):
    """single columns far darker or brighter than both neighbours (mosaic joins, e.g. Ganymede's at 0 degrees): replaced by their neighbours' mean"""
    f = a.astype(np.float32); col = f.mean((0, 2)); d = np.abs(col - (np.roll(col, 1) + np.roll(col, -1)) / 2)
    for c in np.nonzero(d > 6)[0]:
        f[:, c] = (f[:, c - 1] + f[:, (c + 1) % f.shape[1]]) / 2
    return f.clip(0, 255).astype(np.uint8)


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
        sm = cv2.blur(row, (k, 1))[0, k:k + w]
        if abs(lat) > 78:   # the last 12 degrees ease into the row's own mean: no pinched wedges where the meridians meet (v4)
            t = ((abs(lat) - 78) / 12) ** 1.5; sm = sm * (1 - t) + a[r].reshape(-1, a.shape[2]).mean(0) * t
        out[r] = sm.clip(0, 255).astype(np.uint8)
    return out


def main(out, up):
    os.makedirs(out, exist_ok=True)
    ONLY = [a for a in sys.argv[2:] if not a.startswith('--')]
    if not ONLY:
        c = get('mars', 'MDIM21_color').astype(np.float32); hs = get('mars', 'HRSC_MOLA_Blend_Hillshade').mean(2)
        sh = np.clip(hs / np.median(hs), 0.55, 1.45)[..., None]
    maps = {} if ONLY else {'mars_color': np.clip(c * (0.35 + 0.65 * sh), 0, 255).astype(np.uint8), 'mars_elev': get('mars', 'MOLA_color'),
            'mars_themis': get('mars', 'THEMIS'),   # Mars Odyssey THEMIS daytime infrared (ASU/NASA), the zoom's sharpest Mars layer (100 m)
            'venus_radar': get('venus', 'MAGELLAN_color'), 'venus_elev': get('venus', 'MAGELLAN_topography')}
    # MERCURY, THE MOON, THE BIG MOONS (2026-11-08, "yes do mercury and the moon, then the big moons")
    MORE = [('mercury_gray', 'mercury', 'MESSENGER', 1), ('mercury_color', 'mercury', 'MESSENGER_Color', 0), ('moon_wac', 'moon', 'LROC_WAC', 0), ('moon_elev', 'moon', 'LOLA_color', 0),
            ('io_color', 'io', 'SSI_color', 0), ('europa', 'europa', 'GALILEO_VOYAGER', 1), ('ganymede', 'ganymede', 'GALILEO_VOYAGER', 1), ('callisto', 'callisto', 'GALILEO_VOYAGER', 1),
            ('titan', 'titan', 'CASSINI', 1)]
    for k, body, layer, st in MORE:
        if ONLY and body not in ONLY: continue
        a = seams(fill(get(body, layer))); maps[k] = stretch(a) if st else a
    for k, a in maps.items():
        a = poles(a)
        im = Image.fromarray(a)
        for tag, size in (('4k', (4096, 2048)), ('2k', (2048, 1024))):
            p = os.path.join(out, '%s_%s.jpg' % (k, tag)); (im if tag == '4k' else im.resize(size, Image.LANCZOS)).save(p, quality=88, optimize=True, progressive=True)
            if up: subprocess.run(['rclone', 'copyto', p, 'r2:bluishvoid-bg/planets/globe/%s_%s.jpg' % (k, tag), '--s3-no-check-bucket',
                                   '--header-upload', 'Content-Type: image/jpeg', '--header-upload', 'Cache-Control: public, max-age=31536000, immutable'], check=True)
            print(p, os.path.getsize(p) // 1024, 'KB')

if __name__ == '__main__':
    main(sys.argv[1], '--upload' in sys.argv)   # extra args: only these bodies (mercury moon io europa ganymede callisto titan)
