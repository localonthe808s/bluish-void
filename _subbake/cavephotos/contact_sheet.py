"""Contact sheets of downloaded candidate cave photos for visual review
(BLUISH VOID), 2026-11-07. Pillow from the user site-packages.

usage: python3 -I contact_sheet.py DLDIR OUTPREFIX [keys...]
"""
import os, sys
sys.path.append("/Users/vvvaa/Library/Python/3.9/lib/python/site-packages")
from PIL import Image, ImageDraw
dl, pre = sys.argv[1], sys.argv[2]
keys = sys.argv[3:] or sorted(f[:-4] for f in os.listdir(dl) if f.endswith(".img"))
W, H, C = 360, 270, 4
for s in range(0, len(keys), 16):
    ks = keys[s:s + 16]
    sheet = Image.new("RGB", (W * C, (H + 18) * ((len(ks) + C - 1) // C)), "white")
    d = ImageDraw.Draw(sheet)
    for i, k in enumerate(ks):
        im = Image.open(os.path.join(dl, k + ".img")).convert("RGB")
        im.thumbnail((W - 6, H - 6))
        x, y = (i % C) * W, (i // C) * (H + 18)
        sheet.paste(im, (x + 3, y + 3))
        d.text((x + 4, y + H + 2), k, fill="black")
    sheet.save(f"{pre}_{s // 16}.jpg", quality=80)
    print(f"{pre}_{s // 16}.jpg")
