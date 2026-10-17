"""Finish a bake: write season.json, add each city's season shift to cities.json, and report which of the most
common species (by trees, all cities) neither CW_TREE_SEASON nor season.json covers.

  python3 -I _treesbake/season.py <outdir> index.html

season.json  {"_about": "...", "<common name, lowercase>": {"p":[..], "b":[from, to, what], "f":[from, to, color],
              "t": "one line", "ev": true}, ...}
  every month in New York's calendar, exactly like CW_TREE_SEASON; the city's time is month + its shift
  (cities.json "shift": [spring, fall]; p and b take the spring shift, f the fall shift; fall null = no fall).
"""
import glob, json, os, re, sys
from collections import Counter

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from shifts import SHIFT          # noqa: E402
from season_data import S         # noqa: E402

out, html = sys.argv[1], sys.argv[2]


def r1(v): return round(v, 2)


season = {'_about': 'Typical-year pollen (p), bloom (b) and fall color (f) months for street-tree species not in '
                    'the page\'s CW_TREE_SEASON, in New York\'s calendar like it; add the city\'s shift from '
                    'cities.json (spring to p and b, fall to f). t is the same in words, with regional timing. '
                    'ev = evergreen. Keys are lowercase common names as the tree tiles name them.'}
for name, home, p, b, f, t, ev in S:
    sp, fa = SHIFT[home] if home else (0, 0)
    fa = fa or 0
    e = {}
    if p: e['p'] = [r1(p[0] - sp), r1(p[1] - sp)]
    if b: e['b'] = [r1(b[0] - sp), r1(b[1] - sp), b[2]]
    if f: e['f'] = [r1(f[0] - fa), r1(f[1] - fa), f[2]]
    e['t'] = t
    if ev: e['ev'] = True
    k = name.lower()
    assert k not in season, k
    season[k] = e
with open(os.path.join(out, 'season.json'), 'w') as fh:
    json.dump(season, fh, separators=(',', ':'), ensure_ascii=False)

cities = json.load(open(os.path.join(out, 'cities.json')))
for c in cities:
    s_ = SHIFT.get(c['slug'])
    assert s_, 'no shift for ' + c['slug']
    c['shift'] = [s_[0], s_[1]]
with open(os.path.join(out, 'cities.json'), 'w') as fh:
    json.dump(cities, fh, separators=(',', ':'), ensure_ascii=False)

src = open(html).read()
blk = src[src.index('var CW_TREE_SEASON'):]
blk = blk[:blk.index('};')]
have = set(k.lower() for k in re.findall(r"'([^']+)':\s*\{", blk))
both = have & set(season)
cnt = Counter()
for c in cities:
    I = json.load(open(os.path.join(out, c['slug'], 'index.json')))
    for t in glob.glob(os.path.join(out, c['slug'], 't_*.json')):
        for q in json.load(open(t)):
            if q[4] >= 0: cnt[I['sp'][q[4]][0].lower()] += 1
tot = sum(cnt.values())
top = [k for k, _ in cnt.most_common(300) if k not in have]
cov = sum(v for k, v in cnt.items() if k in have or k in season)
print('season.json', len(season) - 1, 'species; overlap with CW_TREE_SEASON:', sorted(both))
print('identified trees covered by CW_TREE_SEASON or season.json: %.1f%%' % (100 * cov / tot))
print('top-150 non-CW species missing from season.json:', [(k, cnt[k]) for k in top[:150] if k not in season])
print('season.json names no tree carries:', [k for k in season if k != '_about' and k not in cnt])
