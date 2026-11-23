"""OUR MAP ON THE SUBDUCTION GLOBE (2026-11-23; user: "could we make our global map transparent and swap it in? it would show the oceans and
lidar mountains"). Composites the dashboard's own world pyramids at one zoom -- the depth tint (bathy/world1), the sea-floor hillshade
(seafloor/v1) and the land relief (relief/v1) over the dark map flavor's land -- and reprojects Web Mercator to an equirectangular
texture for the WebGL globe. Poles past +-85 deg take the nearest row.

Run: python3 _slabbake/globe_tex_bake.py <out.webp> [zoom=4]
"""
import io, math, os, sys, time, urllib.request
import numpy as np
from PIL import Image

Z = int(sys.argv[2]) if len(sys.argv) > 2 else 4
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache', 'globetex')
os.makedirs(CACHE, exist_ok=True)
LAYERS = ['bathy/world1', 'seafloor/v1', 'relief/v1']
LAND = (46, 50, 60)           # the dark flavor's earth (#0f1116), lifted so the relief reads on a globe
RELIEF_GAIN = 2.0             # the land hillshade is tuned for a flat map at street zooms; a whole-world globe needs it stronger

def tile(layer, z, x, y):
    p = os.path.join(CACHE, '%s_%d_%d_%d.webp' % (layer.replace('/', '_'), z, x, y))
    if not os.path.exists(p):
        for k in range(4):
            try:
                r = urllib.request.urlopen(urllib.request.Request('https://cdn.bluishvoid.com/%s/%d/%d/%d.webp?b=3' % (layer, z, x, y),
                                                                  headers={'Origin': 'https://bluishvoid.com', 'User-Agent': 'bluishvoid-globe-bake'}), timeout=60)
                open(p, 'wb').write(r.read()); break
            except urllib.error.HTTPError as e:
                if e.code in (404, 204): open(p, 'wb').write(b''); break
                time.sleep(2 * (k + 1))
            except Exception:
                time.sleep(2 * (k + 1))
    d = open(p, 'rb').read() if os.path.exists(p) else b''
    if not d: return None
    im = Image.open(io.BytesIO(d)).convert('RGBA')
    return im.resize((256, 256), Image.BILINEAR) if im.size != (256, 256) else im

def main():
    out = sys.argv[1]; n = 2 ** Z; S = 256 * n
    merc = np.zeros((S, S, 3), np.float32); merc[:] = LAND
    for layer in LAYERS:
        for x in range(n):
            for y in range(n):
                t = tile(layer, Z, x, y)
                if t is None: continue
                a = np.asarray(t, np.float32) / 255.0
                if layer == 'relief/v1': a[..., 3] = np.clip(a[..., 3] * RELIEF_GAIN, 0, 1)
                blk = merc[y * 256:(y + 1) * 256, x * 256:(x + 1) * 256]
                blk[:] = blk * (1 - a[..., 3:4]) + a[..., :3] * 255 * a[..., 3:4]
        print(layer, 'done')
    W, H = S, S // 2
    lon = (np.arange(W) + 0.5) / W * 360 - 180
    lat = 90 - (np.arange(H) + 0.5) / H * 180
    latc = np.clip(lat, -85.05, 85.05) * math.pi / 180
    my = (1 - np.log(np.tan(latc) + 1 / np.cos(latc)) / math.pi) / 2 * S
    mx = (lon + 180) / 360 * S
    yi = np.clip(my.astype(int), 0, S - 1); xi = np.clip(mx.astype(int), 0, S - 1)
    eq = merc[yi[:, None], xi[None, :]]
    pole = np.clip((np.abs(lat) - 82) / 6, 0, 1)[:, None, None]        # past the Mercator edge: fade to the polar ocean tone, no smeared rows
    eq = eq * (1 - pole) + np.array([14, 26, 48], np.float32) * pole
    Image.fromarray(np.clip(eq, 0, 255).astype(np.uint8)).save(out, quality=88, method=6)
    print('wrote', out, W, 'x', H, os.path.getsize(out) // 1024, 'KB')

if __name__ == '__main__':
    main()
