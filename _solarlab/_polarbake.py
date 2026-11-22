"""North-pole views of the planets for the solar system's spinning globes (2026-11-22; user: "review the solar systems
animations ... the spinning planets/moons, i want to improve this visual significantly").

The map is drawn from above the ecliptic's north, so a planet's spin is its disc turning about the centre. Each disc is the
planet's surface seen straight down on its north pole (orthographic: rho = cos(lat)), longitude 0 along +x, east counter-
clockwise -- the lab turns the image to spin it, so it is baked once, not re-rendered per frame.

Source maps: NASA 3D Resources (github.com/nasa/NASA-3D-Resources, NASA imagery, public domain): Mars (Viking), Jupiter
(Cassini), Neptune (Voyager). Venus's map there is Magellan RADAR terrain, not the clouds you would see, so Venus keeps its
photo; Saturn keeps its ringed art; Uranus lies on its side and is not seen pole-on from above the ecliptic.

Run: python3 _polarbake.py <dir with Mars.jpg Jupiter.jpg Neptune.jpg>  ->  polar_<id>.jpg here, then
     rclone copyto polar_<id>.jpg r2:bluishvoid-bg/planets/polar_<id>_v1.jpg
"""
import os, sys
import numpy as np
from PIL import Image

N = 384
SRC = sys.argv[1] if len(sys.argv) > 1 else '.'
OUT = os.path.dirname(os.path.abspath(__file__))

def polar(path, out):
    tex = np.asarray(Image.open(path).convert('RGB')).astype(np.float32)
    TH, TW = tex.shape[:2]
    # supersample 2x2 per output pixel so the dense bands near the limb do not alias
    acc = np.zeros((N, N, 3), np.float32); cov = np.zeros((N, N), np.float32)
    for oy in (.25, .75):
        for ox in (.25, .75):
            y, x = np.mgrid[0:N, 0:N].astype(np.float32)
            u = (x + ox - N / 2) / (N / 2); v = (N / 2 - (y + oy)) / (N / 2)
            rho = np.sqrt(u * u + v * v); inside = rho < 1
            lat = np.degrees(np.arccos(np.clip(rho, 0, 1)))                     # 90 at the pole (centre), 0 at the limb
            lon = np.degrees(np.arctan2(v, u))                                   # east counter-clockwise from +x
            row = np.clip(((90 - lat) / 180 * TH).astype(int), 0, TH - 1)
            col = (((lon + 180) / 360 % 1) * TW).astype(int) % TW
            px = tex[row, col]
            shade = 0.70 + 0.30 * np.power(np.sqrt(np.clip(1 - rho * rho, 0, 1)), 0.55)   # soft limb darkening, as in photos
            acc += px * (shade * inside)[..., None]; cov += inside
    img = np.where(cov[..., None] > 0, acc / np.maximum(cov, 1)[..., None], 0)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(out, quality=86, optimize=True)
    print(out, os.path.getsize(out) // 1024, 'KB')

# 2026-11-22: only Mars ships. Jupiter's map is smeared poleward of ~60 deg (Cassini never saw the poles), so its pole view was
# a streaked blur; Neptune's came out a flat swirl, weaker than its photo. Both keep their photos, unspun.
for pid, name in (('mars', 'Mars'),):
    polar(os.path.join(SRC, name + '.jpg'), os.path.join(OUT, 'polar_%s.jpg' % pid))
