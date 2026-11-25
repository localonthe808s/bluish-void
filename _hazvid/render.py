"""THE RESTLESS PLANET, 1980-2024 (user 2026-11-25: "a visual that shows every earthquake tropical storm typhoon cyclone into one map
video that shows the overall trends of each, information isnt needed for each, this should stay cheap and easy").

One month per frame on our own world map (SUBDUCTION's earth_v2 texture). Earthquakes M5+ (USGS ComCat) flash as soft dots sized by
magnitude; every tropical storm (IBTrACS v04r01, reaching 34 kt) draws its month of track, colored by what its ocean calls it:
hurricanes orange (North Atlantic, East and Central Pacific), typhoons red (West Pacific), cyclones teal (Indian Ocean, South Pacific).
A slow-fading memory layer keeps where each has been, so the quake belts and storm tracks build up. Yearly bars along the bottom.

  ./fetch.sh            (data into cache/)
  python3 render.py     (frames -> out/restless_v1.mp4, 1280 wide; out/restless_v1_m.mp4, 720 wide)
"""
import csv, glob, math, os, subprocess, sys, collections, datetime
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, 'cache'); OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
Y0, Y1 = 1980, 2024   # 2025 left out: its storm tracks are provisional and the year is not over in the quake catalog
W, MAPH = 1280, 512            # the map: lat 72N .. 58S, equirectangular
LAT_N, LAT_S = 72.0, -58.0
BAR_H = 96; H = MAPH + BAR_H   # 608
FPS = 12
COL = {'hu': (251, 146, 60), 'ty': (248, 113, 113), 'cy': (45, 212, 191), 'q': (253, 230, 138)}
NAME = {'hu': 'HURRICANES', 'ty': 'TYPHOONS', 'cy': 'CYCLONES', 'q': 'EARTHQUAKES M5+'}

def xy(lat, lon):
    return (lon + 180.0) / 360.0 * W, (LAT_N - lat) / (LAT_N - LAT_S) * MAPH

def kind(basin, lon):
    if basin in ('NA',): return 'hu'
    if basin == 'EP': return 'hu'
    if basin == 'WP': return 'ty'
    return 'cy'

# ---- data
print('reading storms', flush=True)
storms = collections.defaultdict(list)   # sid -> [(t, lat, lon, kt, basin)]
r = csv.reader(open(os.path.join(C, 'ibtracs.csv'))); h = next(r); next(r)
I = {k: h.index(k) for k in ('SID', 'BASIN', 'ISO_TIME', 'NATURE', 'LAT', 'LON', 'WMO_WIND', 'USA_WIND', 'TRACK_TYPE')}
for row in r:
    if row[I['TRACK_TYPE']] != 'main': continue
    t = row[I['ISO_TIME']]; y = int(t[:4])
    if y < Y0 or y > Y1: continue
    try: la = float(row[I['LAT']]); lo = float(row[I['LON']])
    except ValueError: continue
    w = row[I['USA_WIND']].strip() or row[I['WMO_WIND']].strip(); kt = float(w) if w else 0.0
    storms[row[I['SID']]].append((t, la, lo, kt, row[I['BASIN']]))
named = {}
for sid, P in storms.items():
    if max(p[3] for p in P) < 34: continue          # a tropical storm at least
    P.sort(); named[sid] = P
print(len(named), 'storms', flush=True)

print('reading quakes', flush=True)
quakes = []
for f in sorted(glob.glob(os.path.join(C, 'q_*.csv'))):
    for q in csv.DictReader(open(f)):
        try: quakes.append((q['time'][:7], float(q['latitude']), float(q['longitude']), float(q['mag'])))
        except ValueError: pass
quakes = sorted(set(quakes))
print(len(quakes), 'quakes', flush=True)

months = ['%04d-%02d' % (y, m) for y in range(Y0, Y1 + 1) for m in range(1, 13)]
qby = collections.defaultdict(list)
for q in quakes: qby[q[0]].append(q)
sby = collections.defaultdict(list)      # month -> [(kind, [(x,y)...], kt)]
yr_storm = collections.defaultdict(lambda: collections.Counter()); yr_quake = collections.Counter()
for sid, P in named.items():
    k = kind(P[0][4], P[0][2]); yr_storm[int(P[0][0][:4])][k] += 1
    seg = collections.defaultdict(list)
    for i, p in enumerate(P):
        seg[p[0][:7]].append(p)
    prev = None
    for mo in sorted(seg):
        pts = ([prev] if prev else []) + seg[mo]
        sby[mo].append((k, [(p[1], p[2]) for p in pts], max(p[3] for p in seg[mo])))
        prev = seg[mo][-1]
for q in quakes: yr_quake[int(q[0][:4])] += 1

# ---- the base map
base = Image.open(os.path.join(C, 'earth_v2.webp')).convert('RGB')
bw, bh = base.size
top = int((90 - LAT_N) / 180 * bh); bot = int((90 - LAT_S) / 180 * bh)
base = base.crop((0, top, bw, bot)).resize((W, MAPH), Image.LANCZOS)
base = Image.blend(base, Image.new('RGB', base.size, (8, 10, 18)), 0.25)   # a touch darker so the marks carry

try:
    FB = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 30)
    FS = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 11)
    FM = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 13)
except Exception:
    FB = FS = FM = ImageFont.load_default()

def wrap_segments(pts):
    """split a track where it crosses the date line"""
    out, cur = [], []
    for la, lo in pts:
        if cur and abs(lo - cur[-1][1]) > 180: out.append(cur); cur = []
        cur.append((la, lo))
    if cur: out.append(cur)
    return out

# memory: a float RGB accumulation that fades
mem = np.zeros((MAPH, W, 3), np.float32); DECAY = 0.993
live_q = []    # (frames_left, x, y, r)
live_s = []    # (frames_left, kind, [xy..], width)
ymax_q = max(yr_quake.values()); ymax_s = max(sum(c.values()) for c in yr_storm.values())
frames_dir = os.path.join(OUT, 'frames'); os.makedirs(frames_dir, exist_ok=True)
for f in glob.glob(os.path.join(frames_dir, '*.png')): os.remove(f)

for fi, mo in enumerate(months):
    y = int(mo[:4]); m = int(mo[5:])
    # new events
    memL = Image.new('RGB', (W, MAPH)); md = ImageDraw.Draw(memL)
    for k, pts, kt in sby.get(mo, []):
        wid = 2 if kt < 64 else 3
        for seg in wrap_segments(pts):
            P = [xy(a, b) for a, b in seg]
            if len(P) > 1: md.line(P, fill=tuple(int(c * .2) for c in COL[k]), width=1)
            live_s.append([6, k, P, wid])
    for _, la, lo, mag in qby.get(mo, []):
        x, yy = xy(la, lo)
        if yy < 0 or yy > MAPH: continue
        r = 1.2 + (mag - 5) * 2.2
        md.ellipse((x - 1, yy - 1, x + 1, yy + 1), fill=tuple(int(c * .22) for c in COL['q']))
        live_q.append([4, x, yy, r, mag])
    mem = mem * DECAY + np.asarray(memL, np.float32)
    np.clip(mem, 0, 255, out=mem)
    # compose: base + memory (screen) + live glow
    frame = np.asarray(base, np.float32)
    frame = 255 - (255 - frame) * (255 - mem * 1.0) / 255
    img = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8))
    glow = Image.new('RGB', (W, MAPH)); gd = ImageDraw.Draw(glow)
    sharp = Image.new('RGBA', (W, MAPH), (0, 0, 0, 0)); sd = ImageDraw.Draw(sharp)
    for L in live_s:
        a = L[0] / 6.0; c = COL[L[1]]
        if len(L[2]) > 1:
            gd.line(L[2], fill=tuple(int(v * a) for v in c), width=L[3] + 5)
            sd.line(L[2], fill=c + (int(255 * a),), width=L[3])
    for Q in live_q:
        a = Q[0] / 4.0; x, yy, r = Q[1], Q[2], Q[3] * (1.25 - .25 * a)
        gd.ellipse((x - r * 2.2, yy - r * 2.2, x + r * 2.2, yy + r * 2.2), fill=tuple(int(v * a * .7) for v in COL['q']))
        sd.ellipse((x - r, yy - r, x + r, yy + r), fill=COL['q'] + (int(230 * a),))
    glow = glow.filter(ImageFilter.GaussianBlur(4))
    g = np.asarray(glow, np.float32); fr = np.asarray(img, np.float32)
    img = Image.fromarray(np.clip(255 - (255 - fr) * (255 - g) / 255, 0, 255).astype(np.uint8))
    img.paste(sharp, (0, 0), sharp)
    live_s = [[L[0] - 1] + L[1:] for L in live_s if L[0] > 1]
    live_q = [[Q[0] - 1] + Q[1:] for Q in live_q if Q[0] > 1]

    # the canvas with the bars under the map
    full = Image.new('RGB', (W, H), (8, 10, 18)); full.paste(img, (0, 0)); d = ImageDraw.Draw(full)
    MN = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
    d.text((18, 14), str(y), font=FB, fill=(255, 255, 255)); d.text((18 + d.textlength(str(y), font=FB) + 8, 28), MN[m - 1], font=FM, fill=(200, 205, 220))
    lx = 18; ly = MAPH - 22
    for k in ('q', 'hu', 'ty', 'cy'):
        d.ellipse((lx, ly + 2, lx + 9, ly + 11), fill=COL[k]); d.text((lx + 14, ly), NAME[k], font=FS, fill=(230, 232, 240)); lx += 36 + d.textlength(NAME[k], font=FS)
    # yearly bars: quakes on the left half, storms (stacked by kind) on the right half
    n = Y1 - Y0 + 1; pad = 18; half = (W - pad * 3) / 2; bw2 = half / n; by0 = MAPH + 26; bh2 = BAR_H - 40
    d.text((pad, MAPH + 8), 'EARTHQUAKES M5+ A YEAR', font=FS, fill=(253, 230, 138)); d.text((pad * 2 + half, MAPH + 8), 'TROPICAL STORMS A YEAR', font=FS, fill=(230, 232, 240))
    for i, yy2 in enumerate(range(Y0, Y1 + 1)):
        if yy2 > y: break
        cur = yy2 == y; f = (m / 12.0) if cur else 1.0
        hq = bh2 * yr_quake[yy2] / ymax_q * f; x0 = pad + i * bw2
        d.rectangle((x0, by0 + bh2 - hq, x0 + bw2 - 1.5, by0 + bh2), fill=COL['q'] if cur else (150, 135, 90))
        x1 = pad * 2 + half + i * bw2; acc = 0
        for k in ('hu', 'ty', 'cy'):
            v = bh2 * yr_storm[yy2][k] / ymax_s * f
            c = COL[k] if cur else tuple(int(cc * .6) for cc in COL[k])
            d.rectangle((x1, by0 + bh2 - acc - v, x1 + bw2 - 1.5, by0 + bh2 - acc), fill=c); acc += v
    for i, yy2 in enumerate(range(Y0, Y1 + 1, 10)):
        for xb in (pad, pad * 2 + half):
            d.text((xb + (yy2 - Y0) * bw2, by0 + bh2 + 3), str(yy2), font=FS, fill=(130, 136, 155))
    full.save(os.path.join(frames_dir, '%04d.png' % fi))
    if fi % 60 == 0: print(mo, flush=True)

# hold the last frame two seconds
last = os.path.join(frames_dir, '%04d.png' % (len(months) - 1))
for j in range(FPS * 2):
    Image.open(last).save(os.path.join(frames_dir, '%04d.png' % (len(months) + j)))
for name, scale, crf in (('restless_v1.mp4', W, 27), ('restless_v1_m.mp4', 720, 28)):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-framerate', str(FPS), '-i', os.path.join(frames_dir, '%04d.png'), '-vf', 'scale=%d:-2' % scale,
                    '-c:v', 'libx264', '-preset', 'slow', '-crf', str(crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', os.path.join(OUT, name)], check=True)
    print(name, os.path.getsize(os.path.join(OUT, name)) // 1024, 'KB')
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', os.path.join(frames_dir, '%04d.png' % (len(months) - 1)), '-q:v', '4', os.path.join(OUT, 'restless_v1_poster.jpg')], check=True)
