#!/usr/bin/env python3
"""ARGO FLOATS (2026-10-25, user: "can we add ARGO OCEAN DATA to water?" -> "do 1 2 3 4 5 6 7"). Argo's ~4,000 robot floats drift
about 3,300 ft down and every ten days rise to the surface, measuring temperature and salinity on the way up from as deep as 6,500 ft;
a few hundred (BGC-Argo) also carry oxygen, chlorophyll, nitrate and pH sensors. This bakes the floats round North America
(5-62 N, 140-40 W) from Ifremer's ERDDAP mirror of the Argo GDAC (keyless; no CORS, so baked):

    argo/latest.json  {"at": unix, "n": floats,
      "f": [[id, lat, lon, t (unix), cycle, track [lon, lat, ... newest last, 60 days], profile [[dbar, degC|null, psu|null], ...]|null,
             metrics {d26, tchp, mld, sss, s1000, t1000} (any may be missing), bgc {...}|null], ...],
      "v": [[lon, lat, u, v, id], ...]            deep drift between surfacings, cm/s (the current at the float's parking depth)
      "sec": {...}}                               THE GULF STREAM SLICE, New Jersey to Bermuda, from the last 45 days' profiles

Metrics, from the newest profile (top 400 dbar every 10, below every 50 -- ERDDAP orderByClosest):
  d26   depth (m) of the 26 C (79 F) water -- how deep the hurricane fuel goes; 0 when the surface is cooler
  tchp  tropical cyclone heat potential, kJ/cm2: the heat in the water above 26 C (Leipper & Volgenau 1972; rho 1025, cp 3993)
  mld   mixed-layer depth (m): where the water is 0.2 C cooler than at 10 m (de Boyer Montegut et al. 2004)
  sss   salinity near the surface (shallowest reading, <= 10 dbar); s1000 / t1000 at 1000 dbar (+-100)
BGC (ArgoFloats-synthetic-BGC, last 30 days, adjusted values with QC 1/2/5/8 and in physical range only):
  {o2s surface oxygen umol/kg, o2min, o2minz, chlmax mg/m3, chlz, no3z nitracline (first nitrate > 1 umol/kg), phs, p: [[dbar, o2, chl, no3, ph], ...]}

    python3 _argobake/bake.py [--dry]
Argo data: "These data were collected and made freely available by the International Argo Program and the national programs that
contribute to it (https://argo.ucsd.edu, https://www.ocean-ops.org)."
"""
import csv, io, json, math, os, subprocess, sys, tempfile, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

E = 'https://erddap.ifremer.fr/erddap/tabledap/'
BOX = '&latitude>=5&latitude<=62&longitude>=-140&longitude<=-40'
BUCKET = 'bluishvoid-bg'; KEY = 'argo/latest.json'
OKQ = ('1', '2', '5', '8')
RANGE = {'o2': (0, 450), 'chl': (-0.2, 60), 'no3': (-1, 55), 'ph': (7.2, 8.6)}


def get(ds, q, tries=4):
    url = E + ds + '.csv?' + urllib.parse.quote(q, safe='&=,')
    for k in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluishvoid.com argo bake'}), timeout=300).read().decode()
            return list(csv.reader(io.StringIO(b)))[2:]
        except urllib.error.HTTPError as e:
            if e.code == 404: return []          # ERDDAP answers 404 for "no matching rows"
            print('retry', k, e); time.sleep(30 * (k + 1))
        except Exception as e:
            print('retry', k, e); time.sleep(30 * (k + 1))
    raise SystemExit('ERDDAP did not answer')


def ts(s): return int(datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp())
def fnum(x):
    try:
        v = float(x); return None if math.isnan(v) or abs(v) > 9e4 else v
    except (TypeError, ValueError): return None


def profiles(t0, box, thin_top=10, thin_deep=50):
    """{(id, cycle): (t, lat, lon, [[dbar, T, S], ...])} -- top 400 dbar every thin_top, deeper every thin_deep"""
    cols = 'platform_number,cycle_number,time,latitude,longitude,pres,temp,psal,temp_qc,psal_qc'
    rows = get('ArgoFloats', cols + '&time>=' + t0 + box + '&pres_qc="1"&pres<=400&orderByClosest("platform_number,cycle_number,pres/%d")' % thin_top)
    rows += get('ArgoFloats', cols + '&time>=' + t0 + box + '&pres_qc="1"&pres>400&orderByClosest("platform_number,cycle_number,pres/%d")' % thin_deep)
    out = {}
    for r in rows:
        try: k = (r[0].strip(), int(r[1])); p = float(r[5])
        except ValueError: continue
        T = fnum(r[6]) if r[8].strip() in ('1', '2') else None
        S = fnum(r[7]) if r[9].strip() in ('1', '2') else None
        if T is not None and not -2.5 <= T <= 36: T = None          # a flag of 1 is not a guarantee: 10-25 had a 3.8 PSU "good" reading
        if S is not None and not 20 <= S <= 41.5: S = None
        if T is None and S is None: continue
        if k not in out: out[k] = (ts(r[2]), float(r[3]), float(r[4]), [])
        out[k][3].append([round(p, 1), None if T is None else round(T, 3), None if S is None else round(S, 3)])
    for k in out: out[k][3].sort()
    return out


def at(P, z, i):
    """value i (1 = T, 2 = S) at depth z, linear between readings; None outside them"""
    pts = [(q[0], q[i]) for q in P if q[i] is not None]
    for a, b in zip(pts, pts[1:]):
        if a[0] <= z <= b[0]: return a[1] + (b[1] - a[1]) * (z - a[0]) / ((b[0] - a[0]) or 1)
    return None


def metrics(P):
    m = {}
    T = [(q[0], q[1]) for q in P if q[1] is not None]
    if len(T) >= 4 and T[0][0] <= 15:
        if T[0][1] < 26: m['d26'] = 0; m['tchp'] = 0
        else:
            z26 = None
            for a, b in zip(T, T[1:]):
                if a[1] >= 26 > b[1]: z26 = a[0] + (a[1] - 26) / ((a[1] - b[1]) or 1) * (b[0] - a[0]); break
            if z26 is not None:
                h = 0.0; prev = (0.0, T[0][1])
                for z, t in T:
                    if z > z26: z, t = z26, 26.0
                    h += 0.5 * (max(prev[1] - 26, 0) + max(t - 26, 0)) * (z - prev[0]); prev = (z, t)
                    if z >= z26: break
                m['d26'] = round(z26); m['tchp'] = round(1025 * 3993 * h / 1e7, 1)
        t10 = at(P, 10, 1)
        if t10 is not None:
            for a, b in zip(T, T[1:]):
                if a[0] >= 10 and b[1] < t10 - 0.2 <= a[1]:
                    m['mld'] = round(a[0] + (a[1] - (t10 - 0.2)) / ((a[1] - b[1]) or 1) * (b[0] - a[0])); break
    S = [(q[0], q[2]) for q in P if q[2] is not None]
    if S and S[0][0] <= 10: m['sss'] = round(S[0][1], 2)
    s1k = at(P, 1000, 2); t1k = at(P, 1000, 1)
    if s1k is not None: m['s1000'] = round(s1k, 3)
    if t1k is not None: m['t1000'] = round(t1k, 2)
    return m


def bgc(t0):
    cols = ['doxy', 'chla', 'nitrate', 'ph_in_situ_total']; keys = ['o2', 'chl', 'no3', 'ph']
    q = ('platform_number,cycle_number,time,pres,' + ','.join(c + '_adjusted,' + c + '_adjusted_qc' for c in cols)
         + '&time>=' + t0 + BOX + '&pres<=2000&orderByClosest("platform_number,cycle_number,pres/25")')
    rows = get('ArgoFloats-synthetic-BGC', q)
    by = {}
    for r in rows:
        try: pid, cyc, p = r[0].strip(), int(r[1]), float(r[3])
        except ValueError: continue
        vals = []
        for j, k in enumerate(keys):
            v = fnum(r[4 + 2 * j]); qc = r[5 + 2 * j].strip()
            lo, hi = RANGE[k]
            vals.append(round(v, 3) if v is not None and qc in OKQ and lo <= v <= hi else None)
        if all(v is None for v in vals): continue
        cur = by.get(pid)
        if cur is None or cyc > cur[0]: by[pid] = cur = (cyc, [])
        if cyc == cur[0]: cur[1].append([round(p)] + vals)
    out = {}
    for pid, (cyc, P) in by.items():
        P.sort(); d = {'p': P}
        o2 = [(q[0], q[1]) for q in P if q[1] is not None]
        if o2:
            if o2[0][0] <= 20: d['o2s'] = round(o2[0][1])
            mn = min(o2, key=lambda x: x[1]); d['o2min'] = round(mn[1]); d['o2minz'] = mn[0]
        ch = [(q[0], q[2]) for q in P if q[2] is not None and q[0] <= 300]
        if ch: mx = max(ch, key=lambda x: x[1]); d['chlmax'] = round(max(mx[1], 0), 2); d['chlz'] = mx[0]
        n3 = [(q[0], q[3]) for q in P if q[3] is not None]
        nz = [z for z, v in n3 if v > 1]
        if n3 and nz and n3[0][0] <= 300: d['no3z'] = nz[0]          # only when the readings start shallow enough to see it                            # the nitracline: where the plankton's food starts (valid nitrate begins ~100 dbar)
        ph = [q[4] for q in P if q[4] is not None and q[0] <= 20]
        if ph: d['phs'] = round(ph[0], 3)
        if len(d) > 1: out[pid] = d
    return out


# THE GULF STREAM SLICE: New Jersey's shelf to Bermuda, the line the Oleander container ship has sampled since 1977 (crossing the Stream
# near 37 N); every profile of the last 45 days within 200 km of it, placed by how far along it lies, laid on a distance x depth grid by
# inverse-distance weighting along the line, with the gap to the nearest profile kept so the page can fade what is estimated.
SEC_A, SEC_B = (39.6, -73.9), (32.4, -64.8)
SEC_Z = [0, 10, 25, 50, 75, 100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 1000, 1200, 1500, 2000]


def section(t0):
    P = profiles(t0, '&latitude>=29&latitude<=42&longitude>=-77&longitude<=-62', 25, 100)
    R = 6371.0; la0 = math.radians((SEC_A[0] + SEC_B[0]) / 2)
    xy = lambda la, lo: (math.radians(lo) * math.cos(la0) * R, math.radians(la) * R)
    ax, ay = xy(*SEC_A); bx, by_ = xy(*SEC_B); L = math.hypot(bx - ax, by_ - ay); ux, uy = (bx - ax) / L, (by_ - ay) / L
    pts = []
    for (pid, cyc), (t, la, lo, rows) in P.items():
        x, y = xy(la, lo); d = (x - ax) * ux + (y - ay) * uy; c = -(x - ax) * uy + (y - ay) * ux
        if -50 <= d <= L + 50 and abs(c) <= 200 and len(rows) >= 5: pts.append((d, c, t, rows, pid))
    D = list(range(0, int(L) + 1, 20))
    TG, SG, NEAR = [], [], []
    for d in D:
        w = [(1.0 / ((d - p[0]) ** 2 + (p[1] / 2) ** 2 + 100.0), p) for p in pts]
        NEAR.append(round(min([abs(d - p[0]) for p in pts] or [999])))
        trow, srow = [], []
        for z in SEC_Z:
            for out_row, i in ((trow, 1), (srow, 2)):
                num = den = 0.0
                for wt, p in w:
                    v = at(p[3], max(z, p[3][0][0]) if z < p[3][0][0] and p[3][0][0] <= 15 else z, i)
                    if v is not None: num += wt * v; den += wt
                out_row.append(round(num / den, 2) if den else None)
        TG.append(trow); SG.append(srow)
    return {'a': SEC_A, 'b': SEC_B, 'km': round(L), 'd': D, 'z': SEC_Z, 'T': TG, 'S': SG, 'near': NEAR,
            'p': sorted([[round(p[0]), round(p[1]), p[2], p[4]] for p in pts])}


def main():
    now = datetime.now(timezone.utc)
    t = lambda d: (now - timedelta(days=d)).strftime('%Y-%m-%dT00:00:00Z')
    pos = get('ArgoFloats', 'platform_number,cycle_number,time,latitude,longitude&time>=' + t(60) + BOX + '&distinct()')
    fl = {}
    for r in pos:
        try: fl.setdefault(r[0].strip(), []).append((ts(r[2]), int(r[1]), float(r[3]), float(r[4])))
        except ValueError: continue
    P = profiles(t(15), BOX)
    newest = {}
    for (pid, cyc), v in P.items():
        if pid not in newest or cyc > newest[pid][0]: newest[pid] = (cyc, v[3])
    B = bgc(t(30))
    out, vel = [], []
    for pid, rows in fl.items():
        rows.sort(); tt, cyc, la, lo = rows[-1]
        trk = []
        for r in rows: trk += [round(r[3], 3), round(r[2], 3)]
        prof = newest.get(pid, (None, None))[1]
        prof1 = [[round(q[0]), None if q[1] is None else round(q[1], 2), None if q[2] is None else round(q[2], 3)] for q in prof] if prof and len(prof) >= 3 else None
        out.append([pid, round(la, 4), round(lo, 4), tt, cyc, trk, prof1, metrics(prof) if prof1 else {}, B.get(pid)])
        # the drift between two surfacings 5-15 days apart: the current at the parking depth (the hours at the surface add a little)
        for a, b in zip(rows, rows[1:]):
            dt = b[0] - a[0]
            if not (5 * 86400 <= dt <= 15 * 86400) or b[1] != a[1] + 1: continue
            dx = math.radians(b[3] - a[3]) * math.cos(math.radians((a[2] + b[2]) / 2)) * 6.371e8; dy = math.radians(b[2] - a[2]) * 6.371e8
            u, v = dx / dt, dy / dt
            if math.hypot(u, v) < 60: vel.append([round((a[3] + b[3]) / 2, 3), round((a[2] + b[2]) / 2, 3), round(u, 1), round(v, 1), pid])
    try: sec = section(t(45))
    except SystemExit: sec = None
    doc = {'at': int(time.time()), 'n': len(out), 'f': out, 'v': vel, 'sec': sec}
    path = os.path.join(tempfile.gettempdir(), 'argo_latest.json'); json.dump(doc, open(path, 'w'), separators=(',', ':'))
    print('floats', len(out), 'profiles', sum(1 for f in out if f[6]), 'bgc', sum(1 for f in out if f[8]), 'drifts', len(vel),
          'slice profiles', len(sec['p']) if sec else 0, 'bytes', os.path.getsize(path))
    if len(out) < 100: raise SystemExit('too few floats; keeping the published file')
    if '--dry' in sys.argv: return
    cache = 'public, max-age=3600'
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', path, 's3://%s/%s' % (BUCKET, KEY), '--content-type', 'application/json', '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', path, 'r2:%s/%s' % (BUCKET, KEY), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: application/json', '--header-upload', 'Cache-Control: ' + cache], check=True)
    print('uploaded', KEY)


if __name__ == '__main__':
    main()
