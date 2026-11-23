#!/usr/bin/env python3
"""Decode out/*_v2.bin via the index JSONs (round-trip check), print sanity lines, draw out/check_v2.png.

Checks per bird: header matches the index, offsets tile the file exactly, no fix-to-fix jump faster than
MAX_KMH (teleport), time strictly increasing; flags manipulated (displaced / released) birds.
Usage: python3 -I check.py [v2]
"""
import json, os, struct, sys, datetime as dt, math, site
sys.path.append(site.getusersitepackages())  # numpy / matplotlib live in the user site, which -I hides
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
VER = sys.argv[1] if len(sys.argv) > 1 else 'v2'
EPOCH = dt.datetime(1990, 1, 1)
MAX_KMH = 150.0


def load(key):
    idx = json.load(open(os.path.join(OUT, '%s_%s.json' % (key, VER))))
    raw = open(os.path.join(OUT, '%s_%s.bin' % (key, VER)), 'rb').read()
    birds = []
    for b in idx['birds']:
        i, n = struct.unpack_from('<II', raw, b['offset'])
        assert i == b['id'] and n == b['n_fixes'], (key, b['id'])
        a = np.frombuffer(raw, dtype='<i4', count=n * 3, offset=b['offset'] + 8).reshape(n, 3)
        birds.append((b, a[:, 0].astype(float), a[:, 1] / 1e4, a[:, 2] / 1e4))
    end = idx['birds'][-1]['offset'] + 8 + 12 * idx['birds'][-1]['n_fixes'] if idx['birds'] else 0
    assert end == len(raw), (key, end, len(raw))
    return idx, birds


def d(t):
    return (EPOCH + dt.timedelta(seconds=float(t))).strftime('%Y-%m-%d')


def hav(a, b, c, e):
    r = math.radians
    x = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(e - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1.0, x)))


def first_autumn(b, t, la, lo, south_of):
    """first fix south of `south_of` deg N, and the departure = last fix within 50 km of the start area before it."""
    k = np.where(la < south_of)[0]
    if not len(k):
        return None
    k = k[0]
    j = 0
    for i in range(k):
        if hav(la[0], lo[0], la[i], lo[i]) < 50:
            j = i
    return j, k


tj = json.load(open(os.path.join(OUT, 'tracks_%s.json' % VER)))
fig, ax = plt.subplots(figsize=(13, 14), dpi=110)
cmap = plt.get_cmap('tab20')
tot = 0; nb = 0; nbytes = os.path.getsize(os.path.join(OUT, 'tracks_%s.json' % VER)); problems = []
for si, sp in enumerate(tj['species']):
    idx, birds = load(sp['key'])
    nbytes += os.path.getsize(os.path.join(OUT, sp['file'])) + os.path.getsize(os.path.join(OUT, sp['index']))
    assert sp['n_birds'] == len(birds), sp['key']
    assert sum(s['n_birds'] for s in sp['sources']) == len(birds), sp['key']
    assert all(s['license'].split(' (')[0] in ('CC0 1.0 Universal', 'Attribution 4.0 International',
               'Creative Commons Zero v1.0 Universal', 'Creative Commons Attribution 4.0 International') for s in sp['sources']), sp['key']
    tot += sum(b[0]['n_fixes'] for b in birds); nb += len(birds)
    col = cmap(si % 20)
    fastest = 0; manip = 0
    for bi, (b, t, la, lo) in enumerate(birds):
        assert 0 <= b['source'] < len(sp['sources'])
        assert np.all(np.diff(t) > 0), (sp['key'], b['id'], 'time not increasing')
        for i in range(len(t) - 1):
            v = hav(la[i], lo[i], la[i + 1], lo[i + 1]) / max((t[i + 1] - t[i]) / 3600, 1 / 60)
            fastest = max(fastest, v)
            if v > MAX_KMH:
                problems.append('%s #%d teleport %.0f km/h on %s' % (sp['key'], b['id'], v, d(t[i])))
        manip += 'manipulation' in b
        # break lines across big time gaps so missing data isn't drawn as flight
        br = np.where(np.diff(t) > 10 * 86400)[0] + 1
        for seg in np.split(np.arange(len(t)), br):
            ax.plot(lo[seg], la[seg], '-', color=col, lw=0.5, alpha=0.7, label=sp['common'] if (bi == 0 and seg[0] == 0) else None)
    print('%-24s birds=%2d migr=%2d manip=%d fixes=%6d south=%6.1f north=%5.1f fastest=%3.0f km/h src=%s' % (
        sp['key'], len(birds), sum(b[0]['migrated'] for b in birds), manip, sum(b[0]['n_fixes'] for b in birds),
        min(b[2].min() for b in birds), max(b[2].max() for b in birds), fastest, [s['n_birds'] for s in sp['sources']]))
ax.set_xlim(-30, 70); ax.set_ylim(-35, 80); ax.set_aspect(1.0)
ax.grid(alpha=0.3); ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
ax.set_title('Bird tracks %s: %d species, %d birds, %d fixes (plain lon/lat)' % (VER, len(tj['species']), nb, tot))
ax.legend(loc='lower left', fontsize=7, ncol=3)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'check_%s.png' % VER))
print('TOTAL species=%d birds=%d fixes=%d bytes=%d' % (len(tj['species']), nb, tot, nbytes))
print('problems:', len(problems)); print('\n'.join(problems[:30]))

# sanity lines
for key, lat_cut in (('white_stork', 15.0), ('caspian_tern', 20.0), ('montagus_harrier', 18.0), ('steppe_eagle', 25.0)):
    if not any(s['key'] == key for s in tj['species']):
        continue
    idx, birds = load(key)
    best = None
    for b, t, la, lo in birds:
        r = first_autumn(b, t, la, lo, lat_cut)
        if r and (best is None or b['km'] > best[0]['km']):
            best = (b, t, la, lo, r)
    if not best:
        continue
    b, t, la, lo, (j, k) = best
    print('%s #%d (%s): start %.2fN %.2fE on %s, left %s, first fix south of %gN on %s at %.2fN %.2fE, '
          'southmost %s, %d fixes %s..%s, total %d km' % (
              key, b['id'], b['label'], la[0], lo[0], d(t[0]), d(t[j]), lat_cut, d(t[k]), la[k], lo[k],
              b['southmost'], b['n_fixes'], b['first'][:10], b['last'][:10], b['km']))
