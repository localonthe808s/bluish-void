#!/usr/bin/env python3
"""The SPACE tab's OBSERVATORIES NOW "GREATEST HITS" row (user 2026-09-24: "do a 2nd row of
photos for the most beautiful / well known / coolest from each").

A hand-picked list -- each observatory's signature images, chosen from the agencies' own
galleries (ESA/Webb's and ESA/Hubble's lead top-100 picks, Chandra's photo album, ESA's Euclid
releases, Rubin's First Look, NASA's photojournal, SVS and PIA archive) -- fetched once,
resized to 640 px WebP and served from our own origin, with each picture's credit and licence.
Roman has no row: it has not taken a sky image yet.

Writes _solarlab/classics/<key>-<n>.webp and _solarlab/classics.json. Run by hand when the
list changes; the 3-hourly observatories bake folds classics.json into observatories.json.

usage: build_classics.py
"""
import io, json, re, time, urllib.request
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'classics'
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid-bake; +https://bluishvoid.com)'}

WEBB = ('NASA, ESA, CSA, STScI', 'CC BY 4.0')
HUBBLE = ('NASA, ESA', 'CC BY 4.0')
CXC = ('NASA/CXC/SAO', 'NASA image, free use with credit')
EUCLID = ('ESA/Euclid/Euclid Consortium/NASA', 'CC BY-SA 3.0 IGO')
RUBIN = ('NSF–DOE Vera C. Rubin Observatory/NOIRLab/SLAC/AURA', 'CC BY 4.0')
JPL = ('NASA/JPL-Caltech', 'public domain')
PSP = ('NASA/Johns Hopkins APL/Naval Research Lab', 'public domain')
VGR = ('NASA/JPL', 'public domain')


def ew(i): return 'https://cdn.esawebb.org/archives/images/screen/%s.jpg' % i, 'https://esawebb.org/images/%s/' % i
def eh(i): return 'https://cdn.esahubble.org/archives/images/screen/%s.jpg' % i, 'https://esahubble.org/images/%s/' % i
def nl(i): return 'https://storage.noirlab.edu/media/archives/images/screen/%s.jpg' % i, 'https://noirlab.edu/public/images/%s/' % i
def pia(i, page=None): return ('pia', i), page or 'https://images.nasa.gov/details/%s' % i
def cxc(img, page): return 'https://chandra.harvard.edu' + img, 'https://chandra.harvard.edu/photo/' + page + '/'
def og(page): return 'og', page
def svs(sid, name): return ('svs', sid, name), 'https://svs.gsfc.nasa.gov/%s/' % sid


LIST = {
    'webb': [(ew('weic2205a'), 'COSMIC CLIFFS, CARINA NEBULA', 2022, WEBB),
             (ew('weic2216a'), 'PILLARS OF CREATION', 2022, WEBB),
             (ew('weic2209a'), 'WEBB’S FIRST DEEP FIELD', 2022, WEBB),
             (ew('weic2208a'), 'STEPHAN’S QUINTET', 2022, WEBB),
             (ew('weic2211a'), 'CARTWHEEL GALAXY', 2022, WEBB),
             (ew('weic2316a'), 'RHO OPHIUCHI', 2023, WEBB)],
    'hubble': [(eh('heic1501a'), 'PILLARS OF CREATION', 2014, HUBBLE),
               (eh('heic0406a'), 'HUBBLE ULTRA DEEP FIELD', 2004, HUBBLE),
               (eh('heic1007a'), 'MYSTIC MOUNTAIN, CARINA', 2010, HUBBLE),
               (eh('heic0515a'), 'CRAB NEBULA', 2005, HUBBLE),
               (eh('heic0506a'), 'WHIRLPOOL GALAXY', 2005, HUBBLE),
               (eh('opo0328a'), 'SOMBRERO GALAXY', 2003, HUBBLE)],
    'chandra': [(cxc('/photo/2006/casa/casa.jpg', '2006/casa'), 'CASSIOPEIA A', 2006, CXC),
                (cxc('/photo/2006/1e0657/1e0657.jpg', '2006/1e0657'), 'BULLET CLUSTER', 2006, CXC),
                (cxc('/photo/2018/crab/crab.jpg', '2018/crab'), 'CRAB NEBULA', 2018, CXC),
                (cxc('/photo/2019/gcenter/gcenter.jpg', '2019/gcenter'), 'GALACTIC CENTRE', 2019, CXC),
                (cxc('/photo/2011/tycho/tycho.jpg', '2011/tycho'), 'TYCHO’S SUPERNOVA', 2011, CXC),
                (cxc('/photo/2017/perseus/perseus.jpg', '2017/perseus'), 'PERSEUS CLUSTER', 2017, CXC)],
    'euclid': [(og('https://www.esa.int/ESA_Multimedia/Images/2023/11/Euclid_s_view_of_the_Horsehead_Nebula'), 'HORSEHEAD NEBULA', 2023, EUCLID),
               (og('https://www.esa.int/ESA_Multimedia/Images/2023/11/Euclid_s_view_of_the_Perseus_cluster_of_galaxies'), 'PERSEUS CLUSTER', 2023, EUCLID),
               (og('https://www.esa.int/ESA_Multimedia/Images/2023/11/Euclid_s_view_of_spiral_galaxy_IC_342'), 'SPIRAL GALAXY IC 342', 2023, EUCLID),
               (og('https://www.esa.int/ESA_Multimedia/Images/2024/05/Euclid_s_new_image_of_star-forming_region_Messier_78'), 'MESSIER 78', 2024, EUCLID),
               (og('https://www.esa.int/ESA_Multimedia/Images/2025/02/Euclid_image_of_a_bright_Einstein_ring_around_galaxy_NGC_6505'), 'EINSTEIN RING, NGC 6505', 2025, EUCLID),
               (og('https://www.esa.int/ESA_Multimedia/Images/2023/11/Euclid_s_view_of_irregular_galaxy_NGC_6822'), 'IRREGULAR GALAXY NGC 6822', 2023, EUCLID)],
    'rubin': [(nl('noirlab2521a'), 'THE COSMIC TREASURE CHEST', 2025, RUBIN),
              (nl('noirlab2521b'), 'TRIFID AND LAGOON NEBULAE', 2025, RUBIN),
              (nl('noirlab2616a'), 'OCEAN OF STARS', 2026, RUBIN),
              (nl('noirlab2618a'), 'DEEP INTO A FAMOUS COSMIC FIELD', 2026, RUBIN)],
    'spherex': [(pia('PIA26280', 'https://science.nasa.gov/photojournal/first-images-from-nasas-spherex/'), 'FIRST IMAGES', 2025, JPL),
                (pia('PIA26352', 'https://science.nasa.gov/photojournal/spherexs-dust-cloud-reveal/'), 'A DUST CLOUD REVEALED', 2025, JPL),
                (pia('PIA26354', 'https://science.nasa.gov/photojournal/spherex-vela-molecular-ridge/'), 'VELA MOLECULAR RIDGE', 2025, JPL),
                (og('https://science.nasa.gov/photojournal/nasas-spherex-mission-maps-water-ice-throughout-cygnus-x/'), 'WATER ICE IN CYGNUS X', 2026, JPL),
                (og('https://science.nasa.gov/photojournal/nasas-spherex-examines-comet-3i-atlass-coma/'), 'COMET 3I/ATLAS', 2025, JPL)],
    'parker': [(svs(14865, '14865_WISPR_12252025.00001_print.jpg'), 'CLOSEST IMAGES OF THE SUN’S ATMOSPHERE', 2025, PSP),
               (svs(14095, 'wispr_composite_topo_project_flat_vfb4.00017_print.jpg'), 'VENUS’ NIGHT SURFACE', 2022, PSP),
               (svs(13661, 'wisprinnerneowise20200705T020949E1_print.jpg'), 'COMET NEOWISE', 2020, PSP),
               (svs(13072, '01_WISPR-crop_print.jpg'), 'FIRST LIGHT', 2018, PSP)],
    'voyager': [(pia('PIA23645'), 'PALE BLUE DOT', 1990, VGR),
                (pia('PIA00014'), 'JUPITER’S GREAT RED SPOT', 1979, VGR),
                (pia('PIA00023'), 'IO', 1979, VGR),
                (pia('PIA00030'), 'SATURN WITH RHEA AND DIONE', 1981, VGR),
                (pia('PIA18182'), 'URANUS', 1986, VGR),
                (pia('PIA01492'), 'NEPTUNE', 1989, VGR)],
}


def get(url, tries=3):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(8 * (i + 1))


def resolve(src):
    if isinstance(src, tuple) and src[0] == 'svs':
        d = json.loads(get('https://svs.gsfc.nasa.gov/api/%s' % src[1]))
        hits = []
        def walk(o):
            if isinstance(o, dict):
                if str(o.get('url', '')).endswith('/' + src[2]): hits.append(o['url'])
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(d)
        if not hits: raise RuntimeError('svs %s has no %s' % src[1:])
        return hits[0]
    if isinstance(src, tuple) and src[0] == 'pia':
        # the asset list names the sizes that exist (~large is 403 on some Voyager ids)
        files = json.loads(get('https://images-assets.nasa.gov/image/%s/collection.json' % src[1]))
        for suf in ('~large.jpg', '~medium.jpg', '~orig.jpg', '~orig.png', '~orig.tif'):
            for f in files:
                if f.endswith(suf): return f.replace('http://', 'https://')
        raise RuntimeError('no usable size for %s' % src[1])
    return src


def main():
    OUT.mkdir(exist_ok=True)
    out = {}
    for key, items in LIST.items():
        rows = []
        for n, ((src, page), title, year, (credit, lic)) in enumerate(items, 1):
            try:
                if src == 'og':
                    x = get(page).decode('utf-8', 'replace')
                    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', x) or re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', x)
                    if not m: raise RuntimeError('no og:image')
                    src = m.group(1).replace('&amp;', '&')
                url = resolve(src)
                im = Image.open(io.BytesIO(get(url))).convert('RGB')
                im.thumbnail((640, 640), Image.LANCZOS)
                name = '%s-%d.webp' % (key, n)
                im.save(OUT / name, 'WEBP', quality=80, method=6)
                rows.append({'img': '/_solarlab/classics/' + name, 'title': title, 'year': year, 'link': page,
                             'credit': credit, 'lic': lic, 'w': im.width, 'h': im.height})
                print('ok  ', key, n, title, im.size, (OUT / name).stat().st_size // 1024, 'KB')
            except Exception as e:
                print('FAIL', key, n, title, e)
            time.sleep(1)
        out[key] = rows
    (ROOT / 'classics.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
