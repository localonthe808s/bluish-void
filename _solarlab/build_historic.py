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
    # (user 2026-10-23: "TIROS 9 first full world weather / LANDSAT / ERTS / SEASAT")
    'tiros9': [
        ("The World's Weather Spac0024-repair.jpg",
         'The first complete view of the world\u2019s weather, Feb 13, 1965 \u2014 450 pictures in one', '1965-02-13', 'TIROS-9 TV cameras', 'NOAA Photo Library'),
        ('Betsy from TIROS IX Spac0008-repair.jpg',
         'Hurricane Betsy, 1965', '1965', 'TIROS-9 TV camera', 'NOAA Photo Library'),
        ('TIROS IX Ross Sea Ice Shelf Spac0155-repair.jpg',
         'Antarctica\u2019s Ross Ice Shelf, orbit 22', '1965-01-23', 'TIROS-9 TV camera', 'NOAA Photo Library'),
        ('Cut-off North Pacific low as seen on pass 129 by TIROS-9 (2268-496).jpg',
         'A cut-off low spinning over the North Pacific, pass 129', '1965-02-01', 'TIROS-9 TV camera', 'NOAA'),
    ],
    'seasat': [
        ('url:https://images-assets.nasa.gov/image/PIA18137/PIA18137~medium.jpg|https://images.nasa.gov/details/PIA18137',
         'The Massachusetts coast: waves and currents on the open sea, Aug 27, 1978', '1978-08-27', 'Seasat synthetic aperture radar', 'NASA/JPL-Caltech'),
        ('Seasat picture of Los Angeles.jpg',
         'Los Angeles by radar, 1978', '1978', 'Seasat synthetic aperture radar', 'NASA/JPL'),
        ('Seasat - (Chesapeake Bay region) LOC 81694423.jpg',
         'The Chesapeake Bay region, Sep 25, 1978', '1978-09-25', 'Seasat synthetic aperture radar', 'NASA/JPL (Library of Congress)'),
    ],
}
HEROES = {'tiros1': 'TIROS-1 satellite.png', 'erts1': 'Landsat-1.jpg', 'tiros9': 'TIROS IX Spac0021-repair.jpg', 'seasat': 'Seasat in orbit.jpg'}


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
    names = [t for s in SETS.values() for t, *_ in s if not t.startswith('url:')] + list(HEROES.values())
    I = {}
    for k in range(0, len(names), 10): I.update(info(names[k:k + 10]))
    for key, rows in SETS.items():
        entries = []
        for n, (t, title, date, inst, credit) in enumerate(rows, 1):
            url, page = t[4:].split('|') if t.startswith('url:') else I[t]; f = '%s_%02d.webp' % (key, n)
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
