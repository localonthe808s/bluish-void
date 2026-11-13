import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as nd
Image.MAX_IMAGE_PIXELS = None
OD, OSM, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
X0, Y1, RES, T, nx, ny = open(os.path.join(OD, 'grid.txt')).read().split(); X0, Y1, RES = float(X0), float(Y1), float(RES); T, nx, ny = int(T), int(nx), int(ny)
R = 6378137
mx = lambda lon: math.radians(lon) * R; my = lambda lat: R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
W, H = nx * T, ny * T
img = np.zeros((H, W, 3), np.uint8)
for j in range(ny):
  for i in range(nx):
    img[j*T:(j+1)*T, i*T:(i+1)*T] = np.asarray(Image.open(os.path.join(OD, 't_%d_%d.png' % (i, j))).convert('RGB'))
px = lambda lon, lat: ((mx(lon) - X0) / RES, (Y1 - my(lat)) / RES)
d = json.load(open(OSM))['elements']
cem = [e for e in d if e.get('tags', {}).get('landuse') == 'cemetery'][0]
poly = [px(g['lon'], g['lat']) for g in cem['geometry']]
m = Image.new('L', (W, H), 0); ImageDraw.Draw(m).polygon(poly, fill=1)
road = Image.new('L', (W, H), 0); dr = ImageDraw.Draw(road)
for e in d:
  hw = e.get('tags', {}).get('highway')
  if not hw: continue
  w = 4.5 if hw in ('service', 'track') else 2.2   # drives 4.5 m, paths 2.2 m (the NYC widths)
  dr.line([px(g['lon'], g['lat']) for g in e['geometry']], fill=1, width=int(round((w + 2.0) / 0.25)))
inside = np.asarray(m, bool) & ~np.asarray(road, bool)
f = img.astype(np.float32)
L = 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]
mxc = f.max(2); mnc = f.min(2); S = (mxc - mnc) / np.maximum(mxc, 1)
# A HEADSTONE IS A PALE GREY STONE WITH ITS SHADOW TO THE NORTHWEST: these spring flights have the sun low in the southeast (the trees'
# shadows run up-left), so each stone is a small bright, grey spot -- brighter than its 3 m surroundings, low in color, not the yellow of
# dry grass -- with a dark patch within ~1.5 m up and to its left. Big shadows (trees) and big pale shapes (paths, plinths) drop on size.
th = L - nd.grey_opening(L, footprint=np.ones((13, 13)))
TH = float(sys.argv[4]) if len(sys.argv) > 4 else 34
bb = f[..., 2] - (f[..., 0] + f[..., 1]) / 2
cand = inside & (th > TH) & (S < 0.20) & (bb > -12) & (L > 135)
lab, n = nd.label(cand)
area = nd.sum(cand, lab, np.arange(1, n + 1))
ok = np.where((area >= 2) & (area <= 90))[0] + 1
cyx = np.array(nd.center_of_mass(cand, lab, ok)) if len(ok) else np.zeros((0, 2))
loc = nd.uniform_filter(L, 25)
DM = float(sys.argv[5]) if len(sys.argv) > 5 else 25
cx, cy = [], []
for (y, x) in cyx:
  yi, xi = int(round(y)), int(round(x))
  if loc[yi, xi] < 95: continue
  win = L[max(0, yi - 7):yi + 1, max(0, xi - 7):xi + 1]
  if win.size and win.min() < loc[yi, xi] - DM: cx.append(x); cy.append(y)
cx, cy = np.array(cx), np.array(cy); n_sh = n
# MODE "lawn" (St. Agnes, 2026-11-12): a newer lawn cemetery -- polished DARK granite stones and rows of small WHITE flat markers on bright
# mowed grass, beside woods. Any small mark clearly brighter OR darker than the grass around it counts, but only where its 4 m surroundings are
# green lawn (G above R and B), which drops the woods, the brush and the dirt. Tree shadows: large, so they fail the size cut.
if os.environ.get('CEM_MODE') == 'lawn':
  g7 = nd.uniform_filter(f[..., 1], 31); r7 = nd.uniform_filter(f[..., 0], 31); b7 = nd.uniform_filter(f[..., 2], 31)
  med = nd.median_filter(L, size=15)
  lawn = (g7 > r7 + 4) & (g7 > b7 + 3) & (med > 80)
  th2 = L - nd.grey_opening(L, footprint=np.ones((9, 9)))
  dark = (L < 68) & (med - L > 35)                     # polished granite: truly dark on bright mowed grass
  bright = (th2 > 24) & (S < .22) & (L > 140)           # white flat markers and pale stones
  mk = inside & lawn & (dark | bright)
  lab2, n2 = nd.label(mk); ar2 = nd.sum(mk, lab2, np.arange(1, n2 + 1))
  ok2 = np.where((ar2 >= 2) & (ar2 <= 60))[0] + 1
  yx = np.array(nd.center_of_mass(mk, lab2, ok2)) if len(ok2) else np.zeros((0, 2))
  cy, cx = yx[:, 0], yx[:, 1]; print('lawn mode: marks', n2, 'sized', len(ok2))
print('pale spots', n, 'sized', len(ok), 'with a shadow NW', len(cx))
np.save(os.path.join(OUT, 'stones_px.npy'), np.vstack([cx, cy]).T)
# a check crop over the sample area: red dots on the photo
CK = [float(v) for v in sys.argv[6].split(',')] if len(sys.argv) > 6 else [-73.7338, 42.7066, -73.7318, 42.7056]   # check crop: W,N,E,S
sx0, sy0 = px(CK[0], CK[1]); sx1, sy1 = px(CK[2], CK[3])
crop = Image.fromarray(img[int(sy0):int(sy1), int(sx0):int(sx1)]).convert('RGB'); crop = crop.resize((crop.width * 3, crop.height * 3), Image.NEAREST); dc = ImageDraw.Draw(crop)
for x, y in zip(cx, cy):
  if sx0 <= x < sx1 and sy0 <= y < sy1: X, Y = (x - sx0) * 3, (y - sy0) * 3; dc.rectangle([X - 4, Y - 4, X + 4, Y + 4], outline=(255, 40, 40), width=2)
crop.save(os.path.join(OUT, 'check.png'))
