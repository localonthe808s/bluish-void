"""THE LOCAL GROUP'S GIANTS AS PHOTOS (2026-11-22; user: "do 1 2 3 4 5 6" on the LOCAL GROUP review).

Each photo is turned so the galaxy's long axis lies horizontal (found from the light's second moments, foreground stars
median-filtered out first) and cropped square round it. The lab lays it on the galaxy's real disc -- its long axis along the
catalogue position angle, deprojected by the catalogue inclination -- so it shows at true size and tilt in the 3D frame.

Sources (Wikimedia Commons, reduced to 1400-1920 px wide):
  m31  Andromeda Galaxy (with h-alpha).jpg        Adam Evans, CC BY 2.0
  m33  VST snaps a very detailed view of the Triangulum Galaxy.jpg   ESO, CC BY 4.0
  lmc  LMC snapped by the ESO 1-metre Schmidt telescope.jpg          ESO, CC BY 4.0
  smc  SMC - Noirlab2030b.jpg                     CTIO/NOIRLab/NSF/AURA/SMASH/D. Nidever, CC BY 4.0
Outputs lg_<id>_v1.webp (512 px) -> rclone copyto ... r2:bluishvoid-bg/galaxy/ --s3-no-check-bucket

Run: python3 _lgbake.py <dir with m31.jpg m33.jpg lmc.jpg smc.jpg> <out dir>
"""
import math, os, sys
import numpy as np
from PIL import Image, ImageFilter

SRC, OUT = sys.argv[1], sys.argv[2]
PAD = {'m31': 1.25, 'm33': 1.5, 'lmc': 1.35, 'smc': 1.5}     # crop half-size, in units of the light's 2.5-sigma major extent
for k in ('m31', 'm33', 'lmc', 'smc'):
    im = Image.open(os.path.join(SRC, k + '.jpg')).convert('RGB')
    sm = im.resize((im.width // 4, im.height // 4), Image.LANCZOS)
    L = np.asarray(sm.convert('L').filter(ImageFilter.MedianFilter(9))).astype(np.float64)
    L = np.clip(L - np.median(L), 0, None); L[L < .25 * L.max()] = 0
    y, x = np.mgrid[0:L.shape[0], 0:L.shape[1]]; w = L.sum()
    cx, cy = (L * x).sum() / w, (L * y).sum() / w
    cxx, cyy, cxy = (L * (x - cx) ** 2).sum() / w, (L * (y - cy) ** 2).sum() / w, (L * (x - cx) * (y - cy)).sum() / w
    ang = .5 * math.degrees(math.atan2(2 * cxy, cxx - cyy))
    lam = .5 * (cxx + cyy) + math.sqrt(((cxx - cyy) / 2) ** 2 + cxy ** 2); maj = 2.5 * math.sqrt(lam) * 4
    ratio = math.sqrt((.5 * (cxx + cyy) - math.sqrt(((cxx - cyy) / 2) ** 2 + cxy ** 2)) / lam)
    rot = im.rotate(ang, resample=Image.BICUBIC, center=(cx * 4, cy * 4), fillcolor=(0, 0, 0))
    h = maj * PAD[k]; box = (int(cx * 4 - h), int(cy * 4 - h), int(cx * 4 + h), int(cy * 4 + h))
    out = rot.crop(box).resize((512, 512), Image.LANCZOS)
    a = np.asarray(out).astype(np.float32); a = np.clip((a - np.percentile(a, 30)) * 1.08, 0, 255)   # a black sky, so the lab's additive blend shows only the galaxy
    # faded to black along an ellipse round the galaxy (its own axis ratio, softened): the rotated frame's edges and a bright
    # sky (the Magellanic Clouds fill their photos) otherwise showed as a lit square
    q = max(.45, ratio); yy, xx = np.mgrid[0:512, 0:512]; rr = np.hypot((xx - 256) / 256, (yy - 256) / (256 * q)) * PAD[k] / 1.15
    a *= np.clip((1 - rr) / .35, 0, 1)[..., None] ** 1.5
    Image.fromarray(a.astype(np.uint8)).save(os.path.join(OUT, 'lg_%s_v1.webp' % k), quality=82, method=6)
    print(k, 'turned %.1f deg' % ang, 'axis ratio %.2f' % ratio)
