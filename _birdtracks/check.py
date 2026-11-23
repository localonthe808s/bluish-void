#!/usr/bin/env python3
"""Decode out/*.bin via the index JSONs (round-trip check), print sanity lines, draw out/check.png."""
import json, os, struct, datetime as dt, math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
EPOCH = dt.datetime(1990, 1, 1)


def load(key):
    idx = json.load(open(os.path.join(OUT, key + '_v1.json')))
    raw = open(os.path.join(OUT, key + '_v1.bin'), 'rb').read()
    birds = []
    for b in idx['birds']:
        i, n = struct.unpack_from('<II', raw, b['offset'])
        assert i == b['id'] and n == b['n_fixes'], (key, b['id'])
        a = np.frombuffer(raw, dtype='<i4', count=n * 3, offset=b['offset'] + 8).reshape(n, 3)
        birds.append((b, a[:, 0].astype(float), a[:, 1] / 1e4, a[:, 2] / 1e4))
    end = idx['birds'][-1]['offset'] + 8 + 12 * idx['birds'][-1]['n_fixes']
    assert end == len(raw), (key, end, len(raw))
    return idx, birds


def d(t):
    return (EPOCH + dt.timedelta(seconds=float(t))).strftime('%Y-%m-%d')


def hav(a, b, c, e):
    r = math.radians
    x = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(e - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


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


tj = json.load(open(os.path.join(OUT, 'tracks_v1.json')))
fig, ax = plt.subplots(figsize=(11, 13), dpi=110)
PAL = ['#1f77b4', '#9ecae1', '#ff7f0e', '#8c564b', '#2ca02c', '#98df8a', '#d62728', '#e377c2', '#7f7f7f', '#17becf', '#bcbd22', '#ffbb78', '#9467bd', '#000000']
tot = 0
for si, sp in enumerate(tj['species']):
    idx, birds = load(sp['key'])
    tot += sum(b[0]['n_fixes'] for b in birds)
    col = PAL[si % len(PAL)]
    for bi, (b, t, la, lo) in enumerate(birds):
        # break lines across big time gaps so missing data isn't drawn as flight
        br = np.where(np.diff(t) > 10 * 86400)[0] + 1
        for seg in np.split(np.arange(len(t)), br):
            ax.plot(lo[seg], la[seg], '-', color=col, lw=0.6, alpha=0.75, label=sp['common'] if (bi == 0 and seg[0] == 0) else None)
    print('%-22s birds=%2d fixes=%5d south=%.1f' % (sp['key'], len(birds), sum(b[0]['n_fixes'] for b in birds),
                                                    min(b[2].min() for b in birds)))
ax.set_xlim(-25, 50); ax.set_ylim(-35, 70); ax.set_aspect(1.0)
ax.grid(alpha=0.3); ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
ax.set_title('Bird tracks v1: %d species, %d fixes (plain lon/lat)' % (len(tj['species']), tot))
ax.legend(loc='lower left', fontsize=8, ncol=2)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'check.png'))

# sanity lines
for key, lat_cut in (('white_stork', 15.0), ('caspian_tern', 20.0), ('montagus_harrier', 18.0)):
    idx, birds = load(key)
    best = None
    for b, t, la, lo in birds:
        r = first_autumn(b, t, la, lo, lat_cut)
        if r and (best is None or b['km'] > best[0]['km']):
            best = (b, t, la, lo, r)
    b, t, la, lo, (j, k) = best
    print('%s #%d (%s): start %.2fN %.2fE on %s, left %s, first fix south of %gN on %s at %.2fN %.2fE, '
          'southmost %s, %d fixes %s..%s, total %d km' % (
              key, b['id'], b['label'], la[0], lo[0], d(t[0]), d(t[j]), lat_cut, d(t[k]), la[k], lo[k],
              b['southmost'], b['n_fixes'], b['first'][:10], b['last'][:10], b['km']))
