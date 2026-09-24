#!/usr/bin/env python3
"""The world's glaciers for EARTH SYSTEMS -> GLACIERS (user 2026-09-24: "lets continue with mapping glaciers on the globe").

One-off (re-run when GlaMBIE or RGI publish a new version):
  * RGI 7.0 outlines, region by region, from the GLIMS map server (whole world, plate carree, 4096 x 2048), each
    region's glaciers coloured by how fast that region is thinning (GlaMBIE mean m w.e./yr, 2000-2024), grown by a
    pixel or two so a small glacier still shows on a globe -> _maplab/rgi_world.png
  * GlaMBIE 2024 (WGMS, doi 10.5904/wgms-glambie-2024-07): per region and global, annual mass change (Gt) and
    thinning (m w.e.), 2000-2024, with a label point per region taken from its own glaciers -> _maplab/rgi_regions.json
ice_bake.py folds rgi_regions.json into ice.json.

Credits: RGI 7.0 Consortium (2023), via GLIMS / NSIDC; GlaMBIE Team (2025), Nature 639, 382-388; WGMS.
"""
import csv, io, json, math, time, urllib.request, zipfile
from pathlib import Path
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent
UA = {'User-Agent': 'bluishvoid-bake (+https://bluishvoid.com)'}
W, H = 4096, 2048
WMS = ('https://www.glims.org/geoserver/GLIMS/wms?service=WMS&version=1.1.1&request=GetMap&srs=EPSG:4326'
       '&bbox=-180,-90,180,90&width=%d&height=%d&format=image/png&transparent=true&styles=&layers=' % (W, H))
GLAMBIE = 'https://wgms.ch/downloads/GlaMBIE_Data_DOI_10.5904_wgms-glambie-2024-07.zip'
# RGI region -> GLIMS layer, the name a reader knows, a label point override where the centroid would mislead
REG = [
    (1, 'alaska', 'ALASKA', None), (2, 'western_canada_usa', 'WESTERN CANADA & US', None),
    (3, 'arctic_canada_north', 'ARCTIC CANADA NORTH', None), (4, 'arctic_canada_south', 'ARCTIC CANADA SOUTH', None),
    (5, 'greenland_periphery', 'GREENLAND’S OUTER GLACIERS', (66.5, -38)), (6, 'iceland', 'ICELAND', None),
    (7, 'svalbard_jan_mayen', 'SVALBARD', None), (8, 'scandinavia', 'SCANDINAVIA', None),
    (9, 'russian_arctic', 'RUSSIAN ARCTIC', None), (10, 'north_asia', 'NORTH ASIA', None),
    (11, 'central_europe', 'THE ALPS', None), (12, 'caucasus_middle_east', 'CAUCASUS', None),
    (13, 'central_asia', 'CENTRAL ASIA', None), (14, 'south_asia_west', 'KARAKORAM & W HIMALAYA', None),
    (15, 'south_asia_east', 'EASTERN HIMALAYA', None), (16, 'low_latitudes', 'TROPICAL ANDES', (-9, -77)),
    (17, 'southern_andes', 'PATAGONIA & S ANDES', None), (18, 'new_zealand', 'NEW ZEALAND', None),
    (19, 'subantarctic_antarctic_islands', 'ANTARCTIC ISLANDS', (-66, -64)),
]
GFILE = {1: 'alaska', 2: 'western_canada_us', 3: 'arctic_canada_north', 4: 'arctic_canada_south', 5: 'greenland_periphery',
         6: 'iceland', 7: 'svalbard', 8: 'scandinavia', 9: 'russian_arctic', 10: 'north_asia', 11: 'central_europe',
         12: 'caucasus_middle_east', 13: 'central_asia', 14: 'south_asia_west', 15: 'south_asia_east', 16: 'low_latitudes',
         17: 'southern_andes', 18: 'new_zealand', 19: 'antarctic_and_subantarctic'}


def get(url, timeout=240, tries=3):
    for i in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception:
            if i == tries - 1: raise
            time.sleep(10 * (i + 1))


def ramp(r):
    """thinning, m w.e. per year (negative) -> colour: ice-pale when slow, amber, then deep red past a metre a year"""
    t = max(0.0, min(1.0, -r / 1.1))
    S = [(0.0, (224, 242, 254)), (0.3, (253, 224, 150)), (0.6, (249, 115, 22)), (1.0, (185, 28, 28))]
    for (a, ca), (b, cb) in zip(S, S[1:]):
        if t <= b:
            k = (t - a) / (b - a); return tuple(round(ca[j] + (cb[j] - ca[j]) * k) for j in range(3))
    return S[-1][1]


def main():
    z = zipfile.ZipFile(io.BytesIO(get(GLAMBIE)))
    def series(name):
        f = next(n for n in z.namelist() if n.endswith('calendar_years/%s.csv' % name))
        return [r for r in csv.DictReader(io.TextIOWrapper(z.open(f), 'utf-8'))]
    glob_ = series('0_global')
    out = {'src': 'GlaMBIE Team (2025), Nature; WGMS doi 10.5904/wgms-glambie-2024-07', 'rgi': 'RGI 7.0 via GLIMS',
           'global': {'years': [[int(float(r['end_dates'])) - 1, round(float(r['combined_gt']), 1)] for r in glob_],
                      'area0': round(float(glob_[0]['glacier_area']))}, 'regions': []}
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    for num, layer, name, over in REG:
        rows = series('%d_%s' % (num, GFILE[num]))
        gt = sum(float(r['combined_gt']) for r in rows); mwe = sum(float(r['combined_mwe']) for r in rows)
        yrs = float(rows[-1]['end_dates']) - float(rows[0]['start_dates'])
        rate = mwe / yrs
        m = Image.open(io.BytesIO(get(WMS + 'RGI2000-v7.0-G-%02d_%s_epsg3857' % (num, layer)))).convert('RGBA').getchannel('A')
        m = m.point(lambda v: 255 if v > 20 else 0).filter(ImageFilter.MaxFilter(5))      # grown ~2 px: a small glacier still shows on a globe
        # label point: the region's own glaciers (circular mean of longitude, so Alaska's Aleutians do not drag it)
        px = m.load(); sx = sy = sc = 0.0; n = 0
        for y in range(0, H, 4):
            for x in range(0, W, 4):
                if px[x, y]:
                    lo = x / W * 360 - 180; sx += math.cos(math.radians(lo)); sy += math.sin(math.radians(lo)); sc += 90 - y / H * 180; n += 1
        lat, lon = (over if over else (sc / max(n, 1), math.degrees(math.atan2(sy, sx))))
        col = ramp(rate)
        img.paste(Image.new('RGBA', (W, H), col + (235,)), (0, 0), m)
        out['regions'].append({'n': num, 'name': name, 'lat': round(lat, 2), 'lon': round(lon, 2), 'gt': round(gt), 'gtyr': round(gt / yrs, 1),
                               'mwe': round(mwe, 2), 'mweyr': round(rate, 3), 'area0': round(float(rows[0]['glacier_area'])), 'col': '#%02x%02x%02x' % col})
        print('%2d %-28s %7.0f Gt  %6.1f Gt/yr  %6.2f m/yr  label %.1f,%.1f' % (num, name, gt, gt / yrs, rate, lat, lon))
    img.save(ROOT / 'rgi_world.png', optimize=True)
    (ROOT / 'rgi_regions.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print('wrote rgi_world.png', (ROOT / 'rgi_world.png').stat().st_size // 1024, 'KB')


if __name__ == '__main__':
    main()
