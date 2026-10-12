"""HUDSON CUT (2026-10-11, user: "dont outline the hudson river in green on these maps"): drops the trim points that run up the Hudson, Battery to Troy, from the NYC coast-trim files; splits lines where it cuts.
python3 hudson_cut.py write <city_coast_*.json ...>  (or plot, for a before/after check)"""
import json, sys
from PIL import Image, ImageDraw
def in_hudson(lon, lat):
    if lat < 40.705 or lat > 42.80: return False
    if lat < 40.86:
        return -74.05 < lon < (-74.017 + (lat - 40.70) * 0.6)
    if lat < 41.1: return -73.99 < lon < -73.84
    if lat < 41.6: return -74.04 < lon < -73.84
    return -74.08 < lon < -73.60
def cut(path, write):
    d = json.load(open(path)); out = []; dropped = 0
    for r in d['r']:
        run = []
        for i in range(0, len(r), 2):
            lon, lat = r[i], r[i+1]
            if in_hudson(lon, lat):
                dropped += 1
                if len(run) >= 4: out.append(run)
                run = []
            else: run += [lon, lat]
        if len(run) >= 4: out.append(run)
    print(path.split('/')[-1], 'lines', len(d['r']), '->', len(out), 'points dropped', dropped)
    if write:
        d['r'] = out; d['src'] += '; the Hudson cut out (user 2026-10-11: no green up the river)'
        json.dump(d, open(path, 'w'), separators=(',', ':'))
    return d['r'] if not write else out, out
# debug plot: before (grey) vs after (green) over lon -74.4..-73.4, lat 40.5..42.9
def plot(path, name):
    d = json.load(open(path)); before = d['r']
    _, after = cut(path, False)
    L0, L1, A0, A1 = -74.4, -73.5, 40.5, 42.9; Wp, Hp = 700, 1800
    im = Image.new('RGB', (Wp, Hp), (20, 24, 50)); g = ImageDraw.Draw(im)
    P = lambda lon, lat: ((lon - L0) / (L1 - L0) * Wp, (A1 - lat) / (A1 - A0) * Hp)
    for col, rs, w in (((230, 60, 60), before, 1), ((5, 219, 50), after, 2)):
        for r in rs:
            pts = [P(r[i], r[i+1]) for i in range(0, len(r), 2)]
            if len(pts) > 1: g.line(pts, fill=col, width=w)
    im.save(name)
    # zoom on the city
    L0, L1, A0, A1 = -74.15, -73.75, 40.62, 40.95; Wp, Hp = 900, 900
    im = Image.new('RGB', (Wp, Hp), (20, 24, 50)); g = ImageDraw.Draw(im)
    for col, rs, w in (((230, 60, 60), before, 1), ((5, 219, 50), after, 2)):
        for r in rs:
            pts = [P(r[i], r[i+1]) for i in range(0, len(r), 2)]
            if len(pts) > 1: g.line(pts, fill=col, width=w)
    im.save(name.replace('.png', '_city.png'))
if __name__ == '__main__':
    mode = sys.argv[1]
    for f in sys.argv[2:]:
        if mode == 'plot': plot(f, f.split('/')[-1].replace('.json', '.png'))
        else: cut(f, True)
