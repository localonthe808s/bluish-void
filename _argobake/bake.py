#!/usr/bin/env python3
"""ARGO FLOATS (2026-10-25, user: "can we add ARGO OCEAN DATA to water?"). Argo's ~4,000 robot floats drift about 3,300 ft down
and every ten days rise to the surface, measuring temperature and salinity on the way up from as deep as 6,500 ft. This bakes
the floats round North America (5-62 N, 140-40 W) from Ifremer's ERDDAP mirror of the Argo GDAC (keyless; no CORS, so baked):

    argo/latest.json  {"at": unix, "n": floats, "f": [[id, lat, lon, t (unix), cycle, track [lon, lat, ... newest last, 60 days],
                                                       profile [[dbar, degC|null, psu|null], ...] or null], ...]}

The newest profile per float comes from the last 15 days, one reading per 50 dbar (ERDDAP orderByClosest), QC flags 1-2 kept.
    python3 _argobake/bake.py [--dry]
Argo data: "These data were collected and made freely available by the International Argo Program and the national programs that
contribute to it (https://argo.ucsd.edu, https://www.ocean-ops.org)."
"""
import csv, io, json, os, subprocess, sys, tempfile, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

E = 'https://erddap.ifremer.fr/erddap/tabledap/ArgoFloats.csv?'
BOX = '&latitude>=5&latitude<=62&longitude>=-140&longitude<=-40'
BUCKET = 'bluishvoid-bg'; KEY = 'argo/latest.json'


def get(q, tries=4):
    url = E + urllib.parse.quote(q, safe='&=,')
    for k in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluishvoid.com argo bake'}), timeout=300).read().decode()
            return list(csv.reader(io.StringIO(b)))[2:]
        except Exception as e:
            print('retry', k, e); time.sleep(30 * (k + 1))
    raise SystemExit('ERDDAP did not answer')


def ts(s): return int(datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp())


def main():
    now = datetime.now(timezone.utc)
    t60 = (now - timedelta(days=60)).strftime('%Y-%m-%dT00:00:00Z'); t15 = (now - timedelta(days=15)).strftime('%Y-%m-%dT00:00:00Z')
    pos = get('platform_number,cycle_number,time,latitude,longitude&time>=' + t60 + BOX + '&distinct()')
    fl = {}
    for r in pos:
        try: fl.setdefault(r[0].strip(), []).append((ts(r[2]), int(r[1]), float(r[3]), float(r[4])))
        except ValueError: continue
    prof = get('platform_number,cycle_number,time,pres,temp,psal,temp_qc,psal_qc&time>=' + t15 + BOX
               + '&pres_qc="1"&orderByClosest("platform_number,cycle_number,pres/50")')
    pr = {}
    for r in prof:
        try: pid, cyc, p = r[0].strip(), int(r[1]), float(r[3])
        except ValueError: continue
        t = float(r[4]) if r[4] and r[6].strip() in ('1', '2') else None
        s = float(r[5]) if r[5] and r[7].strip() in ('1', '2') else None
        cur = pr.get(pid)
        if cur is None or cyc > cur[0]: pr[pid] = cur = (cyc, [])
        if cyc == cur[0] and (t is not None or s is not None): cur[1].append([round(p), None if t is None else round(t, 2), None if s is None else round(s, 3)])
    out = []
    for pid, rows in fl.items():
        rows.sort(); t, cyc, la, lo = rows[-1]
        trk = []
        for r in rows: trk += [round(r[3], 3), round(r[2], 3)]
        P = pr.get(pid); prof1 = sorted(P[1]) if P and len(P[1]) >= 3 else None
        out.append([pid, round(la, 4), round(lo, 4), t, cyc, trk, prof1])
    doc = {'at': int(time.time()), 'n': len(out), 'f': out}
    path = os.path.join(tempfile.gettempdir(), 'argo_latest.json'); json.dump(doc, open(path, 'w'), separators=(',', ':'))
    print('floats', len(out), 'with a profile', sum(1 for f in out if f[6]), 'bytes', os.path.getsize(path))
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
