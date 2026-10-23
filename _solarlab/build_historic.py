#!/usr/bin/env python3
"""THE HISTORIC SATELLITES' FIRST PICTURES (2026-10-23, user: "there should be a group for historic / past satellites, these
wont need latest photos, can we show ERTS and TIROS - first satellites, i would love to show their first or most important
photos"). Curated, public-domain frames from Wikimedia Commons (NASA, NOAA, USGS originals), each vetted on a contact sheet:
duplicates of one frame (TIROS-1's first picture exists as three prints) keep the most original copy.

  tiros1  TIROS-1, the first weather satellite (1960): the raw first recorded frame, the famous print, the four-frame sheet
  erts1   ERTS-1 / Landsat 1 (1972): first light over Dallas-Fort Worth, the first cloud-free scene, Alaska's glaciers, the
          Bay Area, the 1973 Mississippi flood, Los Angeles

Writes _solarlab/probes/<set>_NN.webp (long side 900 px) and merges the sets into _solarlab/probes/probes.json (the probe
archive's manifest; build_probe_archive.py keeps sets it does not own), plus the heroes _solarlab/sprites/{tiros1,erts1}.webp.

    python3 _solarlab/build_historic.py
"""
import io, json, time, urllib.parse, urllib.request
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / 'probes'
UA = {'User-Agent': 'bluishvoid.com historic satellites (nicolas7iana@outlook.com)'}

SETS = {
    'tiros1': [
        ('Celebrating 61 Years of Watching Weather from Space (NESDIS 2021-04-01 the real first TIROS-1 image).png',
         'The first recorded frame, 13:31 UTC, April 1, 1960', '1960-04-01', 'TIROS-1 TV camera 2', 'NOAA / CIMSS'),
        ('1960- First “television” picture of Earth from space (TIROS-1).jpg',
         'First television picture from space, April 1, 1960', '1960-04-01', 'TIROS-1 TV camera', 'NASA'),
        ('First television images of Earth from space; northeastern North America.jpg',
         'Northeastern North America, the first day’s pictures', '1960-04-01', 'TIROS-1 TV camera', 'NASA'),
    ],
    'erts1': [
        ('Landsat 1 First Light Image (1972-07-25).jpg',
         'First light: Dallas–Fort Worth, July 25, 1972', '1972-07-25', 'ERTS-1 multispectral scanner', 'USGS'),
        ('Landsat 1 image of Ouachita Mountains (1972-07-25).jpg',
         'The first cloud-free scene: the Ouachita Mountains', '1972-07-25', 'ERTS-1 multispectral scanner', 'USGS EROS'),
        ('First Glimpse of Alaska’s Glaciers from Landsat (Landsat 1, 1972-07-31).jpg',
         'Alaska’s glaciers, six days in', '1972-07-31', 'ERTS-1 multispectral scanner', 'USGS'),
        ('ERTS-1 San Francisco (ARC-1972-AC78-1116).jpg',
         'The San Francisco Bay Area', '1972', 'ERTS-1 multispectral scanner', 'NASA Ames'),
        ('Morganza Spillway, Louisiana 5 May 1973.jpg',
         'The 1973 Mississippi flood at the Morganza Spillway', '1973-05-05', 'ERTS-1 multispectral scanner', 'NASA / USGS'),
        ('Landsat 1 image of Los Angeles (PIA02988).jpg',
         'Los Angeles and its basin', '1972', 'ERTS-1 multispectral scanner', 'NASA/JPL'),
    ],
}
HEROES = {'tiros1': 'TIROS-1 satellite.png', 'erts1': 'Landsat-1.jpg'}


def info(titles):
    u = ('https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=url&iiurlwidth=1280&format=json&titles='
         + urllib.parse.quote('|'.join('File:' + t for t in titles)))
    j = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
    out = {}
    for p in j['query']['pages'].values():
        ii = (p.get('imageinfo') or [{}])[0]
        out[p['title'][5:]] = (ii.get('thumburl') or ii.get('url'), ii.get('descriptionurl'))
    return out


def fetch(url):
    for i in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
        except Exception:
            time.sleep(15 * (i + 1))                                  # Commons answers 429 to a quick burst
    raise RuntimeError('could not fetch ' + url)


def save(raw, path, side):
    im = Image.open(io.BytesIO(raw)).convert('RGB'); im.thumbnail((side, side), Image.LANCZOS)
    im.save(path, 'WEBP', quality=82, method=6)


def main():
    man = json.loads((OUT / 'probes.json').read_text())
    names = [t for s in SETS.values() for t, *_ in s] + list(HEROES.values())
    I = {}
    for k in range(0, len(names), 10): I.update(info(names[k:k + 10]))
    for key, rows in SETS.items():
        entries = []
        for n, (t, title, date, inst, credit) in enumerate(rows, 1):
            url, page = I[t]; f = '%s_%02d.webp' % (key, n)
            save(fetch(url), OUT / f, 900); time.sleep(3)
            entries.append({'file': f, 'title': title, 'date': date, 'target': 'Earth', 'instrument': inst,
                            'credit': credit + ' · public domain', 'source_url': page})
            print(key, f, title)
        man['sets'][key] = entries
    for key, t in HEROES.items():
        url, _ = I[t]; save(fetch(url), HERE / 'sprites' / (key + '.webp'), 700); time.sleep(3)
        print('hero', key)
    (OUT / 'probes.json').write_text(json.dumps(man, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
