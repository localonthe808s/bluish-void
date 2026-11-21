#!/usr/bin/env python3
"""RADIO's night globe texture (user 2026-11-21: "lets make the map a globe/ball view ... small orange glowing dots"): an
equirectangular image of the world, dark, so the stations' glow carries the picture. Natural Earth 1:50m land, lakes and
land borders (public domain). Out: OUT/globe_{8k,4k}.webp (8192x4096 desktop, 4096x2048 phones).
Run: python3 _radiobake/globe_tex.py NE_DIR OUT
"""
import sys, os, json
from PIL import Image, ImageDraw, ImageFilter

OCEAN, LAND, COAST, BORDER, LAKE = (6, 10, 20), (22, 30, 46), (92, 122, 170), (70, 92, 130), (8, 13, 25)


def rings(g):
    t, c = g['type'], g['coordinates']
    if t == 'Polygon':
        return [c]
    if t == 'MultiPolygon':
        return c
    return []


def lines(g):
    t, c = g['type'], g['coordinates']
    return [c] if t == 'LineString' else c if t == 'MultiLineString' else []


def main():
    ne, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    W, H = 8192, 4096
    P = lambda lo, la: ((lo + 180) / 360 * W, (90 - la) / 180 * H)
    im = Image.new('RGB', (W, H), OCEAN)
    d = ImageDraw.Draw(im)
    land = json.load(open(os.path.join(ne, 'ne_50m_land.geojson')))['features']
    for f in land:
        for poly in rings(f['geometry']):
            d.polygon([P(*q[:2]) for q in poly[0]], fill=LAND)
            for hole in poly[1:]:
                d.polygon([P(*q[:2]) for q in hole], fill=OCEAN)
    for f in json.load(open(os.path.join(ne, 'ne_50m_lakes.geojson')))['features']:
        for poly in rings(f['geometry']):
            d.polygon([P(*q[:2]) for q in poly[0]], fill=LAKE)
    im = im.filter(ImageFilter.GaussianBlur(0.8))                    # soften the stair-stepped polygon edges
    d = ImageDraw.Draw(im)
    for f in land:                                                   # a faint coastline
        for poly in rings(f['geometry']):
            pts = [P(*q[:2]) for q in poly[0]]
            d.line(pts + [pts[0]], fill=COAST, width=2)
    for f in json.load(open(os.path.join(ne, 'ne_50m_admin_0_boundary_lines_land.geojson')))['features']:
        for ln in lines(f['geometry']):
            d.line([P(*q[:2]) for q in ln], fill=BORDER, width=1)
    im.save(os.path.join(out, 'globe_8k.webp'), quality=82, method=6)
    im.resize((4096, 2048), Image.LANCZOS).save(os.path.join(out, 'globe_4k.webp'), quality=84, method=6)
    for k in ('8k', '4k'):
        print(k, os.path.getsize(os.path.join(out, 'globe_%s.webp' % k)) // 1024, 'KB')


if __name__ == '__main__':
    main()
