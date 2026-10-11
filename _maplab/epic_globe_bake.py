"""EPIC GLOBE: stitch one day of NASA DSCOVR/EPIC natural-colour frames into a 2048x1024 equirectangular map of the real
Earth (real clouds, EPIC's own colours), for the spinning globes in BEHIND THE BLUE (TONIGHT + EARTH VIEW).
User 2026-10-11: "can the earth realistically spin as it would for the tonight and earth view".

Each frame is the sunlit disc seen from L1, north up, centred on its centroid lat/lon (orthographic). Every map pixel
blends the frames where it sits nearest the disc centre (weight cos(c)^5, frames used out to cos c 0.13, c = angular distance from the centroid), so the
limb (smeared, hazy) barely counts; pixels no frame sees well (the poles, near the limb in every frame) fall back to Blue
Marble Next Generation, warmed toward EPIC's tones. Disc geometry measured on the 1080 px jpg: centre (540, 542), r 401.
Output: earth/globe/epic.jpg + epic.json (frame date, count) on R2.  Run: python3 epic_globe_bake.py [outdir]"""
import io, json, math, sys, os, urllib.request
import numpy as np
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else '.'
W, H = 2048, 1024
UA = {'User-Agent': 'bluishvoid-epic-globe/1.0'}
def get(u, t=60): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t).read()

meta = json.loads(get('https://epic.gsfc.nasa.gov/api/natural'))
lon = (np.arange(W) + 0.5) / W * 360 - 180
lat = 90 - (np.arange(H) + 0.5) / H * 180
LON, LAT = np.meshgrid(np.radians(lon), np.radians(lat))
acc = np.zeros((H, W, 3)); wsum = np.zeros((H, W))
CX, CY, R = 540.0, 542.0, 401.0
used = 0
for m in meta:
    d = m['date'][:10].split('-')
    url = 'https://epic.gsfc.nasa.gov/archive/natural/%s/%s/%s/jpg/%s.jpg' % (d[0], d[1], d[2], m['image'])
    try: im = np.asarray(Image.open(io.BytesIO(get(url))).convert('RGB')).astype(np.float64)
    except Exception as e: print('skip', m['image'], e); continue
    p0, l0 = math.radians(m['centroid_coordinates']['lat']), math.radians(m['centroid_coordinates']['lon'])
    cosc = np.sin(p0) * np.sin(LAT) + np.cos(p0) * np.cos(LAT) * np.cos(LON - l0)
    x = np.cos(LAT) * np.sin(LON - l0); y = np.cos(p0) * np.sin(LAT) - np.sin(p0) * np.cos(LAT) * np.cos(LON - l0)
    px = CX + x * R; py = CY - y * R
    ok = cosc > 0.13
    xi = np.clip(np.round(px).astype(int), 0, im.shape[1] - 1); yi = np.clip(np.round(py).astype(int), 0, im.shape[0] - 1)
    w = np.where(ok, np.clip(cosc, 0, 1) ** 5, 0.0)
    acc += im[yi, xi] * w[..., None]; wsum += w; used += 1
    print('frame', m['date'], 'centroid', round(math.degrees(l0), 1))
col = acc / np.maximum(wsum, 1e-9)[..., None]
# the fallback where no frame saw it well: Blue Marble, warmed and lifted toward EPIC's hazier tones
bm = np.asarray(Image.open(io.BytesIO(get('https://wvs.earthdata.nasa.gov/api/v1/snapshot?REQUEST=GetSnapshot&LAYERS=BlueMarble_NextGeneration&CRS=EPSG:4326&WIDTH=%d&HEIGHT=%d&BBOX=-90,-180,90,180&FORMAT=image/jpeg' % (W, H), 120))).convert('RGB').resize((W, H))).astype(np.float64)
bm = bm * 0.85 + np.array([18, 30, 52]) * 0.6
fade = np.clip((wsum - 4e-5) / 2e-3, 0, 1)[..., None] ** 0.7
outp = col * fade + bm * (1 - fade)
os.makedirs(OUT, exist_ok=True)
Image.fromarray(np.clip(outp, 0, 255).astype(np.uint8)).save(os.path.join(OUT, 'epic.jpg'), quality=84, optimize=True, progressive=True)
json.dump({'date': meta[0]['date'][:10] if meta else None, 'frames': used, 'built': __import__('datetime').datetime.utcnow().isoformat(timespec='minutes') + 'Z',
           'source': 'NASA DSCOVR/EPIC natural colour, stitched; poles from NASA Blue Marble Next Generation'}, open(os.path.join(OUT, 'epic.json'), 'w'))
print('wrote', used, 'frames')
