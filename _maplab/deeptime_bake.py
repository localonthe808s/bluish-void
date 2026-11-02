#!/usr/bin/env python3
"""
DEEP TIME (2026-11-01): the planet's 4.5 billion years as globe textures and a turning-globe video, for the GEOLOGY tab.

Three kinds of frame, oldest first, all equirectangular 1024 x 512 JPGs on R2 deeptime/frames/<age>.jpg:
  * schematic  4,500 - 1,900 Ma: no plate model exists this far back; the frames are drawn from what is known of the
                 surface (magma ocean, cooling crust, a water world, the first cratons gathering) and labelled as such.
  * plates     1,800 - 550 Ma: the continents of Cao et al. 2024 (CC BY 4.0), the 1.8-billion-year plate model, through
                 the GPlates Web Service (EarthByte), every 10 Myr, drawn as land on a plain ocean.
  * dem        540 - 0 Ma: PALEOMAP PaleoDEMs (Scotese & Wright 2018, CC BY 4.0, Zenodo 5460860): land height and
                 sea-floor depth every ~5 Myr, tinted like a classic paleogeographic map with a light hillshade.
deeptime/index.json lists the frames, the chapters and the sources. deeptime/globe_{d,m}.mp4 is the turning globe through
all of it (1080 / 540 px), ages crossfaded, the age burned in.

    python3 _maplab/deeptime_bake.py out                 # everything
    python3 _maplab/deeptime_bake.py out --quick         # a few ages of each kind, no video (a render check)
    python3 _maplab/deeptime_bake.py out --no-video
"""
import io, json, math, os, subprocess, sys, time, urllib.request, zipfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1024, 512
OUT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else 'out'
QUICK = '--quick' in sys.argv
NOVID = '--no-video' in sys.argv or QUICK
CACHE = os.environ.get('DEEPTIME_CACHE') or os.path.join(OUT, '_cache')
FR = os.path.join(OUT, 'deeptime', 'frames')
os.makedirs(FR, exist_ok=True); os.makedirs(CACHE, exist_ok=True)
UA = {'User-Agent': 'bluishvoid-deeptime-bake (https://bluishvoid.com)'}
PALEODEM_URL = 'https://zenodo.org/records/5460860/files/PaleoDEMS_long_lat_elev_csv_v2.zip?download=1'
GWS = 'https://gws.gplates.org/reconstruct/coastlines/?time=%d&model=CAO2024'


def fetch(url, name, tries=3):
    p = os.path.join(CACHE, name)
    if os.path.exists(p) and os.path.getsize(p) > 100:
        return open(p, 'rb').read()
    for k in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read()
            open(p, 'wb').write(b); return b
        except Exception as e:
            print('  retry', k + 1, name, e); time.sleep(6 * (k + 1))
    raise RuntimeError('could not fetch ' + url)


# ---------------------------------------------------------------- colour
def lerp(a, b, t):
    t = np.clip(t, 0, 1)[..., None]
    return np.asarray(a, float) * (1 - t) + np.asarray(b, float) * t


def tint_dem(elev):
    """elev: (H, W) metres -> (H, W, 3) uint8. Ocean by depth, land by height, a light hillshade."""
    e = elev
    img = np.zeros(e.shape + (3,), float)
    sea = e <= 0
    d = -e
    deep = lerp([10, 24, 58], [22, 58, 112], d / 5000.0)           # abyss -> basin
    shelf = lerp([96, 160, 200], [36, 92, 150], d / 400.0)          # the shelf, pale
    ocean = np.where((d < 400)[..., None], shelf, deep)
    img[sea] = ocean[sea]
    land = ~sea
    low = lerp([120, 150, 88], [178, 168, 104], e / 600.0)          # green plain -> tan
    mid = lerp([178, 168, 104], [150, 118, 86], (e - 600) / 1800.0)  # tan -> brown
    high = lerp([150, 118, 86], [236, 236, 236], (e - 2400) / 2600.0)  # brown -> snow
    lnd = np.where((e < 600)[..., None], low, np.where((e < 2400)[..., None], mid, high))
    img[land] = lnd[land]
    # hillshade from the gradient, light from the north-west
    gy, gx = np.gradient(np.maximum(e, 0) / 900.0)
    shade = 1 + 0.35 * (-gx * 0.7 - gy * 0.7)
    shade = np.clip(shade, 0.72, 1.18)
    img = img * np.where(land, shade, 1.0)[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


def ocean_base():
    yy = np.linspace(0, 1, H)[:, None] * np.ones((1, W))
    base = lerp([18, 46, 96], [28, 70, 128], 1 - np.abs(yy - 0.5) * 2)   # a little lighter at the equator
    return base


# ---------------------------------------------------------------- PALEODEM 540 - 0 Ma
def dem_frames():
    z = zipfile.ZipFile(io.BytesIO(fetch(PALEODEM_URL, 'paleodem_csv.zip')))
    names = sorted(n for n in z.namelist() if n.endswith('.csv'))
    out = []
    for n in names:
        age = int(n.split('_')[-1].replace('Ma.csv', ''))
        txt = z.read(n).decode('utf-8', 'replace').splitlines()
        rows = []
        for l in txt:                                   # some maps head with '# lon,lat,elev', others with 'longitude,latitude,...'
            parts = l.split(',')
            try:
                rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except (ValueError, IndexError):
                continue
        a = np.array(rows)
        lon, lat, el = a[:, 0], a[:, 1], a[:, 2]
        g = np.full((181, 361), np.nan)
        g[((90 - lat)).astype(int), ((lon + 180)).astype(int)] = el
        g = np.where(np.isnan(g), 0, g)
        im = Image.fromarray(g.astype(np.float32)).resize((W, H), Image.BICUBIC)
        e = np.asarray(im, float)
        out.append((age, 'dem', tint_dem(e), None))
    return out


# ---------------------------------------------------------------- CAO 2024 1800 - 550 Ma
def plate_frames(ages):
    out = []
    rng = np.random.default_rng(7)
    grain = rng.normal(0, 1, (H, W)); grain = np.asarray(Image.fromarray(np.clip(grain * 40 + 128, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)), float) / 255 - 0.5
    for age in ages:
        j = json.loads(fetch(GWS % age, 'cao2024_%04d.json' % age))
        mask = Image.new('L', (W, H), 0); dr = ImageDraw.Draw(mask)
        for f in j.get('features', []):
            gm = f.get('geometry') or {}
            polys = [gm['coordinates']] if gm.get('type') == 'Polygon' else gm.get('coordinates', []) if gm.get('type') == 'MultiPolygon' else []
            for poly in polys:
                for k, ring in enumerate(poly):
                    pts = [((lo + 180) / 360 * W, (90 - la) / 180 * H) for lo, la in ring]
                    if len(pts) >= 3:
                        dr.polygon(pts, fill=255 if k == 0 else 0)
        m = np.asarray(mask.filter(ImageFilter.GaussianBlur(0.6)), float) / 255
        land = lerp([168, 150, 112], [128, 104, 78], np.clip(grain * 2 + 0.5, 0, 1)) + grain[..., None] * 30
        img = ocean_base() * (1 - m[..., None]) + land * m[..., None]
        out.append((age, 'plates', np.clip(img, 0, 255).astype(np.uint8), None))
        print('  plates', age, 'Ma:', len(j.get('features', [])), 'polygons')
    return out


# ---------------------------------------------------------------- SCHEMATIC 4500 - 1900 Ma
def noise(seed, scale, octaves=4):
    rng = np.random.default_rng(seed); acc = np.zeros((H, W)); amp = 1.0; s = scale
    for _ in range(octaves):
        small = rng.normal(0, 1, (max(2, int(H / s)), max(2, int(W / s))))
        big = np.asarray(Image.fromarray(small.astype(np.float32)).resize((W, H), Image.BICUBIC), float)
        acc += big * amp; amp *= 0.5; s = max(2, s / 2)
    # seamless in longitude: blend with a half-turn copy under a window that is 0 at the dateline, so column W-1 meets column 0
    w = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(W) / W)[None, :]
    acc = acc * w + np.roll(acc, W // 2, axis=1) * (1 - w)
    acc = (acc - acc.min()) / (acc.max() - acc.min() + 1e-9)
    return acc


SCHEMATIC = [  # (age Ma, stage, the note the page shows)
    (4500, 'magma', 'A molten surface: the planet has just formed and is still sweeping up the debris of the young solar system.'),
    (4450, 'impact', 'Theia strikes: a Mars-sized body hits the young Earth; the Moon forms from the debris and the surface melts again.'),
    (4400, 'crust', 'A thin dark crust skins the magma ocean. The oldest surviving minerals, the Jack Hills zircons, date from now.'),
    (4200, 'crust2', 'The crust thickens and cracks; volcanoes vent the first atmosphere of steam and carbon dioxide.'),
    (4000, 'water', 'The steam rains out: a water world with a few volcanic islands. The Late Heavy Bombardment is ending.'),
    (3800, 'islands', 'Island arcs and the first slivers of continental crust; the oldest rocks (Acasta, Isua) form now.'),
    (3600, 'islands2', 'Life is already here: microbial mats leave the first stromatolites in shallow water.'),
    (3400, 'cratons', 'The first cratons, the stable cores of the continents, harden; plate tectonics may be starting.'),
    (3200, 'cratons2', 'Cratons grow by collision; the Kaapvaal and Pilbara blocks, perhaps joined, form the earliest supercontinent argued for, Vaalbara.'),
    (3000, 'cratons3', 'More continental crust than ever; greenstone belts wrap the cratons.'),
    (2800, 'kenor', 'The cratons gather into Kenorland, a supercontinent of the late Archean.'),
    (2600, 'kenor2', 'Kenorland stands; oxygen from photosynthesis begins to leak into the oceans.'),
    (2400, 'goe', 'The Great Oxidation Event: oxygen reaches the air, iron rusts out of the seas, and the first global ice age follows.'),
    (2200, 'huron', 'The Huronian glaciations: the planet freezes to the tropics several times.'),
    (2000, 'columbia', 'The pieces gather again: Columbia (Nuna), the first supercontinent whose outline is reconstructed.'),
    (1900, 'columbia2', 'Columbia assembles; from 1.8 billion years on the plates can be tracked.'),
]


def schematic_frame(age, stage, k):
    base = ocean_base()
    if stage in ('magma', 'impact', 'crust', 'crust2'):
        n1 = noise(10 + k, 48, 5); n2 = noise(20 + k, 12, 3)
        if stage == 'magma':
            img = lerp([30, 6, 2], [255, 120, 30], n1 ** 1.6) + lerp([0, 0, 0], [255, 220, 120], np.clip(n2 - 0.72, 0, 1) * 3)
        elif stage == 'impact':
            img = lerp([40, 8, 2], [255, 150, 40], n1 ** 1.3) + lerp([0, 0, 0], [255, 240, 180], np.clip(n2 - 0.6, 0, 1) * 2.5)
        elif stage == 'crust':
            img = lerp([24, 18, 16], [140, 40, 14], np.clip(n1 - 0.35, 0, 1) * 1.8) + lerp([0, 0, 0], [255, 140, 40], np.clip(n2 - 0.78, 0, 1) * 4)
        else:
            img = lerp([30, 26, 24], [88, 58, 40], n1) + lerp([0, 0, 0], [255, 120, 30], np.clip(n2 - 0.84, 0, 1) * 5)
        return np.clip(img, 0, 255).astype(np.uint8)
    # water world onward: land masks grow
    cover = {'water': 0.012, 'islands': 0.03, 'islands2': 0.045, 'cratons': 0.07, 'cratons2': 0.09, 'cratons3': 0.12,
             'kenor': 0.16, 'kenor2': 0.17, 'goe': 0.17, 'huron': 0.18, 'columbia': 0.2, 'columbia2': 0.22}[stage]
    n = noise(100 + (3 if stage in ('kenor', 'kenor2', 'goe', 'huron') else 5 if stage in ('columbia', 'columbia2') else k), 64 if cover > 0.1 else 20, 4)
    thr = np.quantile(n, 1 - cover)
    m = np.clip((n - thr) / 0.02, 0, 1)
    land = lerp([110, 96, 70], [150, 130, 96], noise(200 + k, 16, 3))
    img = base * (1 - m[..., None]) + land * m[..., None]
    if stage in ('water', 'islands'):
        glow = np.clip(noise(300 + k, 10, 2) - 0.9, 0, 1) * 10
        img = img + lerp([0, 0, 0], [255, 120, 40], glow) * (m[..., None] > 0.5)
    if stage in ('goe', 'huron'):   # ice to the tropics
        yy = np.abs(np.linspace(-1, 1, H))[:, None] * np.ones((1, W))
        ice = np.clip((yy - (0.45 if stage == 'huron' else 0.6)) / 0.1 + noise(400 + k, 24, 3) * 0.4, 0, 1)
        img = img * (1 - ice[..., None]) + np.array([226, 234, 242]) * ice[..., None]
    if stage == 'goe':   # rust in the seas
        img = img * (1 - m[..., None]) * np.array([1.08, 0.92, 0.84]) + img * m[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


def schematic_frames():
    out = []
    for k, (age, stage, note) in enumerate(SCHEMATIC):
        out.append((age, 'schematic', schematic_frame(age, stage, k), note))
    return out


# ---------------------------------------------------------------- chapters
CHAPTERS = [
    (4500, 'HADEAN', 'The planet forms'), (4450, 'HADEAN', 'The Moon is born'), (4400, 'HADEAN', 'The first crust'), (4000, 'ARCHEAN', 'Oceans'),
    (3700, 'ARCHEAN', 'The first life'), (3400, 'ARCHEAN', 'The first cratons'), (2800, 'ARCHEAN', 'Kenorland'), (2400, 'PROTEROZOIC', 'The Great Oxidation'),
    (2000, 'PROTEROZOIC', 'Columbia'), (1800, 'PROTEROZOIC', 'Plates can be tracked'), (1100, 'PROTEROZOIC', 'Rodinia'), (720, 'PROTEROZOIC', 'Snowball Earth'),
    (600, 'PROTEROZOIC', 'Pannotia and the first animals'), (540, 'PALEOZOIC', 'The Cambrian explosion'), (420, 'PALEOZOIC', 'Life walks onto land'),
    (300, 'PALEOZOIC', 'Pangaea'), (252, 'PALEOZOIC', 'The Great Dying'), (200, 'MESOZOIC', 'Pangaea splits'), (145, 'MESOZOIC', 'The Atlantic opens'),
    (66, 'CENOZOIC', 'The dinosaurs end'), (35, 'CENOZOIC', 'Antarctica freezes'), (3, 'CENOZOIC', 'The Ice Ages'), (0, 'CENOZOIC', 'Today'),
]
SOURCES = [
    ['PALEOMAP PaleoDEMs (Scotese & Wright 2018), CC BY 4.0', 'https://doi.org/10.5281/zenodo.5460860'],
    ['Cao et al. 2024, a 1.8-billion-year plate model, CC BY 4.0', 'https://doi.org/10.5281/zenodo.13628813'],
    ['GPlates Web Service (EarthByte)', 'https://gws.gplates.org/'],
]


# ---------------------------------------------------------------- the turning globe video
def ortho(tex, lat0, lon0, N):
    """tex (H, W, 3) equirect -> (N, N, 4) disc, lit a little from the limb."""
    y, x = np.mgrid[0:N, 0:N]
    u = (x + 0.5 - N / 2) / (N * 0.47); v = (N / 2 - y - 0.5) / (N * 0.47)
    rho = np.sqrt(u * u + v * v); inside = rho < 1
    rho = np.clip(rho, 1e-9, 1); c = np.arcsin(np.clip(rho, 0, 1)); sc, cc = np.sin(c), np.cos(c)
    p0, l0 = math.radians(lat0), math.radians(lon0)
    lat = np.arcsin(np.clip(cc * math.sin(p0) + v * sc * math.cos(p0) / rho, -1, 1))
    lon = l0 + np.arctan2(u * sc, rho * cc * math.cos(p0) - v * sc * math.sin(p0))
    row = np.clip(((np.pi / 2 - lat) / np.pi * H).astype(int), 0, H - 1)
    col = (((lon + np.pi) / (2 * np.pi)) % 1.0 * W).astype(int) % W
    rgb = tex[row, col].astype(float)
    shade = (0.7 + 0.3 * np.power(np.clip(cc, 0, 1), 0.6))[..., None]
    outp = np.zeros((N, N, 4), np.uint8)
    outp[..., :3] = np.clip(rgb * shade, 0, 255)
    outp[..., 3] = (inside * 255).astype(np.uint8)
    return outp


def video(frames, N, path, fps=24, seconds=64):
    """frames: [(age, kind, tex, note)] oldest first. The schedule gives the young, data-rich ages the most screen time."""
    ages = np.array([f[0] for f in frames], float)
    spans = [(4500, 1800, 0.28), (1800, 540, 0.27), (540, 0, 0.45)]   # share of the run
    total = fps * seconds; sched = []
    for a0, a1, share in spans:
        n = int(total * share)
        for i in range(n):
            sched.append(a0 + (a1 - a0) * (i / max(1, n - 1)))
    sched = sched[:total] + [0.0] * max(0, total - len(sched))
    font = None
    for fp in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/Library/Fonts/Arial Bold.ttf']:
        if os.path.exists(fp):
            font = ImageFont.truetype(fp, max(14, N // 34)); break
    tmp = os.path.join(OUT, '_vid_%d' % N); os.makedirs(tmp, exist_ok=True)
    order = np.argsort(-ages); ages_s = ages[order]
    for i, age in enumerate(sched):
        k = np.searchsorted(-ages_s, -age)   # first frame with age <= wanted
        k = min(max(k, 1), len(ages_s) - 1); older, younger = frames[order[k - 1]], frames[order[k]]
        t = 0.0 if older[0] == younger[0] else (older[0] - age) / (older[0] - younger[0])
        tex = (older[2].astype(float) * (1 - t) + younger[2].astype(float) * t).astype(np.uint8)
        lon0 = (i * 360.0 / (fps * 36)) % 360 - 180; lat0 = 12 * math.sin(i / (fps * 40))
        disc = ortho(tex, lat0, lon0, N)
        im = Image.new('RGB', (N, N), (4, 6, 12)); im.paste(Image.fromarray(disc[..., :3]), (0, 0), Image.fromarray(disc[..., 3]))
        if font:
            dr = ImageDraw.Draw(im)
            ma = int(round(age)); label = ('%s MILLION YEARS AGO' % format(ma, ',')) if ma >= 1 else 'TODAY'
            era = [c for c in CHAPTERS if c[0] >= ma][-1][1] if ma > 0 else 'TODAY'
            kind = 'SCHEMATIC' if age > 1800 else 'PLATE MODEL' if age > 540 else 'PALEO-TOPOGRAPHY'
            dr.text((N * 0.04, N * 0.90), label, fill=(255, 236, 200), font=font)
            dr.text((N * 0.04, N * 0.90 + font.size * 1.25), era + ' · ' + kind, fill=(190, 200, 220), font=ImageFont.truetype(font.path, max(11, font.size * 2 // 3)))
        im.save(os.path.join(tmp, 'f%05d.jpg' % i), quality=88)
        if i % 200 == 0:
            print('  video %d: frame %d/%d  %.0f Ma' % (N, i, total, age))
    subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(fps), '-i', os.path.join(tmp, 'f%05d.jpg'),
                           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '23', '-movflags', '+faststart', path])
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    print('wrote', path, os.path.getsize(path) // 1024, 'KB')


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    plate_ages = list(range(1800, 540, -10))
    if QUICK:
        plate_ages = [1800, 1100, 600]
    print('schematic frames'); frames = schematic_frames() if not QUICK else [f for f in schematic_frames() if f[0] in (4500, 4000, 2400)]
    print('plate frames (GPlates Web Service, Cao 2024)'); frames += plate_frames(plate_ages)
    print('PaleoDEM frames'); dem = dem_frames()
    if QUICK:
        dem = [f for f in dem if f[0] in (540, 300, 66, 0)]
    frames += dem
    frames.sort(key=lambda f: -f[0])
    index = {'built': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime()), 'w': W, 'h': H, 'frames': [], 'chapters': [{'ma': c[0], 'era': c[1], 'title': c[2]} for c in CHAPTERS],
             'notes': {str(a): n for a, s, n in SCHEMATIC}, 'sources': SOURCES, 'video': None if NOVID else {'d': 'deeptime/globe_d.mp4', 'm': 'deeptime/globe_m.mp4', 'seconds': 64}}
    for age, kind, tex, note in frames:
        fn = '%04d.jpg' % age
        Image.fromarray(tex).save(os.path.join(FR, fn), quality=84)
        index['frames'].append({'ma': age, 'kind': kind, 'file': 'deeptime/frames/' + fn})
    json.dump(index, open(os.path.join(OUT, 'deeptime', 'index.json'), 'w'), separators=(',', ':'))
    print('%d frames in %.0f s' % (len(frames), time.time() - t0))
    if not NOVID:
        video(frames, 1080, os.path.join(OUT, 'deeptime', 'globe_d.mp4'))
        video(frames, 540, os.path.join(OUT, 'deeptime', 'globe_m.mp4'))
    print('done in %.0f s' % (time.time() - t0))


if __name__ == '__main__':
    main()
