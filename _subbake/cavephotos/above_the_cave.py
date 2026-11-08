#!/usr/bin/env python3
"""ABOVE THE CAVE (user 2026-11-07: "what can you do for the ones that dont have photos?"). Seven notable caves have no openly licensed photo
(Commons, NPS and Openverse searched). Instead of a placeholder: the ground above each, cut from a cloud-free Copernicus Sentinel-2 L2A
true-colour scene (10 m, the 'visual' COG on AWS via the Element84 earth-search STAC, free and open; credit "Contains modified Copernicus
Sentinel data YEAR"). A 6 x 4 km window centred on the cave, a small ring at the entrance. Shown on the site as ABOVE THE CAVE, not as
the cave.

    python3 above_the_cave.py caves_notable_v2.json OUTDIR
"""
import json, sys, os, urllib.request, math
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform as wtransform
from PIL import Image, ImageDraw, ImageEnhance
STAC = 'https://earth-search.aws.element84.com/v1/search'
CLOUD = float(os.environ.get('BV_CLOUD', 3))   # Borneo needs ~20
def best_scene(lon, lat):
    body = {'collections': ['sentinel-2-l2a'], 'intersects': {'type': 'Point', 'coordinates': [lon, lat]}, 'datetime': '2023-01-01T00:00:00Z/2026-10-31T00:00:00Z',
            'query': {'eo:cloud_cover': {'lt': CLOUD}}, 'limit': 40}
    r = urllib.request.Request(STAC, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'User-Agent': 'bluishvoid.com (dashboard)'})
    F = json.loads(urllib.request.urlopen(r, timeout=90).read()).get('features', [])
    F.sort(key=lambda f: (f['properties'].get('eo:cloud_cover', 99), -int(f['properties']['datetime'][:4])))
    return F
def cut(feat, lon, lat, out, w_km=6, h_km=4):
    href = feat['assets']['visual']['href']
    with rasterio.Env(AWS_NO_SIGN_REQUEST='YES', GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'):
        with rasterio.open(href) as src:
            xs, ys = wtransform('EPSG:4326', src.crs, [lon], [lat]); x, y = xs[0], ys[0]
            win = from_bounds(x - w_km * 500, y - h_km * 500, x + w_km * 500, y + h_km * 500, src.transform)
            a = src.read([1, 2, 3], window=win, boundless=True, fill_value=0)
    im = Image.fromarray(a.transpose(1, 2, 0)); px = list(im.getdata()); dark = sum(1 for p in px if max(p) < 12) / len(px)
    if dark > .05: return None          # swath edge / nodata: not exactly 0 in the visual COG, so judge by brightness
    im = ImageEnhance.Contrast(im).enhance(1.08).resize((640, int(640 * h_km / w_km)), Image.LANCZOS)
    d = ImageDraw.Draw(im); cx, cy = im.width / 2, im.height / 2
    for r_, c, wd in ((15, (0, 0, 0), 5), (15, (255, 255, 255), 2)): d.ellipse([cx - r_, cy - r_, cx + r_, cy + r_], outline=c, width=wd)
    im.save(out, quality=82); return feat['properties']['datetime'][:10]
def main(src, outdir):
    os.makedirs(outdir, exist_ok=True); C = json.load(open(src)); res = {}
    for c in C:
        if c.get('photo'): continue
        slug = ''.join(ch if ch.isalnum() else '-' for ch in c['n'].lower()).strip('-'); slug = '-'.join(p for p in slug.split('-') if p)
        for f in best_scene(c['lon'], c['lat'])[:6]:
            try: d = cut(f, c['lon'], c['lat'], os.path.join(outdir, slug + '.jpg'))
            except Exception as e: print('  fail', c['n'], e); d = None
            if d: res[c['n']] = {'file': slug + '.jpg', 'date': d, 'scene': f['id']}; print(c['n'], d, f['id']); break
        else: print('NO SCENE', c['n'])
    json.dump(res, open(os.path.join(outdir, 'above.json'), 'w'), indent=1)
if __name__ == '__main__': main(sys.argv[1], sys.argv[2])
