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
import io, json, math, os, re, subprocess, sys, time, urllib.request, zipfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 2048, 1024          # 2048 since 2026-11-02 (the 6-arc-minute PaleoDEMs; the user: "can we improve the resolution")
OUT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else 'out'
QUICK = '--quick' in sys.argv
NOVID = '--video' not in sys.argv   # the page draws the globe itself now; the mp4 is opt-in (it holds every frame in memory)
CACHE = os.environ.get('DEEPTIME_CACHE') or os.path.join(OUT, '_cache')
FR = os.path.join(OUT, 'deeptime', 'frames')
os.makedirs(FR, exist_ok=True); os.makedirs(CACHE, exist_ok=True)
UA = {'User-Agent': 'bluishvoid-deeptime-bake (https://bluishvoid.com)'}
PALEODEM_URL = 'https://zenodo.org/api/records/5460860/files/Scotese_Wright_2018_Maps_1-88_6minX6min_PaleoDEMS_nc.zip/content'   # 207 MB, netCDF, 0.1 deg
GWS_PTS = 'https://gws.gplates.org/reconstruct/reconstruct_points/?points=%s&time=%d&model=CAO2024'
GWS = 'https://gws.gplates.org/reconstruct/coastlines/?time=%d&model=CAO2024'
GWS_B = 'https://gws.gplates.org/topology/plate_boundaries/?time=%d&model=CAO2024'
GWS_P = 'https://gws.gplates.org/topology/plate_polygons/?time=%d&model=CAO2024'


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
    ew = np.pad(np.maximum(e, 0) / 450.0, ((0, 0), (1, 1)), mode='wrap')   # per-pixel slope at 2048 is half the 1024 one
    gy, gx = np.gradient(ew); gy, gx = gy[:, 1:-1], gx[:, 1:-1]            # the shade wraps at the dateline too
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
    """The 6-arc-minute PaleoDEMs (1801 x 3601 netCDF, lon -180..180 with the dateline column twice) -> (age, 'dem', tex)."""
    import netCDF4, tempfile
    z = zipfile.ZipFile(io.BytesIO(fetch(PALEODEM_URL, 'paleodem_6min.zip')))
    names = sorted(n for n in z.namelist() if n.endswith('.nc') and '__MACOSX' not in n and not os.path.basename(n).startswith('._'))   # the zip carries resource forks
    out = []
    for n in names:
        age = int(re.search(r'_(\d+)Ma\.nc$', n).group(1))
        with tempfile.NamedTemporaryFile(suffix='.nc', delete=False) as tf:
            tf.write(z.read(n)); path = tf.name
        try:
            d = netCDF4.Dataset(path); zv = d.variables['z']; lat = d.variables['latitude'][:]
            g = np.array(zv[:], float)
            if lat[0] < lat[-1]:
                g = g[::-1]                                  # north up
            g = np.where(np.isfinite(g), g, np.nan)[:, :3600]    # the duplicate dateline column goes
            d.close()
        finally:
            os.remove(path)
        for _ in range(3):
            nan = np.isnan(g)
            if not nan.any():
                break
            pad = np.pad(g, 1, mode='edge'); nb = np.stack([pad[:-2, 1:-1], pad[2:, 1:-1], pad[1:-1, :-2], pad[1:-1, 2:]])
            fill = np.nanmean(np.where(np.isnan(nb), np.nan, nb), axis=0); g = np.where(nan & ~np.isnan(fill), fill, g)
        g = np.where(np.isnan(g), -4000.0, g)
        PADC = 40; gp = np.concatenate([g[:, -PADC:], g, g[:, :PADC]], axis=1); padpx = int(round(PADC * W / 3600.0))
        im = Image.fromarray(gp.astype(np.float32)).resize((W + 2 * padpx, H), Image.BICUBIC)
        e = np.asarray(im, float)[:, padpx:padpx + W]
        out.append((age, 'dem', tint_dem(e), None))
        print('  dem', age, 'Ma')
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
    # the poles: an equirectangular noise pinches to a star at the pole on the globe (seen 2026-11-02); the schematic land fades out above 72 deg
    latw = np.clip((84 - np.abs(np.linspace(90, -90, H)[:, None])) / 12.0, 0, 1)
    m = m * latw
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


# ---------------------------------------------------------------- PLATE BOUNDARIES 1800 - 0 Ma (2026-11-02, after the Howtown review)
# The Cao et al. 2024 model carries typed, named plate boundaries with the subduction polarity, and the plate outlines; the
# service gives them per age. Baked small: deeptime/bounds/<age>.json = [[type, name, polarity, [[lon,lat],...]], ...] at 0.1 deg,
# and a per-age tally in the index (km of subduction, ridge and transform, the plate count) -- the paper's own measure of the
# planet's tectonic pulse.
BTYPE = {'SubductionZone': 'S', 'MidOceanRidge': 'R', 'Transform': 'T'}


def boundary_frames(ages):
    os.makedirs(os.path.join(OUT, 'deeptime', 'bounds'), exist_ok=True)
    stats = {}
    for age in ages:
        try:
            j = json.loads(fetch(GWS_B % age, 'cao2024_b_%04d.json' % age))
        except Exception as e:
            print('  bounds', age, 'failed', e); continue
        rows, km = [], {'S': 0.0, 'R': 0.0, 'T': 0.0, 'O': 0.0}
        for f in j.get('features', []):
            pr = f.get('properties') or {}; gm = f.get('geometry') or {}
            t = BTYPE.get(pr.get('type'), 'O'); km[t] += (pr.get('length') or 0) * 6371
            if t == 'O':
                continue
            lines = [gm['coordinates']] if gm.get('type') == 'LineString' else gm.get('coordinates', []) if gm.get('type') == 'MultiLineString' else []
            for ln in lines:
                pts = [[round(p[0], 1), round(p[1], 1)] for p in ln]
                keep = [pts[0]] + [p for k, p in enumerate(pts[1:], 1) if p != pts[k - 1]]
                if len(keep) >= 2:
                    rows.append([t, str(pr.get('name') or '')[:60], (str(pr.get('polarity') or '')[:1] or ''), keep])
        try:
            pj = json.loads(fetch(GWS_P % age, 'cao2024_p_%04d.json' % age)); nplates = len(pj.get('features', []))
        except Exception:
            nplates = None
        with open(os.path.join(OUT, 'deeptime', 'bounds', '%04d.json' % age), 'w') as fh:
            json.dump(rows, fh, separators=(',', ':'))
        stats[str(age)] = {'sub': int(km['S']), 'ridge': int(km['R']), 'trans': int(km['T']), 'plates': nplates, 'n': len(rows)}
        if age % 100 == 0:
            print('  bounds %4d Ma: %3d lines, subduction %6d km, ridges %6d km, plates %s' % (age, len(rows), km['S'], km['R'], nplates))
    return stats


# ---------------------------------------------------------------- THE LANDS (2026-11-02: "add the names of these earlier bodies of land")
# Each ancient landmass is anchored to a point on it today; the GPlates service carries the point back through the Cao 2024
# model, one call per age. Tier 1 = supercontinents, tier 2 = cratons and continents. 999.99 = not on a tracked plate: skipped.
LANDS = [   # (name, lon, lat, from Ma, to Ma, tier)
    ('Nuna', -85, 60, 1800, 1300, 1), ('Rodinia', -85, 60, 1100, 750, 1), ('Pannotia', 20, 0, 620, 560, 1), ('Gondwana', 20, 0, 550, 180, 1),
    ('Laurussia', -85, 60, 420, 340, 1), ('Pangaea', -5, 15, 335, 180, 1), ('Laurasia', -85, 60, 180, 66, 1),
    ('Laurentia', -85, 60, 1800, 420, 2), ('Baltica', 37, 55, 1800, 420, 2), ('Siberia', 100, 60, 1800, 250, 2), ('Amazonia', -60, -5, 1800, 550, 2),
    ('West Africa', -5, 15, 1800, 550, 2), ('Congo', 20, 0, 1800, 550, 2), ('Kalahari', 23, -25, 1800, 550, 2), ('India', 78, 22, 1800, 550, 2),
    ('Australia', 135, -25, 1800, 550, 2), ('North China', 115, 38, 1800, 250, 2), ('South China', 110, 28, 1000, 250, 2), ('Avalonia', -64, 45, 500, 420, 2),
    ('Antarctica', -20, -80, 600, 550, 2),
    ('North America', -100, 45, 180, 0, 2), ('Europe', 15, 50, 180, 0, 2), ('Asia', 100, 50, 180, 0, 2), ('Africa', 20, 5, 180, 0, 2),
    ('South America', -60, -10, 130, 0, 2), ('India', 78, 22, 130, 0, 2), ('Australia', 135, -25, 100, 0, 2), ('Antarctica', -20, -80, 100, 0, 2),
]


def lands_by_age(ages):
    out = {}
    for age in ages:
        want = [L for L in LANDS if L[3] >= age >= L[4]]
        if not want:
            continue
        pts = ','.join('%s,%s' % (L[1], L[2]) for L in want)
        try:
            j = json.loads(fetch(GWS_PTS % (pts, age), 'cao2024_lands_%04d.json' % age))
        except Exception as e:
            print('  lands', age, 'failed', e); continue
        rows = []
        for L, c in zip(want, j.get('coordinates') or []):
            if c and c[0] < 400 and c[1] < 400:
                rows.append([L[0], round(c[0], 1), round(c[1], 1), L[5]])
        out[str(age)] = rows
    return out


# ---------------------------------------------------------------- chapters
CHAPTERS = [
    (4500, 'HADEAN', 'The planet forms'), (4450, 'HADEAN', 'The Moon is born'), (4400, 'HADEAN', 'The first crust'), (4000, 'ARCHEAN', 'Oceans'),
    (3700, 'ARCHEAN', 'The first life'), (3400, 'ARCHEAN', 'The first cratons'), (3200, 'ARCHEAN', 'Vaalbara'), (2800, 'ARCHEAN', 'Kenorland'), (2400, 'PROTEROZOIC', 'The Great Oxidation'),
    (2000, 'PROTEROZOIC', 'Columbia'), (1800, 'PROTEROZOIC', 'Plates can be tracked'), (1600, 'PROTEROZOIC', 'Nuna stands'), (1300, 'PROTEROZOIC', 'Nuna breaks up'),
    (1100, 'PROTEROZOIC', 'Rodinia and the Grenville mountains'), (750, 'PROTEROZOIC', 'Rodinia breaks up'), (717, 'PROTEROZOIC', 'Snowball Earth: the Sturtian'),
    (650, 'PROTEROZOIC', 'Snowball Earth: the Marinoan'), (600, 'PROTEROZOIC', 'Pannotia and the first animals'), (540, 'PALEOZOIC', 'The Cambrian explosion'),
    (480, 'PALEOZOIC', 'The Great Unconformity is buried'), (420, 'PALEOZOIC', 'The Caledonian mountains, life walks onto land'), (375, 'PALEOZOIC', 'Laurussia and the Acadian mountains'),
    (320, 'PALEOZOIC', 'The coal forests'), (300, 'PALEOZOIC', 'Pangaea'), (252, 'PALEOZOIC', 'The Great Dying'), (200, 'MESOZOIC', 'Pangaea splits'), (145, 'MESOZOIC', 'The Atlantic opens'),
    (66, 'CENOZOIC', 'The dinosaurs end'), (50, 'CENOZOIC', 'India hits Asia'), (35, 'CENOZOIC', 'Antarctica freezes'), (3, 'CENOZOIC', 'The Ice Ages'), (0, 'CENOZOIC', 'Today'),
]
SOURCES = [
    ['PALEOMAP PaleoDEMs (Scotese & Wright 2018), CC BY 4.0', 'https://doi.org/10.5281/zenodo.5460860'],
    ['Cao et al. 2024, a 1.8-billion-year plate model, CC BY 4.0', 'https://doi.org/10.5281/zenodo.13628813'],
    ['GPlates Web Service (EarthByte)', 'https://gws.gplates.org/'],
    ['Howtown, 4 billion years of tectonics in 17 minutes (the review that added the boundaries and chapters)', 'https://www.youtube.com/watch?v=t1hOdm0RJlY'],
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


def land_centre(tex):
    """The mean direction of the non-ocean pixels, cos(lat)-weighted -> (lat, lon) or None for an all-ocean or molten frame."""
    a = tex[::4, ::4].astype(float); H2, W2 = a.shape[:2]
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    land = ~((B > R + 18) & (B > G + 6))
    lat = np.radians(90 - (np.arange(H2) + 0.5) / H2 * 180)[:, None]; lon = np.radians((np.arange(W2) + 0.5) / W2 * 360 - 180)[None, :]
    w = np.cos(lat) * land
    x = (w * np.cos(lat) * np.cos(lon)).sum(); y = (w * np.cos(lat) * np.sin(lon)).sum(); z = (w * np.sin(lat)).sum(); n = w.sum()
    if n < 60 or math.hypot(x, y, z) / n < 0.08:
        return None
    return (math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x)))


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
    cen = [land_centre(f[2]) for f in frames]
    cam_lon, cam_lat = -40.0, 12.0
    for i, age in enumerate(sched):
        k = np.searchsorted(-ages_s, -age)   # first frame with age <= wanted
        k = min(max(k, 1), len(ages_s) - 1); older, younger = frames[order[k - 1]], frames[order[k]]
        t = 0.0 if older[0] == younger[0] else (older[0] - age) / (older[0] - younger[0])
        tex = (older[2].astype(float) * (1 - t) + younger[2].astype(float) * t).astype(np.uint8)
        # the camera eases toward where the land is (the nearer frame's centre), with a slow swing so it still turns
        c = cen[order[k]] or cen[order[k - 1]]
        if c:
            dl = ((c[1] - cam_lon + 540) % 360) - 180; cam_lon = ((cam_lon + dl * 0.03 + 540) % 360) - 180
            cam_lat += (max(-45.0, min(45.0, c[0])) - cam_lat) * 0.02
        else:
            cam_lon = ((cam_lon + 0.18 + 540) % 360) - 180
        lon0 = cam_lon + 28 * math.sin(i / (fps * 11.0)); lat0 = cam_lat + 8 * math.sin(i / (fps * 17.0))
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
    print('plate boundaries and the tectonic tally (GPlates Web Service, Cao 2024)'); bstats = boundary_frames([1800, 1100, 300, 0] if QUICK else list(range(1800, -1, -10)))
    print('the lands by age'); lands = lands_by_age([1800, 1100, 300, 0] if QUICK else list(range(1800, -1, -10)))
    print('PaleoDEM frames'); dem = dem_frames()
    if QUICK:
        dem = [f for f in dem if f[0] in (540, 300, 66, 0)]
    frames += dem
    frames.sort(key=lambda f: -f[0])
    index = {'built': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime()), 'w': W, 'h': H, 'frames': [], 'chapters': [{'ma': c[0], 'era': c[1], 'title': c[2]} for c in CHAPTERS],
             'notes': {str(a): n for a, s, n in SCHEMATIC}, 'sources': SOURCES, 'bounds': {'every': 10, 'from': 1800, 'stats': bstats}, 'lands': lands, 'video': None if NOVID else {'d': 'deeptime/globe_d.mp4', 'm': 'deeptime/globe_m.mp4', 'seconds': 64}}
    for age, kind, tex, note in frames:
        fn = '%04d.jpg' % age
        Image.fromarray(tex).save(os.path.join(FR, fn), quality=86)
        index['frames'].append({'ma': age, 'kind': kind, 'file': 'deeptime/frames/' + fn})
    json.dump(index, open(os.path.join(OUT, 'deeptime', 'index.json'), 'w'), separators=(',', ':'))
    print('%d frames in %.0f s' % (len(frames), time.time() - t0))
    if not NOVID:
        video(frames, 1080, os.path.join(OUT, 'deeptime', 'globe_d.mp4'))
        video(frames, 540, os.path.join(OUT, 'deeptime', 'globe_m.mp4'))
    print('done in %.0f s' % (time.time() - t0))


if __name__ == '__main__':
    main()
