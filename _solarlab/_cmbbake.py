"""THE MICROWAVE SKY AS A SPHERE (2026-11-22; user: "do 1 2 3 4 5 6" on the OBSERVABLE UNIVERSE review).

Source: WMAP 9-year Internal Linear Combination map (NASA / LAMBDA, public domain), HEALPix:
  https://lambda.gsfc.nasa.gov/data/map/dr5/dfp/ilc/wmap_ilc_9yr_v5.fits
Resampled into EQUATORIAL coordinates (RA, Dec), so the lab's survey slice -- which runs along the celestial equator -- lies on
the sphere's equator, exactly where the old one-pixel rim was.

Outputs (in the repo, same-origin, so the lab can read pixels):
  galaxy/cmb_eq.webp   1024 x 512, RA 0 at the left increasing right, Dec +90 at the top; coloured by the lab's cmbColor() palette
  galaxy/cmb_t.png     360 x 180 grey: value = clip(uK, -300, 300) mapped to 0..255 (for the tap card's temperature)
Run: python3 _cmbbake.py <ilc.fits>   (needs healpy)
"""
import os, sys
import numpy as np, healpy as hp
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
m = hp.read_map(sys.argv[1]) * 1000.0                      # mK -> microkelvin
m = m - np.mean(m)
rot = hp.Rotator(coord=['C', 'G'])

def sample(W, H):
    ra = (np.arange(W) + .5) / W * 360.0
    dec = 90.0 - (np.arange(H) + .5) / H * 180.0
    RA, DEC = np.meshgrid(ra, dec)
    th, ph = rot(np.radians(90.0 - DEC).ravel(), np.radians(RA).ravel())
    return hp.get_interp_val(m, th, ph).reshape(H, W)

def colour(uK):                                            # the lab's cmbColor(): blue-cold, red-hot, +-220 uK
    t = np.clip(uK / 220.0, -1, 1)
    r = np.where(t < 0, 40 + 150 * (1 + t), 230 - 10 * t)
    g = np.where(t < 0, 90 + 140 * (1 + t), 230 - 170 * t)
    b = np.where(t < 0, 210 + 30 * (1 + t), 240 - 190 * t)
    return np.stack([r, g, b], -1).clip(0, 255).astype(np.uint8)

T = sample(1024, 512)
Image.fromarray(colour(T)).save(os.path.join(HERE, 'galaxy', 'cmb_eq.webp'), quality=86, method=6)
G = sample(360, 180)
Image.fromarray(((np.clip(G, -300, 300) + 300) / 600 * 255).round().astype(np.uint8), 'L').save(os.path.join(HERE, 'galaxy', 'cmb_t.png'), optimize=True)
eq = sample(360, 180)[90]                                  # Dec ~ -0.5: the equator row, to check against the old rim
print('rms uK %.1f' % np.std(T), '| equator row vs old rim:', np.round(eq[:6], 1))
