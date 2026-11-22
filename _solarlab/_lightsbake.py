"""City lights for EARTH's night side, seen from above the north pole (2026-11-22; user: "how can you improve the EARTH tonight view
significantly" -> item 2). NASA Black Marble 2016, 0.1 deg (public domain, NASA Earth Observatory), projected exactly as
earthglobe.js's pole mode draws the globe: northern hemisphere, rho = cos(lat), longitude 0 along +x, east counter-clockwise.
The lab turns this image to the globe's orientation every frame and shows it only through the night half (screen blend).

Run: python3 _lightsbake.py BlackMarble_2016_01deg.jpg  ->  earth_lights_pole.jpg here, then
     rclone copyto earth_lights_pole.jpg r2:bluishvoid-bg/earth/lights_pole_v1.jpg
"""
import os, sys
import numpy as np
from PIL import Image
N = 512
tex = np.asarray(Image.open(sys.argv[1]).convert('RGB')).astype(np.float32); TH, TW = tex.shape[:2]
acc = np.zeros((N, N, 3), np.float32)
for oy in (.25, .75):
    for ox in (.25, .75):
        y, x = np.mgrid[0:N, 0:N].astype(np.float32)
        u = (x + ox - N / 2) / (N / 2); v = (N / 2 - (y + oy)) / (N / 2)
        rho = np.sqrt(u * u + v * v); inside = rho < 1
        lat = np.degrees(np.arccos(np.clip(rho, 0, 1))); lon = np.degrees(np.arctan2(v, u))
        row = np.clip(((90 - lat) / 180 * TH).astype(int), 0, TH - 1); col = (((lon + 180) / 360 % 1) * TW).astype(int) % TW
        acc += tex[row, col] * (inside * (0.55 + 0.45 * np.sqrt(np.clip(1 - rho * rho, 0, 1))))[..., None]
img = acc / 4
# the lights, not the dim land: drop the faint base, lift the cities, warm them toward sodium orange
lum = img.mean(axis=2, keepdims=True)
# north of ~62 deg the bright is moonlit snow and ice (Greenland, the Arctic), not cities: fade it out
_y, _x = np.mgrid[0:N, 0:N].astype(np.float32); _rho = np.sqrt(((_x + .5 - N / 2) / (N / 2)) ** 2 + ((N / 2 - _y - .5) / (N / 2)) ** 2)
lum = lum * np.clip((_rho - 0.42) / 0.12, 0, 1)[..., None]
lit = np.clip((lum - 48) / 75, 0, 1) ** 0.95   # Black Marble carries moonlit land and ice near 40-70: the lights clear it
import cv2
glow = cv2.GaussianBlur(lit, (0, 0), 2.2)[..., None] * 1.6          # a soft halo, so a city reads as light, not a speck
out = np.clip((lit * 1.25 + glow) * np.array([255, 205, 140]), 0, 255)
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'earth_lights_pole.jpg')
Image.fromarray(out.astype(np.uint8)).save(out_path, quality=86, optimize=True)
print(out_path, os.path.getsize(out_path) // 1024, 'KB')
