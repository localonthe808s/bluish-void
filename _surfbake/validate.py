#!/usr/bin/env python3
"""HOW RIGHT ARE THE CURRENTS? (user 2026-10-28: "are they accurate"). Scores a day's surface-current field against what the
Global Drifter Program's buoys actually did that day (OSMC real-time positions off the GTS): each buoy's 24-hour displacement
is a measured current, averaged over a day, which also averages out tides and inertial loops. The field is sampled along the
same path (start, middle, end). Reported against a placebo -- "no current at all" -- so a small error is not mistaken for skill.

Caveats kept in view: a drifter that lost its drogue (the sock that holds it at 15 m) is pushed by the wind as well, so the
measured speeds run a little high; the real-time stream carries no drogue flag.

    python3 validate.py DRIFT.csv DAY  name=field.npz ...      (each npz: U, V on 0.25 deg, rows south->north, cols -180->180)
"""
import csv, math, sys
import numpy as np
from datetime import datetime, timezone


def tsec(s): return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()


def drifters(path, day):
    t0 = tsec(day + 'T00:00:00Z'); t1 = t0 + 86400; P = {}
    with open(path) as f:
        r = csv.reader(f); next(r); next(r)
        for row in r:
            try: P.setdefault(row[0], []).append((tsec(row[1]), float(row[2]), float(row[3])))
            except Exception: pass
    out = []
    for k, L in P.items():
        L.sort()
        a = min(L, key=lambda q: abs(q[0] - t0)); b = min(L, key=lambda q: abs(q[0] - t1))
        if abs(a[0] - t0) > 3 * 3600 or abs(b[0] - t1) > 3 * 3600 or b[0] - a[0] < 20 * 3600: continue
        dt = b[0] - a[0]; la = (a[1] + b[1]) / 2
        dlo = (b[2] - a[2] + 540) % 360 - 180
        u = math.radians(dlo) * 6371000 * math.cos(math.radians(la)) / dt; v = math.radians(b[1] - a[1]) * 6371000 / dt
        if math.hypot(u, v) > 3: continue                     # a bad fix, not a current
        out.append((k, a[1], a[2], b[1], a[2] + dlo, u, v))
    return out


def sample(U, V, la, lo):
    H, W = U.shape; x = (lo + 180) / 360 * W - .5; y = (la + 90) / 180 * H - .5
    x0, y0 = int(math.floor(x)), int(math.floor(y)); fx, fy = x - x0, y - y0; su = sv = sw = 0
    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        xx, yy = (x0 + dx) % W, min(H - 1, max(0, y0 + dy)); u, v = U[yy, xx], V[yy, xx]
        if not (np.isfinite(u) and np.isfinite(v)): continue
        w = (fx if dx else 1 - fx) * (fy if dy else 1 - fy); su += u * w; sv += v * w; sw += w
    return (su / sw, sv / sw) if sw > .3 else None


def score(D, F):
    rows = []
    for k, la0, lo0, la1, lo1, u, v in D:
        s = [sample(F[0], F[1], la0 + (la1 - la0) * t, lo0 + (lo1 - lo0) * t) for t in (0, .5, 1)]
        s = [q for q in s if q]
        if len(s) < 2: continue
        rows.append((la0, u, v, sum(q[0] for q in s) / len(s), sum(q[1] for q in s) / len(s)))
    return np.array(rows)


def stats(A, label):
    if not len(A): return label + ': none'
    la, u, v, fu, fv = A.T
    e = np.hypot(fu - u, fv - v); z = np.hypot(u, v)
    # complex correlation: how well the field's vectors line up with the buoys', 1 = perfectly, 0 = no relation
    w = u + 1j * v; f = fu + 1j * fv
    cc = abs(np.sum(np.conj(w - w.mean()) * (f - f.mean()))) / math.sqrt(np.sum(abs(w - w.mean()) ** 2) * np.sum(abs(f - f.mean()) ** 2))
    ang = np.degrees(np.angle(f / np.where(w == 0, 1e-9, w)))
    good = z > 0.15
    return ('%s: n=%d  rms err %.3f m/s (placebo %.3f)  skill %.0f%%  vector corr %.2f  speed ratio %.2f  dir err median %.0f deg (buoys > 0.15 m/s)'
            % (label, len(A), np.sqrt(np.mean(e ** 2)), np.sqrt(np.mean(z ** 2)), 100 * (1 - np.mean(e ** 2) / np.mean(z ** 2)), cc,
               np.median(np.hypot(fu, fv)[good]) / np.median(z[good]), np.median(np.abs(ang[good]))))


if __name__ == '__main__':
    D = drifters(sys.argv[1], sys.argv[2])
    print(len(D), 'drifters with a clean 24 h track on', sys.argv[2])
    for spec in sys.argv[3:]:
        nm, path = spec.split('=', 1); d = np.load(path); A = score(D, (d['U'], d['V']))
        print(stats(A, nm))
        for lab, m in (('  |lat| < 5 (equator)', np.abs(A[:, 0]) < 5), ('  5-47', (np.abs(A[:, 0]) >= 5) & (np.abs(A[:, 0]) < 47)), ('  > 47 (tripolar rows)', np.abs(A[:, 0]) >= 47)):
            print(stats(A[m], lab))
