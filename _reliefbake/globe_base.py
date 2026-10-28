#!/usr/bin/env python3
"""THE OCEAN GLOBE'S OWN SEA FLOOR (user 2026-10-28: "does the ocean globe show the hi res bathymetry we have?" -> "do 1"). The
EARTH SYSTEMS globe is wrapped in NASA's Blue Marble at 2048 x 1024 (~20 km a pixel). This bakes one 4096 x 2048 picture for
WATER's OCEAN globe from our own world tiles -- the depth tint (bathy/world1) with the sea-floor relief (seafloor/v1) laid over
it, exactly as WATER's flat maps stack them -- on Blue Marble's land, so the globe and the maps show the same sea floor.

The tiles are web mercator; the globe samples plain latitude rows (EPSG:4326). Zoom 5 (8192 px around) is stitched and re-cut
row by row to latitude, then halved to 4096: ~10 km a pixel at the equator, which is about what the globe can show at its
closest (~8 km a screen pixel). Past 85 deg (where mercator stops) Blue Marble stays.

    python3 _reliefbake/globe_base.py [WORLD_DIR] [OUT.jpg]      (default /Users/vvvaa/relief_bake/world)
"""
import io, math, os, sys, urllib.request
import numpy as np
from PIL import Image

Z = 5
N = 1 << Z
W, H = 4096, 2048


def tiles(root, mode):
    a = np.zeros((N * 256, N * 256, 4), np.uint8); n = 0
    for x in range(N):
        for y in range(N):
            p = os.path.join(root, mode, str(Z), str(x), '%d.webp' % y)
            if not os.path.exists(p): continue
            a[y * 256:(y + 1) * 256, x * 256:(x + 1) * 256] = np.asarray(Image.open(p).convert('RGBA')); n += 1
    print(mode, n, 'tiles')
    return a


def over(dst, src):
    """src over dst, straight alpha, float"""
    sa = src[..., 3:4] / 255.0; da = dst[..., 3:4] / 255.0
    oa = sa + da * (1 - sa)
    rgb = (src[..., :3] * sa + dst[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6)
    return np.concatenate([rgb, oa * 255], axis=-1)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else '/Users/vvvaa/relief_bake/world'
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(root), 'globe_base_v1.jpg')
    # mercator rows wanted for each latitude row of the output (2 x H, halved later)
    H2 = H * 2; lat = 90 - (np.arange(H2) + .5) * 180 / H2
    ok = np.abs(lat) < 85.0511
    my = (1 - np.log(np.tan(np.pi / 4 + np.radians(np.clip(lat, -85.05, 85.05)) / 2)) / np.pi) / 2 * (N * 256)
    rows = np.clip(my.astype(int), 0, N * 256 - 1)
    sea = over(tiles(root, 'depth')[rows].astype(np.float32), tiles(root, 'sea')[rows].astype(np.float32))   # depth, then relief over it
    sea[~ok] = 0
    # Blue Marble at the same size, for the land and the poles
    url = ('https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&STYLES=&SRS=EPSG:4326'
           '&BBOX=-180,-90,180,90&WIDTH=%d&HEIGHT=%d&FORMAT=image/jpeg&LAYERS=BlueMarble_ShadedRelief_Bathymetry' % (W, H))
    bm = Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluish-void bake'}), timeout=300).read())).convert('RGB')
    bm = np.asarray(bm.resize((W * 2, H2), Image.LANCZOS)).astype(np.float32)
    a = sea[..., 3:4] / 255.0
    img = sea[..., :3] * a + bm * (1 - a)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).resize((W, H), Image.LANCZOS).save(out, quality=88, optimize=True, progressive=True)
    print(out, os.path.getsize(out), 'bytes')


if __name__ == '__main__':
    main()
